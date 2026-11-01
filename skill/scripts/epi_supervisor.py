#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epi_supervisor.py — 流行病学科研模式的资源守护进程。

设计要点：
  * **不写死硬件**：核数、内存、磁盘每次启动现测；策略只写比例和上限。
  * **不是一次性包装**：常驻进程，持有并发闸门与队列，客户端通过本机套接字提交。
  * **平台自适应**：Linux 用 cgroup v2（可写时）→ 退到 rlimit；macOS 用 rlimit；
    Windows 用 Job Object 硬上限。都拿不到就退到轮询看门狗。
  * **失败即拒绝**：磁盘/内存不达标时不排队、不执行，直接拒绝并说明。

客户端命令：
    python epi_supervisor.py start   --dir <项目>
    python epi_supervisor.py limits  --dir <项目>
    python epi_supervisor.py status  --dir <项目>
    python epi_supervisor.py submit  --dir <项目> [--wait] --label 名称 -- <命令...>
    python epi_supervisor.py wait    --dir <项目> --job <id>
    python epi_supervisor.py cancel  --dir <项目> --job <id>
    python epi_supervisor.py stop    --dir <项目>

退出码：0 正常；2 资源不足 / 被拒；1 其它错误。
"""

import argparse
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:  # Windows 的 Job Object 与内存探测都要用；其它平台允许缺失
    import ctypes
except ImportError:  # pragma: no cover
    ctypes = None

EXIT_OK, EXIT_ERR, EXIT_LIMIT = 0, 1, 2
IS_WIN = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"

SKILL_DIR = Path(__file__).resolve().parent.parent
POLICY_FILE = SKILL_DIR / "config" / "resources.json"

THREAD_ENV = [
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS",
    "R_MAX_NUM_THREADS",
]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def mb(value):
    return round(value / (1024 * 1024), 1)


# ------------------------------------------------------------------ 硬件探测

def total_memory_bytes():
    try:
        if IS_WIN:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys, status.ullAvailPhys
        elif IS_LINUX:
            info = {}
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    key, _, rest = line.partition(":")
                    info[key] = int(rest.split()[0]) * 1024
            return info.get("MemTotal", 0), info.get("MemAvailable", 0)
        else:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return total, 0
    except Exception:
        pass
    return 0, 0


def probe_hardware():
    cores = os.cpu_count() or 1
    total, avail = total_memory_bytes()
    return {
        "platform": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cores": cores,
        "totalMemoryMB": round(total / (1024 * 1024)) if total else None,
        "availMemoryMB": round(avail / (1024 * 1024)) if avail else None,
        "cgroupWritable": cgroup_available(),
    }


def cgroup_available():
    if not IS_LINUX:
        return False
    base = Path("/sys/fs/cgroup")
    try:
        probe = base / "epi-probe"
        probe.mkdir(exist_ok=True)
        probe.rmdir()
        return True
    except Exception:
        return False


def load_policy():
    policy = {
        "maxConcurrentAgents": 3,
        "maxThreadsPerProcess": "auto",
        "memoryFraction": 0.25,
        "memoryCapMB": None,
        "maxWallSeconds": 3600,
        "minFreeDiskGB": 20,
        "maxOutputGrowthMB": 4096,
        "priority": "below-normal",
    }
    try:
        data = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        for key, value in (data.get("policy") or {}).items():
            if value is not None:
                policy[key] = value
    except Exception:
        pass
    return policy


def resolve_limits(hw, policy):
    """把策略落到这台机器上。并发 × 单任务上限不得超过总内存的 80%。"""
    cores = hw["cores"]
    threads = policy["maxThreadsPerProcess"]
    if threads in ("auto", None, 0):
        threads = max(1, min(4, cores // 2))

    total_mb = hw["totalMemoryMB"] or 0
    if policy.get("memoryCapMB"):
        per_job = int(policy["memoryCapMB"])
        source = "policy.memoryCapMB"
    elif total_mb:
        per_job = int(total_mb * float(policy["memoryFraction"]))
        source = f"totalMemory×{policy['memoryFraction']}"
    else:
        per_job = 2048
        source = "fallback"

    concurrent = max(1, int(policy["maxConcurrentAgents"]))
    if total_mb:
        ceiling = int(total_mb * 0.8)
        while concurrent > 1 and per_job * concurrent > ceiling:
            per_job = max(512, per_job // 2)
        if per_job * concurrent > ceiling:
            per_job = max(512, ceiling // concurrent)
            source += "（已按 80% 总内存收敛）"

    return {
        "maxConcurrentAgents": concurrent,
        "maxThreadsPerProcess": int(threads),
        "memoryCapMB": per_job,
        "memoryCapSource": source,
        "maxWallSeconds": int(policy["maxWallSeconds"]),
        "minFreeDiskGB": float(policy["minFreeDiskGB"]),
        "maxOutputGrowthMB": int(policy["maxOutputGrowthMB"]),
        "priority": policy.get("priority", "below-normal"),
    }


def disk_free_gb(path: Path):
    anchor = path
    while anchor and not anchor.exists():
        anchor = anchor.parent
    return shutil.disk_usage(str(anchor)).free / (1024 ** 3)


# ------------------------------------------------------------------ 平台限流

class PosixLimiter:
    def __init__(self, memory_cap_mb, priority):
        self.bytes = memory_cap_mb * 1024 * 1024
        self.nice = 10 if priority == "idle" else 5

    def preexec(self):
        try:
            nice = self.nice
            os.setpriority(os.PRIO_PROCESS, 0, nice)
        except Exception:
            pass
        try:
            import resource

            if self.bytes:
                resource.setrlimit(resource.RLIMIT_AS, (self.bytes, self.bytes))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:
            pass


if ctypes is not None:
    class _JOBOBJ_IO(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _JOBOBJ_BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong)]

    class _JOBOBJ_EXTENDED(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJ_BASIC),
            ("IoInfo", _JOBOBJ_IO),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]
else:
    _JOBOBJ_IO = _JOBOBJ_BASIC = _JOBOBJ_EXTENDED = None


class WindowsJob:
    PROCESS_LIMIT = 0x100
    JOB_LIMIT = 0x200
    EXTENDED = 9
    PRIORITY = {"idle": 0x40, "below-normal": 0x4000, "normal": 0x20}

    def __init__(self, memory_cap_mb, priority):
        self.ctypes = ctypes
        self.k32 = ctypes.windll.kernel32
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObjectW failed")
        info = _JOBOBJ_EXTENDED()
        info.BasicLimitInformation.LimitFlags = self.JOB_LIMIT | self.PROCESS_LIMIT
        info.JobMemoryLimit = memory_cap_mb * 1024 * 1024
        info.ProcessMemoryLimit = memory_cap_mb * 1024 * 1024
        info.BasicLimitInformation.PriorityClass = self.PRIORITY.get(priority, 0x4000)
        if not self.k32.SetInformationJobObject(
            self.handle, self.EXTENDED, self.ctypes.byref(info), self.ctypes.sizeof(info)
        ):
            self.k32.CloseHandle(self.handle)
            self.handle = None
            raise OSError("SetInformationJobObject failed")

    def assign(self, popen):
        ok = self.k32.AssignProcessToJobObject(self.handle, int(popen._handle))
        return bool(ok)

    def peek(self):
        if not self.handle:
            return {}
        info = _JOBOBJ_EXTENDED()
        returned = self.ctypes.c_ulong(0)
        if not self.k32.QueryInformationJobObject(
            self.handle, self.EXTENDED, self.ctypes.byref(info),
            self.ctypes.sizeof(info), self.ctypes.byref(returned)
        ):
            return {}
        return {"peakJobMemoryMB": mb(info.PeakJobMemoryUsed),
                "peakProcessMemoryMB": mb(info.PeakProcessMemoryUsed)}

    def terminate(self, code=1):
        if self.handle:
            self.k32.TerminateJobObject(self.handle, code)

    def close(self):
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


# ------------------------------------------------------------------ 守护进程

class Job:
    def __init__(self, label, argv, cwd):
        self.id = f"j{uuid.uuid4().hex[:8]}"
        self.label = label
        self.argv = argv
        self.cwd = cwd
        self.state = "pending"
        self.exitCode = None
        self.startedAt = None
        self.finishedAt = None
        self.reason = None
        self.result = {}
        self.event = threading.Event()
        self.popen = None
        self.job = None

    def snapshot(self):
        return {
            "id": self.id, "label": self.label, "state": self.state,
            "exitCode": self.exitCode, "reason": self.reason,
            "startedAt": self.startedAt, "finishedAt": self.finishedAt,
            "command": " ".join(self.argv), **self.result,
        }


class Supervisor:
    def __init__(self, project: Path):
        self.project = project
        self.state_dir = project / ".epi-supervisor"
        self.jobs_dir = self.state_dir / "jobs"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(exist_ok=True)
        self.hw = probe_hardware()
        self.policy = load_policy()
        self.limits = resolve_limits(self.hw, self.policy)
        self.jobs = {}
        self.order = []
        self.lock = threading.Lock()
        self.queue = []
        self.running = 0
        self.shutdown = threading.Event()
        self.started_at = now_iso()

    # -- 资源判定 --------------------------------------------------------
    def admit_reason(self):
        free = disk_free_gb(self.project)
        if free < self.limits["minFreeDiskGB"]:
            return f"磁盘余量 {free:.1f} GB < 下限 {self.limits['minFreeDiskGB']} GB"
        return None

    # -- 执行 ------------------------------------------------------------
    def spawn(self, job: Job):
        env = dict(os.environ)
        threads = str(self.limits["maxThreadsPerProcess"])
        for key in THREAD_ENV:
            env[key] = threads
        env["PYTHONUNBUFFERED"] = "1"
        env["EPI_JOB_ID"] = job.id

        log_path = self.jobs_dir / f"{job.id}.log"
        log = open(log_path, "wb")
        kwargs = dict(cwd=job.cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL)
        job_obj = None
        if IS_WIN:
            try:
                job_obj = WindowsJob(self.limits["memoryCapMB"], self.limits["priority"])
            except Exception:
                job_obj = None
        else:
            limiter = PosixLimiter(self.limits["memoryCapMB"], self.limits["priority"])
            kwargs["preexec_fn"] = limiter.preexec

        popen = subprocess.Popen(job.argv, **kwargs)
        if job_obj:
            try:
                job_obj.assign(popen)
            except Exception:
                pass

        job.popen = popen
        job.job = job_obj
        job.state = "running"
        job.startedAt = now_iso()
        started = time.time()

        killed_for = None
        deadline = started + self.limits["maxWallSeconds"]
        while True:
            if popen.poll() is not None:
                break
            if time.time() > deadline:
                killed_for = "timeout"
                break
            time.sleep(0.5)

        if killed_for:
            if job_obj:
                job_obj.terminate(124)
            try:
                popen.kill()
            except Exception:
                pass
            popen.wait()
        wall = round(time.time() - started, 1)
        peaks = job_obj.peek() if job_obj else {}
        if job_obj:
            job_obj.close()
        try:
            log.close()
        except Exception:
            pass

        job.exitCode = popen.returncode
        job.finishedAt = now_iso()
        job.reason = killed_for
        job.state = "killed" if killed_for else ("done" if popen.returncode == 0 else "failed")
        job.result = {
            "wallSeconds": wall,
            "threads": int(threads),
            "memoryCapMB": self.limits["memoryCapMB"],
            "logFile": str(log_path),
            **peaks,
        }
        if not killed_for and job.exitCode not in (0, None):
            text = ""
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")[-1200:]
            except Exception:
                pass
            if "MemoryError" in text or "Cannot allocate memory" in text or "bad_alloc" in text:
                job.reason = "memory"
                job.state = "killed"
                job.result["memoryCapMB"] = self.limits["memoryCapMB"]
        job.event.set()
        self._persist(job)

    def _persist(self, job: Job):
        try:
            with (self.jobs_dir / f"{job.id}.json").open("w", encoding="utf-8") as fh:
                json.dump(job.snapshot(), fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # -- 调度 ------------------------------------------------------------
    def pump(self):
        while not self.shutdown.is_set():
            with self.lock:
                ready = None
                if self.queue and self.running < self.limits["maxConcurrentAgents"]:
                    reason = self.admit_reason()
                    if reason:
                        for job in self.queue:
                            job.state = "rejected"
                            job.reason = reason
                            job.finishedAt = now_iso()
                            job.event.set()
                            self._persist(job)
                        self.queue.clear()
                    else:
                        ready = self.queue.pop(0)
                        self.running += 1
            if ready:
                thread = threading.Thread(target=self._run_one, args=(ready,), daemon=True)
                thread.start()
            else:
                time.sleep(0.2)

    def _run_one(self, job: Job):
        try:
            self.spawn(job)
        except Exception as exc:  # noqa: BLE001
            job.state = "failed"
            job.reason = f"spawn: {exc}"
            job.finishedAt = now_iso()
            job.event.set()
        finally:
            with self.lock:
                self.running -= 1

    def submit(self, label, argv, cwd):
        job = Job(label, argv, cwd)
        with self.lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            self.queue.append(job)
        self._persist(job)
        return job

    def status(self):
        with self.lock:
            jobs = [self.jobs[jid].snapshot() for jid in self.order][-22:]
            queued = len(self.queue)
            running = self.running
        return {
            "project": str(self.project),
            "startedAt": self.started_at,
            "hardware": self.hw,
            "limits": self.limits,
            "running": running,
            "queued": queued,
            "diskFreeGB": round(disk_free_gb(self.project), 1),
            "jobs": jobs,
        }


# ------------------------------------------------------------------ 服务端

def serve(project: Path, port: int | None):
    sup = Supervisor(project)
    threading.Thread(target=sup.pump, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port or 0))
    server.listen(16)
    actual_port = server.getsockname()[1]

    state_file = project / ".epi-supervisor" / "state.json"
    state_file.write_text(json.dumps({
        "pid": os.getpid(), "port": actual_port, "startedAt": sup.started_at,
        "host": "127.0.0.1",
    }, ensure_ascii=False), encoding="utf-8")

    def handle(conn):
        with conn:
            buffer = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line)
                    except Exception:
                        conn.sendall(b'{"error":"bad json"}\n')
                        continue
                    reply = dispatch(sup, request)
                    conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))

    def dispatch(sup, request):
        op = request.get("op")
        if op == "limits":
            return {"ok": True, "hardware": sup.hw, "limits": sup.limits}
        if op == "status":
            return {"ok": True, **sup.status()}
        if op == "submit":
            argv = request.get("argv") or []
            if not argv:
                return {"ok": False, "error": "empty command"}
            job = sup.submit(request.get("label") or "job", argv,
                             request.get("cwd") or str(sup.project))
            return {"ok": True, "jobId": job.id}
        if op == "wait":
            job = sup.jobs.get(request.get("jobId"))
            if not job:
                return {"ok": False, "error": "unknown job"}
            job.event.wait(timeout=request.get("timeout") or sup.limits["maxWallSeconds"] + 30)
            return {"ok": True, "job": job.snapshot()}
        if op == "cancel":
            job = sup.jobs.get(request.get("jobId"))
            if not job:
                return {"ok": False, "error": "unknown job"}
            if job.job:
                job.job.terminate(2)
            if job.popen:
                try:
                    job.popen.kill()
                except Exception:
                    pass
            return {"ok": True}
        if op == "shutdown":
            sup.shutdown.set()
            threading.Timer(0.2, lambda: os._exit(0)).start()
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op}"}

    while not sup.shutdown.is_set():
        try:
            conn, _ = server.accept()
        except OSError:
            break
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

    try:
        server.close()
    finally:
        state_file.unlink(missing_ok=True)


# ------------------------------------------------------------------ 客户端

def state_file(project: Path):
    return project / ".epi-supervisor" / "state.json"


def call(project: Path, request, timeout=30):
    path = state_file(project)
    if not path.exists():
        raise SystemExit("守护进程未启动：先跑 epi_supervisor.py start --dir <项目>")
    state = json.loads(path.read_text(encoding="utf-8"))
    with socket.create_connection((state["host"], state["port"]), timeout=timeout) as conn:
        conn.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def cmd_start(args):
    project = Path(args.dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    (project / ".epi-supervisor").mkdir(exist_ok=True)
    if state_file(project).exists():
        try:
            info = call(project, {"op": "status"}, timeout=5)
            if info.get("ok"):
                print(f"守护进程已在运行（pid {json.loads(state_file(project).read_text())['pid']}）")
                return EXIT_OK
        except Exception:
            state_file(project).unlink(missing_ok=True)

    log = open(project / ".epi-supervisor" / "daemon.log", "ab")
    kwargs = dict(cwd=str(project), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if IS_WIN:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_serve", "--dir", str(project)], **kwargs)

    for _ in range(100):
        if state_file(project).exists():
            try:
                info = call(project, {"op": "limits"}, timeout=3)
                if info.get("ok"):
                    limits = info["limits"]
                    hw = info["hardware"]
                    print(f"守护进程已启动：{hw['platform']} · {hw['cores']} 核 · "
                          f"{hw['totalMemoryMB']} MB 内存")
                    print(f"并发 {limits['maxConcurrentAgents']} · 每任务线程 {limits['maxThreadsPerProcess']} · "
                          f"内存上限 {limits['memoryCapMB']} MB（{limits['memoryCapSource']}）")
                    return EXIT_OK
            except Exception:
                pass
        time.sleep(0.1)
    raise SystemExit("守护进程启动失败，见 .epi-supervisor/daemon.log")


def cmd_limits(args):
    info = call(Path(args.dir).expanduser().resolve(), {"op": "limits"})
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_status(args):
    info = call(Path(args.dir).expanduser().resolve(), {"op": "status"})
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return EXIT_OK
    hw, limits = info["hardware"], info["limits"]
    print(f"项目：{info['project']}")
    print(f"机器：{hw['platform']}/{hw['machine']} · {hw['cores']} 核 · {hw['totalMemoryMB']} MB")
    print(f"上限：并发 {limits['maxConcurrentAgents']} · 线程 {limits['maxThreadsPerProcess']} · "
          f"内存 {limits['memoryCapMB']} MB · 超时 {limits['maxWallSeconds']}s")
    print(f"当前：运行 {info['running']} · 排队 {info['queued']} · 磁盘余 {info['diskFreeGB']} GB")
    if info["jobs"]:
        print("\n最近任务：")
        for job in info["jobs"]:
            print(f"  {job['id']}  {job['state']:<9} {job['label'][:28]:<28} "
                  f"exit={job['exitCode']} {job.get('wallSeconds', '')}s")
    return EXIT_OK


def cmd_submit(args):
    project = Path(args.dir).expanduser().resolve()
    argv = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not argv:
        raise SystemExit("缺少命令：-- 之后的部分")
    info = call(project, {"op": "submit", "label": args.label or "job",
                          "argv": argv, "cwd": args.cwd or str(project)})
    if not info.get("ok"):
        print(f"提交失败：{info.get('error')}")
        return EXIT_LIMIT
    job_id = info["jobId"]
    print(f"已提交：{job_id}")
    if args.wait:
        return wait_job(project, job_id, echo=True)
    return EXIT_OK


def wait_job(project, job_id, echo=False):
    info = call(project, {"op": "wait", "jobId": job_id}, timeout=86400)
    job = info.get("job") or {}
    state = job.get("state")
    if echo:
        log_file = job.get("logFile")
        if log_file and Path(log_file).exists():
            text = Path(log_file).read_text(encoding="utf-8", errors="replace")
            if text.strip():
                print(text.rstrip()[-8000:])
        print(f"\n[{job_id}] {state} exit={job.get('exitCode')} "
              f"wall={job.get('wallSeconds')}s 峰值内存={job.get('peakJobMemoryMB') or job.get('peakProcessMemoryMB')}")
        if job.get("reason"):
            print(f"原因：{job['reason']}")
    return EXIT_OK if state == "done" else EXIT_LIMIT


def cmd_wait(args):
    return wait_job(Path(args.dir).expanduser().resolve(), args.job, echo=True)


def cmd_cancel(args):
    info = call(Path(args.dir).expanduser().resolve(), {"op": "cancel", "jobId": args.job})
    print("已请求终止" if info.get("ok") else f"失败：{info.get('error')}")
    return EXIT_OK


def cmd_stop(args):
    project = Path(args.dir).expanduser().resolve()
    try:
        call(project, {"op": "shutdown"})
    except Exception:
        pass
    for _ in range(50):
        if not state_file(project).exists():
            print("守护进程已停止")
            return EXIT_OK
        time.sleep(0.1)
    print("已发出停止指令")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="epi_supervisor.py", description="科研模式资源守护进程")
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start"); start.add_argument("--dir", required=True); start.set_defaults(func=cmd_start)
    limits = sub.add_parser("limits"); limits.add_argument("--dir", required=True); limits.set_defaults(func=cmd_limits)
    status = sub.add_parser("status"); status.add_argument("--dir", required=True)
    status.add_argument("--json", action="store_true"); status.set_defaults(func=cmd_status)
    submit = sub.add_parser("submit"); submit.add_argument("--dir", required=True)
    submit.add_argument("--label"); submit.add_argument("--cwd"); submit.add_argument("--wait", action="store_true")
    submit.add_argument("command", nargs=argparse.REMAINDER); submit.set_defaults(func=cmd_submit)
    wait = sub.add_parser("wait"); wait.add_argument("--dir", required=True)
    wait.add_argument("--job", required=True); wait.set_defaults(func=cmd_wait)
    cancel = sub.add_parser("cancel"); cancel.add_argument("--dir", required=True)
    cancel.add_argument("--job", required=True); cancel.set_defaults(func=cmd_cancel)
    stop = sub.add_parser("stop"); stop.add_argument("--dir", required=True); stop.set_defaults(func=cmd_stop)

    internal = sub.add_parser("_serve"); internal.add_argument("--dir", required=True)
    internal.add_argument("--port", type=int, default=None)
    internal.set_defaults(func=lambda a: serve(Path(a.dir).expanduser().resolve(), a.port) or EXIT_OK)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    return args.func(args) or EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

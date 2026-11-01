#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epi_run.py — 流行病学统计科研模式的版本账本。

只依赖标准库。所有路径按传入的 --dir 解析。
命令：init / next / seal / verdict / check / deliver / status / log / diff

设计要点：
  * 每个版本目录自带完整产物（copy-forward），任一版本都能单独复现。
  * seal 冻结产物 sha256；review/ 不进哈希（审稿发生在 seal 之后）。
  * deliver 是门禁：未 seal、哈希不符、结论非 ACCEPT（MINOR 需 waiver）一律拒绝。
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = 1
LEDGER_NAME = ".epi-run.json"
CARRY_ITEMS = ["plan.md", "interpretation.md", "code", "results", "figures", "manuscript"]
VERSION_RE = re.compile(r"^v(\d{3,})$")
EXCLUDE_FILES = {"manifest.json", "meta.json"}
EXCLUDE_DIRS = {"review", "__pycache__", ".ipynb_checkpoints", ".git", ".Rproj.user"}

EXIT_OK, EXIT_ERR, EXIT_GATE = 0, 1, 2


class Fail(Exception):
    def __init__(self, msg, code=EXIT_ERR):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- 基础工具

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def dwidth(text: str) -> int:
    """终端显示宽度：CJK 全角算 2，其余算 1。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def dpad(text: str, width: int, right: bool = False) -> str:
    pad = max(0, width - dwidth(text))
    return (" " * pad + text) if right else (text + " " * pad)


def dtable(headers, rows):
    widths = [max([dwidth(str(h))] + [dwidth(str(r[i])) for r in rows]) for i, h in enumerate(headers)]
    out = ["  ".join(dpad(str(h), widths[i]) for i, h in enumerate(headers))]
    out.append("  ".join("-" * w for w in widths))
    for r in rows:
        out.append("  ".join(dpad(str(r[i]), widths[i],
                                   right=bool(re.fullmatch(r"[\d\-]+", str(r[i]))))
                             for i in range(len(headers))))
    return "\n".join(out)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def project_dir(raw: str) -> Path:
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        raise Fail(f"项目目录不存在：{p}")
    return p


def ledger_path(root: Path) -> Path:
    return root / LEDGER_NAME


def load_ledger(root: Path):
    path = ledger_path(root)
    if not path.exists():
        raise Fail(f"这不是一个已立项的项目（缺少 {LEDGER_NAME}）：{root}\n先运行：epi_run.py init --dir <目录> --title ...")
    data = read_json(path)
    if data.get("formatVersion") != FORMAT_VERSION:
        raise Fail(f"账本格式版本不支持：{data.get('formatVersion')}（期望 {FORMAT_VERSION}）")
    return data


def save_ledger(root: Path, data):
    data["updatedAt"] = now_iso()
    write_json(ledger_path(root), data)


def vdir(root: Path, vid: str) -> Path:
    if not VERSION_RE.match(vid):
        raise Fail(f"版本号格式错误：{vid}（应为 v001 这种三位数字）")
    p = root / vid
    if not p.is_dir():
        raise Fail(f"版本目录不存在：{p}")
    return p


def existing_versions(root: Path):
    out = []
    for child in root.iterdir():
        if child.is_dir():
            m = VERSION_RE.match(child.name)
            if m:
                out.append((int(m.group(1)), child.name))
    return sorted(out)


def read_meta(vpath: Path):
    meta = vpath / "meta.json"
    if not meta.exists():
        raise Fail(f"版本缺少 meta.json：{vpath}")
    return read_json(meta)


def collect_files(vpath: Path):
    """产物清单：排除 review/、meta.json、manifest.json 与常见缓存。"""
    files = {}
    for item in sorted(vpath.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(vpath)
        if rel.name in EXCLUDE_FILES:
            continue
        if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        files[rel.as_posix()] = sha256_file(item)
    return files


def collect_inputs(root: Path):
    """输入清单：<项目>/data/ 下所有文件，键为项目相对路径。

    输入不进版本目录（各版本共享同一份原始数据），但必须进 manifest——
    否则只凭版本目录无法判断复跑时输入有没有被换掉。
    """
    data_dir = root / "data"
    if not data_dir.is_dir():
        return {}
    inputs = {}
    for item in sorted(data_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(data_dir)
        if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        inputs[f"data/{rel.as_posix()}"] = sha256_file(item)
    return inputs


def manifest_aggregate(manifest):
    merged = dict(manifest.get("files") or {})
    merged.update(manifest.get("inputs") or {})
    return aggregate_hash(merged)


def aggregate_hash(files: dict) -> str:
    payload = "\n".join(f"{p}\0{h}" for p, h in sorted(files.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------- 命令实现

PLAN_TEMPLATE = """# 分析方案（{title}）

> 版本 {vid} · {stamp} · 主 agent 撰写
> 本文件是后续所有派发与验收的唯一依据。方案外的分析一律不许派。

## 1. 研究问题
{question}

## 2. 设计与人群
- 设计类型：（队列 / 病例对照 / 横断面 / 随机对照）
- 数据来源与时间窗：
- 纳入标准：
- 排除标准（逐条，用于复现剔除明细）：

## 3. 变量定义
| 角色 | 变量名 | 数据类型 | 定义/切点 | 单位 |
|---|---|---|---|---|
| 暴露 |  |  |  |  |
| 结局 |  |  |  |  |
| 协变量 |  |  |  |  |

## 4. 统计分析
- 主模型：（模型形式、链接函数、时间尺度）
- 调整集：（逐个变量，说明为何是混杂）
- 缺失处理：（完整病例 / 多重插补，插补模型）
- 效应量：（OR / HR / RR / 风险差）+ 95%CI 的计算方式
- 聚类/权重/重复测量：

## 5. 敏感性分析
逐条列出要跑的变体，以及"什么结果算稳健"。

## 6. 图表清单
| 编号 | 类型 | 内容 | 依赖的结果表 |
|---|---|---|---|
| T1 | 表 | 主模型效应量 | t1_main.csv |
| F1 | 图 |  |  |

## 7. 验收标准（可判定）
- [ ] 每个效应量有点估计 + 95%CI
- [ ] n 与剔除明细在 RUNLOG、表、图注三处一致
- [ ] 模型收敛，警告已记录
- [ ] （按本项目补充）

## 8. 禁项
- 不得自行更改模型/变量/切点
- 不得解读结果（解读权在主 agent）
- 不得把方案外分析塞进结果
"""


def cmd_init(args):
    root = Path(args.dir).expanduser().resolve()
    if (root / LEDGER_NAME).exists() and not args.force:
        raise Fail(f"该目录已立项：{root}\n要重建请加 --force（会覆盖账本，不删版本目录）")

    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "env").mkdir(exist_ok=True)

    v000 = root / "v000"
    v000.mkdir(exist_ok=True)
    plan = v000 / "plan.md"
    if not plan.exists() or args.force:
        plan.write_text(
            PLAN_TEMPLATE.format(title=args.title, question=args.question or "（待补充）",
                                 vid="v000", stamp=now_iso()),
            encoding="utf-8",
        )

    meta = {
        "id": "v000", "kind": "plan", "note": "立项：分析方案",
        "createdAt": now_iso(), "sealed": False, "sealedAt": None,
        "aggregate": None, "fileCount": None, "verdict": None,
        "delivered": False, "deliveredAt": None, "waiver": None,
    }
    write_json(v000 / "meta.json", meta)

    ledger = {
        "formatVersion": FORMAT_VERSION,
        "runId": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "title": args.title, "question": args.question or "",
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "root": str(root), "latest": "v000", "versions": [],
    }
    save_ledger(root, ledger)
    cmd_log(argparse.Namespace(dir=str(root)))
    print(f"立项完成：{root}")
    print(f"方案版：{v000 / 'plan.md'}")
    print("下一步：填 plan.md → epi_run.py next --note \"...\" 建产物版本")


def cmd_next(args):
    root = project_dir(args.dir)
    ledger = load_ledger(root)
    versions = existing_versions(root)
    next_num = (versions[-1][0] + 1) if versions else 1
    new_id = f"v{next_num:03d}"
    new_dir = root / new_id
    if new_dir.exists():
        raise Fail(f"版本目录已存在：{new_dir}")

    prev = root / versions[-1][1] if versions else None

    # 开新版本前先就地封存上一版（若还没封），保证历史版本不可回写。
    sealed_prev = None
    if prev is not None and collect_files(prev):
        sealed_prev = _do_seal(root, prev, no_inputs=args.no_inputs)

    new_dir.mkdir(parents=True)
    carried = []
    if prev is not None:
        for name in CARRY_ITEMS:
            src = prev / name
            if not src.exists():
                continue
            dst = new_dir / name
            if src.is_dir():
                if not any(src.rglob("*")):     # 空目录不算承接
                    continue
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            carried.append(name)

    for d in ("code", "results", "figures"):
        (new_dir / d).mkdir(exist_ok=True)

    meta = {
        "id": new_id, "kind": "artifact", "note": args.note,
        "createdAt": now_iso(), "sealed": False, "sealedAt": None,
        "aggregate": None, "fileCount": None, "verdict": None,
        "delivered": False, "deliveredAt": None, "waiver": None,
        "carriedFrom": prev.name if prev else None, "carried": carried,
    }
    write_json(new_dir / "meta.json", meta)

    ledger["latest"] = new_id
    ledger.setdefault("versions", []).append(new_id)
    save_ledger(root, ledger)
    cmd_log(argparse.Namespace(dir=str(root)))

    if args.json:
        print(json.dumps({"version": new_id, "dir": str(new_dir), "carried": carried,
                          "sealedPredecessor": (prev.name if sealed_prev else None)},
                         ensure_ascii=False))
    else:
        if sealed_prev:
            print(f"已自动封存上一版 {prev.name}（{len(sealed_prev['files'])} 个产物）——历史不可回写")
        print(f"新版本：{new_id}  {new_dir}")
        print(f"承接：{', '.join(carried) if carried else '（无，首个别版本）'}")
        print(f"说明：{args.note}")
    return EXIT_OK


def _do_seal(root: Path, vpath: Path, force=False, no_inputs=False):
    """封存一个版本。已封存且未 force 时返回 None（不重复封）。"""
    meta = read_meta(vpath)
    if meta.get("sealed") and not force:
        return None
    files = collect_files(vpath)
    if not files:
        raise Fail(f"{vpath.name} 没有任何产物文件，不封存")
    inputs = {} if no_inputs else collect_inputs(root)
    manifest = {
        "version": vpath.name, "sealedAt": now_iso(), "algo": "sha256",
        "aggregateRule": "sha256( join('\\n', sorted(f'{path}\\0{hash}' for path,hash in files ∪ inputs)) )",
        "files": files, "inputs": inputs,
    }
    manifest["aggregate"] = manifest_aggregate(manifest)
    write_json(vpath / "manifest.json", manifest)

    meta.update({
        "sealed": True, "sealedAt": manifest["sealedAt"],
        "aggregate": manifest["aggregate"], "fileCount": len(files),
        "inputCount": len(inputs),
    })
    write_json(vpath / "meta.json", meta)
    return manifest


def cmd_seal(args):
    root = project_dir(args.dir)
    version = args.version or load_ledger(root).get("latest")
    vpath = vdir(root, version)
    meta = read_meta(vpath)
    if meta.get("sealed") and not args.force:
        raise Fail(f"{version} 已封存（{meta.get('sealedAt')}）。确需重封请加 --force")

    manifest = _do_seal(root, vpath, force=args.force, no_inputs=args.no_inputs)
    cmd_log(argparse.Namespace(dir=str(root)))
    print(f"已封存 {version}：{len(manifest['files'])} 个产物 + {len(manifest['inputs'])} 个输入文件，"
          f"聚合哈希 {manifest['aggregate'][:16]}…")
    print("下一步：派审稿人 → verdict")
    return EXIT_OK


def _diff_map(expected: dict, actual: dict):
    changed = sorted(p for p in expected.keys() & actual.keys() if expected[p] != actual[p])
    added = sorted(actual.keys() - expected.keys())
    removed = sorted(expected.keys() - actual.keys())
    return changed, added, removed


def cmd_check(args):
    root = project_dir(args.dir)
    version = args.version or load_ledger(root).get("latest")
    vpath = vdir(root, version)
    manifest_path = vpath / "manifest.json"
    if not manifest_path.exists():
        if args.json:
            print(json.dumps({"version": version, "sealed": False, "ok": False}, ensure_ascii=False))
        else:
            print(f"{version} 未封存（没有 manifest.json），无法校验完整性")
        return EXIT_GATE

    expected = read_json(manifest_path)
    exp_files = expected.get("files") or {}
    changed, added, removed = _diff_map(exp_files, collect_files(vpath))

    exp_inputs = expected.get("inputs")
    if exp_inputs is None:      # 旧版 manifest 没有固定输入，跳过输入校验
        in_changed, in_added, in_removed = [], [], []
    else:
        in_changed, in_added, in_removed = _diff_map(exp_inputs, collect_inputs(root))

    ok = not (changed or added or removed or in_changed or in_added or in_removed)

    if args.json:
        print(json.dumps({
            "version": version, "sealed": True, "ok": ok,
            "changed": changed, "added": added, "removed": removed,
            "inputs": {"changed": in_changed, "added": in_added, "removed": in_removed},
        }, ensure_ascii=False))
        return EXIT_OK if ok else EXIT_GATE

    if ok:
        print(f"{version} 完整性校验通过（{len(exp_files)} 个产物"
              f"{'' if exp_inputs is None else f' + {len(exp_inputs)} 个输入'}，聚合哈希一致）")
        return EXIT_OK

    print(f"{version} 完整性校验失败：")
    for label, items in (("被修改", changed), ("新增", added), ("缺失", removed),
                         ("输入被改", in_changed), ("输入新增", in_added), ("输入缺失", in_removed)):
        for p in items:
            print(f"  [{label}] {p}")
    print("提示：封存后改动必须升新版本 —— next → 重做 → seal")
    return EXIT_GATE


def _review_counts(reviewer_path: Path):
    try:
        data = read_json(reviewer_path)
        if not isinstance(data, dict):
            return None, None, None
        return (data.get("verdict"),
                len(data.get("major") or []),
                len(data.get("minor") or []))
    except Exception:
        return None, None, None


def cmd_verdict(args):
    root = project_dir(args.dir)
    version = args.version or load_ledger(root).get("latest")
    vpath = vdir(root, version)
    meta = read_meta(vpath)

    verdict = args.verdict.upper()
    reviewer_rel = None
    rev_verdict = major_n = minor_n = None
    if args.reviewer:
        rp = Path(args.reviewer)
        if not rp.is_absolute():
            rp = (vpath / rp) if not str(args.reviewer).startswith(str(vpath)) else rp
        rp = rp.expanduser().resolve()
        if not rp.exists():
            raise Fail(f"审稿文件不存在：{rp}")
        reviewer_rel = rp.relative_to(vpath).as_posix() if vpath in rp.parents else str(rp)
        rev_verdict, major_n, minor_n = _review_counts(rp)
        if rev_verdict and str(rev_verdict).upper() != verdict:
            print(f"警告：审稿文件里的 verdict={rev_verdict}，与 --verdict {verdict} 不一致；以 --verdict 为准",
                  file=sys.stderr)

    meta["verdict"] = {
        "verdict": verdict, "summary": args.summary or "",
        "reviewer": reviewer_rel, "at": now_iso(),
        "majorCount": major_n, "minorCount": minor_n,
        "reviewerVerdict": rev_verdict,
    }
    write_json(vpath / "meta.json", meta)
    cmd_log(argparse.Namespace(dir=str(root)))
    print(f"{version} 结论：{verdict}" + (f"（{args.summary}）" if args.summary else ""))
    if verdict in ("MAJOR", "REJECT"):
        print("下一步：回到方案 → next 升版本 → 重派 → 重审")
    elif verdict == "MINOR":
        print("下一步：修完升版本重审；或 deliver --waiver \"...\" 带条件交付（需用户确认）")
    else:
        print("下一步：epi_run.py deliver --version " + version)
    return EXIT_OK


def cmd_deliver(args):
    root = project_dir(args.dir)
    version = args.version or load_ledger(root).get("latest")
    vpath = vdir(root, version)
    meta = read_meta(vpath)

    if not meta.get("sealed"):
        raise Fail(f"{version} 未封存，不能交付。先 seal", EXIT_GATE)
    check = cmd_check(argparse.Namespace(dir=str(root), version=version, json=False))
    if check != EXIT_OK:
        raise Fail(f"{version} 封存后被改动，不能交付。请升新版本重做", EXIT_GATE)

    verdict = (meta.get("verdict") or {}).get("verdict")
    if not verdict:
        raise Fail(f"{version} 没有审稿结论，不能交付", EXIT_GATE)
    if verdict == "MINOR" and not args.waiver:
        raise Fail(f"{version} 结论为 MINOR，必须指定 --waiver \"未修项说明\" 才能交付", EXIT_GATE)
    if verdict in ("MAJOR", "REJECT"):
        raise Fail(f"{version} 结论为 {verdict}，禁止交付", EXIT_GATE)

    meta.update({"delivered": True, "deliveredAt": now_iso(), "waiver": args.waiver})
    write_json(vpath / "meta.json", meta)

    ledger = load_ledger(root)
    ledger["latestDelivered"] = version
    save_ledger(root, ledger)
    cmd_log(argparse.Namespace(dir=str(root)))
    print(f"已交付：{version}")
    if args.waiver:
        print(f"带条件交付，未修项：{args.waiver}")
    return EXIT_OK


def cmd_status(args):
    root = project_dir(args.dir)
    ledger = load_ledger(root)
    rows = []
    for num, name in existing_versions(root):
        try:
            meta = read_meta(root / name)
        except Fail:
            rows.append({"version": name, "kind": "?", "sealed": False, "verdict": None,
                         "delivered": False, "files": None, "note": "（meta.json 缺失）"})
            continue
        rows.append({
            "version": name, "kind": meta.get("kind"), "sealed": bool(meta.get("sealed")),
            "verdict": (meta.get("verdict") or {}).get("verdict"),
            "delivered": bool(meta.get("delivered")),
            "files": meta.get("fileCount"), "note": meta.get("note") or "",
        })

    if args.json:
        print(json.dumps({"title": ledger.get("title"), "latest": ledger.get("latest"),
                          "versions": rows}, ensure_ascii=False, indent=2))
        return EXIT_OK

    print(f"项目：{ledger.get('title')}（{ledger.get('runId')}）")
    print(f"目录：{root}")
    print(f"最新版本：{ledger.get('latest')}\n")
    table = dtable(
        ["版本", "类型", "文件", "封存", "审稿", "交付", "说明"],
        [[r["version"], str(r["kind"]), str(r["files"] or "-"),
          "yes" if r["sealed"] else "-", str(r["verdict"] or "-"),
          "YES" if r["delivered"] else "-", r["note"][:38]] for r in rows],
    )
    print(table)
    return EXIT_OK


def cmd_log(args):
    root = project_dir(args.dir)
    ledger = load_ledger(root)
    lines = [
        f"# 版本沿革 — {ledger.get('title', '')}",
        "",
        f"- Run ID：`{ledger.get('runId')}`",
        f"- 立项：{ledger.get('createdAt')}",
        f"- 研究问题：{ledger.get('question') or '（未填写）'}",
        f"- 最新版本：`{ledger.get('latest')}`",
        "",
        "| 版本 | 类型 | 创建时间 | 文件数 | 封存 | 审稿结论 | 交付 | 说明 |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for _, name in existing_versions(root):
        try:
            meta = read_meta(root / name)
        except Fail:
            lines.append(f"| {name} | ? | ? | - | - | - | - | meta.json 缺失 |")
            continue
        verdict = (meta.get("verdict") or {}).get("verdict") or "-"
        created = (meta.get("createdAt") or "")[:19].replace("T", " ")
        delivered = "已交付" + ("（带条件）" if meta.get("waiver") else "") if meta.get("delivered") else "-"
        lines.append(
            f"| {name} | {meta.get('kind', '?')} | {created} | {meta.get('fileCount') or '-'} | "
            f"{'yes' if meta.get('sealed') else '-'} | {verdict} | {delivered} | "
            f"{str(meta.get('note') or '').replace('|', '/')} |"
        )
    lines.append("")
    lines.append("> 本文件由 `epi_run.py log` 生成，手改会被下次生成覆盖。")
    (root / "HISTORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not getattr(args, "quiet", False):
        print(f"已写入 {root / 'HISTORY.md'}")
    return EXIT_OK


def cmd_diff(args):
    root = project_dir(args.dir)
    a, b = vdir(root, args.v1), vdir(root, args.v2)

    def snapshot(p: Path):
        mf = p / "manifest.json"
        if mf.exists():
            return read_json(mf).get("files", {})
        return collect_files(p)

    fa, fb = snapshot(a), snapshot(b)
    added = sorted(fb.keys() - fa.keys())
    removed = sorted(fa.keys() - fb.keys())
    changed = sorted(k for k in fa.keys() & fb.keys() if fa[k] != fb[k])

    print(f"{args.v1} → {args.v2}")
    for label, items in (("新增", added), ("删除", removed), ("修改", changed)):
        print(f"\n{label} {len(items)} 个：")
        for p in items:
            print(f"  {p}")
    if not (added or removed or changed):
        print("\n两版本产物完全一致")
    return EXIT_OK


def cmd_archive(args):
    """归档代替删除：移到 _archive/<时间戳>/ 并写清单，原路径不再保留。"""
    root = project_dir(args.dir)
    items = [item.strip() for item in (args.items or "").split(",") if item.strip()]
    if not items:
        raise Fail("--items 不能为空（逗号分隔的项目内相对路径）")
    if not args.reason:
        raise Fail("必须写 --reason，说明为什么归档")

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = root / "_archive" / stamp
    target.mkdir(parents=True, exist_ok=True)

    moved = []
    for raw in items:
        source = Path(raw)
        if not source.is_absolute():
            source = root / raw
        source = source.expanduser().resolve()
        if not source.exists():
            print(f"跳过（不存在）：{source}")
            continue
        if source != root and root not in source.parents:
            raise Fail(f"拒绝归档项目外的路径：{source}")
        rel = source.relative_to(root)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        size = (sum(f.stat().st_size for f in source.rglob("*") if f.is_file())
                if source.is_dir() else source.stat().st_size)
        shutil.move(str(source), str(destination))
        moved.append({"from": rel.as_posix(),
                      "to": destination.relative_to(root).as_posix(),
                      "bytes": size, "isDir": destination.is_dir()})

    manifest = {
        "at": now_iso(), "reason": args.reason,
        "archiveDir": target.relative_to(root).as_posix(), "items": moved,
    }
    write_json(target / "MANIFEST.json", manifest)
    print(f"已归档 {len(moved)} 项 → {target.relative_to(root).as_posix()}")
    for item in moved:
        print(f"  {item['from']}  ({item['bytes']} bytes)")
    print("没有删除任何东西。要还原就按清单原路移回。")
    return EXIT_OK


def cmd_where(args):
    """打印技能目录与各处配置的绝对路径——跨机器、跨目录时先跑这个，别猜。"""
    root = Path(__file__).resolve().parent.parent
    print(f"技能目录  : {root}")
    print(f"技能父目录: {root.parent}        # 预设 customSkillDirs 应指向这里")
    print(f"路由文件  : {root / 'config' / 'roles.json'}")
    print(f"资源策略  : {root / 'config' / 'resources.json'}")
    for name in ("executor", "plotter", "reviewer"):
        print(f"角色契约  : {root / 'roles' / (name + '.md')}")
    print(f"账本脚本  : {root / 'scripts' / 'epi_run.py'}")
    print(f"守护进程  : {root / 'scripts' / 'epi_supervisor.py'}")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog="epi_run.py", description="流行病学统计科研模式 · 版本账本")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="立项：建账本 + v000 方案版")
    s.add_argument("--dir", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--question", default="")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("next", help="开新版本（copy-forward 上一版产物）")
    s.add_argument("--dir", required=True)
    s.add_argument("--note", required=True)
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-inputs", action="store_true", help="开新版时不固定输入哈希（不推荐）")
    s.set_defaults(func=cmd_next)

    s = sub.add_parser("seal", help="冻结当前版本产物与输入数据的哈希")
    s.add_argument("--dir", required=True)
    s.add_argument("--version", default=None)
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-inputs", action="store_true", help="不固定 <项目>/data/ 下的输入文件（不推荐）")
    s.set_defaults(func=cmd_seal)

    s = sub.add_parser("verdict", help="记录审稿结论")
    s.add_argument("--dir", required=True)
    s.add_argument("--version", default=None)
    s.add_argument("--verdict", required=True,
                   choices=["ACCEPT", "MINOR", "MAJOR", "REJECT",
                            "accept", "minor", "major", "reject"])
    s.add_argument("--reviewer", default=None)
    s.add_argument("--summary", default="")
    s.set_defaults(func=cmd_verdict)

    s = sub.add_parser("check", help="校验封存后是否被改动")
    s.add_argument("--dir", required=True)
    s.add_argument("--version", default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("deliver", help="交付（门禁：ACCEPT）")
    s.add_argument("--dir", required=True)
    s.add_argument("--version", default=None)
    s.add_argument("--waiver", default=None)
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("status", help="查看版本状态")
    s.add_argument("--dir", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("log", help="重写 HISTORY.md")
    s.add_argument("--dir", required=True)
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("diff", help="比较两版本产物")
    s.add_argument("--dir", required=True)
    s.add_argument("v1")
    s.add_argument("v2")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("archive", help="归档（代替删除）")
    s.add_argument("--dir", required=True)
    s.add_argument("--items", required=True, help="逗号分隔的项目内相对路径")
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_archive)

    s = sub.add_parser("where", help="打印技能目录与配置的绝对路径")
    s.set_defaults(func=cmd_where)

    return p


def main(argv=None):
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or EXIT_OK
    except Fail as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return EXIT_ERR
    except Exception as exc:  # noqa: BLE001
        print(f"未预期错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERR


if __name__ == "__main__":
    sys.exit(main())

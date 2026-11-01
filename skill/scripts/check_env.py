#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_env.py — 流行病学统计科研模式 · 分析环境预检。

在主 agent 制定分析方案**之前**跑一次，确认这个解释器能不能支撑本轮要做的分析。
退出码：0 = 达标；2 = 缺关键依赖（不要开工，先补环境）；1 = 探测失败。

用法：
    python check_env.py                 # 检查当前解释器
    python check_env.py --python <路径>  # 检查指定解释器
    python check_env.py --json
"""

import argparse
import json
import subprocess
import sys

PROBE = r"""
import importlib.util, json, sys
mods = ["numpy", "pandas", "scipy", "statsmodels", "matplotlib",
        "seaborn", "sklearn", "lifelines", "pingouin"]
out = {"version": sys.version.split()[0], "executable": sys.executable, "modules": {}}
for m in mods:
    spec = importlib.util.find_spec(m)
    ver = None
    if spec is not None:
        try:
            mod = __import__(m)
            ver = getattr(mod, "__version__", "unknown")
        except Exception:
            ver = "import-error"
    out["modules"][m] = ver
print(json.dumps(out))
"""

CORE = ["numpy", "pandas"]
STATS = ["scipy", "statsmodels"]
PLOT = ["matplotlib"]
SURV = ["lifelines"]

ROLE = {
    "numpy": "数值基础",
    "pandas": "数据整理",
    "scipy": "分布/检验/优化",
    "statsmodels": "回归、GLM、Cox、边际效应",
    "matplotlib": "作图（执行者与画图者都需要）",
    "seaborn": "作图便捷层（可选）",
    "sklearn": "预测建模、交叉验证（可选）",
    "lifelines": "生存分析（KM/Cox，可选 statsmodels 也可）",
    "pingouin": "常用统计便捷封装（可选）",
}


def probe(python: str):
    proc = subprocess.run(
        [python, "-c", PROBE],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "无输出").strip()[:800])
    line = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if not line:
        raise RuntimeError("探测脚本没有返回 JSON：" + proc.stdout[:400])
    return json.loads(line[-1])


def main():
    ap = argparse.ArgumentParser(description="检查流行病学分析环境")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--need", default="stats,plot",
                    help="需要的能力，逗号分隔：core,stats,plot,survival（默认 stats,plot）")
    args = ap.parse_args()

    try:
        info = probe(args.python)
    except Exception as exc:  # noqa: BLE001
        print(f"探测失败：{exc}", file=sys.stderr)
        print(f"解释器：{args.python}", file=sys.stderr)
        return 1

    mods = info["modules"]
    have = {m for m, v in mods.items() if v not in (None, "import-error")}
    need = {n.strip() for n in args.need.split(",") if n.strip()}

    missing = []
    if "core" in need:
        missing += [m for m in CORE if m not in have]
    if "stats" in need:
        missing += [m for m in STATS if m not in have]
    if "plot" in need:
        missing += [m for m in PLOT if m not in have]
    if "survival" in need:
        missing += [m for m in SURV if m not in have]
    missing = sorted(set(missing))

    ok = not missing
    if args.json:
        print(json.dumps({"python": info["executable"], "version": info["version"],
                          "modules": mods, "need": sorted(need),
                          "missing": missing, "ok": ok}, ensure_ascii=False, indent=2))
        return 0 if ok else 2

    print(f"解释器：{info['executable']}")
    print(f"版本：  {info['version']}")
    print(f"需要：  {', '.join(sorted(need))}\n")
    for m in sorted(mods):
        v = mods[m]
        mark = "OK  " if v not in (None, "import-error") else "MISS"
        note = "" if v not in (None, "import-error") else f"  ← {ROLE.get(m, '')}"
        if v == "import-error":
            note = "  ← 装了但导入失败，环境损坏"
        print(f"  [{mark}] {m:<12} {str(v or '-'):<10}{note}")

    if ok:
        print("\n环境达标，可以开工。")
        return 0

    print(f"\n缺少：{', '.join(missing)}")
    print("不要开工。先让执行者处理环境，并把版本写进项目的 env/ 目录：")
    print(f'  "{info["executable"]}" -m venv .venv')
    print("  .venv\\Scripts\\python -m pip install " + " ".join(missing))
    print("\n若 pip 直接退出（提示配置含无效字符 / 代理连不上）：")
    print("  - 检查 PIP_CONFIG_FILE 指向的 ini 是否含非 ASCII 注释，改成英文或删注释")
    print("  - 检查其中 proxy 指向的本地代理是否在线")
    print("  - 或用 --python 指向另一个已装好科学栈的解释器（如用户自己的 conda 环境）")
    return 2


if __name__ == "__main__":
    sys.exit(main())

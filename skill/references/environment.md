# 环境预检与依赖

## 一、开工前的第 0 步

在写分析方案之前，主 agent 先确认解释器能不能支撑本轮分析：

```powershell
python <技能目录>/scripts/check_env.py --python <解释器路径>
python <技能目录>/scripts/check_env.py --python <解释器路径> --json
```

退出码 `0` 才能开工；`2` 表示缺关键依赖，此时**不要写方案、不要派分析任务**，先让执行者把环境弄好，版本写进项目 `env/`。

## 二、什么必须装库，什么可以手算

| 分析 | 允许的实现 |
|---|---|
| OLS 线性回归 | numpy 闭式解 `(X'X)⁻¹X'y` + 解析标准误，**精确**，允许 |
| t 检验、卡方、2×2 表、Fisher | 公式精确，允许用 numpy/pandas |
| 描述统计、率、标准化率、直接标化 | 精确，允许 |
| Logistic / 泊松 / 负二项 / 条件 logistic | **必须** statsmodels（或 R） |
| Cox、参数生存、竞争风险、KM + log-rank | **必须** lifelines / statsmodels / R |
| 限制性立方样条、GAM、倾向评分匹配/加权 | **必须** 相应库 |
| 多重插补、bootstrap（>1000 次可自行实现但需说明算法） | 优先库；自实现须写清算法与种子 |
| 作图 | **必须** matplotlib（或 R）；不许用 Excel 截图与 ASCII 图 |

**硬规则**：需要迭代拟合或专门算法的方法，不许用"看起来差不多"的手写近似冒充。手写 IRLS 跑 logistic 即使收敛，也不得进结果表——没有经过检验的实现不能背书。

## 三、依赖缺失时的处理顺序

1. **换解释器**：用户可能有装好科学栈的 conda 环境。问一句比装半天快。
2. **建项目级虚拟环境**：

   ```powershell
   <python> -m venv <项目>/.venv
   <项目>/.venv/Scripts/python -m pip install statsmodels matplotlib scipy lifelines
   ```

   装完把版本写进 `<项目>/env/pip-freeze.txt` 与 `<项目>/env/python.txt`。
3. **装不上就停下问用户**，不要用未经验证的实现顶上。

## 四、本机已知问题（2026-11 实测）

| 现象 | 原因 | 处理 |
|---|---|---|
| `python` 命令返回 9009 | `C:\Users\Lenovo\AppData\Local\Microsoft\WindowsApps\python.exe` 是 0 字节的应用商店占位符 | 用 `py -3`，或 `load_workspace_dependencies` 返回的内置解释器路径 |
| 内置解释器 3.12.14 只有 numpy 2.3.5 + pandas 3.0.1 | 未装 scipy / statsmodels / matplotlib / sklearn / lifelines | 见上文第三节 |
| `python -m pip --version` 只打印 `Configuration file contains invalid cp936 characters in D:\AnacondaData\pip\pip.ini` 并退出 2 | `PIP_CONFIG_FILE` 指向的 ini 里有中文注释，pip 在 cp936 下解析失败 | 把注释改成英文或删除注释；另注意该 ini 的 `proxy = http://127.0.0.1:10808` 需要 v2rayN 在线 |
| `py -3`（3.14）有 numpy 但没有 pandas | 与内置解释器不同的环境 | 不要混用；本项目统一用一个解释器，路径写进 `env/python.txt` |

环境一旦确定，**整轮分析不得中途换解释器**——版本号的意义就在于可复现。

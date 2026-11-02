---
name: epi-research-mode
description: 流行病学统计科研模式：主 agent 统筹分析、制定计划、下达任务、验收与核查、分配算力；子 agent 只有三种——执行者（写码/跑数/出表）、画图者（科研规范作图）、审稿人（独立审稿，出接收/小修/大修/拒稿结论）。每轮闭环产生一个新版本号，历史版本全部保留、可溯源。适用于：队列/病例对照/横断面分析、回归与生存建模、倾向评分与敏感性分析、论文图表生产、方法与结果核查、稿件统计自查、复现既有分析。用户提到流行病学分析、科研统计、跑回归、做论文图、审稿意见、返修时使用。读一个文件、改一行代码、纯方法问答不启用。
---

# 流行病学统计科研模式

> 本技能**只由「流行病学科研模式」Agent 预设挂载**（不在任何全局技能根里）。
> 其他模式看不到它——在别的会话里做流行病学分析，请先切到该预设。

一句话：**主 agent 只做判断，子 agent 只做执行，审稿人只说结论，每个版本都留档。**

## 1. 启用边界

- **启用**：从原始数据走到可提交结果，需要 ≥2 类角色协作（分析 + 执行 + 出图 + 审稿）。
- **不启用**：纯问答、读单个文件、改一行代码、解释一个统计概念——主 agent 直接做。
- 用户说"别派、我自己写"时，退化为单人模式，但仍然保留版本留档与自查清单。

## 2. 角色与硬边界

| 角色 | 职责 | 绝对不做 |
|---|---|---|
| **主 agent**（本会话模型） | 研究设计、统计策略、模型选择、结果解读、因果措辞、拆解派发、验收核查、算力分配 | 不写非平凡分析代码；不把自己的判断外包给子 agent |
| **执行者 executor** | 把给定方案变成代码、跑数、出表、出中间结果 | 不解读结果、不改方案、不自选统计方法、不写讨论/结论 |
| **画图者 plotter** | 按科研规范把数据变成图 | 不动数值、不删点、不为美观截轴不标注、不自造数据 |
| **审稿人 reviewer** | 独立审查统计/图/逻辑/可复现性，出四档结论 | 不改任何文件、不给"差不多就行"、不审自己参与的产物 |

- 主 agent 亲手写代码上限约 10 行，且只能用于**不影响结论的一次性检查**（看数据结构、核一个数字）。凡是进入结果的代码，一律派执行者。
- **分析权不可下放**：效应方向、大小、显著性、与假设的关系、能否说因果——全部由主 agent 判断。执行者的报告里出现"结果显著说明……"即为越界。
- 子 agent 不能再派生下级（delegation depth 已到底），不要设计三级流水线。

## 3. 主 agent 的职责顺序

0. **开工序列**（缺一步后面全是返工）：
   1. **环境**：`py -3 <技能目录>/scripts/check_env.py`。缺 statsmodels/matplotlib 先补，别硬上。
   2. **账本**：`py -3 <技能目录>/scripts/epi_run.py status --dir <项目>`。没立项就 `init`；
      项目里已有自己的 `v-2.0` / `v-3.0` 这类目录时，`init` 后按 `references/versioning.md` 第五节
      把现状纳入 `v001` 作为基线——**不要拿既有的业务目录名当本模式的版本号**。
   3. **路由**：读 `<技能目录>/config/roles.json`。这是**技能目录下的绝对路径，不是项目目录**。
      读不到就用 `inherit`（不传 provider/model）继续干，并在交付说明里记一句降级——不要为此停工等用户。
   → 三件事做完，才写 `plan.md`、`next` 开版本、派第一个任务。
1. **分析**：研究问题、人群、暴露/结局/协变量、设计类型、目标 estimand、偏倚来源。
2. **计划**：写进版本目录的 `plan.md`——模型、变量、调整集、缺失处理、图表清单、**验收标准**（可判定的，不是"结果合理"）。
3. **下达**：每个任务给出输入路径、参数、输出路径、验收标准、禁项（见 `references/dispatch-scripts.md`）。
4. **验收**：产物真存在、能跑、图与数一致、数与方案一致（见 `references/acceptance-checklist.md`）。
5. **核查**：随机抽一个数字回算；检查表头、单位、样本量、缺失是否对得上；确认版本哈希未被改动。
6. **算力分配**：本轮用几个并发、各角色挂哪个模型、重型计算是否转后台（`run_in_background`）。预算在派发前声明，不超 `config/roles.json` 的并发上限。

## 4. 一轮循环与版本号

```
v000 方案版（只有 plan.md）
   ↓  派发 → 执行者 / 画图者
vNNN 产物版（code/ results/ figures/）→ 主 agent 验收 + 解读 → seal
   ↓  审稿人独立审
review.json：ACCEPT / MINOR / MAJOR / REJECT
   ↓
ACCEPT → deliver（交付）
MINOR  → 主 agent 判断：修 → 下一版本；或带 waiver 交付（须用户点头）
MAJOR/REJECT → 回第 3 步，下一版本
```

版本规则（硬性）：

- **一次"派发→返回→主 agent 验收"= 一个新版本号**，`v001, v002, ...` 只增不减。
- **审稿不是新版本**，结论挂在被审版本上。
- **已创建版本不得回写**：勘误、修订、补分析一律进新版本。`next` 会自动封存上一版，
  之后再改旧版本会被 `check` 报"被修改"——历史是证据，不是草稿。
- **已交付版本永不覆盖**。用户提新要求 → 新版本，老版本原地保留。
- 每个版本目录**自带完整可运行产物**（新版本从前一版本 copy-forward 后修改），任一版本都能单独打开复现。
  但**承接来的 `results/RUNLOG.md` 记录的是上一版的运行**：要么在本版重跑，要么在 RUNLOG 首行
  写明"承接自 vNNN、未在本版重跑"，否则溯源是假的。
- 原始数据放项目根 `data/`，只读，不进版本目录——保证各版本看到的是同一份输入（`seal` 会把它的哈希钉进 manifest）。

## 5. 派发

**默认用 `epi_dispatch`**：它按角色读 `<技能目录>/config/roles.json`，把**模型和推理强度**一起施加到子 agent。

```json
{ "role": "reviewer", "label": "审稿人·v003", "prompt": "<完整任务>", "schema": { } }
```

- `role` 只能是 `executor` / `plotter` / `reviewer`；模型、推理强度在「设置 → 科研模式」里配，存进 roles.json。
- 给了 `schema` 就返回校验过的对象（审稿人必须给）；不给就返回文本。
- **并行 = 把多次 `epi_dispatch` 放进同一条消息**一起调用。
- 角色契约让子 agent 自己 `read "<技能目录>/roles/<role>.md"`，不要贴全文——单一事实来源，改了立刻生效。

**什么时候改用 `workflow` 的 `agent()`**：需要阶段图、几十个成员的 fan-out、或 `pipeline` 分阶段时。
它支持 `provider`/`model` 与 `label`/`phase`，但**明确拒绝 `reasoningEffort`**（传了会报错），
只能跑会话默认档位。两者可混用：大规模 fan-out 用 workflow，逐轮把关用 `epi_dispatch`。

- 模型 id 用 provider 的注册名，不是显示名——`deepseek-flash` 的显示名是 `DeepSeek-V4.1-Flash`。
- 路由缺失或模型名写错时：回退到 `inherit` 继续，并在交付说明里写明降级，不要停工。
- 角色契约不必贴全文：子 agent 有 `read`，让它 `read "<技能目录>/roles/executor.md"` 并遵守，单一事实来源、改了立刻生效。
  任务短、要省一次工具调用时才整段贴进 prompt——**两种方式选一种，不要各写一份**。
- 需要多轮追问、或要用户在界面里看进度的单角色任务，可用 `subagent`，但它**不能指定模型**（继承主 agent）。
- 给子 agent 的 prompt 必须自包含：目标、数据路径、参数、输出路径、验收标准、禁项、返回格式。

## 6. 审稿闸门

| 结论 | 含义 | 主 agent 的动作 |
|---|---|---|
| `ACCEPT` | 可直接交付 | `deliver` |
| `MINOR` | 不影响结论的表述/格式/标注问题 | 修 → 下一版本；或记 waiver 交付（须用户确认） |
| `MAJOR` | 统计方法、图与数不一致、结论越界 | 回主 agent 重修方案 → 下一版本 → 重审 |
| `REJECT` | 设计或数据不支持该结论 | 停止推进，向用户说明根因与可选方案 |

- 只有 `ACCEPT` 能自动交付。`MINOR` 带 waiver 交付时必须写明未修项。
- 审稿人给 `ACCEPT` 前必须亲自打开图与表，不能只读主 agent 的摘要。

## 7. 版本与溯源命令

脚本：`scripts/epi_run.py`（Python 3.9+，纯标准库）。路径按本技能目录解析。
Windows 上 `python` 可能是不存在的商店占位符——用 `py -3` 或 `load_workspace_dependencies` 返回的解释器，并在整轮里保持不变。

```bash
PY="py -3"   # Windows；macOS/Linux 用 python3；或 load_workspace_dependencies 给的解释器路径
$PY scripts/epi_run.py init  --dir <项目目录> --title "..." --question "..."
$PY scripts/epi_run.py next  --dir <项目目录> --note "改了什么"      # 打印新版本号；顺带封存上一版
$PY scripts/epi_run.py seal  --dir <项目目录>                        # 冻结产物+输入哈希（验收后、审稿前）
$PY scripts/epi_run.py verdict --dir <项目目录> --version v003 --verdict MAJOR --reviewer v003/review/review.json
$PY scripts/epi_run.py check --dir <项目目录>                        # 检测 seal 后产物或输入被改动
$PY scripts/epi_run.py deliver --dir <项目目录> --version v003       # 只放行 ACCEPT（MINOR 需 --waiver）
$PY scripts/epi_run.py status --dir <项目目录> [--json]
$PY scripts/epi_run.py log   --dir <项目目录>                        # 重写 HISTORY.md
$PY scripts/epi_run.py diff  --dir <项目目录> v002 v003
```

顺序不能乱：**验收 → seal → 审稿 → verdict → deliver**。`deliver` 会拒绝未 seal、哈希不符、非 ACCEPT 的版本。
`seal` 同时固定 `<项目>/data/` 下输入的哈希，所以"输入被换掉"也会被 `check` 抓到。

## 8. 红线

- 没派过子 agent 就说派过；编造文件路径、数字、审稿意见。
- 让执行者写结论、让画图者调数据、让审稿人改文件。
- 用未 seal 的图/表交付；审稿后偷偷改文件而不升版本（`check` 能发现）。
- 观察性研究写因果措辞；只报 p 值不报效应量与区间；多重比较不声明。
- 把"结果不显著"包装成"无效应"。

## 9. 资源与删除（硬约束）

**重计算一律走守护进程**，不许 `python xxx.py` 裸跑：

```bash
PY="py -3"; D=<技能目录>/scripts
$PY $D/epi_supervisor.py start  --dir <项目>
$PY $D/epi_supervisor.py submit --dir <项目> --wait --label "执行者·v003·主模型" -- python code/run_main.py
$PY $D/epi_supervisor.py status --dir <项目>
```

- 上限由守护进程按**本机实测**的核数/内存/磁盘推算；策略只在 `config/resources.json` 里写比例，换机器不用改。
- 进程内强制：单任务内存硬上限（Windows Job Object / POSIX rlimit）、墙钟超时、BLAS 线程数、并发闸门。
- 退出码 `2` = 撞上限或被拒（磁盘不足、内存撞顶、超时）。**降规模或分批，不要原样重试。**
- RUNLOG 必须记 job id、峰值内存、墙钟——否则审稿人无法判断结果是不是在受限环境下跑出来的。

**删除一律改归档**：

```bash
$PY $D/epi_run.py archive --dir <项目> --items "results/old.csv" --reason "被 t2 取代"
```

- 本模式挂了删除守卫（工具层拦截，不是口头约定）：`rm -rf`、`Remove-Item`、`del /s`、`git clean -fdx`、`shutil.rmtree`、`DROP TABLE` 等直接被拒。
- 归档到 `_archive/<时间戳>/` 并写 `MANIFEST.json`，可原路还原。
- 确实必须删：请用户亲手做。绕道（改权限、换解释器、写脚本删）同样算违规。

## 10. 资源索引

| 需要时读 | 文件 |
|---|---|
| 环境预检、依赖缺失、什么能手算 | `references/environment.md` |
| 资源上限与守护进程 | `scripts/epi_supervisor.py`、`config/resources.json` |
| 派发单模板 + 可直接复制的 workflow 脚本 | `references/dispatch-scripts.md` |
| 审稿任务模板 + 结论处理 | `references/review-contract.md` |
| seal 前的验收清单 | `references/acceptance-checklist.md` |
| 目录结构、命令细节、迁移旧项目 | `references/versioning.md` |
| 角色预置提示词 | `roles/executor.md`、`roles/plotter.md`、`roles/reviewer.md` |
| 模型与并发路由 | 「设置 → 科研模式」页面（写入 `config/roles.json`） |
| 角色预置提示词 | 同一页面可直接编辑 `roles/*.md` |
| 运行进度 | `workflow` 调用会渲染成对话里的 **运行工作流** 节点：可分阶段、看每个成员的成功/失败、用时与产出 |
| 作图规范细节 | 加载 `nature-figure` 技能（子 agent 也可自行加载） |
| 统计报告规范 | 加载 `nature-statistics` 技能 |
| 文献检索 / 参考文献核对 | 加载 `pubmed`、`nature-ref-verifier` 技能 |
| 英文稿件格式与投稿 | 加载 `academic-manuscript-style` 技能 |

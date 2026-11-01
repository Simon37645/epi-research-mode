# 版本、目录与溯源

## 一、目录结构

```
<项目>/
  .epi-run.json          # 项目账本：runId、标题、版本列表、最新版本
  HISTORY.md             # 人读溯源表（脚本生成，不要手改）
  data/                  # 原始数据，只读，不进版本目录
  env/                   # 可选：sessionInfo.txt / pip freeze / 软件版本
  v000/                  # 方案版
    plan.md
    meta.json
  v001/                  # 产物版
    plan.md              # 本轮方案（copy-forward 后可改）
    code/                # 代码
    results/             # 表 + RUNLOG.md + 中间数据
    figures/             # PNG + PDF + 图注
    review/              # 审稿意见（seal 后写入，不进哈希）
    meta.json            # 本版本元信息
    manifest.json        # seal 时生成的哈希清单
  v002/
    ...
```

- 新版本由 `next` 从前一版本 **copy-forward**（`code/ results/ figures/ manuscript/ plan.md`），
  所以每个版本自成一套可复现产物；`data/` 永远在项目根共享。
- `review/` 不进 `manifest.json`——审稿发生在 seal 之后。
- `meta.json` / `manifest.json` / `.epi-run.json` 本身也不算产物哈希。

## 二、版本号语义

| 版本 | 含义 |
|---|---|
| `v000` | 方案版：只有 `plan.md`（研究问题、设计、模型、变量、图表清单、验收标准）。不跑代码。 |
| `v001..vNNN` | 产物版：一次"派发 → 子 agent 返回 → 主 agent 验收"的闭环结果。 |
| 审稿 | **不产生版本**，结论挂在被审版本上。 |
| 修完再派 | 产生 `v(N+1)`。 |
| 交付 | 在某个 `ACCEPT` 版本上标记，永不覆盖。 |

用户后来提新需求 → 新版本，而不是改已交付版本。已交付版本是历史证据。

## 三、命令

```bash
P=<项目目录>
S="<本技能目录>/scripts/epi_run.py"

python $S init    --dir $P --title "PM2.5 与糖尿病发病" --question "长期 PM2.5 暴露是否与 2 型糖尿病发病风险相关"
python $S next    --dir $P --note "主模型按方案重跑；补齐年龄调整"
python $S seal    --dir $P
python $S verdict --dir $P --version v002 --verdict MAJOR --reviewer $P/v002/review/review.json
python $S check   --dir $P
python $S deliver --dir $P --version v003
python $S status  --dir $P [--json]
python $S log     --dir $P
python $S diff    --dir $P v001 v002
```

### 语义

- `init`：建账本 + `v000/plan.md` 模板 + `data/` 目录。已有账本时拒绝覆盖（除非 `--force`）。
- `next`：**先把上一版就地封存**（若还没封），再建新版本；版本号 = 当前最大 + 1，
  copy-forward 非空产物（`plan.md`、`interpretation.md`、`code/`、`results/`、`figures/`、`manuscript/`，
  空目录不算承接），写 `meta.json`，打印新版本路径。
  自动封存是为了兑现"已创建版本不得回写"——想改旧版必须先升版本。
- `seal`：对版本目录内所有产物（除 `review/`、`meta.json`、`manifest.json`）算 sha256，
  **同时把 `<项目>/data/` 下的输入文件按 `data/<相对路径>` 固定进 `manifest.inputs`**，
  写 `manifest.json`（含 `aggregateRule` 原文），在 `meta.json` 记 `sealed: true` + 汇总哈希。
  输入不在版本目录里（各版本共享同一份原始数据），但必须被固定——否则只凭版本目录无法判断
  复跑时输入有没有被换掉。`--no-inputs` 可关闭，不推荐。
- `verdict`：记结论 + 摘要 + 审稿文件路径；重写 `HISTORY.md`。可以改判（后写覆盖前写）。
- `check`：重算产物与输入的哈希并与 `manifest.json` 比对，报"seal 后被改动""输入被改"的文件。未 seal 时提示未冻结。
- `deliver`：**门禁**——要求已 seal、`check` 通过、`verdict` 为 `ACCEPT`；
  `MINOR` 必须带 `--waiver "..."`（waiver 文本进 HISTORY）。`MAJOR`/`REJECT` 一律拒绝。
- `diff`：比较两版本文件清单（新增/删除/修改），用于写 `next --note`。

## 四、为什么这样设计

- **copy-forward 而不是增量补丁**：论文级产物小（csv/png/pdf），自带完整快照才能"打开任一版本就能复现"，
  不用去追"这个版本基于哪个版本"。
- **seal 哈希**：审稿人评的是某个确定状态。审稿后偷偷改文件是这类工作流最常见的失信方式，
  哈希能让它立刻暴露。
- **deliver 门禁**：把"必须通过审稿"从口头约定变成脚本约束。人不遵守流程时，脚本会拦。
- **HISTORY.md**：一行一版本，写清改了什么、谁审的、结论是什么，交付时直接附给用户。

## 五、把已有分析纳入版本流

1. `epi_run.py init --dir <旧项目> --title ...`（会建 `data/`，把原始数据挪进去或软链接）。
2. 手工建 `v001/`，把既有 `code/ results/ figures/` 移进去。
3. 补齐 `v001/plan.md`——**从代码倒推方案**，写明现在实际用的模型与变量。
4. `seal` → 送审一次，作为基线。之后所有改动走 `next`。

倒推方案时如果发现代码与声称的方法不一致，那本身就是第一个 major，先修再 seal。

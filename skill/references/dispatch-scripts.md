# 派发单与调度脚本

主 agent 下达命令只有一个合法通道：`workflow` 工具的 `agent()`。
它能在**每一次调用**上指定 provider / model，这是本运行时里唯一能按角色换模型的地方。

## 一、派发前：读路由、定预算

1. 读 `<技能目录>\config\roles.json`（技能目录，不是项目目录），
   取本轮要用的 `provider` / `model` / `concurrencyMax`（UI 里改过就是最新的，别用记忆里的值）。
   文件不存在就用 `inherit` 继续，别停工。
2. 声明本轮预算（写进回给用户的话里）：几个并发、哪些角色、是否转后台。
3. `agent()` 拿到的是**全新上下文**，看不到本会话、看不到 `roles.json`、看不到上一个子 agent 说了什么。
   所以脚本里的模型名要**写字面量**，任务要**自包含**（路径用绝对路径或相对版本目录的明确相对路径）。

## 二、派发单（每个子 agent 的 prompt 必须含这七项）

```
1 目标：一句话说清产出什么（可判定的名词，不是"分析一下"）
2 输入：数据/中间结果的绝对路径 + 关键列名 + 单位
3 参数：模型、变量、分组、调整集、参考点、随机种子 —— 全部由主 agent 指定，子 agent 不得改
4 输出：目录 + 文件名 + 格式（图 300/600 dpi PNG + 矢量 PDF）；重计算一律经守护进程 submit，回报 job id、峰值内存、墙钟
5 验收标准：怎样算做对了（可核对的具体条件）
6 禁项：不改设计、不扩范围、不解读结果、有疑点即停
7 返回格式：按 roles/<role>.md 里规定的格式
```

反面例子：*"帮我做个回归看看 PM2.5 对糖尿病的影响"* —— 没有结局定义、没有调整集、没有输出路径、没有验收标准。
正面例子：*"用 `<vdir>/data/cohort.csv` 拟合 logistic 回归：结局 `dm`（0/1），暴露 `pm25`（μg/m³，连续），调整 `age`（连续）、`sex`（0/1）、`bmi`（连续）。完整病例分析，剔除明细写进 RUNLOG。输出 `<vdir>/results/t1_main.csv`：列名 `term, OR, lcl, ucl, p, n`。验收：n 与 RUNLOG 一致、无收敛警告、每个 term 的 CI 不跨 1 也要如实报出。"*

## 二·五、让进度看得懂

`workflow` 调用在对话里渲染成「运行工作流」节点：每个 `agent()` 是一行成员，`label` 是成员名，`phase()` 是分组，成功/失败和用时都在行上。所以：

- `label` 统一写成 `<角色>·<版本>·<子任务>`，例如 `执行者·v003·主模型`、`审稿人·v003`。别用 `agent-1`。
- 先 `phase("方案")` / `phase("执行")` / `phase("作图")` / `phase("审稿")` 分组，一轮循环的先后顺序在节点里就看得见。
- `meta.phases` 里声明这几个阶段标题，跑之前界面就能显示计划。
- 一个阶段内并行的成员，用 `parallel()` 发，别串行 await。

## 三、派发方式

**默认用 `epi_dispatch`**（带推理强度），参数就是一段 JSON：

```json
{ "role": "executor", "label": "执行者·v003·主模型", "prompt": "<七项派发单>" }
```

- 并行：把多次 `epi_dispatch` 放进**同一条消息**。
- 审稿人必须给 `schema`，拿结构化结论。
- 模型与强度来自 `<技能目录>/config/roles.json`，改设置页即生效。
- 下面这些 `workflow` 模板只用于**大规模 fan-out / 需要阶段图**：它接受 `provider`/`model`、`label`、`phase`，
  但**拒绝 `reasoningEffort`**，跑会话默认档位。

## 四、workflow 模板（fan-out / 阶段图）

**角色提示词怎么给**：子 agent 有 `read` 工具。优先让它自己读角色文件（单一事实来源，改了立刻生效）：

```
第一步：read "<技能目录>/roles/executor.md" 并全文遵守——那是你的行为契约。
```

任务短、要省一次工具调用时，才把角色文件全文直接贴进 prompt。两种都行，**不要两种各写一份**。

### A. 单执行者

```js
phase("执行");
const ROLE = String.raw`<技能目录>\roles\executor.md`;
const task = `第一步：read "${ROLE}" 并全文遵守它（你的行为契约）。

# 本轮任务
1 目标：...
2 输入：...
3 参数：...
4 输出：...
5 验收标准：...
6 禁项：...
7 返回格式：按角色文件第 5 节`;

const out = await agent(task, {
  label: "executor-v003-main",
  provider: "deepseek-account",
  model: "deepseek-flash",
});
return out;
```

### B. 多个独立分析（并行执行者）

彼此不依赖才并行。有依赖就顺序 await。

```js
phase("并行执行");
const ROLE = String.raw`<技能目录>\roles\executor.md`;
const head = `第一步：read "${ROLE}" 并全文遵守它（你的行为契约）。\n\n# 本轮任务\n`;
const jobs = [
  { label: "exec-v003-t1", task: "主模型……" },
  { label: "exec-v003-t2", task: "敏感性分析 1……" },
  { label: "exec-v003-t3", task: "敏感性分析 2……" },
];
const results = await parallel(
  jobs.map((j) => () =>
    agent(head + j.task, {
      label: j.label,
      provider: "deepseek-account",
      model: "deepseek-flash",
    })
  )
);
return jobs.map((j, i) => ({ label: j.label, ok: results[i] != null, report: results[i] }));
```

### C. 画图者（在结果落盘之后）

```js
phase("作图");
const ROLE = String.raw`<技能目录>\roles\plotter.md`;
const task = `第一步：read "${ROLE}" 并全文遵守它（你的行为契约）。

# 本轮任务
1 目标：图 1 森林图（主模型 OR）
2 输入：<vdir>/results/t1_main.csv、<vdir>/plan.md 图清单第 1 条
3 参数：横轴 log OR，参考线 1，按暴露三分位分组，误差线 95%CI
4 输出：<vdir>/figures/fig1_forest.png + .pdf，源数据与图注同目录
5 验收标准：图内数值与 csv 一致（抽查 3 点）；轴标签含单位；n 与 RUNLOG 一致
6 禁项：不改数值、不改分组、不截轴不标注
7 返回格式：按角色文件第 6 节`;

const out = await agent(task, {
  label: "plotter-v003",
  provider: "deepseek-account",
  model: "deepseek-flash",
});
return out;
```

### D. 审稿人（必须给 schema）

```js
phase("审稿");
const ROLE = String.raw`<技能目录>\roles\reviewer.md`;
const brief = `第一步：read "${ROLE}" 并全文遵守它（你的行为契约）。

# 审稿任务
版本目录（绝对路径）：<vdir>
分析方案：<vdir>/plan.md
待审产物：<vdir>/results/、<vdir>/figures/、<vdir>/code/
结论写到：<vdir>/review/review.json 与 review.md
注意：只依据文件，不依据任何自述。图表必须实际打开。`;

const schema = {
  type: "object",
  properties: {
    verdict: { type: "string", enum: ["ACCEPT", "MINOR", "MAJOR", "REJECT"] },
    summary: { type: "string" },
    major: { type: "array", items: { type: "object", properties: {
      id: { type: "string" }, surface: { type: "string" }, location: { type: "string" },
      problem: { type: "string" }, fix: { type: "string" } },
      required: ["id", "surface", "location", "problem", "fix"], additionalProperties: false } },
    minor: { type: "array", items: { type: "object", properties: {
      id: { type: "string" }, surface: { type: "string" }, location: { type: "string" },
      problem: { type: "string" }, fix: { type: "string" } },
      required: ["id", "surface", "location", "problem", "fix"], additionalProperties: false } },
    unverifiable: { type: "array", items: { type: "object", properties: {
      item: { type: "string" }, reason: { type: "string" } },
      required: ["item", "reason"], additionalProperties: false } },
  },
  required: ["verdict", "summary", "major", "minor", "unverifiable"],
  additionalProperties: false,
};

let review = await agent(brief, {
  label: "reviewer-v003",
  provider: "deepseek-account",
  model: "deepseek-reasoner",
  schema,
});

// 路由失败（模型名写错）时返回 null：回退到主 agent 的模型重试一次
if (!review) {
  review = await agent(brief, { label: "reviewer-v003-fallback", schema });
}
return review;
```

## 四、失败处理

| 现象 | 处理 |
|---|---|
| `agent()` 返回 `null` | 该路由或调用失败。回退到 `inherit`（不传 provider/model）重试一次；仍失败则本轮作废，向用户报告 |
| 子 agent 返回 `STATUS: STOPPED` | **不要**重派同一个任务。由主 agent 决定方案怎么改，改完再派 |
| 返回内容越界（做了解释/改了方法） | 记为该轮不合格，重派并在任务里点名禁止 |
| 子 agent 说文件已写但不存在 | 视为未完成；主 agent 亲自 `glob` 确认，再决定 |
| 同一问题连续 3 轮 MAJOR | 停下，向用户说明卡点与可选方案，不继续烧算力 |

## 五、上下文预算

- 只把与本任务相关的方案段落贴给子 agent，不要贴整份 `plan.md`。
- 不要把上一个子 agent 的错误猜想贴给下一个——那会污染。
- 子 agent 的返回只保留结论与路径，过程细节留在它自己的会话里。

# 流行病学统计科研模式 · Epidemiology Research Mode

一个给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的**Agent 预设**：把流行病学/统计分析的科研流程固化成一个可复现、可审稿、可溯源的工作方式。

不是"让模型帮你跑个回归"，而是**主 agent 出方案、派活、验收；子 agent 只执行；审稿人独立把关；每一轮都留版本**。

## 它解决什么问题

科研分析里最常见的失败不是算错，是：算不回来、改过的东西找不回、结论比数据走得远、以及"这个数到底哪来的"。

这套模式把四件事变成硬机制：

| 问题 | 机制 |
|---|---|
| 算不回来 | 每个版本目录自带完整可跑产物；`seal` 冻结产物与输入数据的哈希 |
| 改了什么不知道 | `next` 开新版本时自动封存上一版；改旧版本会被 `check` 抓到 |
| 结论越界 | 审稿人独立出四档结论，`deliver` 只放行 ACCEPT |
| 机器被跑死 | 资源守护进程按本机实测值加硬上限，超了整组终止 |

## 三个角色

| 角色 | 做什么 | 绝不做什么 |
|---|---|---|
| **主 agent** | 研究设计、统计策略、结果解读、验收核查、算力分配 | 不写进入结果的分析代码 |
| **执行者** | 写码、跑数、出表、出中间结果 | 不解读结果、不改方案、不自选统计方法 |
| **画图者** | 按期刊规范作图并自检 | 不动数值、不删点、不截轴不标注 |
| **审稿人** | 独立审查统计/图/逻辑/可复现性 | 不改文件、不给"差不多就行" |

## 两条硬约束

1. **资源受管**：所有重计算经守护进程提交，进程内强制内存上限（Windows Job Object / POSIX rlimit）、墙钟超时、BLAS 线程数、并发闸门。上限由机器实测推算，策略只写比例。
2. **删除即归档**：`epi_run.py archive` 移到 `_archive/<时间戳>/` 并写清单；工具守卫直接拒绝 `rm -rf`、`Remove-Item`、`del /s`、`git clean -fdx`、`shutil.rmtree`、`DROP TABLE` 之类命令。

## 仓库结构

```
skill/                    技能本体（协议 + 角色契约 + 脚本）
  SKILL.md
  config/roles.json       角色 → 模型路由（可在设置页编辑）
  config/resources.json   资源策略（比例，不是绝对数值）
  roles/{executor,plotter,reviewer}.md
  references/*.md         派发契约、审稿契约、验收清单、版本规范
  scripts/epi_run.py      版本账本 + 归档
  scripts/epi_supervisor.py 资源守护进程
  scripts/check_env.py    环境预检
plugins/
  epi-research-preset/    把模式做成可选的一档 Agent 预设
  epi-mode-ui/            设置页：每个角色的模型与提示词
  epi-guard/              删除守卫（只由预设挂载）
```

## 安装

需要 DSH Desktop 或带 Web UI 的 dsh，以及 Python 3.9+。

1. **放技能**（放在任何**非默认技能根**的目录，这样只有本模式能看到它）：

   ```bash
   mkdir -p ~/.dsh/epi-mode/skills
   cp -r skill ~/.dsh/epi-mode/skills/epi-research-mode
   python ~/.dsh/epi-mode/skills/epi-research-mode/scripts/epi_run.py where
   ```

   `where` 会打印技能父目录，下一步要用。

2. **改一处路径**：打开 `plugins/epi-research-preset/cordis.patch.yml`，把 `customSkillDirs` 换成上一步打印的**技能父目录**（绝对路径）。

3. **装三个插件**（DSH 里用插件管理器，或命令行）：

   ```
   plugin_manager install_bundle <绝对路径>/plugins/epi-research-preset
   plugin_manager install_bundle <绝对路径>/plugins/epi-mode-ui
   plugin_manager install_bundle <绝对路径>/plugins/epi-guard
   ```

4. **把守卫收进模式内**（否则它全局生效）：

   ```
   plugin_manager set_plugin include:dsh-epi-guard enabled:false
   ```

   预设里那一行仍会挂载它，于是只有科研模式有守卫。

5. 刷新页面 → 设置 → Agent 预设，选「流行病学科研模式」开新会话。

## 用法

进模式后直接说清楚研究任务即可，技能会按关键词自动加载：

> 用流行病学统计科研模式分析 `data/cohort.csv`：研究问题是「长期 PM2.5 暴露是否与成人 log-CRP 水平独立相关」，结局 log_crp，暴露 pm25，协变量 age/sex/bmi/smoking，做 OLS 并给 95%CI。

流程：`v000` 方案 → 派执行者 → 主 agent 验收并 seal → 派审稿人 → 只有 ACCEPT 才交付；不通过就升版本重来。

设置 → 科研模式 里可以给三个角色分别指定模型、编辑行为契约。

## 已在作者机器上验证

- 守护进程：24 核 / 16 GB → 自动定并发 3、每任务 4 线程、内存上限 4040 MB；子进程 `OMP_NUM_THREADS` 确实被压到 4
- 内存上限：申请 6 GB 撞 4040 MB 上限 → `MemoryError`，状态 `killed`，调用方收到退出码 2
- 归档：移动 + `MANIFEST.json`，原路径不再保留
- 删除守卫：9 条样例命令判定正确（6 条危险命令拒绝、3 条正常命令放行）
- 版本门禁：未 seal / 哈希不符 / MAJOR / MINOR 无 waiver 四种交付全部拦下

未在作者机器验证的：预设在新会话中的技能可见性（需要开新会话才能观测）、以及 Linux/macOS 上的限流分支。

## 说明

`skill/references/environment.md` 里保留了作者本机遇到的环境故障记录（Python 商店占位符、pip 配置导致退出、缺科学计算栈），当排错参考看即可。

## 许可

MIT，见 [LICENSE](LICENSE)。

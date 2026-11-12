---
name: consolidate-memory
description: >
  Reflective pass over an agent's memory files — merge duplicates, retire
  stale entries, convert relative time to absolute dates, and prune a bloated
  MEMORY.md back under its size cap. WorkBuddy-adapted edition: maps the
  three-layer memory system (read-only cloud profile / user-level MEMORY.md /
  workspace daily logs), enforces append-only logs, backup-before-write and
  per-item approval. Triggers: "consolidate memory", "memory health check",
  "review memory", "整理记忆", "记忆体检", "记忆去重", "压缩记忆", "清理记忆".
---

# Consolidate Memory（WorkBuddy 适配版）

- **Version**: 1.0.0-wb
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills
- **Upstream**: Claude Code `consolidate-memory` (MIT) — https://claudskills.com/skills/consolidate-memory
- **Platform**: WorkBuddy three-layer memory. Claude Code users should use the upstream original instead.

目标：让下一次会话能快速定位「用户是谁、在意什么、怎么做事」，不用重新问一遍。
原版假定 Claude Code 的单一 memory 目录 + `MEMORY.md` 索引文件；本版按 WorkBuddy 三层记忆重写，目录、红线、容量全部对齐平台规则。

## 0. 目录映射与边界（先做这一步）

| 层 | 位置 | 本 skill 的动作 |
|---|---|---|
| 云记忆 | 会话注入的 `<memory>` 与服务端 profile | **只读，跳过**。服务端自动学习，本地改动会被覆盖 |
| 用户级 | `~/.workbuddy/user-*/MEMORY.md`（用 `ls -d` 定位） | **可整理**：精简、去重、修时间、迁工作流。上限 4,000 字符 |
| 工作区长期 | `<workspace>/.workbuddy/memory/MEMORY.md` | **可整理**：项目长期笔记。上限 3,000 字符 |
| 工作区日志 | `<workspace>/.workbuddy/memory/YYYY-MM-DD.md` | **只读 + 只追加**，不改写、不删除、不重排 |
| 身份三件套 | `~/.workbuddy/user-*/{SOUL,USER,IDENTITY}.md` | **只读**，由用户手动维护 |

硬性红线：
- 绝不删除 `.workbuddy` 目录；不改 SOUL / USER / IDENTITY；不写云记忆。
- 日志 append-only：30 天以上日志的蒸馏由 WorkBuddy 内置机制负责，本 skill **只产出蒸馏候选清单，不执行移动或删除**。
- 不写入密钥、token、身份证 / 银行卡等敏感值；发现即提示用户移除，不复述内容。
- 改动前先把目标文件备份到同目录 `MEMORY.md.bak-YYYYMMDD-HHMMSS`，并确认备份成功。
- **逐条确认**：先给完整清单，用户确认一项才改一项，禁止批量套用。
- 用户级 `MEMORY.md` 是「分节规则清单」，不要套用 Claude 版 `- [Title](file.md) — hook` 索引格式，不凭空造主题文件。

## 1. 盘点

- 定位并读取两层 `MEMORY.md`，用 `wc -m` 统计字符数，对照 4,000 / 3,000 上限。
- 只读扫近期工作区日志，仅用于判断哪些长期条目已经过时。
- 给每条打标签：重复 / 过期 / 相对时间 / 易重查 / 应迁到 skill / 保留。
- 先汇报：条目数、字符数、超限多少、各类问题各几条。

## 2. 整理

按此优先级处理，逐条出示「原文 → 拟改」并等用户确认：
1. **合并重复**：同一规则在多处出现，保留最完整的一条，其余合并或删除。
2. **清理过期**：一次性项目、已过截止日的安排、已失效的账号状态，删掉或折成一句可复用结论。
3. **绝对日期化**：「上周」「本季度」「30 天内」改成 `YYYY-MM-DD`，过期判断据此得出。
4. **去掉易重查的**：能从日历、文档、git、已连接工具随时拉到的内容不存；保留偏好、决策背后的原因、找谁办什么事。
5. **超限时先迁后删**：可执行的多步工作流迁到 skill，`MEMORY.md` 只留一行指针；过程叙述一律删，只留结论。
6. **矛盾项**：两条冲突时保留较新且更明确的一条，另一条标注后交用户裁决，不静默覆盖。

## 3. 收尾

- 复跑 `wc -m`，确认两层都在上限内；按主题分节、每节条目精简；仅扁平索引式 MEMORY.md 才限 10–20 条。
- 确认日志文件未被改动（对比备份或 mtime）。
- 输出汇总：动了几个文件、合并 / 删除 / 修改各几条、压缩前后字符数、剩余待办。
- 若仍超限，说明差多少、建议迁移哪几节，不要自行大删。

## 与内置能力的分工

- 平台内置的「完成实质工作后自动写日志」「30 天以上日志蒸馏进 MEMORY.md」负责**增量写入与归档**；本 skill 负责**存量体检**（去重、去矛盾、绝对日期化、容量压回），两者互补，不替代。
- `/memory` 面板与设置 → 记忆提供单条查看 / 编辑 / 删除 / 导入，适合点状修改；本 skill 适合整本过一遍。
- 本 skill 不自动运行，只在用户显式触发、或发现明显超限时提议一次。

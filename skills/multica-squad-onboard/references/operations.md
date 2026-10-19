# 执行、安装与恢复

## 参数与使用

运行 `python3 <本Skill真实目录>/scripts/onboard.py --help` 获取入口。仅依赖 Python 3.10+ 标准库和已登录的 Multica CLI，不自行安装工具或读取登录凭据。

全局 `--profile`、`--server-url`、`--workspace-id` 在子命令之前。省略时沿用当前 CLI；URL 指定的服务器与工作区须匹配，显式服务器与 URL 不同会停止。UI/API 域名不一致时，由用户确认正确 API 环境后以项目 UUID 加 `--server-url` 重新检查，不自动替换域名。

- `inspect <项目ID或URL> [--squad-id <小队ID或URL>] [--snapshot-file <新文件>]`：只读检查。指定小队只是校验约束；不能消除负责人领导多支小队的歧义。快照保存原有 description/instructions、角色、启用 Skill UUID 等，输出摘要不含原指令。快照父目录可自动创建，文件须不存在。
- `prepare <项目ID或URL> [--squad-id <小队ID或URL>] --reviewed-snapshot <已审阅快照> --skill-id <公共Skill工作区UUID> --plan-file <新文件>`：重新检查，拒绝过期快照及未满足前提；核验公共包的名称、工作区、正文和两个必要文件，生成精确的 before/after 计划，不写平台。调用者须先审阅快照中未托管的原指令和业务要求，并核验所选 Skill 的可信来源；脚本不会仅凭名称/来源标签证明包可信，也不会自动识别原文语义冲突。
- `apply --plan-file <计划> [--reconcile]`：使用计划固定的服务器/profile/工作区，不允许全局参数覆盖。只追加公共 Skill、修改 description/instructions 的本项目托管块；不修改组织关系或业务 Skill；负责人修复使用单独的已授权命令。不等于业务派单。`--reconcile` 只用于已经读平台与日志对账后的恢复，仍检查所有允许状态。

- `set-project-lead <项目ID或URL> --squad-id <已确认小队ID或URL> --agent-id <已授权队长UUID> --authorized --record-file <外部私有记录> [--reconcile]`：仅在用户明确授权该目标负责人变更后使用；不代选、不改小队队长/成员。核验同工作区、目标队长唯一有效小队及成员关系，保存旧值，只调用 `multica project update --lead <Agent UUID>`，写后按 lead_type/lead_id 读回。若 CLI 不支持 UUID 或返回不确定，停止并对账，不盲目改用同名对象。已达目标再次执行只读核验；部分失败须先对账，再允许 --reconcile。--authorized 只是调用防误触开关，不代替人的授权。修复后重新 inspect 并生成新接入计划，不沿用旧快照。

退出码：0 为该命令成功（inspect 无平台配置阻断）；2 为前置阻断、格式问题、漂移或执行失败。inspect 成功不等于远端环境已实测，不等于公共预览/业务验收通过。

调用示例中的 shell 变量均为本次任务实际确认的路径/ID，不要将示例项目写入 Skill：

```bash
python3 "$onboard_dir/scripts/onboard.py" inspect "$project" --snapshot-file "$evidence_dir/before.json"
# 阅读 before.json，审查原指令冲突、作用域和来源；如需用户前置设置，完成后新建快照重新检查。
python3 "$onboard_dir/scripts/onboard.py" prepare "$project" --reviewed-snapshot "$evidence_dir/before.json" --skill-id "$public_skill_id" --plan-file "$evidence_dir/plan.json"
# 检查计划的 before/after；只在用户已授权接入该项目时应用。
python3 "$onboard_dir/scripts/onboard.py" apply --plan-file "$evidence_dir/plan.json"
```

## 公共 Skill 安装

1. `multica skill list --output json` 读取当前工作区，唯一定位 `multica-squad-load-balancer`；列表截断/多重同名时不猜。读取 `skill get`：正文、版本、`scripts/squad_balance.py`、`references/contract.md` 应齐全。
2. 从用户认可的可信来源获取完整包及实际版本，例如本仓库已核验提交中的 `skills/multica-squad-load-balancer/`。固定并记录来源提交/版本，检查文件清单和哈希；不要仅凭同名包认定可信。可使用用户已有的 Skill 注册表或安装工具；不要求安装专有工具。私有来源权限缺失时提示用户完成授权，不索取共享 Token。
3. 从仓库打包时，ZIP 根目录须直接包含该 Skill 的 SKILL.md、scripts/、references/ 等完整文件，不能把整个仓库归档当单个 Skill 包。可从已核验提交的该子目录构建 ZIP；不包含签名材料、凭据、运行日志或缓存。无可复用包且用户已授权接入时，使用 `multica skill import --file <已核验完整ZIP> --on-conflict fail --output json` 导入，读取返回的工作区 Skill UUID。不要从本地 Skill 目录直接全量打包：其中可能有签名私钥、缓存或其他非发布文件。
4. 工作区已有包时先复用；若 origin 为嵌套结构、且记录 local_patch，分别核验可信基包、具体补丁差异及脚本哈希，报告 来源基版和实际补丁版，不将补丁版称为来源正式发布版本。来源无法证明、版本不适用或文件不完整则报告具体问题。全工作区覆盖/升级可能影响其他项目，不把“接入这个项目”当成覆盖授权。确已授权升级时按实际可信来源包更新，并核验内容与来源元信息；先对账，不以失败响应推断未写入。
5. helper 的 apply 使用 `agent skills add` 追加启用给队长和成员，写后检查 enabled；既有业务 Skill（含禁用分配）保留。若追加没有启用已有禁用分配，先报告平台实际行为，不用整表替换来绕过。

来源只输出安全标识、主机及摘要，不回显 URL 查询参数或凭据；公共包须有可识别版本、唯一文件路径。helper 支持旧包 frontmatter 的 version 和本仓库正文的 `- **Version**: x.y.z`，以明确的包版本生成摘要，不将调度记录协议版本当包版本。包来源元信息和内容摘要只是记录，不能替代可信来源验证。安装或发布失败后先查询工作区包和成员分配，不重复创建同名包。本 Skill 本身无需分配给业务执行者；它供完成接入的操作者使用。

## 指令合并与安全边界

`roles.md` 的四个模板分别应用于项目 description、小队 instructions、队长 instructions 和成员 instructions。托管标记为 `multica-squad-onboard:<项目UUID>:begin/end`。只更新当前项目对应块，保留块外原文；重复、残缺、交叉或嵌套标记停止。不同项目可以各自保留块，避免共享 Agent 的角色相互覆盖。

原有未托管文本若要求全局手工派单或队长代做业务，先提出精确修改。不要让新增块和旧规则并存冲突；只有已授权范围内的原文调整才可由 Agent 按字段读写，完成后重新 inspect/prepare。脚本不自动删除任意原文，也不自动重写其他项目块。

计划摘要用于完整性与漂移检查，不是签名或授权凭据；只应用本轮检查并生成、已审阅的计划，不直接执行第三方附件计划。所有计划和日志是私有运行数据，不应打入 Skill 发布包或提交代码。只保存配置所需字段，不保存 Agent runtime_config、CLI stderr、Cookie、Token、私钥。不要在审阅报告中回显原指令里可能已有的敏感信息。

## 漂移、部分失败和恢复

prepare 固定当前路由、成员、原指令、Skill 分配、Runtime 绑定/容量/角色、完整 Skill id/enabled 分配及公共包摘要；apply 前和每次写前重新读取，并在写后核验。平台未提供本流程的跨资源事务/CAS，因此仍存在读写间并发窗口，不能宣称原子更新；发现冲突停止，先协调配置操作者再重建快照。

首次 apply 先以独占方式新建计划对应的 `.apply.json`，每项写前记录 started、读回后记录 verified。若超时、进程中断、日志写入失败或平台返回不确定，先 inspect 并阅读私有日志；不要直接重复 apply、删除日志或自动回滚。恢复只接受平台仍为计划 before/after、公共 Skill 为追加前/后这两种状态；其他更改停止。对账确认后允许用同一计划加 `--reconcile` 继续。已完成计划再次运行只核验，未变时不重复写入。

## 公共预览与远端验证

读取实际安装版本的公共 SKILL.md，使用其真实绝对路径运行 `preview --project-id <项目UUID>`。需要覆盖 CLI 环境时使用同一已核验 profile/服务器/工作区，全局参数放在 preview 之前。只有原业务明确声明要求时才重复传 `--required-skill-id`，或传精确 `--member-role`；不要固定评测项目的业务 Skill。

预览必须核对返回 project/workspace/leader/squad 与检查快照一致；名单和容量仅本次展示，后续派单实时重算。没有可用成员、未知任务状态或截断数据都如实报告，不自写算法兜底。读取新快照时，成员变化须复核并为新增成员接入。

平台包、用于 preview 的安装包与真正成员 Runtime 的包分开记录；版本或内容不一致不得写“全链路已验收”。只能通过已有授权的远端诊断手段检查实际 Python、CLI 登录/读权限、包文件、私有目录可写性；不能因本机通过就替成员打勾。无法实测标待验；不通过派单来偷偷测试。

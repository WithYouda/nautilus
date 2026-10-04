# D1 成果图实施契约

日期：2026-10-04。依据已获作者批准的 D1 计划。此文件是前后端共享工程契约，完成情况以开发状态与实际检查为准。

## 身份与语义

既有 `learning_outcome` ID 不变；新增 `kind=atomic|composite`，旧成果均为 atomic。新增成果不按名称合并，不自动建立或批准标准。composite 是组织层，不允许被普通学习委托冒充可验证成果；整体实践要求独立显示，不平均子项状态。

本次 composite 仅实现组织与组成成果的证据覆盖；`overall_evidence_required=true`，不提供综合成果的整体评估或达成派生。标准治理只展示和校验既有不可变版本、审核人/时间、来源、情境和可用性；包表未记录独立包版本时返回 null，不从名称或标准版本伪造包版本，未记录的限制保留为空。

关系 `contains` 从综合成果指向组成成果（atomic 或 composite），跨情境也禁止结构循环；`prerequisite` 从个人选择的前置成果指向后续成果，仅提供说明，不阻止任务或调整排序，同一适用情境内禁止有向循环；`equivalent`、`overlap` 无向，以端点 ID 排序规范保存。禁止自指、同情境重复关系，以及同一对端点同情境同时等价/包含或等价/前置。所有正式关系均是用户组织决定，不能证明客观领域真理。关系撤销只改变组织，不删除成果、迁移或复制证据。

## HTTP

以下均为已授权 owner 的 `/api/learning/outcome-graph` 路径；响应 `Cache-Control: no-store`。未拥有的端点/来源返回 404，不泄漏存在性。所有 POST 带 `request_key`（1–200 字）；相同键和同请求返回原结果，不同请求返回 409 `idempotency_conflict`。

- `GET /?plan_id=<optional>` 返回 `{nodes,relations,plans,runs}`。不带 plan_id 返回全部；带 plan_id 返回该计划的既有成果、其包含祖先，以及这些节点之间的关系。跨计划选择从不带筛选的结果取得。
- `POST /outcomes`：`{request_key,kind,object_description,behavior,context_key}`，返回 `{id,event_id,aggregate_version}`。kind 默认 atomic；两个描述分别最长500字，context_key 最长200字。
- `POST /relations`：`{request_key,source_outcome_id,target_outcome_id,relation_type,context_key,rationale,uncertainty,source_refs}`，返回 `{id,event_id,aggregate_version}`，aggregate_version 即 revision。
- `POST /relations/{id}/revise`：上述关系字段＋`expected_revision`；返回相同 ID 的新 revision。
- `POST /relations/{id}/revoke`：`{request_key,expected_revision}`，返回 `{id,event_id,aggregate_version}`；同键重试幂等，已撤销对象不能普通修订。
- `GET /relations/{id}` 返回关系当前字段＋`history`（各版本字段，包含撤销记录）。
- `POST /relations/{id}/purge`：`{request_key,expected_revision,confirmation:"PURGE"}`；清除关系说明/情境/来源私文及受管理副本，保留端点、类型、版本、决定历史的最小元数据；返回 `{id,event_id,aggregate_version,purge_report}`。
- `GET /relations/{id}/purge-status` 返回既有受管理清除报告。
- `POST /suggestions`：`{request_key,outcome_ids}`，2–30 个唯一已有成果 ID；立即返回 run（下述格式），后台仅调用一次当前证据分析所选模型或默认模型。只发送所选声明，不读取任务私文、证据正文或联网。
- `GET /suggestions/{run_id}` 返回 run；`POST /suggestions/{run_id}/cancel`：`{request_key,expected_revision}`。
- `POST /suggestions/{run_id}/candidates/{candidate_id}/review`：`{request_key,expected_revision,decision:"accept"|"reject",relation?:<关系字段>}`。accept 可带完整调整后的 relation，省略则采用候选；编辑后的两个端点仍须在冻结的选定范围内。返回 `{candidate_id,revision,status,relation_id}`。
- `POST /suggestions/{run_id}/purge`：`{request_key,expected_revision,confirmation:"PURGE"}`；返回 run＋`purge_report`。`GET /suggestions/{run_id}/purge-status` 返回清除报告。

关系字段：`id,source_outcome_id,target_outcome_id,relation_type,context_key,rationale,uncertainty,source_refs,source_kind("manual"|"ai_accepted"),candidate_id,revision,status("active"|"revoked"|"purged"),created_at,updated_at,available`。source_refs 为 `[{kind:"outcome"|"artifact"|"criterion"|"external",id?:string,version?:integer,url?:string}]`；内部引用校验真实 owner/具体版本，外部 URL 仅保存声明，不假称已核验。每项读取附 `available,unavailable_reason`；来源消失时不补造，关联说明整体隐藏；清除时相应派生私文在历史及备份一起清除。

run：`{id,revision,status:"running"|"succeeded"|"failed"|"canceled"|"purged",reason,outcome_ids,provider_snapshot,created_at,finished_at,candidates}`。candidate：`{id,revision,status:"pending"|"accepted"|"rejected"|"purged",source_outcome_id,target_outcome_id,relation_type,context_key,rationale,uncertainty,source_refs,relation_id,available}`。provider_snapshot 不含秘密；scope、输入及实际模型在发起前冻结，失败/取消/无效结构不生成正式关系。重试使用新 request_key，原请求不会隐藏重复调用。页面刷新通过 graph.runs 和 run GET 恢复。

node：`{id,kind,object_description,behavior,context_key,source,created_at,plan_ids,task_links,evidence_links,coverage,overall_evidence_required}`。task_links：`[{action_id,action_title,plan_id}]`，evidence_links：`[{claim_id,artifact_id,content_version,fact_event_id,criterion_id,dimension_id,stance,available}]`，只引用真实现有证据。coverage：`{status:"no_standard"|"unknown"|"insufficient"|"provisional"|"supported"|"conflicting"|"mixed",standards:[{id,version,context_key,review_status,availability,package_id,package_title,package_version,sources,scope,limitations,dimensions:[{id,label,state}]}]}`。保留全部标准版本、情境及审核/可用状态；没有合格标准显示 no_standard，有合格标准而无证据显示 unknown。混合状态不压成百分比，composite 默认 unknown、overall_evidence_required=true。点节点继续现有 OutcomeReview 依据回看。

10-04失败修正：`reason`区分连接/超时/鉴权/限流/服务响应、输出截断/仅思考、JSON/结构错误和候选关系校验等固定分类；诊断只记录阶段与错误分类，不保存模型原响应或异常正文。旧`generation_failed`不能回填为猜测原因。新运行的`provider_snapshot.max_tokens`冻结实际单次输出预算：默认32768，已知模型输出上限为正整数时取较低值，保留所选模型、思考强度与超时；预算更改不修改已接受运行，也不自动追加请求。提示版本2补齐非空情境与字段长度约束；截断/无效输出仍不保存候选，不改变批次拒绝、重复跳过或用户逐项确认语义。

10-04关联入口修正：右侧显示相邻成果本身的名称和简短关系方向，点击名称使用同一ID定位、选中并打开图中成果；另设“关系详情”查看说明/来源/历史。搜索或计划筛选遮住相邻节点时先揭示该节点，再定位，不创建新身份或改写关系。

## 事务、冲突与生命周期

正式成果/关系及候选审查走 Core 命令，在同事务追加事件、更新投影和幂等结果。旧 revision 返回 409 `version_conflict`；duplicate/cycle/type/source/scope 错误不留下半条关系。关系说明、来源正文及冻结 AI 输入置于可清除的独立私文存储，事件只引用身份和版本；回放读取原私文及清除屏障，不复活清除内容。

新增 migration 042。新增清除种类接入 ManagedPurge、已登记备份和恢复屏障；来源 artifact 清除同时清除依赖关系/候选的派生私文。取消先改变持久状态再终止任务，晚到模型响应不能覆盖取消、清除或源变化。

## 接口就绪检查

后端通知就绪前：隔离数据库迁移042，真实 GET/创建/关系修订撤销/历史/CAS/循环/owner/证据覆盖/API候选审查通过；AI输送只使用合成声明和 MockTransport。前端再启动完整浏览器旅程，复用原 OutcomeReview。后端拥有合成 API fixtures，前端拥有浏览器场景；两者不写原trial或默认 data。原trial启用由主Agent完成最终审阅后另行组织。

## 实际检查与启用（2026-10-04）

17项新增图API检查及79项既有Core/清除/恢复/升级/证据/回看/状态回归，共96项不同检查通过；3条不同浏览器旅程、TSC/隔离构建和桌面/390px审阅通过。一次只含合成声明的生产提示/传输检查返回2条包含候选，schema/枚举/所选范围通过。重复模型候选若与当前同情境正式关系完全重复则跳过，全部重复仍成功、候选为空，不留下正式变化；真正越权/自指/类型/循环/冲突仍拒绝。

经主Agent验收授权，官方工具升级同一原trial041→042，自动备份/清单SHA256/0600和完整性/外键通过；旧62张学习表及18张普通表原列/原行、46旧备份/清单保留，7张新图表为空。受测构建与localhost/实际WSL资源逐字节一致，图路由鉴权通过。工程事实不替代作者真实试用；综合节点继续是组织层，不提供整体评估或自动达成。

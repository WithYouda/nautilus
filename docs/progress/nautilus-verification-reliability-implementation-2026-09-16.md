# Nautilus 验证可靠性与学习室恢复实施记录

日期：2026-09-16，Asia/Shanghai。

用户阅读同日审查后确认按建议修改。本轮完成推荐顺序中的第一实施段（Task 15B），没有操作真实数据库或启用服务；后续证据/删除接入、指标修正和最小计划复核仍按新计划推进。不能将本轮称为完整 PRD V2 或完整长期学习协作者。

## 实际改动

- PRD 新增 `CAP-VERIFY-001` 至 `005`，同步已确认的两个入口、教学/验证分离、作答保存、最后确认和恢复规则。产品决策记录补充用户采纳的推进顺序与多委托完成语义；计划新增 15B、15C、17A.0，使最小连续流程先于完整图形界面。
- 新增 `023_verification_submissions.sql`：不可覆盖的提交记录、独立评估尝试、验证契约快照与当前提交引用、学习会话/对话归属表。保留 022，未改已有迁移。升级会保留 022 最后一份提交及结果；过去已被覆盖的回答和未记录的模型信息无法补回，不伪造历史。
- `verification.py`：`submit` 只保存作答，新增 `evaluate` 和 `confirm`；提交请求键校验内容指纹。AI 失败/取消保留提交，每次重试有独立评估记录；相同请求不重复出站，显式重试使中断请求失效，旧结果不能覆盖当前提交。成功结果重复评估不再调用模型。
- 最终确认引用具体 submission/evaluation，校验当前契约、验证通过和停止条件满足；不重新评分。确认结果、完成事件和会话结束同事务提交，重复确认幂等，存储失败回滚。
- Core 新增 `delegation.completed` 事件；若其他委托仍为 ready/active/paused，只完成指定委托，保留行动 open 及其他运行会话。最后一个开放委托通过确认才生成 action.completed。保留旧 action.completed 回放语义，不重写历史事件。
- 结果仅接受两个布尔值和两个文本字段，拒绝嵌套私密结构及额外字段；来源 URL 校验 hostname、端口和明显占位域名，不抓取网络，不宣称独立核验。题目无论标记何种类型都拒绝填空/补全要求。
- 验证页面按“保存并评估 -> 查看结果 -> 核对停止条件 -> 确认”呈现。教学/验证切换保留组件中的未提交文本；重新打开查询已保存尝试并可重试评估或确认。公开响应不回传私密材料或隐藏评分依据。新尝试使用新的请求键，支持重新准备验证。
- 新增 `learning_room.py`：校验真实会话和对话身份/范围，持久保存会话所属对话及最后选择；跨会话改挂对话被拒绝，删除对话后跳过失效引用。学习室按归属恢复，不退回任意独立对话；工作台当前会话补返回学习室入口。首次提示恢复到尚无用户消息的空对话时仍可自动发送。
- 普通应用启动对两库采用 `migrate=False`：缺库、旧版本和未知版本均拒绝，不创建新库或运行迁移。授权升级工具显式迁移，隔离测试先初始化临时库；调整测试启动脚本并补 README。由一个既有后端子代理独立完成这一模块，没有多代理交叉修改业务文件。

## 文件范围

- 业务后端：`backend/app/verification.py`、`learning_room.py`、`core/learning.py`、`core/events.py`、`schemas.py`、`routers/learning.py`。
- 存储与启动：`backend/app/migrations/023_verification_submissions.sql`、`db.py`、`main.py`、`learning_storage.py`、`learning_production.py`。
- 前端：`frontend/src/LearningVerification.tsx`、`AiLearningRoom.tsx`、`FactWorkspace.tsx`、`api.ts`。
- 验证/运行说明：`backend/tests/test_learning_verifications.py`、`test_verification_reliability.py`、`test_learning_room.py`、`test_startup_migration_guard.py`、`test_learning_domain_schema.py`、`conftest.py`、`scripts/start-e2e.sh`、`README.md`。
- 文档：PRD V2、实施计划、产品决策、本记录和开发状态。全部接手前改动保留，没有暂存/提交/推送或操作 diagnostic-backups/。

## 验证

最终聚焦命令：

```bash
timeout 60s env PYTHONPATH=backend .venv/bin/python -m pytest -q \
  backend/tests/test_learning_verifications.py \
  backend/tests/test_verification_reliability.py \
  backend/tests/test_learning_room.py \
  backend/tests/test_startup_migration_guard.py \
  backend/tests/test_learning_setup.py \
  backend/tests/test_learning_domain_commands.py \
  backend/tests/test_learning_domain_schema.py::test_independent_schema_and_reopen_are_stable \
  backend/tests/test_learning_domain_schema.py::test_learning_database_upgrades_from_016_with_existing_rows \
  backend/tests/test_learning_production_upgrade.py::test_production_upgrade_initializes_and_backs_up_isolated_learning_database \
  backend/tests/test_learning_production_upgrade.py::test_production_upgrade_requires_authorization_and_rejects_default_database
```

结果：**61 passed in 2.92s**。包含 MockTransport/ASGITransport，无真实 Provider 或监听服务。

- 前端 `npm --prefix frontend run build` 通过；保留既有大于 500 kB 的 chunk 提示。
- Python compileall、`bash -n scripts/start-e2e.sh`、`git diff --check` 及本轮未跟踪文件空白检查通过。
- 子代理另有基础 health/WAL 两项通过；不把重复运行累计为更多覆盖。
- 开发中曾遇到新增 023 未同步旧测试版本清单、并行编辑时 ConfigDict 导入未完成；最终聚焦命令均已通过。
- 未运行后端全量、Playwright 或真实 Provider。此前挂起的 `test_learning_facts_api.py::test_learning_database_is_independent_from_legacy_database` 未重跑，仍不计为通过。没有人工浏览器验收，生产构建不等于真实学习旅程验收。

## 保留边界与精确下一步

- 本轮未打开默认主库或真实学习库，没有应用任何生产迁移；021/022/023 实际应用状态未核验，023 仅在隔离库验证。未启动或重启服务。未来授权启动前需先检查并授权升级匹配 schema；主库升级不属于学习库升级工具范围。
- 提交历史仍在专用验证表，尚未接回 raw artifact -> fact -> claim -> derived state，也未补彻底删除链。评估通过只完成工作承诺，不表示成果已有合格证据支持。
- 当前公开 API 可以恢复已保存尝试并重试/确认，不返回私密作答。未提交文本仅在同一学习室组件存活期间保留；刷新或离开整个工作区不保证草稿恢复。完整私密产出读取/编辑恢复与彻底删除一起接入既有产出机制。
- 契约快照从新验证创建时冻结；022 旧记录仅能补当前可查上下文，不能证明历史评估时的契约/Provider 快照。模型来源目前记录 model/provider_kind，后续证据接入时沿用证据分析的完整非敏感运行追溯。
- 学习会话与教学对话已有持久归属，旧的未关联对话不自动猜测归属。跨数据库没有强行建立外键，对话删除后忽略失效引用。
- 独立 URL、完整默认回归视图、完成后计划复核、指标口径修正及真实使用基线仍未完成。
- 精确下一项：Task 15C，将保存的验证产出和评估引用接入现有事实/证据/彻底删除链，优先用已审核 Python 正则标准验证，不把用户材料中的标准答案当能力证据、不让无标准评估派生成果状态。随后 Task 17A.0 最小复核与指标修正；不直接做完整图形界面。

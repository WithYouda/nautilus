# Nautilus 可信性与学习连续性实施记录 — 2026-09-19

## 1. 本轮结论与边界

基线 HEAD `0973056`，branch `main...origin/main`（未 fetch）。开始时无已跟踪未提交修改；原有未跟踪项目未修改。完成只读调查和五份规范修订后，再按 A1～A5、17A.0 顺序开发。所有本轮改动保留在工作区，未提交、push 或部署。

已关闭本轮新写入与受控运行的主要问题：

- Provider 只能输出观察；四类来源/方法/独立性伪造分别被拒绝。Runtime 绑定来源、方法、自报条件及执行版本/时间。确定性检查只说明当前表达式匹配当前样例。人工复核请求仍 pending，不生成 human_review 主张。
- 历史缺少 provenance 的缓存支持不继续当作当前可信结论：025 降级当前缓存，读取与证据回放再次检查。历史状态和事件保留，不把采纳观察当成独立验证。
- 三个内容版本可一次彻底清除，重试不增加 purge 事件，清除后不能追加更正复活内容，事实与证据回放不能恢复正文。
- 普通产出与验证产出共用可清除 private store。claim 正文/范围、review reason、batch reason、follow-up note 以及共享摘录清除；依赖主张失效。普通备份恢复也检查原文、私密 store 与当前证据投影中的残留摘录。
- 事实和证据回放先持有 BEGIN IMMEDIATE，再取截止点及事件；并发 writer 在提交后继续。校验失败不改变原投影。指标使用实际投影摘要、数量、外键与单一 running 约束，不能用 succeeded audit 代替。
- 指标 v3 关联稳定推荐、展示、选择、实际进入、纠正和正式行动完成；结束会话不算完成。恢复/下一行动指标只输出 observed/no_sample，未知、拒绝和窗口未满单列。
- 完成后及返回时的规则卡已实现：位置、事实、支持、未知、一个建议及理由、继续/换项/暂停/查看依据。恢复同委托的新会话可继续原对话。刷新与 390/1024/1440 和 125% 缩放已验证。

仍未关闭：历史 schema v1 事件中的私文处置、既有普通备份清理、双库协调恢复和真实产品价值验证。没有读取真实库，无法声称历史真实数据已完成清理。本轮不是完整 PRD V2，也不是长期学习效果验收。

## 2. 修改文件

### 需求 / 规格 / 交接

- `docs/progress/nautilus-development-status.md`
- `docs/progress/nautilus-learning-continuity-implementation-2026-09-19.md`
- `docs/progress/nautilus-product-design-decisions.md`
- `docs/superpowers/plans/2026-09-05-nautilus-first-slice-implementation.md`
- `docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md`
- `docs/superpowers/specs/2026-09-05-nautilus-first-slice-domain-architecture.md`

### 后端

- `backend/app/continuity.py`
- `backend/app/core/events.py`
- `backend/app/core/learning.py`
- `backend/app/evidence.py`
- `backend/app/evidence_events.py`
- `backend/app/learning_domain.py`
- `backend/app/learning_production.py`
- `backend/app/learning_room.py`
- `backend/app/learning_service.py`
- `backend/app/learning_setup.py`
- `backend/app/measurements.py`
- `backend/app/replay_check.py`
- `backend/app/review.py`
- `backend/app/routers/learning.py`
- `backend/app/schemas.py`
- `backend/app/state_derivation.py`
- `backend/app/verification.py`
- `backend/app/verification_content.py`

### 迁移

- `backend/app/migrations/025_evidence_provenance.sql`
- `backend/app/migrations/026_replay_checks.sql`
- `backend/app/migrations/027_learning_continuity.sql`

### 前端

- `frontend/src/AiLearningRoom.tsx`
- `frontend/src/FactWorkspace.tsx`
- `frontend/src/ReturnReviewCard.tsx`
- `frontend/src/Workspace.tsx`
- `frontend/src/api.ts`
- `frontend/src/styles/fact-workspace.css`

### 测试 / Mock

- `backend/tests/test_artifact_lifecycle.py`
- `backend/tests/test_continuity_measurements.py`
- `backend/tests/test_evidence_claims.py`
- `backend/tests/test_evidence_provenance.py`
- `backend/tests/test_evidence_provider.py`
- `backend/tests/test_evidence_replay.py`
- `backend/tests/test_learning_continuity_safety.py`
- `backend/tests/test_learning_domain_schema.py`
- `backend/tests/test_learning_facts_api.py`
- `backend/tests/test_learning_room.py`
- `backend/tests/test_measurements.py`
- `backend/tests/test_state_derivation.py`
- `backend/tests/test_verification_evidence.py`
- `frontend/e2e/learning-continuity.spec.ts`
- `frontend/e2e/nautilus-first-slice-facts.spec.ts`
- `scripts/mock-openai-provider.py`

## 3. 数据模型变化

| 新迁移 | 变化 | 既有数据处理 |
| --- | --- | --- |
| 025_evidence_provenance | claim provenance_json；来源、方法、条件、执行器与版本/时间由执行边界绑定 | NULL 代表未知；旧当前 supported/partial/contradicted 缓存降为 insufficient；不改历史账本或状态历史 |
| 026_replay_checks | learning_replay_check | 仅 cutoff、before/after digest、数量、约束/一致性结果，无正文；旧审计不回填成功样本 |
| 027_learning_continuity | learning_return_review、learning_usage_event | 稳定推荐 ID、关联 ID、原因码/选择/时间；AI 草案只留指纹，不复制草案；旧会话不推测用户选择 |

没有修改 001～024，没有发布正则标准 v2。所有迁移仅用于临时测试库。真实库需另外批准升级；启动仍拒绝缺失迁移，不能直接启动旧 schema 冒充升级成功。

新增结构的目的：返回推荐 ID 解决刷新后选择与后续执行无法关联；usage event 解决内部 session 状态不能证明用户选择；replay check 解决审计成功不能证明投影一致。没有新数据库、队列、后台 Agent 或通用平台。

## 4. 验证命令与结果

从仓库根目录执行，浏览器命令注明 frontend 工作目录。所有内容为合成样本，Provider 为 Mock。

| 命令 | 结果 |
| --- | --- |
| `env PYTHONPATH=backend timeout 180 .venv/bin/pytest -q backend/tests --tb=short` | 最终后端全量 340 passed、1 warning；包含新行动关联、跨中断正式完成及历史来源缓存保护 |
| `env PYTHONPATH=backend timeout 90 .venv/bin/pytest -q backend/tests/test_continuity_measurements.py backend/tests/test_measurements.py --tb=short` | 阶段定向 16 passed、1 warning，1.95s；其后新增关联场景已纳入最终全量 |
| `env PYTHONPATH=backend timeout 90 .venv/bin/pytest -q backend/tests/test_evidence_provenance.py backend/tests/test_learning_continuity_safety.py --tb=short` | 11 passed；含来源伪造、历史缓存防复活、三版本 purge、普通证据、并发回放、普通备份摘录 |
| `env PYTHONPATH=backend timeout 90 .venv/bin/pytest -q backend/tests/test_verification_evidence.py backend/tests/test_learning_continuity_safety.py backend/tests/test_continuity_measurements.py --tb=short` | 阶段定向 28 passed；覆盖只存参考材料不计首次产出、迟到结果、并发评估等 |
| `npm --prefix frontend run build` | 成功；Vite 提示单 chunk 超过 500KB，未在本轮做拆包项目 |
| frontend: `./node_modules/.bin/playwright test e2e/learning-continuity.spec.ts` | 2 passed，9.2s；完成链、暂停/刷新/原委托/原对话；三种尺寸与 125% 缩放 |
| frontend: `./node_modules/.bin/playwright test e2e/nautilus-first-slice-facts.spec.ts` | 最终定向 5 passed，13.9s（高阶来源显示调整后） |
| frontend: `./node_modules/.bin/playwright test e2e/nautilus-first-slice-facts.spec.ts e2e/ai-learning.spec.ts` | 中间运行 16 passed、2 failed；学习室 13 项全部通过，两项旧事实测试的文案/模糊选择器失败后已修正，见前一行 |
| frontend: `./node_modules/.bin/playwright test e2e/learning-continuity.spec.ts e2e/nautilus-first-slice-facts.spec.ts e2e/ai-learning.spec.ts` | 联合 20 passed，43.8s；包含复核后新行动的正式完成指标、跨中断恢复和窄屏导航；其后高阶来源显示调整定向 5 项复验通过 |
| `git diff --check` | 通过；新文件另检查尾随空白 |

后端 warning 是既有 Starlette/httpx 弃用提示。沙箱 TestClient 有挂起：最初一次用 timeout 结束、一次中止，未记通过；在沙箱外以相同临时数据库约束完成全量，原独立学习库 API 挂起项目也已动态通过。没有依赖真实 Provider 或真实库绕过测试。

失败及关闭过程：

1. 来源伪造四负例、三版本 purge、普通证据 ledger 私文分别先暴露失败，再实现执行边界/清除修复。
2. 首次后端全量 14 failed / 319 passed：旧 Provider 测试仍自报来源、迁移清单过期、同委托恢复规则和旧指标代理断言。保持隔离/归属断言并改为新契约后，全量通过。
3. 浏览器发现最近会话按时间戳排序受时钟回拨影响，修为已提交事件顺序并新增后端回归；125% 缩放暴露 320px 最小宽度，限定返回卡场景修复。
4. 历史缓存保护新测试先暴露排除原因列表处理错误，修复后通过；不更新历史 append-only 事件。
5. 联合浏览器初跑 17 passed / 3 failed：旧事实套件假定全库空白，与新旅程留下的合成数据冲突。测试准备改为只暂停前一临时会话，并按自身行动筛选产出，不删除任何合成领域数据。另两处旧文案/选择器已修正。最终联合 20 passed；过程中另一次 19 passed / 1 failed 暴露窄屏导航遮挡，修为选择页面后自动收起导航。

未运行：其他无关前端套件的完整总集、真实 Provider、真实环境升级/恢复、真机软键盘和真实试点。窄屏截图已检查；自动化截图位于 `/tmp/nautilus-return-{390,1024,1440}.png`，不是用户真实内容。

复核到下一行动的关联补充：`choose_next` 原先无行动 ID，只有用户确认新草案后才绑定其选择；不把它冒充系统预先知道的任务。确认初始化 → 实际房间进入 → 正式 action.completed 可追溯到原返回卡。中断并恢复后，其他会话完成同一正式行动也能关联；普通 session.ended 永远不产生 completed 测量事件。用于这条关系的记录均复用 027 的 ID 字段，没有新增表。高阶事实视图也显示“来源待核实”，不只保护默认返回卡。

初始化采集口径：setup_ai 的 action_id 非空表示用户已确认的 AI 初始化，空值表示草案生成；setup_modified 只在确认内容与服务端指纹不同时记录，忽略首尾空白。first_artifact 是第一次有效保存的自写内容，不代表验证通过或学习有效性。

## 5. 用户现在的旅程

- 新用户：输入想学会的目标 → AI 草案或自行安排 → 默认确认目标/第一步/停止条件 → 进入学习室。复杂对象在高级详情，无标准也能保存；只有满足既有验证与停止条件并确认，才完成委托。
- 中断用户：回到开始学习先看到原位置、保留的记录及一个恢复建议；继续后进入原委托并恢复该委托对话，可换项、纠正或今天先停。时钟回拨不会挑错最近会话。
- 验证完成用户：确认后直接回到复核卡；本次验证记录与可支持的成果分开；没有标准/独立复核/延迟或迁移观察时明确未知。下一步需要用户选择，没有自动扩张正式计划。

## 6. 隐私、权限与恢复边界

- 当前 raw 所有版本、验证作答/评估副本、新证据私文可按各自删除入口清除；关系、ID、状态、hash 与最小审计保留。单产出 purge 不等于删除整个学习方向、独立聊天或整体验证题库，整体验证有其单独入口。
- 不可变事件不直接改写。新证据事件只留结构/私文 hash；历史 v1 若已有文本，须另外授权迁移设计和真实数据处置，本轮没有声称清除。
- 用户能读自己的完整依据；Agent 读取原文仍受现有权限边界限制。Provider 只在用户发起的初始化、教学、验证或证据分析执行路径收到对应任务所需内容，不获得所有领域数据；模型只能输出观察，不能签发来源或正式状态。
- 本地清除不保证 Provider 外部副本、手工导出或文件系统取证不可恢复。普通备份本身没有被擦写；受控恢复入口拒绝复活当前已标记清除的原文/私密副本。丢失当前删除标记或手工恢复不在保证内。
- 真实数据库升级、恢复、历史私文迁移仍需单独授权；未改变网络认证边界，也不宣称防御所有网络攻击。

## 7. 限制和负责人决策

没有真实使用基线；学习状态仅指标准版本与观察范围，不是科学意义上的通用掌握。approved v1 原样保留；多正例、反例、边界、变式等只作 v2 设计，未发布。

A. 未通过正式验证能否算执行完成；B. 本机/WSL2、家庭局域网或不可信共享网络；C. 彻底删除覆盖的副本；D. 首轮试点学习者；E. 是否正式冻结后续图/教练/人格/插件。五项仍待负责人决定，本轮未替其选择。

无完整成果图、路径图、主动后台教练、人格、插件平台、完整模型策略或大规模 Workspace 重构；没有新增基础设施。双数据库仅记录所有权与降级边界，没有协调恢复保证。

## 8. Task 13B 准备与状态

**NOT READY：真实试点尚不能宣布启动。** 工程闭环和无正文结构化采集已经具备；试点人群、网络/删除承诺边界与必要真实环境启用授权尚未确认，旧 schema v1 私文也不能假定处理完成。

采集准备：进入学习、AI 初始化/人工初始化/草案修改、首次非空自写产出；返回卡展示、推荐、用户选择、实际委托进入与纠正；查看依据、拒绝或暂停、关联执行和正式完成。只有材料而无自写内容不会计为首次学习产出。拒绝、未知、无关联与观察窗口未满单列，价值指标没有自设 pass/fail 阈值。

启动后仅从已确认试点的真实使用产生样本；不得导入此处 pytest/Playwright 数据。摩擦通过结构化路径和后续访谈判断，不复制聊天或学习原文用于指标。13B 不支持的后续能力不能因路线图自动开始。

## 9. 唯一下一项与运行边界

**完成 Task 13B 试点启动确认**：由产品负责人确认首轮学习者及网络/删除承诺范围，再单独安排必要真实环境授权。不是自动开始任何后续功能。

本轮没有启动或迁移生产服务。浏览器测试脚本只创建 `/tmp/nautilus-playwright.*`，三个服务绑定 `0.0.0.0`，结束后清理自身临时环境。核对到 WSL2 实际 IP 为 `172.17.253.105`；测试服务运行时的前端地址为 `http://172.17.253.105:5186`（现已退出，不是部署地址）。开发前必须重新读取 CURRENT SNAPSHOT，并保留本轮及用户未提交修改。

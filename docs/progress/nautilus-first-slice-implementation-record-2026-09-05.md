# Nautilus 首片实施记录

## Task 0：隔离存储与恢复演练

- 覆盖 `INV-008`，为 `CAP-MEASURE-001` 提供隔离与恢复验证记录；不代表业务指标已经实现。
- 复用 pytest 临时目录；新增测试连接守卫，SQLite 只允许 pytest 当前临时目录及演练创建的 `/tmp/nautilus-recovery.*`。连接前解析 URI、符号链接和受保护文件 inode，拒绝默认数据库及其别名。
- 通过文件元数据比较确认本轮测试前后默认库、WAL、SHM 未变；不打开默认数据库，不重新查询其迁移版本。默认库 `001`-`004` 沿用历史记录。
- 恢复工具位于 `backend/tests/isolated_storage.py`，只用于合成数据演练，不是产品备份接口。自动创建私有临时目录，用 SQLite backup API 获取已提交 WAL 数据的一致性快照，拒绝活动事务内备份。
- 快照名为 `snapshot-<末次迁移版本>-<随机ID>.sqlite3`，配套 JSON 保存格式版本、迁移文件哈希、快照哈希、完整性/外键检查结果、表数量和逻辑摘要，不保存内容摘录。
- 恢复到新的随机命名临时库，校验文件哈希、迁移清单、`PRAGMA integrity_check`、`PRAGMA foreign_key_check`、版本、表数量和逻辑摘要；失败不覆盖源库。上下文退出关闭连接并清理所属临时目录。
- Task 0 使用仅含 `011_recovery_probe.sql` 的临时迁移目录，表名 `probe_*` 明确表示存储测试夹具；不是新领域 schema，也不包含真实标准、凭据或用户产出。未执行仓库 `001`-`010`。
- 前滚/回退演练边界：新增迁移每份独立事务；失败迁移的 DDL 和版本记录一起回滚，此前成功版本保留。必要恢复路径是验证快照后打开新临时库，不对原库执行降级 SQL。

复现命令：

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_storage_rehearsal.py
git diff --check
```

Task 0 最终 10 项通过（含两次独立完整恢复演练）。事件回放、隐私清除后的备份处理仍未实现。

## Task 1：新领域 Schema 与仓储

- 新增 `backend/app/migrations/011_nautilus_learning_domain.sql`，在独立空库建立新领域表和本地授权基础；无旧计划/任务表、映射或双写。`001`-`010` 未修改或执行。
- `Database` 增加显式迁移上下界，现有入口默认仅选择 `001`-`010`，防止新增 `011` 被旧启动路径自动应用。`open_learning_database` 只选择 `011` 起的连续迁移，连接前拒绝默认库及别名，拒绝把旧迁移历史当作独立库。
- 新领域表包含成果、标准包及不可变标准版本、行动、委托、契约版本、会话、原始文本版本、事件、命令幂等记录、聚合末端位置、投影位置、产出当前态、分析运行与审计。尚无证据主张或派生状态表。
- `LearningRepository` 负责按身份及 Agent 行动范围读取、审核标准/成果/范围/配方/可用性校验。无标准返回明确原因，不能获得合格绑定；此检查不会禁止后续 Core 保存事实。正式写入由 Task 2 的 Core 命令实现。
- 委托初始状态采用 `ready` 对应“待开始”，沿用已确认产品决策第 40 条，避免把正式委托误作 AI 候选草稿。
- 验证命令：`env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_storage_rehearsal.py backend/tests/test_learning_domain_schema.py`，35 项通过。覆盖独立初始化/重开、迁移原子性、作用域、标准准入、唯一键/CHECK/外键、不可覆盖原文与追加式事件、真实领域 schema 恢复。
- 实际变更：新增 `learning_storage.py`、`learning_domain.py`、`011_nautilus_learning_domain.sql`、`test_learning_domain_schema.py`；修改 `db.py`、Task 0 恢复工具及测试和交接文档。
- 仍未实现 Core 写命令、业务回放、用户界面、Agent 授权流程和证据分析；Task 1 不代表事实门通过。

## 当前实现顺序

Task 0-8 已完成：独立学习库、事实 API、前端事实工作台、统一 Agent 权限链路、事实门验收、已审核标准包、Provider 语义分析、确定性检查、候选主张、失败恢复、跟进安排、状态派生、复核动作、批量复核、显式替代关系、回访队列、删除/撤回/彻底删除、证据回放、权限边界、指标和最终交接均已实现。计划内任务完成；证据门整体产品验收仍有明确后续边界。

当前应用同时打开旧主库（`001`-`010`）和独立学习库（`011`），但不会把 `011` 挂到旧主库，也不建立旧模型映射、双写或适配层。既有后端测试与 Playwright 已恢复运行并通过；默认主库仍不迁移，自动化只使用隔离数据目录。

## Task 2：Core 命令与事务投影

- 新增 `backend/app/core/commands.py`、`events.py`、`learning.py`、`__init__.py` 和 `backend/tests/test_learning_domain_commands.py`。
- 创建学习行动、成果和委托必须经过 Core；不接入旧服务或 Agent 直接写表。命令记录、事件、当前态、聚合末端/投影位置及成功审计在同一写事务提交。
- 同一行动的委托、会话和产出采用行动聚合顺序；成果有独立聚合。Core 校验预期版本，事件附带 schema/投影版本、唯一 ID、命令来源、前一事件哈希与自身哈希。
- 幂等检查在写事务内完成：同键同请求返回原结果，同键异请求拒绝并保留无原文审计。Agent 正式写入及跨身份访问被拒绝。
- `Database.transaction(immediate=True)` 支持跨连接写锁；提交阶段失败和取消也会回滚，避免延期外键在 commit 失败后遗留活动事务。
- Task 2 定向 14 项通过；覆盖四个事务失败注入点、提交阶段失败、重复和并发请求、版本冲突、缺口、越权和字段伪造。此前 Task 0/1 35 项通过，累计 49 项。API、会话、原文保存和回放尚未交付，不能视为事实门通过。

## Task 3：会话、文本产出和事实回放

- 新增 `StartSession`、`SaveTextArtifact`、`EndSession`、`CorrectArtifact` Core 命令及会话/产出事件投影。委托进入 active 与会话独立记录；结束/中断会话不关闭委托。
- 原始文本按原字节语义保存，事件 payload 仅保存会话、产出版本和时间等发生上下文；产出内容哈希单独记录。相同保存幂等键返回首次结果，不生成第二份产出或事实事件。
- 没有合格标准时，保存产出同时记录 `blocked_no_criterion` 分析运行，但不生成主张或学习状态。标准绑定仍由 Task 1 的审核/范围校验约束。
- 更正通过同一产出 ID 的新内容版本和新事件追加，旧版本保留；当前态只指向最新版本。尚未实现普通删除、撤回或彻底删除。
- Task 3 首版回放仅恢复缺失行动投影；该实现已被 Task 3.1 的完整回放修复取代，保留此处作为实施历史。
- 验证命令：`env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_storage_rehearsal.py backend/tests/test_learning_domain_schema.py backend/tests/test_learning_domain_commands.py backend/tests/test_learning_facts.py`，61 项通过。Task 4 的真实 API/浏览器流程、完整权限申请 UI 和证据门均未实现。

## Task 3.1：事实基础修复与回放加固

- 修复回放序列判断：按 `(owner_id, aggregate_type, aggregate_id)` 校验聚合版本 1..N，不再把全局 `position` 当作用户内连续序列；多用户事件交叉时各自可回放。
- 回放前校验事件哈希、事件版本、投影版本、payload JSON 和每个聚合的 `previous_hash` 链；首事件必须无前一哈希，后续事件必须指向同聚合上一事件哈希。
- 回放在同一 `BEGIN IMMEDIATE` 事务中删除并重建行动、成果、委托、契约、会话、产出当前态、分析降级记录、流末端和投影位置；失败回滚并保留旧投影，成功后写审计。不可变原始产出表不删除，作为历史依据校验版本、事实事件、会话和内容哈希。
- 回放返回事件数量、聚合数量和由聚合末端版本/哈希组成的投影摘要；重建后验证投影位置数量和末端事件，并测试回放后可以继续结束会话追加事实。
- 产出事件 payload 不保存原文，但保存内容哈希；回放时用不可变原始产出交叉校验。缺少原始产出时拒绝回放，避免伪造历史依据。
- `CorrectArtifact` 在写事务内按当前最高内容版本推导下一版本，连续更正产生 1/2/3 等不可变版本，不再硬编码版本 2。
- `artifact.created` 只有在委托没有标准时创建 `blocked_no_criterion`；绑定已审核标准时不创建误导性分析运行，证据分析留到 Task 5。
- `execute`、`events`、`artifact` 和 `replay` 统一校验用户 Principal 且 `actor_id == owner_id`；Agent 和身份不一致请求返回 `permission_denied`。
- 修订实施计划：Task 3 明确为后端基础，新增 Task 3.1，Task 4 负责 API/UI/Playwright；同时修正 PRD V2 11.2 小节排版顺序。

验证命令：

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q \
  backend/tests/test_storage_rehearsal.py \
  backend/tests/test_learning_domain_schema.py \
  backend/tests/test_learning_domain_commands.py \
  backend/tests/test_learning_facts.py \
  backend/tests/test_learning_fact_hardening.py
```

结果：71 项通过。

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -vv backend/tests
```

结果：185 项通过，1 个既有 Starlette/TestClient 弃用警告。2026-09-06 在最终授权顺序调整后重新执行以上完整复验，结果保持通过。

实际变更：`backend/app/core/learning.py`、`backend/app/core/events.py`、`backend/tests/test_learning_fact_hardening.py`、PRD V2、实施计划、本记录和开发状态文档。未新增迁移，未修改 `001`-`010` 或 `011`，未打开默认数据库。

已知边界：API/UI/Playwright、删除/撤回/彻底删除、证据分析、状态派生和重算仍未实现；尚无真实预审核窄领域标准包，也未选定 Provider。Task 3.1 只是修复后端事实基础，不代表事实门验收通过。

## Task 4：事实门用户流程、权限和 Playwright

- 新增应用级独立学习库路径 `data/learning.sqlite3`，可用 `NAUTILUS_LEARNING_DATABASE` 覆盖；主库仍只应用 `001`-`010`，学习库只应用 `011`，二者不共享迁移历史。
- 新增 `LearningService`，把本地授权身份同步到独立学习库，并封装状态读取、行动/成果/委托/会话/产出/更正/回放命令。
- 新增 `/api/learning/*` 路由和 Pydantic 请求模型，覆盖状态、创建、会话、产出、更正、事件读取和回放；未授权请求返回 401，领域错误返回结构化 `kind/message`。
- 新增前端事实工作台：创建行动/成果/委托、开始/结束/中断会话、保存与更正文本产出、查看事件、回放事实、无标准降级和分析运行状态提示、移动端适配和 Agent 权限演示。
- Playwright 使用 `/tmp/nautilus-playwright.*` 隔离数据目录，覆盖无标准保存、产出更正、回放、刷新恢复、跨身份隔离、Agent 拒绝、重复提交不重复产出和移动端视口。
- 修复 `artifact.corrected` 回放缺陷：回放时先按事件定位已有不可变原文，只在首次执行时推导下一版本；新增回放后更正回归测试。
- 前端 API 客户端为每个操作生成带内容签名的幂等键，并保存在 `sessionStorage` 中用于刷新恢复；成功后清除，失败后保留以便同请求重试。

验证命令：

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -vv backend/tests
```

结果：195 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
./node_modules/.bin/playwright test
```

结果：33 项通过，包含 2 项新增事实门 Playwright；全部使用隔离数据目录。

实际变更：`backend/app/config.py`、`backend/app/dependencies.py`、`backend/app/main.py`、`backend/app/schemas.py`、`backend/app/learning_service.py`、`backend/app/learning_storage.py`、`backend/app/routers/learning.py`、`backend/app/core/events.py`、`backend/tests/conftest.py`、`backend/tests/test_learning_facts_api.py`、`backend/tests/test_learning_fact_hardening.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/Workspace.tsx`、`frontend/src/styles.css`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、`frontend/e2e/v6-workspace.spec.ts`、`scripts/start-e2e.sh`、本计划和开发状态文档。未修改 `001`-`011`，未打开默认主库，未启动交付服务。

已知边界：Task 4 完成时 Agent 权限申请仍是界面演示；该缺口已在 Task 4.1 中关闭。尚无真实预审核窄领域标准包；回放使用同事务重建而非独立临时表。

## Task 4.1：事实门正式验收收尾

- 新增 `learning_agent_permission_request` 表，持久化 Agent ID、目的、范围、目标行动、内容粒度、有效期、状态、创建时间、决定时间和拒绝原因。
- 新增 `backend/app/agent_runtime.py`，作为统一 Agent Runtime 的最小权限边界；权限申请和拒绝均写入 `learning_audit`。
- 新增权限申请 API：创建、列表和拒绝；同键申请幂等，过期申请自动转为 `expired`，已拒绝申请重复拒绝保持原结果。
- 前端事实工作台的 Agent 权限卡改为真实 Runtime 请求：发起申请、查看目的和状态、拒绝后继续保存。
- 新增 `backend/tests/test_agent_permission_runtime.py`，覆盖未授权、申请/拒绝/幂等、审计、拒绝后继续保存、缺失目标、过期和跨身份隔离。
- 新增 `docs/progress/nautilus-fact-gate-acceptance-2026-09-07.md`，逐项记录 PRD 11.4.1 的验收结论、证据和边界。
- 事实门结论：在无标准路径、独立学习库、新领域行动范围和同事务回放替代方案内通过；真实窄领域标准包未建立，证据门不得开始。

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：195 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：33 项通过，全部使用隔离数据目录。

实际变更：`backend/app/migrations/011_nautilus_learning_domain.sql`、`backend/app/agent_runtime.py`、`backend/app/learning_service.py`、`backend/app/dependencies.py`、`backend/app/main.py`、`backend/app/schemas.py`、`backend/app/routers/learning.py`、`backend/tests/test_agent_permission_runtime.py`、前端 API/事实工作台/样式/Playwright、实施计划、本记录、产品决策记录、开发状态和事实门验收记录。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：尚无真实预审核窄领域标准包；Agent 权限仅实现申请、拒绝和过期，尚未实现批准后的实际读取授权；证据分析和状态派生未实现；回放仍采用同事务重建的技术替代。下一项为审核候选标准包，确认后再进入 Task 5。

## Task 5 前置：候选标准包

- 新增 `docs/standards/2026-09-07-first-domain-options.md`，比较 Python 正则、SQL SELECT 和 Git 分支三个备选领域，推荐“Python 正则表达式基础 v1”。
- 新增 `docs/standards/2026-09-07-python-regex-basics-v1-candidate.md`，声明来源、适用范围、可验证成果、三个验收维度、配方 JSON 和边界限制；状态为 candidate。
- 新增 `backend/app/standards/python_regex_basics_v1.candidate.json`，作为机器可读候选包模板。
- 新增 `backend/tests/test_standard_package_candidate.py`，校验候选包元数据和 `CriterionRecipe` 结构。
- 验证：后端全量 196 项通过，1 个既有 Starlette/TestClient 弃用警告；`git diff --check` 通过。
- 边界：候选包未经用户审核，不得绑定正式委托或参与状态派生。下一项是用户确认是否升级为 approved。


## Task 5：候选主张、分析失败和幂等重试

- 用户确认首个窄领域为“Python 正则表达式基础 v1”，标准包升级为 approved；`backend/app/standards.py` 会在独立学习库中按 owner 幂等种入标准成果、标准包和 criterion。
- 新增 `012_learning_evidence_claims.sql`：候选主张同时引用产出 ID、产出版本、事实事件 ID、criterion ID、dimension ID 和分析运行 ID，并记录立场、状态、来源、验证方式、独立条件与范围。
- 新增 `013_learning_evidence_follow_ups.sql`：支持人工复核请求和补充验证安排，保存请求键、说明、到期时间、状态和决定时间。
- 新增 `backend/app/evidence.py`：
  - `ProviderSemanticAnalyzer` 复用现有 Provider 配置执行语义分析，未配置 Provider 时返回可恢复的 `provider_unavailable`，不伪造 AI 主张。
  - `RegexDeterministicAnalyzer` 执行 `application` 维度的确定性正则检查。
  - `EvidenceService` 校验标准配方、生成候选主张、区分六类 AI 故障、记录失败审计、支持重试和同请求幂等。
  - 人工复核和补充验证仅创建 pending 跟进，不直接修改主张状态；执行归 Task 6。
- 新增分析 API：
  - `POST /api/learning/artifacts/{artifact_id}/analysis`
  - `GET /api/learning/evidence-claims`
  - `POST /api/learning/evidence-claims/{claim_id}/human-review`
  - `POST /api/learning/evidence-claims/{claim_id}/supplemental-verification`
  - `GET /api/learning/evidence-follow-ups`
- 前端事实工作台新增分析按钮、分析运行状态、候选主张卡、人工复核和补充验证入口，以及跟进状态；重复分析复用同一幂等键，不重复生成主张。
- Playwright Mock Provider 新增 `mock-evidence` 非流式 JSON 响应，用于验证真实 Provider 语义分析链路。
- 回放保留 `source='standard'` 的系统成果，避免已审核标准包被事实投影重建误删。

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：209 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：34 项通过，全部使用隔离数据目录。

实际变更：`backend/app/standards.py`、`backend/app/standards/python_regex_basics_v1.approved.json`、`backend/app/evidence.py`、`backend/app/main.py`、`backend/app/dependencies.py`、`backend/app/schemas.py`、`backend/app/routers/learning.py`、`backend/app/learning_service.py`、`backend/app/migrations/012_learning_evidence_claims.sql`、`backend/app/migrations/013_learning_evidence_follow_ups.sql`、`backend/app/core/learning.py`、`backend/tests/test_standard_package.py`、`backend/tests/test_evidence_claims.py`、`backend/tests/test_analysis_failures.py`、`backend/tests/test_learning_domain_schema.py`、`backend/tests/test_learning_facts_api.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/src/styles/dialogs.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、`frontend/e2e/ai-learning.spec.ts`、`scripts/mock-openai-provider.py`、标准包文档、本计划和开发状态文档。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：语义分析仅覆盖 `syntax_semantics` 维度，独立解释仍需人工复核执行；状态派生、采纳、质疑、撤回、替代和重算尚未实现。Task 5 不代表证据门正式验收通过，下一项为 Task 6。


## Task 6：状态派生、复核、质疑、撤回和重算

- 新增 `014_learning_derived_states.sql`：
  - `learning_derived_state` 保存当前派生状态。
  - `learning_derived_state_history` 保存每次计算的历史结果。
  - `learning_review_action` 保存采纳、质疑、撤回、替代和暂不处理动作。
- 新增 `backend/app/state_derivation.py`：
  - 按标准配方、维度、来源、独立条件和当前产出版本计算状态。
  - 区分 `awaiting_evidence`、`pending_review`、`insufficient_evidence`、`partially_supported`、`supported`、`contradicted`。
  - 保存参与主张、排除主张和排除原因。
  - 保存标准版本、计算版本和计算时间。
  - 矛盾证据返回 `contradicted`，不做正负抵消。
- 新增 `backend/app/review.py`：
  - 支持候选主张采纳、质疑、撤回、替代和暂不处理。
  - 采纳前校验主张是否满足标准配方。
  - 复核动作幂等并写入审计。
  - 质疑、撤回、替代和采纳后自动重算相关标准维度。
  - 产出更正后自动替代旧版本主张并重算状态。
- 新增 API：
  - `POST /api/learning/evidence-claims/{claim_id}/review`
  - `GET /api/learning/derived-states`
  - `GET /api/learning/derived-state-history`
  - `POST /api/learning/derived-states/recalculate`
- 前端事实工作台新增：
  - 采纳、质疑、撤回、暂不处理按钮。
  - 派生状态卡。
  - 状态、原因、标准版本、计算版本、参与数量、排除数量和排除原因。
  - 重算状态按钮。
  - 产出更正后自动替代旧主张并重算。
- 新增 `backend/tests/test_state_derivation.py` 和 `backend/tests/test_review_workflow.py`，覆盖候选/采纳/排除、矛盾证据、事实更正替代、状态历史、复核幂等、资格校验和质疑/撤回/替代。

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：217 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：35 项通过，全部使用隔离数据目录。

实际变更：`backend/app/state_derivation.py`、`backend/app/review.py`、`backend/app/migrations/014_learning_derived_states.sql`、`backend/app/main.py`、`backend/app/dependencies.py`、`backend/app/schemas.py`、`backend/app/routers/learning.py`、`backend/app/learning_service.py`、`backend/tests/test_state_derivation.py`、`backend/tests/test_review_workflow.py`、`backend/tests/test_learning_domain_schema.py`、`backend/tests/test_learning_facts_api.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、实施计划和开发状态文档。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：批量复核、显式替代关系、回访队列和证据门正式验收尚未实现。Task 6 只是状态派生与复核主链路，不代表证据门通过。下一项为 Task 6.1。


## Task 6.1：状态派生与复核收尾

- 新增 `015_learning_review_completion.sql`：
  - `learning_batch_review_action` 记录批量复核请求。
  - `learning_claim_replacement` 记录显式替代关系。
  - `learning_revisit_item` 记录质疑主张、证据不足状态和到期补充验证的回访项。
  - `learning_review_action` 增加 `replacement_claim_id`。
- `ReviewService` 新增：
  - 批量采纳/质疑/撤回/暂不处理。
  - 批量请求幂等。
  - 每条主张独立复核动作和审计。
  - 批量采纳仍逐条执行标准配方资格校验。
  - 用户替代必须指定同标准、同维度的替代主张。
- `EvidenceService` 在产出更正后的新分析完成时，自动为同维度旧主张写入显式替代关系。
- `StateDerivationService` 新增回访队列：
  - 质疑主张进入 `questioned_claim`。
  - 证据不足状态进入 `insufficient_state`。
  - 到期补充验证进入 `supplemental_verification`。
  - 状态重算时同步新增、取消或恢复回访项。
- 新增标准版本 2 的重算测试，证明标准版本不可原地修改；新增版本后可全量重算并保留旧版本状态。
- 前端事实工作台新增：
  - 批量采纳候选主张。
  - 批量质疑候选主张。
  - 替代关系展示。
  - 回访队列展示。
- 新增 `docs/progress/nautilus-evidence-gate-readiness-2026-09-07.md`，逐项记录 PRD 11.4.2 当前通过和未关闭项。

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：220 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：35 项通过，全部使用隔离数据目录。

实际变更：`backend/app/migrations/015_learning_review_completion.sql`、`backend/app/review.py`、`backend/app/state_derivation.py`、`backend/app/evidence.py`、`backend/app/routers/learning.py`、`backend/app/schemas.py`、`backend/app/learning_service.py`、`backend/tests/test_review_workflow.py`、`backend/tests/test_state_derivation.py`、`backend/tests/test_learning_domain_schema.py`、`backend/tests/test_learning_facts_api.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、实施计划、本记录、开发状态和证据门阶段验收记录。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：证据门整体仍未通过；普通删除、撤回、彻底删除、证据回放、权限 UX、指标和最终全量验收未实现。下一项为 Task 7。


## Task 7：普通删除、撤回、彻底删除、证据回放和权限 UX

- 新增产出生命周期命令：
  - `SoftDeleteArtifact`
  - `RestoreArtifact`
  - `WithdrawArtifact`
  - `PurgeArtifact`
- 新增事实事件类型：
  - `artifact.soft_deleted`
  - `artifact.restored`
  - `artifact.withdrawn`
  - `artifact.purged`
- 普通删除：
  - 保留原文和哈希。
  - 当前态标记 `soft_deleted`。
  - 证据状态标记 `withdrawn`。
  - 可恢复，恢复后重新参与状态计算。
- 撤回：
  - 不删除内容。
  - 只把证据适用性标记为 `withdrawn`。
- 彻底删除：
  - 必须输入 `PURGE` 确认。
  - 清空原文和内容哈希。
  - 写入 `purged_at`。
  - 当前态标记 `purged`。
  - 证据状态标记 `invalidated`。
  - 依赖主张全部失效。
  - 不可恢复。
- 前端提供影响预览：
  - 受影响主张数量。
  - 受影响派生状态数量。
  - 受影响回访项数量。
- 新增 `learning_evidence_event` 证据事件账本：
  - 记录主张创建、主张替代、复核、批量复核、状态派生、跟进创建。
  - 每个聚合维护版本和哈希链。
  - 支持证据回放。
- 新增 `EvidenceEventService.replay`：
  - 校验事件链。
  - 重建主张、复核、批量复核、替代、状态和跟进。
  - 回放后根据当前产出状态恢复 `invalidated` / `withdrawn`。
  - 刷新回访队列。
- 权限与隐私：
  - 彻底删除后 owner 读取返回 `content=null`、`content_hash=null`。
  - 跨身份读取返回 404。
  - Agent 权限申请不包含产出原文。
- 新增测试：
  - `test_artifact_lifecycle.py`
  - `test_privacy_deletion.py`
  - `test_evidence_replay.py`
- 新增 Playwright：
  - `frontend/e2e/nautilus-first-slice-lifecycle.spec.ts`
  - 覆盖普通删除、恢复、撤回、彻底删除、主张失效和证据回放。

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：227 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离数据目录。

实际变更：`backend/app/core/commands.py`、`backend/app/core/events.py`、`backend/app/core/learning.py`、`backend/app/evidence.py`、`backend/app/evidence_events.py`、`backend/app/review.py`、`backend/app/state_derivation.py`、`backend/app/learning_service.py`、`backend/app/routers/learning.py`、`backend/app/schemas.py`、`backend/app/migrations/012_learning_evidence_claims.sql`、`backend/app/migrations/016_learning_evidence_events.sql`、`backend/app/main.py`、`backend/app/dependencies.py`、`backend/tests/test_artifact_lifecycle.py`、`backend/tests/test_privacy_deletion.py`、`backend/tests/test_evidence_replay.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-lifecycle.spec.ts`、`frontend/e2e/fact-helpers.ts`、实施计划和本记录。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：缓存、搜索索引和产品级备份清理当前没有对应实现对象；现有恢复工具是测试夹具，不是产品备份。证据门整体验收和指标归 Task 8。下一项为 Task 8。


## Task 8：指标、全量验证和交接

- 新增 `backend/app/measurements.py`：
  - 固定指标口径版本 `1.0`。
  - 统计产品价值指标：
    - 中断后正确恢复委托比例。
    - 复核到下一行动完成率。
    - 证据可追溯率。
  - 统计硬性护栏：
    - 无依据主张率。
    - AI 失败时产出保存成功率。
    - 事件重建一致性。
    - 权限违规次数。
    - 隐私泄露次数。
  - 零分母返回 `no_sample`，不显示为 0% 或 100%。
  - 权限不足、等待验证和未实现的恢复/下一行动链接不伪造样本。
- 证据回写：
  - `EvidenceReplay` 成功和失败均写入 `learning_audit`。
  - 事件重建一致性基于事实回放与证据回放审计统计。
- 新增 API：
  - `GET /api/learning/metrics`
- 前端事实工作台新增“首片指标”卡，展示产品指标、硬性护栏、状态、数值和统计范围。
- 新增 `backend/tests/test_measurements.py`，覆盖：
  - 无样本标记。
  - 证据可追溯率。
  - 无依据主张率。
  - AI 失败保存成功率。
  - 证据回放一致性。
  - 断链导致重建护栏失败。
- 新增最终交接记录：
  - `docs/progress/nautilus-first-slice-final-acceptance-2026-09-08.md`

验证命令：

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：230 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离数据目录。

实际变更：`backend/app/measurements.py`、`backend/app/evidence_events.py`、`backend/app/main.py`、`backend/app/dependencies.py`、`backend/app/routers/learning.py`、`backend/tests/test_measurements.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、最终验收记录、实施计划、本记录和开发状态文档。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

最终结论：计划内 Task 0-8 已完成。事实门通过；证据门工程链路通过，整体产品验收仍有后续边界，见最终验收记录。下一项不应继续扩张本计划，应先由用户决定后续阶段。


## Task 9：真实标准包与 Provider 正式化

- 真实标准包沿用已审核的 `python-regex-basics-v1`：
  - 来源为 Python 官方 `re` 文档。
  - 版本为 1，审核人为 product-owner。
  - 包含语法语义、应用能力和独立解释三个维度。
  - 合成标准仍只存在于测试夹具，不进入生产状态派生。
- 新增 `017_learning_evidence_provider.sql`：
  - 保存每个 owner 的当前证据分析 Provider / 模型选择。
  - 不保存 API Key 或凭据引用。
- 新增 `018_learning_analysis_provider_snapshot.sql`：
  - 为成功分析运行保存非敏感 Provider / 模型快照。
  - 字段包含选择来源、Provider ID、模型 ID、实际模型名、Provider 类型、配置版本、超时和 Prompt schema 版本。
  - 不包含 API Key、credential key、Authorization 或用户原文副本。
- 新增 `EvidenceProviderService`：
  - 无显式选择时使用默认 Provider。
  - 显式选择保存前校验 Provider、模型和密钥可用。
  - 显式选择失效时失败关闭，不静默回退默认 Provider。
  - 支持恢复默认 Provider。
  - 返回非敏感运行快照。
- 修改 `ProviderSemanticAnalyzer` 和 `EvidenceService`：
  - 语义分析使用证据分析专用 Provider。
  - 成功运行持久化 Provider / 模型快照。
  - 分析请求继承所选 Provider 的超时配置。
  - 不自动重试；用户使用同一 `request_key` 手动重试，成功后重复请求不再次出站。
- 新增 API：
  - `GET /api/learning/evidence-provider`
  - `PUT /api/learning/evidence-provider`
  - `DELETE /api/learning/evidence-provider`
- 前端事实工作台新增“证据分析 Provider”设置卡：
  - 显示当前默认 / 独立配置。
  - 支持选择已有 Provider 和模型并保存。
  - 支持恢复默认 Provider。
  - 所选配置失效时提示分析将失败，不显示误导性的默认回退。
  - 分析运行列表显示实际模型和默认 / 独立配置来源。
- 新增测试：
  - `backend/tests/test_evidence_provider.py`
  - 覆盖默认回退、显式选择、更新、清除、无效配置、失败关闭、跨身份、未授权、运行快照、切换后历史保留、超时和人工重试幂等。
  - 扩展 `016 -> 018` 隔离库升级测试。

验证命令：

```bash
timeout 60s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_evidence_provider.py
timeout 60s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_learning_domain_schema.py
```

以及逐个运行全部 24 个后端测试文件。

结果：后端合计 238 项通过；存在 1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`backend/app/evidence_provider.py`、`backend/app/evidence.py`、`backend/app/conversations.py`、`backend/app/routers/learning.py`、`backend/app/schemas.py`、`backend/app/main.py`、`backend/app/dependencies.py`、`backend/app/learning_service.py`、`backend/app/migrations/017_learning_evidence_provider.sql`、`backend/app/migrations/018_learning_analysis_provider_snapshot.sql`、`backend/tests/test_evidence_provider.py`、`backend/tests/test_learning_domain_schema.py`、`backend/tests/test_learning_facts_api.py`、`backend/tests/test_evidence_claims.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、`frontend/e2e/v6-workspace.spec.ts`、实施计划、本记录、产品决策记录和开发状态文档。未修改 `001`-`010`，未打开默认主库，未启动交付服务。

已知边界：失败运行暂不保存 Provider 快照；Provider 配置历史依赖每次成功分析的运行快照，当前选择表只保存最新值。下一项为 Task 10 Agent 权限批准与最小上下文。

## Task 10：Agent 权限批准与最小上下文

- 新增 `019_agent_permission_grants.sql`：
  - 为批准后的读取授权建立独立 grant 表；
  - 保存 owner、request、agent、scope、target、读取粒度、状态、授权时间、过期时间、撤销时间和原因；
  - 同一 owner + agent + target 只允许一个 active grant；
  - 未修改 `001`-`011`，只在隔离测试库验证。
- 权限生命周期：
  - pending 申请可批准、拒绝；
  - active 授权可撤销；
  - 授权和申请过期后不再返回授权产出；
  - 撤销或过期后可通过新的 request key 再次申请；
  - 批准只扩大读取范围，不新增任何写入、委托或事实确认路径。
- 审计：
  - 申请、批准、拒绝、撤销和过期均写入 `learning_audit`；
  - 用户批准、拒绝和撤销的 actor 记录为用户身份；
  - Agent 申请和系统过期保留明确 actor 语义。
- 新增 API：
  - `POST /api/learning/agent/permission-requests/{request_id}/approve`
  - `POST /api/learning/agent/permission-requests/{request_id}/revoke`
  - `GET /api/learning/agent/context`
- Agent 上下文：
  - 全局默认上下文只包含行动摘要、状态、委托数量和证据引用，不包含原文或主张陈述；
  - 行动级默认上下文包含行动摘要、委托、会话、证据引用和结构化分析限制；
  - metadata 授权只增加授权产出元数据，不返回 `content`；
  - full_text 授权只返回目标学习行动下产出原文；
  - denied / expired / revoked 状态下说明分析未完成及不可用范围，不返回原文；
  - 跨身份、未登录和目标外行动读取均不可获得原文。
- 前端事实工作台：
  - Agent 权限卡支持选择 metadata / full_text、发起申请、批准、拒绝、撤销和再次申请；
  - 显示申请范围、读取粒度、TTL、过期时间和授权状态；
  - 显示当前全局或行动级 Agent 上下文摘要、证据引用数量和不可用范围；
  - 明确拒绝后仍可继续学习和保存产出，Agent 只能基于已授权摘要继续。
- 测试：
  - 后端覆盖申请、批准、拒绝、撤销、过期、再次申请、审计 actor、未登录、跨身份、默认上下文、metadata/full_text、目标隔离、证据引用、彻底删除后原文不恢复；
  - Playwright 覆盖 full_text 申请、批准、上下文预览、撤销、再次申请和拒绝路径。
- 数据边界：
  - 后端和 Playwright 均使用隔离临时数据库；
  - 默认主库 `data/nautilus.sqlite3` 未打开、未迁移；
  - 真实学习库 `data/learning.sqlite3` 未应用 `012`-`019`；
  - 未启动交付服务，未操作 `diagnostic-backups/`。

验证命令：

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：248 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`agent_runtime.py`、`routers/learning.py`、`schemas.py`、`019_agent_permission_grants.sql`、`test_agent_permission_runtime.py`、`test_learning_domain_schema.py`、`test_learning_facts_api.py`、`frontend/src/api.ts`、`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、实施计划、本记录和开发状态文档。

已知边界：`GET /agent/context` 是本阶段的确定性上下文预览和未来 Agent 输入契约，还不是完整外部 Agent 执行环境；完整学习教练消费链路留到 Task 17A/17B。Task 10 只关闭 PRD 11.4.2 第 11-13 条，证据门整体仍需 Task 12 和 Task 11 收尾。

精确下一项：Task 12 实现事件版本支持范围、未知版本明确拒绝和回放失败保护；不为验收发明生产事件版本 2。

## Task 12：事件版本兼容策略与回放硬化

- 未发明生产事件版本 2；当前事实事件和证据事件语义版本均固定为 1。
- 事实事件：
  - 在 `core/events.py` 中建立 `SUPPORTED_EVENT_VERSIONS = {1}` 显式版本注册表；
  - 事件写入、投影应用和事实回放统一使用该注册表；
  - 未知版本继续返回 `event_version_unsupported`，且不覆盖现有投影。
- 证据事件：
  - 新增 `020_evidence_event_schema_version.sql`，为 `learning_evidence_event` 增加 `schema_version`，默认 1；
  - 保留 `016` 中的 `event_version` 作为聚合内顺序，避免改写历史事件和既有哈希；
  - `schema_version` 独立校验，当前仅支持 1；
  - `EvidenceEventService.append` 拒绝未登记的 aggregate/event 类型组合；
  - 证据回放在删除投影前校验语义版本、事件哈希、事件类型、payload 必需字段、聚合内顺序和 previous hash；
  - 投影重建、purge/withdraw 状态修正和成功审计在同一事务内完成；
  - 校验或应用失败返回结构化 409，写拒绝审计并保留现有投影；
  - `020` 为证据事件表增加禁止 UPDATE / DELETE 的 append-only 触发器；
  - 迁移测试覆盖 016 旧事件升级后 `schema_version=1` 且旧哈希仍可按 v1 规则验证。
- 错误语义：
  - `evidence_event_version_unsupported`
  - `evidence_event_integrity_failed`
  - `evidence_event_type_unsupported`
  - 既有 `evidence_event_chain_invalid`
- 测试：
  - 事实回放已有未知版本拒绝测试；
  - 证据回放新增 unsupported schema version、篡改哈希、未知事件类型、断链、payload 缺字段和未知类型写入拒绝测试；
  - 新增 append-only 触发器测试和失败审计断言；
  - 所有失败场景均验证现有投影不被覆盖。
- 数据边界：
  - `020` 只在隔离测试库验证；
  - 默认主库未打开、未迁移；
  - 真实学习库仍未应用 `012`-`020`；
  - 未启动交付服务，未操作 `diagnostic-backups/`。

验证命令：

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：254 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`core/events.py`、`core/learning.py`、`evidence_events.py`、学习路由、`020_evidence_event_schema_version.sql`、`test_evidence_replay.py`、`test_learning_domain_schema.py`、`test_learning_facts_api.py`、`test_measurements.py`、实施计划、本记录和开发状态文档。

已知边界：本任务只建立版本兼容与拒绝策略；未来确实引入事件版本 2 时，必须另行制定显式升级器、迁移范围、回滚方案和版本化测试，不得复用本任务结论。

精确下一项：Task 11 实现复核卡权限可见范围，并在 Task 10 与 Task 12 均已关闭的基础上逐条复核 PRD 11.4.2 全部 14 条，完成证据门最终验收。

## Task 11：复核卡权限可见范围与证据门验收

- 复核卡新增“复核依据可见范围”：
  - 显示用户是否可查看原始产出；
  - 显示 Agent 是仅有摘要、状态和证据引用，还是已获目标行动原文授权；
  - 显示原始产出和事实事件引用；
  - 显示缺少原文授权时的分析限制。
- 明确用户无需批准 Agent 原文读取即可：
  - 暂不处理候选主张；
  - 请求人工复核；
  - 安排补充验证。
- 复核卡本身不向 Agent 上下文传递原文或未授权摘录；Agent 上下文仍由 Task 10 的最小授权边界控制。
- Playwright 新增验证：
  - 默认 Agent 无原文授权；
  - 复核卡显示权限限制；
  - 用户可以暂不处理；
  - 用户可以请求人工复核；
  - 用户可以安排补充验证；
  - 以上路径不要求用户授权。
- 新增 `docs/progress/nautilus-evidence-gate-final-acceptance-2026-09-10.md`，逐项记录 PRD 11.4.2 14 条验收状态。
- 结论：证据门整体产品验收通过；这不是完整 PRD V2 或完整长期学习协作者完成声明。

验证命令：

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：254 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`frontend/src/FactWorkspace.tsx`、`frontend/src/styles/fact-workspace.css`、`frontend/e2e/nautilus-first-slice-facts.spec.ts`、证据门最终验收记录、实施计划、本记录和开发状态文档。

数据边界：未修改业务数据库；默认主库未打开、未迁移；真实学习库未应用 `012-020`；未启动交付服务；未操作 `diagnostic-backups/`。

精确下一项：Task 13A 实现指标采集、口径、观察窗口、删除失效或单列规则和隐私边界。

## Task 13A：指标采集、口径与隐私硬化

- 指标版本从 1.0 升级为 2.0。
- 固定复核到下一行动的观察窗口为 7 天；报告窗口明确为“所有记录至报告时间，观察窗口 7 天”。
- `MetricResult` 新增 `excluded` 计数字段，用于单列：
  - `awaiting_first_selection`
  - `window_pending`
  - `invalidated_by_purge`
  - `cancelled_follow_up`
- 中断后正确恢复委托比例：
  - 从 `session.ended` 事实事件中识别 `disposition=interrupted`；
  - 以中断后用户首次启动的会话作为恢复选择；
  - 首次选择原委托计为成功；
  - 尚无首次选择时单列为 `awaiting_first_selection`，不伪装成失败。
- 复核到下一行动完成率：
  - 以已创建的人工复核 / 补充验证 follow-up 作为已处理复核事项；
  - 通过主张、产出、会话和委托追溯到学习行动；
  - 观察窗口内同一行动的后续已完成会话计为下一行动完成；
  - 窗口未满且尚未完成时单列为 `window_pending`；
  - follow-up 取消单列为 `cancelled_follow_up`；
  - 彻底删除或主张失效后单列为 `invalidated_by_purge`，不进入分母。
- 证据可追溯率与无依据主张率：
  - 彻底删除导致失效的主张不进入当前分母；
  - 失效数量单列为 `invalidated_by_purge`；
  - 历史统计不成为保留私人内容的理由。
- 隐私边界：
  - 指标查询不返回原始产出、凭据、Cookie、API Key 或私密摘录；
  - AI 失败保存检查只查询内容是否存在和哈希是否存在，不加载原文内容；
  - 新增响应扫描测试，确认私有输出、`sk-` 和 `Authorization` 不出现在指标报告中。
- 前端指标卡显示单列原因和数量，不把单列样本伪装成通过或失败。
- 顺手修复一个既有 Playwright 竞态：流式文本可见后等待 `active_run` 变为空，再断言消息数量。

验证命令：

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：259 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`measurements.py`、`test_measurements.py`、前端指标类型与事实工作台、指标样式、`ai-learning.spec.ts`、实施计划、本记录和开发状态文档。

数据边界：未新增迁移；未修改任何数据库；默认主库未打开、未迁移；真实学习库未应用 `012-020`；未启动交付服务；未操作 `diagnostic-backups/`。

已知边界：Task 13A 只完成指标工程和隔离验证，真实使用样本尚未产生；Task 13B 必须在用户授权的真实环境启用后采集。

精确下一项：Task 14 制定并执行生产学习库升级与真实环境启用方案；未获用户明确授权前不得迁移、不得启动服务。

## Task 14：生产学习库升级与真实环境启用（数据层）

- 用户已明确授权生产学习库备份、初始化/升级、完整性校验和恢复演练。
- 操作前发现 `data/learning.sqlite3` 不存在；此前“真实学习库停留在 011”的状态记录与当前文件系统不一致。
- 由于不存在既有学习库，本轮没有升级前数据可迁移，而是初始化新的空生产学习库并直接应用 `011-020`。
- 新增 `backend/app/learning_production.py` 和 `scripts/upgrade-learning-database.py`：
  - 显式授权 required；
  - 拒绝默认主库与 `diagnostic-backups/`;
  - 支持验证、初始化/升级、备份和恢复；
  - 恢复前阻止备份复活当前已彻底删除的产出；
  - 当前库缺失时默认拒绝恢复。
- 生产学习库：
  - 路径 `data/learning.sqlite3`;
  - 权限 `0600`;
  - 迁移 `011-020`;
  - `integrity_check=ok`;
  - `foreign_key_check=ok`;
  - `up_to_date=true`.
- 备份：
  - `data/backups/learning/learning-post-initialization-20260909T170636Z.sqlite3`;
  - 对应 JSON 清单权限 `0600`;
  - SHA-256 `04b8b6196f3af9254306623625c4eadf5a91ecd2818e27a469cdc00226640f93`.
- 恢复演练：
  - 恢复到 `/tmp` 隔离目标；
  - 迁移历史一致；
  - 完整性与外键校验通过；
  - 临时目标自动清理。
- 彻底删除保护：
  - 当前生产库无用户产出，`purged_artifacts_with_content=0`;
  - 隔离测试覆盖“备份试图恢复已彻底删除内容时拒绝恢复”。
- 默认主库：
  - 未打开、未迁移；
  - 操作前后 `data/nautilus.sqlite3`、WAL 和 SHM 文件大小与修改时间均未变化。
- 服务：
  - 未启动；
  - 当前 WSL2 实际 IP 为 `172.17.253.105`;
  - 后续预期 Web `http://172.17.253.105:5173`，API `http://172.17.253.105:8000`;
  - 启动需用户单独授权。
- README 新增生产学习库验证、初始化/升级、备份与恢复说明。

验证命令：

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：262 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

实际变更：`learning_production.py`、`scripts/upgrade-learning-database.py`、`test_learning_production_upgrade.py`、README、生产学习库操作记录、实施计划、本记录和开发状态文档；另创建 Git 忽略的生产学习库与本地备份文件。

已知边界：Task 14 数据层完成，服务启用与真实使用基线采集尚未执行。

精确下一项：用户明确授权后启动交付服务，并进入 Task 13B 真实使用基线采集。

## Task 14 服务启用与 Task 13B 启动

- 用户确认继续后，交付服务已通过 `scripts/start.sh` 启动。
- 服务绑定：
  - 后端 `0.0.0.0:8000`;
  - 前端生产预览 `0.0.0.0:5173`。
- WSL2 实际 IP：
  - `172.17.253.105`。
- 当前访问地址：
  - Web `http://172.17.253.105:5173`;
  - API `http://172.17.253.105:8000`。
- 健康检查：
  - `GET /api/health` 返回 200；
  - 服务状态 `ok`;
  - 主数据库连接 `ok`。
- 前端首页返回 200；
- 前端生产页面不包含 `/@vite/client`，无 HMR 自动刷新；
- 后端与前端日志未见 traceback、critical 或 error。
- 服务启动后再次验证生产学习库：
  - `011-020` 全部应用；
  - `integrity_check=ok`;
  - `foreign_key_check=ok`。
- 服务启动按既有机制将默认主库从 `001-004` 应用到 `001-010`：
  - 未应用 `011+` 学习域迁移；
  - 默认主库 `integrity_check=ok`。
- 已创建默认主库启动后备份：
  - `data/backups/main/nautilus-post-service-start-20260909T171618Z.sqlite3`;
  - SHA-256 `a37affb1ac5c27ece31997046f407a64f5b585c66105d0d50fb6dc6776a1ef1c`。
- 已知边界：本轮未创建默认主库应用 `005-010` 前的备份；启动后备份已如实记录。
- Task 13B 已开始，但生产学习库尚无用户授权身份和真实学习行动，因此暂无真实使用样本。
- 不使用自动化测试或脚本生成“真实使用样本”；等待用户通过 Web 入口进行真实学习、保存产出、复核和恢复操作。

## Task 15A：目标初始化与新领域工作轴最小闭环

- 用户可以从自然语言学习目标开始，选择 AI 整理或手动起步，编辑草案并确认。
- 一次确认命令创建目标、计划、任务、可验证成果和学习委托，并提供直接进入学习会话的下一步。
- 新增 `backend/app/learning_setup.py`、引导式设置 API、`frontend/e2e/guided-setup.spec.ts` 和迁移 `021_learning_guided_setup.sql`；迁移仅在隔离测试库验证，未自动迁移生产学习库或默认主库。
- 修复同一任务再次进入 AI 学习室时保留当前会话 ID，并在恢复前校验任务/目标范围，避免恢复到其他任务或独立会话。
- 本任务只完成新领域工作轴最小闭环，不包含完整模块编辑、成果图、路径图、教练、模型策略、人格/学习模式、知识包治理或统一工作台。
- 验证：Task 15A 后端定向测试 `10 passed`；事实 API 定向测试 `4 passed, 1 warning`；前端生产构建通过；Playwright 全量 `37 passed`；`git diff --check` 通过。
- 本轮后端全量测试未完成：一次从错误目录运行失败，改用正确 `PYTHONPATH` 后长时间无输出并已停止；因此不将本轮后端全量标记为通过。交付服务随后已重新启动于 `0.0.0.0:5173/8000`。
- 精确下一项：先由用户完成真实学习流程以采集 Task 13B 基线；之后进入 Task 15 综合成果与成果图。

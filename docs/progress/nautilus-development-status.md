# 学海无涯（Nautilus）开发进度与 Agent 交接文档

> 本文件是 Nautilus 当前开发状态的单一事实入口。
>
> 所有接手开发的 Agent 必须先阅读正式规格，再阅读本文件。每次完成开发、改变数据库、调整运行方式或修改下一步计划后，都必须在结束前更新本文件。

| 项目 | 当前值 |
| --- | --- |
| 最后更新 | 2026-08-06，Asia/Shanghai |
| 项目目录 | `/home/kingdom/ai_learning` |
| 正式规格 | `docs/superpowers/specs/2026-07-23-nautilus-design.md` |
| 历史概念 | `docs/archive/concepts/2026-07-19-eduflow-concept-v1.md`，仅用于理解演化 |
| 当前开发结论 | 计划信息架构纵切片已按正式规格落地：全部计划总览、单计划概览/结构/排期、文档式大纲与单一内联编辑器、可逆任务完成、计划日历筛选，以及 `global / plan / task` 分级 AI 上下文均已实现。新增迁移 `009_task_completion_restore.sql` 与 `010_ai_conversation_scope.sql`，仅在隔离数据库验证；默认数据库仍停留在 `001`-`004`。 |
| 当前推荐下一步 | 新窗口先讨论 Nautilus 的整体产品定位、首批目标用户、核心使用闭环、真正可宣传的亮点，以及全局/计划/任务 AI 的产品边界；该讨论阶段默认不修改代码。默认数据库 `005`-`010` 迁移演练仍是后续工程任务，未经用户明确确认不得应用迁移。 |

## 1. 后续 Agent 更新规则

每次开发结束前必须更新本文件中的以下内容：

1. `最后更新` 日期。
2. 本轮实际完成的功能和修改文件。
3. 数据库迁移版本；已经应用的迁移禁止原地修改，只能新增迁移。
4. 测试命令和结果。
5. 当前 Git 状态、运行地址和服务状态。
6. 新发现的缺陷、技术债和阻塞项。
7. 下一位 Agent 可以直接执行的第一项任务。
8. 在底部“更新记录”追加一条记录。

禁止把以下内容写入本文件：

- 启动访问令牌。
- AI API 密钥。
- Cookie、会话令牌或其他凭据。
- 用户学习内容全文。

## 2. 必须遵守的产品边界

- 产品中文名是“学海无涯”，英文名和工程代号是 `Nautilus`。
- 首阶段只做 WSL2 中运行的 Web MVP。
- 前端使用 React、TypeScript、Vite；后端使用 FastAPI、Python 模块化单体。
- 服务必须绑定 `0.0.0.0`。
- Windows 宿主机访问说明必须使用 WSL2 实际 IP，不能使用回环地址作为交付地址。
- SQLite 使用 WAL、外键和迁移；搜索使用 FTS5。
- AI 流式文本使用 SSE，计时和状态更新使用 WebSocket。
- AI 工作流使用 LangGraph。
- 不引入 Redis、Celery、Milvus、CrewAI 或多个常驻 Agent 进程。
- AI 写入正式数据前必须生成预览并等待用户确认。
- 不允许模型执行 Shell、任意 Python、网络爬取或未定义外部工具。
- API 密钥不能进入数据库、日志、备份包或对话内容。
- 首阶段不实现云同步、P2P、CRDT、桌面封装或 Android 客户端。

正式规格与本文件冲突时，以正式规格和用户最新指令为准。

## 3. 当前 Git 与工作区状态

2026-08-06 已按用户明确要求建立本地 Git 检查点，当前实现不再处于大面积未提交状态。新增提交：

```text
f48da8d feat(backend): implement local learning and AI services
0560a99 feat(frontend): build the Nautilus learning workspace
953be34 chore: add local runtime and repository workflow
8ffea0a docs: record Nautilus product and implementation decisions
```

本进度文档由随后独立的检查点提交保存。完成该提交后，本地 `main` 领先 `origin/main` 5 个提交；用户明确要求暂不上传云端，因此没有执行 `git push`。

`diagnostic-backups/` 也是未跟踪目录，但不属于 Nautilus，实现过程中没有修改它。该目录包含其他系统的诊断数据库、日志和配置，可能涉及敏感信息：

- 不要执行 `git add .`。
- 不要把该目录纳入 Nautilus 提交。
- 不要删除或改写该目录，除非用户明确要求。

后续提交仍必须使用精确路径暂存，不得把 `diagnostic-backups/` 纳入任何提交。

## 4. 当前运行状态快照

2026-08-06 当前核对：

- 上一轮隔离 production preview `5196/8022/8023` 当前已离线；这是进程生命周期结束，不代表代码回归。需要页面复验时必须重新启动新的 `/tmp/nautilus-*` 隔离 preview。
- 上一轮隔离数据库曾应用 `001`-`010` 并通过 `integrity_check=ok`；临时运行环境不得视为长期用户数据。
- 当前 WSL2 实际 IP 为 `172.17.253.105`。
- 标准 Web/API 仍约定为 `http://172.17.253.105:5173` 与 `http://172.17.253.105:8000`，本轮没有启动标准服务，也没有写入默认数据库。
- 默认 `data/nautilus.sqlite3` 只读核对仍为 `001_initial`-`004_plan_editor`，`integrity_check=ok`。
- 后端由 `scripts/start.sh` 启动，绑定 `0.0.0.0:8000`。
- 前端构建后由 `vite preview` 绑定 `0.0.0.0:5173`，启用 `--strictPort`，不加载 HMR 客户端。
- 当前访问令牌位于 `tmp/access-token`，权限为仅当前用户可读；不要把令牌写入文档。未授权页通过 `GET /api/auth/challenge` 以 `no-store` 响应提供当前进程码，用于同码二维码和文字码展示。
- 后端访问日志已关闭，`tmp/backend.log` 只保留启动和应用日志。
- `scripts/start.sh` 会拒绝首页包含 `/@vite/client` 的错误运行模式，防止开发服务器再次作为用户交付服务。

当前真实 SQLite 数据库不是空库。核对时仅记录数量，不记录用户内容：

- 本地身份：1 个；浏览器会话记录：8 条。
- 学习目标、科目、主题和任务：各 3 个；本轮仅以只读方式核对并一律按用户真实数据保留。
- 学习会话：2 条。
- 当前首页布局：模块顺序为任务、计时、概览、上下文；上下文模块隐藏。
- 个人布局模板：0 个（系统模板 3 个）。

这些数据视为用户数据。后续自动化测试不得删除、覆盖或复用 `data/nautilus.sqlite3`。

## 5. 已应用数据库迁移

当前实际数据库已应用：

```text
001_initial
002_learning_plans
003_dashboard_layouts
004_plan_editor
```

重要规则：仓库现有迁移 `001`-`010` 均不得原地修改。任何新的模式变更必须从 `011_*.sql` 开始；默认数据库仍只应用 `001`-`004`。

### `001_initial`

- `local_identity`
- `sessions`
- 本地身份、设备 ID、会话哈希和过期时间

### `002_learning_plans`

- `learning_goal`
- `subject`
- `topic`
- `task`
- `study_session`
- 任务类型、固定/灵活排期、计时预设和进度字段
- 单个本地身份只能有一个运行中或暂停中的学习会话

### `003_dashboard_layouts`

- `layout_config`
- `layout_template`
- 三套系统模板：今日学习驾驶舱、专注执行、路线回顾

### `004_plan_editor`

- 为 `learning_goal`、`subject`、`topic`、`task` 新增 `deleted_at` 软删除字段。
- 新增活动节点索引，读取计划树、今日驾驶舱和任务归属查询均排除软删除节点。
- 默认用户数据库已在 2026-07-30 正常启动时应用该迁移；未修改 `001`–`003`。

工作区已经存在但默认用户数据库尚未应用 `005_ai_conversations.sql`。该迁移已修正，并在临时数据库中完成应用、约束和失败原子回滚测试；它会建立：

- `provider_profile`
- `conversation`
- `conversation_link`
- `message`
- `context_snapshot`
- `ai_run`

本轮新增 `006_ai_message_reasoning.sql`，为 `message` 增加独立的 `reasoning_content` 字段，用于保存 provider 明确返回的推理内容并支持断线恢复。隔离手测库已应用 `001`–`006`；默认数据库仍只应用 `001`–`004`，只读复核 `integrity_check=ok`。`001`–`005` 均未修改。启动默认服务前必须先由用户确认数据备份和迁移时机，自动化测试不得触碰默认库。

后续隔离实现已继续新增并验证：

- `007_ai_multi_provider_model_selection`：多个 provider profile、provider model、分层配置和 Chat Run 脱敏快照。
- `008_ai_conversation_titles`：持久化标题、Title Run、修订号与失败状态。
- `009_task_completion_restore`：保存任务完成前状态/进度，支持精确撤销完成。
- `010_ai_conversation_scope`：持久化 `independent / global / plan / task` 对话范围与运行快照范围。

默认数据库尚未应用 `005`-`010`。本轮只在自动创建的 `/tmp/nautilus-playwright.*` 数据库中执行和验证这些迁移，`001`-`008` 均未修改。

尚未建立正式规格中的以下表：

- `task_dependency`
- `schedule_entry`
- `branch`
- `approval_request`
- 资料、知识卡片、学习记录和 FTS5 表
- 通知、后台任务、备份记录和领域变更日志

## 6. 已经实现并可运行的功能

### 6.1 基础运行

- React + TypeScript + Vite 前端。
- FastAPI 本地服务。
- `/api/health` 健康检查。
- WSL2 实际 IP 探测脚本。
- 前后端统一启动脚本。
- 标准启动脚本先执行生产构建，再运行无 HMR 的 `vite preview`；开发服务器仅用于单独开发，不作为用户交付方式。
- 服务绑定 `0.0.0.0`。
- Vite 端口严格占用检查。
- 后端关闭访问日志，避免把代理来源写入访问日志。
- favicon 已声明，不再产生默认图标 404。

### 6.2 SQLite 和本地身份

- SQLite WAL。
- SQLite 外键。
- 顺序 SQL 迁移机制。
- 首次启动创建本地身份和设备标识。
- 每次服务进程启动生成随机访问令牌。
- 令牌写入权限为 `0600` 的运行时文件。
- 浏览器授权后使用 `HttpOnly`、`SameSite=Strict` Cookie。
- 授权状态、当前身份和注销接口；会话 Cookie 默认持久保存，直到用户主动注销，服务重启不会要求重复授权。
- 授权页显示当前进程实时码：上方二维码和下方文字码使用完全相同的内容；每次服务启动轮换一次。

### 6.3 四层计划纵切片

已实现的数据层级：

```text
学习目标
  -> 科目
    -> 主题
      -> 任务
```

当前“手动创建计划”表单会在一个事务中创建一条完整的初始链：

- 一个学习目标。
- 一个科目。
- 一个主题。
- 一个首个可执行任务。

任务支持：

- 学习、练习、复习、知识产出四种类型。
- 固定日程和灵活进度。
- 日期范围。
- 可选具体开始和结束时间。
- 预计学习分钟数。
- 任务状态、进度、完成时间和逾期判断。

当前已增加统一计划编辑器纵切片：

- 目标、科目、主题和任务均支持新增与编辑。
- 同级节点支持上移、下移和完整 ID 列表排序。
- 四层节点均支持软删除；存在活动计时时拒绝删除对应分支。
- 手动创建计划后自动进入计划编辑器，继续修改同一条四层路线。
- 计划编辑器采用左侧结构航线、右侧当前节点表单，桌面和移动端均有响应式布局。

这仍然只是计划阶段的可运行纵切片；独立任务列表、基础筛选、月历和手动按天重排已完成，提醒、AI/依赖重排和身份时区语义尚未完成。

### 6.4 独立任务列表、重排和月历

- 独立任务列表返回目标、科目、主题和任务四层上下文。
- 支持关键词、状态、类型、排期方式和日期范围筛选。
- 支持任务按天延期或提前，固定开始和结束时间同步平移。
- 重排复用计划编辑器事务和计划日期边界校验；已完成和已取消任务不能重排。
- 月历按任务日期范围显示任务，支持月份切换和点击回到今日任务上下文。
- 当前只完成手动单任务纵切片；AI 建议、批量重排、依赖联动和完整甘特图仍未实现。

### 6.5 今日学习驾驶舱

- 当前日期和完成进度。
- 今日任务数量。
- 计划时长和已记录时长。
- 今日任务队列。
- 当前任务的目标、科目、主题、任务路径。
- 任务选择和默认一键完成。
- 空状态和创建计划入口。
- 桌面工作区和移动单列响应式布局。

### 6.6 学习计时

- 25/5。
- 50/10。
- 自定义番茄钟。
- 普通正计时。
- 开始、暂停、继续、结束。
- 一键完成任务时结束活动会话。
- WebSocket 每秒发送计时快照。
- 番茄钟根据累计秒数计算专注和休息阶段。
- 同一本地身份只允许一个活动计时。

### 6.7 首页布局

- 今日概览、今日任务、专注计时、任务位置四个模块。
- 模块显示和隐藏。
- 使用上下按钮调整模块顺序。
- 三套系统模板可应用，系统模板不能覆盖、重命名或删除。
- 当前布局可以另存为个人模板。
- 个人模板支持应用、重命名和删除。
- 应用模板后仍可继续修改。

### 6.8 当前前端入口

- 本地授权页。
- 今日工作区。
- 独立任务列表。
- 计划树视图。
- 月历视图。
- 手动计划创建对话框。
- 首页布局设置对话框。
- 甘特图入口可见但处于禁用状态。
- AI 快速生成和引导式规划入口可见但处于开发中状态。
- 计划编辑器入口：统一编辑目标、科目、主题和任务四层节点。

### 6.9 AI 学习最小可用纵切片（已实现，尚非完整阶段）

- `CredentialStore` 使用成熟的 `cryptography.Fernet`，凭据目录位于 `NAUTILUS_DATA_DIR/runtime/credentials`，目录/文件权限分别为 `0700`/`0600`；对外 API 只返回掩码或非敏感配置。
- 仅支持一个 OpenAI Chat Completions 风格兼容适配器；provider、model、base URL、启用状态和配置版本进入 SQLite，API key 只进入 CredentialStore；提供连接测试和错误状态记录。
- 普通线性 `conversation`、追加式 `message`、任务/计划 `conversation_link`、`context_snapshot` 和 `ai_run` 已落地；运行状态可区分 `queued/running/succeeded/failed/canceled`，并冻结本次请求使用的 provider 配置。
- 消息发送通过 SSE 增量返回；支持取消、浏览器断开后后台继续、同一运行重连重放、重复提交幂等和同一客户端 ID 不同正文冲突。
- 前端新增当前任务上下文的最小“与 AI 学习”入口、学习室、provider 设置对话框、流状态、取消、错误/重试和刷新恢复；本轮学习室和管理工作区复用了 V6 视觉 token，但没有伪造尚未实现的知识源或分支能力。
- 学习室输入支持 `Enter` 发送、`Shift+Enter` 换行，并避开输入法组合态；助手回答通过 `react-markdown` 与 `remark-gfm` 安全渲染标题、列表、表格、引用和代码，不执行原始 HTML。
- provider 设置支持聚焦模型框时通过后端代理发现 `/models`、前后端短期缓存、显式刷新、下拉选择和手动模型名；连接测试会先打开模型选择弹窗，允许用当前未保存表单配置测试，成功状态在按钮右侧以绿色显示，并为已测试模型显示绿色圆形勾。
- 仅展示 provider 明确返回的 `reasoning_content`、`reasoning` 或 `<think>` 内容；推理与最终正文分流保存，生成中低对比度展开，完成后默认折叠。不会展示、推断或伪造未由 API 返回的隐藏思维链。
- 学习室头部、上下文栏和输入区已压缩，消息区占据剩余高度；桌面、窄桌面和移动端均使用独立消息滚动区，不通过扩大页面高度容纳回答。
- 新增隔离 Mock provider 与 Playwright 流程，覆盖正常完成、provider 错误、用户取消、刷新恢复和重复提交；自动化不调用真实 AI API，也不输出秘密。

本轮明确没有实现：对话分支图、知识源连接器、FTS5、知识卡片/学习记录正式写入、AI 计划生成/重排、多个原生提供方和复杂 LangGraph 工作流。因此本节只能描述为一个可验证的最小纵切片，不能描述为 AI 阶段或首阶段完成。

## 7. 当前 API

### 基础与授权

```text
GET    /api/health
GET    /api/auth/challenge
GET    /api/auth/status
POST   /api/auth/authorize
POST   /api/auth/logout
GET    /api/me
```

### 计划、任务和计时

```text
GET    /api/plans
GET    /api/tasks
POST   /api/plans/manual
PATCH  /api/plans/{goal_id}
DELETE /api/plans/{goal_id}
POST   /api/plans/{goal_id}/subjects
PUT    /api/plans/{goal_id}/subjects/order
PATCH  /api/subjects/{subject_id}
DELETE /api/subjects/{subject_id}
POST   /api/subjects/{subject_id}/topics
PUT    /api/subjects/{subject_id}/topics/order
PATCH  /api/topics/{topic_id}
DELETE /api/topics/{topic_id}
POST   /api/topics/{topic_id}/tasks
PUT    /api/topics/{topic_id}/tasks/order
PATCH  /api/tasks/{task_id}
POST   /api/tasks/{task_id}/reschedule
DELETE /api/tasks/{task_id}
GET    /api/dashboard/today
POST   /api/tasks/{task_id}/complete
POST   /api/tasks/{task_id}/timer
WS     /api/ws/timers/{task_id}
```

### 首页布局

```text
GET    /api/layout
PUT    /api/layout
GET    /api/layout/templates
POST   /api/layout/templates
POST   /api/layout/templates/{template_id}/apply
PATCH  /api/layout/templates/{template_id}
DELETE /api/layout/templates/{template_id}
```

### AI 学习最小纵切片

```text
GET    /api/ai/provider
PUT    /api/ai/provider
DELETE /api/ai/provider
POST   /api/ai/provider/test
POST   /api/ai/provider/models
GET    /api/ai/conversations
POST   /api/ai/conversations
GET    /api/ai/conversations/{conversation_id}
GET    /api/ai/tasks/{task_id}/context
POST   /api/ai/conversations/{conversation_id}/messages
GET    /api/ai/runs/{run_id}/stream
POST   /api/ai/runs/{run_id}/cancel
```

## 8. 主要代码边界

### 后端

- `backend/app/main.py`：应用生命周期、服务组装和 Router 注册。
- `backend/app/db.py`：SQLite 连接、配置、迁移和事务边界。
- `backend/app/auth.py`：本地身份、运行时令牌和浏览器会话。
- `backend/app/plans.py`：计划树、今日驾驶舱、任务完成和计时状态机。
- `backend/app/plan_editor.py`：四层计划节点 CRUD、排序、软删除和写事务。
- `backend/app/routers/`：系统、授权、计划和布局 API 路由。
- `backend/app/layouts.py`：首页布局和模板生命周期。
- `backend/app/credentials.py`：本地加密凭据文件、权限和掩码边界。
- `backend/app/providers.py`：OpenAI Chat Completions 兼容提供方适配器。
- `backend/app/model_discovery.py`：OpenAI 兼容模型发现、缓存键和 10 分钟进程内缓存。
- `backend/app/conversations.py`：提供方配置、普通线性对话、任务上下文、消息和运行持久化。
- `backend/app/ai_runtime.py`：后台 AI 运行、SSE 订阅、重放和取消。
- `backend/app/routers/ai.py`：AI 提供方、对话、上下文、流和取消 API。
- `backend/app/schemas.py`：Pydantic 输入模型。
- `backend/app/migrations/`：SQL 迁移。

### 前端

- `frontend/src/App.tsx`：启动、健康状态和授权页面。
- `frontend/src/Workspace.tsx`：工作区状态、导航、数据加载和弹窗编排。
- `frontend/src/TodayView.tsx`：今日任务、计时、概览和四层上下文模块。
- `frontend/src/PlanEditor.tsx`：统一四层计划编辑器。
- `frontend/src/TaskListView.tsx`：独立任务列表、筛选和手动按天重排。
- `frontend/src/CalendarView.tsx`：42 格月历、月份切换和任务落点。
- `frontend/src/PlanDialog.tsx`：手动创建初始计划链。
- `frontend/src/LayoutDialog.tsx`：模块和布局模板设置。
- `frontend/src/AiLearningRoom.tsx`：当前任务上下文、输入快捷键、Markdown 回答、显式推理折叠、SSE 状态、取消和刷新恢复。
- `frontend/src/AiCompanionPanel.tsx`：V6 管理态右侧 AI 学习伙伴侧栏。
- `frontend/src/AiProviderDialog.tsx`：可编辑模型组合框、模型发现缓存、临时配置测试和绿色测试状态；密钥只保留在内存表单。
- `frontend/src/FloatingTimer.tsx`：活动计时悬浮窗、拖动、最小化和恢复。
- `frontend/src/api.ts`：前端 API 类型和请求封装。
- `frontend/src/styles.css`：样式入口。
- `frontend/src/styles/`：基础、工作区、计划编辑器和对话框样式。
- `frontend/src/styles/v6-workspace.css`：V6 三栏壳层、航海图 token、折叠/拖动、伙伴侧栏和悬浮计时器。
- `frontend/e2e/ai-learning.spec.ts`：隔离 AI 浏览器流程。
- `scripts/mock-openai-provider.py`：不记录请求密钥或正文的本地 SSE Mock provider。
- `scripts/test-start-e2e-safety.sh`：临时数据目录路径安全回归测试。

当前文件规模已按本轮边界拆分：

- `backend/app/main.py`：约 97 行。
- `backend/app/plans.py`：约 685 行，包含计划汇总/详情/排期读模型、任务列表和完成恢复领域逻辑；继续新增依赖算法前应拆分读模型与任务命令。
- `backend/app/plan_editor.py`：约 333 行。
- `backend/app/conversations.py`：约 2032 行，已明显超出单一边界；下一次扩展 AI 上下文或历史能力前，应优先按 provider 配置、对话读写、上下文构建和运行准备拆分。
- `frontend/src/Workspace.tsx`：约 574 行，包含 V6 壳层、视角导航、计时和分级 AI 入口状态。
- `frontend/src/PlanEditor.tsx`：约 287 行，仅保留可复用计划/节点/任务表单和确认弹窗；结构编排已移到约 342 行的 `PlanStructure.tsx`。
- `frontend/src/AiLearningRoom.tsx`：约 1133 行，下一次进入分支、知识源或高级历史管理前必须先拆分工具栏、历史层、消息运行和配置层。
- `frontend/src/styles/`：按职责拆分，入口约 7 行。

下一阶段开发应在功能边界明确时拆分路由和前端模块，避免继续把所有功能堆入这些文件。

## 9. 测试与验证状态

2026-08-05 最新完整验证，以下结果覆盖并替代本节较早的测试基线：

- 后端全量：`114 passed, 1 warning`。警告仍为 Starlette TestClient/httpx 弃用提示。
- 前端 production build：成功，`2069 modules transformed`；仅有既有的单 chunk 超过 500kB 警告。
- Playwright 全量：`31 passed`，全部使用自动创建并清理的 `/tmp/nautilus-playwright.*` 数据目录。
- 计划工作区定向 Playwright：`8 passed`，覆盖总览、单一任务编辑器、dirty 三选一保护、新建失败保留输入、计划设置关闭保护、计划日历筛选的后退/前进/刷新、1024/390 AI 抽屉关闭和三档无页面级溢出。
- `bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh`：通过。
- `bash scripts/test-start-e2e-safety.sh`：通过。
- `.venv/bin/pip check`：`No broken requirements found`。
- `git diff --check`：通过。
- 真实 Chromium production preview 截图复核：`1440x1000`、`1024x640`、`390x844` 的 `scrollWidth/scrollHeight` 均等于视口；计划总览、结构无默认编辑器、单一内联编辑器、dirty 弹窗、计划筛选日历和 AI 抽屉均无重叠或文字截断。截图只写入 `/tmp/nautilus-visual-plan-ia-1785941304`。
- 默认数据库只读核对为 `001`-`004` 且 `integrity_check=ok`；隔离预览库为 `001`-`010` 且 `integrity_check=ok`。

2026-08-02 本轮最终验证：

```bash
timeout 150s env PYTHONPATH=backend .venv/bin/python -m pytest -q
```

结果：

```text
87 passed, 1 warning
```

警告来自当前 FastAPI/Starlette TestClient 对 `httpx` 的弃用提示，不影响现有测试结果，但后续应升级测试依赖或迁移到推荐客户端。

后端测试在既有 CredentialStore、迁移原子性、普通对话、上下文快照、SSE、取消、断线恢复和幂等覆盖之外，新增模型列表解析、临时表单配置、模型发现缓存、显式推理流分离、推理持久化与重放覆盖。

前端构建：

```bash
npm --prefix frontend run build
```

结果：成功，2063 个模块完成转换；当前 production preview 资源为 `/assets/index-BsZgZyPS.js` 和 `/assets/index-HebGp4zr.css`。

其他本轮已验证项目：

- 最终所有前端改动完成后，使用独立端口直接运行完整 Playwright 为 `16 passed`，覆盖交付稳定性、计划/任务/日历、工作区视口稳定性和 AI 正常流/取消/错误/刷新/幂等；新增覆盖 Enter/Shift+Enter、GFM 语义节点、模型发现缓存/选择/测试/绿色勾、显式推理完成折叠/刷新恢复和学习室密度。缓存指纹改动完成时也曾运行 AI 定向套件，结果为 `6 passed`。
- `bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh`、`bash scripts/test-start-e2e-safety.sh`、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 所有自动化使用独立临时数据库和本地 Mock HTTP，未调用真实 AI API，未记录凭据或真实用户学习内容。
- 真实 production preview 截图检查 `1440x1000`、`1024x900`、`390x844`：三档文档尺寸均等于当前视口，无页面级纵向/横向溢出；AI 头部约 `57/51/50px`，消息主区约 `641/551/496px`，输入区约 `126/126/119px`，移动端返回/设置收敛为带无障碍名称的图标按钮。三档均确认 Markdown 标题、列表、表格和代码正常，推理在完成后折叠，控制台错误为零。
- provider 模型测试弹窗已在真实页面检查，候选模型、手动输入和测试确认均处于当前视口内；成功状态和绿色圆形勾由 Playwright 自动化验证。
- 当前 WSL2 实际 IP 为 `172.17.253.105`；隔离 production preview `5186`、API `8012` 和 Mock provider `8013` 保持运行，标准 `5173/8000` 未启动。
- 默认数据库只读核对通过：`integrity_check=ok`，迁移仍仅为 `001_initial` 至 `004_plan_editor`；`005`、`006` 只在隔离库中验证。

Playwright 数据目录使用真实路径校验，拒绝路径穿越、已有目录和符号链接；安全回归脚本确认受保护目录不会被删除或复用。

## 10. 尚未实现的首阶段功能

### 10.1 计划阶段未完成

- 应用内提醒和浏览器通知。
- 任务延期和重排策略已完成基础手动按天平移纵切片；AI 建议重排和批量依赖重排仍未实现。
- 软删除回收站和恢复规则。
- 精确按身份时区计算“今天”。

### 10.2 AI 学习最小纵切片（本轮已交付；完整 AI 阶段仍未开始）

- 本轮已完成 `CredentialStore`、一个 OpenAI 兼容适配器、提供方配置冻结、跨存储补偿、SSE/取消/幂等和最小前端学习室；完整 AI 阶段仍未开始。
- Google Gemini 原生适配器。
- Anthropic Claude 原生适配器。
- 全局模型和工作流专用模型配置。
- 明示模型回退。
- LangGraph 工作流。
- AI 快速生成计划。
- AI 对话式引导规划。
- 上下文预览后端已实现；上下文移除尚未实现。
- `approval_request` 和写入确认流程。
- SSE 后端和前端真实链路已由隔离 Mock provider Playwright 验证；真实外部 provider 仍需用户主动配置后手动连接测试。

### 10.3 对话和分支仅完成线性基础

- 普通线性对话、任务主关联、消息、上下文快照和 AI 运行已由前后端最小入口接入。
- `branch` 数据模型和所有分支功能尚未实现。
- 从历史消息创建分支。
- 窄轨分支图。
- 全屏 React Flow 画布。
- 移动端分支抽屉。

### 10.4 资料和知识未开始

- PDF、Markdown、TXT 导入。
- 本地资料库复制和哈希。
- 文本层 PDF 解析。
- SQLite FTS5。
- 历史消息、资料和知识卡片搜索。
- 知识卡片、大纲和学习记录。
- Markdown 编辑、预览和导出。
- Obsidian、飞书、本地受控文件夹和云存储连接器不在 2026-07-23 原规格的首版导入范围内，是 2026-08-01 用户新增方向；连接权限、同步方式和写回边界仍待正式扩展设计确认。

### 10.5 排期和质量未开始或只完成基础部分

- 完整甘特图。
- FS、SS、FF、SF 依赖。
- 提前量和延迟量。
- 循环依赖检测。
- 自动快照、手动备份和恢复。
- 后台任务执行器。
- 错误恢复模式。
- 完整 Playwright 业务覆盖（甘特图、提醒、计时恢复、备份恢复等）。
- 大数据性能测试。
- 备份恢复测试。

## 11. 已知问题和技术债

### P0：接手前必须注意

1. **实现尚未提交。** 当前代码全部是未跟踪文件，容易被误删，也缺少可审查的提交边界。
2. **真实数据库包含数据。** 不得再使用默认 `data/` 目录执行破坏性浏览器测试。
3. **没有备份功能。** 当前用户数据还没有自动快照和恢复能力。
4. **`diagnostic-backups/` 不属于项目且可能敏感。** 禁止整体暂存工作区。

### P1：计划阶段必须修复

1. 计划总览、详情、结构和排期纵切片已经实现；仍缺少回收站恢复、批量编辑、依赖联动和完整甘特图，不得把当前纵切片表述为计划阶段全部完成。
2. 后端“今日”使用服务进程的 `date.today()`，没有根据身份的 `timezone` 计算。
3. `planned_start` 和 `planned_end` 主要依赖前端转换为 UTC，后端没有统一的 UTC 标准化边界。
4. `study_session` 保存精确秒数，但任务的 `actual_minutes` 使用整数分钟累加，短于一分钟的会话显示为 0 分钟。
5. 运行中的计时在服务停机期间仍可能按墙上时间继续累计，需要明确重启恢复策略。
6. 番茄钟阶段是根据累计时间动态推导的，没有持久化阶段切换和通知。
7. 任务完成会结束活动会话，但没有独立“取消计时”操作。
8. 计划编辑器写接口已实现；任务列表、基础筛选、月历和手动单任务重排已加入，但尚未提供回收站恢复、批量编辑和依赖联动。
9. 番茄钟功能仍在 `TodayView.tsx`，默认真实布局也将计时模块设为可见；但它仍是可排序/可隐藏的窄模块，未作为当前学习会话的核心控制器，视觉层级不足，用户实际未感知到该入口。
10. V6 管理态三栏壳层、左栏折叠、限定拖动、AI 学习伙伴侧栏和活动悬浮计时器已落地；完整知识库、分支画布、跨视角 AI 诊断和 V6 学习室三栏内容仍未实现。

### P2：结构和测试债务

1. 已建立正式 Playwright 套件，仍缺少完整业务端到端覆盖（甘特图、计时恢复、授权撤销等）。
2. 计划界面已拆分为 `PlanWorkspace`、`PlanOverview`、`PlanStructure`、`PlanSchedule` 和可复用表单；后续新增依赖/甘特功能时应继续保持这些边界，避免重新堆回单文件。
3. 测试有一条 Starlette/httpx 弃用警告。
4. 没有 OpenAPI 契约快照、性能基准或数据库回滚测试。
5. 本轮按用户明确要求把会话改为主动注销前持续有效，这与原规格 5.1 的“短期会话”表述存在偏差；正式发布前需要补充安全设置、会话撤销和规格修订说明。
6. 标准运行方式曾错误使用 Vite 开发服务器，导致修改源码时用户浏览器被 HMR 热更新或整页刷新；已修复，事故复盘见 `docs/progress/retrospectives/2026-07-30-vite-hmr-browser-refresh.md`。
7. `005`-`010` 已在临时库验证，但默认用户数据库仍未应用；真实 provider 连接未在本轮自动化中调用，避免秘密泄露和外部费用。模型发现按 OpenAI 兼容 `/models` 约定实现，不兼容的提供方仍需手动填写模型名。

## 12. 对上一阶段工作的反思

以下问题是上一位 Agent，也就是本文件首次整理者，在开发方式上做得不好的地方：

1. **阶段完成度表述过满。** 实际只完成了计划纵切片，却在交付中使用了接近“计划阶段完成”的说法。以后必须明确写“可运行纵切片”或“完整阶段”。
2. **偏离开发顺序。** 在完整计划编辑器尚未完成时，提前进入并完成了首页布局模板。虽然布局本身符合规格，但下一步必须回到计划编辑器补齐基础能力。
3. **没有及时建立交接文档。** 只更新 README 和聊天说明，不足以支持多个 Agent 连续开发。
4. **没有建立提交检查点。** 大量新增文件处于未跟踪状态，增加了丢失、误暂存和接手困难的风险。
5. **端到端验证不可复用。** 因项目未安装 Playwright，使用了 `/tmp` 中的临时 Chromium DevTools 脚本，验证结果无法由下一位 Agent 一条命令复现。
6. **曾使用真实数据库创建验证数据。** 虽然当时清理了已知测试记录，但这种做法本身不正确。以后必须使用临时 `NAUTILUS_DATA_DIR`。
7. **文件边界控制不够。** `main.py`、`Workspace.tsx` 和 `styles.css` 在短时间内快速膨胀，后续功能再叠加会显著降低可维护性。
8. **最终汇报缺少当前数据状态。** 只描述代码和测试，没有把数据库非空、当前布局和未提交状态作为接手风险突出说明。

改进要求：

- 每轮先定义本轮验收边界，再编码。
- 每轮结束更新本文件。
- 区分“已实现”“只完成基础纵切片”“尚未开始”。
- 浏览器测试使用独立临时数据目录。
- 已应用迁移保持不可变。
- 在继续新增大功能前拆分过大的模块。
- 提交或暂存时使用精确路径，不使用全工作区暂存。

## 13. 下一位 Agent 的推荐工作顺序

计划信息架构纵切片已实现并建立本地 Git 检查点。下一窗口优先完成产品层决策，不要因为代码已经可运行就直接扩展功能：

1. **先讨论产品定位。** 明确 Nautilus 最核心的问题、首批目标用户和长期价值，区分“AI 学习管理工具”“备考执行系统”和“个人学习操作系统”等方向的收益与风险。
2. **提炼真实亮点。** 基于现有计划层级、执行闭环、本地优先和全局/计划/任务 AI，区分真正差异化、基础功能、可宣传能力和当前不能宣传的未来能力。
3. **明确三级 AI 的产品边界。** 讨论用户是否直接看到“全局/计划/任务 AI”、三者如何切换、哪些操作可以建议、哪些写入必须确认，以及如何避免上下文重复。
4. **定义核心日常闭环。** 从查看整体状态、选择下一项、任务执行、AI 辅助、计时、完成到复盘和计划调整，判断当前哪些环节已经成立，哪些仍只是页面能力拼接。
5. **产品决策确认后再排工程顺序。** 默认数据库 `005`-`010` 迁移演练、身份时区、计时恢复和回收站仍是重要工程任务，但不应抢在整体方向讨论之前。完整甘特、任务依赖、附件、Web Search、思考强度和自定义请求继续单独设计。

### 下一位 Agent 可以直接执行的第一项任务

新窗口先阅读以下文件并总结真实产品状态，然后与用户讨论整体方向和亮点，默认不修改代码：

```text
docs/superpowers/specs/2026-07-23-nautilus-design.md
docs/progress/nautilus-development-status.md
docs/superpowers/specs/2026-08-04-nautilus-plan-information-architecture-design.md
docs/superpowers/plans/2026-08-05-nautilus-plan-information-architecture-implementation.md
docs/superpowers/specs/2026-08-01-nautilus-ai-learning-minimal-slice-design.md
docs/superpowers/specs/2026-08-03-nautilus-conversation-management-layout-design.md
```

讨论至少输出：推荐产品定位、首批目标用户、3-5 个真实亮点、核心日常闭环、三级 AI 边界和后续优先级。用户确认方向前不要创建新功能规格、修改代码、启动默认数据库迁移、提交、推送或部署。

## 14. 远期规划，当前不要实现

- 云端同步。
- P2P、CRDT 和复杂冲突合并。
- Windows 桌面封装。
- Android 客户端。
- 远程 AI 业务服务。
- Embedding 和向量数据库。
- `.xmind` 输出。
- 分支合并和文本级 Diff。
- 资源约束、容量平衡和最优排程。

## 15. 更新记录

### 2026-07-29

- 建立本交接文档。
- 重新核对 Git、运行服务、数据库迁移、真实数据数量和当前布局。
- 明确基础运行可用，计划/计时/布局为可运行纵切片，完整首阶段仍未完成。
- 记录未提交风险、真实数据库测试风险、结构债务和下一步工作顺序。
- 最后测试结果：后端 12 项通过；前端生产构建通过。
- 已生成供新窗口直接使用的完整接手提示词；本轮未修改业务代码、数据库迁移或服务运行状态。

### 2026-07-30

- 修复 `.venv`：补齐 `pip`、FastAPI、Uvicorn、pytest 和 httpx 依赖，后端测试统一使用 `.venv/bin/python`。
- 新增不可变迁移 `004_plan_editor`，为四层计划节点增加软删除字段和活动索引；默认用户数据库已应用该迁移，现有数据数量未改变。
- 新增 `PlanEditorService`、计划 CRUD/排序/软删除 API 和对应 Router；`main.py` 保留生命周期与 Router 注册，`plans.py` 保留读取、驾驶舱、完成和计时。
- 前端新增 `PlanEditor.tsx`、`TodayView.tsx`，拆分工作区与样式边界，加入 `lucide-react`，完成统一四层计划编辑器和手动创建后自动进入编辑器。
- UI 重做为冷白工作台、海绿主操作和左侧航线结构；Chromium 临时隔离数据库验证桌面 `1440x1000`、移动 `390x844` 无横向溢出，控制台错误和网络失败均为零。
- 本轮验证：`.venv/bin/python -m pytest -q` 结果 `16 passed, 1 warning`；`npm --prefix frontend run build` 成功；脚本语法、Git 空白检查和 WSL2 实际 IP 请求均通过。
- 当前仍是可运行纵切片，不代表完整计划阶段或首阶段完成；下一项是正式 Playwright 套件和计划阶段剩余的任务列表/日历/时区能力。
- 根据用户授权体验要求，新增实时授权挑战接口和授权页二维码/文字码双展示；授权码每次服务启动轮换，二维码内容与文字码完全一致。
- 会话 Cookie 改为长期持久保存，数据库会话仅在主动注销时撤销；增加挑战接口的 `no-store` 响应头、复制授权码入口和当前授权码自动填入入口。
- 同步更新正式规格 5.1 和 `README.md` 的授权说明，明确持久会话、启动轮换码和二维码/文字码同值规则。
- 本轮验证：后端 `16 passed, 1 warning`；前端构建成功，`1803` 个模块；独立临时数据目录 Chromium 验证授权页桌面/移动端无横向溢出、无控制台错误和网络失败；默认服务已在 WSL2 `172.17.253.105` 的 8000/5173 重新启动。
- 本轮仍未实现二维码授权之外的账号体系、跨设备同步或云端登录；当前授权码对能访问本地 Web 的设备可见，这是本地 MVP 的已知安全边界。

### 2026-08-01

- 修复浏览器间歇性自动刷新：根因是 `scripts/start.sh` 把 Vite 开发服务器作为标准用户服务，源码变化通过 `/@vite/client` HMR WebSocket 触发热替换或整页 reload。
- `scripts/start.sh` 改为启动前构建前端，再以 `vite preview` 提供生产资源；增加前端就绪检查和 `/@vite/client` 防回归检测，发现开发客户端时拒绝启动。
- `frontend/vite.config.ts` 新增 preview 的 API 与 WebSocket 代理配置；`README.md` 明确开发服务器不得作为用户交付运行方式。
- 新增事故复盘 `docs/progress/retrospectives/2026-07-30-vite-hmr-browser-refresh.md`，记录现象、根因、漏检原因、修复和六条防复发规则。
- 验证：后端 `16 passed, 1 warning`；前端生产构建成功，`1803` 个模块；脚本语法和 `git diff --check` 通过；35 秒 Chromium 观察中无 HMR WebSocket、无额外导航、无网络失败，页面状态标记保持不变。
- 数据库迁移没有变化，默认用户计划和学习会话数据未被测试修改；本轮浏览器验证没有执行数据库写操作。
- 下一项仍是把临时 Chromium 验证收敛为仓库内正式 Playwright 套件，并加入“交付页面禁止 HMR 客户端”的自动断言。

### 2026-08-01（任务列表、日历与 Playwright）

- 新增 `GET /api/tasks` 独立任务列表查询，支持关键词、状态、任务类型、排期方式和日期范围筛选，并返回目标/科目/主题上下文。
- 新增 `POST /api/tasks/{task_id}/reschedule` 手动按天平移任务日期；固定开始/结束时间按 UTC 平移，复用计划编辑器事务和计划日期范围校验，已完成/已取消任务拒绝重排。
- 新增前端 `TaskListView.tsx`：任务搜索、状态/类型/排期/日期筛选、完成操作和延期/提前控件。
- 新增前端 `CalendarView.tsx`：42 格月历、任务覆盖日期、状态色和点击回到今日上下文。导航中的任务和日历入口由禁用状态改为可用；甘特图仍未实现。
- 新增 `frontend/styles/task-calendar.css` 并接入现有样式入口，桌面和移动端分别处理筛选布局、任务表和月历横向浏览。
- 新增后端测试覆盖任务列表筛选/搜索/日期范围与重排事务边界；后端结果 `18 passed, 1 warning`。
- 正式 Playwright 套件扩展到 4 项：生产首页禁止 `/@vite/client`/React Refresh、授权后 5 秒零意外导航与非应用 WebSocket、隔离数据库任务筛选/重排/月历流程、移动任务/月历页面无页面级横向溢出；结果 `4 passed`。
- Playwright 使用 `frontend/playwright.config.ts`、`frontend/e2e/` 和 `scripts/start-e2e.sh`，每次使用 `/tmp/nautilus-playwright.*`，不读写默认 `data/nautilus.sqlite3`。
- 本轮修改文件：`.gitignore`、`README.md`、`backend/app/plans.py`、`backend/app/plan_editor.py`、`backend/app/routers/plans.py`、`backend/app/schemas.py`、`backend/tests/test_plans.py`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/playwright.config.ts`、`frontend/e2e/delivery-stability.spec.ts`、`frontend/e2e/global-teardown.ts`、`frontend/src/api.ts`、`frontend/src/Workspace.tsx`、`frontend/src/TaskListView.tsx`、`frontend/src/CalendarView.tsx`、`frontend/src/styles.css`、`frontend/src/styles/task-calendar.css`、`scripts/start-e2e.sh` 和本进度文档。
- 数据库迁移：无新增；`001_initial`–`004_plan_editor` 均未修改，下一次结构变更必须从 `005_*.sql` 开始。
- 前端生产构建成功（1805 modules transformed）；`bash -n`、`git diff --check` 通过。标准 `5173` 首页只引用 `/assets/index-*.js`，不含 `/@vite/client`，`8000/api/health` 返回 `ok`。
- 默认数据库未被本轮自动化写入；只读核对仍为 WAL、`integrity_check=ok`、迁移 `001_initial` 至 `004_plan_editor`，数量为 `local_identity=1`、`sessions=8`、`learning_goal=2`、`subject=2`、`topic=2`、`task=2`、`study_session=2`、`layout_config=1`、`layout_template=3`。
- 工作区仍包含此前未提交实现与 `diagnostic-backups/` 未跟踪目录；本轮没有修改、删除或暂存该目录，也没有提交/推送/部署。
- 当前仍是计划阶段可运行纵切片，不代表计划阶段或首阶段完成。
- 下一项：修正身份时区下的“今日”和秒级学习时长统计，随后补提醒/通知、回收站恢复和更完整的计划质量测试。

### 2026-08-01（AI 学习信息架构复核）

- 重新核对正式规格：AI 对话与学习辅导并非遗漏，规格将其列入首阶段能力，并在 AI 阶段/对话阶段实现；当前 MVP 尚未实现对应数据模型、提供方、LangGraph、SSE、分支和审批流程。
- 发现当前页面仅暴露今日/任务/计划/日历/甘特视图，缺少 AI 学习的首页入口和与当前任务上下文的连接；这属于当前 MVP 的信息架构缺口，不修改正式规格既定方向。
- 已启动可视化伴随页面，展示 A 今日双栏工作台、B 路线画布底部 AI 抽屉、C 今日入口 + 全屏 AI 学习室三种方案；当前推荐 A+C 混合，等待用户确认后再写设计方案和实现计划。
- 本轮没有修改业务代码、数据库迁移或默认数据库；没有提交、推送、部署，也没有修改/删除/暂存 `diagnostic-backups/`。
- 下一项：根据用户对视觉方案和“常驻侧栏/全屏学习室/新窗口”选择的反馈，形成经确认的 AI 学习入口与统一计划视图设计，再开始编码。

### 2026-08-01（番茄钟与外部知识源设计补充）

- 用户确认采用 A+C：今日页保留可直接对话的 AI 学习伙伴，长对话展开到同一浏览器内的独立 AI 学习室；不默认强制打开新的浏览器窗口。
- 复核现有实现确认番茄钟没有被删除：`frontend/src/TodayView.tsx` 仍包含 25/5、50/10、自定义番茄钟和普通计时，默认真实布局也显示计时模块；当前问题是计时仍属于可隐藏窄模块、视觉层级不足，且没有贯穿 AI 学习室。
- 新可视化方案将番茄钟提升为“全局当前学习会话”控制器：今日页顶部显示当前任务、剩余时间、暂停和完成本轮；进入 AI 学习室后变成持续可见的紧凑计时坞。
- 用户新增 Obsidian、飞书、本地文件和云存储知识源方向。建议使用“来源连接器 -> 统一文档模型 -> FTS 检索/上下文选择 -> AI 对话与知识卡片”的适配架构，而不是把各软件仅作为外链。
- 当前推荐首版外部知识源只读：AI 只能检索和引用用户选中的资料，生成内容先保存为 Nautilus 草稿；逐个连接器的外部写回作为后续能力，必须有独立权限和用户确认。该权限边界尚待用户最终确认。
- 本轮新增的可视化伴随文件位于已忽略的 `.superpowers/brainstorm/16155-1785554666/content/pomodoro-knowledge-architecture-v2.html`；业务代码、正式规格、数据库迁移、默认数据库和运行服务均未修改。
- 本轮仅做设计复核和只读代码检查，没有重新运行后端测试、前端构建或 Playwright；最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功和 Playwright `4 passed`。
- 修改文件：本进度文档，以及 Git 已忽略的可视化伴随 HTML；没有提交、推送、部署，也没有修改、删除或暂存 `diagnostic-backups/`。
- 下一项：用户确认“外部知识源首版只读”或“允许写回”后，写新的正式扩展设计文档并请用户审阅；设计批准前不新增业务代码或 `005` 迁移。

### 2026-08-01（协作原则与 MVP 前端策略）

- 根据用户反馈，将“主动判断、指出风险、给出替代方案，不机械接受用户建议”写入 `AGENTS.md` 的协作与工程判断规则；同时补齐已应用 `004_plan_editor` 迁移的保护范围。
- 当前产品判断：不应继续无边界堆叠后端功能，也不应先做脱离真实流程的长期视觉精装修。推荐先暂停新增大模块，完成统一工作区的信息层级、番茄钟主入口、AI 学习入口和一套可复用视觉规范，再用真实 AI 学习闭环验证。
- MVP 的前端质量目标不是“功能能显示”或“最终商业级全量精致”，而是核心路径清晰、视觉层级稳定、响应式可用、状态反馈完整、无明显占位感；非核心甘特高级交互和全面视觉打磨可后置。
- 本轮修改文件：`AGENTS.md`、本进度文档。没有修改业务代码、正式规格、数据库迁移、默认数据库或运行服务；没有修改、删除或暂存 `diagnostic-backups/`。
- 测试：本轮为协作规则和产品策略更新，未重新运行测试；最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。
- 下一项：在用户确认“先做统一工作区骨架校正，再做 AI 最小闭环”的推进顺序后，写该范围的正式设计/实施计划；设计批准前不直接编码新的大模块。

### 2026-08-01（统一工作区高保真视觉方向）

- 按“先校正统一工作区骨架与视觉语言，再开发 AI 最小闭环”的顺序继续设计，没有直接修改业务实现。
- 新增三套使用相同真实信息架构的高保真视觉方向：A“纸上航线”采用深海蓝、暖纸色和赤陶色，强调长期阅读与航海日志气质；B“精密研究台”强调高密度和工具效率；C“深海专注”强调暗色沉浸和当前学习会话。
- 当前专业推荐为 A，并保留 B 的精确对齐与信息密度：它在产品辨识度、长时间阅读、复杂计划界面可扩展性和 MVP 实现成本之间最平衡；不建议纯暗色覆盖所有计划管理页面。
- 三套方案都明确把番茄钟作为当前学习会话主控，把任务/计划/日历/甘特作为同一工作区内部视角，并保留今日 AI 侧栏、全屏学习室和只读知识源上下文。
- 新可视化文件位于 Git 已忽略的 `.superpowers/brainstorm/16155-1785554666/content/unified-workspace-visual-directions-v3.html`，可通过当前视觉伴随地址查看并点击选择。
- 修改文件：本进度文档，以及 Git 已忽略的可视化伴随 HTML。业务代码、正式规格、迁移、默认数据库和运行服务均未修改；没有修改、删除或暂存 `diagnostic-backups/`。
- 测试：本轮仅为视觉设计，未运行后端测试、前端构建或 Playwright；最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。可视化页面已通过本地 HTTP 返回并包含三套方向标题。
- 下一项：收集用户对 A/B/C 的选择及具体偏好，迭代一版最终视觉方向；确认后写正式统一工作区与 AI/知识源扩展设计文档，完成审阅门槛后才开始业务代码。

### 2026-08-01（A 视觉 + C 布局的多页面系统 v4）

- 用户明确选择 A 的暖纸色、深海蓝与赤陶色视觉语言，但偏好 C 的空间布局；同时要求番茄钟不横穿整个界面、不打断最右侧 AI 区，并要求设计今日、任务、计划、日历、甘特、知识库和沉浸 AI 学习室等多个页面状态。
- 将统一工作区重构为三栏设计：左侧全局导航；中间承载今日/任务/计划/日历/甘特的内部视角；右侧保持完整的 AI 学习准备台。番茄钟放在中间标题区右上角的紧凑模块，不再占据整页横幅。
- 主动修正此前“首页侧栏承载完整长对话”的建议：管理态右侧 AI 区改为准备台，显示当前任务、知识源、上次会话和输入；用户发送第一条学习消息、继续会话或点击“与 AI 学习”后，才进入沉浸学习室。
- 沉浸学习室采用暗色三栏：左侧会话/分支，中间长对话，右侧知识源/引用；番茄钟缩为顶部控制胶囊。建议仅在用户明确发起学习时切换，不在计划、日历或甘特管理操作中自动抢占界面。
- 新交互原型覆盖今日、全部任务、计划结构、日历、甘特、知识资料和 AI 学习室，可在页面内点击导航与“开始 AI 学习”体验状态切换。转场目标 220–260ms，并尊重减少动态效果设置。
- 上一可视化服务因空闲停止且仅绑定 `127.0.0.1`，用户浏览器无法打开；已重新以 `0.0.0.0` 绑定并通过 WSL2 实际 IP 验证。当前可视化伴随地址为 `http://172.17.253.105:56517`，原型文件位于 Git 已忽略的 `.superpowers/brainstorm/25859-1785570333/content/nautilus-page-system-a-visual-c-layout-v4.html`。
- 修改文件：本进度文档，以及 Git 已忽略的可视化伴随 HTML。业务代码、正式规格、数据库迁移、默认数据库和标准 5173/8000 服务均未修改；没有修改、删除或暂存 `diagnostic-backups/`。
- 测试：本轮为交互设计与可视化服务修复，没有运行后端测试、前端构建或 Playwright；最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。新可视化页面已通过 `127.0.0.1:56517` 和 `172.17.253.105:56517` HTTP 检查，并包含工作区、AI 准备台、学习室和确认选项。
- 下一项：用户确认 v4 骨架或指出具体页面调整；确认后将多页面布局、模式切换、番茄钟位置、知识源只读边界和响应式规则写入新的正式扩展设计文档，完成用户审阅后再制定实施计划。

### 2026-08-01（统一主题、AI 学习伙伴与知识库 v5）

- 用户基本认可 v4 空间骨架，但指出三项问题：学习室大规模换色突兀；“AI 学习准备台”概念不直观；左栏“知识资料”和“知识卡片”入口疑似重合。
- 设计判断：同意取消整页换肤和拆分的知识入口；右侧 AI 区仍有必要，因为它提供“就当前任务、计划或资料立即提问”的低摩擦入口，但不应作为独立准备阶段，也不应承载完整长对话。
- v5 将右栏统一命名为“AI 学习伙伴”，直接展示当前上下文、短对话、最近会话和输入框；用户发起长对话后进入学习室。进入学习室时保持暖纸色、深海蓝和赤陶色 token，只通过空间重排与内容焦点体现沉浸，不再大规模换色。
- 左栏合并为单一“知识库”入口；知识库内部按“原始资料、知识卡片、学习记录”区分类型，并继续按 Obsidian、本地文件、飞书等来源以及计划/标签筛选。合并的是导航，不是数据类型和来源追溯。
- 已将当前设计写入讨论稿 `docs/superpowers/specs/2026-08-01-nautilus-workspace-layout-design.md`，覆盖统一视觉语言、三栏管理工作区、紧凑番茄钟、AI 学习室、合并知识库、响应式和验收标准；当前状态仍为待用户审阅，不替代 2026-07-23 正式规格。
- 新 v5 可点击原型位于 Git 已忽略的 `.superpowers/brainstorm/25859-1785570333/content/nautilus-page-system-v5-continuous-theme.html`，沿用可访问地址 `http://172.17.253.105:56517`，可在今日、学习室和知识库之间切换。
- 修改文件：`docs/superpowers/specs/2026-08-01-nautilus-workspace-layout-design.md`、本进度文档，以及 Git 已忽略的 v5 可视化 HTML。业务代码、数据库迁移、默认数据库和标准 5173/8000 服务均未修改；没有修改、删除或暂存 `diagnostic-backups/`。
- 测试：本轮为设计与可视化原型，没有运行后端测试、前端构建或 Playwright；最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。v5 已通过 `http://172.17.253.105:56517` HTTP 检查并包含主题连续、AI 学习伙伴、统一知识库和确认入口。
- 风险：v5 尚未完成真实桌面/移动截图验证，各栏精确宽度、长中文标题、空状态和移动抽屉仍需在实现计划和代码验证中细化；当前不能描述为前端改版完成。
- 下一项：用户审阅 v5 和布局讨论稿；若确认，完成规格占位符/冲突/歧义自审，再写分阶段实施计划，首个实现切片为统一壳层、紧凑计时与 AI 学习伙伴静态入口，不一次接入全部 AI/知识库后端。

### 2026-08-01（可折叠三栏、悬浮番茄钟与 v6 视觉探索）

- 用户认可 v5 的大体布局，但新增三项要求：左侧边栏可收起；三个区域宽度在限定范围内可拖动；尝试悬浮番茄钟；并明确反馈整体仍“太 AI”、缺少风格。
- 设计判断：保留三栏工作区，但增加左栏折叠、左右分隔线有限拖动、双击恢复推荐宽度；中栏必须保留核心操作最小宽度，移动端不提供自由拖动而使用抽屉。
- 番茄钟改为“活动时显示的可停靠悬浮窗”：仅在计时运行时出现，限制在中栏范围，可拖动、最小化、关闭后从顶部恢复；不进入或遮挡右侧 AI 区，空闲时不常驻。
- 对 v5 的奶油色/大衬线/陶土色组合进行了自我否定：该组合仍接近当前常见 AI 设计默认。v6 改为“水文航海图 / 学术编辑台”视觉探索，使用冷灰蓝图纸、普鲁士蓝、航标红、规则线、航线编号、坐标标注和测深线，减少圆角卡片、胶囊标签和渐变装饰。
- v6 交互原型位于 Git 已忽略的 `.superpowers/brainstorm/25859-1785570333/content/nautilus-v6-editorial-navigation.html`，沿用 `http://172.17.253.105:56517`；原型包含左栏收起、两条分隔线拖动、悬浮计时器拖动/最小化/关闭恢复、今日/学习室/知识库切换。
- 已将折叠、有限拖动和悬浮番茄钟规则补入 `docs/superpowers/specs/2026-08-01-nautilus-workspace-layout-design.md`；该文档仍为视觉方向讨论稿，未替代正式 2026-07-23 规格。
- 修改文件：本进度文档、布局讨论稿，以及 Git 已忽略的 v6 可视化 HTML。没有修改业务代码、数据库迁移、默认数据库或标准 5173/8000 服务；没有修改、删除或暂存 `diagnostic-backups/`。
- 测试：本轮未运行后端测试、前端构建或 Playwright；通过 `new Function` 检查 v6 原型脚本语法，并通过 WSL2 实际地址 HTTP 检查页面包含 v6、悬浮窗、学习室和 AI 学习伙伴内容。最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。
- 风险：v6 只是风格与交互原型，尚未接入真实 React 状态、布局持久化、计时状态或移动端抽屉；悬浮窗口的真实可访问性、键盘拖动替代方案和窄屏行为必须在实现阶段补齐。
- 下一项：用户审阅 v6 是否有足够产品个性，并指出需要保留/删除的视觉元素；确认后完成讨论稿自审，进入写实施计划阶段，暂不直接大规模改业务 UI。

### 2026-08-01（冻结 UI 探索并转入 AI 功能纵切片）

- 用户决定暂不继续 UI 视觉设计，后续功能开发不应继续消耗时间制作新视觉方案；v5/v6 仅作为未来布局机制和信息架构参考，不代表已经批准实施其视觉风格。
- 下一步专业建议调整为 AI 学习最小纵切片，因为普通 AI 学习对话是正式规格核心闭环中最重要的当前缺口，比继续扩展非核心视觉或一次完成所有知识连接器更能验证产品价值。
- 建议首轮范围：本地加密 `CredentialStore`；一个 OpenAI API 兼容提供方的非秘密配置和连接测试；普通线性对话及消息持久化；SSE 流式输出和取消/重复提交边界；当前任务与计划的只读上下文预览；最小可用前端入口。
- 首轮明确不做：对话分支图、Obsidian/飞书/云存储连接器、FTS5、知识卡片、学习记录写入、AI 计划生成/重排、多个原生提供方和复杂 LangGraph 工作流。这些能力保留接口边界，后续逐个纵切片实现。
- 自动化测试必须使用 Mock 提供方或 Mock HTTP，不得消耗真实 API，不得输出或记录真实密钥；浏览器写测试继续使用独立临时 `NAUTILUS_DATA_DIR`。
- 若新增数据库结构，必须从 `005_*.sql` 开始；`001_initial`–`004_plan_editor` 不得修改。API 密钥不得进入 SQLite、日志、对话、备份或进度文档。
- 本轮为新窗口交接准备，没有修改业务代码、数据库迁移、默认数据库或标准 5173/8000 服务，也没有提交、推送、部署；没有修改、删除或暂存 `diagnostic-backups/`。UI 探索冻结后已停止临时可视化伴随服务，正式 Web/API 继续运行。
- 本轮只读核对：Git 分支为 `main...origin/main`，工作区仍有大量未提交/未跟踪实现；标准服务仍监听 `0.0.0.0:5173` 和 `0.0.0.0:8000`，WSL2 实际 IP 为 `172.17.253.105`。本轮没有重新运行后端测试、前端构建或 Playwright，最近有效基线仍为后端 `18 passed, 1 warning`、前端构建成功、Playwright `4 passed`。
- 下一项：新窗口先完整阅读正式规格、状态、`AGENTS.md` 和 HMR 事故复盘，重新核对 Git/服务/迁移/默认数据库数量并重跑基线；随后给出短计划，直接实现 AI 学习最小纵切片，不继续 UI 视觉改版。

### 2026-08-01（新窗口接管与 AI 纵切片现状核对）

- 完整重读正式规格、交接状态、`AGENTS.md`、Vite HMR 事故复盘和统一工作区讨论稿；确认 v5/v6 视觉探索冻结，不把其风格实现到正式前端。
- 重新核对工作区：发现后端 AI 纵切片已经存在于未跟踪实现中，不能按“尚未开始”重做；本轮没有修改或删除既有业务实现，也没有提交、推送或部署。
- 基线重新运行：`timeout 80s env PYTHONPATH=backend .venv/bin/python -m pytest -q` 为 `68 passed, 1 warning`；`npm --prefix frontend run build` 成功（1805 modules）；`npm --prefix frontend run test:e2e` 为 `4 passed`；脚本语法与 `git diff --check` 通过。
- 只读核对 WSL2 IP 为 `172.17.253.105`；标准 `8000/5173` 当前未运行，因此本轮未启动默认服务，避免在高风险边界未修复前自动应用 `005_ai_conversations` 到用户数据库。
- 默认数据库只读核对：迁移仍为 `001_initial`–`004_plan_editor`，`integrity_check=ok`；`local_identity=1`、`sessions=8`、`learning_goal/subject/topic/task` 各 `3`、`study_session=2`、`layout_config=1`、`layout_template=3`。这些数据按用户真实数据保留，未执行写入。
- 子 Agent 只读审查确认的高风险：`cryptography` 未声明依赖；迁移失败不原子回滚；`prepare_run` 提交后再次读取 provider 可能留下永久 `queued`；流协议异常可能误判成功；CredentialStore 与 SQLite 缺少补偿式一致性；Playwright 数据目录前缀校验可被 `..` 路径穿越；AI 浏览器测试尚未存在。
- 本轮新增/修改文件：仅本进度文档；没有新增或应用数据库迁移，没有修改 `001`–`004`，没有修改/删除/暂存 `diagnostic-backups/`。
- 当前阻塞与下一项：设计确认前不写业务代码。推荐先修后端/迁移/测试安全边界，补极简 provider 设置和独立 AI 学习室，再用隔离 Mock provider 跑真实 Playwright；等待用户确认是否把 provider 设置面板纳入本轮及短设计方案。

### 2026-08-01（AI 学习最小纵切片设计确认）

- 用户确认采用定向修复方案：不直接把现有后端接到前端，也不重写为复杂 AI 架构；先修复高风险一致性边界，再补简化学习室、极简 provider 设置和隔离浏览器测试。
- 新增正式实施设计 `docs/superpowers/specs/2026-08-01-nautilus-ai-learning-minimal-slice-design.md`，明确 CredentialStore、OpenAI 兼容提供方、线性对话、上下文快照、SSE、取消、幂等、刷新恢复、迁移和测试边界。
- 设计继续冻结 v5/v6 视觉探索，不实现三栏重构、分支图、知识源、知识卡片、AI 计划生成、多个原生提供方或复杂 LangGraph 工作流。
- 已完成设计自审：无 `TBD/TODO` 占位；明确使用 SQLite 延迟外键解决同一事务内消息与运行的相互引用；范围保持为一个可实施纵切片。
- 本次只修改设计与进度文档，没有修改业务代码、迁移、默认数据库或运行服务；按用户指令没有提交、推送或部署。
- 下一项：用户书面确认设计文件后，编写实施计划并开始测试保护、后端修复、前端接入和隔离 Playwright。

### 2026-08-01（AI 学习最小可用纵切片实现与隔离验证）

- 按已确认设计完成定向实现：本地加密 CredentialStore、一个 OpenAI Chat Completions 风格兼容 provider、普通线性对话、追加式消息、任务/计划上下文快照、AI 运行状态、SSE、取消、断开恢复和重复提交幂等均已接通；这只是最小纵切片，不代表 AI 阶段或首阶段完成。
- 后端主要新增/修改：`backend/requirements.txt`、`backend/app/db.py`、`backend/app/credentials.py`、`backend/app/providers.py`、`backend/app/conversations.py`、`backend/app/ai_runtime.py`、`backend/app/routers/ai.py`、`backend/app/migrations/005_ai_conversations.sql`，以及 `backend/tests/test_credentials.py`、`test_providers.py`、`test_ai_conversations.py`。
- 前端主要新增/修改：`frontend/src/AiLearningRoom.tsx`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/Workspace.tsx`、`frontend/src/TodayView.tsx`、`frontend/src/api.ts`、`frontend/src/styles.css` 和 `frontend/src/styles/ai-learning.css`；只复用现有工作区与样式，没有实施 v5/v6 视觉方案或大规模重构。
- 测试基础主要新增/修改：`frontend/e2e/ai-learning.spec.ts`、`frontend/playwright.config.ts`、`frontend/e2e/global-teardown.ts`、`scripts/start-e2e.sh`、`scripts/mock-openai-provider.py`、`scripts/test-start-e2e-safety.sh` 和 `scripts/start.sh`。浏览器测试使用独立临时 `NAUTILUS_DATA_DIR` 和本地 Mock provider，不调用真实 AI API。
- 迁移状态：新增且只修改 `005_ai_conversations.sql`，`001_initial`–`004_plan_editor` 未改变。`005` 的应用、约束和失败原子回滚已在临时数据库测试；默认 `data/nautilus.sqlite3` 仍只应用 `001`–`004`，本轮没有写入或清理用户数据库。
- 最终验证：后端 `83 passed, 1 warning`；前端生产构建成功（`1807 modules transformed`）；Playwright `8 passed`；脚本语法、E2E 路径安全测试、`pip check` 和 `git diff --check` 均通过。最终无 `5173/8000` 或 Mock provider 监听残留，WSL2 实际 IP 为 `172.17.253.105`。
- 已知风险：默认数据库尚未应用 `005`；自动化按要求未验证真实外部 provider；工作区实现仍未提交。`backend/requirements.txt` 已将 `cryptography` 范围统一为 `>=43,<51`，包含本轮验证使用的 `50.0.0`。
- 下一项：先在独立数据库副本中做 `005` 迁移上线演练，并在用户确认备份与迁移时机后再决定是否应用到默认库；随后由用户主动配置真实 provider 做一次手动连接和对话烟测。本轮没有提交、推送或部署，也没有修改、删除或暂存 `diagnostic-backups/`。

### 2026-08-01（V6 工作区视觉落地与功能测试入口）

- 用户明确改变此前“冻结 V6 视觉落地”的优先级，要求先把 V6 UI 写入正式前端，以便人工验证已经实现的 AI 学习功能；本轮按该新决定执行，没有重新讨论已确认的布局方向。
- 正式 React 工作区已采用 V6“水文航海图 / 学术编辑台”视觉 token：冷灰蓝图纸、深海蓝导航、航标红当前行动、规则线、坐标标签和低圆角工具面板；没有新增视觉原型或把 v6 原型中的假数据复制进业务页面。
- 管理态新增三栏壳层：左侧导航支持折叠并本地保存状态；中栏保留今日、任务、计划和日历真实视角；右侧新增 AI 学习伙伴，展示真实当前任务和 provider 状态，并进入现有 AI 学习室。
- 桌面两条分隔线支持限定范围拖动与双击恢复；右栏限制在 `260–420px`，左栏展开限制在 `144–240px`，中栏保持可用宽度。窄屏隐藏右栏，移动端使用固定菜单按钮打开左侧抽屉。
- 活动计时新增 `FloatingTimer.tsx`：仅在存在真实活动计时时出现，严格限制在中栏，支持暂停/继续、结束、拖动、最小化、隐藏和恢复；移动端固定为底部紧凑条。旧计时面板继续保留完整的启动与配置入口。
- 主要修改/新增文件：`frontend/src/Workspace.tsx`、`frontend/src/AiCompanionPanel.tsx`、`frontend/src/FloatingTimer.tsx`、`frontend/src/styles.css`、`frontend/src/styles/base.css`、`frontend/src/styles/workspace.css`、`frontend/src/styles/ai-learning.css`、`frontend/src/styles/v6-workspace.css`、`frontend/e2e/v6-workspace.spec.ts` 和本进度文档。
- 迁移和数据状态：没有新增或修改数据库迁移；`001`–`004` 未改变，`005_ai_conversations.sql` 仍未应用到默认用户数据库。所有浏览器写测试继续使用独立临时 `NAUTILUS_DATA_DIR`，默认数据库未被本轮测试写入。
- 最终验证：后端 `83 passed, 1 warning`；前端生产构建成功（`1809 modules transformed`）；Playwright `11 passed`，其中新增 3 项覆盖 V6 桌面折叠/拖动/导航、活动悬浮计时器边界与操作、移动导航抽屉和页面无溢出；脚本语法、路径安全、`pip check` 和 `git diff --check` 通过。
- 已知边界：右栏当前是进入完整学习室的真实入口，不在管理态直接发送短问答；知识库、知识源、分支图和完整 V6 学习室三栏仍未实现，禁用入口不会伪装成可用功能。标准 5173/8000 服务仍未启动，以免未经确认把 `005` 应用到默认数据库。
- 下一项：使用隔离临时数据目录启动生产预览供用户人工测试 V6 和 AI 闭环；根据实际反馈只修复影响测试的 UI/功能问题，再决定默认数据库迁移与真实 provider 烟测。本轮没有提交、推送或部署，也没有修改、删除或暂存 `diagnostic-backups/`。
- 人工验收入口：隔离预览已实际启动，用户可直接访问 `http://172.17.253.105:5186`；若需停止或重置该环境，应只操作其专用进程和临时数据目录，不触碰默认数据库。

### 2026-08-01（V6 人工验收不通过与新窗口交接）

- 用户人工检查后明确否决当前 V6 页面呈现，当前实现只能视为待修复草稿，不能称为视觉验收通过。
- 已确认问题一：点击“新建计划”后，弹窗没有覆盖当前视口，而是出现在页面下方，必须滚动才能看到；下一轮应先检查三栏壳层引入的定位上下文、滚动容器和层叠关系。
- 已确认问题二：首页“今日 / 任务 / 计划 / 日历”视角导航位置过高且层级错误，需要重新放回符合主内容阅读顺序的位置，不能继续挤在页面最上方。
- 已确认问题三：进入 AI 学习室后仍在左侧持续显示当前任务状态等低优先级信息，破坏沉浸式学习；学习室应减少外围管理信息，只保留学习对话所需上下文和必要操作。
- 已确认问题四：首页左栏使用“今日航线 / 全部任务 / 计划结构 / 学习日历 / 知识库”的分类显得混乱，信息架构需要重新收敛，不能把当前分类当成已确认方案。
- 过程缺陷：本轮虽然增加了 Playwright 布局断言，但没有在交付前以真实截图进行足够的桌面视觉检查，自动化通过未能发现上述可用性问题。后续任何 UI 验收声明前，Agent 必须自行截图查看实际页面并记录观察结果。
- 运行与数据边界不变：隔离手测环境仍位于 `5186/8012/8013`，使用 `/tmp/nautilus-playwright.manual-v6-20260801`；默认数据库没有应用 `005`，也没有提交、推送或部署。
- 精确下一项：新窗口先完整阅读规格、布局讨论稿、事故复盘和本文件，再在隔离环境复现四项问题；先修弹窗与学习室结构，再收敛导航和左栏信息架构，完成桌面/移动端截图检查后交给用户复验。

### 2026-08-01（工作区与学习室可用性修复）

- 完成只读接管核对：完整阅读正式规格、当前进度、`AGENTS.md`、Vite HMR 复盘、统一工作区布局讨论稿和 AI 学习最小切片设计；确认隔离环境端口曾存活，随后用新隔离数据目录重启 production preview，未启动标准 `5173/8000`。
- 根据真实截图定位并修复四项问题：所有工作区弹窗通过 `DialogPortal` 挂载到 `document.body`，避免三栏滚动/定位上下文影响 `position: fixed`；视角 tabs 从 header 移到中栏内容层的“当前视角”栏；AI 学习室隐藏管理左栏、右侧伙伴栏和管理导航，只保留返回、上下文摘要、对话、provider 设置及流式/取消/重试操作；左栏收敛为“今日 / 学习室 / 知识库（开发中）”，不伪装未实现知识库。
- 主要修改文件：`frontend/src/DialogPortal.tsx`、`frontend/src/PlanDialog.tsx`、`frontend/src/LayoutDialog.tsx`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/PlanEditor.tsx`、`frontend/src/Workspace.tsx`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/styles/dialogs.css`、`frontend/src/styles/v6-workspace.css`、`frontend/src/styles/ai-learning.css`、`frontend/e2e/v6-workspace.spec.ts`、`frontend/e2e/ai-learning.spec.ts`、`frontend/e2e/delivery-stability.spec.ts`。
- 新增回归覆盖：桌面/移动弹窗 backdrop 必须是 `BODY` 下的 fixed 视口层；视角导航必须位于 header 下方；管理左栏入口数量与知识库禁用状态；学习室不得渲染管理左栏/伙伴栏、上下文默认折叠且可展开；保留既有 SSE、取消、刷新幂等等测试。
- 真实截图复查：使用隔离 production preview `http://172.17.253.105:5186`，视口 `1440x1000`、`1024x900`、`390x844`。三档均无页面级横向溢出；弹窗均在当前视口内（桌面/平板居中、移动端底部 sheet）；学习室均无管理左栏/右栏，上下文默认折叠；截图对应浏览器控制台错误和请求失败均为零。截图仅写入 `/tmp`，未纳入仓库。
- 测试结果：`timeout 150s env PYTHONPATH=backend .venv/bin/python -m pytest -q` 为 `83 passed, 1 warning`；`npm --prefix frontend run build` 成功（`1811 modules transformed`）；`npm --prefix frontend run test:e2e` 为 `12 passed`；`bash -n ...`、`bash scripts/test-start-e2e-safety.sh`、`.venv/bin/pip check`、`git diff --check` 均通过。
- 数据与运行边界：无新增或修改数据库迁移；`001_initial`–`004_plan_editor` 未修改，`005_ai_conversations.sql` 仍未应用默认数据库；默认库只读复核 `integrity_check=ok`、迁移仍为 `001_initial,002_learning_plans,003_dashboard_layouts,004_plan_editor`；未修改、删除或暂存 `diagnostic-backups/`，未提交/推送/部署。WSL2 实际 IP 为 `172.17.253.105`；验证结束后无 `5186/8012/8013` 监听残留。
- 已知风险与下一项：当前实现仍未得到用户最终视觉复验；学习室仍是最小线性切片，不包含分支、知识源或知识产出。下一项是用户复验本轮布局修复；通过后再单独做 `005` 上线审查和真实 provider 手动烟测，不把本轮描述为 V6 或 AI 阶段完成。

### 2026-08-02（隔离生产预览恢复）

- 用户反馈网页无法打开。核对确认代码修复已经完成，但上一轮验收清理同时停止了临时预览服务并移除了临时数据目录；这是运行状态交接疏漏，不是新的业务代码故障。
- 使用项目自带 `scripts/start-e2e.sh` 重新创建 `/tmp/nautilus-playwright.manual-v6-20260801`，恢复 Web `5186`、API `8012` 和本地 Mock provider `8013`；三个服务均绑定 `0.0.0.0`，当前 WSL2 访问地址为 `http://172.17.253.105:5186`。
- 实际验证：`5186/8012/8013` 均处于监听状态；`GET /api/health` 返回数据库健康；网页 HTML 引用 `/assets/index-*.js` 和 `/assets/index-*.css`，且不包含 `/@vite/client` 或 React Refresh，确认是 production preview。
- 本轮只修改本进度文档，没有修改业务代码或数据库迁移；没有启动或写入默认 `data/nautilus.sqlite3`，没有修改、删除或暂存 `diagnostic-backups/`，也没有提交、推送或部署。
- 已知运行边界：该人工验收环境依赖当前本地服务进程，WSL 或承载会话退出后需要重新启动。精确下一项是用户重新打开页面并复验弹窗、视角导航、沉浸式学习室和左栏信息架构。

### 2026-08-02（视口布局稳定性修复设计确认中）

- 用户复验后指出：活动番茄钟仍会越界并拉长页面；桌面左右栏会随长页面产生不协调滚动和底部空白；页面没有正确适应实际设备可用宽高；AI 学习室两侧留白仍过多；大面积青绿色背景不可接受。
- 使用真实 production preview 复现根因：向旧计时器位置键注入 `{x:2400,y:3600}` 后，浮窗实际到达约 `x=2603,y=4698`，中栏滚动尺寸扩大到约 `2626x4766`；AI 学习室在 `1440px` 视口被限制为 `1040px`，左右合计留白约 `400px`。
- 用户确认番茄钟采用 B“受控拖动”，并确认背景采用 B“岩砂航海日志”。新增修复设计 `docs/superpowers/specs/2026-08-02-nautilus-viewport-layout-stability-design.md`，同时明确桌面固定视口三栏、中栏独立滚动、移动单一页面流、动态视口安全区和学习室铺满规则。
- 本轮仍处于设计审阅门槛，尚未修改业务代码、数据库迁移或默认数据库；没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 精确下一项：用户复核新设计文件；确认后先实现浮窗 Portal、归一化位置与 ResizeObserver 钳制，再修工作区高度/滚动模型、AI 学习室宽高和背景 token，最后补回归与真实截图验收。

### 2026-08-02（视口布局稳定性修复实现与验收）

- 用户确认 B 方案与“岩砂航海日志”背景后完成实现：`frontend/src/FloatingTimer.tsx` 改为 Portal + `position: fixed`，旧像素坐标兼容读取后立即钳制/迁移为归一化坐标；拖动、刷新、窗口/视觉视口变化、栏宽变化和浮窗尺寸变化均通过 `ResizeObserver` 与边界重算保持在中栏和当前视口内。移动端固定底部安全区条，不覆盖 AI 输入区，也不覆盖桌面拖动坐标。
- 工作区样式修改：`frontend/src/Workspace.tsx` 传入中栏边界并标记活动计时状态；`frontend/src/styles/base.css`、`frontend/src/styles/workspace.css`、`frontend/src/styles/v6-workspace.css`、`frontend/src/styles/ai-learning.css` 改用岩砂/炭灰/铁锈红 token、低对比度纸张颗粒、`100dvh` 固定壳层、左右栏固定和中栏独立滚动；AI 学习室取消 `1040px` 最大宽度，桌面只保留 24px 安全边距，消息列表独立滚动。
- 回归测试修改：`frontend/e2e/v6-workspace.spec.ts` 新增极端旧坐标、拖动后改栏宽、缩放到 1024px、桌面左右栏固定、移动计时条与学习室输入区不重叠断言；`frontend/e2e/ai-learning.spec.ts` 新增学习室宽度、动态视口、输入区和消息滚动断言。未修改后端 AI、计时状态机或任何数据库迁移。
- 实际截图复查：使用全新隔离 production preview，视口 `1440x1000`、`1024x900`、`390x844`，分别查看管理态和 AI 学习室。六组最终截图均无页面级横向/纵向溢出；桌面三栏高度分别等于 `1000px`，平板主栏等于 `900px`，移动壳层等于 `844px`；AI 学习室桌面宽度 `1377px`（视口的约 95.6%），移动输入区底部 `741px`、底部计时条顶部 `764px`，安全间距超过 8px；控制台错误和请求失败均为零。截图仅写入 `/tmp`，未纳入仓库。
- 测试结果：后端 `timeout 150s env PYTHONPATH=backend .venv/bin/python -m pytest -q` 为 `83 passed, 1 warning`；前端生产构建成功（`1811 modules transformed`）；完整 Playwright `14 passed`（包含本轮新增的 6 项布局/响应式断言）；脚本 `bash -n ...`、`bash scripts/test-start-e2e-safety.sh`、`.venv/bin/pip check`、`git diff --check` 均通过。
- 数据与运行边界：没有新增或修改数据库迁移；默认数据库只读 `integrity_check=ok`，未写入默认 `data/nautilus.sqlite3`；本轮人工复现创建的四个临时计划已按精确 ID 删除，原有活动计时保持不变；没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。用户隔离预览 `http://172.17.253.105:5186`、API `8012` 和 Mock `8013` 仍保持运行并已核对为最新 production preview（无 HMR 客户端）。
- 已知风险与下一项：B 方案仍允许桌面拖动，用户可将浮窗放到遮挡正文的位置；当前实现只保证不越界和不撑长页面，不自动避让每个业务卡片。下一项是用户在自己的设备上复验真实地址栏变化、拖动偏好和 AI 学习室滚动手感；通过后再进行 `005` 默认数据库迁移演练和真实 provider 手动烟测，不把本轮描述为产品阶段完成。

### 2026-08-02（AI 学习交互、Markdown 与模型发现改进）

- 按用户确认的组合方案完成学习室高频交互：输入框普通 `Enter` 发送、`Shift+Enter` 换行，并保护输入法组合态；助手正文使用 `react-markdown` 与 `remark-gfm` 渲染 GFM，用户消息保持纯文本，不启用原始 HTML。
- provider 设置改为可编辑模型组合框：聚焦时通过后端代理请求 OpenAI 兼容 `/models`，前后端均缓存结果并支持显式刷新；发现失败或列表为空时仍可手动填写。连接测试先打开模型选择弹窗，可使用尚未保存的当前表单配置；成功提示在按钮右侧以绿色显示，已测试模型带绿色圆形勾。
- provider 流适配器新增显式推理分流，支持 `reasoning_content`、`reasoning` 和流中 `<think>` 标签；推理内容与最终正文分别通过 SSE、数据库和断线恢复链路传递。学习室只展示 API 明确返回的推理内容，生成时低对比度展开，完成后默认折叠，不推断或伪造隐藏思维链。
- 学习室密度重新收敛：压缩应用顶栏、学习室标题栏、上下文栏和两行输入区，消息列表占据剩余空间并独立滚动；移动端返回与设置按钮使用图标和无障碍名称，避免窄屏中文纵排。AI 模式继续铺满中栏，不恢复管理态左右栏。
- 后端主要新增/修改：`backend/app/migrations/006_ai_message_reasoning.sql`、`backend/app/model_discovery.py`、`backend/app/providers.py`、`backend/app/conversations.py`、`backend/app/ai_runtime.py`、`backend/app/routers/ai.py`、`backend/app/schemas.py`、`backend/app/main.py`，以及 `backend/tests/test_providers.py`、`test_ai_conversations.py`、`test_foundation.py`、`test_plans.py`。
- 前端和验证主要修改：`frontend/package.json`、`frontend/package-lock.json`、`frontend/src/api.ts`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/styles/ai-learning.css`、`frontend/src/styles/dialogs.css`、`frontend/src/styles/v6-workspace.css`、`frontend/e2e/ai-learning.spec.ts`、`scripts/mock-openai-provider.py`；新增确认设计 `docs/superpowers/specs/2026-08-02-nautilus-ai-learning-interaction-design.md`。
- 迁移与数据：新增 `006_ai_message_reasoning.sql`，未修改 `001`–`005`；隔离手测库已应用 `001`–`006`，默认 `data/nautilus.sqlite3` 只读复核仍为 `001_initial,002_learning_plans,003_dashboard_layouts,004_plan_editor` 且 `integrity_check=ok`。本轮没有写默认数据库，也没有调用真实 AI API。
- 测试结果：后端全量 `87 passed, 1 warning`；前端生产构建成功（`2063 modules transformed`）；最终所有改动完成后直接运行完整 Playwright `16 passed`，缓存指纹改动完成时 AI 定向套件另为 `6 passed`；脚本语法/数据目录安全测试、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 真实截图验收：在 production preview 检查 `1440x1000`、`1024x900`、`390x844`。三档文档尺寸均等于视口，无页面级溢出；消息区分别约 `641px`、`551px`、`496px`，明显大于紧凑头部和输入区；Markdown 语义内容、完成后推理折叠和模型测试选择弹窗均已实际查看，控制台错误为零。截图仅写入仓库外临时目录并在交付前清理。
- 已知边界：模型自动发现依赖 OpenAI 兼容 `/models`，不兼容时使用手动模型名；只能展示 provider 显式返回的推理字段或标签。当前实现仍是线性 AI 学习最小纵切片，不包含分支、知识源或 LangGraph 工作流。没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 精确下一项：用户硬刷新并复验 `http://172.17.253.105:5186`；确认交互和视觉通过后，再单独审查 `005`、`006` 默认数据库迁移和真实 provider 手动烟测。

### 2026-08-02（AI 对话与提供方能力差距调研）

- 按用户要求只做调研，没有修改业务代码、数据库迁移、默认数据库或 `diagnostic-backups/`，没有提交、推送或部署。
- 已核对 Nautilus 当前边界：只有一个 `provider_profile`、一个 OpenAI Chat Completions 兼容适配器和一个默认模型；模型发现只服务于设置弹窗；消息只有纯文本正文与独立推理文本；发送请求固定为 `model/messages/stream`，没有对话级 provider/model、搜索、思考参数、附件 parts、自定义 Headers/Body 或模型能力元数据。
- 交叉参考 RikkaHub、Chatbox、Open WebUI、LibreChat，确认成熟产品普遍将 provider、model、session/assistant settings、message parts、tool/search/attachment capability 分层，而不是把所有选项写进单个 provider 表单。调研清单已在本次交接回复中按 P0/P1/P2 和正式规格边界列出。
- 精确下一项：等待用户确认差距清单的实现优先级；用户确认前不编写新的实现计划、不新增迁移、不实现功能。

### 2026-08-02（AI 对话与提供方扩展范围确认）

- 用户已确认本轮调研结论和推荐实施顺序，下一阶段允许进入正式设计，但尚未批准直接编码实现。
- 已确认的目标范围：多提供方、多模型、学习室内提供方/模型切换、模型能力元数据、Provider/Model/Conversation/Run 配置层级与请求配置快照；随后加入对话级思考强度、受安全边界约束的 Web Search、图片与小型文件附件；再加入自定义 Headers、JSON Body、Provider/Model 覆盖规则、请求预览与敏感 Header 加密；最后补齐对话管理、消息复制/编辑/重试、上下文/Token 信息、分支和更完整的 Markdown/引用渲染。
- 推荐顺序已确认：先做多提供方/多模型基础架构，再做思考强度、搜索和小型附件，再做自定义 Headers/Body，最后做对话质量与分支能力。每一层必须先有正式设计、数据安全边界、迁移方案、测试保护和隔离验收。
- 明确暂缓或禁止直接照搬：OAuth、MCP、任意 Shell/Python/网络爬取、代码解释器、自动记忆、完整知识库/RAG、云同步、图像生成、语音和视频；这些与当前正式规格或 MVP 优先级存在边界冲突，除非另写扩展规格并重新确认。
- 当前没有开始实现以上扩展，没有新增 `007` 或其他迁移，没有修改默认数据库，也没有调用真实 AI API。当前已有 `005_ai_conversations.sql` 和 `006_ai_message_reasoning.sql` 仍只在隔离库验证，默认库仍为 `001`–`004`。
- 精确下一项：新窗口先重新阅读正式规格、布局/AI 设计、`AGENTS.md`、本进度文档和最新调研结论；然后只为“多提供方、多模型、对话级选择与配置快照”编写正式设计文档，提交用户审阅通过后再制定实施计划和开始编码。不要在设计确认前扩展附件、搜索或自定义请求体。

### 2026-08-02（多提供方、多模型基础架构正式设计）

- 按用户已确认的第一阶段范围，完整重读正式规格、进度、`AGENTS.md`、HMR 事故复盘、工作区布局设计、AI 最小切片设计、AI 交互设计和视口稳定性设计，并重新执行 Git、迁移、WSL2 IP、端口和健康接口只读核对。
- 新增正式设计文件 `docs/superpowers/specs/2026-08-02-nautilus-multi-provider-model-selection-design.md`，推荐 Provider Profile、Provider Model、Conversation Config、Run Snapshot 四层分表；新增 Provider Adapter Registry；第一阶段只实际注册 `openai_compatible`，为 Gemini/Anthropic 保留扩展接口但不伪装为已支持。
- 设计覆盖 provider/model 数据模型、多 provider 与模型 API、发现和缓存、能力元数据、学习室选择器、provider 默认值、model 覆盖、conversation 临时配置、运行时优先级、凭据加密边界、错误/兼容性、从 `007_ai_multi_provider_model_selection.sql` 开始的迁移策略、后端/Playwright 测试和桌面/平板/移动验收标准。
- 设计自审已完成：未发现 `TBD`、`TODO` 或模糊占位；明确附件、Web Search、思考强度、自定义 Headers/Body、原生 Gemini/Anthropic 调用均不属于本阶段；明确不修改 `001`–`006`，不创建 `007`，不应用默认数据库迁移。
- 本轮修改文件：仅新增上述正式设计文件，并更新本进度文档；没有修改后端业务代码、前端业务代码、数据库迁移、默认 `data/nautilus.sqlite3` 或 `diagnostic-backups/`；没有提交、推送或部署。
- 本轮验证：只读 `git status --short --branch`、迁移文件列表、`./scripts/wsl-ip.sh`、端口监听、两个 `curl` 健康/首页请求；当前 WSL2 IP 为 `172.17.253.105`，`5173/8000/5186/8012/8013` 均未监听，隔离服务不可达。设计文件占位扫描和 `git diff --check` 通过；未运行业务测试、构建或 Playwright，因为本轮没有实现代码变更。
- 已知边界：正式设计尚未得到用户批准；在批准前不得进入实施计划或任何 `007`/业务代码工作。精确下一项是用户审阅并确认该设计，或提出需要修改的设计章节。

### 2026-08-02（多提供方、多模型与对话配置快照实现）

- 用户明确批准 `docs/superpowers/specs/2026-08-02-nautilus-multi-provider-model-selection-design.md` 后进入实施。本轮新增 `backend/app/migrations/007_ai_multi_provider_model_selection.sql`，未修改 `001`–`006`；迁移新增 `provider_model`、`conversation_config`，并为 `provider_profile`、`ai_run` 增加默认模型、凭据版本、provider model 引用和版本化配置快照字段。旧 `provider_profile.model` 与单数 `/api/ai/provider` API 保留为兼容影子字段/接口。
- 后端实现 Provider Adapter Registry，当前只注册 `openai_compatible`；新增多 provider 创建、更新、设默认、删除、按 provider 连接测试，以及模型列表、手动模型、发现模型持久化 API。模型记录包含发现来源/状态、启用状态、能力元数据和预留覆盖 JSON；未伪装支持原生 Gemini/Anthropic。
- Conversation/Run 配置链路已接通：对话可保存 provider/model 选择和超时覆盖；请求启动时按默认 provider/model 或对话选择解析一次配置，并把 provider、model、能力、有效超时、配置版本和凭据引用版本冻结到 `ai_run.config_snapshot_json`。快照不含 API Key，运行中后续配置修改不会改变既有 Run。
- 前端实现：`frontend/src/AiLearningRoom.tsx` 新增紧凑的对话 provider/model 选择栏，根据 provider/model 启用与发现状态控制选项；`frontend/src/AiProviderDialog.tsx` 扩展为可查看、切换和新增多个 provider 的管理入口，并支持指定 provider 的模型发现与连接测试；`frontend/src/api.ts` 增加相应类型和 API；`frontend/src/styles/ai-learning.css`、`frontend/src/styles/dialogs.css` 保持桌面/移动布局稳定。
- 本轮主要修改/新增文件：`backend/app/migrations/007_ai_multi_provider_model_selection.sql`、`backend/app/providers.py`、`backend/app/conversations.py`、`backend/app/schemas.py`、`backend/app/routers/ai.py`、`backend/tests/test_ai_conversations.py`、`backend/tests/test_foundation.py`、`backend/tests/test_plans.py`、`frontend/src/api.ts`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/styles/ai-learning.css`、`frontend/src/styles/dialogs.css` 和本进度文档。
- 测试与验收：后端全量 `89 passed, 1 warning`；前端 production build 成功（`2063 modules transformed`）；使用 `/tmp/nautilus-playwright.final-multi-ok-20260802`、端口 `8095/5241/8096` 和现有 Chromium 运行完整 Playwright 为 `16 passed`。`git diff --check`、`.venv/bin/pip check`、`bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh` 均通过；本轮 Playwright 结果目录已清理。
- 数据和安全边界：所有自动化写入均使用 `/tmp` 隔离目录和 Mock provider；默认 `data/nautilus.sqlite3` 只读复核迁移仍为 `001_initial,002_learning_plans,003_dashboard_layouts,004_plan_editor`，`integrity_check=ok`。没有写入真实 API Key/用户学习内容到 SQLite、日志、测试或进度文档；没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 已知边界与风险：本轮只完成第一阶段基础架构，不含思考强度、Web Search、附件、自定义 Headers/Body 或高级模型参数；真实外部 provider 尚未手动烟测；默认数据库尚未应用 `005`–`007`；多 provider 设置弹窗已经可新增/切换，但删除入口和模型启停/能力人工编辑仍留给后续设置增强，不影响学习室选择与运行快照主闭环。
- 精确下一项：用新的隔离数据目录启动 production preview，人工验证创建第二 provider、模型发现、连接测试、学习室对话级切换和发送后 Run 快照；验收通过后制定 `005`–`007` 默认数据库迁移演练清单。第二阶段功能必须先写正式设计，不直接继续编码。

### 2026-08-02（多提供方基础架构隔离人工验收环境）

- 按用户确认启动新的隔离 production preview：Web `http://172.17.253.105:5186`、API `8012`、Mock provider `8013`，三项服务均绑定 `0.0.0.0`；隔离数据目录为 `/tmp/nautilus-playwright.manual-multi-20260802`。
- 实际核对：API `/api/health` 与 Mock `/health` 均正常；网页加载 `/assets/index-CrZEREAu.js` 和 `/assets/index-QO_wVF_O.css`，不包含 Vite HMR/React Refresh 客户端，确认是本轮最新 production build。
- 隔离数据库已应用 `001`–`007` 且 `integrity_check=ok`。默认 `data/nautilus.sqlite3` 继续只读核对为 `001`–`004`、`integrity_check=ok`，本次启动没有应用 `005`–`007` 到默认数据库。
- 本次只启动隔离服务并更新进度文档，没有修改业务代码、迁移、默认数据库或 `diagnostic-backups/`，没有提交、推送或部署。
- 精确下一项：用户在该地址人工验证新增两个 provider、设置默认项、指定 provider 模型发现/连接测试，以及学习室内对话级 provider/model 切换；环境通过本地进程维持，WSL 或承载会话退出后需要重新启动。

### 2026-08-02（AI 学习室缩放与信息层级反馈设计中）

- 用户人工验收提出四项问题：模型下拉在点击其他区域后应可靠收起；浏览器放大时常驻上下文、配置条和输入区挤压消息空间；任务路径应移到学习室右侧中部；对话需要 AI 生成标题并占据原上下文标题位置，配置改为按需展开，输入区随有效视口紧凑适配。
- 只读核对确认当前 `mousedown` 外部监听覆盖不完整；放大浏览器后 CSS 有效宽度进入窄屏断点，上下文与配置条纵向堆叠，是消息区被压缩的主要原因。AI 标题还涉及额外模型调用、失败回退、幂等和配置快照归属，不能仅按视觉改动处理。
- 已启动 brainstorming 可视化伴随页 `http://172.17.253.105:51713`，展示右侧边缘信息签、常驻窄右栏和统一信息抽屉三种布局；用户已选择 A“右侧边缘信息签”。配置按钮确定使用岩砂灰褐低对比度底色、炭灰文字和细边框，悬停才显示铁锈红反馈，不使用白色背景。
- 源码级参考 RikkaHub（临时克隆至 `/tmp`，未进入仓库）：它在主回答成功保存后异步启动 `generateTitle`，默认使用 `titleModelId`，未设置时回退 `fastModelId`；标题只取最近 4 条消息、每条最多 500 字，使用独立后台文本生成参数，生成完成后重新读取最新会话再写标题，并提供强制重新生成和手动编辑标题 API/入口。Nautilus 采用其调用时机、截断、并发更新保护和重生成边界，但本阶段先使用当前 Run 已冻结的 provider/model，未来再增加独立标题模型设置，避免提前引入全局 fast model 层。
- 本轮没有修改前后端业务代码、迁移、默认数据库或 `diagnostic-backups/`，没有提交、推送或部署。下一项是将上述方案写入正式修复设计，明确标题生成失败回退、重生成/手动改名、配置快照归属和缩放验收，然后等待用户审阅确认。

### 2026-08-02（AI 学习室标题、信息层级与缩放适配正式设计）

- 用户确认 A“右侧边缘信息签”布局、灰褐色对话配置按钮、首次自动生成一次标题、后续只手动重新生成，以及独立后台 Title Run 架构。
- 新增正式设计 `docs/superpowers/specs/2026-08-02-nautilus-ai-learning-room-title-density-design.md`。设计覆盖 Provider 模型下拉的 `pointerdown/focusin/Escape` 关闭语义、标题栏、右侧任务路径签、按需配置浮层、一至三行自适应输入区、浏览器放大等效视口、标题生命周期、非流式 Provider 能力、`008_ai_conversation_titles.sql`、Title Run 数据模型/API、错误与测试策略。
- 设计明确参考 RikkaHub 源码的主回答成功后异步生成、独立标题模型回退结构、最近四条消息截断、重新读取会话避免并发覆盖、重新生成入口；Nautilus 当前阶段先使用触发 Chat Run 已冻结的 Provider/Model，未来扩展为“专用标题模型 -> 当前对话模型”。
- 自审已完成：无 `TBD/TODO`；未把附件、搜索、思考强度或自定义请求体带入本轮；明确不修改 `001`–`007`。兼容既有显式标题：`title_source` 包含 `manual`，`008` 只把“新的学习对话”和“与 AI 学习：…”旧机械标题标记为待自动生成，其他标题不被自动覆盖。
- 本轮只新增设计文件、更新进度文档和 `.gitignore` 已排除的 brainstorming 页面；没有创建 `008`，没有修改前后端业务代码、默认数据库或 `diagnostic-backups/`，没有提交、推送或部署。当前隔离 preview `5186/8012/8013` 与 brainstorming `51713` 继续运行。
- 精确下一项：用户审阅上述设计文件；批准后再编写实施计划，随后从 `008_ai_conversation_titles.sql` 开始实现和隔离验证。

### 2026-08-02（AI 学习室标题、密度与弹层交互实现）

- 用户批准 `docs/superpowers/specs/2026-08-02-nautilus-ai-learning-room-title-density-design.md` 后进入实现。新增 `backend/app/migrations/008_ai_conversation_titles.sql`，未修改 `001`–`007`；为 `conversation` 增加标题来源、生成状态、版本和生成时间，并新增独立 `conversation_title_run` 表与单对话活动运行唯一索引。
- 标题链路已接通：第一条用户提问写入时立即生成最多 32 字的本地兜底标题；首次成功 `tutor_chat` 完成后异步启动一次 Title Run，使用该 Chat Run 已冻结的 provider/model 配置和最近 4 条完整消息（每条最多 500 字、总计最多 2000 字）；标题调用为非流式、`max_tokens=48`、最多 30 秒。Title Run 只保存非敏感配置快照和输入消息 ID，不保存 API Key，也不额外复制消息正文。
- 标题失败不改变主回答状态、不插入对话错误消息、不自动反复重试；保留本地兜底标题。配置浮层提供“重新生成标题”，手动运行使用当前对话配置；完成写入采用 `title_revision` 条件更新避免旧结果覆盖新状态。服务启动会把遗留 `queued/running` 标题运行收敛为 `failed/interrupted`。
- 后端新增/修改：`backend/app/providers.py` 增加统一非流式 `generate_text`；`backend/app/conversations.py` 增加兜底标题、Title Run 生命周期和恢复默认对话配置；`backend/app/ai_runtime.py` 增加与 Chat Run 解耦的标题后台任务；`backend/app/routers/ai.py` 增加标题重生成、标题运行查询和删除对话配置 API；`backend/app/main.py` 增加启动恢复。主要专项测试位于 `backend/tests/test_ai_conversations.py`。
- 前端学习室按批准的 A 方案重排：移除常驻上下文栏、对话配置栏和独立状态栏；对话标题占据聊天窗口顶部，状态压缩为标题下的小字；任务路径改为聊天区右侧中部灰褐信息签并向左展开；对话配置改为 `#ddd5c7` 灰褐按钮和不参与布局回流的浮层，包含 provider/model、能力摘要、恢复默认和标题状态/重生成。新对话在发送前可在会话暂存中选择 provider/model，创建对话后先持久化配置再发送。
- 输入区改为一至三行自动增高：默认约 `52–79px`（依视口和提示行而定），文本域上限 `112px/22dvh`，低高度视口上限 `88px`；桌面、浏览器放大等效 `1024×640` 和移动 `390×844` 都保持消息区为主要剩余空间。模型发现下拉和学习室浮层统一支持捕获阶段 `pointerdown` 外部点击、`focusin` 焦点离开与 `Escape` 收起；实现复用 `frontend/src/useDismissibleLayer.ts`。
- 主要前端/测试文件：`frontend/src/AiLearningRoom.tsx`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/api.ts`、`frontend/src/styles/ai-learning.css`、`frontend/src/useDismissibleLayer.ts`、`frontend/e2e/ai-learning.spec.ts`、`scripts/mock-openai-provider.py`。Mock provider 把 Chat 和标题请求分别计数，仍不记录 Authorization、请求正文或测试假密钥。
- 最终验证：后端全量 `92 passed, 1 warning`；前端 production build 成功（`2064 modules transformed`）；最终完整 Playwright `16 passed`。`bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh`、`bash scripts/test-start-e2e-safety.sh`、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 真实截图与量化检查：`1440×1000` 为标题栏 `49.5px`、输入区 `79px`、消息区 `750.5px`；`1024×640` 放大等效视口为标题栏 `48px`、输入区 `79px`、消息区 `400px`；`390×844` 为标题栏 `46px`、输入区 `52px`、消息区 `637px`。三档文档宽高均等于视口，无页面级溢出；配置按钮实际背景为 `rgb(221, 213, 199)`，未使用白色。截图只写入 `/tmp`，未纳入仓库。
- 数据与运行边界：默认 `data/nautilus.sqlite3` 未写入，仍只应用 `001`–`004`；自动化和人工预览均使用 `/tmp` 隔离数据目录。最新隔离 production preview 已重启：Web `http://172.17.253.105:5186`、API `8012`、Mock provider `8013`，三项绑定 `0.0.0.0`；数据目录 `/tmp/nautilus-playwright.manual-title-density-v2-20260802` 已应用 `001`–`008`，加载 `/assets/index-Lz3CkQjA.js` 与 `/assets/index-D6lu5bjX.css`，不含 HMR。
- 已知风险：默认数据库尚未应用 `005`–`008`；真实外部 provider 仍未手动烟测；标题质量依赖所选模型且当前没有独立标题模型设置；工作区实现仍未提交。没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 精确下一项：用户硬刷新并在自己的缩放级别复验 `http://172.17.253.105:5186` 的标题、右侧任务签、灰褐配置按钮/浮层、输入区高度与模型下拉外部收起；确认后制定 `005`–`008` 默认数据库迁移演练清单，不直接进入附件、Web Search、思考强度或自定义请求实现。

### 2026-08-03（AI 学习室严重回归修复、历史管理与真实浏览器验收）

- DeepSeek/连接错误根因已分层：接管时本地 `5173/5186/8000/8012/8013` 均未监听，说明原始 `Failed to fetch` 至少可能发生在“浏览器到 Nautilus API”这一跳；代码同时确认 `frontend/src/api.ts` 未捕获 `fetch()` 网络异常，并且只解析字符串 `detail`，会丢失后端 `{detail:{kind,message}}`。现新增 `ApiError` 协议：浏览器网络失败明确显示“无法连接 Nautilus 本地服务”；后端结构化的鉴权、路径、限流、超时、网络、协议和上游错误保留可行动消息。模型发现失败只显示在模型/测试流程中并明确仍可手动填写，不阻止手动模型或 Chat Completions 测试，也不显示原生 `Failed to fetch`。
- 任务上下文丢失根因已修复：`Workspace.openAiLearning()` 原先保留旧 `conversationId/runId/pending`，`AiLearningRoom.loadRoom()` 又无条件优先恢复该 ID，导致任务入口可带入独立或错误上下文会话。显式任务入口现在清除不可信活动 ID，再按后端列表恢复该任务最近一条有效对话；学习室内部历史切换仍保存当前选择，刷新后可恢复独立或其他任务对话。任务内点击加号的新对话继续把当前任务 ID 写入后端 `conversation_link`，不会覆盖旧任务对话关联。
- 修复了“最近任务对话”排序的不确定性：同一秒内连续创建/发送两段对话时，旧时间字符串只有秒精度，列表排序可能并列并错误恢复第一段。`backend/app/conversations.py` 的新写入时间改为 UTC 微秒精度，列表增加稳定 `rowid` 次序；旧秒精度 ISO 时间字符串仍与新值兼容，无需迁移。新增后端回归测试验证同一任务多对话按最近消息稳定排序。
- 学习室接入最小历史管理：外层标题工具区新增“对话历史”，显示持久化标题、当前项、当前任务/其他任务/独立对话标识，以及加载、空、失败状态；可新建当前任务对话并切换任意历史项。切换会从后端详情和对话配置 API 恢复消息、标题、provider/model 配置、活动 Run 和任务上下文；独立对话上下文不再被入口任务的 React 临时状态覆盖。
- 对话配置入口已从 `.ai-room-chat` 消息画布移到 `.ai-room-header` 外层工具区，保留 `#ddd5c7` 灰褐视觉、外部点击、焦点离开和 Escape 关闭。历史和配置在移动端使用图标按钮，浮层内部文字按钮不再被错误压缩为 36px；输入 placeholder 缩短，390px 宽度下不换行裁切。右侧任务路径信息签保持已批准的位置和行为。
- 本轮修改文件：`frontend/src/api.ts`、`frontend/src/AiProviderDialog.tsx`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/Workspace.tsx`、`frontend/src/styles/ai-learning.css`、`frontend/e2e/ai-learning.spec.ts`、`backend/app/conversations.py`、`backend/tests/test_ai_conversations.py` 和本进度文档。没有新增或修改迁移 `001`–`008`；没有修改、删除或暂存 `diagnostic-backups/`；没有提交、推送或部署。
- 最终自动化验证：后端全量 `103 passed, 1 warning`；前端 production build 成功（`2064 modules transformed`，仅有既有的 500kB chunk 警告）；AI 学习室定向 Playwright `11 passed`；最终项目 Playwright 全量 `21 passed`。`bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh`、`bash scripts/test-start-e2e-safety.sh`、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 真实 Chromium production preview 验证：`1440×1000` 消息区 `750.5px`，`1024×640` 消息区 `400px`，`390×844` 消息区 `637px`；三档 `scrollWidth/scrollHeight` 均等于视口，`roomBottom` 不超过视口，`configInsideChat=false`。逐张检查桌面、紧凑、移动、移动历史浮层和移动配置浮层截图，无页面级溢出、文字裁切或控件重叠。截图仅位于 `/tmp`，未纳入仓库。
- 数据和运行状态：所有自动化与人工浏览器写入均使用新的 `/tmp/nautilus-playwright.*` 数据目录和 Mock provider；默认 `data/nautilus.sqlite3` 只读核对仍为 `001`–`004`、`integrity_check=ok`。当前隔离 preview 为 Web `http://172.17.253.105:5197`、API `8024`、Mock provider `8025`，绑定 `0.0.0.0`；隔离库应用 `001`–`008` 且 `integrity_check=ok`。
- 已知风险：未读取或使用用户真实 API Key，因此真实 DeepSeek 的账户权限、额度、TLS/DNS 和上游兼容性仍待用户侧复验；本轮已保证这些失败不再笼统显示为 `Failed to fetch`。默认数据库尚未应用 `005`–`008`；附件、Web Search、思考强度、自定义 Headers/Body 和高级历史管理（搜索、置顶、归档、批量操作）仍未实现。
- 精确下一项：用户在 `http://172.17.253.105:5197` 使用现有 DeepSeek 配置执行一次模型发现和手动模型 Chat Completions 连接测试，并反馈新的具体错误类别或成功结果；通过后立即编写并演练默认数据库 `005`–`008` 的备份、迁移、完整性校验和回滚清单，不扩展附件、搜索或自定义请求。

### 2026-08-03（AI 对话信息层级、历史改名删除与标题生成修复）

- 用户明确要求把“当前对话信息”从聊天画布内移到“对话历史”附近，并在历史浮层中直接改名、通过确认弹窗删除；同时要求标题正中显示，移除标题下方机器人图标和“回答完成/可以开始提问”等常驻状态。新增经用户确认的设计 `docs/superpowers/specs/2026-08-03-nautilus-conversation-management-layout-design.md`，未新增数据库迁移。
- 标题问题已定位到实际 Title Run，而不是前端只拿首问当最终标题：隔离验收库的两条 fallback 对话均记录 `title_generation_status=failed`，对应 Title Run 为 `protocol_error`，错误是非流式响应没有最终正文。现有标题调用只给 `max_tokens=48`，推理模型可能把预算全部用于 `reasoning_content`。`backend/app/ai_runtime.py` 将标题输出预算提高到 `512`，`backend/app/providers.py` 对“只有推理、没有最终文本”给出明确协议错误；前端在主回答后对 `pending/queued/running` 增加入队宽限轮询，避免极短竞态漏掉标题任务。首问仍只作为即时和失败回退，不再被误认为正常最终标题。
- 新增 `PATCH /api/ai/conversations/{conversation_id}` 与 `DELETE /api/ai/conversations/{conversation_id}`。手动改名会设置 `title_source=manual`、`title_generation_status=idle`、增加 `title_revision`，并把旧的活动 Title Run 标记为 `superseded`；软删除复用既有 `conversation.deleted_at`，保留消息和运行记录。存在 `queued/running` Chat Run 时返回 409，要求先取消生成；发送事务也重新检查对话未被软删除，封住删除与发送并发写入。
- 前端外层工具区顺序调整为“对话历史 / 当前对话信息 / 对话配置 / AI 提供方设置 / 新建对话”。当前对话信息浮层继续显示任务路径、状态、截止日期和进度，但入口和浮层不再属于 `.ai-room-chat`。历史行拆为独立切换区、编辑图标和删除图标；编辑支持 Enter 保存、Escape 取消，删除使用 `DialogPortal` 确认弹窗，取消后保留历史浮层。删除当前对话后优先恢复同一任务最近的有效对话，没有候选时回到当前任务的空白新对话状态。
- 聊天标题栏只保留单行居中标题，删除 `.ai-status`、机器人图标、回答完成/可以开始提问、重连计数和标题生成中提示。运行反馈仍由流式消息、取消按钮、错误条和重试入口承担；对话配置浮层继续显示标题生成状态和手动重生成入口。
- 本轮主要修改文件：`backend/app/schemas.py`、`backend/app/routers/ai.py`、`backend/app/conversations.py`、`backend/app/ai_runtime.py`、`backend/app/providers.py`、`backend/tests/test_ai_conversations.py`、`frontend/src/api.ts`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/styles/ai-learning.css`、`frontend/e2e/ai-learning.spec.ts`、`scripts/mock-openai-provider.py`、上述新设计文件和本进度文档。迁移 `001`–`008` 均未修改，没有新增 `009`。
- 自动化验证：标题/改名/删除后端定向测试通过；`backend/tests/test_ai_conversations.py` 为 `52 passed`，`backend/tests/test_providers.py` 为 `23 passed`，后端全量为 `107 passed, 1 warning`。最终 production build 成功（`2064 modules transformed`，仅有既有 500kB chunk 警告）；AI 学习室 Playwright `12 passed`，最终项目 Playwright `22 passed`。启动脚本语法检查、安全测试、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 真实 Chromium production preview 使用 `/tmp/nautilus-playwright.manual-conversation-management-20260803`、Web `5198`、API `8026`、Mock provider `8027`，均绑定 `0.0.0.0`。`1440×1000`、`1024×640`、`390×844` 的文档宽高均等于视口；消息区分别约 `758/406/643px`，标题中心偏差均为 `0px`，信息按钮分别紧邻历史按钮 `8/8/4px`，`infoInsideChat=false`、`.ai-status=0`。历史浮层、任务信息浮层和移动删除确认均完整位于视口内；刷新前三档 conversation ID 保持一致；控制台错误和请求失败均为零。截图只写入 `/tmp`。
- 安全与边界：本轮自动化和人工浏览器仅使用 `/tmp` 隔离库、假密钥和 Mock provider，没有触碰默认 `data/nautilus.sqlite3`，没有读取或修改 `diagnostic-backups/`，没有提交、推送或部署。没有读取用户真实 DeepSeek API Key，因此真实 DeepSeek 推理模型在 `512` token 和 30 秒限制下的标题质量仍需用户侧复验；若仍只返回推理或超时，会保留首问回退并可手动重生成。
- 精确下一项：用户在 `http://172.17.253.105:5198` 复验信息入口位置、历史改名/删除确认和真实 DeepSeek 首轮标题覆盖。通过后制定并演练默认数据库 `005`–`008` 的备份、迁移、完整性校验和回滚清单；不直接扩展附件、Web Search、思考强度或自定义请求。

### 2026-08-04（计划信息架构、文档式大纲与分级 AI 设计确认）

- 用户确认计划入口采用 A“全部计划总览清单 -> 独立计划详情”，并确认计划详情的结构编辑采用 B“文档式层级大纲 + 节点内联编辑”。计划详情包含 `概览 / 结构 / 排期`，科目进度与近期任务上下排列，不再使用中栏固定窄树侧栏。
- 新增正式规格 `docs/superpowers/specs/2026-08-04-nautilus-plan-information-architecture-design.md`。规格明确：`＋科目` 归属计划标题，`＋主题/＋任务` 归属对应父节点；箭头、名称、复选框、任务 AI 和更多菜单分别只承担一种行为；同一时间只开一个编辑器；dirty 切换使用“保存/放弃/继续编辑”。
- 对默认折叠问题采用结构性处理：计划总览和结构编辑分成不同内容表面；首次进入结构只自动展开“下一项”所在焦点路径，用户操作后的展开状态按计划保存在 `sessionStorage`，其余分支不自动展开。计划行“下一项”定义为后端稳定计算的下一条可执行任务，不表示下一个计划。
- 规格确定任务完成必须可撤销并恢复完成前的状态和进度，同时保留学习时长与会话历史；预计实施时新增 `009_task_completion_restore.sql`，不修改 `001`–`008`。迁移前既有已完成任务因无法还原未知旧值，首次撤销使用明确的 `pending / 0%` 兼容回退。
- 规格确定首页、计划详情和任务入口分别使用 `global / plan / task` AI 上下文，三者复用现有 provider、对话、运行、标题、SSE 和历史管理链路。为区分全局对话与既有独立对话，预计新增 `010_ai_conversation_scope.sql`，并保持既有无关联对话为 `independent`。
- 本轮只新增上述正式规格并更新本进度文档；没有修改前后端业务代码、没有创建或应用迁移、没有写入默认 `data/nautilus.sqlite3`，没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 本轮未运行后端、构建或 Playwright，因为没有业务代码变化；规格自审已完成，无 `TBD/TODO`，迁移、恢复、响应式和验收边界均已明确。当前设计伴随页仍运行在 `http://172.17.253.105:51769`；此前隔离预览 `5197/8024/8025` 与 `5198/8026/8027` 也仍在监听，本轮未重启或写入这些环境。
- 精确下一项：用户复核新规格；确认后进入实施计划，不直接开始编码。实施顺序为计划汇总/详情与可逆完成测试 -> `009` -> 计划总览/概览/文档式结构/排期 -> `010` -> 分级 AI 上下文与全量验证。

### 2026-08-04（计划设计伴随服务恢复）

- 用户反馈上一条回复提供的设计伴随链接无法访问。核对确认原 `51769` 及先前 `5197/5198` 隔离预览均已停止，属于本地进程生命周期问题，不是设计文件丢失或业务代码回归。
- 使用 brainstorming 伴随服务重新托管最新 `plan-outline-b-detail-v1.html`，新服务绑定 `0.0.0.0:56955`，当前 WSL2 地址为 `http://172.17.253.105:56955`。宿主侧根地址检查返回 `200`，响应内容包含“文档式计划大纲”“极限综合练习”和计划级上下文标识。
- 第一次重启产生的重复端口 `54295` 已停止；当前只保留 `56955`。本轮没有启动标准 `5173/8000` 或隔离业务 preview，没有写入默认数据库。
- 本轮只更新运行状态和本进度文档，没有修改业务代码、迁移、正式规格或 `diagnostic-backups/`，没有提交、推送或部署；未运行 pytest、构建或 Playwright。
- 精确下一项仍为用户复核 `docs/superpowers/specs/2026-08-04-nautilus-plan-information-architecture-design.md`；确认后编写实施计划。

### 2026-08-05（计划设计页面再次恢复）

- 原 brainstorming 服务因空闲自动退出导致 `56955` 不可访问。现改用不带空闲退出机制的 Python 静态服务重新绑定 `0.0.0.0:56955`，宿主侧检查返回 `200`。
- 本轮只恢复设计页面并更新运行记录，没有修改业务代码、迁移、默认数据库或 `diagnostic-backups/`，没有提交、推送或部署。
- 当前地址：`http://172.17.253.105:56955`；下一项仍为用户复核计划信息架构规格。

### 2026-08-05（结构页默认编辑器修正）

- 用户指出设计稿在进入结构页时默认打开“极限综合练习”编辑器，与“用户点击节点名称才编辑”的确认语义冲突。
- 已修改被 `.gitignore` 排除的设计伴随文件：结构页初始只展开焦点路径，不选中任务、不显示编辑器；点击“极限综合练习”名称后才显示对应内联编辑器，点击取消会关闭编辑器并清除选中状态。
- 真实 Chromium 验证结果：`initial=false`、点击任务名称后 `afterClick=true`；`1440x1000` 初始截图确认页面只展示结构行，没有默认编辑块。
- 正式规格原本已明确“自动展开焦点路径但不自动打开编辑器”，因此未修改业务代码、迁移或正式规格；当前在线地址仍为 `http://172.17.253.105:56955`。

### 2026-08-05（任务节点行单开折叠交互细化）

- 用户进一步明确任务编辑交互：点击任务节点行的主区域打开编辑器；再次点击当前任务时收起；点击其他任务时关闭当前编辑内容并在新任务下方打开同一个编辑器。
- 前端命名确定为“任务节点行”（组件建议 `TaskOutlineItem`），标题和摘要所在点击区称“任务节点主区域”。任务复选框、任务 AI 和更多菜单保持独立，不触发编辑器切换。
- 已更新设计伴随稿和正式规格 `docs/superpowers/specs/2026-08-04-nautilus-plan-information-architecture-design.md`。设计稿使用单一可移动编辑器，不为每个任务常驻复制表单。
- 真实 Chromium 验证：`initial=false`；点击第一项后 `openA=true`；再次点击为 `closeA=false`；点击另一任务后 `switchB=true`，标题正确更新为“编辑任务：导数错题复盘”。
- 本轮没有修改业务代码、迁移、默认数据库或 `diagnostic-backups/`；在线地址仍为 `http://172.17.253.105:56955`。

### 2026-08-05（计划信息架构、可逆完成与分级 AI 纵切片落地）

- 按 `2026-08-04-nautilus-plan-information-architecture-design.md` 和对应实施计划完成计划信息架构纵切片。计划视角首先显示全部计划总览，不默认打开第一条计划树；单计划详情提供概览、结构和排期，URL 可恢复计划、子视图和目标任务。
- 新增 `GET /api/plans/summary`、`GET /api/plans/{goal_id}`、`GET /api/plans/{goal_id}/schedule` 和 `PUT /api/tasks/{task_id}/completion`。下一任务使用服务端稳定排序；完成前保存状态/进度，撤销时精确恢复，旧完成任务回退 `pending / 0%`，历史学习时长和已结算会话不回滚。
- 新增迁移 `backend/app/migrations/009_task_completion_restore.sql` 与 `backend/app/migrations/010_ai_conversation_scope.sql`。AI 对话持久化 `independent / global / plan / task` 范围，全局、计划和任务入口复用同一 provider、对话、运行、标题、SSE 和历史管理链路，只改变有界上下文和冻结快照范围；旧任务关联对话回填为 `task`，无关联对话保持 `independent`。
- 前端新增 `PlanWorkspace.tsx`、`PlanOverview.tsx`、`PlanStructure.tsx`、`PlanSchedule.tsx` 和 `UnsavedChangesDialog.tsx`，重构 `PlanEditor.tsx`。结构页所有科目常显，焦点路径和会话展开状态独立；初始不打开编辑器，点击任务节点主区域执行打开、再次点击收起、点击其他任务移动唯一编辑器。复选框、任务 AI 和更多菜单不切换编辑器。
- dirty 修改在切换节点、子视图、计划和 AI 入口时统一提供保存、放弃和继续编辑；浏览器刷新使用原生提示。本次收尾补齐计划设置弹窗的关闭按钮、背景点击和 Escape 未保存保护，并验证新建节点 API 失败时错误和输入都保留。
- 今日、任务列表、计划概览、结构和排期均支持完成/撤销。计划排期进入学习日历时写入可刷新恢复的 `plan_filter`，页面显示可清除筛选；工作区补充 `popstate` 恢复，浏览器后退/前进不会出现 URL 与视图不一致。
- 首页和计划详情右栏分别使用全局/计划 AI；任务 AI 只由明确入口触发。`1180px` 以下使用 AI 学习伙伴抽屉，1024 和 390 视口下均验证 Escape、背景点击关闭和无页面级溢出。
- 主要后端改动文件：`backend/app/plans.py`、`backend/app/schemas.py`、`backend/app/routers/plans.py`、`backend/app/conversations.py`、`backend/app/routers/ai.py`、迁移 `009/010`、`backend/tests/test_plans.py`、`backend/tests/test_ai_conversations.py`。
- 主要前端改动文件：`frontend/src/api.ts`、`frontend/src/Workspace.tsx`、`frontend/src/AiCompanionPanel.tsx`、`frontend/src/AiLearningRoom.tsx`、`frontend/src/PlanWorkspace.tsx`、`frontend/src/PlanOverview.tsx`、`frontend/src/PlanStructure.tsx`、`frontend/src/PlanSchedule.tsx`、`frontend/src/PlanEditor.tsx`、`frontend/src/UnsavedChangesDialog.tsx`、`frontend/src/CalendarView.tsx`、`frontend/src/styles/plan-editor.css`、`frontend/src/styles/v6-workspace.css`、`frontend/src/styles/ai-learning.css`、`frontend/src/styles/task-calendar.css`、`frontend/e2e/plan-workspace.spec.ts` 和 `frontend/e2e/ai-learning.spec.ts`。
- 最终验证：后端全量 `114 passed, 1 warning`；production build 成功，`2069 modules transformed`；Playwright 全量 `31 passed`。启动脚本语法、安全测试、`.venv/bin/pip check` 和 `git diff --check` 均通过。
- 真实 Chromium production preview 使用 `/tmp/nautilus-playwright.manual-plan-ia-1785941304`，Web `http://172.17.253.105:5196`、API `8022`、Mock provider `8023`。`1440x1000`、`1024x640`、`390x844` 文档宽高均等于视口；逐张检查总览、单编辑器、dirty 弹窗、计划筛选日历和两档 AI 抽屉，无重叠或文字截断。截图仅位于 `/tmp/nautilus-visual-plan-ia-1785941304`。
- 数据与安全边界：隔离库应用 `001`-`010` 且 `integrity_check=ok`；默认 `data/nautilus.sqlite3` 只读核对仍为 `001`-`004` 且 `integrity_check=ok`。没有读取真实 provider 凭据，没有修改、删除或暂存 `diagnostic-backups/`，没有提交、推送或部署。
- 已知风险：默认数据库尚未应用 `005`-`010`；完整甘特、任务依赖、回收站恢复、身份时区“今日”和计时重启策略仍未完成；真实外部 provider 未在本轮烟测。
- 精确下一项：用户先复验 `http://172.17.253.105:5196`。确认后编写默认数据库 `005`-`010` 的备份、副本迁移、完整性/外键校验和回滚恢复清单；未经用户明确确认不得对默认数据库应用迁移。

### 2026-08-06（本地 Git 检查点与新窗口产品讨论交接）

- 用户明确要求在新开窗口前完成 Git commit 管理，但暂不上传云端。已按职责拆分本地提交：`f48da8d` 后端与迁移、`0560a99` 前端工作区与 E2E、`953be34` 本地运行与仓库规则、`8ffea0a` 正式规格与实施决策；本进度文档由独立检查点提交保存。
- 提交前使用精确路径暂存并逐批运行 `git diff --cached --check`；没有使用 `git add .`。依赖、构建产物、Playwright 输出、默认数据目录和运行令牌继续由 `.gitignore` 排除。
- 敏感信息扫描只命中后端/前端测试中的明确假密钥，没有发现真实运行凭据、私钥或 Bearer Token。`diagnostic-backups/` 保持未跟踪，未读取其内容、未修改、未暂存、未提交。
- 同步校正文档漂移：README 已列出当前计划和 AI 纵切片；AGENTS 规定现有 `001`-`010` 迁移不可修改，未来从 `011` 开始；已实现规格状态改为“已实现并完成隔离验收”；计划信息架构实施计划 52 项清单均标记完成并记录最终验证结果。
- 本轮没有修改业务代码、数据库或运行数据，也没有重新执行全量测试；提交内容对应上一轮已经通过的后端 `114 passed, 1 warning`、production build 成功和 Playwright `31 passed` 基线。所有提交均仅保存在本地 `main`，没有执行 `git push`。
- 上一轮 `5196/8022/8023` 隔离 preview 当前已离线。新窗口如需页面核对，应重新使用独立 `/tmp/nautilus-*` 数据目录启动，不得使用默认 `data/`。
- 精确下一项：新窗口先讨论 Nautilus 的整体产品定位、目标用户、核心使用闭环、3-5 个真实产品亮点和全局/计划/任务 AI 的产品边界，默认不修改代码；确认产品方向后再决定默认数据库迁移演练和下一工程纵切片。

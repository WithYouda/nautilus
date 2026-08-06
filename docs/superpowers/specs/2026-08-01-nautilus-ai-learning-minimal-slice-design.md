# Nautilus AI 学习最小可用纵切片设计

| 项目 | 内容 |
| --- | --- |
| 日期 | 2026-08-01 |
| 状态 | 用户已确认，已实现并完成隔离验收 |
| 上位规格 | `docs/superpowers/specs/2026-07-23-nautilus-design.md` |
| 相关布局讨论稿 | `docs/superpowers/specs/2026-08-01-nautilus-workspace-layout-design.md` |

## 1. 目标

本轮交付一个可由普通用户完成的 AI 学习最小纵切片：

```text
选择当前任务
  -> 查看只读任务/计划上下文
  -> 创建或打开普通线性对话
  -> 发送学习问题
  -> 通过 SSE 查看流式回复
  -> 追加式保存消息与上下文快照
  -> 可显式取消
  -> 刷新、断线或重复提交不产生重复 AI 运行
```

当前工作区已经存在未交付的后端实现。本轮不重写整个 AI 子系统，而是先修复已确认的数据安全和运行一致性风险，再补齐最小前端与真实浏览器验证。

## 2. 范围

### 2.1 本轮包含

- 本地加密 `CredentialStore` 的依赖、权限、损坏和跨存储一致性边界。
- 一个 OpenAI Chat Completions 风格兼容提供方。
- 非敏感提供方配置、掩码 API key 状态和连接测试。
- 普通线性 `conversation`、追加式 `message`、`conversation_link`、`context_snapshot` 和 `ai_run`。
- 当前任务及其目标、科目、主题的只读上下文预览与请求快照。
- SSE 流式输出、取消、断开重连、刷新恢复和提交幂等。
- 不依赖新视觉方案的简化 AI 学习室。
- 极简提供方设置面板，使用户无需手工调用 API 即可完成配置。
- 后端 Mock HTTP 测试和隔离的浏览器 Mock provider 测试。

### 2.2 本轮不包含

- v5/v6 视觉风格落地或统一工作区大规模重构。
- 对话分支、分支图、React Flow 画布或分支合并。
- 知识源连接器、资料导入、FTS5、知识卡片或学习记录写入。
- AI 计划生成、引导规划、重排、审批流或 LangGraph 多工作流。
- Gemini、Anthropic 等多个原生提供方。
- 云同步、桌面封装或移动客户端。

## 3. 架构边界

### 3.1 CredentialStore

- 使用成熟的 `cryptography.Fernet`，并在后端依赖中声明版本范围。
- 凭据目录固定在 `NAUTILUS_DATA_DIR/runtime/credentials`。
- 目录权限为 `0700`，主密钥和密文文件权限为 `0600`；无法收紧权限时失败关闭。
- API key 不进入 SQLite、日志、Cookie、前端持久化、对话内容、进度文档或备份范围。
- 已存在但为空、无法解密或内容损坏的密文文件视为错误，不静默当作空存储。
- 提供方配置与凭据文件无法共享数据库事务，因此采用补偿式一致性：
  - 新建数据库记录失败时删除刚写入的凭据。
  - 更新数据库记录失败时恢复旧凭据。
  - 删除凭据失败时不把提供方删除报告为完全成功。
- 对外接口只返回 `has_api_key`、掩码和不含秘密的错误状态。

### 3.2 Provider Adapter

- 首轮只实现 `openai_compatible`，使用现有 `httpx` 和 `/chat/completions`。
- base URL 使用结构化 URL 校验：拒绝 userinfo、query 和 fragment；远程地址要求 HTTPS，回环地址允许 HTTP，供本地服务与自动化 Mock 使用。
- 每次运行冻结 provider、model、base URL、timeout 和 `config_version`；运行开始后配置变化不影响本次调用。
- `config_version` 在任何影响实际出站调用的配置变化时递增，包括模型、base URL、API key 和 timeout。
- 流式协议必须识别：
  - 正常正文增量与明确结束标记。
  - HTTP 错误、流内错误对象、非法 JSON、空响应、缺少结束标记和异常提前结束。
  - 协议异常统一记录为不含秘密的 `protocol_error`，不得保存为成功。
- 设置单次运行总时限、最大响应字符数和有限的活动运行数，避免无限流导致内存无界增长。

### 3.3 对话与运行

- 普通对话保持线性，不提前引入 `branch`。
- 消息只追加，不原地重写历史用户消息；助手占位消息只在对应运行收敛时更新其流式内容和状态。
- 一个对话同一时间最多一个 `queued/running` 运行，由数据库部分唯一索引保证，不只依赖应用层查询。
- `client_message_id` 在一个对话内唯一：
  - 相同 ID 与相同正文命中已有运行并返回 `created=false`。
  - 相同 ID 与不同正文返回 `409 Conflict`，不得静默吞掉新问题。
- 创建运行时在同一数据库事务内写入：上下文快照、用户消息、助手占位和 `ai_run`。
- `prepare_run` 返回已经冻结的 provider runtime 配置；运行器不得在提交后再次读取可变 provider 状态。
- 若后台任务在数据库提交后无法启动，必须立即把运行和助手消息收敛为 `failed`，不能遗留永久 `queued`。
- 最终 SSE 事件只能在运行结果成功持久化后发送；持久化失败时返回明确的内部错误状态。
- 浏览器断开只取消订阅，不取消上游生成；用户点击取消才调用取消 API。
- 服务重启后遗留的 `queued/running` 运行在读取或订阅时收敛为 `failed/interrupted`，不重复调用 provider。

### 3.4 数据库迁移

- `001_initial`、`002_learning_plans`、`003_dashboard_layouts` 和 `004_plan_editor` 保持不变。
- 默认用户数据库尚未应用 `005_ai_conversations`，因此可在首次正式应用前修正该迁移。
- `005` 建立：`provider_profile`、`conversation`、`conversation_link`、`message`、`context_snapshot` 和 `ai_run`。
- AI 运行与消息追溯字段统一使用 SQLite `DEFERRABLE INITIALLY DEFERRED` 外键：助手占位消息的 `ai_run_id`、运行的请求消息 ID 和响应消息 ID 在同一事务提交时一起校验；删除消息时追溯字段置空，避免孤立记录且不破坏当前插入顺序。
- 数据库迁移器必须把单个迁移脚本和 `schema_migrations` 记录放在同一个显式事务中；任何语句失败时整体回滚。
- 测试覆盖成功应用、重复打开幂等和故障脚本不留下表、索引或版本记录。

## 4. API

所有接口继续使用当前本地会话身份校验。

### 4.1 Provider

```text
GET    /api/ai/provider
PUT    /api/ai/provider
DELETE /api/ai/provider
POST   /api/ai/provider/test
```

- GET 只返回非敏感配置、掩码、连接测试状态和凭据错误状态。
- PUT 中 API key 留空表示保留原密钥；首次配置必须提供密钥。
- 连接测试使用当前保存配置，不返回完整请求或密钥。

### 4.2 对话与上下文

```text
GET    /api/ai/conversations
POST   /api/ai/conversations
GET    /api/ai/conversations/{conversation_id}
GET    /api/ai/tasks/{task_id}/context
```

- 对话可以关联当前任务；后端据此读取目标、科目、主题和任务上下文。
- 对话详情返回消息和当前活动运行，作为刷新恢复的权威状态。
- 进入学习室不自动创建空对话；打开已有任务对话，或在首次发送时创建。

### 4.3 发送、流式与取消

```text
POST   /api/ai/conversations/{conversation_id}/messages
GET    /api/ai/runs/{run_id}/stream
POST   /api/ai/runs/{run_id}/cancel
```

- POST 返回运行、是否新建和当前消息快照。
- SSE 事件：
  - `start`：包含当前完整已生成文本，用于刷新重连时替换本地缓冲。
  - `delta`：只包含新增文本，用于追加。
  - `done`：包含最终状态和完整文本。
  - `error`：包含脱敏错误、失败状态和已生成的部分文本。
- 重连必须复用同一 `run_id`，不得重新 POST。

## 5. 前端设计

### 5.1 工作区入口

- 保留现有 `Workspace` 的今日、任务、计划和日历结构。
- 在今日页选中任务的固定操作区提供“与 AI 学习”按钮；入口不能只放在可隐藏的上下文模块中。
- 进入 AI 学习室是同一浏览器工作区内的模式切换；保留当前任务、计时状态和返回前视图。

### 5.2 简化学习室

新增独立 `AiLearningRoom`，首轮只包含：

- 返回工作区。
- 当前任务/计划只读上下文预览。
- 当前任务相关的已有对话选择和新对话入口。
- 线性消息列表。
- 输入框、发送、流式状态和取消按钮。
- provider 未配置、连接错误、运行失败、取消和重新连接状态。
- “重新发送”以新的 `client_message_id` 追加新消息，不修改历史失败消息。

不实现三栏、分支画布、知识源栏或新的视觉语言。桌面复用现有页面宽度和 token；移动端采用单列布局。

### 5.3 Provider 设置

- 从学习室的阻塞状态或“AI 设置”入口打开极简对话框。
- 字段：显示名称、base URL、模型、API key、启用状态和 timeout；提供保存与连接测试。
- API key 输入值只保存在 React 表单内存中；关闭或保存后清空，不写 localStorage、sessionStorage、URL 或日志。
- 已保存时只显示后端掩码，不把掩码当作可提交的新密钥。

### 5.4 刷新、断开和幂等

- 当前 `conversation_id`、`run_id` 和尚未确认结果的 `client_message_id` 可保存在 sessionStorage；不保存 API key。
- POST 前生成稳定的 `crypto.randomUUID()`，请求结果不确定或页面刷新时复用同一 ID。
- 页面恢复后先 GET 对话详情；若存在活动运行，订阅同一 `run_id`。
- `start.content` 替换本地助手缓冲，`delta.text` 才追加，避免重放文本重复。
- 网络断开采用有界退避重连；超过次数后提供手动重连，不自动重新提交问题。
- 组件卸载或返回工作区只关闭订阅；取消按钮明确调用取消 API。

### 5.5 移动端最低要求

- `390px` 下保持单列、无页面级横向溢出。
- 上下文可折叠，消息长文本与代码允许换行。
- 输入区和取消按钮保持可见，按钮触控高度至少约 40–44px。
- 使用 `aria-live=polite` 宣告短状态，不逐 token 触发读屏。

## 6. 测试策略

### 6.1 后端

- CredentialStore：保存、读取、覆盖、删除、严格权限、无法收紧权限、错误主密钥、空/损坏密文、原子替换失败和补偿恢复。
- Provider：正常流、HTTP 错误、流内错误、非法 JSON、空响应、缺失结束标记、超时、总长度/时间限制和脱敏日志。
- 对话：身份隔离、上下文快照、追加式消息、同 ID 同正文重放、同 ID 不同正文冲突、并发双提交和单活动运行约束。
- AI 运行：正常、provider 失败、启动失败收敛、取消、订阅断开、重连、服务重启中断和持久化失败。
- 迁移：成功应用、重复打开幂等、失败整体回滚和 `001`–`004` 不变。

### 6.2 浏览器

- Playwright 继续使用独立 `/tmp/nautilus-playwright.*`，但启动脚本先解析真实路径并验证目标确实位于 `/tmp` 下；清理不得依赖未经解析的字符串前缀。
- 启动测试专用本地 OpenAI 兼容 HTTP 服务，模型请求由后端真实发出，不使用浏览器路由伪造。
- Mock provider 支持确定场景：正常延迟分块、慢流、认证/服务错误和非流式连接测试。
- 覆盖：
  - 从当前任务进入学习室、配置 provider、正常分块完成。
  - 刷新后仍只有一对消息和一个运行。
  - 慢流取消并保留部分文本。
  - 流中刷新/断开后重连同一运行。
  - provider 错误、错误状态和重新发送。
  - 移动 `390px` 无横向溢出。
- 自动化测试不得调用真实 AI API，不得读取或写入默认 `data/nautilus.sqlite3`。

## 7. 实施顺序

1. 修复测试数据目录真实路径保护和迁移原子性。
2. 补齐依赖、CredentialStore 与 provider 安全边界。
3. 修复运行冻结配置、收敛、协议校验、并发和幂等边界。
4. 扩展后端测试并运行完整后端基线。
5. 接入前端 API、provider 设置和简化学习室。
6. 增加本地 Mock provider 与 AI Playwright。
7. 运行完整后端、构建、Playwright、脚本语法和 `git diff --check`。
8. 更新开发状态；仅在全部隔离验证通过后，才考虑启动标准服务并将 `005` 应用到默认数据库。

## 8. 完成定义

本轮完成时，用户能够从当前任务进入简化学习室，经前端配置一个 OpenAI 兼容提供方，查看只读上下文，发送问题，看到真实 SSE 增量，取消请求，并在刷新或断线后恢复同一运行；消息、上下文快照和运行记录保持追加式、可追溯且不重复。API key 不进入 SQLite、日志、Cookie、前端持久化或对话内容。

这只是 AI 学习最小可用纵切片，不代表 AI 阶段、对话阶段或首阶段产品完成。

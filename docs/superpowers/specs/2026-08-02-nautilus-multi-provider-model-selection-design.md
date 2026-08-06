# Nautilus 多提供方、多模型、对话级选择与配置快照设计

| 项目 | 内容 |
| --- | --- |
| 日期 | 2026-08-02 |
| 状态 | 用户已确认，已实现并完成隔离验收 |
| 上位规格 | \`docs/superpowers/specs/2026-07-23-nautilus-design.md\` |
| 前置设计 | \`docs/superpowers/specs/2026-08-01-nautilus-ai-learning-minimal-slice-design.md\`、\`docs/superpowers/specs/2026-08-02-nautilus-ai-learning-interaction-design.md\` |
| 适用阶段 | 第一阶段：多提供方、多模型、学习室选择、能力元数据和运行配置快照 |

## 1. 目标与边界

本设计把当前“一个 \`provider_profile\`、一个模型、一个线性对话默认配置”的最小纵切片，扩展为可安全演进的配置层级：

\`\`\`text
本地身份
  -> Provider Profile（连接端点与凭据引用）
    -> Provider Model（该端点可用的具体模型与能力）
      -> Conversation Config（该对话的选择与临时覆盖）
        -> Run Snapshot（本次请求的不可变有效配置）
\`\`\`

第一阶段必须交付：

- 同一身份可保存多个独立提供方配置，并明确一个默认提供方。
- 每个提供方可维护多个模型，支持自动发现、缓存和手动添加。
- 学习室可在对话级切换提供方和模型；切换不修改其他对话或全局默认值。
- 模型保存规范化能力元数据，未知能力不得被前端臆测为支持。
- Provider、Model、Conversation、Run 四层配置边界清晰；运行启动时冻结完整的非敏感配置快照，并在内存中冻结对应凭据。
- 现有 OpenAI 兼容线性对话继续可用，旧接口在迁移期保持兼容。

第一阶段明确不交付：

- Gemini、Anthropic 等原生适配器的实际出站调用；它们只通过适配器注册接口保留扩展位。
- 对话级思考强度、Web Search、图片或文件附件、附件预览和失败重试。
- 自定义 Headers、Custom JSON Body、Provider/Model 覆盖规则、请求预览和敏感 Header 加密配置。
- 分支对话、消息编辑/重新生成、Token 统计、知识库/RAG、OAuth、MCP、Shell/Python、任意网络爬取、云同步、图像生成、语音和视频。

本设计只规定第一阶段的基础架构。第二至第四阶段必须在此边界上另写规格，不得把未实现能力提前暴露为可操作控件。

## 2. 当前架构核对结论

当前代码的真实边界如下：

- \`backend/app/migrations/005_ai_conversations.sql\` 已定义 \`provider_profile\`、\`conversation\`、\`message\`、\`context_snapshot\` 和 \`ai_run\`；默认数据库尚未应用 \`005\`，隔离库已验证 \`001\`–\`006\`。
- \`provider_profile\` 当前每个本地身份只读取一条记录，\`model\` 直接存放在 provider 行中，\`is_default\` 约束尚未支持多个可选 provider。
- \`backend/app/providers.py\` 只有 \`openai_compatible\` 适配器，模型发现只访问该适配器的 \`/models\`。
- \`backend/app/conversations.py\` 已有 \`config_version\`、运行前配置准备、任务上下文快照和单对话单活动运行约束，但运行后的配置记录仍只有 provider/model 的扁平字段。
- \`frontend/src/AiProviderDialog.tsx\` 目前是单 provider 设置对话框，已有模型发现、手动模型和连接测试交互；\`frontend/src/AiLearningRoom.tsx\` 已有线性对话、SSE、刷新恢复和显式 reasoning 展示。

因此，本设计优先新增规范化模型目录、对话选择记录和运行快照；不重写已有 SSE/取消协议，也不把第二阶段控件提前塞入学习室。

## 3. 方案比较

### 方案 A：在现有 provider 表上继续堆叠字段

将 \`provider_profile.model\` 改成 JSON 或逗号分隔列表，并把对话选择、能力和覆盖配置继续放入同一张表。

- 优点：迁移和初始代码量最小。
- 缺点：一个模型无法独立保存能力、发现时间和启停状态；对话选择会污染全局配置；并发更新容易覆盖；无法清楚区分 provider 默认值、模型值和运行快照。
- 结论：不采用。它会把当前最小纵切片的单行假设固化为长期债务。

### 方案 B：Provider、Model、Conversation Config 分表，Run 保存混合快照（推荐）

Provider 只负责端点、凭据引用和默认连接参数；Model 负责具体模型标识、别名、发现状态和能力元数据；Conversation Config 只保存对话级选择；Run 在启动事务中保存不可变快照，并在进程内保存含凭据的运行对象。

- 优点：边界与用户心智模型一致；同名模型可在不同 provider 下独立存在；模型目录可重建；运行可审计且配置变更不影响进行中的请求；后续思考、搜索和附件可以按能力扩展。
- 缺点：需要 \`007\` 迁移、更多 API 和前端状态；需要处理旧 \`provider_profile.model\` 的兼容影子字段。
- 结论：采用。它是当前 MVP 规模内最小的可持续结构。

### 方案 C：Provider Adapter + 完全不透明 JSON 配置

每个 provider 只保存一个适配器类型和一份 JSON；模型、对话选项和快照全部由适配器解释。

- 优点：新增原生 provider 时表结构变更少。
- 缺点：数据库无法验证模型归属和能力；查询、迁移、权限和 UI 校验都依赖字符串约定；快照无法稳定重放；错误更晚暴露。
- 结论：不采用为主架构。适配器可以拥有受限的 provider-specific metadata，但核心身份、模型和配置字段必须规范化。

## 4. 推荐架构

### 4.1 Provider Registry

后端新增 \`ProviderAdapterRegistry\`，按 \`provider_kind\` 注册适配器。每个适配器必须实现以下接口：

\`\`\`text
validate_connection_config(config) -> NormalizedProviderConfig
discover_models(config) -> list[DiscoveredModel]
test_model(config, model_id) -> ProviderTestResult
stream_chat(config, model_id, messages) -> AsyncIterator[NormalizedDelta]
\`\`\`

适配器还要声明：支持的协议版本、可识别的能力字段、最大 URL/请求限制和错误脱敏器。第一阶段只注册 \`openai_compatible\`；未注册的 provider 类型不能被启用或用于运行。

注册表不保存凭据，不直接读取数据库。领域服务负责加载 provider/model，适配器只接收一次性内存配置。任何适配器返回的模型名称、能力和错误都视为不可信外部输入。

### 4.2 配置对象分层

\`\`\`text
ProviderProfile
  connection: provider_kind, base_url, credential_ref, enabled, timeout
  defaults: default_model_id

ProviderModel
  identity: provider_profile_id, model_id, display_name, enabled
  metadata: capabilities, discovery_status, source
  overrides: 第一阶段仅允许 timeout_override 和 capability_override

ConversationConfig
  selection: provider_profile_id, provider_model_id
  temporary: timeout_override

RunConfigSnapshot
  effective: provider + model + timeout + capability metadata + schema version
  secret binding: credential_ref + credential_version（不含密钥内容）
\`\`\`

第二阶段可以在 \`temporary\` 中增加思考强度、搜索和附件策略，但必须经过能力校验和独立设计；第一阶段不接受这些字段。

## 5. 数据模型

### 5.1 \`provider_profile\`

以现有表为基础，第一阶段增加以下语义：

| 字段 | 规则 |
| --- | --- |
| \`id\` | 稳定 UUID；provider 配置实例的唯一标识 |
| \`identity_id\` | 所属本地身份；所有查询必须带身份条件 |
| \`display_name\` | 用户可读名称，1–80 个字符；不作为唯一键 |
| \`provider_kind\` | 第一阶段只能是 \`openai_compatible\`；未知值以不可用状态读取 |
| \`base_url\` | 规范化 URL；拒绝 userinfo、query、fragment；远程地址要求 HTTPS，回环地址允许 HTTP |
| \`credential_key\` | CredentialStore 引用；不包含密钥正文 |
| \`enabled\` | 禁用 provider 不得启动新 run；历史 run 仍可查看 |
| \`is_default\` | 每个身份最多一个默认 provider；删除默认项时不自动静默替换 |
| \`request_timeout_seconds\` | 5–600 秒；作为 provider 默认连接超时 |
| \`credential_version\` | 每次密钥新增、替换或删除递增；用于运行快照绑定 |
| \`config_version\` | 影响出站请求的任一字段变化时递增，包括 URL、密钥、默认模型和超时 |
| \`deleted_at\` | 软删除；历史对话和 run 保留追溯信息 |

现有 \`model\` 列在 \`007\` 中保留为兼容影子字段：迁移时用于回填首个 \`provider_model\`，新代码以 \`default_model_id\` 和模型表为准，并在写入时同步影子值。后续迁移可以在确认没有旧客户端后删除它，本设计不在第一阶段删除。

### 5.2 \`provider_model\`

每个 provider 的模型独立建行，同一字符串在两个 provider 下是两个不同模型。

| 字段 | 规则 |
| --- | --- |
| \`id\` | 稳定 UUID |
| \`provider_profile_id\` | 所属 provider；删除 provider 时级联软删除或标记不可用 |
| \`model_id\` | 发给适配器的原始模型标识，1–200 个字符；同一 provider 内唯一 |
| \`display_name\` | 可选别名，默认等于 \`model_id\` |
| \`source\` | \`discovered\` 或 \`manual\`；手动模型不能被发现刷新删除 |
| \`enabled\` | 模型级启停；禁用模型不能用于新 run |
| \`discovery_status\` | \`fresh\`、\`stale\`、\`unavailable\`；不代表模型一定支持某能力 |
| \`last_discovered_at\` | 最近一次成功发现时间；手动模型可为空 |
| \`capabilities_json\` | 规范化能力对象，未知值使用 \`null\`，不得用 \`false\` 代替未知 |
| \`capability_source\` | \`provider\`、\`manual_override\` 或 \`inferred_registry\` |
| \`overrides_json\` | 第一阶段只允许 \`request_timeout_seconds\` 和能力覆盖；拒绝其他键 |
| \`created_at\` / \`updated_at\` | UTC 时间 |

能力对象固定为以下键，便于第二阶段读取：

\`\`\`json
{
  "input_modalities": ["text"],
  "output_modalities": ["text"],
  "supports_streaming": true,
  "supports_reasoning": null,
  "supports_web_search": null,
  "supports_image_input": null,
  "supports_file_input": null,
  "max_context_tokens": null,
  "max_output_tokens": null
}
\`\`\`

第一阶段只用 \`input_modalities\`、\`output_modalities\` 和 \`supports_streaming\` 做运行前校验；其余字段先保存并展示为“未声明”，不启用任何搜索、思考或附件控件。

### 5.3 \`conversation_config\`

一条对话最多一条当前配置记录，以对话为作用域，不修改 provider 全局默认值。

| 字段 | 规则 |
| --- | --- |
| \`conversation_id\` | 主键，同时外键到 \`conversation\` |
| \`provider_profile_id\` | 当前选中的 provider；必须与模型归属一致 |
| \`provider_model_id\` | 当前选中的模型；必须启用且属于选中 provider |
| \`timeout_override_seconds\` | 可为空；为空时使用 provider/model 有效值；范围 5–600 |
| \`config_version\` | 对话选择或临时覆盖变化时递增 |
| \`updated_at\` | UTC 时间 |

“临时”表示配置只影响这一对话的后续运行，不会改写 provider 默认值；用户切换后刷新页面仍保留该对话选择。若仅为一次测试而不希望保存，使用 provider 测试 API，不创建 conversation config。

### 5.4 \`ai_run\` 与运行快照

现有 \`ai_run\` 的 \`provider_profile_id\`、\`provider_kind\`、\`model\`、\`config_version\` 字段继续保留用于列表和旧客户端；\`007\` 增加：

- \`snapshot_schema_version INTEGER NOT NULL DEFAULT 1\`。
- \`config_snapshot_json TEXT NOT NULL DEFAULT '{}'\`。
- \`credential_version INTEGER\`。
- \`provider_model_id TEXT\`，外键使用 \`ON DELETE SET NULL\`，避免删除模型破坏历史记录。

\`config_snapshot_json\` 在创建 run 的同一事务中写入，包含：

\`\`\`json
{
  "schema_version": 1,
  "provider": {
    "id": "...",
    "kind": "openai_compatible",
    "base_url": "https://example.invalid/v1",
    "config_version": 3
  },
  "model": {
    "id": "...",
    "model_id": "example-model",
    "display_name": "Example Model",
    "capabilities": {"supports_streaming": true}
  },
  "effective": {"timeout_seconds": 60},
  "credential": {"ref": "provider:...", "version": 4}
}
\`\`\`

快照不得包含 API key、Cookie、Authorization Header、请求正文或用户消息全文。上下文内容继续由现有 \`context_snapshot\` 单独保存，运行快照只记录其 ID。实际密钥在 run 启动时加载到内存对象，并在 run 结束、取消或失败后释放引用；配置修改不会影响已启动 run。

## 6. 多 provider API

### 6.1 Provider 管理

\`\`\`text
GET    /api/ai/providers
POST   /api/ai/providers
GET    /api/ai/providers/{provider_id}
PATCH  /api/ai/providers/{provider_id}
DELETE /api/ai/providers/{provider_id}
POST   /api/ai/providers/{provider_id}/test
\`\`\`

创建和更新字段：\`display_name\`、\`provider_kind\`、\`base_url\`、\`api_key\`、\`enabled\`、\`is_default\`、\`request_timeout_seconds\`。API key 为空表示更新时保留现有密钥；首次创建必须提供。响应只返回 \`has_api_key\`、掩码、状态和非敏感配置。

兼容保留：

- \`GET /api/ai/provider\` 返回当前默认 provider 的单对象，供旧前端使用。
- \`PUT /api/ai/provider\` 写入或更新默认 provider，并映射到新的 provider 服务。
- \`DELETE /api/ai/provider\` 只删除默认 provider。

新前端只使用复数接口。删除默认 provider 时返回明确的 \`default_provider_required\` 错误，用户必须先指定另一 provider 为默认或明确确认无默认 provider；系统不静默选取其他配置。

### 6.2 Model 管理与发现

\`\`\`text
GET    /api/ai/providers/{provider_id}/models
POST   /api/ai/providers/{provider_id}/models/discover
POST   /api/ai/providers/{provider_id}/models/manual
PATCH  /api/ai/providers/{provider_id}/models/{model_id}
DELETE /api/ai/providers/{provider_id}/models/{model_id}
\`\`\`

- \`discover\` 使用已保存 provider 配置，也接受一次性 \`api_key\`、\`base_url\` 和 \`force_refresh\`；一次性密钥只在请求内存中存在。
- 发现请求只交给对应适配器。\`openai_compatible\` 访问规范化 Base URL 的 \`/models\`，解析现有兼容格式，去重并限制最多 500 个模型。
- 成功发现会 upsert \`source=discovered\` 模型，刷新时间更新为当前 UTC；本次未返回的旧模型标记为 \`stale\`，不直接删除。
- 手动模型通过 \`manual\` 接口加入，\`source=manual\`；刷新发现不得删除或覆盖其模型 ID。
- 进程内缓存 TTL 为 10 分钟，缓存键为本地身份、provider ID、规范化 Base URL 和 \`credential_version\`；缓存只保存模型名称和时间，不保存密钥或响应原文。
- provider URL、密钥或凭据版本变化后缓存立即失效；显式 \`force_refresh\` 绕过缓存。
- 模型列表响应包含 \`id\`、\`model_id\`、\`display_name\`、\`source\`、\`enabled\`、\`discovery_status\`、能力元数据和最近发现时间。

### 6.3 学习室与对话配置 API

\`\`\`text
POST   /api/ai/conversations
GET    /api/ai/conversations
GET    /api/ai/conversations/{conversation_id}
GET    /api/ai/conversations/{conversation_id}/config
PUT    /api/ai/conversations/{conversation_id}/config
POST   /api/ai/conversations/{conversation_id}/messages
\`\`\`

\`POST /conversations\` 可带 \`provider_profile_id\` 和 \`provider_model_id\`；省略时使用身份默认 provider 的默认模型。\`PUT /config\` 只允许切换已启用且归属一致的 provider/model，并可设置超时覆盖。\`POST /messages\` 可带一次性的 \`provider_model_id\` 选择，作为本次 run 的选择而不改变对话配置；学习室常规切换使用 \`PUT /config\`，避免每条消息隐式改变对话状态。

所有接口都以当前本地身份过滤对象；跨身份、已删除、禁用或不兼容的 provider/model 统一返回可识别错误码，不能通过客户端传入名称绕过校验。

## 7. 模型能力元数据

能力来源按可信度排序：provider 返回的明确元数据 > 用户对该模型的显式覆盖 > 内置静态注册表推断 > \`null\` 未知。第一阶段默认不接受用户随意编辑能力，只允许后端为已知 provider 响应建立覆盖；前端展示“提供方声明/系统识别/未声明”来源。

运行前能力检查只做硬约束：

- 模型必须声明或适配器保证支持文本输入和当前流式协议。
- \`supports_streaming=false\` 或明确不支持时，禁止进入当前 SSE 对话并提示更换模型。
- \`null\` 不等于不支持；第一阶段因为没有附件、搜索和思考控件，不需要为未知值做降级。

能力元数据是可变派生信息，模型目录刷新可以更新它；run 快照复制当时的有效元数据，保证历史审计不随刷新改变。

## 8. 配置默认值与优先级

有效配置按以下顺序计算，后者覆盖前者：

1. 系统安全约束和适配器协议限制：URL 校验、允许的 provider kind、超时和大小上限，任何用户配置都不能绕过。
2. Provider 默认配置：Base URL、凭据引用、启用状态、默认超时和默认模型。
3. Model 配置：模型启停、显示名称、能力元数据和第一阶段允许的超时覆盖。
4. Conversation Config：对话选择的 provider/model 和对话级超时覆盖。
5. 本次请求的一次性选择：仅允许选择已登记模型和超时；不写回对话配置。
6. Run Snapshot：创建事务中固化的最终值；run 启动后不再读取可变配置。

当前阶段没有 temperature、top-p、max tokens、reasoning、search、attachments、custom headers/body 等可覆盖参数。任何未知字段都返回校验错误，而不是静默放入 JSON。

## 9. 凭据加密边界

- API key 继续由 \`CredentialStore\` 使用本地加密文件保存；SQLite 只保存 \`credential_key\`、\`credential_version\` 和掩码状态。
- 多 provider 使用不同的 \`credential_key\`；provider 软删除时先删除凭据，补偿失败则报告未完成，不能留下“数据库已删、凭据未删”的假成功。
- 模型发现、连接测试和 run 只在后端进程内存中读取明文密钥；不得写入 SQLite、日志、缓存、SSE、异常、进度文档、备份或前端持久化。
- \`config_snapshot_json\` 只保存凭据引用和版本，不保存密钥、Authorization Header 或完整出站请求。
- API 响应中的 provider 配置永远只返回 \`has_api_key\` 和掩码；前端表单关闭、保存或切换 provider 时清空新输入密钥。
- 未来自定义 Headers/Body 若要加入，必须使用新规格和独立加密字段；不得复用第一阶段快照 JSON 保存敏感值。

## 10. 错误处理与兼容性

错误响应统一包含稳定 \`code\`、中文 \`message\` 和可选 \`field\`，不包含密钥、完整 URL 查询参数或 provider 原始认证文本。第一阶段至少定义：

\`\`\`text
provider_not_found
provider_disabled
provider_kind_unsupported
provider_default_required
model_not_found
model_disabled
model_provider_mismatch
model_streaming_unsupported
provider_discovery_failed
provider_test_failed
provider_protocol_error
config_conflict
run_snapshot_invalid
\`\`\`

- provider 或 model 不可用时阻止新 run，并保留对话历史；不自动静默回退到全局模型。
- 如果未来引入显式回退，必须在单独规格中定义并在 UI 显示实际使用的 provider/model。
- provider 发现失败不清空已有模型；用户可以继续使用已登记模型或手动添加模型。
- 刷新发现未返回某模型只标记 \`stale\`，历史对话仍可读；选择 stale 模型启动新 run 时要求重新发现或用户明确确认。
- 旧单数 provider API 映射到默认 provider；旧客户端发送的 \`model\` 字符串在服务端转换为默认 provider 下的 \`provider_model\`，找不到时返回 \`model_not_found\`，不创建隐式模型。
- 旧 \`ai_run\` 没有快照时读取其已有扁平字段，标记为 \`snapshot_schema_version=0\`；新 run 一律写版本 1 快照。

## 11. 迁移策略

不得修改已应用的 \`001_initial\`、\`002_learning_plans\`、\`003_dashboard_layouts\`、\`004_plan_editor\`、\`005_ai_conversations\` 或 \`006_ai_message_reasoning\`。本设计的结构变更从 \`007_ai_multi_provider_model_selection.sql\` 开始，具体顺序如下：

1. 在同一迁移事务中创建 \`provider_model\` 和 \`conversation_config\`。
2. 为 \`provider_profile\` 增加 \`default_model_id\`、\`credential_version\` 等非破坏性列；保留原 \`model\` 影子列。
3. 为 \`ai_run\` 增加 \`provider_model_id\`、\`snapshot_schema_version\`、\`config_snapshot_json\` 和 \`credential_version\`。
4. 为每个已有 provider 依据非空 \`provider_profile.model\` 回填一个 \`source=manual\` 的 \`provider_model\`，并设置 \`default_model_id\`；回填失败时整个迁移回滚。
5. 为新表建立身份、provider/model 归属、默认值和活动状态索引；不删除历史数据，不重写消息内容。
6. 迁移完成后新服务优先读取模型表；写入 provider 时同时更新旧 \`model\` 影子列，直至后续版本确认没有旧客户端。

默认数据库当前只有 \`001\`–\`004\`，正式上线必须先创建一致性备份，再由迁移器顺序应用 \`005\`、\`006\`、\`007\`。本轮不创建 \`007\` 文件、不应用任何迁移，也不修改默认数据库。隔离测试库继续使用独立 \`/tmp/nautilus-playwright.*\` 路径。

## 12. 测试策略

### 12.1 后端单元与集成

- Provider Registry：已注册/未注册 kind、配置校验、适配器隔离和错误脱敏。
- Provider CRUD：多 provider、默认 provider 唯一性、启停、软删除、身份隔离和凭据补偿。
- Model：同 provider 唯一、跨 provider 同名、手动模型保护、发现 upsert、stale 标记、缓存命中/失效和 500 条上限。
- Capability：明确值、未知值、来源优先级、流式硬约束和快照复制。
- Conversation Config：合法切换、provider/model 不匹配、禁用项、超时范围和一次性选择不回写。
- Run Snapshot：启动事务内完整写入；provider、模型、默认值或密钥版本变化后已有 run 仍使用旧快照；快照中无密钥和用户消息全文。
- 迁移：\`001\`–\`006\` 文件哈希不变；从 \`004\` 顺序应用到 \`007\`；重复打开幂等；故障脚本整体回滚且不留半成品表或索引。
- 兼容接口：单数 provider API、旧 model 字段映射、旧 run 无快照读取和明确错误码。

### 12.2 前端与 Playwright

使用本地 Mock provider，不调用真实 AI API；每个测试使用独立 \`/tmp/nautilus-playwright.*\` 数据目录，不接触默认 \`data/\`。

- 桌面 \`1440x1000\`：provider 列表、模型列表、默认标记、学习室双选择器和当前 run 快照信息可见；切换后不丢失输入草稿。
- 平板 \`1024x900\`：右侧伙伴栏可隐藏，provider/model 选择仍在学习室标题区可操作，弹层不超出视口。
- 移动 \`390x844\`：选择器进入底部 sheet 或全宽弹层，触控目标至少 44px，无页面级横向溢出，输入区和取消按钮保持可见。
- 发现加载、缓存命中、刷新、失败和手动模型输入均可操作；失败不清空已有值。
- 禁用 provider/model 时控件显示原因并禁止发送；未知能力不渲染附件、搜索或思考控件。
- 页面刷新、SSE 断线和 provider 配置变更不会创建重复 run；历史消息显示实际 provider/model 名称。
- 生产 preview 必须检查不包含 \`/@vite/client\`，并对上述视口执行截图、控制台错误和网络失败核对。

### 12.3 完成门槛

实施阶段必须同时通过：

\`\`\`bash
timeout 150s env PYTHONPATH=backend .venv/bin/python -m pytest -q
npm --prefix frontend run build
npx playwright test --reporter=line
bash -n scripts/start-e2e.sh scripts/start.sh scripts/wsl-ip.sh scripts/test-start-e2e-safety.sh
bash scripts/test-start-e2e-safety.sh
.venv/bin/pip check
git diff --check
\`\`\`

测试报告只能记录数量、错误类别和临时路径，不得记录真实密钥、Cookie 或用户学习内容。

## 13. UI 验收标准

### 桌面端（宽度大于 1180px）

- 管理工作区保持左导航、中间内容、右侧 AI 伙伴三栏；学习室进入后中栏铺满可用主区，不显示未实现的分支/知识源控件。
- provider 选择器和 model 选择器位于学习室标题区或其紧邻工具区，显示当前名称、启停状态和能力状态；选择器打开不改变页面滚动位置。
- provider 设置可新增、编辑、测试、设为默认和删除多个 provider；默认标记唯一且清晰。
- 模型下拉显示来源（已发现/手动）、状态（可用/过期/不可用）和能力摘要；长名称截断但可通过无障碍名称读取完整值。
- 配置切换不停止活动计时，不清空未发送输入，不产生页面级横向/纵向溢出。

### 平板端（761–1180px）

- 右侧 AI 伙伴可以收起，学习室选择器仍可在当前视口内完成切换。
- provider/model 弹层不被三栏滚动容器裁剪，操作完成后返回原滚动位置。
- 选择器和状态信息不依赖横向拖动；模型能力未知时仍保持紧凑而不展示未来阶段控件。

### 移动端（不大于 760px，重点 390x844）

- 学习室为单列；provider/model 选择使用底部 sheet 或全宽弹层，关闭后保留选择和输入草稿。
- 触控目标至少 44px，按钮不出现中文竖排；加载、失败、禁用和当前选择都有短文本与 \`aria-live=polite\` 状态。
- 页面 \`scrollWidth\` 不超过 \`clientWidth\`；消息列表是主要滚动区，输入区、发送/取消按钮和当前模型摘要在可用视口内保持可见。
- 旋转、地址栏收缩和安全区变化只重新计算布局，不重置 provider/model 或活动 run。

## 14. 实施顺序与禁止事项

实施必须按以下顺序推进：

1. 先建立 \`007\` 隔离迁移和 Provider/Model/Conversation/Run 领域接口。
2. 接入多 provider CRUD、模型目录、发现缓存和兼容单数 API。
3. 接入学习室 provider/model 选择器、禁用状态和能力摘要。
4. 接入运行快照、凭据版本绑定和配置变更回归测试。
5. 完成后端、构建、隔离 Playwright、脚本安全和三档视口截图验收。
6. 由用户审阅隔离结果后，另行决定默认数据库迁移和真实 provider 手动烟测。

在用户确认本设计前，禁止创建 \`007\` 迁移、修改后端/前端业务代码、实现附件、搜索、思考强度、自定义 Headers/Body、提交、推送或部署。

本设计完成不代表第一阶段、AI 阶段或对话阶段完成；它只定义第一阶段基础架构的可实施边界。

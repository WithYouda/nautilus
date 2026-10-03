# 本地 Obsidian Vault 只读检索与显式快照选用（B2-1）

**状态：** 冻结规格（2026-10-02 Planner 冻结，DSH 实施）。本文件是 B2-1 唯一详细契约；PRD、产品决定和开发状态只记录结论与实施状态，不复制本文件内容。

**范围：** 一个本地 Obsidian Vault 的连接设置、只读检索、显式保存快照并选用、来源回看、断开，以及接入现有资料清除与恢复链。不是通用知识库平台，不是完整 B2。

## 0. 产品输入（作者已确认）

1. 首家来源是 Obsidian，读取运行 Nautilus 后端的主机可访问的本地 Vault。
2. 允许访问整个指定 Vault，但只实现本文件列出的读取范围。
3. 不连接云端备份，不比较本地与云端是否同步。
4. 路径由用户在设置中输入；不写死，不自动搜索用户磁盘。
5. 不需要 API Key，不安装 Obsidian 插件。

## 1. 读取边界

- 读取普通 `.md` 文件，扩展名判断不区分大小写，包含子目录。
- 支持 UTF-8 与 UTF-8 BOM。
- 跳过 `.obsidian`、`.git`、`.trash` 目录，以及符号链接和非普通文件；不读取 PDF、图片、Canvas、数据库或插件配置。
- Markdown、YAML frontmatter、wikilink、嵌入标记和代码块按文本保存；不执行脚本、不求值 Dataview、不展开嵌入、不请求网络。
- 全部读取只读；不创建、修改、重命名或删除 Vault 内文件。
- 整库授权不允许路径逃逸、跟随链接读取 Vault 外文件或改读父目录。
- 不引入正文长度、资料数量或文件大小产品限制；不静默截断正文，不把大文档读取失败伪装为成功。
- 先实现当前 Web/WSL2 路径，不扩展原生客户端文件访问体系。

## 2. 连接配置

- 使用现有 `CredentialStore` 的独立 owner-scoped 键 `obsidian-local:{owner_id}`，不扩展 `PreferencesService` 结构。
- 保存字段：`connection_id`（随机 UUID）、`revision`（持久化整数）、`root_path`（后端主机规范绝对路径）、`vault_name`（根目录名）、`enabled`。
- 首次保存 `revision=1`；后续变更要求 `expected_revision` 匹配，成功后递增；旧页面提交返回 409，不静默覆盖。
- 断开保留配置并令 `enabled=false`，重启后仍为断开；重新连接同一路径保留 `connection_id`，换根目录生成新 ID，旧快照仍属旧连接、不自动重绑。
- 路径验证失败不覆盖此前有效配置。
- 根路径只用于设置与服务端读取：不进入模型提示词、回答运行快照、检索日志或普通来源 URL。
- 配置中不保存笔记索引、正文、摘要、文件列表或搜索历史。

## 3. 检索与显式选择

- 检索必须由当前对话中的用户操作触发；打开设置、恢复历史回答或发送普通消息都不扫描 Vault。
- 资料面板提供“从 Obsidian 选用”入口，明确显示当前 Vault。
- 首片按相对路径或正文文字匹配（casefold），空查询列出笔记；不引入分词、语义排序或检索模型。
- 结果按相对路径稳定排序，每页最多 50 项，提供下一页；分页限制不是 Vault 文件数量上限。游标按**本页已处理的最后一个候选路径**推进，不依赖本页是否成功生成条目：一页文件全部不可读时仍返回严格前进的游标与 `has_more=true`，客户端不得在缺少游标时重放第一页。
- 结果项：相对路径、显示标题、命中摘要与行范围、内容 SHA-256、选择令牌；响应另含 `next_after`、`has_more`、`complete`、`unreadable_count`。
- 摘要只帮助选文档，选用时保存整份 Markdown；不把摘要宣称为模型实际引用过的句段。
- 不建立持久化全文索引，不落盘检索正文或摘要，不自动入库。
- 用户动作名称固定为“保存快照并选用”，并解释：“将这份笔记快照存入 Nautilus 资料库并用于当前对话；不会导入整个 Vault，也不会修改 Obsidian 原文。”只有当前对话状态**确认写入成功**后才显示“已保存快照并选用”；保存成功而当前态未确认（忙碌、旧修订冲突或其他写入失败）时保留快照并提示“快照已保存，但当前选择未确认，请读取最新状态后重试”，不自动重试、不自动清除、也不覆盖其他页面的新状态。
- 单次动作只处理一份笔记；不做批量导入或全库同步。
- 已知成本：首片不建索引，一次检索会遍历并读取 Vault 内 `.md` 文件以判断正文命中；分页不缓存正文，翻页会重新遍历。

## 4. 新增 API 契约

新增 `/api/obsidian` 命名空间，全部使用现有身份认证，全部返回 `Cache-Control: no-store`，请求体拒绝未定义字段，scope 接口在任何文件读取前校验 owner 与 scope。查询词放在 POST 正文。

| 接口 | 请求 | 响应 |
| --- | --- | --- |
| `GET /api/obsidian/connection` | — | `{connection: null \| Connection}`；不扫描文件，不声称当前可读 |
| `PUT /api/obsidian/connection` | `{root_path, expected_revision}` | `{connection}`；首次 `expected_revision=null`；不接受 API Key、远端 URL 或命令 |
| `POST /api/obsidian/connection/disconnect` | `{expected_revision}` | `{connection}`；持久化停用并废弃候选与未提交读取结果，不清除已保存资料 |
| `POST /api/obsidian/{kind}/{scope_id}/search` | `{connection_id, connection_revision, query, after}` | `{items[], next_after, has_more, complete, unreadable_count}`；`kind` 只允许 conversation/discussion；`after` 仅作排序过滤，不是任意文件读取授权 |
| `POST /api/obsidian/{kind}/{scope_id}/capture` | `{selection_token}` | 现有 `MaterialVersion`；客户端不提供正文、原件、provenance 或绝对路径；不改 `CurrentConversationState` |
| `GET /api/obsidian/{kind}/{scope_id}/versions/{version_id}/source-status` | — | `{status, checked_at}`；`status ∈ same_as_snapshot/changed/missing/unavailable/disconnected/not_applicable`；无启用连接时不得读盘 |

不修改既有发送消息 API、`SourceScope` 或学习偏好 API。

## 5. 资料身份、版本与事务

- 来源文档身份：`owner_id + connection_id + Vault 相对路径`；不用内容哈希做身份，不合并同内容的不同笔记。
- 复用已有资料的查找使用服务器写入的 `provenance_json`；不新建表，不把映射塞进 `learning_material_link` 或凭据配置。
- 首次明确选用创建资料组；再次选用同一来源复用资料组。
- 最新版本仍是该来源且原始字节哈希未变 → 复用最新版本；原文变化或最新版本是用户手动编辑稿 → 追加新版本；A→B→A 可以产生第 3 版。
- `provenance_json` 固定字段（全部服务端构造，不含根目录绝对路径）：
  `{kind: "obsidian_local", schema_version: 1, connection_id, vault_name, relative_path, sha256, captured_at, locator: {kind: "whole_document", start_line: 1, end_line}}`
- `content_kind` 沿用 `text`，`url` 为 `null`；正文保存解码后的完整文本，原始字节存 `learning_material_original`（文件名为笔记文件名，媒体类型 `text/markdown`）；SHA-256 基于原始字节。
- 沿用现有标题长度契约（显示标题可缩短到 300 字符）；完整相对路径在来源元数据中，正文和原件不因标题限制被截断。
- 资料版本、原件、入库关系与当前 scope 的 version link 在同一个学习数据库事务中完成；任一步失败全部回滚。
- 入库是本动作明确请求的一部分，不改变其他上传、粘贴、网页资料的既有规则。
- 数据库层 `scope_kind` 仍只使用真实 conversation/discussion；不新增伪造 scope，不建隐藏对话承载资料。
- 实现为专用服务端捕获方法与局部私有写入辅助函数；不向通用 `MaterialCreate` 开放任意 provenance。
- 同一来源的并发捕获使用现有资料锁与事务串行化；相同内容的重复点击或重试不产生重复资料组或版本。

## 6. 文件安全、令牌与并发

- 路径只由已保存连接与服务端相对路径产生；校验绝对路径、`..`、空字节、链接和非普通文件。根路径按已保存的规范绝对路径**逐组件** descriptor-relative 打开，每层拒绝符号链接（祖先目录被替换为链接时整次读取失败，不会重定向到原 Vault 外）；Vault 内每次目录/文件打开同样使用 descriptor-relative + `O_NOFOLLOW`，文件用 `O_NONBLOCK` 打开并先 `fstat` 确认是普通文件，避免被替换成 FIFO 时阻塞；平台缺少这些能力时明确报不可用，不静默退化为跟随链接。
- 根目录缺失、无权限或文件变化不作为空 Vault；不自动创建 Vault，不对源目录 chmod，不尝试提升权限。
- 选择令牌为进程内、不持久化的随机不透明标识，有效期 10 分钟，绑定 owner、kind、scope_id、connection_id、连接 revision、相对路径、预期 SHA-256 与当前读取代次；只保留必要元数据。
- **撤权顺序（冻结）：** 连接配置写入与失效、以及清除失效，都在既有资料锁内与捕获提交互斥（获取顺序恒为 materials.lock → obsidian._lock，不存在反向路径）。因此只有两种合法结果：捕获先取得提交边界并完成提交，断开在它之后完成、快照合法保留；或断开/换连接/清除先完成，旧捕获必须拒绝且不创建版本、原件、入库或 scope link。目录遍历、每个文件打开与正文读取块在每次读取前都复查代次与连接修订；候选的最终检查与发布在同一个短临界区完成；来源变化检查使用同一读取边界，读取期间失效时返回冲突而**不**返回“相同/已变化”。
- 每个 scope 只保留当前一次检索页的候选；新检索替换旧候选，过期候选主动释放；进程重启后旧令牌失效。
- capture 重新读取文件，检查读取前后文件状态与原始字节 SHA-256；不一致返回冲突，不保存另一份内容。
- 长遍历不持续占有资料写锁；读取前、循环中与提交前检查连接与读取代次。**根路径打开（含首层与每一层组件）、目录枚举（`scandir`）与每个目录项的处理，都各自取得一次本地读取许可**；`search`、`capture` 与来源变化检查共用同一许可入口（进入读取阶段时冻结的连接快照与代次），撤权完成后旧操作不会重新领取最新代次，也不会打开根目录或开始枚举。
- 资料清除入口接入窄失效通知：清除开始时在同一资料锁边界内废弃该 owner 的候选并增加读取代次；旧 capture 不能在清除后补写。
- 断开或替换连接同样废弃候选并改变读取代次；断开提交后不启动新的源文件读取，在途迟到结果不作为成功返回或写入资料。
- 捕获前检查现有清除收据：存在未完成的 material 清除时拒绝新捕获并提示先完成重试；不新建持久化删除状态。
- 断开前已提交的快照保留；已使用保存快照开始的教学不因断开被追溯取消；不宣称撤回已发生的外发。

## 7. 当前对话与来源回看

- capture 成功后刷新资料列表，沿用现有 `selectSaved`/`onChange` 流程；替换同资料组的旧版本，保留其他资料与冲突策略；`unspecified` 变为 `reference`，`only` 不自动改成 `reference`。
- **关闭即失效：** 折叠内层“从 Obsidian 选用”入口、关闭外层资料面板、切换 kind/id/identity 或卸载，都同步使尚未发出的“捕获后选用”失效——不再发起当前态写入，也不显示属于该失效操作的成功或失败提示；重新打开同一对话不会让旧操作重新有效。判定在选取入口进入、资料列表刷新之后与发出当前态写入之前三处执行。已经发出的写入可以完成、不回滚；已经提交的快照保留，不因关闭被清除或伪报为保存失败。
- 保留 `CurrentConversationState.expected_revision` 检查；资料已保存但当前态冲突时说明“快照已保存，当前选择未应用”，读取最新状态让用户重新操作，不覆盖较新的页面状态。
- scope/identity 切换、关闭或取消后忽略迟到响应，复用 `TaskMaterials` 的 epoch/request 防串线方式。
- 普通学习室与题目讨论共用资料组件获得该入口；未打开有效对话时不创建伪 scope、不启动捕获。
- 当前资料与回答回看始终标识为“Obsidian 保存快照”，显示 Vault 名、相对路径、Nautilus 版本、保存时间、内容指纹与全文定位。
- 沿用文档级【资料N】标记及其准确性免责声明；不把所选资料当成已验证证据、已掌握知识或精确句级引文。
- 来源信息从 `provenance_json` 读取；旧版本缺字段或无法解析时正常降级，不破坏历史资料显示；不把笔记正文复制进额外运行快照。
- 提供“在 Obsidian 打开”和“复制相对路径”：专门构造 `obsidian://open?vault=...&file=...`（分别编码），只允许 `open`；不放宽通用 `safeSourceUrl` 协议白名单，不执行 shell。
- 外部打开依赖浏览器设备上的 Obsidian 与对应 Vault；提示外部原文可能已变化，无法确认打开成功时不显示成功保证。
- 保存快照参与教学模型上下文；搜索/工具外发仍沿用 A2，整库读取授权不等于公开资料标记或外发白名单。

## 8. 删除、变化与恢复

- 断开只停止外部读取，保留配置与保存快照。
- 外部源文件删除、改名或失去权限，不自动清除 Nautilus 快照。
- 原文更新不修改既有资料版本、回答或当前选择；需要重新检索并明确选用。
- 清除沿用现有资料组 purge 与危险确认：覆盖该组所有版本、原件与既有契约定义的关联内容，并处理受管理备份、重试、运行缓存与恢复屏障。
- 不新增绕过清除服务的直接 `DELETE`。
- 外部 Vault 与其同步/备份目录不是 Nautilus 管理副本目录：不登记为备份，不删除、不清空、不修改。
- UI 明确说明：“清除 Nautilus 保存的这份资料及相关内容；不会删除 Obsidian 原文或其云端备份。”保留既有外部副本保证限制。
- 清除后仍可重新检索外部仍存在的笔记并明确保存：这是新的取得动作，创建新资料组；不复活原 `material_id`、原 `version_id`、旧回答或清除前待提交请求。
- 本轮只提供现有单资料组清除，不新增“清空整个 Vault 的全部副本”。

## 9. 错误码

| 场景 | 状态与代码 |
| --- | --- |
| 未认证 | 401（沿用） |
| 非本人或不可访问的 scope/version | 404（沿用，不泄漏来源存在性） |
| 旧配置修订、断开、失效选择、内容变化、清除竞争 | 409：`obsidian_connection_revision`、`obsidian_disconnected`、`obsidian_selection_invalid`、`obsidian_source_changed`、`obsidian_purge_pending`、`obsidian_search_invalidated` |
| 非法路径、根目录不可读、格式不支持、编码失败、空白笔记 | 422：`obsidian_path_invalid`、`obsidian_path_unreadable`、`obsidian_note_unsupported`、`obsidian_note_encoding`、`obsidian_note_empty` |
| Vault 运行时不可访问、根路径任一组件被替换为链接，或其他 I/O 故障 | 503：`obsidian_vault_unavailable`；不伪造空结果，也不暴露外部正文 |
| 当前平台不支持 descriptor-relative 无跟随打开 | 503：`obsidian_platform_unsupported`；明确不可用，不静默退化为跟随链接 |
| 检索词或翻页游标格式不正确 | 422：`obsidian_query_invalid` |
| 已保存连接无法读取 | 503：`obsidian_connection_unreadable` |

局部文件读取失败可显示其余结果，但 `complete=false` 且界面提示不完整。事务失败不得留下无原件版本、半条入库关系或错误 scope link。原始异常不得把绝对路径、正文或凭据写入日志或进度文档。

## 10. 明确不做

Obsidian Sync/云端 API/插件；自动后台扫描、watcher、定时刷新、写回；Embedding、向量库、持久化索引、自动 RAG；PDF/OCR/图片/Canvas、嵌入展开、wikilink 图谱、Dataview；句级引用验证、块级版本、改名自动追踪；多知识库平台或通用连接器框架；新迁移与新依赖；修改 `SourceScope`、消息生成 API、Core 或教学 Runtime；客户端迁移与整体 UI 改造；批量导入真实 Vault 或真实 trial 操作。

## 11. 实施状态

**代码与隔离检查已完成，10-03审查整改后已在既有trial038启用，作者随后反馈实际试用无问题；不等于完整B2验收：** 实现位置为 `backend/app/obsidian.py`、`backend/app/routers/obsidian.py`、`frontend/src/ObsidianMaterials.tsx`、`frontend/src/ObsidianSettings.tsx`，并在 `backend/app/materials.py` 提供同事务的 `capture_obsidian` 与清除时的候选失效接入。实际测试结果、未完成项与下一评审动作只在[开发状态](../../progress/nautilus-development-status.md)维护，不在本文件重复。

R2 补修（2026-10-02，C1/C2）：关闭内层入口或外层资料面板后，未发出的捕获后选用不再启动（`onCaptured(version, isOperationCurrent)`、面板关闭同步失效、三处检查）；根描述符打开、目录枚举与每个目录项处理接入与正文读取相同的单次许可（`_permit`），`search`/`capture`/`source_status` 共用同一 guard。

R1 补修（2026-10-02，修复已确认缺陷）：当前态应用结果沿 `ObsidianMaterials → TaskMaterials → 父组件 useConversationState.save() → 服务端修订检查` 全链返回真实布尔值；捕获后只有确认写入才显示“已选用”。读取边界补全：根路径逐组件无跟随打开、文件 `O_NONBLOCK` + `fstat` 拒绝特殊文件、每次打开/读取块前复查代次、候选检查与发布同临界区、来源状态与检索共用同一读取边界。分页游标改为按已处理候选推进。

实现期间相对本文件的实现细节（不改变契约）：请求体中的 `query` 可省略（等价于空查询）；一个检索请求会遍历并读取 Vault 内 `.md` 以判断正文命中，`unreadable_count` 统计目录遍历与文件读取中的失败；捕获成功后接口返回 201 与现有 `MaterialVersion` 结构。

# 题目讨论流式交互与记录预览

## 根因和结果

此前只统一了题目讨论和教学学习室的视觉布局，发送接口仍等待 `generate_text` 完整返回；前端同样等请求完成后才更新两条消息。因此本人气泡延迟出现，AI 回复整段出现，与普通聊天不同。

现在发送在事务保存问题后立即确认；前端在网络请求尚未返回时即显示靠右的待确认气泡、清空输入框，确认后用保存的同一消息替换。失败保留待发送消息和幂等键，可重试而不重复创建。生成任务使用已有 Provider 的 stream_chat，正文块逐步保存到现有 assistant_content 字段。

HTTP 增加当前轮次 SSE 和取消入口。SSE 使用持久化快照，每 50 ms 检查变化，等待期间每 10 秒发送无正文保活；不构建可在删除后重放私文的事件缓存。刷新/重连只订阅已有轮次，不重新调用模型。生成任务与订阅连接分离，应用退出时取消并收敛运行状态。取消/上游失败保留已经收到的部分正文，界面可重试同一已保存问题。非敏感 attempt_id 防止旧尝试覆写重试结果。

当前工作区沿用共用消息/输入组件，聊天面板增加跟随行为：发送新消息时到底部；流式更新时仅在用户仍贴近底部时跟随；上滚阅读时保持位置。输入法与 Enter/Shift+Enter 行为沿用共享输入组件。

来源区首次展开列出所有实际命中记录段的短预览。每条独立展开/收起，长预览通过 CSS mask 的透明渐变收尾，仅内容确实超出预览高度时显示渐变。保留实际检索段落原有最多 6 段、每段最多 1600 字符边界，不因点击展开进行额外检索或展示未授权内容。

## 数据与生命周期

- 无新迁移，不修改 001–028；复用原有 running/succeeded/failed/purged 状态，取消使用 failed + cancelled 原因。
- 运行任务由应用级 QuestionDiscussionService 持有，生命周期关闭时等待取消完成，再关闭数据库。不是新增常驻进程或通用后台 Agent。
- 所有新保存块和最终结果校验当前尝试、运行状态和讨论删除状态，引用来源失效时拒绝提交；清除验证/产出时现有触发器同时清除部分正文，SSE 后续快照也清除客户端讨论。重连不重放被清除正文。
- 讨论、来源和验证完成事实仍分开；不改变本地历史范围、评分或正式完成，不写私人正文进普通运行快照、事件或进度文档。
- 生成中刷新恢复指应用进程仍在运行时恢复订阅；进程重启后中断轮次标记未完成，保留部分正文供用户重试，不承诺跨重启自动继续外部调用。

## 本轮文件

- 后端：`backend/app/question_discussion.py`、`backend/app/routers/learning.py`、`backend/app/main.py`。
- 前端：`frontend/src/QuestionDiscussion.tsx`、`LearningRoomLayout.tsx`、`AiLearningRoom.tsx`、`api.ts`、`styles/ai-learning.css`；新增 `DiscussionSources.tsx`。普通聊天与讨论共用 SSE 帧读取器及自动跟随面板，领域状态仍各自管理。
- 测试：新增 `backend/tests/test_discussion_streaming.py`；更新 `test_learning_verifications.py` 的合成传输以提供 SSE，调整 `test_verification_review.py` 的迟到流式响应；扩充 `frontend/e2e/verification-review.spec.ts`、`scripts/mock-openai-provider.py` 的慢分块场景。
- 文档：PRD V2、产品决策、首片实施计划、本记录、开发状态。技能文件与 Codex 配置未修改；用户询问的 skill 停用属于建议，不记为已执行操作。

## 验证

- 流式/回看定向 20 passed；加入 HTTP 边界用例后的后端全量 `env PYTHONPATH=backend .venv/bin/pytest -q backend/tests --tb=short` → **376 passed，1 个既有 Starlette/httpx 弃用提示**。
- `npm --prefix frontend run build -- --outDir /tmp/nautilus-stream-dist` 通过，仍有既有大包提示。frontend 中 `env NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-stream-dist ./node_modules/.bin/playwright test e2e/verification-review.spec.ts e2e/ai-learning.spec.ts` → **14 passed**。
- 后端覆盖立即保存、首块未完成时持久可见、断开订阅后重连、幂等消息、取消与重试、生成中彻底删除及迟到流不能复活、失败/关闭时保留部分内容、HTTP SSE/no-store 与跨身份访问隔离。
- 浏览器主动阻塞发送请求，确认右侧气泡和清空输入不等待网络；观察第一段回复时仍有取消按钮；生成中刷新后仍仅一条用户消息；取消保留第一段、重试仍不重复问题；来源列表全部短预览、每条独立展开，渐变样式与 390/1440 无横向溢出检查通过。
- 已查看 `/tmp/nautilus-stream-sources-390.png`、`/tmp/nautilus-stream-sources-1440.png` 合成数据截图。测试均使用隔离数据库与 Mock，不读取真实学习正文/凭据或调用真实 Provider。运行启用结果见开发状态顶部。

## 限制与下一项

真实 DeepSeek 的流式延迟、首字时间和长回复仍需作者复试；测试不能替代真实学习基线。这里只流式展示回复正文，Provider 额外的推理字段没有新增持久化；已保存的原验证结果不被续问改写。保留既有本地检索、删除/备份和外部副本边界。

唯一下一项：作者刷新试用页，在题目讨论发送一条问题，检查即时右侧气泡、逐步回答、取消/刷新恢复及引用逐条预览。根据实际反馈继续最小修复，不启动额外大型能力。


## 运行启用

同日已核对并停止原试用 supervisor，将已验收构建安装到 frontend/dist（保留旧 assets、原子替换入口），沿用 run.sh 重启。无迁移或真实内容操作。Web `http://172.17.253.105:5188/`，API 8018，均绑定 0.0.0.0；页面、新 JS/CSS HTTP 200，直接与代理健康 status/database=ok，未登录学习记录及 SSE 均 401。最终 PID、构建名和下一项见开发状态顶部。

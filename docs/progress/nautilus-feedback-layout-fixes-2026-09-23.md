# 验证逐题反馈与题目学习室补修

## 问题与处理

本轮再次试用反馈：验证只有整次总结、题目讨论中反馈不完整、讨论布局与学习室不一致、后续布局需要便于修改，以及删除名称不易理解。

代码核查发现评估请求虽然要求 question_feedback，但校验仍兼容仅含四个整体字段的新响应，导致缺失逐题反馈也被标记成功。评估输入此前也没有显式携带公开题目。现在评估提示 schema 为 v4，显式提供每道题的原 ID 和题干；要求针对每题作答先给出具体反馈与建议，再给出整体总结。新响应必须完整覆盖题目、ID 不重复且每题反馈非空；不合格时保留已保存作答、记录失败并允许手动重试，不能确认完成。材料验证对应 material 一项。没有修改成功历史结果、自动重新评分或创建新迁移。

回看按题目、本人原作答、AI 反馈与建议、参考解法及可选拓展排列，最后展示独立标记的整体验证总结。历史缺少逐题反馈时逐题解释缺失原因，原总结仍可查看；讨论中的历史总结也明确标为整体验证总结，不把它冒充本题反馈。

题目入口改为“讨论这道题”。题目讨论共用教学学习室的聊天面板、消息和输入组件，内容区独立滚动、输入区保持可见，Enter 发送/Shift+Enter 换行并保护输入法组合输入。来源折叠区包含原题、原作答和全部逐题反馈；从历史记录打开也使用专注学习布局，刷新恢复仍沿用已有定位。未增加流式讨论、模型工具或权限范围。

删除次级入口改为“更多操作”，按钮仍为“彻底删除本次验证内容”。确认中的关联讨论数量、证据失效、完成事实保留及不可恢复说明继续保留；只修改文案，不改变删除实现和现有备份/外部副本边界。

## 为后续布局修改保留的边界

- `frontend/src/LearningRoomLayout.tsx`：教学与题目讨论共用的 LearningChatPanel、LearningMessage、LearningComposer，只接收展示内容和回调，不发起领域请求。
- `frontend/src/QuestionFeedbackContent.tsx`：回看和题目来源区共用的逐题反馈展示，避免两处字段遗漏或文案漂移。
- `styles/ai-learning.css`：聊天与反馈样式；`styles/v6-workspace.css`：宿主工作区在学习/讨论场景的布局；`styles/fact-workspace.css`：验证、学习记录及更多操作。
- 业务状态、运行恢复、授权与存储继续在原模块；未来更改布局从这些呈现边界入手。本轮没有全站重设计，也没有引入通用页面配置引擎。

## 本轮文件

- 后端：`backend/app/verification.py`。
- 后端测试：`test_learning_verifications.py`、`test_verification_reliability.py`、`test_verification_evidence.py` 的合成评估契约更新；`test_verification_review.py` 新增多题缺失/空白/重复反馈拒绝、保存与重试、题目反馈对应及旧总结保留验证。
- 前端：新增上述两个共用组件；修改 `AiLearningRoom.tsx`、`QuestionDiscussion.tsx`、`VerificationReview.tsx`、`LearningVerification.tsx` 及上述三个样式文件。
- 浏览器测试与合成服务：`frontend/e2e/verification-review.spec.ts`、`scripts/mock-openai-provider.py`；两题场景逐题对应、总结顺序、390/1024/1440 滚动和输入区、讨论发送/来源/刷新、完成后回看及删除、历史只有总结时的展示。
- 文档：本记录、PRD V2、产品决策与开发状态。所有此前未提交修改保留；无暂存、提交或 push，无新迁移。

## 验证范围

后端先定向运行验证相关五个测试文件，66 passed；全量 `env PYTHONPATH=backend .venv/bin/pytest -q backend/tests --tb=short` 为 370 passed、1 个既有 Starlette/httpx 弃用提示。没有把不同轮次数字相加。

构建使用 `npm --prefix frontend run build -- --outDir /tmp/nautilus-feedback-dist`，通过，保留既有大包提示。浏览器在 frontend 中使用 `NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-feedback-dist ./node_modules/.bin/playwright test`，首次四文件联合（verification-review、learning-feedback、ai-learning、learning-continuity）17 passed。最后共用消息状态样式/输入法细节及旧总结展示回归的复验结果、服务启用事实见开发状态顶部。

已检查隔离合成数据截图：`/tmp/nautilus-discussion-390.png`、`/tmp/nautilus-discussion-1440.png`、`/tmp/nautilus-discussion-from-records.png`。未读取真实学习内容、调用真实 DeepSeek 或在试用库运行自动化；这些检查不能证明实际模型反馈质量或完整真实学习基线。所有数据库测试使用临时/隔离环境，未触碰默认 data/ 或 diagnostic-backups/。

## 下一项

作者刷新试用页面，做一次新验证，检查每题反馈与最后总结；从题目进入讨论，核对原题/答案/完整反馈、输入区和刷新恢复。旧记录缺少的逐题反馈不会被补造，可在题目讨论中请求新的讲解。FOLLOWUP-SEARCH-001 保持后续计划，不扩大功能范围。


## 同日最终回归与启用

最后两个受影响浏览器文件 verification-review、ai-learning 共 14 passed；包含旧总结展示和共用输入组件键盘行为。最终构建通过，Git 空白及启动脚本语法通过。

核对原 supervisor 和监听后停止试用服务，将隔离构建 assets 安装至 frontend/dist 并原子替换 index.html，沿用 run.sh 重启。未执行迁移或真实内容操作。实际 WSL2 访问地址 `http://172.17.253.105:5188/`，API 8018，均绑定 0.0.0.0；Web、新 JS/CSS HTTP 200，代理与直接 API 健康 status/database=ok，未登录学习记录 401。最终运行 PID 和构建名见开发状态。下一项为作者复试新验证反馈与讨论布局。

# 题目讨论思考内容补齐（2026-09-24）

## 根因与实现

上一轮题目讨论 `_generate` 跳过所有非 content 片段，导致 Provider 返回的思考既未保存也未传输。普通学习室已有相应能力，因此只接正文并未满足相同聊天体验。

本轮分开累积正文和 reasoning，逐块保存，通过原有持久化 SSE 快照传输。ReasoningBlock 从普通学习室移至共用 LearningRoomLayout，两个页面调用同一组件与样式：生成时展开，结束后折叠，手动可展开，刷新恢复保存内容。保留即时右侧消息、来源逐条渐变预览和现有滚动行为。

新增 029_discussion_reasoning.sql，为讨论轮次增加独立可删除的 reasoning_content，重建清除触发器并覆盖派生讨论。重试清空旧正文与思考；取消/失败保留已收到的部分；引用失效两者一起清除；旧尝试或删除后的迟到片段无法复活内容。备份恢复校验纳入思考残留，同时兼容未具备该列的旧备份。思考不进入引用检索、普通运行快照或不可删除事件，不补造旧记录或模型未返回的思考。

## 文件与验证

- 后端：question_discussion.py、learning_production.py；新增 migrations/029_discussion_reasoning.sql（001–028 未修改）。
- 前端：LearningRoomLayout.tsx、AiLearningRoom.tsx、QuestionDiscussion.tsx、api.ts。
- 测试：test_discussion_streaming.py、test_verification_review.py、test_learning_domain_schema.py、test_learning_facts_api.py、frontend/e2e/verification-review.spec.ts、scripts/mock-openai-provider.py。
- 文档：本记录、开发状态、产品决定、PRD V2。
- 定向 51 passed；最终全量 `env PYTHONPATH=backend .venv/bin/pytest -q backend/tests --tb=short` 为 **377 passed，1 个既有 Starlette/httpx warning**。
- `npm --prefix frontend run build -- --outDir /tmp/nautilus-reasoning-dist` 通过（既有大包提示）。frontend 中 `env NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-reasoning-dist ./node_modules/.bin/playwright test e2e/verification-review.spec.ts e2e/ai-learning.spec.ts` 为 **14 passed**。
- 浏览器实测思考先于正文逐步出现、生成中展开、在尚未出现正文时刷新恢复、正文流中再次刷新、完成和取消后折叠、手动展开及完成后再次刷新恢复；普通学习室同一组件回归通过。原即时气泡、引用预览/独立展开/渐变和删除旅程仍通过。
- 合成 028 库升级至 029 演练通过：升级前后备份、完整性与外键检查通过，原问题、正文和状态保留，新列初始为空，新思考可清除。备份仅残留思考也被恢复保护拒绝；旧 028 结构备份检查兼容。全程使用隔离合成数据与 Mock Provider。

## 技能停用

按用户明确要求，将 `/home/kingdom/.codex/config.toml` 增加指向 `/home/kingdom/.codex/skills/frontend-skill/SKILL.md` 的 skills.config 条目，enabled=false。解析校验通过，技能文件保留，frontend-design 未修改。本轮不再应用 frontend-skill；官方配置说明要求重启 Codex 使后续加载生效。这与 Nautilus 服务重启是两件独立的事。

## 试用库启用方案（准备阶段历史，现已授权执行）

真实试用服务当前仍运行 028，未安装本轮构建、未迁移、未重启。此前单独授权明确不含未来迁移，见产品决定 2026-09-23 独立试用库升级与启用授权；普通启动不得迁移的规则见 2026-09-16 审查建议采纳与验证可靠性优先。

待授权的唯一范围：停止已核验的试用进程，仅检查并备份 `/home/kingdom/ai_learning/tmp/nautilus-trial-20260919/learning.sqlite3`，通过已有升级工具应用 029，校验完整性/外键和升级前后备份；安装 `/tmp/nautilus-reasoning-dist` 的已验收构建，沿用 run.sh 绑定 0.0.0.0 启动 API 8018/Web 5188，核对健康、入口和资源。备份放该 trial 的 backups 目录，权限沿用升级工具的私有本地限制。不读取学习正文或凭据，不调用真实 Provider，不执行恢复或删除，不碰默认 data/ 与 diagnostic-backups/。

准备好的升级命令（仅获上述授权后执行）：

```sh
env PYTHONPATH=backend .venv/bin/python scripts/upgrade-learning-database.py --database /home/kingdom/ai_learning/tmp/nautilus-trial-20260919/learning.sqlite3 --backup-dir /home/kingdom/ai_learning/tmp/nautilus-trial-20260919/backups --authorize-production
```

当前 WSL2 入口 `http://172.17.253.105:5188/`，现有 Web/API HTTP 200。新构建入口脚本为 index-D8Y8sq_J.js，CSS index-BEDFnmSN.css；安装前不要把它记为已启用。真实 Provider 表现需启用后作者复试；旧记录不会出现从未保存的思考。无暂存、提交或 push，原未提交工作保留。

更新历史：2026-09-24 修复、377/14 回归和合成升级演练完成；frontend-skill 已写入停用配置，真实升级待指定范围授权。


## 授权执行结果

用户在下一轮明确回复“授权备份、升级并重启”，本方案已于本地2026-09-24执行。原待授权状态为历史，当前指定trial已升级至029并启用修复。

已核验旧进程命令后停止supervisor，升级工具完成指定学习库的前后备份与028→029迁移。所有业务表记录数量保持，完整性/FK均ok，新reasoning_content列与清除触发器核对通过。未读出学习正文或凭据，未调用真实Provider，未执行恢复或删除；默认data/和diagnostic-backups/不在操作范围。

备份位于trial/backups：`learning-pre-upgrade-20260923T163610016556Z.sqlite3`、`learning-post-upgrade-20260923T163610213396Z.sqlite3`。备份和清单均0600，SHA-256匹配，前后版本为028/029；文件名为UTC。

安装已验收的/tmp/nautilus-reasoning-dist（保留旧assets、原子替换index），沿用run.sh绑定0.0.0.0启动API8018/Web5188；当前脚本/API/Web PID为23768/23771/23810，后续需重新核验。实际WSL2入口http://172.17.253.105:5188/；API直连、代理和实际IP健康均ok，入口、新JS/CSS为200且匹配已验收构建，未登录记录和SSE为401。

本轮没有改应用代码或重复回归，沿用377后端/14浏览器及合成升级验收；新增实际部署和健康验证。更新开发状态、产品决定和本记录，未暂存、提交或push。下一项：作者刷新页面发送新问题，复试思考流、正文流与刷新恢复；旧记录没有保存的思考无法补回。frontend-skill停用配置保持，仍需重启Codex以重新加载。

更新历史：2026-09-24 明确授权已执行，029思考内容修复已启用，进入作者真实复试。

# 2026-09-23 验证回看、题目讨论与学习记录实施记录

> 最新运行状态：同日用户已明确授权并完成独立试用学习库 027 → 028 备份/升级及新版启用。下文“尚未执行”“等待授权”描述的是工程交付时历史状态，由文末运行更新覆盖。

本轮落实用户“接着按照你说的建议继续改进”，承接同日反馈审查与右栏默认折叠决定。HEAD 为 `0973056`，branch `main...origin/main`；保留既有大量未提交变更，没有暂存、提交、push。不是完整 PRD 或学习价值验收。

## 已实现

- 本人鉴权详情返回原题、不可变提交版本、当时作答、对应评估。逐题反馈与 AI 参考解法置于该题作答下方；旧评估只有整体反馈时按原样显示，不事后生成伪历史。隐藏评分字段不直接返回。已提交内容自动保存，无需额外保存按钮；未提交输入仍只在当前页面。
- 新评估区分原要求缺口与可选拓展问题：有必需缺口时强制不通过；缺少题目/错配题目的反馈标为评估失败，原作答保留。反馈后重答同题保守记录为 with_materials，保持请求幂等，不把再次勾选独立当成新独立证据。
- 每题可新建讨论，在学习区继续追问或回答拓展问题；保留原提交/结果/完成事实。讨论绑定 submission/question/evaluation，不复制整段教学历史；模型先决定关键词，服务实际检索本人同委托教学/题目讨论，展示真实来源与未检索/未命中状态。最多一次检索、6 段、每段 1600 字符，使用当前讨论最近 8 轮。不是联网搜索或完整语义搜索。
- “开始学习 → 学习记录”列出进行中和已完成委托，关联新领域目标/安排与全部验证；未挂旧计划的记录也可回看。验证与讨论选择可跨刷新恢复，原学习对话可打开；只读历史入口不冒记学习开始。
- 彻底删除下沉到“更多与隐私管理”；确认显示关联/衍生讨论数量、证据失效、完成事实保留与不可恢复。题目讨论私文放学习库，以便和验证清除同事务执行。没有把私文再复制入主库运行快照。
- 联合旅程暴露的旧缺陷：运行中选“安排新的第一步”原来只打开表单，开始时被旧 session 阻止。现在明确提示先暂停已有学习；记录 choose_other/switched，幂等重试不误停之后的学习，不计为“今天先停”或推荐完成。新安排仍需用户确认。
- 右侧 AI 学习伙伴继续默认折叠、保留展开功能。FOLLOWUP-SEARCH-001 联网服务配置继续列入后续计划，本轮没有开通外部服务。

## 文件

- 需求/规格/计划：PRD V2、产品决策记录、领域架构规格、首片实施计划、开发状态、本记录；同日反馈审查保留为历史并链接实施结果。
- 后端新增：`backend/app/learning_records.py`、`backend/app/question_discussion.py`。修改：`verification.py`、`continuity.py`、`schemas.py`、`routers/learning.py`、`main.py`、`learning_production.py`。
- 迁移新增：`backend/app/migrations/028_verification_discussions.sql`。没有修改 001–027。
- 前端新增：`VerificationReview.tsx`、`QuestionDiscussion.tsx`、`LearningRecords.tsx`。修改：`LearningVerification.tsx`、`AiLearningRoom.tsx`、`FactWorkspace.tsx`、`ReturnReviewCard.tsx`、`api.ts`、`styles/fact-workspace.css`。
- 测试新增：`backend/tests/test_verification_review.py`、`frontend/e2e/verification-review.spec.ts`。修改：schema/API 的迁移列表、`test_continuity_measurements.py`、`learning-feedback.spec.ts`、Mock Provider、`scripts/start-e2e.sh` 的隔离构建参数。

## 数据模型与删除

028 新增 `learning_question_discussion`（验证/提交/题目/评估引用）、`learning_discussion_turn`（可清除用户/AI 正文、运行状态、幂等键与无正文配置快照）、`learning_discussion_dependency`（实际引用来源 ID）。一段讨论最多一个运行轮次；重启将未完成轮次标记中断，可重试已保存问题。

两个 SQLite 触发器把 submission 清除传播到根讨论及依赖它的讨论，再清空轮次正文、来源和配置快照。正文不写入不可变事实/证据事件；保留 ID、状态、时间和依赖关系。普通产出入口清除验证产出也进入同一触发链；迟到回复不复活内容。受控恢复额外检查讨论私文残留，即使备份中原产出已清除也拒绝恢复残留讨论。当前没有单独删除某轮讨论的功能，关联清除会清除整段受影响讨论，确认提示已说明。

027 → 028 合成升级演练验证原答案及旧反馈保留、旧 schema 启动被拒绝、升级后讨论可用和 FK 检查。没有打开/迁移真实试用库、默认 `data/` 或受禁目录，没有读取真实学习原文或凭据。

## 验证记录

所有 pytest 使用临时库；浏览器使用 `/tmp/nautilus-playwright.*` 和 Mock Provider，不写入真实产品指标。

- `env PYTHONPATH=backend timeout 180 .venv/bin/pytest -q backend/tests --tb=short`：最终 **365 passed, 1 warning**；warning 是既有 Starlette/httpx 弃用提示。
- 最后一处评估提示文字调整后，`env PYTHONPATH=backend timeout 60 .venv/bin/pytest -q backend/tests/test_verification_review.py backend/tests/test_learning_verifications.py backend/tests/test_verification_reliability.py backend/tests/test_continuity_measurements.py --tb=short`：**42 passed**。不与全量数字相加。
- `npm --prefix frontend run build -- --outDir /tmp/nautilus-review-dist`：通过；既有超过 500 kB 包体提示仍存在。输出隔离，未用该构建作为新版本试用启用。
- frontend 中 `env NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-review-dist ./node_modules/.bin/playwright test e2e/verification-review.spec.ts e2e/learning-feedback.spec.ts e2e/learning-continuity.spec.ts e2e/ai-learning.spec.ts e2e/nautilus-first-slice-facts.spec.ts`：**22 passed**。覆盖新回看/讨论/来源/删除，原完成和中断恢复，AI 教学、事实/证据回放；390×844、1024×640、1440×1000，无横向溢出和滚轮/触摸滚动。
- `git diff --check`、`bash -n scripts/start-e2e.sh`：通过。
- 未运行：全部其他前端套件、真实 DeepSeek、新版本真实试用升级、真实手机软键盘、真实学习效果评估。自动化样本不构成 Task 13B 真实基线。

中间失败如实记录：首轮后端三个迁移期望列表遗漏 028；新增测试先后发现嵌套事务、非法逐题结果仍残留 passed，以及测试合成身份/产出版本准备问题，均修复。TypeScript 曾把随机请求键推断为 UUID 模板字面量类型，已显式改为 string。浏览器联合运行先暴露新方向未暂停旧会话的实际缺陷，随后修正共享合成账号下新用户/历史任务/验证数量断言。单独新旅程先通过；22 项联合运行一度 21 passed / 1 failed（旧计划入口预期仍假定空账号），修正测试准备/范围后复验。

构建操作偏差：一次误用 `npm run test:e2e`，该脚本隐含默认 `npm run build`，短暂覆盖了试用预览的 dist。发现后停止，立即在 `/tmp/nautilus-pre-review-ui` 重建兼容现有 027 服务的前端并恢复预览入口，保留原已交付的公式、滚动和折叠能力；不是逐字节原构建回滚。新回看/讨论入口未留在旧服务上。后续直接调用 Playwright 且只预览 `/tmp/nautilus-review-dist`。没有数据库迁移、服务重启或真实正文读取；Web HTTP 200。不能把这次操作写为“运行构建完全未触碰”。

## 试用启用准备（尚未执行）

已有试用 Web 为 `http://172.17.253.105:5188/`，绑定 0.0.0.0；现有后端不自动重载。新代码要求 028，不能直接按旧脚本重启，否则 schema guard 会拒绝。得到针对真实试用库的明确授权后：停止原试用服务；确认版本确为 027；使用既有升级工具生成本地升级前/后备份，应用 028 并检查完整性/FK；安装已验证的新前端构建；沿用原试用配置重新启动并检查 Web/健康接口。升级输出仅记录版本/检查结果，不输出学习内容或凭据；若版本不符先停止，不能顺带执行其他迁移。

准备好的升级命令（仅在用户明确授权且停止服务后执行）：

```bash
PYTHONPATH=backend .venv/bin/python scripts/upgrade-learning-database.py \
  --database /home/kingdom/ai_learning/tmp/nautilus-trial-20260919/learning.sqlite3 \
  --backup-dir /home/kingdom/ai_learning/tmp/nautilus-trial-20260919/backups/learning \
  --authorize-production
```

备份属于真实副本，应受相同目录权限保护；之后的 purge 不物理改写历史备份，应用受控恢复会拒绝复活已清除内容。不要在真实环境测试删除或自动恢复；Provider、手工导出和文件系统取证不在保证内。

## 限制与唯一下一项

本地关键词检索会漏掉同义表达或较早段落；整段回复无流式显示，没有后台任务或通用工具生命周期。AI 参考解法仍是模型判断；学习状态不是通用掌握证明。已经有作者试用反馈，但完整真实结构化基线未形成；网络信任、全副本删除承诺、第一轮更广试点对象、行动执行完成是否脱离正式验证和长期冻结范围仍未最终确认。不进入成果图、路径图、后台教练、人格、插件平台。

**唯一下一项：获得试用学习库 027 → 028 升级、备份及重启的明确授权，然后启用本轮已验收版本供作者复试。** 新旅程的 Task 13B 真实验收目前 NOT READY（待启用及真实 Provider 复试）；采集能力仍保留，不能用本轮自动化结果填充真实基线。

## 同日授权启用（已执行）

用户已明确授权上文具体方案。本轮没有业务代码或新迁移变更；实际试用学习库从 027 升级至 028，未执行其他迁移或历史回填。升级前后原有各表记录数量保持，完整性/FK 均 ok；没有查询或输出学习正文/凭据，也未进行真实删除、恢复或自动化试用。

升级前后备份为 `learning-pre-upgrade-20260923T150453961390Z.sqlite3` 与 `learning-post-upgrade-20260923T150454397876Z.sqlite3`，位于试用目录 `backups/learning/`；目录 0700、备份/清单 0600。使用既有 upgrade_learning_database 的授权入口，并在外层持有 service.lock、限定仅 028、比较原有表数量；没有扩展读取默认库。

当时原试用服务已停止且 /tmp 构建不存在，重新运行隔离输出构建成功，安装到 frontend/dist 后沿用 run.sh 启动。Web `http://172.17.253.105:5188/`、当前构建 `index-BRYOYg_g.js` 均 HTTP 200；代理健康接口 status/database=ok；无身份访问学习记录 401。API/Web 均绑定 0.0.0.0。没有读取运行日志中的真实内容、调用 Provider 或重跑自动化套件，前面的 365/42/22 是上一实施轮结果。

本次同步五份基线、当前记录及新窗口交接提示词；未提交/push。Task 13B 作者本人继续试用为 READY（运行条件），完整真实基线仍未知。唯一下一项改为作者复试历史作答回看、单题续问/本地来源、刷新恢复和新 DeepSeek 逐题反馈；不自动开始后续扩张。

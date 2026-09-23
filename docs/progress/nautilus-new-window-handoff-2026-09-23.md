# Nautilus 新窗口接手提示词（2026-09-23，028 已启用）

以下内容可作为新窗口的任务输入。

---

你接管 Nautilus（学海无涯），仓库 `/home/kingdom/ai_learning`，远程 `https://github.com/WithYouda/nautilus`。现在的主任务是协助作者继续真实学习试用，并根据反馈修复最小连续旅程。不要扩张功能体系，不要重新实施已经完成的工作。

## 先读基线，再核对事实

完整读取 AGENTS.md 并遵守。读取：

- `docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md`
- `docs/superpowers/specs/2026-07-23-nautilus-design.md`
- `docs/progress/nautilus-prd-v2-review-2026-09-05.md`
- `docs/progress/nautilus-product-design-decisions.md`
- `docs/superpowers/specs/2026-09-05-nautilus-first-slice-domain-architecture.md`
- `docs/superpowers/plans/2026-09-05-nautilus-first-slice-implementation.md`
- `docs/progress/nautilus-development-status.md`，以顶部 CURRENT SNAPSHOT 为当前状态，旧日期和同日历史不覆盖它。
- `docs/progress/nautilus-verification-review-implementation-2026-09-23.md`，特别看文末“同日授权启用”。

涉及证据、删除或回放修复时，另完整核对 2026-09-16 的 PRD/计划/实现审查、verification-reliability、verification-evidence 三份实施/审查记录，以及 `nautilus-learning-continuity-implementation-2026-09-19.md`。随后读对应当前代码，文档不能替代核验。

只读核对 `git status --short --branch`、`git log -1 --oneline`、`git diff --check`，以及服务监听、Web/健康接口。HEAD 最后为 `0973056`，main，存在大量未提交实现和文档；这是需要保留的工作，禁止覆盖、reset、清理或广泛暂存。不得提交/push。

## 已完成与已启用

用户已经明确授权 027 → 028 的独立试用学习库备份、升级和服务重启，且这次授权已经执行完毕。不要再次请求同一授权或重复执行迁移。

- Web：`http://172.17.253.105:5188/`；API 8018，均绑定 0.0.0.0。IP 可能变化，使用 `hostname -I` 核对实际 WSL2 地址。
- 启动脚本：`/home/kingdom/ai_learning/tmp/nautilus-trial-20260919/run.sh`；正常启动只检查 schema，不自动迁移。健康时不要无故重启；需要恢复服务时先核对进程，不盲用历史 PID。
- 试用目录 `tmp/nautilus-trial-20260919/` 已含真实用户学习内容及凭据，绝不是测试目录。
- 实际学习库已到 `028_verification_discussions`；升级前/后备份在试用目录 `backups/learning/`，完整性/FK 检查通过，原有表记录数量保持。备份路径和权限记录在开发状态；不需要为接手打开备份或数据库。
- 新前端已安装到 frontend/dist。上次页面与 JS 返回 200，代理健康 status/database=ok，未登录学习记录接口 401。

本轮已实现：

1. 验证后回看原题、本人答案、对应逐题反馈和参考解法，并保留提交/评估版本；已提交自动保存。
2. 旧记录只有整体反馈时保持原貌，不伪造逐题历史；AI 提出的可选拓展不改写原完成条件。有原要求缺口则不能判通过。
3. 每题打开独立题目讨论，继续追问/回答拓展；原验证及完成事实保留。讨论私文在学习库，避免复制到主库运行快照。
4. 模型可选择本地关键词，系统实际检索本人同委托教学对话和题目讨论，展示实际来源。最多一次查询、6 段、每段 1600 字符，讨论使用最近 8 轮；不是全历史复制、语义检索或联网。
5. 开始学习 → 学习记录，能找回进行中/已完成委托、历史验证及讨论，刷新恢复；查看历史不冒记学习开始。
6. 彻底删除移到“更多与隐私管理”，确认影响数量；清除验证/产出会同事务清除关联和引用传播的讨论正文，完成事实保留。迟到输出、回放及受控恢复不可复活内容。
7. 右侧 AI 学习伙伴默认折叠但保留；切换新方向时先暂停正在运行的学习，防止旧 session 阻止新任务。新安排仍需用户确认。

关键代码：learning_records.py、question_discussion.py、verification.py、continuity.py、learning_production.py、routers/learning.py；前端 VerificationReview、QuestionDiscussion、LearningRecords、LearningVerification、AiLearningRoom、FactWorkspace、ReturnReviewCard。不要开启大规模重构。

## 证据与测试范围

上一实施轮：后端全量 365 passed；最后提示调整后相关契约 42 passed；浏览器联合 22 passed；构建通过。测试包含回看/讨论/真实本地来源、完成/中断恢复、清除传播、迟到输出、受控恢复、合成 027 升级及窄屏。完整命令、中间失败和构建偏差见实施记录。

最近启用轮只重新构建并执行授权升级和健康检查，没有重跑全量测试或验证真实 DeepSeek。不要把旧测试数字写成新窗口刚跑过，也不要把 Mock/Playwright 当真实学习基线。

后续构建与自动化默认使用独立输出：

```bash
npm --prefix frontend run build -- --outDir /tmp/nautilus-review-dist
```

在 frontend 目录直接用 `NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-review-dist ./node_modules/.bin/playwright test ...`。避免直接 `npm run test:e2e`：它隐含默认 build，会覆盖正在服务的 frontend/dist。全部测试使用 pytest 临时库、`/tmp/nautilus-*`、Mock Provider 和明确合成内容。

## 不可越过的边界

- 不读取、搜索、打开、复制、修改或暂存 diagnostic-backups/。
- 不打开或操作默认 data/ 真实库。
- 不读取/输出 API Key、授权码、Cookie、Session Token、Provider 凭据或真实学习原文；不要索要这些内容。不要盲读真实运行日志。
- 本次 028 升级授权已经用毕，不是今后任意正文诊断、迁移、恢复、删除或数据修补的授权。不得自动迁移/恢复真实库，不为测试修改真实数据，不修改已有迁移。
- 可以只读检查启动脚本、PID、监听、静态页面和健康接口；不得借验收登录用户账号、调用真实 Provider 或自动采集学习正文。
- 不自动创建 Task 15/16 成果/路径图、17B 后台教练、19 人格或20插件平台；不进入18–21等后续扩张，不引入新基础设施。
- 正式完成门槛、网络信任、全副本删除承诺、第一轮更广试点对象、长期冻结决定仍有未决项，不替产品负责人选择。
- 额外联网服务配置 **FOLLOWUP-SEARCH-001** 已明确进入开发计划，必须继续保留。用户使用 DeepSeek 官方 API；当前本地检索不等于联网，新增搜索供应商、费用及出站范围尚未确认，不自行开通。

## 唯一下一项

协助作者在 Web 验收：学习记录找到已完成委托 → 打开旧验证确认原答案可见 → 围绕单题继续讨论并查看实际历史来源 → 刷新/重开恢复；另做一次新验证检查 DeepSeek 新生成的逐题反馈。不要要求用户为验收删除真实记录。

先完成只读接手核对，给出简短状态与最短验收路径。作者报告新问题后再定位并落实修复；若已有具体反馈，直接处理，不停在计划。Task 13B 目前 READY 仅指作者继续试用的运行条件，完整真实使用基线与长期产品价值仍未知。

每轮开发结束同步开发状态、相关决策/规格，记录实际文件、迁移、运行过的命令、失败/未测项目与唯一下一项。

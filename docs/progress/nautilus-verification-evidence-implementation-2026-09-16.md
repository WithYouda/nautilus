# Nautilus 验证产出、证据与删除实施记录

日期：2026-09-16，Asia/Shanghai。

本轮按用户已采纳的顺序完成 Task 15C，承接 Task 15B。复用既有事实、证据复核和状态派生，未新增产品方向决定；不代表完整 PRD V2、生产启用或真实学习旅程已验收。

## 实际改动

- 新增 `024_verification_evidence.sql`：验证提交关联原始产出、删除标记、评估关联证据运行；验证内容不可覆盖；证据私密文本独立保存，允许清除但禁止改写、删除记录或恢复原文。没有修改 001-023 迁移。
- 新提交与 `RecordVerificationArtifact` 命令、`verification.artifact_recorded` 事实事件在同一事务完成。内容只保留在 raw artifact，清除验证表重复原文；事件记录引用、校验值、真实会话和原提交时间。保存失败回滚，不调用 Provider。
- 用户材料分为题目/参考答案与“我的过程、理解或项目结果”。证据分析只接收本人产出；参考答案单独存在时不能通过能力验证，旧记录的历史通过结果也不能据此完成尚未完成的行动。AI 出题模式只分析已保存作答，不把服务器答案作为证据输入。
- 独立完成声明默认不勾选，条件随提交冻结。未勾选仍可保存、评估；目前已审核的 Python 正则标准要求独立证据，因此有资料/提示的提交不进入独立证据分析。声明不是系统对学习过程的独立核验。更改条件或作答必须新提交，通用产出更正不能绕过验证提交不可变约束。
- 用户在验证评估后主动调用 `/verifications/{id}/evidence`，复用现有标准分析、候选主张、人工复核与派生状态；评估与分析各自有运行引用和来源快照。验证通过不等于主张采纳，行动完成与成果获得支持分别表达。无标准保留事实/反馈和 blocked 运行，不生成能力主张或状态。
- 分析标准从真实会话绑定的契约版本读取；模型返回前后检查产出可用性，彻底删除期间的迟到评估/分析不能复活内容或主张。
- 新增 `/verifications/{id}/purge`，仅 owner 可用且要求 `confirmation: "PURGE"`。验证页说明影响并明确确认后，删除本验证全部提交、题目、答案、评估和私密契约快照；关联证据立即失效，状态和回访在同一事务重算。已完成行动和最小审计元数据保留。
- 通用产出彻底删除入口同步清除验证提交/评估副本，状态重算纳入同事务；其他尝试和题目仍可保留，页面会说明并提供删除剩余内容入口。删除后拒绝旧提交评估/确认/分析，允许未完成验证保存新的作答。
- 验证相关证据事件使用 schema 2，把主张文本、复核理由、回访备注等移到可删除私密记录；账本保留引用和校验值，不改写或重新计算历史链。删除同步清理投影副本；混合批量复核的共享理由也被清除，其他有效产出的证据不被连带失效。回放校验私密文本哈希，已删内容不会从事件重建。
- 显式授权升级工具在 schema 升级后导入可关联的旧提交，导入中断后即使 schema 已到最新也可重试。仅已有真实会话的旧提交接入事实链，无会话记录不补造关联且仍可彻底删除；过去已被覆盖的回答和缺失的模型快照不能补回。
- 备份恢复在既有 raw artifact 检查外增加验证提交、评估、题目/答案/契约和私密证据检查；拒绝恢复当前已删除的内容，删除后新备份可恢复。备份文件名增加微秒避免快速重试时名称冲突。普通应用启动仍只检查 schema，不执行导入或迁移。

## 文件范围

- 新增：`backend/app/migrations/024_verification_evidence.sql`、`backend/app/verification_content.py`、`backend/tests/test_verification_evidence.py`、本记录。
- 后端修改：`backend/app/core/commands.py`、`core/learning.py`、`core/events.py`、`verification.py`、`evidence.py`、`evidence_events.py`、`review.py`、`state_derivation.py`、`learning_service.py`、`learning_production.py`、`main.py`、`schemas.py`、`routers/learning.py`。
- 前端修改：`frontend/src/LearningVerification.tsx`、`frontend/src/api.ts`。
- 既有测试更新：`backend/tests/test_learning_verifications.py`、`test_verification_reliability.py`、`test_learning_domain_schema.py`。
- 文档同步：开发进度、产品决策的实现状态与更新历史、首片实施计划。PRD 产品语义未扩展。接手时全部其他改动保留，无暂存/提交/推送，未操作 `diagnostic-backups/`。

## 验证范围

聚焦命令（临时 SQLite、Mock/ASGI 请求，无真实 Provider、无监听服务）：

```bash
timeout 60s env PYTHONPATH=backend .venv/bin/python -m pytest -q \
  backend/tests/test_verification_evidence.py \
  backend/tests/test_verification_reliability.py \
  backend/tests/test_learning_verifications.py \
  backend/tests/test_learning_domain_schema.py \
  backend/tests/test_artifact_lifecycle.py \
  backend/tests/test_state_derivation.py \
  backend/tests/test_review_workflow.py \
  backend/tests/test_evidence_replay.py \
  backend/tests/test_learning_production_upgrade.py \
  backend/tests/test_startup_migration_guard.py \
  backend/tests/test_learning_domain_commands.py \
  backend/tests/test_learning_fact_hardening.py \
  backend/tests/test_evidence_claims.py \
  backend/tests/test_analysis_failures.py \
  backend/tests/test_evidence_provider.py \
  backend/tests/test_privacy_deletion.py
```

验证覆盖保存事务、两种作答模式、参考材料与独立条件、无标准降级、owner/确认契约、并发删除、复核/派生、混合批量引用清除、事件链不变、回放、迁移导入重试、旧备份拒绝及删除后恢复。

结果：**142 passed, 1 warning in 14.30s**，包含新增验证证据测试 15 项。最后补齐“删除旧尝试后，新尝试评估不应阻止删除后备份恢复”和回放共享引用清理后，另定向重跑验证证据、生产恢复与证据回放，**26 passed, 1 warning in 2.95s**；重复测试不累计为更多覆盖。警告来自既有 Starlette/httpx TestClient 弃用提示。

- 前端 `npm --prefix frontend run build` 通过，保留既有大于 500 kB chunk 提示。
- Python compileall、`git diff --check` 和本轮未跟踪文件空白检查通过。
- 未运行后端全量、Playwright、真实 Provider 或人工浏览器学习旅程；本轮不需要纯 UI Playwright。历史 `test_learning_facts_api.py::test_learning_database_is_independent_from_legacy_database` 曾在 TestClient 请求挂起，本轮未重跑、不计通过。其他聚焦 TestClient 回归正常结束。

## 生产与已知边界

- 未打开默认 `data/nautilus.sqlite3` 或真实 `data/learning.sqlite3`，未应用任何生产迁移，未启动或重启服务。024 仅在隔离测试库应用；021/022/023/024 的实际生产应用状态未核验，不以历史文档代替授权后的实际检查。
- 当前分析只覆盖既有已审核 Python 正则标准和已有分析器；声明独立完成不构成防作弊保证，AI 评估也不会补足缺少的独立人工复核维度。没有新增开放搜索、研究 Agent、附件解析或通用评分框架。
- 验证材料可由 owner 通过已有 raw artifact 读取，但验证公开响应不返还原文，验证页也不自动恢复私密作答编辑框。跨刷新未提交草稿、独立 URL、完成后复核与默认返回视图仍未完成。
- 删除边界是当前数据库逻辑可读内容、事件回放与应用的受控备份恢复。没有逐个重写外部旧备份、清除 Provider 已收到的材料或系统级副本，也没有验证磁盘取证级擦除。恢复工具必须持有当前删除标记；目标数据库丢失时的人工灾难恢复不能自动证明已删除内容不会复活。不得将本轮称为任意副本全域清除。
- 删除验证不会删除用户在教学对话中另行粘贴的内容、正式委托/目标本身或独立保存的其他产出；这些对象有各自边界。保留行动完成事实与删除后的证据失效语义。

精确下一项：Task 17A.0，先核对 PRD、已确认决策、`measurements.py` 和返回/完成入口，提供最小复核卡的当前位置、已有依据、未知缺口、一个推荐行动及理由和继续入口，修正完成/中断/主动切换/未知的测量口径。正式计划或目标变化仍须确认；不依赖成果图，不自动迁移真实库或启用服务。

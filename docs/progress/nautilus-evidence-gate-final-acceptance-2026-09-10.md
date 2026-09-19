# Nautilus 证据门最终验收记录

| 项目 | 内容 |
| --- | --- |
| 验收日期 | 2026-09-10，Asia/Shanghai |
| 验收范围 | PRD V2 11.4.2 证据闭环 14 条、Task 10-12 及复核卡权限可见范围 |
| 结论 | 证据门整体产品验收通过 |
| 产品边界 | 仅代表 PRD V2 首片证据门通过，不代表完整 PRD V2、CAP-FUT-001 或完整长期学习协作者已完成 |
| 数据边界 | 后端与 Playwright 均使用隔离临时数据库；默认主库和真实学习库未迁移 |

## 1. 总体验收结论

- Task 10 已关闭 PRD 11.4.2 第 11-13 条。
- Task 12 已关闭 PRD 11.4.2 第 9 条。
- Task 11 已补齐复核卡权限可见范围、无授权替代路径和证据门逐项验收。
- PRD 11.4.2 第 1-14 条均具备后端、前端或 Playwright 可复现证据。
- 证据门整体产品验收通过。
- 完整 PRD V2 仍需 Task 13A 之后的后续任务。

## 2. PRD 11.4.2 逐项状态

| 条目 | 状态 | 验收证据 |
| --- | --- | --- |
| 1. 候选主张同时引用原始产出、事实事件、成果、标准版本和能力维度 | 通过 | `test_evidence_claims.py`、`test_evidence_replay.py`、`nautilus-first-slice-facts.spec.ts` |
| 2. 无引用 AI 印象不能进入证据链 | 通过 | `test_evidence_claims.py`、`test_analysis_failures.py`、测量护栏测试 |
| 3. Core 根据当前可参与证据派生状态和原因标签 | 通过 | `test_state_derivation.py`、`test_review_workflow.py`、`nautilus-first-slice-facts.spec.ts` |
| 4. 质疑后主张立即退出当前状态计算，历史与审计保留 | 通过 | `test_review_workflow.py`、证据回放测试 |
| 5. 批量处理、逐条依据、采纳、撤销、暂不处理，且用户动作不绕过 Core | 通过 | `test_review_workflow.py`、`nautilus-first-slice-facts.spec.ts` |
| 6. 四类 AI 失败不阻塞保存，界面区分保存与分析结果，提供恢复入口 | 通过 | `test_analysis_failures.py`、`test_agent_permission_runtime.py`、Playwright |
| 7. 重试幂等，不重复事实或证据，失败与成功可追踪 | 通过 | `test_analysis_failures.py`、`test_evidence_provider.py` |
| 8. 状态、审查动作和撤销可从事件与投影重建 | 通过 | `test_evidence_replay.py`、`test_measurements.py` |
| 9. 事件版本变化显式拒绝，不静默改变含义 | 通过 | `test_learning_fact_hardening.py`、`test_evidence_replay.py`、Task 12 |
| 10. 更正、普通删除、撤回、彻底删除及其状态重算符合隐私边界 | 通过 | `test_artifact_lifecycle.py`、`test_privacy_deletion.py`、`test_evidence_replay.py` |
| 11. 全局 Agent 默认上下文只含最小摘要、状态和证据引用，不含未授权原文 | 通过 | `test_agent_permission_runtime.py` |
| 12. Agent 权限申请显示目的、范围、粒度、时效和替代方案；批准只扩大读取 | 通过 | `test_agent_permission_runtime.py`、`nautilus-first-slice-facts.spec.ts` |
| 13. 拒绝后仍可学习、保存和读取；Agent 基于已授权信息继续并说明限制 | 通过 | `test_agent_permission_runtime.py`、`nautilus-first-slice-facts.spec.ts` |
| 14. 复核卡展示依据可见范围和权限限制；未授权原文或摘录不进入卡片或 Agent 上下文；用户可暂不处理或安排验证 | 通过 | `nautilus-first-slice-facts.spec.ts` 新增复核依据可见范围、暂不处理、人工复核和补充验证场景；Agent 上下文后端测试 |

## 3. Task 11 实际交付

- 复核卡新增“复核依据可见范围”：
  - 用户是否可查看原始产出；
  - Agent 是仅有摘要、状态和证据引用，还是已获目标行动原文授权；
  - 原始产出与事实事件引用；
  - 缺少原文授权时的分析限制说明。
- 明确用户无需授权即可：
  - 暂不处理；
  - 请求人工复核；
  - 安排补充验证。
- Playwright 验证：
  - 默认 Agent 无原文授权；
  - 复核卡显示权限限制；
  - 用户可以暂不处理候选主张；
  - 用户可以请求人工复核；
  - 用户可以安排补充验证；
  - 以上路径不要求用户批准 Agent 原文读取。

## 4. 已知边界

- 证据门通过不代表完整 PRD V2 完成。
- `GET /agent/context` 是确定性上下文预览和未来 Agent 输入契约，还不是完整外部 Agent 执行环境。
- 真实使用基线尚未采集。
- 生产学习库尚未升级。
- 新领域工作轴、成果图、路径图、回归教练和主动教练仍未实现。
- `012-020` 迁移仍未应用到真实学习库。

## 5. 验证命令与结果

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：254 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：36 项通过，全部使用隔离 E2E 数据目录。

```bash
git diff --check
```

结果：通过。

## 6. 交接结论

PRD V2 首片证据门整体产品验收通过。下一项进入 Task 13A：指标采集、口径与隐私硬化。

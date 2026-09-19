# Nautilus 事实门验收记录

| 项目 | 内容 |
| --- | --- |
| 验收日期 | 2026-09-07，Asia/Shanghai |
| 验收对象 | PRD V2 11.4.1 事实闭环 |
| 验收范围 | 无合格达成标准路径、独立学习库、新领域学习行动范围、统一 Agent 权限申请/拒绝链路 |
| 结论 | 事实门在验收时按“无标准路径 + 新领域行动范围”通过；验收后用户已确认 Python 正则基础 v1 标准包，证据门工程链路已开始但尚未正式验收 |
| 数据边界 | 全部自动化测试使用 pytest 临时目录或 `/tmp/nautilus-playwright.*`；未打开默认 `data/nautilus.sqlite3` |

## 1. 验收结论

事实门已按以下边界关闭：

1. **无标准路径**：允许创建学习行动、可验证成果、学习委托、学习会话和原始文本产出；保存事实事件和当前态投影；显示 `blocked_no_criterion`，不生成证据主张或学习状态。
2. **新领域行动范围**：首片不引入旧 `global / plan / task` 层级，也不建立旧模型映射；事实范围按独立学习库中的 owner 与 learning action 执行。
3. **统一 Agent Runtime**：新增持久化权限申请、拒绝、过期和审计；Agent 不能直接读事实，用户拒绝后仍可继续保存。
4. **回放实现**：当前采用同一 SQLite 事务内删除并重建投影，事务提交前不暴露半成品，失败时回滚并保留旧投影；这是首片对“隔离投影 + 校验后切换”的已记录技术替代。

尚未关闭的边界：

- 尚无真实预审核、版本化的窄领域标准包；
- Agent 权限仅实现申请、拒绝和过期，尚未实现批准后的实际读取授权；
- 尚无 Provider 选择和证据分析；
- 尚无同一用户内部的旧 `global / plan / task` 范围，因为首片不引入旧模型；
- 证据门不得开始。

## 2. PRD 11.4.1 逐项结论

### 2.1 原始文本产出不可被后续主张或投影覆盖、篡改

**结论：通过。**

- `learning_raw_artifact` 保存不可变内容版本、内容哈希、事实事件 ID 和会话 ID。
- 普通更正通过追加新版本和 `artifact.corrected` 事件表达。
- 回放时用不可变原文校验事件 payload 的内容哈希。
- 证据：`test_learning_fact_hardening.py`、`test_learning_facts.py`、`test_learning_facts_api.py`。

### 2.2 无合格标准时仍保存但不生成主张或学习状态

**结论：通过。**

- 无标准委托允许创建。
- 保存产出时创建 `learning_analysis_run(status=blocked_no_criterion, reason=no approved criterion)`。
- 不生成证据主张或派生学习状态。
- 证据：`test_learning_facts.py`、`test_learning_facts_api.py`、`nautilus-first-slice-facts.spec.ts`。

### 2.3 原始产出内容与事实事件分开保存

**结论：通过。**

- 原文只在 `learning_raw_artifact`。
- 事件 payload 记录会话、产出版本、动作和时间等上下文，并保存内容哈希，不保存原文。
- 证据：`test_learning_facts.py`、`test_learning_fact_hardening.py`。

### 2.4 事件唯一、聚合内有序、命令重试幂等

**结论：通过。**

- 事件有唯一 `event_id`、聚合版本和 `previous_hash` 链。
- 命令有唯一幂等键；同键同请求返回原结果，同键异请求拒绝。
- 证据：`test_learning_domain_commands.py`、`test_learning_fact_hardening.py`、`test_learning_facts_api.py`。

### 2.5 事件追加和当前态投影同事务提交

**结论：通过。**

- `LearningCore.execute()` 在同一 `BEGIN IMMEDIATE` 事务内写命令、事件、投影和审计。
- 事务失败时全部回滚。
- 证据：`test_learning_domain_commands.py`。

### 2.6 投影可重建并在校验通过后切换，失败不覆盖现有投影

**结论：通过，采用已记录技术替代。**

- 当前实现为同一 SQLite 事务内删除并重建投影。
- 事务提交前外部查询看不到半成品；失败回滚并保留旧投影。
- 该实现满足首片“原子切换”和“失败不覆盖”的目标，但不是独立临时表。
- 证据：`test_learning_fact_hardening.py`。

### 2.7 跨身份、越权和未授权访问由 Core/Runtime 拒绝

**结论：通过，按首片新领域范围解释。**

- 跨身份 HTTP 读取和写入返回 `not_found` 或 `permission_denied`。
- Agent 不能直接读事实；统一 Runtime 权限申请被拒绝后仍可保存。
- 首片不引入旧 `global / plan / task` 范围；等价边界为独立学习库中的 owner 与 learning action。
- 证据：`test_learning_facts_api.py`、`test_agent_permission_runtime.py`。

### 2.8 业务测试使用隔离数据库，默认 `data/` 不参与自动化验证

**结论：通过。**

- pytest 使用临时目录。
- Playwright 使用 `/tmp/nautilus-playwright.*`。
- 未打开默认主库。
- 证据：`backend/tests/conftest.py`、`scripts/start-e2e.sh`、本记录验证命令。

### 2.9 不启用 AI 分析时仍可保存并重新读取

**结论：通过。**

- 前端事实工作台可在无 AI 分析时保存会话和文本产出。
- 刷新后可重新读取当前版本和历史版本。
- 证据：`nautilus-first-slice-facts.spec.ts`。

## 3. 验证命令

```bash
timeout 120s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：195 项通过，1 个既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
./node_modules/.bin/playwright test
```

结果：33 项通过，全部使用隔离数据目录。

```bash
git diff --check
```

结果：通过。

## 4. 后续边界

1. 事实门通过不代表证据门通过。
2. 证据门开始前必须先确定首个窄领域和真实预审核标准包。
3. 旧 `global / plan / task` 范围不进入首片事实门；若后续需要，应在新领域模型中显式建模，不恢复旧模型映射。
4. 回放的独立临时投影实现可在后续性能或并发需求出现时再评估，当前事务内重建已满足首片验收。


## 5. 验收后补充

2026-09-07 用户确认首个窄领域为“Python 正则表达式基础 v1”，标准包已升级为 approved 并种入独立学习库。随后 Task 5 实现了 Provider 语义分析、确定性检查、候选主张、四类失败恢复、人工复核请求和补充验证安排。

该补充不改变本记录的事实门验收边界：事实门验收发生时按无标准路径关闭；证据门尚未正式验收，状态派生、复核执行、质疑、撤回和重算仍待 Task 6 完成。

# Nautilus 生产学习库初始化与验收记录

| 项目 | 内容 |
| --- | --- |
| 操作日期 | 2026-09-10，Asia/Shanghai |
| 授权状态 | 用户已明确授权生产学习库备份、初始化/升级、完整性校验和恢复演练 |
| 操作范围 | 仅独立学习库 `data/learning.sqlite3` |
| 结论 | 生产学习库已初始化到 `020` 并通过校验；交付服务已启动并通过健康检查 |
| 默认主库 | 未打开、未迁移，文件元数据未变化 |
| 服务状态 | 已启动，绑定 `0.0.0.0`；Web `5173`，API `8000` |

## 1. 重要事实修正

操作前检查发现：

```text
data/learning.sqlite3 不存在
```

这与此前开发状态中“真实学习库停留在 011”的记录不一致。本轮没有找到该文件，也没有执行任何删除或移动操作。

因此本次操作不是“从既有 011 库升级”，而是：

```text
初始化一个新的空生产学习库，并直接应用 011-020
```

由于源库不存在，没有升级前数据可备份或迁移。若用户此前另有学习库路径或备份，需要另行提供路径后再评估导入；本轮未在仓库外搜索私人数据文件。

## 2. 实际操作

新增生产工具：

```text
backend/app/learning_production.py
scripts/upgrade-learning-database.py
```

功能：

- 拒绝操作默认主库和 `diagnostic-backups/`；
- 要求显式 `--authorize-production`；
- 已有库时先创建升级前备份；
- 初始化或升级学习库；
- 执行 `PRAGMA integrity_check`；
- 执行 `PRAGMA foreign_key_check`；
- 创建 `0600` 权限的本地备份；
- 创建不含私人内容的 JSON 清单；
- 恢复前检查备份是否会复活当前已彻底删除的产出；
- 当前库缺失时默认拒绝恢复，除非显式接受无法对照当前删除标记验证。

## 3. 生产学习库状态

路径：

```text
data/learning.sqlite3
```

文件权限：

```text
0600
```

已应用迁移：

```text
011_nautilus_learning_domain
012_learning_evidence_claims
013_learning_evidence_follow_ups
014_learning_derived_states
015_learning_review_completion
016_learning_evidence_events
017_learning_evidence_provider
018_learning_analysis_provider_snapshot
019_agent_permission_grants
020_evidence_event_schema_version
```

校验结果：

```text
integrity_check = ok
foreign_key_check = ok
up_to_date = true
```

## 4. 备份与恢复演练

备份路径：

```text
data/backups/learning/learning-post-initialization-20260909T170636Z.sqlite3
```

备份清单：

```text
data/backups/learning/learning-post-initialization-20260909T170636Z.json
```

备份 SHA-256：

```text
04b8b6196f3af9254306623625c4eadf5a91ecd2818e27a469cdc00226640f93
```

备份和清单权限均为：

```text
0600
```

恢复演练：

- 将备份恢复到 `/tmp/nautilus-learning-restore-.*` 隔离目标；
- 恢复后迁移历史与生产库一致；
- `integrity_check = ok`;
- `foreign_key_check = ok`;
- 临时目标已自动清理。

## 5. 彻底删除保护

生产库当前没有用户产出，检查结果：

```text
purged_artifacts_with_content = 0
```

恢复工具包含以下保护：

- 若当前库中某产出已彻底删除；
- 且待恢复备份中该产出仍含 `content` 或 `content_hash`;
- 则拒绝恢复；
- 要求先创建彻底删除后的新备份。

隔离测试覆盖了该拒绝路径。

## 6. 默认主库保护

本轮前后仅比较文件元数据，未打开默认主库。

操作前后以下文件大小和修改时间均未变化：

```text
data/nautilus.sqlite3
data/nautilus.sqlite3-wal
data/nautilus.sqlite3-shm
```

未把 `011+` 迁移应用到默认主库。

## 7. 运行边界

用户随后授权启动交付服务。服务由 `scripts/start.sh` 启动：

- 后端绑定 `0.0.0.0:8000`;
- 前端生产预览绑定 `0.0.0.0:5173`;
- 前端页面不含 `/@vite/client`，无 HMR 自动刷新；
- WSL2 实际 IP 为 `172.17.253.105`。

当前访问地址：

```text
Web: http://172.17.253.105:5173
API: http://172.17.253.105:8000
```

健康检查：

```text
GET /api/health -> 200
{"status":"ok","service":"nautilus","version":"0.1.0","database":"ok"}
```

Web 首页返回 `200`。后端与前端日志未见 traceback、critical 或 error。

## 7.1 默认主库启动后状态

服务启动按既有主库迁移机制将默认主库从 `001-004` 应用到 `001-010`。这是启动脚本既有行为；未把 `011+` 学习域迁移应用到默认主库。

启动后只读校验：

```text
default_main_migrations = 001_initial ... 010_ai_conversation_scope
default_main_integrity = ok
```

已创建启动后主库备份：

```text
data/backups/main/nautilus-post-service-start-20260909T171618Z.sqlite3
```

备份 SHA-256：

```text
a37affb1ac5c27ece31997046f407a64f5b585c66105d0d50fb6dc6776a1ef1c
```

备份与清单权限为 `0600`。本轮未创建 `005-010` 应用前的主库备份；该边界已如实记录。

## 8. 验证

```bash
timeout 180s env PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests
```

结果：

```text
262 passed, 1 warning
```

警告为既有 Starlette/TestClient 弃用警告。

```bash
npm --prefix frontend run build
```

结果：TypeScript 和生产构建通过。

```bash
cd frontend && node_modules/.bin/playwright test
```

结果：

```text
36 passed
```

```bash
git diff --check
```

结果：通过。

## 9. 交接结论

- 生产学习库数据层已初始化并验证；
- 备份、恢复演练和彻底删除保护已建立；
- 默认主库未变化；
- 交付服务已启动并通过健康检查；
- Task 14 已完成；
- Task 13B 真实使用基线采集开始，但尚无真实使用样本。

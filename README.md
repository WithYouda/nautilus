# 学海无涯（Nautilus）

本地优先的AI学习协作者：从学习目标和第一步开始，进入教学、提交作答、获得逐题反馈，再继续讨论或复核下一步。当前为作者试用中的可运行纵切片，长期学习效果尚未验收。主导航为学习首页、学习计划、学习记录；旧规划、日历和计时界面已退出。

## 文档入口

- [当前状态、试用地址、限制与下一项](docs/progress/nautilus-development-status.md)
- [PRD V2：正式需求](docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md)
- [产品决定：已确认协议与开放问题](docs/progress/nautilus-product-design-decisions.md)
- [当前实施计划与后续范围](docs/superpowers/plans/2026-09-05-nautilus-first-slice-implementation.md)
- [领域架构与数据边界](docs/superpowers/specs/2026-09-05-nautilus-first-slice-domain-architecture.md)
- [开发规则](AGENTS.md)

状态、需求、决定各维护一处。已被替代的进度报告和旧交接内容可从Git历史查询，不作为当前操作步骤。其余早期设计规格保留独立设计细节；与PRD V2冲突时以V2及后续确认决定为准。

## 开发环境与启动

依赖Python3.12+、Node.js20+、npm10+及WSL2：

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

当前已有trial使用开发状态中的run.sh；它保留用户配置与数据。对结构已匹配的默认环境可运行 `./scripts/start.sh`，构建前端后提供无HMR的预览。普通启动不建库、不迁移；缺库或版本不符会停止。初始化、升级、恢复按明确的数据库范围处理，不通过重复启动解决。

服务绑定 `0.0.0.0`。默认脚本端口为Web5173/API8000，当前trial为Web5188/API8018；Windows访问地址用 `hostname -I` 的实际WSL2 IP。开发用HMR可单独运行 `npm --prefix frontend run dev -- --host 0.0.0.0`，用户试用使用已构建预览。

授权页提供同一实时授权码的文字和二维码；浏览器会话持续到主动注销，普通服务重启不要求重新授权。令牌只保存在本机配置的运行路径（默认 `tmp/access-token`），不写入日志、文档或Git。

## 数据库、升级与恢复

同一环境有两个职责不同的文件：`nautilus.sqlite3`承载普通会话/配置等，`learning.sqlite3`承载新学习域。主库迁移001–010、学习库迁移011及以后；029是结构版本号，不是额外环境。

下列命令仅在授权了指定库的操作后执行，路径必须指向目标环境：

```bash
env PYTHONPATH=backend .venv/bin/python scripts/upgrade-learning-database.py   --database <learning.sqlite3> --backup-dir <backups-dir> --authorize-production
```

工具拒绝默认主库和diagnostic-backups；现有库先备份，再迁移并校验完整性/外键，最后创建升级后备份和哈希清单。目前尚未把“省去后置备份”建议实现到工具中。备份是私有运行数据，权限0600，不纳入Git；普通代码修改或服务重启无需备份。一次清理旧备份不等于配置了自动保留策略。

仅检查可添加 `--verify-only`；恢复使用 `--restore <backup.sqlite3> --database <target-learning.sqlite3> --authorize-production`。恢复会对照当前删除标记，拒绝复活已彻底删除内容；目标库缺失时默认拒绝，只有接受无法对照删除标记这一边界后才用 `--allow-missing-current`。恢复演练是独立验证步骤，不是每次升级命令自动执行。

## 测试

后端使用隔离临时库；浏览器使用Mock Provider及临时服务。不要用真实trial或默认data作为自动化数据，也不要让测试构建覆盖正在试用的frontend/dist：

```bash
env PYTHONPATH=backend .venv/bin/pytest -q backend/tests
npm --prefix frontend run build -- --outDir /tmp/nautilus-test-dist
cd frontend
NAUTILUS_E2E_BUILD_DIR=/tmp/nautilus-test-dist ./node_modules/.bin/playwright test
```

小改动选相关测试文件；共享逻辑或数据生命周期变化再扩大回归。代码未变时复用有效结果，不为文档、提交或重启重复跑全套。Playwright默认使用API8012/Web5186与 `/tmp/nautilus-playwright.*`，结束后清理；若无系统Chromium，安装Playwright Chromium后再运行。

## 提交与日常维护

完成一个可验证的小改动即本地commit，明确列出暂存路径；push另行按任务范围处理。不要提交运行库、备份、凭据、diagnostic-backups或无关文件。进度文档仅维护当前状态与简短更新记录，需求改变才同步PRD/产品决定；详细修改由Git diff与测试记录说明。

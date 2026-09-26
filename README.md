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

首次授权时，在运行服务的 WSL2 主机本地读取授权码文件并手动输入页面。默认启动脚本使用 `tmp/access-token`；当前trial使用 `tmp/nautilus-trial-20260919/runtime/access-token`；若设置了 `NAUTILUS_RUNTIME_TOKEN_FILE`，读取该路径。父目录权限0700、文件0600；默认启动脚本只提示路径，不打印授权码。浏览器会话持续到主动注销，普通服务重启不要求重新授权。授权码不写入日志、文档或Git；网络可达不代表已授权，正式网络信任范围仍待决定。

## 联网搜索

在工作区页头或学习室输入区打开“搜索设置”，可添加/测试19种外部服务，配置密钥、搜索深度、地址和各服务高级参数。默认有无需密钥的Bing，进入会话默认关闭搜索；发送前选择“外部服务”，查询留空使用当前问题。DeepSeek等聊天模型可以继续使用原提供方，由所选外部服务提供资料。付费服务需要自己的账户，搜索测试会实际调用配置的服务。

“模型内置”需要在AI提供方设置选择支持的API协议：OpenAI Responses、Google Gemini或Anthropic Messages，并使用支持搜索工具的模型/账户；普通OpenAI兼容协议不能仅靠开关获得厂商搜索。来源和检索状态随每版回答保存，结果默认折叠。Custom JS需要后端requirements中的QuickJS，在隔离进程执行。服务字段、协议、运行限制与尚未完成的真实账户验收见[联网搜索规格](docs/superpowers/specs/2026-09-26-nautilus-web-search.md)。

## 数据库、升级与恢复

同一环境有两个职责不同的文件：`nautilus.sqlite3`承载普通会话/配置等，`learning.sqlite3`承载新学习域。主库迁移001–010、学习库迁移011及以后；029是结构版本号，不是额外环境。

下列命令仅在授权了指定库的操作后执行，路径必须指向目标环境：

```bash
env PYTHONPATH=backend .venv/bin/python scripts/upgrade-learning-database.py   --database <learning.sqlite3> --backup-dir <backups-dir> --authorize-production
```

工具拒绝默认主库和diagnostic-backups；现有库先备份，再迁移并校验完整性/外键，最后创建升级后备份和哈希清单。目前尚未把“省去后置备份”建议实现到工具中。备份是私有运行数据，权限0600，不纳入Git；普通代码修改或服务重启无需备份。一次清理旧备份不等于配置了自动保留策略。

仅检查可添加 `--verify-only`；停服务后的离线恢复使用 `--restore <backup.sqlite3> --database <target-learning.sqlite3> --authorize-production`。工具对实际待安装的快照检查已知删除内容和删除标记：缺少当前任一产出版本、验证、提交、证据私文或讨论的清除标记即拒绝，候选正文为空也不能绕过；拒绝不替换当前库。目标库缺失时默认拒绝；显式 `--allow-missing-current` 是缺失库灾难恢复例外，无法证明历史删除不被复活。恢复演练是独立验证步骤，不是每次升级命令自动执行。

这些保护不等于所有副本已被物理清除：旧 schema v1 事件私文、保留备份、导出、Provider 和文件系统副本仍有未完成边界；旧备份不会随运行库删除自动改写。PRD 的删除目标不因此收窄，分层保证和验收见[领域架构](docs/superpowers/specs/2026-09-05-nautilus-first-slice-domain-architecture.md#删除影响矩阵)。

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

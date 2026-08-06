# 学海无涯（Nautilus）

Nautilus 是一个本地优先的 AI 学习管理 Web 应用。当前仓库已具备 WSL2 本地运行基础、可执行的四层学习计划、今日驾驶舱、学习计时，以及全局/计划/任务三级上下文的 AI 学习纵切片。

当前完整开发状态、已知问题和 Agent 接手步骤见：

```text
docs/progress/nautilus-development-status.md
```

## 开发环境

- Python 3.12+
- Node.js 20+
- npm 10+
- WSL2

## 启动

首次启动前安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

启动前端和后端：

```bash
./scripts/start.sh
```

标准启动脚本会先构建前端，再以无 HMR 的生产预览模式提供页面。开发时可以单独使用 `npm run dev`，但开发服务器不能作为用户交付运行方式，否则源码变化会触发浏览器刷新。

启动脚本会绑定 `0.0.0.0`，并打印 WSL2 实际访问地址，例如：

```text
Web: http://<WSL2_IP>:5173
API: http://<WSL2_IP>:8000
```

首次打开 Web 地址时，授权页会显示本次服务启动生成的实时授权码：上方二维码和下方文字码内容相同，可扫码、复制或手动输入。授权成功后，会话默认持续到主动注销；服务重启不会要求重复授权。

当前运行中的授权码只保存在权限为 `0600` 的 `tmp/access-token` 文件中，也可在授权页查看。不要把它写入日志、截图或提交记录。

## 单独运行

后端：

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --no-access-log
```

前端：

```bash
npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173 --strictPort --logLevel silent
```

## 测试

```bash
PYTHONPATH=backend python3 -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

端到端测试会先创建生产构建，再在 `8012/5186` 启动隔离服务。测试数据库位于自动创建的 `/tmp/nautilus-playwright.*`，测试结束后删除，不会读写默认 `data/nautilus.sqlite3`。套件会自动使用已安装的系统 Chromium；若系统中没有 Chromium，可先运行 `npx --prefix frontend playwright install chromium`。

## 当前阶段

已实现：

- WSL2 启动脚本和实际 IP 输出
- React + TypeScript + Vite 前端骨架
- FastAPI 本地服务和健康检查
- SQLite WAL、外键和迁移机制
- 首次启动自动创建本地身份和设备标识
- 服务启动随机访问令牌
- 授权页实时授权码、同码二维码和复制入口
- 主动注销前持续有效的本地浏览器会话
- HttpOnly、SameSite=Strict 浏览器会话
- 计划、科目、主题、任务四层计划模型
- 全部计划总览与单计划概览、结构、排期视图
- 文档式计划大纲和单一内联节点编辑器
- 任务完成与精确撤销完成
- 今日任务、时长与完成进度驾驶舱
- 学习、练习、复习和知识产出四类任务
- 独立任务列表与搜索、状态、类型、排期和日期筛选
- 任务按天延期或提前重排
- 月历任务视图
- 灵活进度和固定日程字段
- 25/5、50/10、自定义番茄钟和普通计时
- 开始、暂停、继续、结束与一键完成
- WebSocket 计时状态更新和精确学习会话记录
- 首页模块显示、隐藏和排序
- 三套系统布局模板
- 个人布局模板保存、重命名、应用和删除
- OpenAI-compatible 多提供方和多模型配置
- 模型发现、手动模型和脱敏运行配置快照
- AI 学习室、流式 Markdown 回复和显式推理内容折叠
- 持久化对话历史、改名、删除确认和标题生成
- 全局、计划、任务和独立对话上下文范围
- 全局 AI 学习伙伴、计划 AI 和任务 AI 入口
- 隔离临时数据库的正式 Playwright 回归测试

当前仍是可运行纵切片，不代表首阶段全部完成。审批写入、对话分支、资料检索、知识库、任务依赖、完整甘特图、附件、Web Search 和高级模型请求参数仍按正式规格分阶段实现。

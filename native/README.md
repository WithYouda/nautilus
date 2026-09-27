# Nautilus 独立运行验证

这是 A3 的最小技术验证：Tauri/React 界面、Rust 模型连接、本机 SQLite 保存文字资料及对话。它不连接电脑上的 Python 服务，不导入原 trial 数据。当前只有一个验证对话；完整学习流程、搜索外发确认、设备配对与同步尚未移植。模型接口只接入兼容 OpenAI 的流式 Chat Completions，不代表已有所有 Provider 协议均可用。

## 使用

本次安装包：Windows下载文件夹的 `nautilus-independent-0.1.0-arm64-20260928.apk`（28,855,642字节，Android 7.0及以上ARM64，作者已在小米13确认彻底退出后资料和回答保留）。SHA256：`ef99649aed5ce3eaf17fa5ef79d65a7acd206d6fede17599177ddf1dbe282200`。

1. 安装提供的 Android APK，打开“Nautilus 独立验证”。
2. 保存自己的模型服务 HTTPS 地址（通常以 `/v1` 结尾）和模型名称；填写 API 密钥。密钥只保留在当前应用内存，重开后重新输入。
3. 粘贴一份测试文字资料，保存后选用；发送问题。问题、所选资料及相同资料版本范围内连续成功的对话会交给指定模型服务。更换资料或资料版本后重新开始上下文，不把其他范围的私文带入。
4. 关闭电脑，手机联网后继续对话；彻底关闭并重开应用，核对资料、已生成回答和失败状态仍在。关闭手机网络仍可查看本机已存内容，不能生成新回答。本验证版重开后需重新勾选下一轮要使用的资料；历史各轮使用的资料版本仍保存。
5. 生成中点击停止；已收到的部分保留，重开不会自动重发。请反馈手机型号、Android版本和失败步骤，不需要提供密钥。

本验证版不提供资料删除、数据导出或迁入正式客户端，先使用测试资料。卸载应用或清除应用数据会删除本机记录；Android云备份/系统设备迁移在本包中关闭，避免误认为已实现Nautilus设备同步。原试用环境不受影响。

## 构建

JavaScript依赖复用 `frontend/package-lock.json`；Rust依赖固定于本目录 `Cargo.lock`。

```sh
cd /home/kingdom/ai_learning/frontend
npm ci
npx tsc -p tsconfig.native.json --noEmit
npx vite build --config vite.native.config.ts
cd ../native
cargo test -p nautilus-core
```

Android需要JDK21、Android SDK（本次Tauri模板要求API 37，对应SDK包 `platforms;android-37.0`）、构建工具37.0.0、NDK27.2.12479018和Rust `aarch64-linux-android` target。设置 `JAVA_HOME`、`ANDROID_HOME`、`NDK_HOME` 后：

```sh
../frontend/node_modules/.bin/tauri icon ../frontend/public/favicon.svg --output src-tauri/icons
../frontend/node_modules/.bin/tauri android init --ci --skip-targets-install
python3 scripts/prepare-android.py
../frontend/node_modules/.bin/tauri android build --debug --target aarch64 --apk
```

本机Java下载官方Maven依赖曾反复发生TLS握手失败；已用正常校验HTTPS的下载器建立官方依赖缓存。需要复用时，运行准备脚本前设置 `NAUTILUS_MAVEN_CACHE=/home/kingdom/.local/share/nautilus-toolchains/maven-http-cache`，优先读取缓存，再访问官方源。缓存和临时下载进程均不进入安装包。

使用开发签名，供本人安装验证；不是应用商店发布包。生成的Android工程、工具链、签名及APK不提交Git。后续更新须沿用同一签名才能覆盖安装；不要为更新而要求用户卸载清除数据。

Android原生库按[Android官方16 KB页面要求](https://developer.android.com/guide/practices/page-sizes?hl=zh-CN)设置链接对齐；打包后仍须真机验证。

### Windows

本次程序：下载文件夹 `nautilus-independent-0.1.0-windows-x64-20260928-014337.exe`（14,468,608字节）。SHA256：`ced15d2702d4a959d524f097af319e0b14467852fda01016ccc0726b04d47488`。双击后按上方相同流程配置模型、粘贴测试资料和对话；它不依赖WSL服务。程序未签名，Windows可能提示未知发布者。实际Windows原生旅程检查已通过，仍待本人使用反馈；尚未实现手机与电脑同步。

Windows需要微软C++构建工具、Windows SDK、Rust MSVC stable与WebView2。本机已获许可并安装构建组件；保留既有GNU默认工具链。先完成上述前端及图标生成，再用Windows PowerShell执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu\home\kingdom\ai_learning\native\scripts\build-windows.ps1"
```

脚本只复制构建输入到 `%LOCALAPPDATA%\NautilusBuild\windows-validation`，用MSVC构建后将EXE放到下载文件夹并输出SHA256。程序直接运行，依赖Windows已安装的WebView2；不是安装向导或商店发布包。数据库保存在 `%LOCALAPPDATA%\com.nautilus.validation\native-validation.sqlite3`，关闭程序或替换EXE不会清除它。重复打开会回到现有窗口，避免第二个进程把正在生成的回答误判为中断。

实际原生检查脚本为 `scripts/smoke-windows.cjs`，由Windows Node执行，参数依次为EXE路径和含Playwright的 `frontend` 目录。它用临时数据目录、本机模拟模型及WebView2调试连接检查真实Rust调用、重复启动、取消和重开；不使用真实模型或trial。`NAUTILUS_VALIDATION_DATA_DIR` 仅供Windows隔离测试覆盖保存位置，正常使用无需设置。

Mac/iPhone尚无构建和真机验证资源。共享Rust代码通过检查不等于四平台验收。

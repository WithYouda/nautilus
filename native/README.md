# Nautilus 独立运行验证

这是 A3 的最小技术验证：Tauri/React 界面、Rust 模型连接、本机 SQLite 保存文字资料及对话。它不连接电脑上的 Python 服务，不导入原 trial 数据。当前是一个可分支的验证对话；局域网配对与同步已接入，完整学习流程和搜索外发确认尚未移植。模型接口只接入兼容 OpenAI 的流式 Chat Completions，不代表已有所有 Provider 协议均可用。

## 当前版本与使用

0.2.0在Windows/Android验证本机保存、局域网配对、双向自动同步、资料冲突选择和对话分支。真实Android与Windows互通仍需作者用手机反馈；自动化不能代替该反馈。正式客户端须记住API Key，当前验证包仍仅存内存，重开需重新输入。

1. 手机覆盖安装新版APK，不卸载旧版；Windows运行新版EXE。两端连接同一Wi-Fi/局域网，保持应用打开。Windows若显示防火墙提示，允许本应用在本人使用的专用网络通信；Android如提示本地网络权限，允许后可点“重试连接”。
2. 已有0.1.0数据时，应用先显示“备份并升级本机数据”。只有点击后才在本机创建升级前SQLite备份，并把本机结构1升级为2，保留资料、历史回答及当时使用的资料版本。该操作不接触原trial035。备份路径会显示在界面；不要通过卸载或清数据解决升级问题。
3. 为两端分别填写容易辨认的设备名称。一端生成配对码，复制到另一端输入；配对码包含加密身份和连接信息，较长，10分钟内有效。两端核对设备名称，分别确认后才交换内容。
4. 配对后同步本验证App的全部文字资料和已保存对话。保存新资料或回答后，另一端自动读取更新，无需退出重进；正在生成的回答结束后才同步。API Key和当前设备的模型设置不随同步改变，历史每轮使用的模型快照会保留。
5. 离线时各自继续使用；应用重新打开、网络可连接后自动补齐更新。同一资料两边分别修改会保留两版，请选择后续使用版本；资料选择发生冲突也需本人选择。从同一回答继续的不同问答保留为可切换分支，不把两边上下文混成一段。同步保留未发送问题和编辑草稿。
6. 解除配对会停止交换，双方已保存内容保留；重新连接须重新配对。“解除配对”不表示删除对方副本。删除/导出、完整学习流程、原trial迁入、搜索和跨网中继尚未接入本验证包。

配置模型时，保存兼容OpenAI的HTTPS地址（通常以`/v1`结尾）和模型名称，再输入Key。发送会把问题、选中资料和当前祖先路径内资料版本范围一致的连续成功对话交给该模型。更换资料范围或版本会停止继承旧范围的上下文；失败/停止的回答不作为成功历史传给模型。停止后已收到的部分保留，可继续提问；重开不会自动重发。

卸载或清除应用数据会移除本机记录；Android云备份和系统迁移在验证包中关闭。Windows移动或替换EXE不会删除本机记录。原试用环境不受影响。当前包供本人验证，不是完整Nautilus正式版。

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

当前交付文件与SHA256见[开发状态](../docs/progress/nautilus-development-status.md#验证证据)。程序未签名，Windows可能提示未知发布者。

Windows需要微软C++构建工具、Windows SDK、Rust MSVC stable与WebView2。本机已获许可并安装构建组件；保留既有GNU默认工具链。先完成上述前端及图标生成，再用Windows PowerShell执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "\\wsl.localhost\Ubuntu\home\kingdom\ai_learning\native\scripts\build-windows.ps1"
```

脚本只复制构建输入到 `%LOCALAPPDATA%\NautilusBuild\windows-validation`，用MSVC构建后将EXE放到下载文件夹并输出SHA256。程序直接运行，依赖Windows已安装的WebView2；不是安装向导或商店发布包。数据库保存在 `%LOCALAPPDATA%\com.nautilus.validation\native-validation.sqlite3`，关闭程序或替换EXE不会清除它。重复打开会回到现有窗口，避免第二个进程把正在生成的回答误判为中断。

实际原生检查脚本为 `scripts/smoke-windows.cjs` 和 `scripts/smoke-windows-sync.cjs`，由Windows Node执行，前两个参数为EXE路径和含Playwright的 `frontend` 目录；同步旅程另外需要合成对端地址、端口和临时控制令牌，完整参数见脚本头部。它们用临时数据目录、本机模拟模型及WebView2调试连接检查真实Rust调用、重复启动、取消和重开；不使用真实模型或trial。`NAUTILUS_VALIDATION_DATA_DIR` 仅供Windows隔离测试覆盖保存位置，正常使用无需设置。

Mac/iPhone尚无构建和真机验证资源。共享Rust代码通过检查不等于四平台验收。

### 同步边界与检查

`native/sync`采用固定版本iroh 1.2.0和局域网mDNS发现；显式关闭公共中继、DNS地址发现、网关端口映射及网络探测。加密连接身份与应用层双端配对分开，不以“能连通”当作允许传资料。[iroh构建选项](https://docs.rs/iroh/1.2.0/iroh/endpoint/struct.Builder.html)、[局域网发现](https://docs.rs/iroh-mdns-address-lookup/0.4.0/iroh_mdns_address_lookup/)。Android仅在前台持有组播接收锁，Android17本地网络权限按[官方要求](https://developer.android.com/privacy-and-security/local-network-permission)处理。首版不保证后台/锁屏持续同步或跨网络可达。

业务同步交换缺失的不可变资料版本、已结束的回答和资料选择版本；同一ID不同内容或依赖缺失拒绝整批导入，不覆盖整库，不触发模型重新生成。原数据升级只在明确命令中执行；配对配置保存在本机应用目录，不加入业务同步。

```sh
cd /home/kingdom/ai_learning/native
cargo test -p nautilus-core --test store --test sync_store --test provider
cargo test -p nautilus-sync --lib -- --test-threads=1
```

`sync/examples/synthetic_peer.rs`是实际Windows联调专用的合成对端；只使用新建空的`nautilus-sync-peer-*`目录。它的带临时令牌控制接口只用于测试，不随应用发布，不得指向真实数据。WebView联调脚本参数和准备方法见各脚本头部；所有测试均须使用隔离目录。

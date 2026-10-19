# Omi Windows 控制中心

唯一上位机源码目录为 `Tools/Desktop/`，采用 Tauri 2 + React + Fluent UI React，Python 后台复用 `DeviceBridge` 与 `CodexMonitor`。布局参考 Microsoft WinUI Gallery 的导航、分组设置和自适应设计；没有复制其 XAML 或业务源码。

## 使用与连接

完整解压 `release/OmiPet-Windows-0.2.0.zip` 后运行 `Omi.exe`，保留旁边完整的 `omi-device/`。该目录是内置后台与 Python 环境，不是第二套界面；用户无需安装 Python、Rust 或取得源码。使用步骤见 [QUICK_START.md](QUICK_START.md)。

- 首页“设备连接”统一切换 USB / Wi-Fi。USB 选择与刷新串口；Wi-Fi 选择与刷新已保存设备，只有一台可用设备时自动选中，多台时手选。
- 未确认或重新配对待确认的记录不能从首页直接连接，需通过“配对与设备管理”先验证。首次配对、换网寻址、更新地址与重配也在该页处理。
- 连接后显示实际方式与地址，连接期间禁止切换；断开后可换另一种连接。USB 串口选择与无线地址独立。
- 连接、配对和灯光操作均以设备确认或后台结果为准，点击按钮不代表成功。灯带预览显示编辑值，不是设备最终灯光读回。
- USB 与无线复用本地灯光、Codex 监控和监控灯效页。USB 有效监控优先；语音可立即接管两路监控，旧快照不能抢回。无线界面显示本连接确认状态，不代表跨连接最终输出。
- 本地灯光支持常亮、彩虹、呼吸、跑马、扩散和关闭，RGB/亮度 0–255。监控中禁止手动调灯；语音活动和固件能力不足时按实际错误提示处理。
- 诊断页保留最近 200 条操作结果及通信统计；音频队列、麦克风与看门狗健康只从 USB 日志观测，无线不提供音频健康日志。

换 Wi-Fi 后可先用原凭据查找/更新地址，也可语音开启新配对：说“老鼠狒狒”，听到确认音后说“开启配对模式”，输入屏幕当前 IP 与新码。主动重配需明确勾选，成功后旧凭据失效。普通重启不开窗；五分钟或五次尝试后可再次用语音开窗。需配套固件与 47 词模型，详见 [PAIRING.md](../DeviceBridge/PAIRING.md)。

## 外观、窗口与托盘

品牌和窗口标题为 Omi，应用图标来源见 [icons/README.md](src-tauri/icons/README.md)。侧栏可拖动至 160–320 px，也支持聚焦分隔线后使用方向键、Home/End；小屏使用顶部导航。

设置提供浅色、深色、跟随系统三张预览卡。浅色白底、深色黑底；Windows 标题栏同步切换。偏好保存在本机 `omi.theme`，默认跟随系统；固定主题不受系统切换影响。存储不可用时仍可本次切换。

默认点击 X 隐藏到系统托盘，设备连接与监控继续运行。单击托盘图标或右键“显示主窗口”恢复；右键“退出软件”先释放设备连接，再退出后台、托盘与主程序。设置只保留“关闭窗口时”的隐藏/退出选项，保存在原生配置目录 `window.json`；保存失败保留原选择。托盘创建失败时不隐藏窗口，关闭回退为退出，避免无入口恢复。退出软件不卸载 Codex 采集器。

## 首次监控配置

首次未配置时，首页显示三步向导。完成配置或选择“稍后配置”后记住收起状态，重启不再展开；升级前已经安装的用户也会自动收起，不要求每次启动先收到新事件。偏好保存在本机 `omi.monitorSetup.dismissed`，存储不可用时仍可本次收起。设置页始终保留完整检测、修复/更新与卸载入口；收起向导不表示监控已就绪：

1. 核对运行中的 Codex 程序，或手动选择桌面/CLI 的 `Codex.exe`，安装采集组件。
2. 在 Codex 中审查并信任 Omi Hook；定义变化后按 Codex 提示重新审查。安装不自动授予信任。
3. 让 Codex 执行普通操作，再检测；只有本次安装收到真实事件且宿主关联正常才显示就绪。

安装将运行组件复制到 `%LOCALAPPDATA%/OmiPet/monitor-runtime/<安装ID>/`，与解压目录独立。备份并合并用户级 Hook，保留其他工具配置；可明确识别的旧 Omi Python 入口可迁移，未知或手动修改的入口停止并提示。`CODEX_HOME` 未设置时使用 `~/.codex`。

安装/修复/卸载仅在断开设备且非演示模式时允许。版本化运行目录避免覆盖正在使用的采集器；写入前检查配置外部变更，安装收据保存失败回退原 Hook。卸载只删除清单内哈希匹配的自有文件，保留占用/修改文件、其他 Hook、备份和历史状态。不读写 Codex 内部信任数据库；未收到事件时无法区分未信任与尚未触发。

Codex 更新后若出现来源异常，先核对所选程序是否仍是当前实际运行路径，再修复安装、重新信任并用普通操作验证。升级 Omi 包不会自动替换独立安装的采集器；完整排查、结束仍红的原因及验收步骤见 [更新后排查与本次修复](../CodexMonitor/README.md#codex-更新后排查与本次修复--upgrade-troubleshooting)。

## 监控状态与灯效

- 默认运行红、等待操作黄、完成/空闲绿；来源异常/无事件及会话离线默认绿，协议仍分别保留 unknown、idle、offline，不伪造完成。
- 同一聊天的异步待回复问题不再覆盖实际运行：运行时为 working；当前任务停止但仍有本任务问题待回复时为 waitingApproval；新用户任务接替后，旧问题仍保留记录，但不阻止新任务完成。同步输入与真实权限审批仍优先；不同聊天之间保持等待优先。普通文字或其他工具返回不代表回答了特定问题。
- 监控灯效页可分别修改五种状态的颜色、动效、亮度。设备全局 NVS `omi-monitor/profiles` 保存完整版本，USB/WSS 共用；ACK 确认后提示成功，重启加载后下一次监控沿用。保存不启动监控，也不改变开机本地白光。
- 配置缺失使用默认亮度 16 的红/黄/绿扩散；损坏/未知版本回退默认并记录日志，存储不可用拒绝保存。版本冲突保留编辑并要求重新读取；相同配置不重复写 Flash。不会擦除 Wi-Fi 或配对身份。
- 监控断联、连接租约到期或真正退出监控连接仍关灯，不受五状态灯效配置影响；语音优先。

桌面 `LifecycleReader` 仅接纳近期、事件证明匹配且宿主存活的记录，之后延续同一生命周期。30 秒评估预算、8 秒传输余量、1 秒通信周期、2 秒超时、1 次重试和 5 秒租约保持独立。没有新 Hook 不等于完成；不改写事件原始时间，不允许缓存评估自行续期。快照与宿主证明在同一互斥锁内发布/读取。

进程退出、绑定/身份失效、来源不可读或锁失败会清除延续资格；重开监控不接纳过期历史。旧轮次漏失 Stop/Interrupt 不再永久覆盖新任务的结束。若当前任务也漏失结束事件且尚无新用户任务接替，仍可能保留红/黄；宿主存活不能证明具体聊天运行，当前没有独立逐聊天状态接口，不能承诺绝对精准。异常默认绿也不代表已完成。细节见 [CodexMonitor](../CodexMonitor/README.md)。

## 源码结构与构建

[Tools 分层](../README.md) 按界面、状态来源、设备传输拆分。`App.tsx` 负责导航；`Overview.tsx` 负责首页双连接；`DevicePages.tsx` 负责配对、诊断与设置；灯光、主题、窗口设置和监控向导分别使用独立组件。

Rust 只启动固定相邻路径 `omi-device/omi-device.exe` 并串行转发 JSON；请求与管道读写不阻塞界面。隐藏窗口保留后台，真正退出统一释放设备。原生命令仅接受主窗口调用；原生对话框只用于选择文件/目录，不开放任意程序执行或远程网络接口。

`backend.py` 调用 `controller.py` / `worker.py`，USB/WSS 共用会话初始化与失败释放。配对、验证与寻址使用后台工作线程。`monitor_setup.py` 管安装，冻结后台 `--collect-hook` 经 `hook_runner.py` 调用 `bound_collector.run`，共享原生命周期与宿主关联逻辑。仅保存状态/关联元数据，不保存对话、工具参数或回复；设备传输只发送连接内别名。

构建需要 Node.js、Rust MSVC、Microsoft C++ Build Tools（使用 C++ 的桌面开发）、WebView2、Python 3.10+、CMake、Ninja 和 PlatformIO SDK 的 Mbed TLS 2.28.7 源码。依赖版本由 npm/Cargo 锁文件、原生构建版本检查和 `requirements-build.txt` 管理。

```powershell
cd Tools/Desktop
npm ci
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
npm test
npm run build
./build_windows.ps1 -Python python
```

产物仅为 `release/OmiPet/` 和 `release/OmiPet-Windows-0.2.0.zip`。`src-tauri/target/release/omipet-ui-pilot.exe` 是内部名称，单独拷贝不能运行。`npm run dev` 只在 `127.0.0.1:5173` 预览，浏览器不能操作设备；`Omi.exe --demo` 仅操作模拟设备。Tauri 开发模式需先把 `build/helper/omi-device/` 复制至 `src-tauri/target/debug/`。

打包包含 Python、串口/WSS 依赖及原生 PAKE DLL；许可收集缺失即失败，含所下载的 Rust 构建依赖。依赖来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。缓存、exe/zip、凭据、安装记录和原始日志均不进入 Git；提交、推送和 Release 发布须分别授权。

## 验证现状与边界（2026-10-18）

首页双连接改动通过 30 项前端测试、TypeScript/Vite 与 Windows release 构建；最终顶部标识修改后 17 项首页/App 测试通过。同期桥接 124 项、桌面 Python 36 项、语音词表 4 项与原生窗口设置 2 项通过；这些是对应源码的快照，不是长期或硬件认证。

- 已实测：语音开启配对窗口、屏幕新码/IP、重配提交、重启后绑定及无线调灯；完整 Flash 备份与应用/5 MiB 模型写入校验通过。测试期间出现过一次自动断连，原因未定位。
- 历史证据：2026-10-16 USB 20 ms 隔离版曾完成 30 分钟更新，无新增断线/超时/音频队列/WDT异常；另一轮真实 Hook 已确认黄→红，独立供电下拔 USB 关灯、插回恢复绿。不能扩展为当前固件长期稳定保证。
- 2026-10-19：修复旧轮次持续占用红灯后，用户确认真实运行红、结束绿、异步选项待回复黄及回答后恢复；事件日志与结果一致。本轮没有重新实测真实权限审批。
- 待验：新版首页原生窗口与实机 USB/Wi-Fi 流程、托盘完整实窗操作、五状态配置物理断电持久化、跨连接最终输出及完整灯光读回、重配故障注入与长期稳定性。

设备验收前先枚举串口并避免占用；实际设备需支持相应能力，默认固件不启用桌面协议与无线实验。USB 回归入口：

```powershell
python verify_usb.py --backend build/helper/omi-device/omi-device.exe --port <实际串口> --report <新的报告路径>
```

设备状态 → 握手/能力 → 灯效 ACK → 监控锁灯/语音接管 → 断开释放与实体灯色。检查 `lastLight`、`mode`、`monitorOutput`、`releaseConfirmed`、`replyTimeouts`、`decodeIssues`，以及已观测的 mic、queued/dropped、WDT/panic；物理拔线需独立供电。编译、协议 ACK、模拟故障和实物目视分别记录，不能互相代替。

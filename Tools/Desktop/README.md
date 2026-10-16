# OmiPet Windows 控制中心

Tauri + React + MUI 界面已接入现有 Python USB 控制层。用户已确认独立样机的连续缩放明显流畅；本轮将设备控制迁入该界面，最终原生交互验收仍在进行。当前唯一上位机目录为 `Tools/Desktop/`，旧 Tk 界面已退役。

## 已接入

- USB 串口枚举、刷新、握手、能力检查、断开和关闭释放。
- 本地灯光：颜色、0–255 亮度、常亮/彩虹/呼吸/跑马/扩散/关闭；编辑后点击应用，设备 ACK 才显示成功。
- Codex 监控：延续本次监控中已确认的生命周期状态，持续核对宿主绑定；30 秒预算和 8 秒传输余量用于每次评估的传输有效期。无事件/完成/来源异常绿、运行红、审批或选项等待黄，扩散灯；断联关灯。监控中禁用手动调灯，语音接管后退出监控。
- 通信/音频健康汇总、最近 200 条操作结果、状态目录和绑定文件选择。设置只在断开后修改。
- 无线隔离配对：设备地址、六位码、已保存设备与重连身份验证；后台执行、提交后清空码，收到确认才显示成功。需对应无线隔离固件，实机结果见 [配对实验](../DeviceBridge/PAIRING.md)。无线灯光控制尚未接入。灯带预览是编辑值，不是设备实时读回。

## 结构

`App.tsx` 使用 CSS 响应式布局和 MUI 控件；没有窗口 resize 监听、手动画布重画或缩放延时。`backend.ts` 负责调用和显示事件，按既有 100 ms 界面轮询节奏读取后台结果；一轮完成后才安排下一轮。

Rust 只启动固定相邻路径 `omi-device/omi-device.exe` 并串行转发 JSON。管道读写运行在后台，关闭窗口先等待释放，再销毁窗口。Python `backend.py` 复用同目录的 `worker.py` / `controller.py`、`DeviceBridge`、`CodexMonitor`；未复制设备协议、状态归并、重试、语音接管或租约逻辑。EOF 同样触发原有关闭流程；后台积压时只保留各类最新事件。

监控启动时只接纳近期、事件证明匹配且宿主存活的记录；随后同一生命周期不会因没有新 Hook 而自动变绿。事件原始时间及年龄不改写，每次重新校验产生独立传输评估，缓存评估仍会过期。进程退出、身份变化、绑定失效或来源不可读会清除延续资格。重开监控不会复活过期历史记录。若 `Stop` 丢失而宿主仍存活，可能保留红/黄；宿主存活不能证明具体聊天还在运行，当前没有可靠的逐聊天独立状态校验。

快照与宿主证明现通过采集器原有互斥锁完整发布和读取，避免更新中途短暂降级 unknown；桌面后台和已安装 Hook 包装器须配套更新。来源异常仍按约定显示绿，锁超时也会清除旧状态；没有增加显示宽限或修改事件有效期。2026-10-16 并发回归与 73 项采集、90 项桥接、16 项桌面测试通过；COM17 60 秒 56 次更新均为 working，退出释放确认。此前长测的 3 次 unknown 原因记录不足，本次只确认并修复可复现的读写竞态，长期效果仍待验证。

同日补验：真实 Hook 轮测 55 次更新全部确认，working 44 次、waitingApproval 11 次，未出现 unknown；用户目视确认选项黄灯及回复后恢复红色扩散灯。隔离完成样例的绿色扩散、保持独立供电时拔 USB 关灯、插回恢复绿色也经用户确认；该样例只验证设备显示/断联行为。新版 Windows 构建、338 项许可收集及冻结后台真实模式启动/关闭通过，现有固件未重新烧录。

选项工具归入黄色“等待操作”：同步工具返回后解除；异步工具创建窗口后的立即返回不解除，需收到带对应 `questionItemId` 的用户回复。选项中的自由输入同样处理；普通聊天文字不猜测为某个窗口的回答。只存调用 ID 和数量，不保存问题、选项或回答文本。协议沿用 `waitingApproval` 表示需要用户操作，避免要求更新设备固件。

桌面程序默认使用真实 USB；`OmiPet.exe --demo` 明确启用现有模拟设备。浏览器只预览，禁止设备操作。原生命令只接受主窗口调用，原生对话框仅授予选择文件/目录权限；不开放任意程序执行或远程网络接口。

## 构建和测试

需要 Node.js、Rust MSVC、Microsoft C++ Build Tools“使用 C++ 的桌面开发”、WebView2、Python 3.10+、CMake、Ninja，以及本机 PlatformIO SDK 中的 Mbed TLS 2.28.7 源码。版本由两份锁文件、原生配对构建检查和 `requirements-build.txt` 固定。

```powershell
cd Tools/Desktop
npm ci
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
npm test
npm run build
./build_windows.ps1 -Python python
```

便携包为 `release/OmiPet/OmiPet.exe`，zip 为 `release/OmiPet-Windows-0.2.0.zip`；必须保留旁边的 `omi-device/` 整个目录。包内包含 Python 与串口依赖，不需要用户额外安装 Python。`src-tauri/target/release/omipet-ui-pilot.exe` 是保留的内部构建名称；单独拷贝它不能工作。

`npm run dev` 仅在 `127.0.0.1:5173` 提供界面预览。`npm run tauri dev` 需先将构建出的 `build/helper/omi-device` 目录复制到 `src-tauri/target/debug/`；开发模式也使用同一后台，不引入另一套开发服务器协议。

打包会检查许可文件，缺失时失败。`collect_licenses.py` 收集生产 npm、当前 Cargo 下载源、Python、pyserial、PyInstaller、websocket-client 和 Mbed TLS 许可；输出也包含构建时 Rust 依赖。源码、锁文件、构建脚本和许可可审查；缓存、DLL、exe、zip、诊断和配对数据库不进入 Git。提交/推送仍须用户另行授权。

2026-10-16 无线配对验收：新版便携包中首次六位码配对、设备重启后无新配对码、保存设备的“验证连接”均经用户实测通过。100 项桥接、17 项桌面和 7 项前端测试通过，设备及电脑已持久保存配对。网络负例与固件验证见 [PAIRING.md](../DeviceBridge/PAIRING.md)；无线灯光/监控传输仍待接入，现有控制使用 USB。

## 实机验证

设备状态：运行现有支持 `light`、`monitorLights`、`monitorGreenOff` 的固件，USB 数据线连接，串口未被其他程序占用。端口每次重新枚举，不固定假设 COM17。

```powershell
python verify_usb.py --backend build/helper/omi-device/omi-device.exe --port COM17 --report ../../tmp/tauri-usb-report.json
```

流程：握手 → 六种灯效依次应用（沿用亮度 16）→ 开启监控 → 验证手动灯光被拒绝 → 断开确认监控关闭 → 重连并关闭后台。检查 ACK、`lastLight`、`mode`、`monitorOutput`、`releaseConfirmed`、`replyTimeouts`、`decodeIssues`；健康摘要保留 `mic`、队列和看门狗的已观测信息，不保存原始语音或对话文本。

2026-10-16：冻结后台在 COM17 上 21 项协议检查通过，六种灯效 ACK、监控锁灯、断开/关闭释放均确认，通信超时与解码错误为 0。该结果不能代替目视灯效、语音和原生窗口验收。合并后上位机 15 项测试、界面 6 项交互测试通过；五页在 1160×820 下无内容溢出，800×600 下只在必要页面纵向滚动，无横向溢出。未修改/烧录固件。

2026-10-16 实体倒数第二颗曾出现红色不亮、白色偏青；更换该灯珠并恢复诊断前原应用后，用户确认红、白、黄全部正常。正式 RMT/灯效源码未因诊断改变。原生程序及后台关闭退出曾确认，完整语音接管、监控关闭与断线目视验收仍待补齐。不能把协议检查或单次目视结果扩展为长期稳定保证。

旧 Tk 入口、专用控件、布局测试和 GUI 依赖已移除。保留控制器、工作线程、模拟器及对应测试；用户只启动 `release/OmiPet/OmiPet.exe`，旁边的 `omi-device/` 是内部通信后台，不是另一套上位机。

2026-10-16 生命周期修复：171 项 Python、6 项界面测试及 Windows 打包通过。COM17 实测 60 秒内 56 次 ACK 均为 working，最长约 40 秒无新事件仍保持 working，零超时/解码错误，退出释放确认；另一轮选项窗口有 38 次 waitingApproval ACK 与扩散灯切换日志，但末尾发生 1 次 USB 短断线，随后重连关闭确认。真实选项回复 Hook 已确认待回复数 1→0、状态恢复 working。随后复测 60 秒有 55 次 ACK，确认 working→waitingApproval→working，用户目视确认黄色扩散；零超时/解码错误、link_losses 未新增，关闭释放确认。回复后红色目视尚未单独确认；未修改或烧录固件，USB 长期稳定性仍待查。

界面实现参考：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev/blob/main/src/pages/home.tsx) 的 Tauri/React/MUI 与 Grid、[CC Switch](https://github.com/farion1231/cc-switch/blob/main/src/App.tsx) 的 Flex/滚动布局。没有复制其业务代码。

2026-10-16 USB 修复：桥接器在外部预连接、首轮会话重建后也会重新握手并确认退出释放；88 项桥接、16 项桌面测试及 Windows 打包通过。用户确认并刷入 20 ms 信号过滤隔离固件，30 分钟 1613 次更新全部确认，过滤 9 次短脉冲，无断线/重连/超时/解码/音频队列/WDT异常，关闭释放确认。新鲜度、1 秒周期、2 秒超时、1 次重试和 5 秒租约未改。另有 3 次临时 `unknown` 尚未定位；来源异常按约定仍显示绿，不能据此宣称红绿状态完全稳定，目视及物理拔线待补。日志/镜像/回退只留本地，原始模型与词表 7 个文件内容哈希与备份一致。

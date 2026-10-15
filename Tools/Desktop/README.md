# OmiPet Windows 控制台

用户已确认 Windows 桌面程序，主模式为“本地灯光 / Codex 监控”。新版采用浅色侧栏、卡片概览、圆形颜色预设、六个灯效选项及亮度百分比；用户认可预览方向。控制模式为纵向开关行，二者互斥，设备确认后显示选中；新增模式可扩展 `MODES` 定义，控制器和能力检查仍须同步实现。**监控模式禁止上位机手动调灯**，先切回本地再应用设置，语音继续优先。

灯光摘要使用 10 磅字体和上下留白，宽度不足时换行。卡片按内容申请高度，内容区支持滚动，避免较大系统字体下裁切；概览灯带示意随尺寸变化重新绘制。0.3 源码测试覆盖 100%/125%/150% 对应的 Tk 字体缩放、文字/开关边界、滚动到底和互斥模式选择；这不替代用户实际显示器上的目视验收。提交及隐私排除规则见根目录 `CONTRIBUTING.md`。

## 启动

0.3 修正版位于 `Tools/Desktop/dist/OmiPet-0-3/OmiPet-0-3.exe`；整个 `OmiPet-0-3` 目录一起保留，直接双击 exe，无需另装 Python。它与正在运行的旧版分开打包，切换前请自行在旧窗口断开设备，避免占用同一串口。默认打包命令仍输出 `dist/OmiPet/OmiPet.exe`；独立版本使用 `build_windows.ps1 -Name OmiPet-0-3`。

已有 Python 3 与 Tkinter 时，安装 `requirements.txt` 后双击 `Launch OmiPet.cmd`，或运行：

```powershell
python Tools/Desktop/app.py
python Tools/Desktop/app.py --demo
```

演示模式不打开串口、不写设备；标题和提示明确标记演示。USB 页列出实际端口，单个端口时预选，多端口时由用户选择。连接后握手读取能力；旧固件没有 `light` 命令时，手动灯光控件禁用。

## 当前功能与边界

| 功能 | 实现 |
|---|---|
| USB 连接、断开 | 单独工作线程持有串口；监控退出发断联释放并关灯，本地退出保留本地灯光 |
| 本地 / Codex 监控 | 本地等待设备确认 release；监控复用已有 Hook 绑定、有效期挑战和桥接 |
| 颜色、亮度、灯效 | 本地模式显式点击应用；RGB 与亮度 0–255，常亮/彩虹/呼吸/跑马/扩散/关闭 |
| 手动控制互斥 | 界面和控制器禁止监控中手动调灯，支持的固件再次检查监控/唤醒状态 |
| 诊断 | 已确认协议模式、最后收到的监控显示状态、USB 超时/解码统计与麦克风日志观测 |
| 配对页 | 显示已确认规则与未就绪提示；无线认证运行入口未完成，提交禁用 |
| 设置 | 选择现有 Hook 状态目录及 host-bindings.json；连接时生效，不保存密钥或配对码 |

灯光控件和 13 灯示意显示**本次编辑值**，不是设备实时读回；语音仍可随后改灯。ACK 表示设备协议已接受设置，不能替代目视、电气或完整 UI 操作验证。监控按钮要求 `monitorLights=true` 和 `monitorGreenOff=true`，旧固件缺少能力时提示更新。温湿度、电池、屏幕配置、语音管理、配网管理、无线配对和 WSS 传输仍需设备能力接入，不能宣称“一切功能”已完成。旧界面暂以 `--legacy` 保留用于比较。

串口由工作线程独占；模式切换、调灯和释放不并发发送。发送超时后的连接恢复不会自动重发手动灯光。沿用已批准的 4096 字节/16 会话、1 秒更新、2 秒超时、1 次重试、30 秒观测有效期、8 秒传输预留和 5 秒连接租约；没有新阈值。界面连接状态代表串口工作线程，通信异常会显示等待恢复。

## 已确认监控灯规则

| 情况 | 灯带 |
|---|---|
| 无事件、完成、空闲 | 绿色扩散 |
| 工作中 | 红色扩散 |
| 待审批 | 黄色扩散，优先于工作 |
| 来源异常、未知、过期 | 绿色扩散；协议仍记录 unknown，不伪造完成 |
| 监控连接断开 | 关灯；主动断开即释放，异常断联由链路检测或现有租约判定 |
| 主动切本地 | 恢复保存的本地灯效 |
| 语音唤醒 | 退出监控，白色跑马提示，指令继续控制本地灯光 |

断联熄灯状态跨探测/握手保持，避免白光闪回；新监控快照恢复监控。手动点连接默认进入本地模式。语音接管后，后续关闭监控连接不会熄灭语音灯光。

## 固件能力

`light` 只在 `OMIPET_DESKTOP_CONTROL=1` 的 USB 隔离构建公布，稳定配置默认关闭。正文为 `effect/red/green/blue/brightness`；RGB 与底层亮度仍为 0–255，界面换算百分比。设备拒绝未知字段、非法值、监控模式、唤醒等待及同轮语音动作时的设置；同序号重试不增加修订号。颜色和模式一次更新后只绘一帧，复用原动画时序。设置没有 Flash 持久化，重启沿用启动灯光。

绿色回退/断联关灯使用独立 `OMIPET_MONITOR_GREEN_OFF=1`，依赖监控灯开关。ACK 增加 `monitorOutput` 区分 local/connected/disconnected。主动本地使用空正文 release；监控退出使用严格的 `release {"disconnect":true}`。旧构建路径保留，稳定配置没有启用这些开关。

## 开发验证与打包

```powershell
python -m unittest discover -s Tools/Desktop/tests
python Tools/Desktop/app.py --demo --smoke-test
python -m unittest discover -s Tools/DeviceBridge/tests
```

安装 `requirements-build.txt` 后运行 `Tools/Desktop/build_windows.ps1`，输出 `Tools/Desktop/dist/OmiPet/OmiPet.exe` 与其同目录依赖。本次构建使用 Python 3.10.10、PyInstaller 6.22.3。应整体分发该目录，不单独移动 exe。构建目录被 Git 忽略。无线配对完成前不要把六位码发送给未经认证的服务。

## 2026-10-15 验证与交接

本阶段修改 `Tools/Desktop/`、协议核心/实验适配器、`main.cpp` 和 LED 配置接口，以及相关测试/文档。目标是先完成 Windows USB 本地灯光与监控控制；无线配对与其余设备管理仍是未完成工作。

上次设备交付时 11 项上位机、85 项桥接及原生 ASan/UBSan 检查通过。0.3 界面修正后上位机测试增至 13 项，另有 3 项提交检查器测试；包含五页最小 1060×780 窗口内容尺寸及全部调灯控件锁定。隔离固件仍为 RAM 66,512、Flash 1,549,097 字节，模型 5 MiB；配置 `protocol-monitor-green-off.ini`，构建日志 `green-off-firmware-build-20261015.log`，均在 `tmp/codex-monitor-probe/`。本轮稳定配置重新构建通过，RAM 57,896、Flash 1,532,693；未改稳定开关、未重新刷写设备。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：COM17（303A:1001，唯一序列号仅保留本地收据），备份此前已安装版五镜像并按收据校验后烧录，新版五次写入哈希验证通过。运行 `tests/verify_monitor_policy_usb.py`：空来源→合成工作/审批/空闲→来源抛错→主动断开→握手→停止心跳至原租约到期→重连→主动本地。预期 ACK 输出 connected/disconnected/local 及 `[LED] owner=monitor effect=center_expand status=...`、`owner=off reason=monitor-disconnected`、`owner=local reason=fallback`。15 项检查通过，捕获两次关灯、7 次监控转换和一次本地恢复；0 超时/解码错误，38 个音频样本无积压/WDT，mic=ok，最大往返 16 ms。报告 `green-off-usb-20261015.json`。这是合成状态和设备日志验证，不代表全桌面真实状态、物理拔线或肉眼灯色验收。

随后 `tests/verify_usb.py --exercise-lights` 覆盖六种本地灯效、监控中拒绝手动、退出后恢复，8 条日志按修订 1–8 连续完整，0 超时/解码错误，26 个音频样本无积压/WDT，最大往返 32 ms。最终设备本地白色常亮 16、租约释放、串口关闭；报告 `modern-desktop-usb-20261015.json`。此前首轮缺一条日志未复现，原因仍未确定；同轮语音优先有原生检查，真人同时操作仍待验证。

最新设备安装收据 `firmware-green-off-install-20261015.json`，回退目录 `usb-rollback-before-green-off-20261015/`；均在 `tmp/codex-monitor-probe/`。上次默认 exe 和完整 Windows zip 已打包，演示冒烟检查通过。上次 computer-use 捕获重试后仍报 `FrameArrived timed out: timed out waiting on channel`；随后用户按 Escape 停止界面操作。用户认可预览方向，但这不构成截图审查通过。以上为此前设备验收记录，提交情况以 Git 历史为准。

本轮先将现有源码按规则、采集、配对基础、USB 桥接、上位机五个功能批次分别提交和推送，再独立修正 0.3 界面。`dist/OmiPet-0-3/` 与 `OmiPet-Windows-0.3.zip` 留本地，不上传 Git 或 Release。可从暂存树导出干净源码验证，避免本机忽略文件掩盖依赖缺失。下一步仍是用户核验摘要字号、纵向开关及新版断联灯效；无线和完整设备读回未接入。

# OmiPet Windows 控制台

用户已确认 Windows 桌面程序，主模式为“本地灯光 / Codex 监控”。新版采用浅色侧栏、卡片概览、圆形颜色预设、六个灯效选项及亮度百分比；用户认可预览方向。控制模式为纵向开关行，二者互斥，设备确认后显示选中；新增模式可扩展 `MODES` 定义，控制器和能力检查仍须同步实现。**监控模式禁止上位机手动调灯**，先切回本地再应用设置，语音继续优先。

0.5 使用 [CustomTkinter 5.2.2](https://github.com/TomSchimansky/CustomTkinter) 的圆角卡片、按钮、开关、细滚动条和亮度滑条。亮度滑条为圆形滑块、圆角滑轨，监控/未连接时禁用并变灰，保留 0–255 整数范围及百分比显示；拖动只编辑，点击应用才发送。色值按钮的文本变量也已修复。库采用 MIT 许可，依赖和字体声明见 `THIRD_PARTY_NOTICES.md`；打包保留字体、主题及许可文件。保留现有 Tk 布局和业务控制器，库自动 DPI 缩放关闭，字体按现有 Tk 缩放换算。0.4、0.3 安装包及提交 `0744e03` 保留回退。

灯光摘要保持 10 磅字体和留白，宽度不足时换行；卡片按内容申请高度。滚动条仅在内容溢出时出现，无箭头、无凹槽，隐藏时归还占位并回到顶部；缩放窗口或换页后重新判断。默认 1160×820、100% 字体缩放下五页均能容纳且隐藏滚动条；较大字体或小窗口允许滚动。测试覆盖 100%/125%/150% 对应的 Tk 字体缩放、摘要/开关边界、滚动到底、溢出切换及设备确认后的互斥模式选择。几何与组件测试不替代实际显示器目视验收。提交及隐私规则见根目录 `CONTRIBUTING.md`。

## 启动

0.5 位于 `Tools/Desktop/dist/OmiPet-0-5/OmiPet-0-5.exe`；整个 `OmiPet-0-5` 目录一起保留，双击 exe，无需另装 Python。与旧版分开打包，切换前请在旧窗口断开设备，避免占用同一串口。默认打包命令仍输出 `dist/OmiPet/OmiPet.exe`；独立版本使用 `build_windows.ps1 -Name OmiPet-0-5`。

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

此前源码按五个功能批次及 0.3 界面修正共六批推送至 `0744e03`。0.4/0.5 后续改动按提交规则、依赖与许可、圆角控件与滚动条、亮度滑条、重绘优化五批发布，具体提交号以 Git 历史为准；每批相关检查及干净源码导出测试通过，最终 17 项上位机测试通过，含亮度范围/百分比/发送值、禁用保护、色值文本、重复状态不重绘无关按钮以及状态改变后仍正确锁定。本轮未改通信周期、超时、重试或固件，未刷机。安装包、原始报告、收据和本地配置按 `CONTRIBUTING.md` 留本地。下一步用户核验滑条与操作流畅度；无线和完整设备读回未接入。

库控件封装在 `styled_widgets.py`，页面继续由 `modern_ui.py` 编排。本地证据：`tmp/codex-monitor-probe/desktop-styled-build-20261015.log`、`desktop-styled-package-20261015.json`；15 项测试、打包 exe 演示启动、主题/圆角字体/许可资源和 zip 完整性检查通过。无本轮截图或人工验收记录，旧程序及串口连接未操作。

0.5 修正 UI 重绘：控件可用性/模式相同则跳过控件更新；按钮样式、状态区和预览只在可见内容变化时重绘，亮度回调仅更新百分比/摘要。串口仍在原工作线程处理，1 秒通信周期与 100 ms UI 队列轮询未改。本机离线同步回调测量（不含窗口事件循环、设备或屏幕延迟）：20 次未变化状态刷新中位数约 251.17→0.0015 ms，按钮绘制 900→0；40 次亮度回调约 27.12→3.58 ms，按钮绘制 240→0。后者包含变量驱动的新滑条自身绘制，不能当作整体帧率或实机响应保证。原始数据 `tmp/codex-monitor-probe/desktop-ui-before-20261015.json`、`desktop-ui-after-20261015.json`；0.5 构建/包记录为 `desktop-responsive-build-20261015.log`、`desktop-responsive-package-20261015.json`。下一步人工确认流畅度。

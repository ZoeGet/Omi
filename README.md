<div align="center">

<h1>Omi | 桌面伙伴</h1>

<h3>让桌面多一点陪伴，让任务进度看得见。</h3>

<p>离线中文语音 · 环境显示 · 灯光控制 · Codex 任务状态监控</p>

<p><em>An experimental ESP32-S3 desktop companion with offline Chinese voice commands,<br>environmental sensing, lighting, and a Windows app for Codex task monitoring.</em></p>

<p>
  <a href="https://github.com/ZoeGet/Omi/releases/tag/v1.0.1"><img src="https://img.shields.io/badge/version-v1.0.1-blue" alt="Windows 软件版本 v1.0.1"></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="桌面软件平台 Windows">
  <img src="https://img.shields.io/badge/hardware-ESP32--S3-orange" alt="硬件 ESP32-S3">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0-green" alt="软件许可 GPL-2.0"></a>
  <img src="https://img.shields.io/badge/status-Prototype-yellow" alt="原型开发阶段">
</p>

<p>
  <a href="https://github.com/ZoeGet/Omi/releases">下载 Windows 软件</a> ·
  <a href="Tools/Desktop/QUICK_START.md">使用指南</a> ·
  <a href="#可以做什么--features">功能介绍</a> ·
  <a href="Firmware/README.md">固件开发</a> ·
  <a href="#硬件资料--hardware-resources">硬件资料</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a>
</p>

</div>

---

**项目处于原型开发阶段。** 基础硬件和语音已有实测，桌面/无线功能需要配套的隔离固件；长期稳定性与部分异常边界仍待验证。语音采用有限词表，不支持开放域对话、云端语音或 TTS。

## 可以做什么 / Features

| 功能 | 当前支持与条件 |
| --- | --- |
| 桌面显示 | NV3007 横屏界面、温湿度、电池估算电量；联网且 NTP 同步后显示时间，断网显示占位符 |
| 离线语音 | “老鼠狒狒”进入监听，再说亮度、颜色或灯效指令；无需 Wi-Fi |
| 灯光 | 13 颗 WS2812B，常亮、彩虹、呼吸、往返跑马、中心扩散及关闭 |
| Windows 控制 | USB/Wi-Fi 连接、本地调灯、配对/重配、主题与托盘；需支持桌面协议的固件 |
| Codex 监控 | 通过本机 Hook 观察运行与等待等状态，以灯光和最多四张任务卡显示；需安装并信任监控组件及配套固件 |
| 无线配对 | 设备联网后语音开启限时六位码窗口；日常连接校验已保存身份，首次配对无需 USB |

“老鼠狒狒”是 ESP-SR v1.2.0 中文 MultiNet `mn6_cn` 中的自定义命令入口，**不是定制 WakeNet 模型**。当前包含 47 条短语、命令 ID 1–17；误唤醒率、漏识别率和长期延迟分布尚未完成统计。实现与修改词表的方法见[固件文档](Firmware/README.md#语音技术栈与唤醒词架构--voice-stack-and-wake-phrase-architecture)。

## 开始使用 / Getting started

### 已有 Omi 设备

1. 在 [Releases](https://github.com/ZoeGet/Omi/releases) 的 **Assets** 中下载 `Omi-Windows-1.0.1.zip`，完整解压后运行 `Omi/Omi.exe`；保留相邻的 `omi-device` 文件夹和许可文件。
2. 需要 Windows x64 和 WebView2 Runtime。便携包内置后台，无需安装 Python、Rust 或 PlatformIO；任务监控还需要本机 Codex。
3. 按[使用指南](Tools/Desktop/QUICK_START.md)连接设备、调灯或配置监控。软件不包含固件镜像，也不会自动升级设备。

**设备必须支持相应协议。** 默认固件关闭 USB 桌面协议与无线服务；只下载 Windows 软件或刷默认固件，不能获得桌面连接和任务屏功能。开发者应按[隔离构建说明](Tools/DeviceBridge/README.md#构建与验证)构建对应版本。

### 从源码开发

```powershell
git clone --recurse-submodules https://github.com/ZoeGet/Omi.git
cd Omi
pio run -d Firmware -e esp32-s3-devkitc-1
```

以上命令需要先安装 PlatformIO，构建的是默认固件，不会刷机。已克隆但未初始化子模块时运行 `git submodule update --init --recursive`。固件采用 Arduino + ESP-IDF，Espressif32 固定为 6.12.0；完整工具链、引脚与烧录步骤见[固件开发](Firmware/README.md)。Windows 开发依赖和打包步骤见[桌面开发文档](Tools/Desktop/README.md#源码结构与构建)。

### 版本与下载源码

V1.0.1 的 Windows 包对应 [`v1.0.1` 标签](https://github.com/ZoeGet/Omi/tree/v1.0.1)，包内 `SOURCE_VERSION.txt` 记录完整提交号；变更与升级步骤见 [V1.0.1 发布说明](Tools/Desktop/RELEASE_NOTES_V1.0.1.md)。

V1.0 的更新便携包对应源码 `b09d6e4`，原 `v1.0.0` 标签仍指向首发提交 `4520425`；复现该更新包应使用 [b09d6e4 源码快照](https://github.com/ZoeGet/Omi/tree/b09d6e4c4a67d39e20379c929cb9782289e35c0d)，不要把 Release 自动生成的 Source code 当作更新后的源码。该历史差异也写在 Release 页面；后续发布使用与对应源码一致的新版本标签。

## 监控状态与隐私 / Monitoring and privacy

默认运行红、等待操作黄、完成/空闲绿；五种状态的颜色、亮度与灯效可以配置。**来源异常也可能显示绿色，绿色本身不证明任务完成。** 监控断联或租约结束关灯，语音优先；本地灯光模式可手动调灯。设备确认 ACK 表示收到命令，不等于实时物理灯光读回。

监控依赖已收到的 Hook 与宿主关联。漏失结束事件时可能保留旧状态；没有新事件也不证明空闲或完成。完整状态规则与升级排查见[CodexMonitor](Tools/CodexMonitor/README.md)。

开启任务屏后，软件会读取本机标题索引，把**可识读的聊天标题位图发送到 Omi 设备并显示**。不传聊天正文、提示词、工具参数或回复正文；采集器仍会在本地保存会话/轮次/调用标识、工作目录、事件和宿主关联等元数据。这些信息及配对凭据应留在本机，不要随 Issue 或仓库公开。协议边界见[任务屏说明](Tools/DeviceBridge/README.md#业务快照--business-snapshots)。

### 监控会话数量限制

| 范围 | 限制 |
| --- | --- |
| 设备屏幕 | 最多四张活动任务卡；超过四个提示额外数量 |
| 当前设备监控视图 | 最多 16 条会话，包含运行、等待、未知及保留的最新结束记录；真正超限会报来源异常 |
| 累计聊天与磁盘历史 | 未设固定数量上限，也没有自动裁剪；仍受电脑存储、内存与处理时间限制 |

累计到第 17 个历史聊天不会直接停止监控；已接纳的运行/等待不会因静默而丢弃。详见[历史容量排查](Tools/CodexMonitor/README.md#历史聊天超过设备容量导致来源异常)。仅由电脑发送汇总状态以取消设备会话上限尚未实现。

为兼容已有安装，本机数据目录及部分内部标识沿用 `OmiPet`，无需改名或删除。

## 硬件资料 / Hardware Resources

已验证硬件为自制 **ESP32-S3-WROOM-1-N16R8** 板：16 MB Flash、8 MB OPI PSRAM、NV3007 `142×428` LCD、AHT20、13 颗 WS2812B-2020-V6、ICS-43434 与无源蜂鸣器。其他 ESP32-S3 板需要核对引脚、内存模式、外设与供电，不能直接按开发板名称判断兼容。

| 已公开资料 | 用途 |
| --- | --- |
| [原理图 PDF](Hardware/Schematic/Omi_Schematic.pdf) | 查看电路连接 |
| [焊接完成照片](Hardware/Images/Welding.jpg) | 查看原型实物，照片不代表完整装配指南 |
| [前壳 STEP](Hardware/Enclosure/Frontcover.STEP)、[后壳 STEP](Hardware/Enclosure/Backcover.STEP) | 查看外壳模型，装配与加工尺寸需自行复核 |

当前仓库**未提供 PCB 编辑工程、Gerber、完整 BOM 和装配指南**，硬件资料还不足以直接生产整机。厂家原始 LCD 资料未随仓库分发；已有驱动及初始化代码位于 `Firmware/lib/NV3007_Display/`。

<details>
<summary>查看原型焊接照片</summary>

<img src="Hardware/Images/Welding.jpg" alt="Omi 原型 PCB 正反面焊接照片" width="520">

</details>

## 验证范围与待办 / Validation and next steps

- 已有实测：显示、温湿度、I²S 采集、有限词表语音调灯、语音配对/重配和无线调灯。任务屏已通过短时演示与区域刷新目视检查。
- 历史 USB 隔离版完成过 30 分钟连续更新检查；后续重配测试仍出现一次原因未定位的自动断连，不能把旧版本长测视作当前固件长期保证。
- Windows V1.0 已有界面/后台测试、构建和模拟重连验证；真实拔插、断网恢复、托盘完整操作与不同电脑兼容性仍待验。
- 待验：五状态 NVS 配置的物理断电持久化、跨连接最终输出、重配故障注入、语音误识别与长期并行稳定性。
- 电池百分比尚未按实测放电曲线校准；电池供电下曾报告联网后灯带随机闪烁，原因未定位。灯带低电量供电裕量、背光电流/温升等硬件条件需独立验证。

## 目录与贡献 / Repository and contributions

| 目录 | 内容 |
| --- | --- |
| [Firmware](Firmware/README.md) | PlatformIO 固件、本地驱动、ESP-SR 子模块与模型生成 |
| [Hardware](Hardware/) | 原理图、原型照片和 STEP 外壳 |
| [Tools/Desktop](Tools/Desktop/README.md) | Windows 界面、后台与便携包构建 |
| [Tools/CodexMonitor](Tools/CodexMonitor/README.md) | Hook 采集、宿主关联和状态判断 |
| [Tools/DeviceBridge](Tools/DeviceBridge/README.md) | USB/WSS 协议、配对、模拟及验证工具 |
| [Tools/Repository](Tools/Repository/) | 源码发布检查 |

欢迎通过 Issue 报告问题或提交 Pull Request。请提供版本、设备/环境、复现步骤与预期结果，并对日志脱敏。测试、注释格式和提交范围见[贡献指南](CONTRIBUTING.md)。

## 许可与素材 / License and assets

项目软件许可见 [GPL-2.0 LICENSE](LICENSE)。第三方组件保留各自许可，桌面组件详见[第三方说明](Tools/Desktop/THIRD_PARTY_NOTICES.md)。硬件资料的公开范围见上表；角色图案和应用图标涉及第三方形象，不应据软件许可推定其形象已获授权，当前仓库未附该形象的再分发授权文件，来源与限制见[图标说明](Tools/Desktop/src-tauri/icons/README.md)。

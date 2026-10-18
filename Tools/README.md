# Windows 上位机工具

开发源码按职责分层，发布时交付一个完整 Windows 压缩包。

| 目录 | 职责 | 依赖方向 |
|---|---|---|
| `Desktop/` | Tauri/React 界面、Python 后台、首次监控配置、Windows 打包 | 调用 DeviceBridge 和 CodexMonitor |
| `CodexMonitor/` | Hook 生命周期采集、进程关联、状态读取和诊断 | 不依赖界面或设备传输 |
| `DeviceBridge/` | 协议、USB/WSS、配对和设备会话 | 读取 CodexMonitor 状态 |
| `Repository/` | 源码发布检查 | 开发时运行 |

各模块的 `tests/` 是开发验证源码，不要求用户运行。缓存、测试报告、构建目录、安装收据和本机凭证都不随源码发布。

开发构建入口是 `Desktop/build_windows.ps1`；输出 `Desktop/release/OmiPet-Windows-0.2.0.zip`。首页统一选择 USB 串口或已配对 Wi-Fi 设备；配对管理处理首次配对、换网寻址与语音重配。用户完整解压后运行 `Omi.exe`，旁边的 `omi-device/` 是内部后台及内置 Python 环境，不是第二套界面。

后台同一个可执行文件兼任短时 Hook 入口（`--collect-hook`），复用现有采集和关联逻辑。首次配置将运行环境复制到用户数据目录的独立版本目录，再备份并合并用户级 Hook。安装和修复不自动授予 Hook 信任，也不自动启动设备监控；移除接入只处理有安装记录且未修改的自有组件。

使用步骤见 [QUICK_START.md](Desktop/QUICK_START.md)，构建及验证见 [Desktop/README.md](Desktop/README.md)。源代码分层不需要与最终用户看到的发布包目录一一对应。

仓库忽略的 `tmp/` 不全是可丢弃缓存：本机还存放完整 Flash 备份、回退镜像、隔离固件配置和构建环境。清理前先转存所需备份/配置；原始诊断可按需保留，删除后不能从 Git 恢复。正常安装的采集组件与配对凭据位于用户数据目录，不在源码 `tmp/` 中。

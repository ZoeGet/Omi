# 无线配对隔离实验

2026-10-16：已接入设备 WSS 配对服务、上位机六位码输入、双方确认、凭据持久化和重连身份验证。源码和构建验证不等于实机验收；当前实验不承载无线灯光/监控命令，控制继续使用 USB。稳定构建默认关闭服务。

已确认产品规则：同一局域网；屏幕六位随机数字码，5 分钟有效、最多 5 次错误；仅尚未配对时重启自动开放。目标是防局域网冒充，尚未开启 Flash/NVS 加密，不执行不可逆 eFuse 设置。USB/Wi-Fi 仲裁在后续传输层集成，语音始终优先。

已确认参数：WSS `8443`、最多 1 个无线客户端、TLS/配对步骤 10 秒、日常 I/O 2 秒、4096 字节完整文本帧、每轮密码交换最多 1024 字节。TLS DER 证书/私钥缓冲分别 1024/256 字节，证书日期固定为 2026-01-01 至 2050-01-01；配对后以完整证书 SHA-256 指纹验证身份。服务沿用 ESP-IDF 默认优先级，栈 10 KB。

`Firmware/src/wireless_pairing.cpp` 使用 ESP-IDF HTTP/WebSocket 服务和 Mbed TLS TLS 1.2 传输回调，绝对截止时间限制握手；主循环不运行密码交换，只更新屏幕和连接截止时间。仅设备联网后启动一次，屏幕显示六位码、倒计时和 IPv4 地址；失联时关闭连接并隐藏码，期限不重新开始。每次有效配对尝试均计数，中断也消耗一次；验证失败不签发凭据。已有/损坏的 NVS 身份不覆盖、不擦除。

`pairing_exchange.h` 是 Windows 和 ESP32 共用的有序 EC J-PAKE 实现；Windows 通过 `native/pake.cpp` 的小型 DLL 调用本机 SDK 内 Mbed TLS 2.28.7，未修改上游源文件。密码证明绑定四轮消息、角色和本次 TLS 证书指纹；六位码不直接发送到网络，也不使用六位码的普通哈希替代 PAKE。TLS 首次连接的证书只有在 PAKE 确认后才可信，失败不能进入日常认证。

提交顺序：双方完成密码证明 → 电脑先持久保存 pending 凭据 → 设备验证提交证明并保存/读回 NVS → 返回提交证明 → 电脑标记 confirmed。确认包丢失时点击“验证连接”，使用已保存的密钥和指纹恢复。设备保存失败时，可在仍有效的窗口内重新配对；仅同一证书下、未 confirmed 的候选凭据可更新。confirmed 身份永不自动替换。设备重启后凭据未知或身份不匹配均拒绝开放配对。

日常验证使用双方新随机数和已有双向 HMAC 门禁。电脑在发送应用消息之前校验证书指纹。凭据保存在当前用户 `%LOCALAPPDATA%/OmiPet/pairing.sqlite3`；不记录配对码/密钥/原始网络错误，不上传凭据。当前按地址查找设备，DHCP 地址变化的迁移、撤销/重置配对和无线灯光控制尚未接入。

验证入口：

```powershell
python -m unittest discover -s Tools/DeviceBridge/tests -p 'test_pairing*.py'
python Tools/DeviceBridge/native/build_windows.py
python -m unittest discover -s Tools/DeviceBridge/tests -p 'test_wireless_pairing.py'
python Tools/DeviceBridge/tests/run_pairing_crypto_probe.py --mbedtls-dir <本机MbedTLS源码目录> --wsl-distro <已安装发行版> --report tmp/pairing-probe.json
```

原生构建需要 CMake、Ninja 和 Microsoft C++ Build Tools，默认读取 PlatformIO 安装的 Mbed TLS 2.28.7 源；可通过 `--source` 指定同版本来源。源码版本、许可证随便携包记录，不把 DLL/构建目录加入 Git。真实配对码、私钥、凭据、备份和设备日志只留本地。

隔离固件由 `tests/create_experiment_config.py --wireless-pairing` 生成，其他 USB 参数按已批准值显式传入。配置、SDK defaults 与 sdkconfig 放在输出配置旁，必须在可丢弃的 `.pio` 构建目录外；避免 PlatformIO 首次清理缓存时清掉实验配置。生成不自动构建或烧录。已有 20 ms USB 过滤、语音和灯光逻辑沿用，不改变 GPIO、词表、模型或 eFuse。

实机验收：设备接 USB 且独立供电 → 备份当前完整 Flash 并校验摘要 → 烧录隔离应用及原 5 MiB 模型 → 检查 `[PAIR] ready=1 paired=0 ip=… port=8443`、`mic`、`queued/dropped`、`task_wdt` → 用户在上位机输入屏幕地址/码 → 检查 `[PAIR] committed=1` 和成功回执 → 断开/重启后“验证连接”，确认不重新显示码。

2026-10-16 实测：COM17 完整 16 MiB 备份逐块及整体 MD5 校验通过；隔离固件五个写入镜像校验通过。用户确认首次配对成功，重启后不再显示码且上位机验证成功；设备日志由 `paired=0`、`committed=1` 变为重启后的 `paired=1`。错误证书在应用消息发送前拒绝，错误日常密钥被设备关闭连接，随后正确凭据仍可认证；不发送 TLS 握手的连接在 10.01 秒被关闭，之后服务恢复。首次配对期间 101 条音频记录的 queued/dropped 均为 0，无看门狗/崩溃日志。100 项桥接、17 项桌面、7 项前端测试及隔离/默认固件构建通过；新版便携包已更新。

尚需实机核验错码、5 次锁定、5 分钟过期、断网、最后确认丢失及 NVS 写入失败；模拟失败测试不能替代实机断电/故障注入。短测不代表长期音频/无线稳定性。私有备份和日志只保存在被忽略的 `tmp/wireless-pairing-20261016/`。

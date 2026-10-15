# 无线配对基础模块

当前仅为隔离基础模块及离线验证，尚无网络服务、TLS/WSS 运行接入或自动凭证签发。设备当前不会因这些源码开启配对，也不会写入真实密钥。完整历史验证边界见同目录 README。

已确认产品规则：同一局域网；屏幕六位随机数字码，5 分钟有效、最多 5 次错误；仅尚未配对时重启自动开放。目标是防局域网冒充，尚未开启 Flash/NVS 加密，不执行不可逆 eFuse 设置。USB/Wi-Fi 仲裁在后续传输层集成，语音始终优先。

已实现代码：配对窗口与启动门禁、PAKE 相关密钥派生和双向证明、101 字节凭证记录、一次性文件/NVS 保存、设备 TLS 身份生成/校验/NVS 保存，以及 LCD 配对码显示接口。损坏或无法确认的身份为 unknown；不覆盖已有身份、不擦除 NVS，不把校验摘要当成物理篡改防护。

验证入口：

```powershell
python -m unittest discover -s Tools/DeviceBridge/tests -p 'test_pairing*.py'
python Tools/DeviceBridge/tests/run_pairing_crypto_probe.py --mbedtls-dir <本机MbedTLS源码目录> --wsl-distro <已安装发行版> --report tmp/pairing-probe.json
```

测试只生成临时身份，源码中的顺序字节为公开合成向量。真实配对码、证书私钥、凭证记录和本机路径不得提交。密码原语/NVS 模拟检查不替代设备断电验证或完整无线认证；可信随机源、时间与容量参数、配对确认后的两端提交和 TLS/WSS 连接门禁仍须后续接入。

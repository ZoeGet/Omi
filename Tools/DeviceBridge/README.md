# OmiPet 共用通信协议

本目录提供 USB/WSS 共用协议、状态桥接、模拟器和验证工具。用户使用的唯一桌面入口见 [Tools/Desktop](../Desktop/README.md)。隔离实验已支持六位码配对、凭据保存、重连认证及无线灯光/监控；实现和验证边界见 [PAIRING.md](PAIRING.md)。

| 文件 | 职责 |
| --- | --- |
| `protocol.py` | 有界解码、信封/快照校验、会话别名及有效期转换 |
| `simulator.py`、`demo.py` | 无设备模拟与重试/过期验证 |
| `usb_client.py`、`bridge.py` | USB 确认/重连和真实 Hook 状态桥接 |
| `wss_stream.py` | 已认证 WSS 字节流适配，复用原有确认、重试及状态桥接 |
| `verify_usb.py`、`verify_challenge.py`、`verify_fallback.py`、`verify_lights.py` | 分层实机协议检查；不能代替目视验收 |
| `tests/` | Python 回归、原固件 C++ 原生检查、隔离构建配置生成 |

## 当前行为与验证边界

当前设备已升级语音重配隔离固件及配套模型，保留 20 ms USB 过滤，并支持 USB/WSS 手动灯光、五状态可配置监控灯效及语音优先。默认来源未知/无事件/完成绿、工作红、待操作黄；监控断联或租约结束关灯，不受灯效配置影响。换珠后默认红白黄曾经用户目视确认；用户修改配置后应以保存的灯效为准。默认 `Firmware/platformio.ini` 仍关闭协议实验，不能拿默认镜像替代当前设备的上位机固件。

历史 USB 旧版曾有恢复性重连，后续 20 ms 隔离版有 30 分钟全部更新确认、无新增断线的记录。2026-10-18 重配测试仍出现过自动断连，原因未定位；不同版本的测试不能互相替代或证明当前长期稳定。实际波形、完整语音/监控关闭/断联目视验收仍需补齐；原始收据、日志和备份只留本地 `tmp/`。历史实现过程从 Git 历史查看，本文只保留现行接口与必要验证边界。

## 传输与信封 / Transport and envelope

- USB：`@OMI ` + 一个紧凑 UTF-8 JSON 对象 + `\n`；兼容 `\r\n`。
- WebSocket：相同 JSON 对象作为一条文本消息，没有串口前缀；隔离控制固件在 TLS 身份校验及日常双向 HMAC 认证后接受 `?` 探测及协议消息。
- 串口只将行首完全匹配前缀的内容交给协议解析。其他日志不执行为命令；前缀出现在日志中间也不会成为协议帧。
- JSON 大小上限计算 UTF-8 字节数，串口前缀/换行不计入。接收缓冲有界，超长帧丢至换行后重新同步；截断不执行，重复 JSON 键、非有限数常量、错误版本和非法标识均拒绝。

共同信封字段如下，所有字段必需，不接受额外顶层字段：

| 字段 | 类型与含义 |
| --- | --- |
| `v` | 整数 `1`，布尔值不等同版本号 |
| `boot` | 设备每次启动生成的 32 位小写十六进制标识 |
| `channel` | 每次连接生成的新标识，同上格式 |
| `session` | 主机为该连接生成的新标识；welcome 中为空字符串 |
| `seq` | uint32；welcome 为 0，主机命令从 1 严格递增，溢出前重新连接 |
| `type` | welcome、hello、heartbeat、snapshot、release、可选 light/monitorProfile 或 ack |
| `body` | 对象，由消息类型约束 |

三个标识分别防止设备重启、连接替换和主机会话混淆；无线配对与认证由独立的 PAKE、证书指纹和双向 HMAC 实现，详见 [PAIRING.md](PAIRING.md)。

## 握手与确认 / Handshake and acknowledgements

1. 模拟设备 `open()` 创建连接，进入 local，发送 welcome。USB 实验使用 `\n@OMI ?\n` 安全探测触发新连接；未收到有效 welcome 且完成 hello 前，主机不发送业务命令。探测帧不含 w，因此不会触发旧固件的串口唤醒入口。
2. welcome 返回 `operations`、`maxJsonBytes`、`maxSessions`、`leaseMs`。基础操作为 hello、heartbeat、snapshot、release；显式启用上位机控制的固件增加 light；启用监控灯效保存能力时还声明 monitorProfile。`monitorLights=true` 声明实体监控灯支持，`monitorGreenOff=true` 声明绿色回退/断联关灯策略，缺失不能当作支持。主机取双方资源上限的较小值。
3. 主机发送序号 1 的 hello，正文严格为 `{"protocol":1}`，确认后才能发送其他操作。
4. 每条 ack 回显 boot/channel/session/seq 和 `command`，包含 `ok`、`code`、`duplicate`、`state`。主机检查关联标识与状态结构，不接受其他连接的确认。

主机一次只有一条待确认命令，没有隐藏发送队列。`retry()` 返回同一条规范化命令；调用方决定何时重试，没有预设重试间隔、次数或后台循环。设备只缓存最近一条命令的内容/结果：同序号同内容返回去重确认，同序号不同内容拒绝，缺号或旧号拒绝。去重确认复用原命令的成功/错误结果，但 state 反映回复时的当前状态，防止重试恢复已经过期的显示；重试不重复应用，也不延长租约或业务有效期。

握手后的正文/业务错误会消费该命令序号并返回失败确认，保留已应用状态；连接、会话或序号错误不消费序号。连接到期要求新握手，不能通过重试或迟到快照重新获得控制。

## 业务快照 / Business snapshots

snapshot 正文包含：

| 字段 | 含义 |
| --- | --- |
| `revision` | 当前连接内递增的 uint32 快照版本；重复或旧版本不能续期 |
| `validForMs` | uint32，显示状态的剩余有效期；未知快照可为 0 |
| `sourceLiveness` | 当前固定为 unverified，不因通信心跳而变为已验证 |
| `overallStatus` | 按各会话 display 计算的汇总 |
| `sessions` | 完整会话集合，超出容量拒绝，不静默截断 |

每个会话只有 `id`、`observed`、`display`、`host`：

- id 是本次主机连接内稳定的 s1、s2 等别名，不发送真实 Codex 会话 ID、路径、提示词、工具内容或回复。
- observed 保留最后业务观测；display 表示候选显示状态。工作、待审批、空闲、离线及未知分别用 working、waitingApproval、idle、offline、unknown 表示。
- host 表示进程查询结果，running 之外的结果不能支持非未知显示。running 本身也不证明聊天仍然存活。
- 汇总优先级：waitingApproval → working → unknown → idle → offline；空集合为 unknown。

`SnapshotMapper` 接收 [CodexMonitor](../CodexMonitor/README.md) 的状态视图。只有来源可读、进程 running、显式观测策略有效且年龄未过期时才保留非未知显示；会扣除视图生成后经过的时间，防止重复读取旧文件重启有效期。多个非未知会话使用最短剩余有效期；到期后整个快照显示未知，不伪造 Stop。

别名历史同样受显式会话容量约束。容量或快照版本用尽时需重新连接并创建新 mapper，不回收/复用别名冒充其他会话。

## 控制与故障 / Control and failure behavior

- hello 仅握手，保持 local；有效 snapshot 进入 monitor。
- heartbeat 只续通信租约，不延长快照的业务有效期，不将 unverified 升级为已验证，也不会自动重新进入已释放的 monitor。
- 空正文 release 表示主动切本地，恢复保存的本地效果。断线或租约到期使协议回 local，旧连接失效；启用新策略时灯带关灯并保持，握手本身不恢复本地效果。
- ack 的 state 包含 mode、displayStatus、sourceLiveness、leaseActive。启用新策略时还含 monitorOutput=local/connected/disconnected，表示本地、监控连接保持或监控断联关灯。实际灯带还由语音优先权仲裁，不能仅凭 mode 推断实体灯效。

`OMIPET_MONITOR_GREEN_OFF=1` 要求同时启用监控灯，默认关闭并保留旧版路径。该策略的默认配置为 unknown/offline/空集合绿色扩散、working 红色、waitingApproval 黄色、idle 绿色；支持 monitorProfile 时使用各状态保存值，断联仍强制关灯。协议 unknown 不改成 idle。主机退出监控连接发送严格的 `release {"disconnect":true}`，设备关灯；主动切本地仍发 `release {}`。voice 接管退出监控选择，后续退出连接不能熄灭语音设置。熄灯期间不推进本地动画，防止下一帧重新点亮。状态有效期和连接租约仍相互独立。

2026-10-15 上位机隔离版增加 `light`：正文严格包含 `effect/red/green/blue/brightness`；effect 为 solid/rainbow/breathe/sweep/centerExpand/off，四个数值字段为 0–255 整数。仅本地模式且未在唤醒等待时接受；监控中返回 `monitor-mode-active`，语音活动中返回 `voice-active`。同序号重试不重复启动动画，失联或 release 不撤销已接受的本地设置，重启仍用原启动灯光。颜色和模式一次更新再绘制，设备自行播放动画，不逐帧传 LED 数据。固件 `OMIPET_DESKTOP_CONTROL` 默认关闭。

Windows 控制中心、实机步骤与最新验证见 [Desktop](../Desktop/README.md)。无线隔离实验沿用上述能力及 20 ms USB 过滤，另启用 WSS 配对、认证和控制。USB 有效监控优先，无线在 USB 释放后接续；语音同时退出两路监控，旧快照不能接管。ACK 描述本连接状态，跨连接最终输出及完整灯光读回、屏幕对话摘要尚未接入。无线不提供串口音频健康日志。

## 持久化监控灯效（monitorProfile）

只有 `welcome.body.operations` 声明 `monitorProfile` 时使用。`monitorProfile {}` 读取；写入正文为 `{"revision":当前版本,"profiles":{"working":Light,"waitingApproval":Light,"idle":Light,"unknown":Light,"offline":Light}}`，五项必须齐全且无多余字段；Light 与 `light` 的 effect/red/green/blue/brightness 约束相同。写入是设备全局配置，不切换本地/监控选择或覆盖语音。实际改变时版本递增，先确认完整 ACK 能生成，再提交单键 NVS 存储并发布；同序号重试或相同配置不重复写入。

支持此能力的每条 ACK 正文额外包含 `monitorProfile={revision,profiles}`（包括冲突/失败回复），设备状态结构不变。USB/WSS 共用版本；旧版本返回 `monitor-profile-conflict`，存储失败返回 `monitor-profile-save-failed`，版本耗尽返回 `monitor-profile-revision-exhausted`。主机校验完整读回，保持既有 JSON/深度/重试预算与状态采集周期。断联/租约到期仍强制关灯，unknown/offline 使用各自配置；无事件和业务状态过期仍是 unknown。NVS 启动加载不自动进入监控，也不恢复旧快照/租约。该能力已随当前隔离固件刷入，物理断电持久化与完整跨连接读回仍待实机验收。

## 状态来源与运行参数

CodexMonitor 保存生命周期观测和事件关联宿主证据。CLI 默认仍使用事件年龄预算。桌面监控通过 `LifecycleReader` 接纳近期且宿主存活的 schema 2 事件证明，随后延续同一生命周期，收到结束事件才结束；不会将长时间无新事件误当成完成。旧事件时间与年龄保留不变，每轮独立校验的评估使用原有 30 秒预算，扣除 8 秒传输余量；设备挑战还会扣除心跳到快照的耗时，缓存评估不能自行续期。重开监控不接纳过期历史状态，来源/绑定/进程失效则清除延续资格。心跳不生成业务事件，`sourceLiveness` 仍为 `unverified`；遗漏 Stop 且宿主仍存活时无法独立确认聊天已结束。协议 unknown 不等同 idle，`waitingApproval` 同时覆盖待审批与待用户选项回复。同一聊天的异步问题保留待回复记录，但不覆盖实际执行的 working；当前任务停止而仍有本任务问题待回复时显示等待；新任务接替后，历史未结束轮次和背景异步问题不再覆盖新任务完成，真实审批及跨聊天等待仍优先。

已确认实机预算：最大 JSON 4096 字节、最多 16 会话、深度 8、每轮接收 64 字节、USB TX 缓冲 8192 字节、写等待 1 ms、租约 5000 ms。桌面通信周期 1 秒、超时 2 秒、最多重试 1 次。修改预算或调度前按项目协作规则确认，不能照搬测试中的合成阈值。

### 历史验证（2026-10-16，仅适用于当时镜像）

短断线排查：旧日志有无总线重置、无协议超时的毫秒级 `isPlugged()` 低信号，旧传输层会立即清除会话。[Espressif HWCDC 源码](https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/HWCDC.cpp) 也说明 SOF 检测可短时翻转；这不能单独证明物理线缆稳定。可选 `--link-grace-ms` 只用于隔离构建，必须显式指定正数且小于租约；默认 `OMIPET_PROTOCOL_LINK_GRACE_MS=0` 保持即时断开。宽限期内暂停收发、不续租；恢复后只延续尚未过期的原会话，达到边界仍断开并拒绝旧连接请求。`filtered_link_gaps` 与确认断开的 `link_losses` 分别计数。用户已确认 20 ms 并授权烧录，现有 SOF 修补和稳定默认配置保持不变。

2026-10-16：COM17 上 30 分钟共 1613 次状态更新全部确认，过滤 9 次短脉冲，最长记录 6 ms；断线/重连/总线重置/写失败均未新增，零超时/解码错误、无音频队列或看门狗异常，关闭释放确认。实验固件 RAM 66520 / Flash 1549229 字节，5 MiB 模型随 5 个镜像校验烧录；默认构建 RAM 57896 / Flash 1532693 字节通过且未刷入。另有 3 次 `unknown`，尚未确定状态来源原因，不能将 USB 连续性通过等同于状态/灯效全部稳定；该轮未完成物理拔线与完整红绿目视；后续补验仅覆盖下文的相应样例。

上位机退出释放补充：桌面控制器先完成连接，再创建桥接器；首轮遇到连接重建后，桥接器的连接计数可能仍为零。释放判断现在也检查是否尝试过运行周期，避免跳过重新握手与释放。没有启动的桥接器仍不打开串口。合成回归及 COM17 注入主机会话丢失的重新握手/关闭检查通过，不能据此宣称底层短断线已修复。

状态一致性修复：桌面读取与 Hook 包装器共用原有互斥锁，使快照和宿主证明作为同一批发布被读取；锁失效仍降级，不新增重试或状态保留期限。报告新增 `unknownReasons` 累计原因和 `lastUnknownSnapshot` 时间/原因汇总，区分事件证明、进程、传输有效期及设备返回未知。`device-display-unknown` 仅说明发送已知状态后设备仍返回未知，不据此推断根因；非白名单原因统一记作 `unclassified`，不复制原始 ID 或文本。COM17 60 秒复测 56 次更新全部为 working，零 unknown/超时/解码错误，退出释放确认；未重新烧录，不能替代长期及目视验收。

随后真实 Hook 60 秒轮测 55 次 ACK（working 44 / waitingApproval 11），零 unknown/超时/解码错误，退出释放确认；用户目视确认选项黄、回复后红。隔离完成样例的绿灯及独立供电时拔线关灯、插回恢复绿灯同样经用户确认；该轮共 51 次 idle ACK，拔线期间 3 次更新失败，插回恢复并在结束时释放确认，不能把模拟来源当成真实会话结束证据。

### 当前 CLI 使用

桌面程序复用 `Desktop/controller.py` 和 `worker.py`，不安装自动后台服务。CLI 默认只传 unknown；显式的状态显示需同时给出有效期、宿主绑定及 `--monitor-lights`。例如在仓库根目录执行已确认的 60 秒前台实验：

```powershell
python Tools/DeviceBridge/bridge.py --port COM17 --max-json-bytes 4096 --max-sessions 16 --interval-seconds 1 --timeout-seconds 2 --retries 1 --duration-seconds 60 --max-age-seconds 30 --process-bindings <本机绑定文件> --monitor-lights --stop-file tmp/codex-bridge.stop --report tmp/codex-bridge-report.json
```

端口先重新枚举，report 选尚不存在的新路径；已有 stop 文件会阻止打开串口。Ctrl+C 或 stop 文件结束时尝试 release，只有匹配 ACK 才能报告释放确认；异常退出依靠设备租约。耗时超出周期不补发旧观测，租约到期重新握手。

## 构建与验证

Python 3.10+；USB 另需 pyserial。无设备测试：

```powershell
python -m unittest discover -s Tools/DeviceBridge/tests -v
python Tools/DeviceBridge/demo.py --max-json-bytes 4096 --max-sessions 16 --lease-ms 1000
```

上述 1000 ms 仅用于模拟，不是实机租约。Python 测试依赖见 `../Desktop/requirements.txt`，无线还需 websocket-client；涉及原生 PAKE 的测试应先构建 DLL。原生测试 `tests/run_firmware_native.py` 需指定本机 cJSON 源码目录，Windows 需明确指定已有 WSL 发行版；加密原语验证见 PAIRING.md。模拟器和测试替身用于故障/边界检查，不是另一套生产固件。

隔离配置生成器只写新配置，不构建、不刷机；在仓库根目录运行：

```powershell
python Tools/DeviceBridge/tests/create_experiment_config.py --output tmp/desktop-protocol.ini --build-dir Firmware/.pio/desktop-protocol --max-json-bytes 4096 --rx-bytes-per-loop 64 --max-json-depth 8 --usb --max-sessions 16 --lease-ms 5000 --tx-buffer-bytes 8192 --write-wait-ms 1 --sof-reset-fix --freshness-challenge --monitor-lights --monitor-green-off --desktop-control --link-grace-ms 20
pio run -d Firmware -c (Resolve-Path tmp/desktop-protocol.ini)
```

该示例只启用 USB 桌面功能。完整无线配对/控制使用另一份新配置，在同一生成命令中额外加入 `--wireless-pairing --wireless-control`；保持其余已确认参数，并为 `--output` 和 `--build-dir` 选择独立新路径。生成配置不会自动烧录，也不会更换稳定默认构建。

SOF 修复只在构建目录生成 SDK 源文件副本，不改上游安装包。正式默认配置和当前设备镜像保持分离；烧录须另有用户授权，并保留原应用、引导、分区、OTA 与 5 MiB 模型回退证据。不能只烧应用后宣称模型一致。

实机验收：设备状态 → 独占正确串口 → 握手与能力 → light/快照/过期/释放 → 比较 ACK 与实体行为。检查 `[PROTO]` 的 mode/display/lease、丢帧/重连计数，`mic=ok`、`queued/dropped`、WDT/panic 和语音 ID；无日志证据时写未观测，不写通过。物理拔线需设备独立供电，正常关闭串口不等于物理拔线。

## 隐私与配对

Hook 原始事件、真实会话/工具标识、宿主路径、串口日志、报告和镜像不提交。传输只使用连接内别名和状态；配对码、日常凭证和 TLS 私钥只留本地。真实网络配对仅在隔离固件开启，稳定配置默认关闭；未启用 NVS 加密，不执行不可逆 eFuse 配置。提交边界见根目录 CONTRIBUTING.md。

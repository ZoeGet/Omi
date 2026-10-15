# OmiPet 共用通信协议原型 / Shared device protocol prototype

这是隔离的主机/固件协议实验：Python 3.10+ 编解码与模拟器只用标准库，实际 USB 客户端另需 pyserial。已实现默认关闭的固件 USB 收发与主机验证工具；只有显式运行 USB 工具才会打开指定端口，没有后台服务或真实 WebSocket 连接。实机历史记录在后文；最新上位机及绿色回退/断联关灯结果见 [Desktop](../Desktop/README.md)，以该现状为准。

| 文件 | 职责 |
| --- | --- |
| `protocol.py` | 有界解码、信封/快照校验、会话别名与来源有效性转换 |
| `simulator.py` | 主机单条待确认状态机、设备握手/去重/控制租约模拟 |
| `demo.py` | 两种编码的完整内存往返演示 |
| `tests/test_protocol.py` | 分包、异常输入、重试、过期、重连、隐私及资源边界验证 |
| `tests/run_firmware_native.py`、`tests/native/` | 用固件原始 C++ 源码及已安装的 IDF cJSON 做原生检查 |
| `tests/create_experiment_config.py` | 显式预算生成隔离的仅构建配置，不改稳定配置或刷机 |
| `usb_client.py`、`verify_usb.py` | 安全探测后握手、单请求确认/重试、显式端口实机验证 |
| `bridge.py`、`tests/test_bridge.py` | 持续读取真实 Hook 观测、仅状态传输、停止释放与恢复测试 |
| `tests/test_usb_client.py`、`tests/native/transport_native.cpp` | 主机故障恢复与实际 C++ 传输核心的背压/断连检查 |

## 当前验证 / Current verification

2026-10-14：30 项测试通过，包含每个字节切分位置、混合日志、UTF-8 字节上限、截断/损坏帧、旧连接/重启/其他会话、序号冲突、丢确认重试、业务有效期与连接租约独立、缓存视图老化及容量错误无部分应用。合成演示和 7 个真实会话只读视图的模拟传输均完成；真实会话 ID 被替换成别名，默认汇总保持 unknown。

```powershell
python Tools/DeviceBridge/tests/test_protocol.py
python Tools/DeviceBridge/demo.py --max-json-bytes 4096 --max-sessions 16 --lease-ms 1000
```

示例中的 1000 ms 租约仅为模拟参数；实机采用用户确认的 4096 字节、16 会话和 5000 ms 租约，完整参数见文末。所有资源上限和租约均须显式传入，未设置生产默认值。演示支持 `--view-file` 读取 CodexMonitor 状态视图、`--report` 写入摘要；输入文件可能含本地元数据，不提交 Git。

## 传输与信封 / Transport and envelope

- USB：`@OMI ` + 一个紧凑 UTF-8 JSON 对象 + `\n`；兼容 `\r\n`。
- WebSocket：相同 JSON 对象作为一条文本消息，没有串口前缀。这里只验证文本编解码，没有实现网络连接或 WebSocket 握手。
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
| `type` | welcome、hello、heartbeat、snapshot、release、可选 light 或 ack |
| `body` | 对象，由消息类型约束 |

三个标识分别防止设备重启、连接替换和主机会话混淆；它们不是 Wi-Fi 身份认证方案。真实 Wi-Fi 接入的配对/鉴权尚未实现。

## 握手与确认 / Handshake and acknowledgements

1. 模拟设备 `open()` 创建连接，进入 local，发送 welcome。USB 实验使用 `\n@OMI ?\n` 安全探测触发新连接；未收到有效 welcome 且完成 hello 前，主机不发送业务命令。探测帧不含 w，因此不会触发旧固件的串口唤醒入口。
2. welcome 返回 `operations`、`maxJsonBytes`、`maxSessions`、`leaseMs`。基础操作为 hello、heartbeat、snapshot、release；仅显式启用上位机控制的固件增加 light。`monitorLights=true` 声明实体监控灯支持，`monitorGreenOff=true` 声明绿色回退/断联关灯策略，缺失不能当作支持。主机取双方资源上限的较小值。
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

`OMIPET_MONITOR_GREEN_OFF=1` 要求同时启用监控灯，默认关闭并保留旧版路径。新策略下 unknown/offline/空集合用绿色扩散灯，working 红色、waitingApproval 黄色、idle 绿色；协议 unknown 不改成 idle。主机退出监控连接发送严格的 `release {"disconnect":true}`，设备关灯；主动切本地仍发 `release {}`。voice 接管退出监控选择，后续退出连接不能熄灭语音设置。熄灯期间不推进本地动画，防止下一帧重新点亮。状态有效期和连接租约仍相互独立。

2026-10-15 上位机隔离版增加 `light`：正文严格包含 `effect/red/green/blue/brightness`；effect 为 solid/rainbow/breathe/sweep/centerExpand/off，四个数值字段为 0–255 整数。仅本地模式且未在唤醒等待时接受；监控中返回 `monitor-mode-active`，语音活动中返回 `voice-active`。同序号重试不重复启动动画，失联或 release 不撤销已接受的本地设置，重启仍用原启动灯光。颜色和模式一次更新再绘制，设备自行播放动画，不逐帧传 LED 数据。固件 `OMIPET_DESKTOP_CONTROL` 默认关闭。

Windows 控制台、实机步骤/日志/回退及最新验证见 [Desktop](../Desktop/README.md)。本轮 COM17 已烧录支持上述能力的 USB 隔离固件；无线认证、WSS、屏幕摘要及完整设备状态读回尚未接入。

## 上机前待办 / Before device integration

当前稳定配置仍逐字符识别 w，默认不解析协议；JSON 中出现 w 可能触发该调试路径。USB 客户端先发安全探测，旧固件不回应 welcome 时超时退出，不向其发送 JSON。

已新增默认关闭的诊断入口，以及独立开关的 USB 协议执行入口。后者把状态核心接到收发适配器，但不接管灯带/语音。用户已确认实验参数并授权刷写；2026-10-14 已通过 COM17 烧录及实机通信验证，结果见文末。

实机帧大小、会话容量、心跳周期、租约、重试策略和观测有效期仍待资源/延迟测量后确认。当前模拟设备从收到快照开始计算 validForMs；真实传输还需扣除排队及往返延迟预算，不能把内存演示当作端到端新鲜度证明。当前没有串口/网络吞吐、丢包、重连或固件时延的实测结论。

## 固件接收诊断实验 / Firmware receive diagnostic experiment

| 文件 | 职责 |
| --- | --- |
| `Firmware/include/protocol_experiment_config.h` | `OMIPET_PROTOCOL_EXPERIMENT` 默认 0；启用必须给出三个正数预算 |
| `Firmware/include/device_protocol_framer.h` | 固定容量字节分帧，不将帧内字节回放给调试 w |
| `Firmware/src/device_protocol_envelope.cpp` | UTF-8、深度、JSON 完整性/重复键、信封字段检查 |
| `Firmware/src/device_protocol_experiment.cpp` | 有界读取、帧外调试回调、每轮最多一条诊断日志 |
| `Firmware/src/main.cpp` | 编译开关选择旧入口或实验入口，原语音调试动作独立为回调 |

实验入口不执行协议命令、不生成 welcome/成功 ACK、不改变灯带和控制权。输出仅为普通 `[PROTO]` 诊断日志，带 `execution=disabled`；不会回显 JSON、提示词、会话 ID 或载荷内容。`envelope_valid` 只表示信封格式检查通过，尚未完成快照正文的业务校验。

解析采用当前 ESP-IDF 自带的 json/cJSON 组件，没有引入新外部 JSON 依赖。进入库前限制嵌套深度，拒绝非法 UTF-8、裸控制字符、嵌入 NUL 和浮点/指数数值表示；按字节长度检查完整 JSON，递归拒绝重复键。输入丢弃至换行后恢复。截断帧不会触发调试 w；未设置帧超时，必要时先发送换行恢复分帧状态。

默认关闭构建已验证，不包含实验分帧器缓冲或解析函数符号。基线 RAM/Flash 为 57,852/1,532,017 字节；修改后的默认关闭构建为 57,856/1,531,949 字节，两者均生成 5 MiB 模型。构建成功不代表实机 I²S、时延或看门狗已验证。

隔离的实验开启构建同样通过：RAM 61,968 字节（18.9%），Flash 1,538,829 字节（29.4%），模型 5 MiB；已从 ELF 符号确认诊断入口和解析器被链接。独立状态核心已编译为 ESP32 对象文件，但未被诊断入口调用，最终镜像将其裁除，因此这些数值不包含接入核心后的完整开销。两版均未刷写。

原生检查使用安装中的 IDF cJSON，编译固件实际解析器和串口适配器源码，开启地址与未定义行为检查。Windows 上须显式选择已有的 WSL 发行版，示例使用本机 Ubuntu-22.04：

```powershell
$protocolCjsonPath = Join-Path $env:USERPROFILE '.platformio/packages/framework-espidf/components/json/cJSON'
python Tools/DeviceBridge/tests/run_firmware_native.py --cjson-dir $protocolCjsonPath --wsl-distro Ubuntu-22.04
```

本轮 15 组原生测试和 3 项编译配置检查全部通过，地址与未定义行为检查无报错。覆盖完整/截断/超长帧、CRLF 边界、帧内 w、无效前缀/NUL、UTF-8/重复键/深度、uint32 边界、串口读取预算，以及 Python 编码的四种请求到 C++ 解析的交叉检查；也检查默认关闭、缺预算和零预算拒绝。测试参数 4096 字节/每轮 16 字节/深度 8 只供编译及替身测试。

如需复现隔离开启构建，先生成一个新的临时配置。以下仍为测试参数，不能直接当成实机调度值：

```powershell
python Tools/DeviceBridge/tests/create_experiment_config.py --output tmp/protocol-compile-check.ini --build-dir Firmware/.pio/protocol-compile-check --max-json-bytes 4096 --rx-bytes-per-loop 16 --max-json-depth 8
$protocolCompileConfig = (Resolve-Path -LiteralPath 'tmp/protocol-compile-check.ini').Path
& "$env:USERPROFILE/.platformio/penv/Scripts/platformio.exe" run -d Firmware -c $protocolCompileConfig -e esp32-s3-devkitc-1
```

生成器保留原硬件/语音构建项，拒绝覆盖既有配置或使用普通构建目录；不开启串口、不上传。稳定 `Firmware/platformio.ini` 不增加实验开关。

USB 实机测试已记录协议轮询耗时、总剩余堆和音频队列；尚未独立测量 cJSON 峰值分配或真实 Serial 背压对语音的影响。诊断入口不调用下述核心，独立 USB 开关才启用协议执行；远程灯光及与语音的仲裁未接入。

## 固件协议状态核心 / Firmware protocol state core

`Firmware/include/device_protocol_session.h` 与 `Firmware/src/device_protocol_session.cpp` 提供独立的 `ProtocolSession`；实现受同一个默认关闭的实验开关保护。它维护协议状态并生成无前缀 JSON，不自行读写串口、生成标识或驱动灯带。

- 构造时明确传入启动标识、帧大小、会话容量、JSON 深度和正数租约。`open()` 接受新连接标识并生成 welcome；未成功生成应答不会打开连接。实机标识由 USB 适配器随机生成，不能复用测试值。
- `receive()` 校验连接/会话、hello、递增序号、四种命令正文、快照版本、别名唯一性、状态/宿主一致性和汇总优先级。快照只在全部校验通过后应用；业务错误消费序号，身份/序号/握手错误不消费。
- 只保留最近请求以判重；对象键顺序和空白不影响相等判断，数组顺序仍有意义。另存整数字面量，防止 JSON 库的 double 舍入把两个大整数误判为相同内容。
- 先完整生成 ACK，再提交新命令状态。输出容量不足或分配失败时不消费序号，可重试；时间推进和到期仍生效。非法信封、超长、过深、重复键以及非整数字面量在输入边界拒绝，不生成 ACK，也不消费序号。
- `advance()` 使用外部单调 64 位毫秒时钟；无消息时也须调用。通过已过时间判断过期，避免截止时间相加溢出；倒退时钟拒绝。未来接入 32 位 `millis()` 时必须先扩展，不能直接强制转换假装已处理回绕。
- `disconnect()` 立即回 local；租约到期后旧连接不能靠重试复活。heartbeat 不续快照有效期；release 后 heartbeat 仅保活，不能恢复 monitor。新的有效 snapshot 才能进入 monitor。

输入与输出缓冲必须分开，输出容量包含结尾 NUL。调用方须检查返回结果，不能把未生成的应答当成成功发送。当前保留汇总状态及最后请求用于去重，不提供屏幕会话列表或灯效回调。`OMIPET_PROTOCOL_USB=0` 时诊断入口仍只输出 `execution=disabled`。

验证使用 `tests/session_vectors.py` 从 Python 模拟设备生成逐步期望值，由 `tests/native/session_native.cpp` 驱动实际 C++ 核心逐项比对 welcome、ACK 和状态；原生运行命令仍为上节的 `run_firmware_native.py`。另有输出不足、逐个分配点故障注入、时钟边界及恢复测试，开启 ASan/UBSan。测试中的 1000 ms 租约、4096 字节、16 会话、深度 8 均为夹具参数。

2026-10-14 状态核心阶段：33 组状态核心检查通过（29 组协议交叉场景、4 组缓冲/分配/时钟边界），原有 15 组解析检查、3 项配置检查及 Python 30 测试通过。覆盖无效正文不部分应用、重复失败应答、快照过期后重试不恢复显示、释放后保活、断线重连，以及大整数精度冲突；ASan/UBSan 无报错。后续 USB 接入的构建、扩展检查和实机结果见下节。

状态核心的 `monitor` 只是逻辑控制模式，不代表灯带已交给电脑；正式硬件仲裁仍待实现。端到端快照新鲜度、实机背压与语音任务时延仍待验证。

## USB 收发实验 / USB transport experiment

`device_protocol_transport.h` 提供单槽待发送缓冲和有界接收；`device_protocol_experiment.cpp` 在独立的 `OMIPET_PROTOCOL_USB=1` 下使用 HWCDC、`esp_timer_get_time()` 的 64 位毫秒时钟及 `esp_fill_random()` 标识。两个实验开关默认均为 0。USB 构建必须额外显式提供会话容量、租约、TX 环形缓冲大小和正数写等待；不能将 SDK 写等待设为 0（当前实现存在无进展计数下溢路径）。RX 缓冲在首次 Serial.begin 前按最大帧加前缀余量分配，运行中不重设。

- 探测创建新 channel 并释放旧协议状态；丢失 welcome 时可重新探测。日志与半帧由领先换行重新同步。设备启动标识在本次运行内不变。
- 应答带完整 `\n@OMI JSON\n`，只有 HWCDC 空间足够容纳整帧时才一次写入；背压时继续主循环。其他并发或底层控制台输出仍可能损坏一帧，主机须校验并重试，不能把单次写入当作所有日志源的全局原子性保证。
- 不排队执行第二条业务命令；待发送时收到额外业务帧会丢弃，正常主机保持单条待确认。探测可替换堵塞中的连接。短写会释放协议状态并要求重连。
- 发送前若状态已过期，丢弃旧应答；已进入 USB/操作系统缓冲的字节无法撤回。因此 ACK 是一次观测，不是持续存活证明，也不保证非未知快照端到端新鲜度；目前只用合成状态验证，不将真实 Codex 状态接管灯带。
- SDK 物理拔线/总线复位会释放协议状态；关闭电脑串口不等于可检测的物理断连。正常退出发送 release，异常退出靠显式租约到期回 local。断连后残留半帧丢至换行，避免正文 w 变成调试输入。

用户已确认并用于本次实机实验的参数：4096 字节、16 会话、深度 8、每轮 RX 64 字节、TX 8192 字节、SDK 写等待 1 ms、租约 5000 ms。隔离配置生成器支持 `--usb --max-sessions ... --lease-ms ... --tx-buffer-bytes ... --write-wait-ms ...`，不修改稳定配置，不自动烧录。

2026-10-14：6 组传输核心、33 组状态核心、15 组解析和 7 项配置检查通过，ASan/UBSan 无报错；主机 USB 6 测试及协议 30 测试通过。USB 构建 RAM 66,368 字节（20.3%）、Flash 1,544,449 字节（29.5%），模型 5 MiB。默认关闭版也构建通过：RAM 57,852 字节（17.7%）、Flash 1,532,029 字节（29.2%），模型 5 MiB，ELF 不含实验入口。

设备重新枚举为 COM17（303A:1001）；刷写前只读日志正常。经授权写入 USB 实验版的引导程序、分区表、OTA 初始数据、应用及模型，5 个镜像均通过烧录哈希校验，未整片擦除或擦除 NVS。设备当前运行 USB 实验版，测试结束已 release 并关闭主机串口，没有后台桥接进程。稳定 platformio.ini 仍默认关闭实验；以后按普通配置烧录会关闭 USB 协议。

实机三轮通过：首轮约 72 秒；补充去重检查后两轮各 15 项通过，含握手、忽略已收到的首个 ACK 后同序号重试、快照过期、释放后保活、关闭串口后租约到期、重连、半帧及超长帧恢复。最终日志 mic=ok、queued=0/dropped=0，无 task_wdt/panic 或帧内 w 意外触发唤醒；累计记录的最大协议轮询耗时 3921 µs，不能视为最坏耗时保证。最低报告剩余堆 4,472,815 字节包含 PSRAM，不代表内部 SRAM 余量。

本地证据：`tmp/codex-monitor-probe/firmware-usb-install.json`、`firmware-usb-upload.log`、`usb-live-final-check.json/.log`；首轮为 `usb-live-check.json/.log`。回退镜像保留于 `usb-rollback-20261014-204753/`，含清单和哈希；它们来自此前默认关闭版构建，不是设备 Flash 读回备份。当前实验配置为 `protocol-usb-candidate.ini`，镜像位于 `Firmware/.pio/protocol-usb-build/esp32-s3-devkitc-1/`。

复测命令如下；先重新枚举端口并确认匹配固件，log 路径要求不存在：

```powershell
python Tools/DeviceBridge/verify_usb.py --port COM17 --timeout-seconds 2 --retries 1 --max-json-bytes 4096 --max-sessions 16 --observe-seconds 60 --report tmp/usb-check.json --log tmp/usb-check.log
```

设备状态 → 操作 → 预期日志 → 判定：保持 OmiPet USB 供电，工具完成合成快照/过期/释放/关闭串口等待租约/重连及半帧恢复；检查 `[PROTO]` mode/display/lease/seq、max_poll_us、heap，以及 `[SYS] mic=ok`、`[AUDIO] queued=0 dropped=0`、无 task_wdt/panic/意外 serial wake。脚本通过不等于语音识别率、真实拔线、硬件背压或长期稳定已验证。

本节为合成状态验证；下一节为随后接入的真实观测桥接。端到端新鲜度、手动/语音/监控灯光仲裁、真实拔线、硬件背压、实际语音识别及长期稳定仍待验证。

## 真实观测桥接 / Observations-only bridge

`bridge.py` 按显式周期读取 CodexMonitor 的原有 `snapshot.json`，通过已烧录的 USB 实验协议发送快照。不修改 Hook 定义、采集器或登录配置，不需要重新烧录。只传临时别名、最后观测状态、unknown 显示和未验证的宿主状态；不发送真实会话 ID、路径、工具名、提示词或回复。

本阶段强制 `maxAgeSeconds=None`、`display=unknown`、`validForMs=0`，不开放启用红黄绿的命令参数。真实“最后观测为 working/idle”等信息不构成实时存活证明；重复读取旧记录不会延长它的业务有效期。连接租约仍表示 USB 通信，不表示聊天存活。设备 `monitor` 是逻辑模式，尚未驱动灯带。

在仓库根目录运行，先重新枚举端口；report 路径必须不存在：

```powershell
python Tools/DeviceBridge/bridge.py --port COM17 --max-json-bytes 4096 --max-sessions 16 --interval-seconds 1 --timeout-seconds 2 --retries 1 --duration-seconds 60 --stop-file tmp/codex-bridge.stop --report tmp/codex-bridge-report.json
```

2026-10-15 用户已确认本次实机周期 1 秒、单次超时 2 秒、最多重试 1 次、运行 60 秒，未设状态有效期。资源上限仍为此前确认的 4096 字节/16 会话，设备租约由握手确认。所有调度参数须显式填写，周期必须短于设备租约；耗时超出周期时不补发历史任务，租约过期则重新握手并读取新视图。

省略 `--duration-seconds` 可在前台持续运行。Ctrl+C 或创建指定 stop 文件可停止，已有 stop 文件则不打开串口；程序不会删除用户的 stop 文件。检查停止请求的间隔受轮询和正在执行的串口超时影响，60 秒是运行预算而非强制终止期限。正常停止尝试 release，只有匹配 ACK 确认 local/lease=false 才记录 releaseConfirmed；无法收到确认时不能宣称已释放，异常退出后依靠设备租约恢复。

串口异常时下一轮重新打开同一显式端口并重新探测，不猜其他设备；旧连接的待确认命令和别名不跨新连接复用。持续出现的新会话耗尽别名后重新连接；单个视图本身超过容量或数据损坏时发送空 unknown 快照，不截取一部分冒充全部会话。来源缺失也发送空 unknown，来源恢复后重新读取；USB ACK 仅表示设备接受该快照。

报告保存计数、超时/解码诊断、设备协议计数、来源类别、最后状态计数、最新观测时间、通信/释放结果及筛选的设备健康统计，不保存完整源视图、协议载荷或串口日志。别名表、接收行和最近传输计时受限或每轮清空，不积累无限历史。该命令不安装开机启动或后台服务。

验证：`python Tools/DeviceBridge/tests/test_bridge.py`。19 项测试覆盖真实快照文件变更与隐私、强制 unknown、来源缺失/损坏/超限、丢 ACK 去重、串口/租约恢复、别名耗尽、运行期限/停止/中断释放、旧固件安全探测及日志容量。协议 30、USB 客户端 7、状态视图 16 项回归通过。

下一步：补齐非 unknown 快照的端到端新鲜度，再实现灯光仲裁。真实拔线、拒绝审批/输入等待、语音识别率和长期运行尚未由本轮验证。

2026-10-15 定位记录：两轮真实观测运行均为 60 秒、7 会话、52 轮/51 ACK；一次超时后自动恢复且最终释放确认成功，结果记为 incomplete。第二轮主机无解码错误，但设备 rejected 增加两次，不能据此猜测具体原因。随后增加 session_failure/frame_failure 类别诊断，构建并经 COM17 烧录五镜像校验通过；参数未改。诊断版 RAM 66,376（20.3%）、Flash 1,544,525（29.5%）、模型 5 MiB，稳定配置仍关闭。新增 200 次七会话排序快照交叉验证通过；原生检查为 15 解析/34 状态/6 传输/7 配置。证据位于本地 tmp/codex-monitor-probe/bridge-*-20261015.json、firmware-bridge-*.log/json。

诊断结果：session_failure=3 对应 SessionResult::NotOpen，frame_failure=0，表示协议连接已经关闭；不是已证实的 JSON 损坏或内存不足。关闭来源还需通过新增 link_losses 与 bus_resets 区分，不能猜测用户实际拔线。修复后的传输器收到关闭连接的请求只返回新 channel 的 welcome，不执行旧正文，不续旧租约；主机识别新 welcome 后中断旧 ACK 等待，下一轮重新探测并读取当前视图。正常租约过期仍按原协议错误处理。

新握手通知单独记录 connectionResets；包含这类恢复且其他通信无错误的结果标为 pass-with-recovery，不等于物理 USB 无波动。无响应超时、串口错误等仍记录 communicationErrors，结果为 incomplete；任何结果都要求有效快照 ACK 和退出释放确认，才可记为通过。旧客户端仍可在超时后重新探测兼容恢复。

恢复固件构建 RAM 66,384（20.3%）、Flash 1,544,809（29.5%）、模型 5 MiB。原生 15 解析/34 状态/7 传输/7 配置检查及 ASan/UBSan 通过；新增测试确认关闭连接旧快照不应用、新握手前无控制权、主机不再等待该 ACK 超时。

最终实机结果（2026-10-15，COM17）：60 秒、58 轮、57 个快照 ACK，7 个真实已观测会话；观测时间推进 7 次，最后观测 working=3/idle=3/offline=1。USB 应答超时/解码错误/设备拒绝均为 0；一次新握手恢复，结果 pass-with-recovery。SDK 连接指示 link_losses=8、reopens=1、bus_resets=0；不能将这些指示等同于用户拔线，也未证实底层原因已经消失。

mic=ok，59 个音频诊断样本未出现 queued/dropped 非零，无 WDT/panic/意外串口唤醒；本轮报告的最大协议轮询 6418 µs，不是最坏延迟保证。最后 releaseConfirmed=true、local/unknown/lease=false，串口已关闭，没有后台桥接进程。真实语音识别与长期稳定未测。

设备状态 → 操作 → 预期 → 实际 → 下一步：USB 实验固件、COM17；按用户确认的 1 秒周期发送真实只读观测 60 秒；预期仅别名/状态、显示 unknown、连接恢复及退出释放、音频健康；上述快照确认与恢复通过，但 SDK 连接指示有波动。下一步调查底层 USB 指示波动，并处理非 unknown 快照端到端新鲜度和灯光仲裁。本阶段无需用户操作，未提交或推送。

最终证据：`tmp/codex-monitor-probe/bridge-live-recovery-20261015.json`、`firmware-bridge-recovery-install-20261015.json`、`firmware-bridge-recovery-upload-20261015.log`、`firmware-bridge-recovery-native-20261015.json`。应用 SHA256 `4d65c97656fef24fed1f95bdaa52a71727dfff19fba215a03e55422084bc8a5f`；该轮设备运行恢复版；随后 SOF 修复见下节。默认关闭构建与既有回退镜像保留，ESP-SR 未改。

## SOF 连接判定修复 / Isolated SOF counter fix

2026-10-15 本机 Arduino 包 HWCDC.cpp 中，usb_serial_jtag_sof_tick_hook 只在连接状态与当前 SOF 读数不同时进入更新分支。连接保持 true 时，收到 SOF 不会重置 remaining_allowed_no_sof_ticks，零散未观测到 SOF 的 tick 会跨成功观测累积，最终造成短暂 false。这与代码注释所述的连续缺失判定不一致；不代表已测得 USB 电气层丢包或确认用户拔线。

原生测试提取本机实际 SDK 函数，分别执行原版和修复版：交替缺失/收到 SOF 可复现原版 false，修复版保持连接；连续缺失仍在原有 ALLOWED_NO_SOF_TICKS+1 次时断连，重新收到 SOF 恢复完整预算。本机 CONFIG_FREERTOS_HZ=1000，SDK 原有门限为 5 ms，修复没有增加新门限或更改 tick 调度。测试中的 SOF 序列是输入夹具，不是新的实机参数。

Firmware/scripts/usb_sof_fix.py 只接受已审计的原始源 SHA256 d0a8ca606c2729c8522a041113285dbf27033c22a5a6af8649a7305ffe84c449；其他版本、换行变化或重复打补丁均拒绝。脚本保留许可证，在构建目录生成副本，只替换计数分支。全局 SDK 文件和 ESP-SR 未改；包升级后须重新审计，不能直接放宽哈希条件。

Firmware/CMakeLists.txt 新增默认 OFF 的 OMIPET_USB_SOF_FIX：启用时替换 Arduino 组件中唯一 HWCDC.cpp 源，重复或缺失匹配会失败，生成脚本/源变化会重新配置。稳定 platformio.ini 不启用该选项；隔离配置生成器增加 --sof-reset-fix，且必须同时指定 --usb 和原有预算。

```powershell
python Tools/DeviceBridge/tests/create_experiment_config.py --output tmp/protocol-sof.ini --build-dir Firmware/.pio/protocol-sof-build --max-json-bytes 4096 --rx-bytes-per-loop 64 --max-json-depth 8 --usb --max-sessions 16 --lease-ms 5000 --tx-buffer-bytes 8192 --write-wait-ms 1 --sof-reset-fix
python Tools/DeviceBridge/tests/test_sof_fix.py
```

6 项 Python 检查通过：只替换已审计分支、原门限/注册不变、未知源/重复补丁拒绝、提取实际函数、必须显式启用、稳定配置保持不变。原生运行器可传 --hwcdc-source 指向本机 HWCDC.cpp，新增 5 组 SOF 检查，连同既有 15 解析/34 状态/7 传输/7 配置检查通过 ASan/UBSan。USB 客户端 7 和桥接 19 项回归通过。

隔离配置 tmp/codex-monitor-probe/protocol-usb-sof-fix.ini，构建目录 Firmware/.pio/protocol-sof-fix-build/esp32-s3-devkitc-1。compile_commands.json 已核对仅一个 HWCDC.cpp 输入，来自 omipet-sof/ 副本，不编译原版。前一恢复版的五镜像另存 tmp/codex-monitor-probe/usb-rollback-before-sof-20261015/，逐项与已验证收据核对哈希；不是设备 Flash 读回备份。

2026-10-15 构建与烧录完成：隔离修复版 RAM 66,384 字节（20.3%）、Flash 1,544,757 字节（29.5%），模型 5 MiB；COM17（303A:1001）五镜像写入均通过哈希校验。默认关闭版独立构建通过，RAM 57,852 字节（17.7%）、Flash 1,532,029 字节（29.2%）、模型 5 MiB，未烧录。两份 compile_commands 分别确认唯一 HWCDC 输入为隔离副本和原始 SDK；全局 SDK 哈希未变。

实机操作与判定：设备运行 SOF 修复实验版、USB 连接 COM17；按已批准的 1 秒周期/2 秒超时/1 次重试运行真实观测桥接 60 秒。预期快照 ACK、显示 unknown、退出释放且音频健康。本次 56 轮/56 快照 ACK、7 个真实已观测会话、观测时间推进 8 次；通信错误、超时、解码错误、连接重建及设备拒绝均为 0，result=pass。

连接指示必须按增量解释：首个和末个协议样本 link_losses 均为 2（增量 0），reopens=0、bus_resets=0。这证明本次采样范围内没有新增连接丢失指示，不代表开机至首次采样没有变化；最初两次的实际原因未确认。前一恢复版记录 link_losses=8、一次重建，本次结果支持修复有效，但不是受控电气对照或长期保证。

83 个音频诊断样本 mic=ok、无 queued/dropped 非零，无 WDT/panic/意外串口唤醒；最大协议轮询 6188 µs、最大应答往返约 484 ms，均不是最坏耗时保证。最终 releaseConfirmed=true、local/unknown/lease=false，桥接退出并关闭串口。设备保留 SOF 修复实验固件，灯带未接管；真实语音识别、物理拔线和长期稳定仍待验证。

证据：本地 tmp/codex-monitor-probe/bridge-live-sof-fix-20261015.json、firmware-sof-install-20261015.json、firmware-sof-default-build-20261015.json、firmware-sof-native-20261015.json 及对应构建/烧录日志。安装收据记录五镜像 SHA256；本阶段未提交或推送。

下一步：补齐非 unknown 快照的端到端新鲜度规则和验证，再接灯光仲裁。当前未选新的状态有效期，不因 USB 通信健康自动把历史状态显示为红黄绿。暂不需要用户操作。


## 显式状态有效期候选 / Explicit freshness candidate

2026-10-15 主机链路已加入可选的状态有效期路径，默认桥接仍强制 unknown。只有同时提供 `--max-age-seconds` 和 `--process-bindings` 才能计算非 unknown：每轮重新读取原始 Hook 快照与绑定文件，并查询绑定的 PID、创建时间和程序路径。来源损坏/缺失、未来时间、观测过期、绑定缺失/失效都会降级 unknown；不会把旧样本的进程身份当作持久心跳。现有两个历史绑定在本次只读复核中均为 unknown，所以尚不能支持真实状态显示。

`SnapshotMapper` 现在从事件原始时间起计算剩余有效期，扣除视图生成后的耗时以及传输预留，再下发 `validForMs`；反复重读同一事件不能重置原事件的截止时间。传输预留由当前调用的串口写超时、应答超时及最多重试次数计算：`(write_timeout + reply_timeout) × (retries + 1)`。该计算覆盖按配置运行的发送/重试窗口，但 Python 调度停顿、驱动/USB 排队没有可证实的硬上限，因此目前不能宣称严格的端到端物理时限保证。

合成链路测试覆盖原事件随时间过期、预留扣减、缺失/失效绑定、默认 unknown、私有字段不出设备、参数必须成对给出。默认桥接仍强制 unknown，实验启用需显式传入 30 秒预算及新绑定；实机验证见下文。灯带未接管，SOF 修复版与回退镜像仍保留。

2026-10-15 用户确认事件有效期 30 秒，并授权短时 Hook 宿主采样及只读协议复测。采样前原采集器与仓库基线哈希一致；独立包装器获取 10 条 Pre/Post 观测并导出 1 个与当前快照匹配的会话→进程绑定，读取时再次确认其进程身份为 running。采样后按哈希恢复原采集器，Hook 配置与信任记录未改。旧的 2 个历史绑定本次检查均为 unknown，因此未沿用。绑定文件/进程路径保存在本地忽略目录，不发送到设备或报告。

设备状态 → 操作步骤 → 预期字段 → 实际结果 → 下一步：COM17、SOF 修复隔离固件、已确认 4096 字节/16 会话/5000 ms 租约；使用 30 秒事件预算、8 秒传输预留，按 1 秒周期、2 秒超时/1 重试进行两轮各 60 秒前台只读复测。预期 `[PROTO]` 无拒绝、ACK 先确认近期状态、旧事件约 22 秒后退回 unknown、退出 release 回 local，并检查 `mic`、`queued/dropped`、WDT。第一轮 56/56 ACK、零超时/重建，21 轮发送非 unknown 候选、末态 unknown；报告当时未记录 ACK 状态计数，因此这轮只能证明候选发送。

补充 ACK 计数后第二轮 55/56 ACK，设备实际确认 `working` 21 次、`unknown` 34 次；首个非 unknown ACK 为 02:47:51 UTC，首次回到 unknown 为 02:48:13 UTC，相隔约 22 秒。7 个已观测会话中仅 1 个有新绑定，`working` 只证明至少该会话近期被观测，不代表桌面所有会话的实时状态。通信错误/超时/解码错误/设备拒绝均为 0，但有一次新握手恢复，结果 `pass-with-recovery`；SDK link_losses 5→6、reopens 0→1、bus_resets 0，不能宣称连接波动已完全消失或归因为电气问题。最后 releaseConfirmed=true、local/unknown/lease=false，前台桥接退出。

第二轮 mic=ok，80 个音频诊断样本无 queued/dropped 非零，无 WDT/panic/意外串口唤醒；最大协议轮询 6570 µs，最大 USB 往返约 359 ms，均非最坏时延保证。设备未重刷，实际灯带控制未接入。原事件时间与预留能让已接收状态在本次受控时序下退回 unknown，但 Python 调度/驱动排队没有硬上限，尚不能宣称严格端到端物理时限保证。

证据：本地 `tmp/codex-monitor-probe/freshness-host-sample-install.json`、`freshness-host-bindings-summary.json`、`bridge-live-freshness-20261015.json`、`bridge-live-freshness-confirm-20261015.json`。当前临时 Hook 已恢复，30 秒参数仅显式实验使用；默认桥接继续 unknown。下一步是先解决可验证的全会话宿主关联/时钟时限，再设计手动、语音和监控灯光仲裁；USB 偶发重连需独立追踪。本阶段未提交或推送。

## 事件关联绑定实机复测 / Event-correlated binding run

2026-10-15 将可回退的绑定侧文件包装器接入现有用户 Hook，原采集器保留并先执行；没有改 `hooks.json` 或信任记录。短时恢复测试中，恢复后原事件使旧证明失效；随后持续启用包装器。当前 7 个快照会话中，1 个因真实 Pre/Post 配对得到 confirmed 宿主，其他 6 个没有新证据，继续 unknown。侧文件只含会话/轮次/调用 ID、事件时间及宿主身份，不发送这些 ID 或进程路径到设备。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：COM17、SOF 修复隔离固件，未重刷；沿用已批准的 4096 字节/16 会话/5000 ms 租约、1 秒周期/2 秒超时/1 次重试、30 秒观测预算及 8 秒传输预留，运行 60 秒前台只读桥接。预期 ACK 中近期观测为 working，约 22 秒后 unknown，退出 release 回 local；检查 `mic`、`queued/dropped` 和 WDT。实际 58/58 快照 ACK，设备确认 working 21 次、unknown 37 次，首次 unknown 距首次 working 约 22.3 秒；无通信错误、超时或本轮连接重建，releaseConfirmed=true，local/unknown/lease=false。83 个音频样本 mic=ok、无队列异常/WDT/panic/意外调试唤醒；本轮 SDK link_losses 7→7、reopens 1→1、bus_resets 0。最大 USB 往返约 516 ms、最大协议轮询 6570 µs，均非最坏保证。

报告：`tmp/codex-monitor-probe/bridge-live-event-bindings-20261015.json`。持续绑定解决了活跃会话的人工一次性绑定问题，但不能证明静默历史聊天在线，也未消除 Python 调度和 USB 排队的无界时延；因此 30 秒规则目前是有预留的实验策略，不是严格端到端安全时限。桥接默认仍 unknown，物理灯带控制未接入。下一步先界定可证明的设备接收时限/失联退回机制，再设计手动、语音与监控状态的灯光仲裁。

## 租约退回与单调年龄复核 / Lease fallback and monotonic age

2026-10-15 新增 `verify_fallback.py`，仅发送合成逻辑状态，不控制灯带。设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：COM17、SOF 修复隔离固件，未重刷；使用已确认的 30 秒有效期及设备返回的 5000 ms 租约，先发送 `working`，缓存下一条快照，保持连接但不发送命令直至租约结束，再发送缓存快照。预期返回 `connection-expired-reconnect-required` 和 `local/unknown/lease=false`，重新握手后释放；检查 `mic`、`queued/dropped`、WDT。实机静默约 5984 ms 后按预期拒绝迟到快照，最终 releaseConfirmed=true；mic=ok、无积压、WDT/panic 或调试唤醒。报告和串口记录为 `tmp/codex-monitor-probe/usb-fallback-20261015.json`、同名 `.log`。模拟回归 1 项通过。

主机 Hook 侧文件现记录单调事件时间；绑定视图和快照映射均按单调经过时间扣减 30 秒预算，时钟跳变模拟与原有测试通过。桥接仅允许带单调计数的 schema 2 事件绑定产生非 unknown；旧的 schema 1 手工绑定即使进程仍运行也不能点亮状态。用户级包装器已按哈希升级，原生命周期采集器和 Hook 定义未改。随后用真实绑定重复 60 秒只读 USB：56/56 快照 ACK，设备确认 working 21、unknown 35，首次 unknown 距首次 working 约 22.7 秒；零超时/本轮重建，最终 releaseConfirmed=true、local/unknown/lease=false。83 个音频样本 mic=ok、无队列异常/WDT/panic；SDK link_losses 8→8、reopens 1→1、bus_resets 0。报告 `tmp/codex-monitor-probe/bridge-live-monotonic-20261015.json`；未重刷、未控灯、无后台桥接。

当前单线程桥接发送前重算事件剩余时间并预留 8 秒；设备仅在 5 秒租约有效时接受下一条快照，静默更久的缓存帧不能重新取得控制。这一组合通过上述有限样本，但不等于任意客户端的协议级严格保证：协议仍允许独立心跳续租，设备无法自行验证主机上报的事件年龄；设备或主机卡死、计时器失效时，也不能保证物理灯光立即变化。开放物理灯带前，需要设计并测试设备挑战/快照关联或等效的端到端证明及失效策略。

## 设备挑战校验候选 / Device freshness challenge candidate

隔离实验构建可增加 `--freshness-challenge`，仅与 `--usb` 同时使用。设备在 welcome 中声明 `freshnessChallenge=true`；主机先发送 heartbeat，再读取绑定视图，对非 unknown 快照附上该心跳的 `challengeSeq`。设备只接受紧跟在成功心跳后的匹配序号；收到快照时，从 `validForMs` 扣除设备单调时钟上自心跳经过的时间。扣尽时 ACK 仍可成功，但设备显示 unknown。旧挑战、失败心跳、缺失序号和重复提交均不能续新鲜度；默认固件仍关闭此功能，未声明能力的设备只接收主机的 unknown 快照。

这能限制可信主机在读取视图到设备接收快照之间的排队和停顿，并防止独立心跳为旧快照重新计时。它不能让设备验证主机伪造的源事件时间，也不能证明静默历史会话正在工作；仍需 Hook 事件关联、进程身份及主机单调年龄检查。实际灯带尚未接管，实机结果须在烧录后单独记录。

2026-10-15 验证：`test_freshness_challenge.py` 5 项、桥接 24 项、协议 32 项、USB 客户端 7 项及 C++ 原生挑战校验通过；原生运行使用 ASan/UBSan。隔离配置 `tmp/codex-monitor-probe/protocol-usb-challenge.ini`，资源参数仍为 4096 字节、16 会话、深度 8、64 字节/轮、8192 字节 TX、1 ms 写等待、5000 ms 租约，并保留 SOF 修复。构建 RAM 66,384 字节（20.3%）、Flash 1,545,265 字节（29.5%）、模型 5 MiB。COM17（303A:1001）烧录五镜像均通过写入哈希校验；烧录前已按旧收据哈希备份 SOF 修复版五镜像至 `tmp/codex-monitor-probe/usb-rollback-before-challenge-20261015/`。新镜像和哈希见 `firmware-challenge-install-20261015.json`。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：设备运行挑战隔离版、COM17，仅逻辑快照不控制灯带；先送缺失挑战的合成 working、有效 heartbeat 与快照、续租后复用旧挑战，预期两次拒绝、一次 working ACK、最后 release 回 local。实测如预期，报告 `usb-challenge-check-final-20261015.json`。刚烧录后两次探测曾超时，设备随后输出带 `freshnessChallenge=true` 的 welcome；复测一次成功，初始超时原因未定。

随后按批准的 1 秒周期、2 秒超时、1 次重试、30 秒事件预算和 8 秒传输预留运行真实 Hook 桥接 60 秒：54/54 快照 ACK、零通信超时/解码错误/重连，设备 ACK 为 working 19 次、unknown 35 次，约 21.6 秒后退回 unknown；非 unknown 候选 20 次，设备有一次保守降级。最终 releaseConfirmed=true、local/unknown/lease=false，串口关闭；mic=ok，82 个音频样本无队列异常、WDT/panic 或意外调试唤醒，最大轮询 6849 µs、最大 USB 往返约 859 ms。设备协议 rejected=0；SDK link_losses 0→2、reopens 0，波动原因未定。报告 `bridge-live-challenge-20261015.json`。测试只证明当前有事件关联的会话，不能把其余历史会话说成实时在线；下一步先调查 USB 指示波动，再设计监控状态与手动/语音灯光仲裁。未提交或推送。

## USB 连接指示诊断 / USB link signal diagnostics

2026-10-15 源码复核：`link_losses` 只在 `Serial.isPlugged()` 从真变假时增加；该 SDK 值来自 SOF 观察，不是数据包丢失计数。协议层原样立即断开并依靠已批准的 5 秒租约退回。本轮只增加 `link_down_polls`、`last_link_down_ms`、`max_link_down_ms` 诊断字段，记录假值轮数及恢复时设备单调时钟经过的时间，不改变断线、重连、租约、灯带或阈值。原生传输测试检查两轮假值后的 2 ms 记录；ASan/UBSan 及现有协议/桥接回归通过。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：先用原挑战固件在 COM17 按已批准的 1 秒/2 秒/1 重试运行 60 秒 unknown 桥接；预期快照 ACK、release 回 local、监测 `link_losses/reopens/bus_resets`。实际 57/58 ACK、`link_losses` 3→4、`reopens` 0→1、无通信超时、释放确认；说明挑战路径并非指示变化的必要条件。随后保持串口打开 60 秒，只读日志、不发协议命令；`link_losses` 4→4、`reopens` 1→1，mic=ok，无积压/WDT。这些有限样本不能证明流量必然导致波动。

隔离诊断固件构建 RAM 66,416 字节、Flash 1,545,537 字节、模型 5 MiB；烧录前已按收据哈希备份挑战版五镜像至 `tmp/codex-monitor-probe/usb-rollback-before-gap-diagnostics-20261015/`。COM17 五镜像写入哈希均通过。烧录后首轮 60 秒 unknown 桥接 50/52 ACK，曾在启动握手附近超时并收到新 welcome，最终 releaseConfirmed=true；本轮未捕获新的假 `isPlugged`。不重刷的第二轮 57/57 ACK、零通信错误/重建，`link_losses` 0→0、`link_down_polls` 0→0，最终 local/unknown，mic=ok，77 个音频样本无积压/WDT。未触发的诊断字段不能解释此前波动；暂不更改立即断开行为。后续若再次出现，可据持续时间与 `bus_resets` 判断是否只是短暂 SOF 缺口。物理拔线、独立供电条件及长期稳定待验证；本阶段未控灯、未提交或推送。

本地证据：`bridge-usb-indicator-20261015.json`、`passive-usb-indicator-20261015.json`、`firmware-usb-gap-install-20261015.json`、`firmware-usb-gap-upload-20261015.log`、`usb-gap-native-20261015.json`、`bridge-usb-gap-20261015.json`、`bridge-usb-gap-repeat-20261015.json`。

## 监控灯光仲裁实机实验 / Monitor light arbitration

2026-10-15 当前 COM17（303A:1001，序列号 `仅本地收据保留`）运行**隔离实验固件**。只有显式启用 USB、设备新鲜度挑战及 `--monitor-lights` 的构建和前台桥接，才能让有效监控状态接管灯带。状态显示使用中心扩散灯：working 红 `(255,0,0)`、waitingApproval 纯黄 `(255,255,0)`、idle 绿 `(0,255,0)`。监控颜色只影响监控动画；原语音黄色和原本灯效保持原配置。语音灯光命令抢占后维持本地灯效，直到协议返回 local 或连接租约失效。unknown、offline、连接中断、租约结束及 release 均回到原本本地灯效。默认稳定构建关闭实验，默认桥接强制 unknown。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：烧录前保留上一隔离诊断版五镜像于 `tmp/codex-monitor-probe/usb-rollback-before-monitor-lights-20261015/`；纯黄版五镜像在 COM17 写入并逐一校验哈希。用前台合成状态依次发送 working、waitingApproval、idle、unknown，预期 `[LED] owner=monitor effect=center_expand status=...` 三次、随后 `owner=local`，最终 release 为 local/unknown。实测全部通过，最多往返 31 ms，mic=ok、无音频积压/WDT/panic；用户现场目视确认纯黄色扩散灯与恢复效果。原自动报告的 `visualVerified=false` 表示生成报告时尚未收到用户反馈，不应据此否定后续目视确认。安装收据 `tmp/codex-monitor-probe/firmware-monitor-lights-pure-yellow-install-20261015.json`，轮测报告 `monitor-lights-pure-yellow-final-20261015.json`。此前暖黄 `(255,160,0)` 被用户观察到偏红，现仅将监控黄色改为纯黄；未能取得暖黄版的精确闪存回读备份，已有更早诊断版回退镜像可用。

另一次合成实验验证在有效 working 后静默超过 5 秒租约会回到本地灯效，见 `monitor-lights-lease-20261015.json`。真实 Hook 前台桥接按已批准的 1 秒周期、2 秒 USB 超时、1 次重试、30 秒观测预算与 8 秒传输预留运行 60 秒：56/56 快照 ACK，设备确认 working 20、unknown 36，观测过期后有一次本地回退；最终 releaseConfirmed=true、local/unknown/lease=false。77 个音频诊断样本 mic=ok、无积压/WDT/panic，最大协议轮询 6641 µs；本轮 `link_losses` 1→1、无重握手。报告 `bridge-live-monitor-lights-20261015.json`。桥接已退出、串口关闭，无后台服务。稳定构建 RAM 57,852/Flash 1,532,045 字节；灯光实验构建 RAM 66,440/Flash 1,546,461 字节、模型 5 MiB；原生仲裁/动画 ASan、UBSan 与 Python 回归通过。

边界：真实 Hook 桥接本轮只覆盖有新事件关联的会话；语音命令抢占通过原生测试，尚未做真实语音实机抢占；未做物理拔线、色度测量和长期运行。烧录后初始握手曾两次失败，后续重试成功，原因待查。设备无法验证恶意主机伪造的原事件时间，5 秒租约也不是硬实时断电保护。下一步宜针对真实语音抢占、USB 短时波动和物理断线作独立实机验证；每次先确认设备当前固件/端口及回退镜像。

## 唤醒白色跑马灯 / White wake sweep

2026-10-15 先对上一纯黄版做真人语音接管：真实 Hook 前台桥接 60 秒，55/56 快照 ACK、working 20、unknown 35，记录一次 `owner=local reason=voice`；用户确认说完“老鼠狒狒”与“蓝色灯光”后立即变为蓝色常亮并保持。期间 USB 重握手一次，最终 releaseConfirmed=true、local/unknown/lease=false；78 个音频样本 mic=ok、无积压/WDT。报告 `tmp/codex-monitor-probe/bridge-live-voice-takeover-20261015.json`。用户同时指出唤醒瞬间会出现开机白色常亮：旧逻辑只进入语音监听，没有专属唤醒灯效，监控退回本地时便显示旧灯效。

当前已刷入新的隔离固件：唤醒词被接受后立即以**独立动画控制器**显示白色左右往返跑马灯，语音接管从唤醒开始；命令成功后结束临时提示，在保留的本地动效上执行命令，等待超时则恢复原本本地灯效。显式“跑马灯”命令仍默认绿色；唤醒提示不改写原本灯色/动效。稳定构建也包含唤醒提示，但监控灯光开关仍默认关闭。隔离构建 RAM 66,464/Flash 1,546,785 字节，稳定构建 RAM 57,876/Flash 1,532,361 字节，均生成 5 MiB 模型；原生仲裁/动画 ASan、UBSan 与 DeviceBridge 75 项 Python 检查通过。COM17 五镜像写入哈希校验完成，收据 `firmware-wake-white-sweep-install-20261015.json`；精确的上一纯黄版闪存回读未取得，早前隔离诊断版五镜像仍在回退目录。刷后第一次探测超时、第二次收到重开 welcome，第三次三色/unknown 轮测通过并 release，mic=ok、无队列积压/WDT；报告 `wake-white-sweep-postflash-lights-final-20261015.json`。

补充串口调试入口验证（不代替真人语音）：保持合成 working 快照，帧外发送 `w` 后持续更新协议 8 轮，日志按顺序出现监控红色扩散、`owner=local reason=voice`、`owner=voice effect=sweep color=white`、5 秒命令等待超时与 `owner=local reason=voice-ended`；监控在当前连接中没有抢回灯带。最终 release 确认，mic=ok，无音频积压/WDT；报告 `wake-white-sweep-debug-probe-20261015.json`。

真人语音复测（同日）：按 1 秒周期、2 秒超时、1 次重试、30 秒观测预算/8 秒传输预留运行 60 秒，设备收到 56/56 快照 ACK，working 40、unknown 16；串口识别 ID `1` 和 `6` 各一次。用户确认“红色扩散→白色跑马→蓝色常亮”实际观感符合预期。最终 releaseConfirmed=true、local/unknown/lease=false；79 个音频样本 mic=ok、无 queued/dropped 非零或 WDT/panic，最大轮询 20,990 µs；本轮 `link_losses` 9→9、无重握手/超时。报告 `bridge-live-wake-sweep-20261015.json` 原值 `wakeSweepStarts=0`、`voiceLedTakeovers=0`、`ledColorCommands={}` 为主机日志解析器未剥离串口行尾 `CR` 所致假阴性，不能据此否定用户目视；已修正解析并用原始调试日志回放确认这些计数各为 1，75 项桥接回归通过。该次真人串口原始日志未另存，因此不能反写原报告计数。当前桥接已停止、端口已关闭，无后台任务；长期稳定和物理拔线仍待验证。

## 刷机后握手与物理拔线 / Post-flash handshake and physical unplug

2026-10-15 对照三次刷后日志：第一次探测 4.1 秒内无欢迎帧；第二次在设备约 24 秒启动进程中收到同一 `boot`、多个不同 `channel` 的欢迎帧以及 `wrong-connection` ACK；第三次握手和灯光轮测通过。固件的协议轮询在语音初始化完成后进入主循环，积压探测会使较早的 welcome 立即过期。主机 `usb_client.py` 现读取已有缓冲中的最新 welcome；若 ACK 明确表明当前通道已更换，则立即要求重握手，不再等完整超时。`test_usb_client.py` 新增双欢迎帧和旧通道 ACK 回归；DeviceBridge 全套 77 项通过。启动耗时和 USB 短时波动仍可能造成首次探测超时；本改动不调整已批准的 2 秒超时/1 次重试，也不改固件。

设备状态 → 操作步骤 → 预期日志 → 实际结果 → 下一步：COM17（303A:1001）运行白色唤醒跑马灯隔离固件，设备带电池供电；主机以 1 秒周期发送合成 working 挑战快照，预期红色中心扩散，拔 USB 后 `owner=local reason=fallback`、`link_losses` 增加并保持设备开机，插回后新通道握手、`local/unknown/lease=false`。实际拔线前 27 次快照确认，主机捕获 `SerialTimeoutException`；用户目视确认红色扩散退回白色本地初始灯且设备继续运行，插回后仍为白色。重插串口首行含 `[LED] owner=local reason=fallback`，`max_link_down_ms=8694`、`link_losses=3`、`bus_resets=3`（包含本轮此前短暂波动，不能全归于这一次拔线）；`boot` 未变，`channel` 更新，release 确认，`mic=ok`、`queued=0/dropped=0`、无 WDT/panic。证据 `tmp/codex-monitor-probe/physical-unplug-20261015.json/.log`、`physical-replug-20261015.json/.log`。自动报告的 `visualVerified=false` 产生于用户回复前，目视确认以其后回复为准。当前端口关闭、设备本地灯效运行；物理回退只证明这次电池供电条件，长期稳定仍待持续观察。

## 局域网无线迁移候选 / Local-network transport candidate

用户确认电脑与 OmiPet 通常在同一局域网，先规划本地直连，不引入云中继；首次配对采用设备屏幕显示一次性码，日常不要求 USB。当前固件仅有 Wi-Fi STA/配网与 USB 协议入口；`websocket_text()` 只是编码工具，尚无网络连接或认证。已安装的 ESP-IDF 4.4.7 提供 [WebSocket HTTP 服务端](https://docs.espressif.com/projects/esp-idf/en/v4.4.1/esp32/api-reference/protocols/esp_http_server.html)、[mDNS 服务发现](https://docs.espressif.com/projects/esp-idf/zh_CN/v4.4.7/esp32/api-reference/protocols/mdns.html)和 [HTTPS 服务端](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-reference/protocols/esp_https_server.html)，但本项目 `sdkconfig` 尚未开启 WebSocket/HTTPS。官方 HTTPS 文档估算单个加密连接约需 40 KB RAM；必须在语音负载下实测内存、延迟和重连。

候选分层：主机 WebSocket 适配器复用 `HostSession` 和有界 JSON；固件网络适配器复用 `ProtocolSession`，不直接复用带串口帧解析的 USB 传输类。Wi-Fi 仅在 STA 已连接时启动，断网或配网期间关闭并回本地灯效。设备发现可用 mDNS，地址变化不能改变设备身份。现有 `boot/channel/session` 是防旧连接标识，不是认证；屏幕一次性码须与设备身份校验和安全凭证建立关联，不能只在未加密连接中发送短码。码长、有效时间、尝试次数、TLS/证书校验与 USB/Wi-Fi 同时连接的控制权规则待确定并验证；此前网络实验不能接受非 unknown 灯光状态。此节为规划，未构建、未刷写、未实机验证。

## 30 分钟 USB 持续运行 / Thirty-minute USB run

目标：在现有隔离固件上观察正常连接时的重握手和设备健康，不改变灯效。设备状态与操作：COM17（303A:1001）、电池与 USB 均连接；默认桥接强制发送 unknown，按已批准的 1 秒周期、2 秒 USB 超时、1 次重试运行 1800 秒，退出时 release；未刷机、未开启无线服务。预期报告字段：`acknowledgedSnapshots`、`connectionResets`、`communicationErrors`、`usbDiagnostics.replyTimeouts/decodeIssues`、设备 `link_losses/reopens/bus_resets`、`mic/queued/dropped/task_wdt` 与最终 `releaseConfirmed`。

实际 2026-10-15 13:36:15–14:06:15（北京时间）：1685 轮、1678 个快照 ACK，全部设备显示 unknown；7 轮遇到新通道并自动重连，主机完整超时/解码错误/其他通信错误均为 0，结果 `pass-with-recovery`。首末设备计数 `link_losses` 4→11、`reopens` 0→7、`bus_resets` 3→3、`link_down_polls` 8373→8390；和 7 次重连数量一致，但本报告未保存每次断线时间，不能断言每一对计数的精确事件对应或电气原因。`rejected/stalled/stale/write_failures` 增量均为 0；1812 个音频样本 `mic=ok`、无 queued/dropped 非零、WDT/panic 或意外调试唤醒，最大已观察协议轮询 10,379 µs、USB 往返 953 ms，均非最坏保证。最终 `releaseConfirmed=true`、`local/unknown/lease=false`，进程与串口均已关闭。报告 `tmp/codex-monitor-probe/bridge-soak-30min-20261015.json`。下一步先诊断 7 次短暂 USB 指示变化，不能据此宣称长时稳定；无线局域网路线仍是规划，稳定固件不受影响。

## USB 连接指示时间戳 / Timestamped USB link diagnostics

`bridge.py --protocol-trace <新文件.jsonl>` 可将收到的 `[PROTO]` 日志解析为逐行 JSON：主机接收 UTC 时间、仅设备数字计数和相对上一条的增量。它不保存原始串口行、对话内容或会话身份，也不改变 USB 超时、重试、租约或设备断线回退。每条时间戳是**主机收到日志的时间**，并非设备实际断线瞬间；固件每约 2 秒报告一次，连续多次波动可能合并在一次增量中。

2026-10-15 COM17（303A:1001）试跑 60 秒，57 轮、56 个 unknown 快照 ACK，1 次自动重连；`link_losses` 14→15、`reopens` 7→8、`bus_resets` 保持 3。14:14:05 北京时间收到的样本记录两次 `link_down_polls` 与 `last_link_down_ms=5`，无完整应答超时、解码错误、音频积压或 WDT，最终 `releaseConfirmed=true`、`local/unknown/lease=false`。这证明至少一次短暂连接指示缺口及既有恢复路径；不能凭 `bus_resets` 未变断言 USB 总线或线缆完全无问题，也不能把先前 7 次都推定为同一原因。报告和逐条证据为 `tmp/codex-monitor-probe/bridge-trace-smoke-20261015-141312.json`、`protocol-trace-smoke-20261015-141312.jsonl`。后续如需量化发生率，再按同参数重复长测；当前不调整断线宽限阈值。

## 屏幕一次性码配对候选 / On-screen one-time pairing candidate

用户明确选择设备屏幕显示**随机 6 位数字一次性码**，而非 16 位 Base32 校验码。本地 SDK 有 ESP-IDF 4.4.7 的 [HTTPS 服务端](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/protocols/esp_https_server.html)、[HTTP WebSocket](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-reference/protocols/esp_http_server.html) 和 mDNS；目前 `CONFIG_ESP_HTTPS_SERVER_ENABLE`、`CONFIG_HTTPD_WS_SUPPORT` 均未启用。当前安装的 ESP-IDF `protocomm` 源码仅含 `security0.c` 与 `security1.c`，没有后续版本的 SRP6a `security2.c`；[现行官方文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/provisioning/protocomm.html)将 Security 2 的 SRP6a/AES-GCM 作为推荐生产方案。不能把 6 位码直接通过未经认证的 TLS/HTTP 发送，或仅凭 `boot/channel/session` 授予控制权。

对安装版 `security1.c` 的推断：它用共享 ECDH 值异或短码的 SHA-256 结果作 AES-CTR 密钥，再用已知公钥作握手校验。若对端是假设备并掌握其所选 ECDH 私钥，收到校验密文后可能在本地枚举全部 6 位码；因此不将当前 Security 1 + 六位 PoP 直接视为安全配对实现。后续须以正式威胁模型和独立测试复核此推断。

候选路线是隔离评估经审查的短码 PAKE；配对成功后发放并保存设备/电脑双方的长期身份，日常在认证后的 TLS/WSS 上传输现有有界协议。mDNS 仅负责发现地址，不提供身份保证。用户已确认配对码**5 分钟有效、最多 5 次失败后关闭**；只有尚未配对的设备在重启后自动开启新窗口，已配对设备重启不显示新码。双连接时 USB 有效监控会话优先，USB 退出后才允许已认证且租约有效的 Wi-Fi 会话接管；语音仍优先。评估移植 SRP6a 时须核对[官方 Security 2 安全公告](https://github.com/espressif/esp-idf/security/advisories/GHSA-9r76-858f-v6jh)，不能直接复制旧版本。HTTPS 官方文档给出单连接约 40 KB RAM 的参考值。稳定固件和当前设备均没有局域网监控服务。

2026-10-15 隔离进展：`Firmware/include/pairing_code.h` 可把合格随机 32 位字无模偏差地映射为补零六位码，拒绝超出均匀采样区间的值；**不负责提供随机源**。设备端实际生成须在 Wi-Fi RF 已启用时使用 [ESP32-S3 硬件随机数](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32s3/api-reference/system/random.html)并重取被拒样本。`pairing_window.h` 仅管理已批准的时限/次数，不接收明文码，也没有任何网络入口：第五次失败锁定，证明超时和时钟倒退均拒绝成功。原生 ASan/UBSan 测试 6 项通过，报告 `tmp/codex-monitor-probe/pairing-window-native-20261015.json`。

现有 Mbed TLS 2.28.7 虽未启用，但包含底层 EC J-PAKE。只在 WSL 主机上临时编译该原语，9 项离线探针通过：库自检、相同六位码及证书指纹的双方密钥确认、错误码或指纹确认失败、畸形轮次拒绝、第五次正确证明与窗口联动，以及日常认证向量、连接门禁和 HKDF 派生。报告 `tmp/codex-monitor-probe/pairing-ecjpake-probe-20261015.json`，探针代码 `tests/native/pairing_ecjpake_probe.cpp`；没有启用 TLS EC J-PAKE 套件、固件构建、刷写、网络监听或真实屏幕显示。[2026 年 TLS EC J-PAKE 公告](https://mbed-tls.readthedocs.io/en/latest/security-advisories/mbedtls-security-advisory-2026-07-tls12-ecjpake-serverkeyexchange-oob-read/)明确列出 2.28.7 不受该特定问题影响，但[该 2.28 分支已不在维护名单](https://github.com/Mbed-TLS/mbedtls/blob/development/BRANCHES.md)；原语探针不等于完整配对安全审查。仍需核对设备端实现/资源、随机源、网络报文边界、双方长期身份、持久化、重放/断网及音频负载后才能开放无线控制。

新增隔离的 `Firmware/include/pairing_boot.h`：引导时传入可信电脑身份的三态读取结果；只有明确确认“未配对”且屏幕、硬件随机数、认证服务全部就绪时才抽取码并开启本次启动唯一窗口，读取失败或记录损坏时关闭配对。超时、5 次失败或证明通过且长期身份已安全保存后立即隐藏并清除内存码，同一次运行期不能重置启动入口；再次重启仍未配对才产生新码。`OmiPetUi::setPairingCode()` 提供中央卡片的六位码和倒计时绘制，隐藏后恢复时钟。**当前没有调用这些入口，也没有凭证读取、真正的设备随机源或无线认证服务**，因此设备仍不会显示配对码；不能把离线状态机说成实际无线配对完成。原生检查报告 `tmp/codex-monitor-probe/pairing-boot-native-20261015.json`。

新增隔离的 `Firmware/include/monitor_transport_arbiter.h`：只有 USB 的监控会话及租约仍有效时才保持 USB 优先，即使 USB 状态为 unknown 也不让 Wi-Fi 覆盖；USB 退出后，仅已认证且仍有租约的 Wi-Fi 会话可被选中，随后复用现有灯光仲裁，语音接管继续优先。USB 恢复活动会话后重新优先。`monitor_transport_native.cpp` 四项 ASan/UBSan 检查通过。当前 USB 主循环仍按原单通道运行；无线连接/认证来源未实现，选择器尚未接线。

2026-10-15 身份校验边界：用户将无线安全目标明确为**防局域网冒充**，不要求抵御读取设备 Flash/NVS 的物理攻击。现有配置的 Flash/NVS 加密均关闭；本阶段不烧 eFuse，也不改变这些配置。隔离新增 `Firmware/include/pairing_auth_proof.h` 和 `pairing_auth_gate.h`：在 TLS 连接就绪后，使用配对产生的 32 字节长期密钥、双方各 32 字节新随机数和设备证书 SHA-256 指纹计算区分主机/设备角色的 HMAC-SHA256 证明；只有主机证明正确的**当前连接**才可标记 `authorized()`，断连或失败清除状态及内存密钥。主机侧 `pairing_auth.py` 提供相同证明和证书 DER 指纹校验；主机必须先核对实际 TLS 证书，再发送任何协议数据。设备适配器仍须确保每条连接重新生成不可预测的设备随机数、验证主机证明并在解析 JSON 前检查门禁；mDNS 地址和协议 `boot/channel/session` 均不能替代认证。

这只是待接入的认证原语；后文虽有隔离的 TLS 身份生成和存储代码，设备上仍未生成或保存 TLS 证书、长期密钥，也没有完成实际 EC J-PAKE 会话到凭证的接线、网络握手、无线监听或固件资源验证。隔离的 `pairing_key_derivation.h` 与 Python 同伴使用标准 HKDF-SHA256，以 PAKE 共享秘密、握手记录摘要及证书指纹派生 32 字节日常密钥；双方确认计算也绑定指纹。后续应完成**经 PAKE 双方确认后**的实际凭证写入，再接入受 TLS 与认证门禁保护的 WebSocket；在这些边界完成前不能发送非 unknown 监控状态或声明无线可用。

2026-10-15 凭证存储边界：新增跨主机/设备共用的 101 字节 v1 记录（版本、32 字节日常密钥、32 字节设备证书指纹、SHA-256 损坏校验）。校验和只用于发现意外损坏，**不提供物理篡改防护**，与用户限定的防局域网冒充目标一致。主机 `pairing_credentials.py` 接受调用者显式指定的路径，用同目录临时文件和原子硬链接发布一次；已有或损坏文件不会被覆盖，读取失败为 unknown。设备 `pairing_nvs_store.cpp` 仅访问 `omipet_pair/identity`，不擦除 NVS，也不触碰 Wi-Fi 命名空间；先查询固定长度再解码，任何 NVS 错误、截断或摘要错误为 unknown，首次写入后提交并回读，已有记录拒绝覆盖。[ESP-IDF 4.4.7 NVS 文档](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/storage/nvs_flash.html)说明其可从断电中恢复，但正在写入的新键可能丢失；这一条不等同本设备已完成断电实测。

代码尚未接入启动或配对完成路径，**当前设备 NVS 中没有被本步骤写入凭证或 TLS 身份**。运行时必须先验证可用的 TLS 证书/私钥及其指纹，再把凭证 `Present` 传给 `PairingBoot`，并只在 PAKE 双方确认后写记录；如果提交结果不明确，应关闭本次配对窗口并只读核对，不能继续开放服务。`pairing_identity_state.h` 在电脑凭证缺失、TLS 身份缺失或已验证时判“未配对”，允许先生成设备 TLS 身份再打开首次配对；孤立凭证、TLS 损坏/读错或指纹不符均判 unknown，不会自动开码。

2026-10-15 隔离新增 `pairing_tls_identity.cpp`：由调用方提供可信随机源、UTC 有效期及缓冲容量，生成 P-256 ECDSA 自签 DER 证书和私钥，计算完整证书 SHA-256 指纹；读取时复核指纹、DER 和公私钥匹配。`pairing_tls_store.cpp` 将证书和私钥作为单条 `omipet_tls/identity` NVS 记录一次写入、提交并回读；长度、摘要、DER 或密钥不符及 NVS 错误均为 unknown，已有记录不覆盖，私钥临时缓冲在释放前清零。硬件随机源适配器须在 Wi-Fi RF 提供真实熵后接入；测试用的有效期和缓冲容量不是产品参数。没有运行时调用、无线端口或屏幕配对入口，也没有刷机。密码、凭证、TLS 与 NVS 原生探针共 22 项通过；主机测试 85 项通过。以当前 ESP32-S3 编译数据库和安装版 IDF 头文件分别单独编译 `pairing_nvs_store.cpp`、`pairing_tls_identity.cpp`、`pairing_tls_store.cpp` 成功；因未加入 `Firmware/src/CMakeLists.txt`，这**不是完整固件构建或实机验证**。下一步需将可信 RNG、引导读取及 PAKE 成功后的两端凭证提交接入，再完成 TLS/WSS 身份与连接门禁；在端到端验证前无线控制保持关闭。

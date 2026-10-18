# Codex 状态采集实验 / Codex lifecycle monitor

Windows 主机端工具，读取 Codex Hook 的生命周期 JSON，按会话、轮次和工具调用 ID 保存状态。只使用 Python 标准库，需要 Python 3.10 或更新版本。

本目录负责状态来源，不实现设备传输、灯带驱动或桌面气泡；相关设备功能见根目录 README。已有快照不能当作持续在线的证明。以下带日期的实验记录保留各次验证边界，后续结果以最新现状及 Git 历史为准。

## 文件 / Files

| 文件 | 职责 |
| --- | --- |
| `collector.py` | UTF-8 输入、Windows 互斥锁、审批关联及原子快照写入 |
| `make_hooks.py` | 只向标准输出生成配置，不修改用户设置 |
| `audit.py` | 只读诊断与按会话、轮次检查 |
| `state_view.py` | 独立的只读失联策略候选，不安装到 Hook |
| `process_probe.py` | 只读核对 Windows 进程身份及退出信号，不推断会话状态 |
| `host_observer.py` | 从 Hook 进程的父进程链采集独立宿主证据 |
| `host_sample_collector.py` | 临时采样包装器，先执行原生命周期采集再隔离记录证据 |
| `host_bindings.py` | 按同会话/轮次/调用的 Pre/Post 配对生成候选绑定 |
| `bound_collector.py`、`host_binding_sidecar.py` | 可选的事件关联侧文件；原采集器先执行，失败时不阻断生命周期采集 |
| `tests/test_approvals.py` | 隔离目录内的生命周期、隐私及多进程回归 |
| `tests/test_audit.py` | 缺失来源、目标隔离、损坏行及审批覆盖率测试 |
| `tests/test_state_view.py` | 静默、过期、损坏、时钟异常及只读性测试 |
| `tests/test_process_probe.py` | 进程身份、PID 重用、访问失败及真实隔离子进程测试 |
| `tests/test_host_observer.py` | 父进程链、采样隐私、失败隔离及绑定冲突测试 |
| `tests/test_host_binding_sidecar.py`、`test_bound_collector.py` | 事件精确匹配、迟到事件、宿主变更及真实父进程/原采集器回归 |

## 安装 / Setup

普通 Windows 用户使用完整 Omi 发布包中的首次监控向导，见 [快速开始](../Desktop/QUICK_START.md)。下面的 Python 手动安装流程保留供开发者调试和历史部署维护。桌面包使用内置运行环境执行同一生命周期/绑定逻辑，安装后的就绪检测必须等待真实新事件；不会自动授予 Hook 信任。

1. 备份已有 `~/.codex/hooks.json`，以及已有的 `~/.codex/hooks/omipet-monitor/collector.py`。保留旧状态目录作为回退证据。
2. 将本目录的 `collector.py` 复制到 `~/.codex/hooks/omipet-monitor/collector.py`。
3. 在仓库根目录运行以下命令，生成与当前解释器、安装路径对应的配置预览：

```powershell
$monitorCollectorPath = Join-Path $env:USERPROFILE '.codex/hooks/omipet-monitor/collector.py'
python Tools/CodexMonitor/make_hooks.py --collector $monitorCollectorPath
```

生成的配置包含 8 个事件。将这些处理器合并到用户级 `hooks.json`；已安装本工具时更新对应处理器，避免重复注册。保留其他工具的 Hook，不覆盖整份现有配置。处理器使用绝对解释器和脚本路径；更换 Python 或移动脚本后需要重新生成。

4. 在 Codex 中审查并信任新定义。官方 CLI 入口为 `/hooks`；安装配置不代表已经受信任。不自动修改信任记录或使用信任绕过参数。
5. 在正常聊天中验证新事件。审批只观察用户自行处理的请求，不自动批准、拒绝或制造危险操作。

默认 `SessionStart`、`Stop`、`SessionEnd` 同步执行，其他事件异步执行；超时为 3 秒。异步事件可能乱序，不能将接收顺序当成操作发生顺序。另见 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。

## 本地数据与隐私 / Local data and privacy

默认目录：`%LOCALAPPDATA%/OmiPet/codex-monitor-probe-v2`。可用进程环境变量 `OMIPET_CODEX_MONITOR_DIR` 改到隔离目录，测试使用此方法，不写真实状态。

- `events.jsonl`：收到的生命周期元数据及处理结果。
- `sessions/*.json`：各会话的轮次和工具关联状态。
- `snapshot.json`：已观测会话的汇总。
- `collector-error-<PID>.json`：失败时间和异常类型，不写原始输入或异常中的敏感内容。

只保存会话/轮次/工具 ID、事件、工作目录、权限模式和派生状态。不保存提示词、工具入参、回复、凭证或命令指纹。工作目录和 ID 本身仍是本地元数据，不应将这些日志、快照、配置备份或个人安装收据提交到 Git。

采集器退出时不向标准输出返回决策；采集失败也不会代替用户审批。

## 状态与边界 / States and limits

| 状态 | 含义 |
| --- | --- |
| `working` | 有尚未结束的已观测轮次 |
| `waitingApproval` | 存在已观测的待审批或待选项回复 |
| `idle` | 已观测轮次收到结束/中断，且没有其他未结束轮次 |
| `offline` | 收到 `SessionEnd` |
| `unknown` | 来源不足、关联不明或缺失必要标识 |

`PermissionRequest` 提供调用 ID 时，只允许同一轮次、同一调用的 `PostToolUse` 清除对应项。普通工具的开始、其他工具的完成、旧轮次的结束均不会清除它。

本机实测发现，`request_permissions` 工具的窗口可以进入 Desktop 的 `waitingOnApproval`，却不触发 `PermissionRequest` Hook。因此还将这个工具的 `PreToolUse` 作为审批开始，通过相同调用 ID 的 `PostToolUse` 解除。

通用 `PermissionRequest` 不保证提供调用 ID。缺失时，后续工具活动不能证明是哪一项审批结束，状态会降级为 `unknown`/`approvalUnconfirmed`，直到本轮结束。`PostToolUse` 只证明调用已返回，不能单独推断用户批准还是拒绝。

按轮次保留已结束记录，可阻止迟到事件复活旧任务。记录尚未自动裁剪。汇总只覆盖已观测会话，不能代表 Desktop 所有聊天。采集器尚无心跳或进程退出恢复；长时间没有新事件不能证明空闲或仍在线。下面的独立视图仅提供候选显示策略。

## 只读失联策略候选 / Read-only source policy candidate

`state_view.py` 不改写日志或快照，不修改安装与信任配置。它将历史观测和候选显示状态分开：

| 输出 | 含义 |
| --- | --- |
| `lastObservedStatus` | 快照中的最后观测，过期后仍保留 |
| `observationAgeSeconds` | 当前时间与该会话观测时间之差 |
| `displayStatus` / `reason` | 候选显示状态及其依据 |
| `sourceState=readable` | 文件可读，不代表 Codex 或采集器在线 |
| `liveness=unverified` | 当前没有持续存活证据 |

CLI 默认未设置新鲜度策略，各会话显示 `unknown`，不会将历史红/黄/绿作为当前状态。调用方可显式传入正数 `--max-age-seconds`；测试中的 10 秒仅为合成边界测试。`read_bound_view` 保持该保守行为。桌面专用 `LifecycleReader` 只在近期、精确事件证明且宿主存活时接纳生命周期；后续没有新 Hook 仍保持工作/等待，独立评估传输有效期，不改写事件时间。来源不可读、身份/证明变化或宿主失效会清除接纳记录，重开监控不会接纳过期历史。它不证明具体聊天存活；漏掉 Stop 而宿主仍存活时可能保留旧状态。

2026-10-16 一致性修复：`bound_collector.py` 在原有同目录互斥锁内完成生命周期与侧文件发布，桌面读取同样持有这把锁，避免新快照配上旧证明而短暂降级。锁的原有 1 秒等待上限不变；无法取得锁时仍显示 unknown 并清除延续资格，不沿用未核验状态。桌面后台和已安装包装器需配套更新；只升级其中一个不能保证一致性。并发回归已先复现旧实现读到半次发布，再验证新实现等待完整发布后读到结束状态；此前 30 分钟的 3 次 unknown 缺少逐次原因，不能全部归因于这一竞态。

`request_user_input` 的 Pre/Post 对应等待/回复完成；`request_user_input_async` 的 Post 只表示窗口已创建，等待需保留到 `UserPromptSubmit` 中对应 `send_user_message_question_reply` / `questionItemId` 回复，或中断/会话结束。待回复跨 Stop 保留，防止创建选项后结束本轮便错误变绿；其他工具调用与无关联文本不清除它。同一聊天继续执行时显示 working，只有没有正在执行的轮次而仍有异步待回复问题时显示 waitingApproval；真实权限审批和同步输入仍优先显示 waitingApproval。不同聊天之间仍保持等待优先。自由输入选项使用同一回复关联，不保存问题、选项或回答文本。该应用回复格式来自本机实测，非通用 Hooks 稳定协议；格式改变需重新验证。[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks) 的工具返回事件不能等同异步人工回复。

每个会话分别计算年龄，不使用全局快照生成时间刷新其他聊天。超期、未来时间、缺少时区或非法记录均显示未知；静默不会产生 `Stop`、`idle` 或 `offline`。汇总保留等待审批、工作、未知、空闲、离线的优先级，未知会阻止仅凭另一个空闲会话显示全局空闲。

```powershell
python Tools/CodexMonitor/state_view.py
python Tools/CodexMonitor/state_view.py --source-unavailable
python Tools/CodexMonitor/tests/test_state_view.py
```

`--source-unavailable` 由调用方在已有独立失联证据时传入；该工具不探测或终止进程。来源缺失或损坏时同样返回未知，并给出来源原因；不尝试修复真实数据。

2026-10-14：状态视图 16 项、进程探针 10 项、宿主观测/绑定 16 项和审计 5 项测试通过，其中包括 Windows 隔离子进程真实退出及联动降级。开启宿主采样后的包装器还通过 52 条生命周期事件和 6 会话并发回归，最长单次约 0.281 秒。视图尚未接串口或灯带；不能宣称真实 Codex 会话异常退出已被自动识别。

## 进程证据候选 / Process evidence candidate

`process_probe.py` 通过 Windows 的查询和同步权限读取进程，不读取命令行、环境变量、内存或登录资料，不终止被观察进程。身份由 PID、原始 100 ns 创建时间字符串和完整映像路径共同组成；创建时间使用字符串以免 JSON 数值精度损失。

核对使用同一个进程句柄读取创建时间与映像，并零等待检查退出信号。PID 重用、映像变化和访问失败均不能刷新原来源。进程退出或无法确认时显示未知；进程存活只表示主机进程存在，不证明聊天正在工作、Hook 正常或 UI 有响应。实现依据见 Microsoft 的 [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)、[QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew) 与 [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)。

入口：`process_probe.py --capture-pid <明确选择的PID>` 仅打印身份；`process_probe.py --identity <身份文件>` 重新查询该身份。生成的身份文件包含个人程序路径，不提交 Git。工具不按进程名自动选择宿主。

状态视图支持 `--process-bindings <绑定文件>`，格式如下，所有值均需由实测填写，不能照抄示例：

```json
{
  "schema": 1,
  "sessions": {
    "<已验证的session-id>": {
      "pid": 123,
      "creationTime100ns": "<capture返回的精确字符串>",
      "imagePath": "<capture返回的完整路径>"
    }
  }
}
```

每次读取视图都会重新查询对应进程，不信任旧的探针结果文件。缺失或非法绑定会降级未知；绑定进程运行也不能绕过缺省策略、观测过期或独立失联证据。这是附加的失效检查，不会把历史观测升级成实时状态，也不改写 Hook 日志。

## 真实 Hook 宿主采样 / Live Hook launcher sampling

`host_sample_collector.py` 是独立实验包装器。它优先加载同目录保存的 `lifecycle_collector.py`，仓库内运行时回退到原 `collector.py`；先完成原有采集，再读取同目录的 `host-observer.json`。未放置配置时不采样；采样配置/查询失败也不改变生命周期结果或标准输出。配置需明确给出 `enabled`、程序完整路径列表 `allowedImages` 和独立的绝对 `outputDirectory`。

父进程链通过只读 Windows Toolhelp 快照获得，再逐个核对创建时间、完整映像路径和存活状态。父进程比子进程新、链循环或查询期间身份变化时拒绝关联；只接受路径列表中最近的祖先进程。这里只证明 Hook 的启动来源，不代表进程独占会话或会话仍在运行。实现依据见 [PROCESSENTRY32W](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w) 和 [CreateToolhelp32Snapshot](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)。

每条样本使用独立随机文件名，只保存会话/轮次/调用 ID、事件、时间与祖先进程的 PID/创建时间/路径。样本可能包含个人目录，须保存在本地，不提交 Git。旧 `events.jsonl` 和快照格式不增加字段。

2026-10-14 19:27–19:28 的短暂真实采样得到 2 个会话、9 条 Pre/Post 事件；9 条均为 `Python → PowerShell → 同一个 codex.exe`。原采集器随后按 SHA-256 恢复，Hook 定义及信任记录未改，未安装持续后台任务。不同会话共享同一宿主，不能将进程当作聊天的独立心跳。第二个同名进程未因名称相同而被绑定。

`host_bindings.py --observations <样本目录>` 只向标准输出生成候选。每个会话须有同轮次、同调用 ID 的 Pre/Post 配对，且该批样本中的宿主身份一致；重复开始、其他调用/轮次的完成、未知或冲突宿主均不能满足绑定。损坏的输入使整个输入失效。输出保留配对证据数，`sessionLiveness` 始终未验证。

该批真实样本生成 2 个候选绑定，分别含 1 和 2 组工具配对。只读接入状态视图时两个宿主查询均为 running；没有观测有效期策略，汇总仍是 unknown。候选未启用持续采样，绑定只覆盖已观测的启动来源，不能外推到所有历史聊天或重启后的新来源。

## 持续事件绑定 / Event-correlated bindings

2026-10-15 起，用户级 Hook 的 `collector.py` 使用 `bound_collector.py` 包装原生命周期采集器，Hook 定义未改。原脚本另存同目录 `lifecycle_collector.py`，原件备份及收据在 `tmp/codex-monitor-probe/live-binding-probe.json`。只允许本机实测的 Codex 程序完整路径，最多 16 个当前快照会话；这些参数仅用于已批准的隔离实验。侧文件位于原状态目录的 `host-bindings.json`，不会写入提示词、工具参数或串口消息。包装器出错不改变原采集结果。

同一会话、轮次及工具调用的 `PreToolUse`/`PostToolUse` 必须来自同一个经查询的父进程身份，才会标记 confirmed；之后每次事件还需与刚写入的原始时间、事件、轮次、调用 ID 以及 `applied=true` 精确对应。身份变化须重新配对，`SessionEnd` 删除该绑定。视图每次读取重新检查进程身份与最新事件证明；未覆盖的历史会话、迟到事件、损坏证据和过期事件均显示 unknown。进程存在仍不证明聊天持续运行。

短时实机接入前，隔离目录内的 52 条原采集事件回归及真实 Windows 父进程测试通过；真实 Hook 形成 1 个 confirmed 绑定，随后用它完成 USB 只读复测。持续绑定只会随新 Hook 事件逐步覆盖当前会话，不能补造没有新事件的另外 6 个历史会话。设备通信及 30 秒预算结果见 [DeviceBridge](../DeviceBridge/README.md)。恢复原采集脚本可运行 `python tmp/codex-monitor-probe/live_binding_probe.py restore`；恢复会核对当前包装器及备份哈希，不修改 Hook 定义。恢复后下一次原始事件会使旧侧文件证明失效。

USB/Wi-Fi 共用消息协议及真实观测桥接见 [DeviceBridge](../DeviceBridge/README.md)。USB 实验固件已于 2026-10-14 授权烧录；`bridge.py` 可在前台持续读取本工具的原有快照，将临时别名和最后观测状态发送到设备，停止时尝试释放。2026-10-15 本次确认周期 1 秒、超时 2 秒、重试 1 次并运行 60 秒；未设置业务有效期，设备显示强制 unknown。SDK SOF 计数缺陷已通过隔离副本修复并烧录；复测 60 秒获 56 个真实观测 ACK，零超时/重建，link_losses 首尾均为 2、未新增，确认退出释放。长期稳定仍待验证。没有修改 Hook 或安装后台服务；真实控灯、新鲜度和 Wi-Fi 传输待实现。

## 复核 / Verification

在仓库根目录运行：

```powershell
python Tools/CodexMonitor/tests/test_approvals.py
python Tools/CodexMonitor/tests/test_audit.py
python Tools/CodexMonitor/audit.py
python Tools/CodexMonitor/audit.py --session <session-id> --turn <turn-id>
```

生命周期测试包含 52 条合成事件和 6 会话并发；测试报告写在输出注明的临时目录，不写源码目录。审计工具支持 `--root` 指定其他来源、`--output` 导出报告。按目标轮次检查 `turnStatus`，不要用另一个聊天的 `Stop` 或当前会话的新消息替代完成证据。

2026-10-14 的实测边界：中文回复结束可正确记录 `Stop`；一个修复后的 `request_permissions` 窗口在用户批准后完成 `waitingApproval → working → idle`，同一调用的待审批数从 1 变为 0。期间其他聊天活动未覆盖等待状态。此为有限样本，拒绝、所有审批来源、长期稳定性和失联处理未全部验证。

## 回退 / Rollback

恢复安装前保存的脚本和对应的 Hook 定义，核对之后是否追加了其他配置；定义变化后按 Codex 提示重新审查。保留原日志与快照，不把新旧采集器同时写到同一状态目录。停用时只禁用本工具对应的处理器。

2026-10-15 状态有效期候选已在 USB 桥接层加入显式参数和传输时间预留；默认仍显示 unknown。以前短时采样生成的 2 个宿主绑定本次复核均为 unknown，因此不能用于开启真实状态。用户确认 30 秒实验预算后，短时采样取得 1 个当前会话绑定并恢复原采集器；仅显式实验启用，未接灯带，详见 DeviceBridge 文档。

2026-10-15 后续将 Hook 采集时间同时绑定到 Windows 单调时钟计数，侧文件增加十进制 `observedMonotonicNs`。schema 2 视图用它计算事件年龄；缺失、倒退或异常计数一律 unknown。桥接生成快照时再扣除单调时钟经过的时间，墙上时间跳变不能延长已观测状态。原 UTC 时间仍用于审计；宿主进程身份实时核对也阻止重启后的旧计数直接沿用。旧侧文件记录会因缺少单调证明降级，直到新 Hook 事件更新。用户级包装器已按哈希升级，Hook 定义和原生命周期采集器未改。

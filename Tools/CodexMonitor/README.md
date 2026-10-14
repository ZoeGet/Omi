# Codex 状态采集实验 / Codex lifecycle monitor

Windows 主机端工具，读取 Codex Hook 的生命周期 JSON，按会话、轮次和工具调用 ID 保存状态。只使用 Python 标准库，需要 Python 3.10 或更新版本。

这是状态源实验。目前没有 USB/Wi-Fi 传输、灯带控制或桌面气泡，也不能将已有快照当作持续在线的证明。

## 文件 / Files

| 文件 | 职责 |
| --- | --- |
| `collector.py` | UTF-8 输入、Windows 互斥锁、审批关联及原子快照写入 |
| `make_hooks.py` | 只向标准输出生成配置，不修改用户设置 |
| `audit.py` | 只读诊断与按会话、轮次检查 |
| `tests/test_approvals.py` | 隔离目录内的生命周期、隐私及多进程回归 |
| `tests/test_audit.py` | 缺失来源、目标隔离、损坏行及审批覆盖率测试 |

## 安装 / Setup

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
| `waitingApproval` | 存在已观测的待确认审批 |
| `idle` | 已观测轮次收到结束/中断，且没有其他未结束轮次 |
| `offline` | 收到 `SessionEnd` |
| `unknown` | 来源不足、关联不明或缺失必要标识 |

`PermissionRequest` 提供调用 ID 时，只允许同一轮次、同一调用的 `PostToolUse` 清除对应项。普通工具的开始、其他工具的完成、旧轮次的结束均不会清除它。

本机实测发现，`request_permissions` 工具的窗口可以进入 Desktop 的 `waitingOnApproval`，却不触发 `PermissionRequest` Hook。因此还将这个工具的 `PreToolUse` 作为审批开始，通过相同调用 ID 的 `PostToolUse` 解除。

通用 `PermissionRequest` 不保证提供调用 ID。缺失时，后续工具活动不能证明是哪一项审批结束，状态会降级为 `unknown`/`approvalUnconfirmed`，直到本轮结束。`PostToolUse` 只证明调用已返回，不能单独推断用户批准还是拒绝。

按轮次保留已结束记录，可阻止迟到事件复活旧任务。记录尚未自动裁剪。汇总只覆盖已观测会话，不能代表 Desktop 所有聊天。尚无心跳、进程退出恢复和过期策略；长时间没有新事件不能证明空闲或仍在线。

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

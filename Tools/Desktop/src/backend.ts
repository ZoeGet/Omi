import { useCallback, useEffect, useRef, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';

export type Light = { effect: string; red: number; green: number; blue: number; brightness: number };
export type Port = { device: string; description: string };
export type Settings = { port: string; root: string; bindings: string };
export type MonitorProfile = { revision: number; profiles: Record<string, Light> };
export type MonitorUpdate = { state: string; message: string };
type RequestBody = Settings | Light | MonitorProfile | { address: string; code?: string; previous?: string } | { images: string[] } | null;
export type Snapshot = {
  monitorSource?: { state: string; reasons: string[] }; taskScreenSupported?: boolean;
  state: { mode: string; displayStatus: string; monitorOutput?: string; leaseActive: boolean } | null;
  monitorRequested: boolean; monitorLights: boolean; monitorGreenOff: boolean; operations: string[];
  monitorProfile?: MonitorProfile | null;
  lastLight: Light | null; diagnostics: Record<string, number>; health: Record<string, unknown>;
};
export type WorkerEvent = Partial<Snapshot> & {
  kind: string; port?: string; ok?: boolean; command?: string; error?: string;
  releaseConfirmed?: boolean; monitorOff?: boolean;
  transport?: 'usb' | 'wifi';
  attempt?: number; delay?: number;
  pairingState?: string;
  update?: MonitorUpdate | null;
};
type Reply = { ok: boolean; result?: unknown; error?: string; events: WorkerEvent[] };
type State = {
  ready: boolean; connected: boolean; busy: boolean; demo: boolean;
  ports: Port[]; settings: Settings; snapshot: Partial<Snapshot>; notice: string; logs: string[];
  transport?: 'usb' | 'wifi'; endpoint?: string;
  reconnecting?: boolean; connectionError?: string; lightResult?: 'pending' | 'failed' | 'confirmed';
  pairingInspection?: { address: string; state: string };
  monitorUpdate?: MonitorUpdate | null;
};
export const pairingStatusText: Record<string, string> = {
  new: '设备报告尚未绑定，可输入屏幕上的六位码完成首次配对。',
  'paired-here': '已验证本机配对凭据，可直接无线连接，无需再次输入配对码。',
  pending: '本机有待确认的配对记录，请先验证连接恢复，不要重复配对。',
  'repair-required': '设备已有绑定或绑定状态发生变化，本机没有有效凭据。请明确选择重新配对。',
  'identity-changed': '此地址的设备身份与本机记录不同。请核对设备和 IP，不能直接覆盖原绑定。',
  unknown: '尚未确认设备配对状态，请检查地址、网络或其他电脑是否占用连接后重新检测。',
};
const errors: Record<string, string> = {
  'monitor-profile-not-supported': '当前固件不支持保存监控灯效，请升级固件。',
  'monitor-profile-conflict': '设备配置已被其他连接修改，请重新读取后再保存。',
  'monitor-profile-save-failed': '设备存储写入失败，监控灯效未确认保存。',
  'monitor-profile-revision-exhausted': '设备配置版本已用尽，请联系维护者。',
  'monitor-mode-active': '监控模式已锁定手动灯光，请先切回本地模式。',
  'voice-active': '设备正在响应语音，请稍后再应用灯光。',
  'usb-priority': 'USB 连接优先，请先断开 USB 控制再通过无线调灯。',
  'wireless-pairing-required': '请先在无线配对页保存此设备。',
  'wireless-authentication-failed': '无线设备认证失败；换网后请到无线配对页，点击重新查找设备。',
  'wireless-disconnected': '无线连接已断开，等待重新连接。',
  'wireless-unavailable': '无线设备暂时不可达。',
  'reconnect-exhausted': '自动重连未成功，请检查供电、串口或网络后手动连接。',
  'connection-interrupted': '连接已中断，未发送的操作已取消，请恢复连接后重新应用。',
  'wireless-send-failed': '无线发送失败，请检查设备网络。',
  'wireless-receive-failed': '无线接收失败，请检查设备网络。',
  'device-not-ready': '设备尚未就绪，请等待当前操作完成。',
  'port-not-found': '串口已断开，请刷新后重新选择。',
  'light-command-not-supported': '当前固件未提供手动灯光控制。',
  'monitor-lights-not-supported': '当前固件未提供监控灯光能力。',
  'monitor-policy-not-supported': '当前固件不支持来源异常绿、断线关灯的规则。',
  'freshness-challenge-required': '当前固件不支持监控状态有效期校验。',
  'monitor-update-failed': '监控更新失败，正在尝试重连；设备按原有规则回退。',
  'local-mode-unconfirmed': '设备尚未确认退出监控，请重试或断开连接。',
};
const errorText = (error: string) => errors[error] ?? `操作失败：${error}`;
const commands: Record<string, string> = { local: '已切回本地灯光。', monitor: 'Codex 监控已开启。', light: '灯光设置已获设备确认。', 'monitor-profile': '监控灯效已保存到设备，重启后保留。', 'monitor-profile-read': '已重新读取设备监控灯效。' };

function log(state: State, text: string): State {
  return { ...state, notice: text, logs: [...state.logs, `${new Date().toLocaleTimeString()}  ${text}`].slice(-200) };
}

export function applyEvents(state: State, events: WorkerEvent[]): State {
  for (const event of events) {
    switch (event.kind) {
      case 'monitor-setup':
        state = { ...state, monitorUpdate: event.update };
        if (event.update) state = log(state, event.update.message);
        break;
      case 'connected':
        state = log({ ...state, connected: true, busy: false, reconnecting: false, connectionError: undefined, lightResult: undefined,
          snapshot: {}, transport: event.transport ?? 'usb', endpoint: event.port }, `已连接 ${event.port}，设备握手成功。`);
        break;
      case 'reconnecting':
        state = log({ ...state, connected: false, busy: true, reconnecting: true, snapshot: {}, lightResult: undefined },
          `正在自动重连（${event.attempt}/5），${event.delay} 秒后重试，可取消。`);
        break;
      case 'status':
        if (state.snapshot.monitorRequested && !event.monitorRequested && event.state?.mode === 'local') {
          state = log(state, '设备已退出监控，恢复本地控制。');
        }
        state = { ...state, snapshot: event };
        break;
      case 'command':
        state = log({ ...state, busy: false,
          lightResult: event.command === 'light' ? event.ok ? 'confirmed' : 'failed' : state.lightResult }, event.ok ? commands[event.command!] : errorText(event.error!));
        break;
      case 'pairing':
        if (event.command === 'inspect-wireless' || event.pairingState) {
          state = { ...state, pairingInspection: { address: event.port ?? '', state: event.pairingState ?? 'unknown' } };
        } else if (event.ok && ['pair', 're-pair', 'verify-wireless'].includes(event.command!)) {
          state = { ...state, pairingInspection: undefined };
        }
        state = log({ ...state, busy: false }, event.ok
          ? event.command === 'inspect-wireless' ? pairingStatusText[event.pairingState ?? 'unknown'] ?? pairingStatusText.unknown
            : event.command === 'pair' ? '无线配对已保存。'
            : event.command === 're-pair' ? '重新配对成功，旧配对凭据已失效。'
            : ['find-wireless', 'relocate-wireless'].includes(event.command!) ? `已验证原设备并保存当前地址：${event.port}，无需重新配对。` : '无线设备身份验证通过。'
          : event.error!);
        break;
      case 'update-error':
        state = { ...state, snapshot: { ...state.snapshot, state: null } };
        if (state.notice !== errorText(event.error!)) state = log(state, errorText(event.error!));
        break;
      case 'connection-error':
        state = log({ ...state, reconnecting: false, connectionError: errorText(event.error!) }, `${errorText(event.error!)} 请检查后手动连接。`);
        break;
      case 'disconnected':
        state = log({ ...state, connected: false, busy: false, reconnecting: false, snapshot: {}, lightResult: undefined },
          state.connectionError ? state.notice : event.releaseConfirmed ? event.monitorOff ? '已断开，设备确认监控输出关闭。' : '已断开，设备确认释放控制。'
            : '连接已关闭，未收到释放确认；设备由既有租约规则回退。');
        break;
    }
  }
  return state;
}

type LastConnection = { port: string; transport: 'usb' | 'wifi'; enabled: boolean };
function lastConnection(): LastConnection | null {
  try {
    const saved = JSON.parse(localStorage.getItem('omi.lastConnection') ?? 'null');
    return saved && typeof saved.port === 'string' && saved.port && ['usb', 'wifi'].includes(saved.transport)
      && typeof saved.enabled === 'boolean' ? saved : null;
  } catch { return null; }
}
function rememberConnection(value: LastConnection) {
  try { localStorage.setItem('omi.lastConnection', JSON.stringify(value)); }
  catch {
    //  偏好保存失败不影响本次连接 / A failed preference write does not affect the current connection
  }
}

export function useDevice() {
  const native = isTauri();
  const manuallyDisconnected = useRef(false);
  const [state, setState] = useState<State>({ ready: false, connected: false, busy: false, demo: false,
    ports: [], settings: { port: '', root: '', bindings: '' }, snapshot: {}, logs: [],
    notice: native ? '正在启动设备后台…' : '浏览器仅预览界面，请打开桌面程序连接设备。' });
  const report = useCallback((text: string) => setState(value => log(value, text)), []);
  const request = useCallback(async (action: string, body: RequestBody = null) => {
    const reply = await invoke<Reply>('request', { message: { action, body } });
    setState(value => applyEvents(reply.ok ? value : log({ ...value, busy: false,
      lightResult: action === 'light' ? 'failed' : value.lightResult }, errorText(reply.error!)), reply.events));
    return reply;
  }, []);

  useEffect(() => {
    if (!native) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const reply = await invoke<Reply>('request', { message: { action: 'poll', body: null } });
        if (disposed) return;
        if (!reply.ok) throw new Error(reply.error);
        if (reply.events.length) setState(value => applyEvents(value, reply.events));
        //  回复后再安排下一轮，不堆积请求或干预窗口缩放 / Schedule after the reply without piling up requests or interfering with resize
        timer = setTimeout(poll, 100);
      } catch (error) {
        if (!disposed) setState(value => log({ ...value, ready: false, connected: false, busy: false, snapshot: {} }, String(error)));
      }
    }
    invoke<Reply>('request', { message: { action: 'init', body: null } }).then(reply => {
      if (disposed) return;
      if (!reply.ok) throw new Error(reply.error);
      const info = reply.result as { demo: boolean; root: string; bindings: string; ports: Port[] };
      const saved = info.demo ? null : lastConnection();
      setState(value => ({ ...value, ready: true, demo: info.demo, ports: info.ports,
        transport: saved?.transport, endpoint: saved?.port,
        settings: { root: info.root, bindings: info.bindings, port: saved?.transport === 'usb' ? saved.port : info.ports.length === 1 ? info.ports[0].device : '' },
        notice: info.demo ? '演示模式：仅操作模拟设备。' : '请选择 USB 串口或已配对的 Wi-Fi 设备进行连接。' }));
      if (saved?.enabled) {
        if (saved.transport === 'wifi' || info.ports.some(port => port.device === saved.port)) {
          setState(value => ({ ...value, busy: true, notice: '正在连接上次使用的设备…' }));
          void request(saved.transport === 'wifi' ? 'connect-wireless' : 'connect', { port: saved.port, root: info.root, bindings: info.bindings })
            .catch(error => setState(value => log({ ...value, busy: false }, String(error))));
        } else report('上次使用的 USB 串口未找到，请插入设备后手动连接。');
      }
      void poll();
    }).catch(error => { if (!disposed) report(String(error)); });
    return () => { disposed = true; clearTimeout(timer); };
  }, [native, report, request]);

  useEffect(() => {
    if (state.connected && state.endpoint && state.transport && !state.demo && !manuallyDisconnected.current) {
      rememberConnection({ port: state.endpoint, transport: state.transport, enabled: true });
    }
  }, [state.connected, state.endpoint, state.transport, state.demo]);

  async function send(action: string, body: RequestBody = null) {
    if (!state.ready || state.busy && action !== 'disconnect') return;
    if (action === 'connect' || action === 'connect-wireless') manuallyDisconnected.current = false;
    if (action === 'disconnect' && !state.demo) {
      manuallyDisconnected.current = true;
      const saved = lastConnection();
      if (saved) rememberConnection({ ...saved, enabled: false });
    }
    setState(value => ({ ...value, busy: true,
      connectionError: action.startsWith('connect') || action === 'disconnect' ? undefined : value.connectionError,
      lightResult: action === 'light' ? 'pending' : value.lightResult,
      pairingInspection: action === 'inspect-wireless' ? undefined : value.pairingInspection }));
    try { await request(action, body); }
    catch (error) { setState(value => log({ ...value, busy: false, ready: false, snapshot: {},
      lightResult: action === 'light' ? 'failed' : value.lightResult }, String(error))); }
  }
  async function refresh() {
    try {
      const reply = await request('ports');
      if (reply.ok) {
        const ports = reply.result as Port[];
        setState(value => ({ ...value, ports, settings: { ...value.settings,
          port: ports.some(port => port.device === value.settings.port) ? value.settings.port : ports.length === 1 ? ports[0].device : '' } }));
      }
    } catch (error) { report(String(error)); }
  }
  function settings(patch: Partial<Settings>) {
    setState(value => ({ ...value, settings: { ...value.settings, ...patch } }));
  }
  return { ...state, send, refresh, request, settingsChanged: settings, report };
}

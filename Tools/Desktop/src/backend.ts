import { useCallback, useEffect, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';

export type Light = { effect: string; red: number; green: number; blue: number; brightness: number };
export type Port = { device: string; description: string };
export type Settings = { port: string; root: string; bindings: string };
export type MonitorProfile = { revision: number; profiles: Record<string, Light> };
type RequestBody = Settings | Light | MonitorProfile | { address: string; code?: string } | null;
export type Snapshot = {
  state: { mode: string; displayStatus: string; monitorOutput?: string; leaseActive: boolean } | null;
  monitorRequested: boolean; monitorLights: boolean; monitorGreenOff: boolean; operations: string[];
  monitorProfile?: MonitorProfile | null;
  lastLight: Light | null; diagnostics: Record<string, number>; health: Record<string, unknown>;
};
export type WorkerEvent = Partial<Snapshot> & {
  kind: string; port?: string; ok?: boolean; command?: string; error?: string;
  releaseConfirmed?: boolean; monitorOff?: boolean;
  transport?: 'usb' | 'wifi';
};
type Reply = { ok: boolean; result?: unknown; error?: string; events: WorkerEvent[] };
type State = {
  ready: boolean; connected: boolean; busy: boolean; demo: boolean;
  ports: Port[]; settings: Settings; snapshot: Partial<Snapshot>; notice: string; logs: string[];
  transport?: 'usb' | 'wifi'; endpoint?: string;
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
  'wireless-authentication-failed': '无线设备认证失败，请检查网络和已保存的设备地址。',
  'wireless-disconnected': '无线连接已断开，等待重新连接。',
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
      case 'connected':
        state = log({ ...state, connected: true, busy: false, transport: event.transport ?? 'usb', endpoint: event.port }, `已连接 ${event.port}，设备握手成功。`);
        break;
      case 'status':
        if (state.snapshot.monitorRequested && !event.monitorRequested && event.state?.mode === 'local') {
          state = log(state, '设备已退出监控，恢复本地控制。');
        }
        state = { ...state, snapshot: event };
        break;
      case 'command':
        state = log({ ...state, busy: false }, event.ok ? commands[event.command!] : errorText(event.error!));
        break;
      case 'pairing':
        state = log({ ...state, busy: false }, event.ok
          ? event.command === 'pair' ? '无线配对已保存。' : '无线设备身份验证通过。'
          : event.error!);
        break;
      case 'update-error':
        state = { ...state, snapshot: { ...state.snapshot, state: null } };
        if (state.notice !== errorText(event.error!)) state = log(state, errorText(event.error!));
        break;
      case 'connection-error':
        state = log(state, errorText(event.error!));
        break;
      case 'disconnected':
        state = log({ ...state, connected: false, busy: false, snapshot: {} },
          event.releaseConfirmed ? event.monitorOff ? '已断开，设备确认监控输出关闭。' : '已断开，设备确认释放控制。'
            : '连接已关闭，未收到释放确认；设备由既有租约规则回退。');
        break;
    }
  }
  return state;
}

export function useDevice() {
  const native = isTauri();
  const [state, setState] = useState<State>({ ready: false, connected: false, busy: false, demo: false,
    ports: [], settings: { port: '', root: '', bindings: '' }, snapshot: {}, logs: [],
    notice: native ? '正在启动设备后台…' : '浏览器仅预览界面，请打开桌面程序连接设备。' });
  const report = useCallback((text: string) => setState(value => log(value, text)), []);
  const request = useCallback(async (action: string, body: RequestBody = null) => {
    const reply = await invoke<Reply>('request', { message: { action, body } });
    setState(value => applyEvents(reply.ok ? value : log({ ...value, busy: false }, errorText(reply.error!)), reply.events));
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
      setState(value => ({ ...value, ready: true, demo: info.demo, ports: info.ports,
        settings: { root: info.root, bindings: info.bindings, port: info.ports.length === 1 ? info.ports[0].device : '' },
        notice: info.demo ? '演示模式：仅操作模拟设备。' : '请选择 USB 串口并连接设备。' }));
      void poll();
    }).catch(error => { if (!disposed) report(String(error)); });
    return () => { disposed = true; clearTimeout(timer); };
  }, [native, report]);

  async function send(action: string, body: RequestBody = null) {
    if (!state.ready || state.busy) return;
    setState(value => ({ ...value, busy: true }));
    try { await request(action, body); }
    catch (error) { setState(value => log({ ...value, busy: false, ready: false, snapshot: {} }, String(error))); }
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

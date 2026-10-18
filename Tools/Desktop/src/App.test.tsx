import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { Snapshot, WorkerEvent } from './backend';

const bridge = vi.hoisted(() => ({ native: true, invoke: vi.fn(), events: [] as WorkerEvent[] }));
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => bridge.native,
  invoke: (command: string, args: unknown) => command === 'window_control'
    ? Promise.resolve({ closeBehavior: 'tray', trayAvailable: true }) : bridge.invoke(command, args) }));
vi.mock('@tauri-apps/plugin-dialog', () => ({ open: vi.fn() }));
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => ({ setTheme: vi.fn().mockResolvedValue(undefined) }) }));
const local: Snapshot = { state: { mode: 'local', leaseActive: false, displayStatus: 'unknown', monitorOutput: 'local' },
  monitorRequested: false, monitorLights: true, monitorGreenOff: true, operations: ['light'], lastLight: null, diagnostics: {}, health: {} };
function status(value: Partial<Snapshot> = {}): WorkerEvent { return { kind: 'status', ...local, ...value }; }
function monitor(displayStatus = 'working'): WorkerEvent {
  return status({ monitorRequested: true, state: { mode: 'monitor', leaseActive: true, monitorOutput: 'connected', displayStatus } });
}
async function connect(snapshot = status()) {
  const user = userEvent.setup();
  await waitFor(() => expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(false));
  await user.click(screen.getByRole('button', { name: '连接设备' }));
  bridge.events.push({ kind: 'connected', port: 'COM17' }, snapshot);
  await waitFor(() => expect((screen.getByRole('button', { name: '断开连接' }) as HTMLButtonElement).disabled).toBe(false));
  return user;
}
beforeEach(() => {
  bridge.native = true;
  bridge.events = [];
  bridge.invoke.mockReset().mockImplementation(async (_command, { message }) => ({ ok: true,
    result: message.action === 'init' ? { demo: false, root: 'C:/state', bindings: 'C:/binding.json', ports: [{ device: 'COM17', description: 'OmiPet' }] }
      : message.action === 'monitor-setup-status' ? { state: 'not-installed', message: '尚未配置 Codex 监控', packaged: true, candidates: ['C:/Codex.exe'], home: 'C:/codex', root: 'C:/state' }
      : message.action === 'paired-devices' ? [] : null,
    events: bridge.events.splice(0) }));
});

describe('USB desktop', () => {
  it('requires explicit repair selection and clears the new screen code on submit', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '无线配对' }));
    await user.type(screen.getByLabelText('设备地址'), '192.0.2.42');
    await user.type(screen.getByLabelText('六位配对码'), '654321');
    await user.click(screen.getByRole('checkbox', { name: '我确认重新配对，成功后旧电脑的配对凭据将失效' }));
    await user.click(screen.getByRole('button', { name: '重新配对' }));
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 're-pair'
      && args.message.body.address === '192.0.2.42' && args.message.body.code === '654321')).toBe(true);
    expect((screen.getByLabelText('六位配对码') as HTMLInputElement).value).toBe('');
    expect(screen.queryByText('重新配对成功，旧配对凭据已失效。')).toBeNull();
    bridge.events.push({ kind: 'pairing', command: 're-pair', ok: true });
    await screen.findByText('重新配对成功，旧配对凭据已失效。');
  });
  it('finds a paired device after a network change and allows authenticated manual address updates', async () => {
    let address = 'wss://192.0.2.1:8443/pair';
    bridge.invoke.mockImplementation(async (_command, { message }) => ({ ok: true,
      result: message.action === 'init' ? { demo: false, root: 'C:/state', bindings: 'C:/binding.json', ports: [] }
        : message.action === 'paired-devices' ? [{ address, confirmed: true }] : null,
      events: bridge.events.splice(0) }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '无线配对' }));
    await user.click(await screen.findByRole('button', { name: '在当前网络查找' }));
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'find-wireless'
      && args.message.body.address === address)).toBe(true);
    expect((screen.getByRole('button', { name: '无线连接' }) as HTMLButtonElement).disabled).toBe(true);
    address = 'wss://192.0.2.42:8443/pair';
    bridge.events.push({ kind: 'pairing', ok: true, command: 'find-wireless', port: address });
    await screen.findByText(address, { selector: 'strong' });
    await user.click(screen.getByRole('button', { name: '修改地址' }));
    await user.type(screen.getByLabelText('设备新地址'), '192.0.2.43');
    await user.click(screen.getByRole('button', { name: '验证并保存地址' }));
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'relocate-wireless'
      && args.message.body.previous === address && args.message.body.address === '192.0.2.43')).toBe(true);
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'pair')).toBe(false);
  });
  it('connects a saved wireless device and uses the shared controls', async () => {
    bridge.invoke.mockImplementation(async (_command, { message }) => ({ ok: true,
      result: message.action === 'init' ? { demo: false, root: 'C:/state', bindings: 'C:/binding.json', ports: [] }
        : message.action === 'paired-devices' ? [{ address: 'wss://192.0.2.1:8443/pair', confirmed: true }] : null,
      events: bridge.events.splice(0) }));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '无线配对' }));
    await user.click(await screen.findByRole('button', { name: '无线连接' }));
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'connect-wireless'
      && args.message.body.port === 'wss://192.0.2.1:8443/pair')).toBe(true);
    bridge.events.push({ kind: 'connected', port: 'wss://192.0.2.1:8443/pair', transport: 'wifi' }, status());
    await waitFor(() => expect((screen.getByRole('switch', { name: '本地灯光' }) as HTMLInputElement).disabled).toBe(false));
    expect(screen.getByText('可信无线连接')).toBeTruthy();
  });
  it('clears the pairing code on submit and waits for the backend result', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '无线配对' }));
    await user.type(screen.getByLabelText('设备地址'), '192.0.2.1');
    await user.type(screen.getByLabelText('六位配对码'), '123456');
    await user.click(screen.getByRole('button', { name: /^配对$/ }));
    expect((screen.getByLabelText('六位配对码') as HTMLInputElement).value).toBe('');
    expect((screen.getByRole('button', { name: /^配对$/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'pair' && args.message.body.code === '123456')).toBe(true);
    expect(screen.queryByText('无线配对已保存。')).toBeNull();
    bridge.events.push({ kind: 'pairing', ok: true, command: 'pair' });
    await waitFor(() => expect(screen.getByText('无线配对已保存。')).toBeTruthy());
  });
  it('requires confirmed mode changes and locks lights while monitoring', async () => {
    render(<App />);
    expect((screen.getByRole('switch', { name: '本地灯光' }) as HTMLInputElement).disabled).toBe(true);
    const user = await connect();
    const input = screen.getByRole('switch', { name: 'Codex 监控' }) as HTMLInputElement;
    await user.click(input);
    expect(input.checked).toBe(false);
    expect(input.disabled).toBe(true);
    bridge.events.push({ kind: 'command', command: 'monitor', ok: true }, monitor());
    await waitFor(() => expect(input.checked).toBe(true));
    await user.click(screen.getByRole('button', { name: '灯光与灯效' }));
    for (const name of ['应用灯光设置', '选择颜色 #0000FF', '常亮', '扩散灯']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect((screen.getByRole('slider', { name: '灯光亮度' }) as HTMLInputElement).disabled).toBe(true);
  });

  it('sends edited RGB/effect/brightness only on apply and reports ACK errors', async () => {
    render(<App />);
    const user = await connect();
    await user.click(screen.getByRole('button', { name: '灯光与灯效' }));
    await user.click(screen.getByRole('button', { name: '选择颜色 #0000FF' }));
    await user.click(screen.getByRole('button', { name: '扩散灯' }));
    const lights = () => bridge.invoke.mock.calls.filter(([, args]) => args.message.action === 'light');
    for (const brightness of [0, 255]) {
      const count = lights().length;
      fireEvent.change(screen.getByRole('slider', { name: '灯光亮度' }), { target: { value: brightness } });
      expect(lights()).toHaveLength(count);
      await user.click(screen.getByRole('button', { name: '应用灯光设置' }));
      expect(lights().at(-1)?.[1].message.body).toEqual({ effect: 'centerExpand', red: 0, green: 0, blue: 255, brightness });
      expect(screen.queryByText('灯光设置已获设备确认。')).toBeNull();
      bridge.events.push({ kind: 'command', command: 'light', ok: false, error: 'voice-active' }, status());
      await waitFor(() => expect((screen.getByRole('button', { name: '应用灯光设置' }) as HTMLButtonElement).disabled).toBe(false));
      expect(screen.getByText('设备正在响应语音，请稍后再应用灯光。')).toBeTruthy();
    }
  });

  it('honors firmware capabilities rather than enabling unsupported controls', async () => {
    render(<App />);
    const user = await connect(status({ operations: [], monitorLights: false, monitorGreenOff: false }));
    expect((screen.getByRole('switch', { name: 'Codex 监控' }) as HTMLInputElement).disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: '灯光与灯效' }));
    expect((screen.getByRole('button', { name: '应用灯光设置' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows device status, recovers to local after voice and clears state on disconnect', async () => {
    render(<App />);
    const user = await connect(monitor());
    for (const [value, title] of [['working', '运行中'], ['waitingApproval', '等待操作'], ['unknown', '来源异常']]) {
      bridge.events.push(monitor(value));
      await waitFor(() => expect(screen.getByRole('status').textContent).toBe(title));
    }
    bridge.events.push({ kind: 'update-error', error: 'monitor-update-failed' });
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('连接中断'));
    expect(screen.getByLabelText('灯带预览：关闭')).toBeTruthy();
    bridge.events.push(status());
    await waitFor(() => expect((screen.getByRole('switch', { name: '本地灯光' }) as HTMLInputElement).checked).toBe(true));
    await user.click(screen.getByRole('button', { name: '断开连接' }));
    bridge.events.push({ kind: 'disconnected', releaseConfirmed: true, monitorOff: true });
    await waitFor(() => expect(screen.getByText('已断开，设备确认监控输出关闭。')).toBeTruthy());
    expect((screen.getByRole('switch', { name: '本地灯光' }) as HTMLInputElement).disabled).toBe(true);
  });

  it('edits every monitor state, waits for save ACK, and protects concurrent changes', async () => {
    const profile = { revision: 4, profiles: Object.fromEntries(['working', 'waitingApproval', 'idle', 'unknown', 'offline'].map(status =>
      [status, { effect: 'centerExpand', red: 0, green: 255, blue: 0, brightness: 16 }])) };
    render(<App />);
    const user = await connect(status({ operations: ['light', 'monitorProfile'], monitorProfile: profile }));
    await user.click(screen.getByRole('button', { name: '监控灯效' }));
    await screen.findByRole('heading', { name: '运行中' });
    expect(screen.getAllByRole('slider')).toHaveLength(1);
    const button = screen.getByRole('button', { name: '保存监控灯效到设备' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    for (const title of ['运行中', '等待操作', '完成 / 空闲', '来源异常 / 无事件', '会话离线']) {
      await user.click(screen.getByRole('button', { name: `编辑${title}` }));
      fireEvent.change(screen.getByRole('slider', { name: `${title}亮度` }), { target: { value: 0 } });
    }
    await user.click(screen.getByRole('button', { name: '编辑运行中' }));
    fireEvent.change(screen.getByLabelText('运行中颜色'), { target: { value: '#FF00FF' } });
    expect(bridge.invoke.mock.calls.some(([, args]) => args.message.action === 'monitor-profile')).toBe(false);
    await user.click(button);
    const submitted = bridge.invoke.mock.calls.find(([, args]) => args.message.action === 'monitor-profile')![1].message.body;
    expect(submitted.revision).toBe(4);
    expect(submitted.profiles.working.red).toBe(255);
    for (const entry of Object.values(submitted.profiles) as { brightness: number }[]) expect(entry.brightness).toBe(0);
    expect(screen.queryByText('监控灯效已保存到设备，重启后保留。')).toBeNull();
    bridge.events.push({ kind: 'command', command: 'monitor-profile', ok: true }, status({ operations: ['light', 'monitorProfile'], monitorProfile: { ...submitted, revision: 5 } }));
    await waitFor(() => expect(screen.getByText('监控灯效已保存到设备，重启后保留。')).toBeTruthy());
    await waitFor(() => expect(button.disabled).toBe(true));
    fireEvent.change(screen.getByLabelText('运行中亮度'), { target: { value: 255 } });
    bridge.events.push(status({ operations: ['light', 'monitorProfile'], monitorProfile: { ...submitted, revision: 6 } }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(button.disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: '重新读取设备配置' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect((screen.getByLabelText('运行中亮度') as HTMLInputElement).value).toBe('0');
  });

  it('keeps monitor profile editing disabled on older firmware', async () => {
    render(<App />);
    const user = await connect();
    await user.click(screen.getByRole('button', { name: '监控灯效' }));
    expect(screen.getByText('当前固件不支持保存监控灯效，请升级固件。')).toBeTruthy();
    expect((screen.getByRole('button', { name: '保存监控灯效到设备' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps browser previews away from device controls', () => {
    bridge.native = false;
    render(<App />);
    expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('浏览器仅预览界面，请打开桌面程序连接设备。')).toBeTruthy();
    expect(bridge.invoke).not.toHaveBeenCalled();
  });

  it('disables stale controls if the native backend exits', async () => {
    render(<App />);
    await connect();
    bridge.invoke.mockRejectedValue(new Error('设备后台已退出'));
    await waitFor(() => expect(screen.getByText('Error: 设备后台已退出')).toBeTruthy());
    expect((screen.getByRole('switch', { name: '本地灯光' }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

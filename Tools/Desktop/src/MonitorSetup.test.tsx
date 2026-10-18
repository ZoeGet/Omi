import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { MonitorSetup } from './MonitorSetup';
import type { Device } from './Surface';

vi.mock('@tauri-apps/plugin-dialog', () => ({ open: vi.fn() }));
function fixture() {
  let state = { state: 'not-installed', message: '尚未配置 Codex 监控', packaged: true, candidates: ['C:/Codex.exe'], home: 'C:/codex', root: 'C:/state' };
  const request = vi.fn(async (action: string) => {
    if (action === 'monitor-setup-status') return { ok: true, result: state };
    if (action === 'monitor-setup-install') state = { ...state, state: 'awaiting-event', message: '等待信任和新事件', images: ['C:/Codex.exe'] } as typeof state;
    if (action === 'monitor-setup-uninstall') state = { ...state, state: 'not-installed', message: '尚未配置 Codex 监控', images: undefined } as typeof state;
    return { ok: true, result: { message: '配置操作完成', backup: 'C:/backup', root: 'C:/state', bindings: 'C:/state/host-bindings.json' } };
  });
  const device = { ready: true, connected: false, busy: false, demo: false, request, report: vi.fn(), settingsChanged: vi.fn() } as unknown as Device;
  return { device, request, ready: () => { state = { ...state, state: 'ready', message: '真实事件及宿主关联正常' }; } };
}

it('installs selected images but only completes after genuine ready status; uninstall needs selection', async () => {
  const { device, request, ready } = fixture();
  const completed = vi.fn();
  const user = userEvent.setup();
  render(<MonitorSetup device={device} completed={completed} />);
  const install = await screen.findByRole('button', { name: '安装监控组件' });
  await waitFor(() => expect((install as HTMLButtonElement).disabled).toBe(false));
  await user.click(install);
  expect(request).toHaveBeenCalledWith('monitor-setup-install', { images: ['C:/Codex.exe'] });
  expect(device.settingsChanged).toHaveBeenCalledWith({ root: 'C:/state', bindings: 'C:/state/host-bindings.json' });
  await screen.findByText('等待信任和新事件');
  expect(completed).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: '卸载监控接入' }) as HTMLButtonElement).disabled).toBe(true);
  ready();
  await user.click(screen.getByRole('button', { name: '重新检测监控' }));
  await waitFor(() => expect(completed).toHaveBeenCalledOnce());
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: '卸载监控接入' }));
  expect(request).toHaveBeenCalledWith('monitor-setup-uninstall', null);
});

it('allows diagnosis but prevents installation while connected or in demo mode', async () => {
  const { device } = fixture();
  const view = render(<MonitorSetup device={{ ...device, connected: true }} />);
  await screen.findByText('尚未配置 Codex 监控');
  expect((screen.getByRole('button', { name: '安装监控组件' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: '重新检测监控' }) as HTMLButtonElement).disabled).toBe(false);
  view.rerender(<MonitorSetup device={{ ...device, demo: true }} />);
  expect((screen.getByRole('button', { name: '安装监控组件' }) as HTMLButtonElement).disabled).toBe(true);
});

it('reports setup failures without claiming installation succeeded', async () => {
  const { device } = fixture();
  device.request = vi.fn().mockResolvedValue({ ok: false, error: '配置已被修改', events: [] });
  render(<MonitorSetup device={device} />);
  expect((await screen.findByRole('alert')).textContent).toContain('配置已被修改');
  expect(device.report).not.toHaveBeenCalled();
});

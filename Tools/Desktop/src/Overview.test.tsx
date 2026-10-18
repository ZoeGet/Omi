import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { Overview } from './Overview';
import type { Device } from './Surface';

const draft = { color: '#FFFFFF', brightness: 16, effect: 'solid' };
function fixture(devices: { address: string; confirmed: boolean; pendingRepair?: boolean }[] = []) {
  return { ready: true, connected: false, busy: false, demo: false, snapshot: {},
    ports: [{ device: 'COM1', description: 'Omi' }], settings: { port: 'COM1', root: 'C:/state', bindings: 'C:/bindings' },
    request: vi.fn().mockResolvedValue({ ok: true, result: devices }), send: vi.fn(), refresh: vi.fn(), settingsChanged: vi.fn(),
  } as unknown as Device;
}

it('connects USB and keeps its selection separate from the wireless address', async () => {
  const device = fixture([{ address: 'wss://192.0.2.1:8443/pair', confirmed: true }]);
  const user = userEvent.setup();
  render(<Overview device={device} light={draft} navigate={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: '连接设备' }));
  expect(device.send).toHaveBeenLastCalledWith('connect', device.settings);
  await user.click(screen.getByRole('tab', { name: 'Wi-Fi' }));
  await waitFor(() => expect((screen.getByLabelText('已配对的无线设备') as HTMLSelectElement).value).toContain('192.0.2.1'));
  await user.click(screen.getByRole('button', { name: '连接设备' }));
  expect(device.send).toHaveBeenLastCalledWith('connect-wireless', { ...device.settings, port: 'wss://192.0.2.1:8443/pair' });
  await user.click(screen.getByRole('tab', { name: 'USB' }));
  expect((screen.getByLabelText('USB 串口') as HTMLSelectElement).value).toBe('COM1');
  expect(device.settingsChanged).not.toHaveBeenCalled();
});

it('requires selection among multiple devices and blocks pending credentials', async () => {
  const device = fixture([{ address: '192.0.2.1', confirmed: true }, { address: '192.0.2.2', confirmed: true },
    { address: '192.0.2.3', confirmed: false }, { address: '192.0.2.4', confirmed: true, pendingRepair: true }]);
  const user = userEvent.setup();
  render(<Overview device={device} light={draft} navigate={vi.fn()} />);
  await user.click(screen.getByRole('tab', { name: 'Wi-Fi' }));
  const choice = screen.getByLabelText('已配对的无线设备');
  await screen.findByRole('option', { name: '192.0.2.4 · 待验证' });
  expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('option', { name: '192.0.2.3 · 待验证' }) as HTMLOptionElement).disabled).toBe(true);
  expect((screen.getByRole('option', { name: '192.0.2.4 · 待验证' }) as HTMLOptionElement).disabled).toBe(true);
  await user.selectOptions(choice, '192.0.2.2');
  await user.click(screen.getByRole('button', { name: '连接设备' }));
  expect(device.send).toHaveBeenCalledWith('connect-wireless', { ...device.settings, port: '192.0.2.2' });
});

it('offers pairing for an empty list and refreshes saved devices', async () => {
  const device = fixture(); const navigate = vi.fn(); const user = userEvent.setup();
  render(<Overview device={device} light={draft} navigate={navigate} />);
  await user.click(screen.getByRole('tab', { name: 'Wi-Fi' }));
  await screen.findByRole('option', { name: '尚无已保存设备' });
  expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole('button', { name: '配对与设备管理' }));
  expect(navigate).toHaveBeenCalledWith('pairing');
  vi.mocked(device.request).mockResolvedValue({ ok: true, result: [{ address: '192.0.2.9', confirmed: true }], events: [] });
  await user.click(screen.getByRole('button', { name: '刷新无线设备' }));
  await waitFor(() => expect((screen.getByLabelText('已配对的无线设备') as HTMLSelectElement).value).toBe('192.0.2.9'));
});

it('displays the actual transport and locks switching until disconnected', async () => {
  const device = fixture(); const user = userEvent.setup();
  const view = render(<Overview device={device} light={draft} navigate={vi.fn()} />);
  view.rerender(<Overview device={{ ...device, connected: true, transport: 'wifi', endpoint: 'wss://192.0.2.1:8443/pair' }} light={draft} navigate={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('tab', { name: 'Wi-Fi' }).getAttribute('aria-selected')).toBe('true'));
  expect((screen.getByRole('tab', { name: 'USB' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('wss://192.0.2.1:8443/pair')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: '断开连接' }));
  expect(device.send).toHaveBeenCalledWith('disconnect');
});

it('discards delayed responses after switching away and disables connection on read errors', async () => {
  const device = fixture(); const user = userEvent.setup();
  let finish!: (reply: Awaited<ReturnType<Device['request']>>) => void;
  vi.mocked(device.request).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  render(<Overview device={device} light={draft} navigate={vi.fn()} />);
  await user.click(screen.getByRole('tab', { name: 'Wi-Fi' }));
  await user.click(screen.getByRole('tab', { name: 'USB' }));
  await act(async () => finish({ ok: true, result: [{ address: 'stale', confirmed: true }], events: [] }));
  vi.mocked(device.request).mockRejectedValueOnce(new Error('无法读取设备'));
  await user.click(screen.getByRole('tab', { name: 'Wi-Fi' }));
  await screen.findByRole('alert');
  expect(screen.queryByRole('option', { name: 'stale' })).toBeNull();
  expect((screen.getByRole('button', { name: '连接设备' }) as HTMLButtonElement).disabled).toBe(true);
});

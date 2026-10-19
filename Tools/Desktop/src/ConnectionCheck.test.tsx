import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ConnectionCheck } from './ConnectionCheck';
import type { Device } from './Surface';

function fixture(setup: object) {
  return { ready: true, connected: false, busy: false, demo: false, snapshot: {},
    request: vi.fn().mockResolvedValue({ ok: true, result: setup }),
  } as unknown as Device;
}

it('separates missing setup, missing events and live task data', async () => {
  const device = fixture({ state: 'not-installed', installed: false, hookReceived: false, message: '尚未配置' });
  const view = render(<ConnectionCheck device={device} />);
  await screen.findByText('需要配置或修复');
  expect(screen.getByText('尚未收到事件')).toBeTruthy();
  expect(screen.getByText('等待连接设备')).toBeTruthy();
  view.rerender(<ConnectionCheck device={{ ...device, connected: true, transport: 'wifi', snapshot: { monitorRequested: true,
    monitorSource: { state: 'unavailable', reasons: [] } } }} />);
  expect(screen.getByText('Wi-Fi 已连接')).toBeTruthy();
  expect(screen.getByText('任务来源不可用')).toBeTruthy();
  view.rerender(<ConnectionCheck device={{ ...device, connected: true, snapshot: { monitorRequested: true,
    monitorSource: { state: 'valid', reasons: [] }, taskScreenSupported: true } }} />);
  expect(screen.getByText('任务数据有效')).toBeTruthy();
});

it('does not confuse a historic Hook event with valid current data and refreshes explicitly', async () => {
  const device = fixture({ state: 'awaiting-binding', installed: true, hookReceived: true, message: '等待宿主关联' });
  const navigate = vi.fn(); const user = userEvent.setup();
  render(<ConnectionCheck device={{ ...device, connected: true, snapshot: { monitorRequested: true,
    monitorSource: { state: 'unavailable', reasons: [] } } }} navigate={navigate} />);
  await screen.findByText('已收到本次安装的事件');
  expect(screen.getByText('任务来源不可用')).toBeTruthy();
  expect(screen.getByText(/宿主关联尚未完成/)).toBeTruthy();
  await user.click(screen.getByRole('button', { name: '重新自检' }));
  expect(device.request).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole('button', { name: '配置与修复监控' }));
  expect(navigate).toHaveBeenCalledWith('settings');
});

it('explains expired observations and never treats them as an idle task', async () => {
  const device = fixture({ state: 'ready', installed: true, hookReceived: true, message: '已收到事件' });
  render(<ConnectionCheck device={{ ...device, connected: true, snapshot: { monitorRequested: true,
    monitorSource: { state: 'unavailable', reasons: ['observation-expired'] } } }} />);
  await screen.findByText('已安装');
  expect(screen.getByText('任务事件已过期，请让 Codex 执行一次新操作。')).toBeTruthy();
  expect(screen.queryByText('任务数据有效')).toBeNull();
});

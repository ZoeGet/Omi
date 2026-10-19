import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { Pairing } from './DevicePages';
import type { Device } from './Surface';

it.each(['repair-required', 'identity-changed'])('requires explicit replacement after detecting %s', async state => {
  const device = { ready: true, busy: false, connected: false, demo: false,
    settings: { root: 'C:/state', bindings: 'C:/binding.json', port: '' },
    request: vi.fn().mockResolvedValue({ ok: true, result: [] }), send: vi.fn(),
  } as unknown as Device;
  const user = userEvent.setup(); const navigate = vi.fn();
  const view = render(<Pairing device={device} navigate={navigate} />);
  await user.type(screen.getByLabelText('设备地址'), '192.0.2.1');
  await user.tab();
  expect(device.send).toHaveBeenCalledWith('inspect-wireless', { address: '192.0.2.1' });
  view.rerender(<Pairing device={{ ...device, pairingInspection: { address: 'wss://192.0.2.1:8443/pair', state } }} navigate={navigate} />);
  expect((screen.getByRole('button', { name: /^配对$/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(device.send).not.toHaveBeenCalledWith('re-pair', expect.anything());
  await user.click(screen.getByRole('button', { name: '重新配对该设备' }));
  expect(screen.getByRole('alert').textContent).toContain('旧电脑的配对凭据将失效');
  await user.type(screen.getByLabelText('六位配对码'), '123456');
  await user.click(screen.getByRole('button', { name: '确认重新配对' }));
  expect(device.send).toHaveBeenLastCalledWith('re-pair', { address: '192.0.2.1', code: '123456' });
});

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { WindowSettings } from './WindowSettings';

const native = vi.hoisted(() => ({ enabled: true, invoke: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => native.enabled, invoke: native.invoke }));
beforeEach(() => {
  native.enabled = true;
  native.invoke.mockReset().mockImplementation(async (_, args) => ({ closeBehavior: args.behavior ?? 'tray', trayAvailable: true }));
});

it('loads and saves close behavior with only the selector', async () => {
  const report = vi.fn();
  const user = userEvent.setup();
  render(<WindowSettings report={report} />);
  const choice = screen.getByRole('combobox', { name: '窗口关闭行为' });
  await waitFor(() => expect((choice as HTMLSelectElement).disabled).toBe(false));
  expect((choice as HTMLSelectElement).value).toBe('tray');
  await user.selectOptions(choice, 'exit');
  await waitFor(() => expect(report).toHaveBeenCalledWith('窗口关闭行为已保存。'));
  expect(native.invoke).toHaveBeenCalledWith('window_control', { action: 'close-behavior', behavior: 'exit' });
  expect((choice as HTMLSelectElement).value).toBe('exit');
  expect(screen.getByText('关闭窗口时')).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
});

it('preserves the saved selection when persistence fails', async () => {
  const report = vi.fn();
  const user = userEvent.setup();
  render(<WindowSettings report={report} />);
  const choice = screen.getByRole('combobox', { name: '窗口关闭行为' });
  await waitFor(() => expect((choice as HTMLSelectElement).disabled).toBe(false));
  native.invoke.mockRejectedValueOnce('disk unavailable');
  await user.selectOptions(choice, 'exit');
  await waitFor(() => expect(report).toHaveBeenCalledWith('应用操作未完成：disk unavailable'));
  expect((choice as HTMLSelectElement).value).toBe('tray');
});

it('reports unavailable tray while keeping the close behavior selector', async () => {
  native.invoke.mockResolvedValue({ closeBehavior: 'tray', trayAvailable: false });
  render(<WindowSettings report={vi.fn()} />);
  await screen.findByRole('alert');
  expect((screen.getByRole('combobox', { name: '窗口关闭行为' }) as HTMLSelectElement).disabled).toBe(false);
});

it('keeps browser previews away from native window controls', () => {
  native.enabled = false;
  render(<WindowSettings report={vi.fn()} />);
  expect((screen.getByRole('combobox', { name: '窗口关闭行为' }) as HTMLSelectElement).disabled).toBe(true);
  expect(native.invoke).not.toHaveBeenCalled();
});

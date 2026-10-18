import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAppTheme } from './theme';
import { ThemePicker } from './ThemePicker';

const native = vi.hoisted(() => ({ enabled: false, setTheme: vi.fn().mockResolvedValue(undefined) }));
vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => native.enabled }));
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => ({ setTheme: native.setTheme }) }));
beforeEach(() => { localStorage.clear(); native.enabled = false; native.setTheme.mockClear(); });
afterEach(() => vi.restoreAllMocks());

function Preview() {
  const { dark, theme, preference, setPreference } = useAppTheme();
  return <><ThemePicker value={preference} change={setPreference} /><span data-testid="theme">{dark ? 'dark' : 'light'}:{theme.colorNeutralBackground1}</span></>;
}

it('synchronizes the native window theme and restores system following', () => {
  native.enabled = true;
  render(<Preview />);
  expect(native.setTheme).toHaveBeenLastCalledWith(null);
  fireEvent.click(screen.getByRole('radio', { name: '深色' }));
  expect(native.setTheme).toHaveBeenLastCalledWith('dark');
  fireEvent.click(screen.getByRole('radio', { name: '浅色' }));
  expect(native.setTheme).toHaveBeenLastCalledWith('light');
  fireEvent.click(screen.getByRole('radio', { name: '跟随系统' }));
  expect(native.setTheme).toHaveBeenLastCalledWith(null);
});

it('follows system appearance changes and removes the listener on unmount', () => {
  const media = Object.assign(new EventTarget(), { matches: false, media: '(prefers-color-scheme: dark)' });
  const remove = vi.spyOn(media, 'removeEventListener');
  vi.spyOn(window, 'matchMedia').mockReturnValue(media as MediaQueryList);
  const view = render(<Preview />);
  expect((screen.getByRole('radio', { name: '跟随系统' }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
  act(() => { media.matches = true; media.dispatchEvent(new Event('change')); });
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
  act(() => { media.matches = false; media.dispatchEvent(new Event('change')); });
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
  view.unmount();
  expect(remove).toHaveBeenCalledWith('change', expect.any(Function));
});

it('keeps explicit themes fixed, resumes current system appearance, and restores the saved choice', () => {
  const media = Object.assign(new EventTarget(), { matches: false });
  vi.spyOn(window, 'matchMedia').mockReturnValue(media as MediaQueryList);
  const view = render(<Preview />);
  fireEvent.click(screen.getByRole('radio', { name: '深色' }));
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
  expect(localStorage.getItem('omi.theme')).toBe('dark');
  act(() => media.dispatchEvent(new Event('change')));
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
  fireEvent.click(screen.getByRole('radio', { name: '浅色' }));
  act(() => { media.matches = true; media.dispatchEvent(new Event('change')); });
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
  fireEvent.click(screen.getByRole('radio', { name: '跟随系统' }));
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
  fireEvent.click(screen.getByRole('radio', { name: '浅色' }));
  view.unmount();
  render(<Preview />);
  expect((screen.getByRole('radio', { name: '浅色' }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
});

it('falls back for invalid preferences and allows switching when storage is unavailable', () => {
  localStorage.setItem('omi.theme', 'invalid');
  const view = render(<Preview />);
  expect((screen.getByRole('radio', { name: '跟随系统' }) as HTMLInputElement).checked).toBe(true);
  view.unmount();
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('unavailable'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('unavailable'); });
  render(<Preview />);
  fireEvent.click(screen.getByRole('radio', { name: '深色' }));
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
});

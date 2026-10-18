import { act, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useSystemTheme } from './theme';

it('follows system appearance changes and removes the listener on unmount', () => {
  const media = Object.assign(new EventTarget(), { matches: false, media: '(prefers-color-scheme: dark)' });
  const remove = vi.spyOn(media, 'removeEventListener');
  const spy = vi.spyOn(window, 'matchMedia').mockReturnValue(media as MediaQueryList);
  function Preview() {
    const { dark, theme } = useSystemTheme();
    return <span data-testid="theme">{dark ? 'dark' : 'light'}:{theme.colorNeutralBackground1}</span>;
  }
  const view = render(<Preview />);
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
  act(() => { media.matches = true; media.dispatchEvent(new Event('change')); });
  expect(screen.getByTestId('theme').textContent).toBe('dark:#000000');
  act(() => { media.matches = false; media.dispatchEvent(new Event('change')); });
  expect(screen.getByTestId('theme').textContent).toBe('light:#ffffff');
  view.unmount();
  expect(remove).toHaveBeenCalledWith('change', expect.any(Function));
  spy.mockRestore();
});

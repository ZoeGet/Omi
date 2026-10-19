import { act, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LightStrip } from './Surface';
import { previewPixel } from './lightPreview';

afterEach(() => vi.unstubAllGlobals());

it('moves rainbow hues, breathes together, and keeps moving effects base-lit', () => {
  expect(previewPixel('rainbow', 0, 0).hue).not.toBe(previewPixel('rainbow', 1, 0).hue);
  expect(previewPixel('rainbow', 0, 0).hue).not.toBe(previewPixel('rainbow', 0, 1800).hue);
  expect(previewPixel('breathe', 0, 1500).level).toBe(1);
  expect(previewPixel('breathe', 0, 0).level).toBeLessThan(0.1);
  expect(previewPixel('sweep', 0, 0).level).toBeGreaterThan(previewPixel('sweep', 12, 0).level);
  expect(previewPixel('sweep', 12, 1800).level).toBeGreaterThan(previewPixel('sweep', 0, 1800).level);
  for (const time of [0, 1050, 2100, 3150]) {
    for (let index = 0; index < 13; index++) {
      expect(previewPixel('centerExpand', index, time).level).toBeCloseTo(previewPixel('centerExpand', 12 - index, time).level);
      expect(previewPixel('centerExpand', index, time).level).toBeGreaterThan(0.2);
    }
  }
});

it('animates frames, scales brightness, stops when off, and cancels on unmount', () => {
  let tick: FrameRequestCallback = () => {};
  const request = vi.fn((callback: FrameRequestCallback) => { tick = callback; return 1; });
  const cancel = vi.fn();
  vi.stubGlobal('requestAnimationFrame', request);
  vi.stubGlobal('cancelAnimationFrame', cancel);
  const { container, rerender, unmount } = render(<LightStrip color="#FF0000" effect="breathe" brightness={128} />);
  const first = () => (container.querySelector('span') as HTMLElement).style.opacity;
  act(() => tick(0));
  const dim = Number(first());
  act(() => tick(1500));
  expect(Number(first())).toBeCloseTo(0.65 + 0.35 * Math.sqrt(128 / 255));
  expect(Number(first())).toBeGreaterThan(dim);
  rerender(<LightStrip color="#FF0000" effect="off" />);
  expect(container.querySelector('[aria-label="灯带预览：关闭"]')).not.toBeNull();
  expect(cancel).toHaveBeenCalledWith(1);
  rerender(<LightStrip color="#FF0000" effect="sweep" />);
  cancel.mockClear();
  unmount();
  expect(cancel).toHaveBeenCalledWith(1);
});

it('keeps default 6% brightness visible while preserving animation contrast and zero-off', () => {
  const { container, rerender } = render(<LightStrip color="#00FF00" effect="centerExpand" brightness={16} />);
  const levels = Array.from(container.querySelectorAll('span'), pixel => Number(pixel.style.opacity));
  expect(Math.min(...levels)).toBeGreaterThan(0.3);
  expect(Math.max(...levels) - Math.min(...levels)).toBeGreaterThan(0.3);
  rerender(<LightStrip color="#00FF00" effect="centerExpand" brightness={0} />);
  expect(container.querySelector('[aria-label="灯带预览：关闭"]')).not.toBeNull();
});

it('keeps a static frame when reduced motion is requested', () => {
  vi.stubGlobal('matchMedia', () => Object.assign(new EventTarget(), { matches: true }));
  const request = vi.fn();
  vi.stubGlobal('requestAnimationFrame', request);
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  render(<LightStrip color="#FF0000" effect="rainbow" />);
  expect(request).not.toHaveBeenCalled();
});

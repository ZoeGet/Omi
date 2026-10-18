import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterAll, beforeAll, expect, it, vi } from 'vitest';
import { SidebarResize } from './SidebarResize';

beforeAll(() => {
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit) { super(type, init); this.pointerId = init.pointerId ?? 0; }
  });
});
afterAll(() => vi.unstubAllGlobals());

function Preview() {
  const [width, change] = useState(216);
  return <SidebarResize width={width} change={change} />;
}

it('drags with pointer capture, clamps both ends, and stops after cancellation', () => {
  render(<Preview />);
  const handle = screen.getByRole('separator', { name: '调整侧栏宽度' });
  handle.setPointerCapture = vi.fn();
  handle.releasePointerCapture = vi.fn();
  fireEvent.pointerDown(handle, { button: 0, pointerId: 3, clientX: 216 });
  fireEvent.pointerMove(handle, { pointerId: 3, clientX: 276 });
  expect(handle.getAttribute('aria-valuenow')).toBe('276');
  fireEvent.pointerMove(handle, { pointerId: 3, clientX: 999 });
  expect(handle.getAttribute('aria-valuenow')).toBe('320');
  fireEvent.pointerMove(handle, { pointerId: 3, clientX: -10 });
  expect(handle.getAttribute('aria-valuenow')).toBe('160');
  fireEvent.pointerCancel(handle, { pointerId: 3 });
  fireEvent.pointerMove(handle, { pointerId: 3, clientX: 300 });
  expect(handle.getAttribute('aria-valuenow')).toBe('160');
  expect(handle.setPointerCapture).toHaveBeenCalledWith(3);
});

it('supports keyboard resizing without exceeding bounds', () => {
  render(<Preview />);
  const handle = screen.getByRole('separator');
  fireEvent.keyDown(handle, { key: 'ArrowRight' });
  expect(handle.getAttribute('aria-valuenow')).toBe('224');
  fireEvent.keyDown(handle, { key: 'End' });
  fireEvent.keyDown(handle, { key: 'ArrowRight' });
  expect(handle.getAttribute('aria-valuenow')).toBe('320');
  fireEvent.keyDown(handle, { key: 'Home' });
  fireEvent.keyDown(handle, { key: 'ArrowLeft' });
  expect(handle.getAttribute('aria-valuenow')).toBe('160');
});

import { useRef } from 'react';

const minimum = 160;
const maximum = 320;
const clamp = (value: number) => Math.min(maximum, Math.max(minimum, value));

export function SidebarResize({ width, change }: { width: number; change: (width: number) => void }) {
  const drag = useRef<{ id: number; x: number; width: number } | null>(null);
  return <div role="separator" aria-label="调整侧栏宽度" aria-orientation="vertical" tabIndex={0}
    aria-valuemin={minimum} aria-valuemax={maximum} aria-valuenow={width} className="sidebar-resize"
    onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { id: event.pointerId, x: event.clientX, width };
    }}
    onPointerMove={event => {
      if (drag.current?.id === event.pointerId) change(clamp(drag.current.width + event.clientX - drag.current.x));
    }}
    onPointerUp={event => {
      if (drag.current?.id !== event.pointerId) return;
      drag.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }}
    onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
    onKeyDown={event => {
      const next = event.key === 'ArrowLeft' ? width - 8 : event.key === 'ArrowRight' ? width + 8
        : event.key === 'Home' ? minimum : event.key === 'End' ? maximum : null;
      if (next !== null) { event.preventDefault(); change(clamp(next)); }
    }} />;
}

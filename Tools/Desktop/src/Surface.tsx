import { useEffect, useState, type ReactNode } from 'react';
import { Button } from '@fluentui/react-components';
import type { useDevice } from './backend';
import { animatedLight, previewPixel } from './lightPreview';

export type Device = ReturnType<typeof useDevice>;

export function Card({ title, caption, children, className = '' }: {
  title: string; caption?: string; children: ReactNode; className?: string;
}) {
  return <section className={`card ${className}`}>
    <div className="module-heading"><h2>{title}</h2>{caption && <p className="caption">{caption}</p>}</div>
    {children}
  </section>;
}

export function LightStrip({ color, off = false, effect = 'solid', brightness = 255 }: {
  color: string; off?: boolean; effect?: string; brightness?: number;
}) {
  const [elapsed, setElapsed] = useState(0);
  const dark = off || effect === 'off' || brightness === 0;
  useEffect(() => {
    setElapsed(0);
    if (dark || !animatedLight(effect)) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let start: number | undefined;
    let last = -Infinity;
    const tick = (now: number) => {
      start ??= now;
      if (now - last >= 32) { setElapsed(now - start); last = now; }
      frame = requestAnimationFrame(tick);
    };
    const restart = () => {
      cancelAnimationFrame(frame);
      start = undefined;
      last = -Infinity;
      setElapsed(0);
      if (!reduced.matches && !document.hidden) frame = requestAnimationFrame(tick);
    };
    restart();
    reduced.addEventListener('change', restart);
    document.addEventListener('visibilitychange', restart);
    return () => {
      cancelAnimationFrame(frame);
      reduced.removeEventListener('change', restart);
      document.removeEventListener('visibilitychange', restart);
    };
  }, [effect, dark]);
  return <div className="light-strip" aria-label={dark ? '灯带预览：关闭' : `灯带预览：${effect === 'rainbow' ? '彩虹' : color}`} data-effect={effect}>
    {Array.from({ length: 13 }, (_, index) => {
      const pixel = previewPixel(effect, index, elapsed);
      const pixelColor = effect === 'rainbow' ? `hsl(${pixel.hue} 100% 50%)` : color;
      //  屏幕预览保留可见底光，低设备亮度不直接等于低透明度 / Keep a visible preview floor instead of mapping low device brightness directly to opacity
      const level = (0.3 + 0.7 * pixel.level) * (0.65 + 0.35 * Math.sqrt(Math.max(0, Math.min(255, brightness)) / 255));
      return <span key={index} style={{ backgroundColor: dark ? 'var(--led-off)' : pixelColor,
        opacity: dark ? 1 : level, boxShadow: dark ? 'none' : `0 0 12px ${pixelColor}` }} />;
    })}
  </div>;
}

export function SettingRow({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <div className="setting-row"><div className="setting-copy"><h3>{title}</h3>{description && <p>{description}</p>}</div>
    <div className="setting-control">{children}</div></div>;
}

export function ColorField({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (color: string) => void }) {
  return <label className={`color-picker ${disabled ? 'disabled' : ''}`}><input type="color" aria-label={label} value={value}
    disabled={disabled} onChange={event => onChange(event.target.value.toUpperCase())} /><span>{value}</span></label>;
}

export const effectLabels: Record<string, string> = { solid: '常亮', rainbow: '彩虹', breathe: '呼吸灯', sweep: '跑马灯', centerExpand: '扩散灯', off: '关闭灯光' };
export function EffectPicker({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (effect: string) => void }) {
  return <div className="effect-grid" role="group" aria-label="灯光效果">{Object.entries(effectLabels).map(([effect, title]) =>
    <Button key={effect} disabled={disabled} aria-pressed={value === effect} onClick={() => onChange(effect)}>{title}</Button>)}</div>;
}

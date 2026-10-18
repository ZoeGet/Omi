import type { ReactNode } from 'react';
import { Button } from '@fluentui/react-components';
import type { useDevice } from './backend';

export type Device = ReturnType<typeof useDevice>;

export function Card({ title, caption, children, className = '' }: {
  title: string; caption?: string; children: ReactNode; className?: string;
}) {
  return <section className={`card ${className}`}>
    <div className="module-heading"><h2>{title}</h2>{caption && <p className="caption">{caption}</p>}</div>
    {children}
  </section>;
}

export function LightStrip({ color, off = false }: { color: string; off?: boolean }) {
  return <div className="light-strip" aria-label={off ? '灯带预览：关闭' : `灯带预览：${color}`}>
    {Array.from({ length: 13 }, (_, index) => <span key={index}
      style={{ backgroundColor: off ? 'var(--led-off)' : color, boxShadow: off ? 'none' : `0 0 12px ${color}44` }} />)}
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

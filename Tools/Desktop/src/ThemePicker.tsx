import type { ThemePreference } from './theme';

function MiniWindow({ mode }: { mode: 'light' | 'dark' }) {
  return <span className={`theme-mini ${mode}`}><span className="theme-mini-title"><i /><i /><i /></span>
    <span className="theme-mini-body"><span className="theme-mini-sidebar"><i /><i /><i /></span>
      <span className="theme-mini-content"><i /><span /><span /></span></span></span>;
}

export function ThemePicker({ value, change }: { value: ThemePreference; change: (value: ThemePreference) => void }) {
  return <div className="theme-picker" role="radiogroup" aria-label="主题">
    {([['light', '浅色'], ['dark', '深色'], ['system', '跟随系统']] as const).map(([mode, title]) =>
      <label className={`theme-option ${value === mode ? 'selected' : ''}`} key={mode}>
        <input type="radio" name="app-theme" value={mode} checked={value === mode} onChange={() => change(mode)} />
        <span className={`theme-preview ${mode === 'system' ? 'split' : ''}`} aria-hidden="true">
          {mode === 'system' ? <><MiniWindow mode="light" /><MiniWindow mode="dark" /></> : <MiniWindow mode={mode} />}
        </span><span className="theme-option-label"><span className="theme-radio" aria-hidden="true" />{title}</span>
      </label>)}
  </div>;
}

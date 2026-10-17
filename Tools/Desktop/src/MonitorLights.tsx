import { useEffect, useRef, useState } from 'react';
import { Button, MenuItem, Paper, Select, Slider, Typography } from '@mui/material';
import type { Light, MonitorProfile } from './backend';

export const monitorStates = [
  ['working', '运行中', '任务正在执行'],
  ['waitingApproval', '等待操作', '等待审批、选项或自由输入回复'],
  ['idle', '完成 / 空闲', '已收到结束事件'],
  ['unknown', '来源异常 / 无事件', '来源不可读、绑定失效、状态过期或没有有效事件'],
  ['offline', '会话离线', '状态来源报告离线；与设备连接断开不同'],
] as const;
export const effectLabels: Record<string, string> = { solid: '常亮', rainbow: '彩虹', breathe: '呼吸灯', sweep: '跑马灯', centerExpand: '扩散灯', off: '关闭灯光' };
export const lightColor = (light: Light) => `#${[light.red, light.green, light.blue].map(value => value.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
export const lightDescription = (light: Light) => `${effectLabels[light.effect]} · ${lightColor(light)} · 亮度 ${Math.round(light.brightness / 255 * 100)}%`;

export function MonitorLights({ profile, enabled, connected, supported, demo, save, read }: {
  profile?: MonitorProfile | null; enabled: boolean; connected: boolean; supported: boolean; demo: boolean;
  save: (profile: MonitorProfile) => void; read: () => void;
}) {
  const [draft, setDraft] = useState<MonitorProfile | null>(null);
  const previous = useRef('null');
  const serialized = JSON.stringify(profile ?? null);
  useEffect(() => {
    const old = previous.current;
    previous.current = serialized;
    const incoming = JSON.parse(serialized) as MonitorProfile | null;
    setDraft(current => !incoming ? null : !current || JSON.stringify(current) === old ||
      JSON.stringify(current.profiles) === JSON.stringify(incoming.profiles) ? incoming : current);
  }, [serialized]);
  const dirty = Boolean(draft && JSON.stringify(draft) !== serialized);
  const conflict = Boolean(draft && profile && draft.revision !== profile.revision);
  function update(status: string, patch: Partial<Light>) {
    setDraft(value => value ? { ...value, profiles: { ...value.profiles, [status]: { ...value.profiles[status], ...patch } } } : value);
  }
  return <div className="detail-stack">
    <Paper className="card">
      <Typography component="h2" variant="subtitle1">Codex 监控灯效</Typography>
      <Typography variant="body2" color="textSecondary">每种状态独立设置，点击保存后写入设备；重启后进入监控仍使用保存的灯效。断联或租约到期始终关灯，语音优先。</Typography>
      <Typography variant="body2" color="textSecondary">多个会话按等待操作 → 运行中 → 来源异常 → 完成/空闲 → 离线的顺序汇总。无事件与来源异常使用同一项。</Typography>
      {!connected ? <p>请先连接设备。</p> : !supported ? <p>当前固件不支持保存监控灯效，请升级固件。</p> : !profile ? <p>等待设备配置读回…</p> : <p>设备配置版本：{profile.revision}{dirty ? ' · 有未保存修改' : ' · 已读取'}</p>}
      {demo && <p>演示模式仅保存在模拟设备内，不代表断电持久化。</p>}
      {conflict && <p role="alert">设备配置已改变。请重新读取设备配置，再修改并保存。</p>}
    </Paper>
    {draft && monitorStates.map(([status, title, description]) => {
      const light = draft.profiles[status];
      const editable = enabled && supported && !conflict;
      return <Paper component="section" className="card" key={status}>
        <Typography component="h2" variant="subtitle1">{title}</Typography>
        <Typography variant="body2" color="textSecondary">{description}</Typography>
        <div className="monitor-profile-fields">
          <label>颜色 <input aria-label={`${title}颜色`} type="color" value={lightColor(light)} disabled={!editable}
            onChange={event => { const rgb = event.target.value.slice(1).match(/../g)!.map(value => parseInt(value, 16)); update(status, { red: rgb[0], green: rgb[1], blue: rgb[2] }); }} /></label>
          <Select size="small" value={light.effect} disabled={!editable} inputProps={{ 'aria-label': `${title}灯效` }}
            onChange={event => update(status, { effect: event.target.value })}>
            {Object.entries(effectLabels).map(([value, label]) => <MenuItem value={value} key={value}>{label}</MenuItem>)}
          </Select>
          <div><Typography variant="body2">亮度 {light.brightness}/255 · {Math.round(light.brightness / 255 * 100)}%</Typography>
            <Slider aria-label={`${title}亮度`} value={light.brightness} min={0} max={255} step={1} disabled={!editable}
              onChange={(_, value) => update(status, { brightness: value as number })} /></div>
        </div>
        <Typography variant="body2" color="textSecondary">{lightDescription(light)}{light.effect === 'rainbow' ? ' · 彩虹使用独立色谱' : ''}</Typography>
      </Paper>;
    })}
    <Paper className="card"><div className="button-row">
      <Button variant="outlined" disabled={!enabled || !profile} onClick={() => { setDraft(JSON.parse(serialized)); read(); }}>重新读取设备配置</Button>
      <Button variant="contained" disabled={!enabled || !supported || !draft || !dirty || conflict}
        onClick={() => { if (draft) save(draft); }}>保存监控灯效到设备</Button>
    </div><Typography variant="body2" color="textSecondary">一次保存全部状态。监控开启时可修改，收到设备保存确认才算成功。修改不会自动开启监控。</Typography></Paper>
  </div>;
}

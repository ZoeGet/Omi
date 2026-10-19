import { useEffect, useRef, useState } from 'react';
import { Button, Slider } from '@fluentui/react-components';
import { ArrowSync20Regular, Save20Regular, ChevronRight16Regular } from '@fluentui/react-icons';
import type { Light, MonitorProfile } from './backend';
import { Card, ColorField, EffectPicker, LightStrip, SettingRow, effectLabels } from './Surface';

export const monitorStates = [
  ['working', '运行中', '任务正在执行'],
  ['waitingApproval', '等待操作', '等待审批、选项或自由输入回复'],
  ['idle', '完成 / 空闲', '已收到结束事件'],
  ['unknown', '来源异常 / 无事件', '来源不可读、绑定失效、状态过期或没有有效事件'],
  ['offline', '会话离线', '状态来源报告离线；与设备连接断开不同'],
] as const;
export const lightColor = (light: Light) => `#${[light.red, light.green, light.blue].map(value => value.toString(16).padStart(2, '0')).join('').toUpperCase()}`;
export const lightDescription = (light: Light) => `${effectLabels[light.effect]} · ${lightColor(light)} · 亮度 ${Math.round(light.brightness / 255 * 100)}%`;

export function MonitorLights({ profile, enabled, connected, supported, demo, save, read }: {
  profile?: MonitorProfile | null; enabled: boolean; connected: boolean; supported: boolean; demo: boolean;
  save: (profile: MonitorProfile) => void; read: () => void;
}) {
  const [draft, setDraft] = useState<MonitorProfile | null>(null);
  const [selected, setSelected] = useState('working');
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
  const editable = enabled && supported && !conflict;
  const [status, title, description] = monitorStates.find(item => item[0] === selected)!;
  const light = draft?.profiles[status];
  function update(patch: Partial<Light>) {
    setDraft(value => value ? { ...value, profiles: { ...value.profiles, [status]: { ...value.profiles[status], ...patch } } } : value);
  }
  return <div className="monitor-page">
    <div className="monitor-summary"><div><strong>{!connected ? '请先连接设备。' : !supported ? '当前固件不支持保存监控灯效，请升级固件。' : !profile ? '等待设备配置读回…' : `设备配置版本：${profile.revision}`}</strong>
      <p>断联或租约到期始终关灯，语音优先。</p></div><span className={`save-state ${dirty ? 'dirty' : ''}`}>{dirty ? '有未保存修改' : profile ? '已读取设备配置' : '等待设备'}</span></div>
    {demo && <p className="module-note">演示模式仅保存在模拟设备内，不代表断电持久化。</p>}
    {conflict && <p role="alert" className="conflict-notice">设备配置已改变。请重新读取设备配置，再修改并保存。</p>}
    {draft && light ? <div className="monitor-layout"><section className="profile-list" aria-label="选择监控状态"><h2>状态规则</h2>
      {monitorStates.map(([key, label]) => <Button key={key} appearance="subtle" className={`profile-choice ${selected === key ? 'selected' : ''}`}
        aria-pressed={selected === key} aria-label={`编辑${label}`} onClick={() => setSelected(key)}>
        <span className="profile-dot" style={{ backgroundColor: lightColor(draft.profiles[key]) }} /><span><strong>{label}</strong><small>{effectLabels[draft.profiles[key].effect]} · {draft.profiles[key].brightness}/255</small></span><ChevronRight16Regular /></Button>)}
      <p className="module-note">多会话优先级：等待 → 运行 → 异常 → 完成 → 离线。</p>
    </section><Card title={title} caption={description} className="profile-editor">
      <SettingRow title="颜色"><ColorField label={`${title}颜色`} value={lightColor(light)} disabled={!editable} onChange={color => {
        const rgb = color.slice(1).match(/../g)!.map(value => parseInt(value, 16)); update({ red: rgb[0], green: rgb[1], blue: rgb[2] });
      }} /></SettingRow>
      <SettingRow title="亮度" description={`${light.brightness}/255 · ${Math.round(light.brightness / 255 * 100)}%`}><Slider aria-label={`${title}亮度`} min={0} max={255} value={light.brightness} disabled={!editable} onChange={(_, data) => update({ brightness: data.value })} /></SettingRow>
      <SettingRow title="灯效"><EffectPicker value={light.effect} disabled={!editable} onChange={effect => update({ effect })} /></SettingRow>
      <LightStrip color={lightColor(light)} effect={light.effect} brightness={light.brightness} /><p className="module-note">动画模拟编辑值，不代表设备当前输出。{light.effect === 'rainbow' ? '彩虹使用独立色谱。' : ''}</p>
    </Card></div> : <div className="empty-state monitor-empty"><h2>{connected ? '等待监控灯效配置' : '连接设备后设置灯效'}</h2><p>五种状态可独立编辑，保存后重启仍保留。</p></div>}
    <section className="apply-row"><div><strong>{dirty ? '保存全部五种状态' : '配置保存在设备中'}</strong><p>收到设备保存确认后生效。保存不会自动开启监控。</p></div><div className="button-row">
      <Button icon={<ArrowSync20Regular />} disabled={!enabled || !profile} onClick={() => { setDraft(JSON.parse(serialized)); read(); }}>重新读取设备配置</Button>
      <Button appearance="primary" icon={<Save20Regular />} disabled={!enabled || !supported || !draft || !dirty || conflict} onClick={() => { if (draft) save(draft); }}>保存监控灯效到设备</Button>
    </div></section>
  </div>;
}

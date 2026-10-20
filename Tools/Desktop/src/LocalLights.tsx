import { useRef } from 'react';
import { Button, Slider } from '@fluentui/react-components';
import { Card, EffectPicker, LightStrip, type Device } from './Surface';
import { lightColor, lightDescription, monitorStates } from './MonitorLights';

export type LightDraft = { color: string; brightness: number; effect: string };
const colors = [
  '#FFFFFF', '#FFF4D6', '#FFD6A5', '#FFB347', '#FF8000', '#FF4500', '#FF0000', '#DC143C',
  '#FFFF00', '#D4FF00', '#80FF00', '#00FF00', '#00C853', '#00BFA5', '#00FFFF', '#00BFFF',
  '#0080FF', '#0000FF', '#6A5ACD', '#8A2BE2', '#BF00FF', '#FF00FF', '#FF69B4', '#FFB6C1',
];

export function LocalLights({ device, draft, change }: { device: Device; draft: LightDraft; change: (light: LightDraft) => void }) {
  const { connected, busy, snapshot } = device;
  const colorInput = useRef<HTMLInputElement>(null);
  const monitoring = Boolean(snapshot.monitorRequested);
  const editable = device.ready && connected && !busy && !monitoring && snapshot.state?.mode === 'local' && Boolean(snapshot.operations?.includes('light'));
  const percent = Math.round(draft.brightness / 255 * 100);
  function apply() {
    const rgb = draft.color.slice(1).match(/../g)!.map(value => parseInt(value, 16));
    void device.send('light', { effect: draft.effect, red: rgb[0], green: rgb[1], blue: rgb[2], brightness: draft.brightness });
  }
  return <div className="lighting-grid">
    <Card title="编辑灯光" caption="颜色、亮度与灯效一起应用" className="light-editor">
      <div className="field-title"><strong>灯光颜色</strong><span className="muted">常用色</span></div>
      <div className="swatches">{colors.map(value => <button key={value} type="button" aria-label={`选择颜色 ${value}`} aria-pressed={draft.color === value}
        title={value} style={{ backgroundColor: value }} disabled={!editable} onClick={() => change({ ...draft, color: value })} />)}</div>
      <div className="custom-light-color">
        <span className="custom-color-trigger">
          <Button disabled={!editable} onClick={() => colorInput.current?.click()}>自定义颜色</Button>
          <input ref={colorInput} type="color" aria-label="自定义灯光颜色" value={draft.color} disabled={!editable} tabIndex={-1}
            onChange={event => change({ ...draft, color: event.target.value.toUpperCase() })} />
        </span>
        <span className="custom-color-value"><i style={{ backgroundColor: draft.color }} />{draft.color}</span>
      </div>
      <div className="field-title"><strong>灯光亮度</strong><span className="muted">{draft.brightness}/255 · {percent}%</span></div>
      <Slider aria-label="灯光亮度" min={0} max={255} value={draft.brightness} disabled={!editable} onChange={(_, data) => change({ ...draft, brightness: data.value })} />
      <div className="field-title"><strong>灯效</strong></div><EffectPicker value={draft.effect} disabled={!editable} onChange={effect => change({ ...draft, effect })} />
      <p className="module-note">彩虹使用独立色谱；关闭灯光保留编辑参数。</p>
    </Card>
    <Card title="灯光预览" caption="模拟编辑值的颜色、亮度与动画，不是设备实时读回"><LightStrip color={draft.color} effect={draft.effect} brightness={draft.brightness} /><p className="muted">{draft.effect === 'rainbow' ? '独立彩虹色谱' : draft.color} · 亮度 {percent}%</p></Card>
    <Card title="监控灯光规则"><ul className="rules">{monitorStates.map(([key, title]) => <li key={key}><i style={{ backgroundColor: snapshot.monitorProfile?.profiles[key] ? lightColor(snapshot.monitorProfile.profiles[key]) : 'var(--muted)' }} /><span>{title}</span>
      <strong>{snapshot.monitorProfile?.profiles[key] ? lightDescription(snapshot.monitorProfile.profiles[key]) : key === 'working' ? '红色扩散灯' : key === 'waitingApproval' ? '黄色扩散灯' : '绿色扩散灯'}</strong></li>)}</ul><p className="module-note">来源异常和离线使用设备保存的配置；连接断开则关灯。</p></Card>
    <section className="apply-row"><p>{!connected ? '请先连接设备。' : monitoring ? '监控模式已锁定手动灯光，请先切回本地。' : !editable ? '等待设备就绪或确认灯光能力。' : '收到设备回执后才确认成功。'}</p>
      <Button appearance="primary" disabled={!editable} onClick={apply}>应用灯光设置</Button></section>
  </div>;
}

import { Button, Select, Switch } from '@fluentui/react-components';
import { ArrowRight20Regular, ArrowSync20Regular } from '@fluentui/react-icons';
import { Card, LightStrip, type Device } from './Surface';
import { lightColor, lightDescription } from './MonitorLights';
import type { LightDraft } from './LocalLights';

export function Overview({ device, light, navigate }: { device: Device; light: LightDraft; navigate: (page: string) => void }) {
  const { connected, busy, snapshot, settings } = device;
  const monitoring = Boolean(snapshot.monitorRequested);
  const confirmed = snapshot.state;
  const local = connected && !monitoring && confirmed?.mode === 'local';
  const active = device.ready && connected && !busy;
  const monitorReady = snapshot.monitorLights && snapshot.monitorGreenOff;
  const monitorConnected = monitoring && confirmed?.monitorOutput === 'connected';
  const saved = snapshot.monitorProfile?.profiles;
  const canConfigure = device.ready && !connected && !busy;
  const defaults: Record<string, { title: string; color: string; note: string }> = {
    idle: { title: '无任务 / 完成', color: '#20a66a', note: '绿色扩散灯' },
    working: { title: '运行中', color: '#e45d64', note: '红色扩散灯' },
    waitingApproval: { title: '等待操作', color: '#dba32c', note: '审批或回复 · 黄色扩散灯' },
    unknown: { title: '来源异常', color: '#20a66a', note: '绿色扩散灯 · 状态仍为未知' },
    offline: { title: '会话离线', color: '#20a66a', note: '绿色扩散灯' },
  };
  const display = !connected ? { title: '等待连接', color: '#8a8a8a', note: '连接设备后显示实际状态' }
    : !confirmed || monitoring && !monitorConnected ? { title: '连接中断', color: '#8a8a8a', note: '设备检测到断联后关灯，等待重新连接' }
    : !monitoring ? { title: '本地灯光', color: '#3987c6', note: '灯光由手动设置或语音控制' }
    : (() => { const base = defaults[confirmed.displayStatus] ?? defaults.unknown; const p = saved?.[confirmed.displayStatus];
      return p ? { ...base, color: lightColor(p), note: lightDescription(p) } : base; })();
  return <div className="overview-grid">
    <Card title="设备连接" caption="USB 直连，或从无线配对页连接已保存设备" className="connection-module">
      <div className="connection-content"><div className="connection-summary"><span className="module-symbol">USB / WSS</span>
        <h3>{connected ? '连接已建立' : '连接你的 Omi'}</h3><p className="muted">{connected ? device.transport === 'wifi' ? '可信无线连接' : 'USB 串口连接' : '选择串口后连接设备'}</p></div>
        <div className="connection-controls">{connected && device.transport === 'wifi' ? <p className="endpoint">{device.endpoint}</p> :
          <div className="port-row"><Select value={settings.port} disabled={!canConfigure} aria-label="USB 串口"
            onChange={(_, data) => device.settingsChanged({ port: data.value })}>
            <option value="">{device.ports.length ? '请选择串口' : '未找到串口'}</option>
            {device.ports.map(port => <option key={port.device} value={port.device}>{port.device} · {port.description}</option>)}
          </Select><Button icon={<ArrowSync20Regular />} disabled={!canConfigure} onClick={() => void device.refresh()} aria-label="刷新串口" /></div>}
          <div className="button-row"><Button appearance="primary" disabled={!canConfigure || !settings.port || !settings.root || !settings.bindings}
            onClick={() => void device.send('connect', settings)}>连接设备</Button><Button disabled={!connected || busy} onClick={() => void device.send('disconnect')}>断开连接</Button></div>
        </div></div>
    </Card>
    <Card title="控制模式" caption="选择本地控制，或跟随 Codex 状态">
      <div className="mode-list">{([['local', '本地灯光', '手动设置与语音控制'], ['monitor', 'Codex 监控', '跟随任务运行与等待状态']] as const).map(([key, text, note]) =>
        <div className="mode-row" key={key}><div><strong>{text}</strong><small>{note}</small></div>
          <Switch checked={Boolean(key === 'local' ? local : monitorConnected)} disabled={!active || key === 'monitor' && !monitorReady}
            onChange={() => void device.send(key)} aria-label={text} /></div>)}</div>
      <p className="module-note">{connected && !monitorReady ? '当前固件不支持监控灯光规则。' : '监控中锁定手动调灯，语音可立即接管。'}</p>
    </Card>
    <Card title="监控状态" caption={device.transport === 'wifi' ? '本连接已确认状态；同时监控时 USB 优先' : '最近一次设备确认的状态'}>
      <div className="status-display"><span className="status-indicator" style={{ backgroundColor: display.color }} /><div><h3 role="status">{display.title}</h3><p>{display.note}</p></div></div>
      <div className="legend">{(['idle', 'working', 'waitingApproval'] as const).map(key => <span key={key}><i style={{ backgroundColor: saved?.[key] ? lightColor(saved[key]) : defaults[key].color }} />{defaults[key].title}</span>)}</div>
    </Card>
    <Card title="灯光预览" caption="编辑值，不是设备实时灯光读回" className="preview-module">
      <LightStrip color={monitoring ? display.color : light.color} off={!connected || !confirmed || monitoring && (!monitorConnected || saved?.[confirmed?.displayStatus ?? 'unknown']?.effect === 'off' || saved?.[confirmed?.displayStatus ?? 'unknown']?.brightness === 0) || !monitoring && (light.effect === 'off' || light.brightness === 0)} />
      <div className="preview-caption"><span className="muted">{monitoring ? display.note : `${light.color} · 亮度 ${Math.round(light.brightness / 255 * 100)}%`}</span>
        <Button appearance="subtle" icon={<ArrowRight20Regular />} iconPosition="after" onClick={() => navigate('lights')}>调整灯光</Button></div>
    </Card>
    <section className="metrics" aria-label="连接摘要">{[['连接方式', device.demo ? '模拟设备' : device.transport === 'wifi' ? 'Wi-Fi' : 'USB'], ['通信超时', `${snapshot.diagnostics?.replyTimeouts ?? 0} 次`],
      ['当前模式', !connected ? '等待连接' : !confirmed ? '待确认' : monitoring ? 'Codex 监控' : '本地灯光'],
      ['输出状态', monitorConnected ? '监控输出' : connected ? '本地控制' : '连接未建立']].map(([key, value]) => <div key={key}><small>{key}</small><strong>{value}</strong></div>)}</section>
  </div>;
}

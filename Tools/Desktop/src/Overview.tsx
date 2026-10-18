import { useEffect, useState } from 'react';
import { Button, Select, Switch, Tab, TabList } from '@fluentui/react-components';
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
  const [connectionType, setConnectionType] = useState<'usb' | 'wifi'>(device.transport ?? 'usb');
  const [wirelessDevices, setWirelessDevices] = useState<{ address: string; confirmed: boolean; pendingRepair?: boolean }[]>([]);
  const [wirelessAddress, setWirelessAddress] = useState('');
  const [wirelessLoading, setWirelessLoading] = useState(false);
  const [wirelessError, setWirelessError] = useState('');
  const [wirelessRefresh, setWirelessRefresh] = useState(0);
  useEffect(() => {
    if (connected && device.transport) setConnectionType(device.transport);
  }, [connected, device.transport]);
  useEffect(() => {
    if (connectionType !== 'wifi' || !device.ready || connected || busy || device.demo) return;
    let cancelled = false;
    setWirelessLoading(true); setWirelessError('');
    device.request('paired-devices').then(reply => {
      if (cancelled) return;
      if (!reply.ok || !Array.isArray(reply.result)) throw new Error(reply.error ?? '无法读取已保存设备');
      const devices = reply.result as typeof wirelessDevices;
      setWirelessDevices(devices);
      const available = devices.filter(item => item.confirmed && !item.pendingRepair);
      setWirelessAddress(current => available.some(item => item.address === current) ? current : available.length === 1 ? available[0].address : '');
    }).catch(error => {
      if (!cancelled) { setWirelessDevices([]); setWirelessAddress(''); setWirelessError(String(error)); }
    }).finally(() => { if (!cancelled) setWirelessLoading(false); });
    return () => { cancelled = true; };
  }, [connectionType, device.ready, connected, busy, device.demo, device.request, wirelessRefresh]);
  const wifi = connectionType === 'wifi';
  const canConnect = canConfigure && settings.root && settings.bindings && (wifi
    ? !wirelessLoading && wirelessDevices.some(item => item.address === wirelessAddress && item.confirmed && !item.pendingRepair)
    : device.ports.some(port => port.device === settings.port));
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
    <Card title="设备连接" caption="选择 USB 直连或 Wi-Fi，连接后可控制灯光与 Codex 监控" className="connection-module">
      <div className="connection-content"><div className="connection-summary"><span className="module-symbol">{connected ? device.transport === 'wifi' ? 'WI-FI' : 'USB' : 'USB / WI-FI'}</span>
        <h3>{connected ? '连接已建立' : '连接你的 Omi'}</h3><p className="muted">{connected ? device.transport === 'wifi' ? '可信无线连接' : 'USB 串口连接' : wifi ? '选择已配对设备，无需再次输入配对码' : '使用数据线连接设备，选择 USB 串口'}</p></div>
        <div className="connection-controls"><TabList aria-label="连接方式" selectedValue={connectionType}
          onTabSelect={(_, data) => setConnectionType(data.value as 'usb' | 'wifi')}>
          <Tab value="usb" aria-selected={connectionType === 'usb'} disabled={!canConfigure}>USB</Tab><Tab value="wifi" aria-selected={connectionType === 'wifi'} disabled={!canConfigure || device.demo}>Wi-Fi</Tab>
        </TabList>{connected ? <p className="endpoint">{device.endpoint}</p> : wifi ? <>
          <div className="port-row"><Select value={wirelessAddress} disabled={!canConfigure || wirelessLoading} aria-label="已配对的无线设备"
            onChange={(_, data) => setWirelessAddress(data.value)}>
            <option value="">{wirelessLoading ? '正在读取设备…' : wirelessDevices.length ? '请选择无线设备' : '尚无已保存设备'}</option>
            {wirelessDevices.map(item => <option key={item.address} value={item.address} disabled={!item.confirmed || item.pendingRepair}>
              {item.address}{!item.confirmed || item.pendingRepair ? ' · 待验证' : ''}</option>)}
          </Select><Button icon={<ArrowSync20Regular />} disabled={!canConfigure || wirelessLoading} onClick={() => setWirelessRefresh(value => value + 1)} aria-label="刷新无线设备" /></div>
          {wirelessError && <p role="alert" className="module-note">{wirelessError}</p>}
        </> :
          <div className="port-row"><Select value={settings.port} disabled={!canConfigure} aria-label="USB 串口"
            onChange={(_, data) => device.settingsChanged({ port: data.value })}>
            <option value="">{device.ports.length ? '请选择串口' : '未找到串口'}</option>
            {device.ports.map(port => <option key={port.device} value={port.device}>{port.device} · {port.description}</option>)}
          </Select><Button icon={<ArrowSync20Regular />} disabled={!canConfigure} onClick={() => void device.refresh()} aria-label="刷新串口" /></div>}
          <div className="button-row"><Button appearance="primary" disabled={!canConnect}
            onClick={() => void device.send(wifi ? 'connect-wireless' : 'connect', wifi ? { ...settings, port: wirelessAddress } : settings)}>连接设备</Button><Button disabled={!connected || busy} onClick={() => void device.send('disconnect')}>断开连接</Button></div>
          {wifi && !connected && <p className="module-note">电脑与设备需处于可互通的局域网。首次配对、换网寻址或待验证的设备，请前往<Button appearance="transparent" disabled={busy} onClick={() => navigate('pairing')}>配对与设备管理</Button>。</p>}
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
    <section className="metrics" aria-label="连接摘要">{[['连接方式', device.demo ? '模拟设备' : !connected ? '未连接' : device.transport === 'wifi' ? 'Wi-Fi' : 'USB'], ['通信超时', `${snapshot.diagnostics?.replyTimeouts ?? 0} 次`],
      ['当前模式', !connected ? '等待连接' : !confirmed ? '待确认' : monitoring ? 'Codex 监控' : '本地灯光'],
      ['输出状态', monitorConnected ? '监控输出' : connected ? '本地控制' : '连接未建立']].map(([key, value]) => <div key={key}><small>{key}</small><strong>{value}</strong></div>)}</section>
  </div>;
}

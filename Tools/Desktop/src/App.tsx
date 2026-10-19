import { useState, type CSSProperties } from 'react';
import { Badge, Button, FluentProvider } from '@fluentui/react-components';
import { Home20Regular, Lightbulb20Regular, PlugConnected20Regular, Settings20Regular,
  Pulse20Regular, Link20Regular, ShieldCheckmark20Regular } from '@fluentui/react-icons';
import { useDevice } from './backend';
import { Overview } from './Overview';
import { LocalLights, type LightDraft } from './LocalLights';
import { MonitorLights } from './MonitorLights';
import { Pairing, Diagnostics, Settings } from './DevicePages';
import { useAppTheme } from './theme';
import type { Device } from './Surface';
import { SidebarResize } from './SidebarResize';
import { MonitorSetup } from './MonitorSetup';
import appIcon from '../src-tauri/icons/256x256.png';

const pages = [
  { id: 'overview', title: '设备概览', icon: <Home20Regular />, caption: '连接设备，查看控制模式与当前状态。' },
  { id: 'lights', title: '灯光与灯效', icon: <Lightbulb20Regular />, caption: '设置本地灯光的颜色、亮度与效果。' },
  { id: 'monitor-lights', title: '监控灯效', icon: <Pulse20Regular />, caption: '为每种 Codex 状态设置灯效，保存到设备。' },
  { id: 'pairing', title: '无线配对', icon: <Link20Regular />, caption: '通过设备屏幕上的六位码，建立可信无线连接。' },
  { id: 'diagnostics', title: '连接诊断', icon: <PlugConnected20Regular />, caption: '查看通信质量、设备健康和最近操作。' },
  { id: 'settings', title: '设置', icon: <Settings20Regular />, caption: '选择外观主题，管理 Codex 状态来源与宿主绑定。' },
];

export default function App() {
  const device = useDevice();
  const appearance = useAppTheme();
  return <Desktop device={device} appearance={appearance} />;
}

export function Desktop({ device, appearance: { dark, theme, preference, setPreference } }: { device: Device; appearance: ReturnType<typeof useAppTheme> }) {
  const [page, setPage] = useState('overview');
  const [setupChecked, setSetupChecked] = useState(() => {
    try { return localStorage.getItem('omi.monitorSetup.dismissed') === '1'; }
    catch { return false; }
  });
  function dismissSetup() {
    setSetupChecked(true);
    try { localStorage.setItem('omi.monitorSetup.dismissed', '1'); }
    catch {
      //  存储不可用时仍允许本次收起 / Allow dismissal for this session when storage is unavailable
    }
  }
  const [sidebarWidth, setSidebarWidth] = useState(216);
  const [light, setLight] = useState<LightDraft>({ color: '#FFFFFF', brightness: 16, effect: 'solid' });
  const heading = pages.find(item => item.id === page)!;
  const active = device.ready && device.connected && !device.busy;
  return <FluentProvider theme={theme} className="app-provider" style={{ colorScheme: dark ? 'dark' : 'light' }}>
    <div className="shell" data-theme={dark ? 'dark' : 'light'} style={{ '--sidebar-width': `${sidebarWidth}px` } as CSSProperties}>
      <aside className="sidebar">
        <div className="brand"><img className="brand-icon" src={appIcon} alt="" /><div><strong>Omi</strong><small>设备控制中心</small></div></div>
        <span className="nav-label">工作空间</span>
        <nav aria-label="主导航">{pages.map((item, index) => <Button key={item.id} appearance="subtle" icon={item.icon}
          className={`nav ${page === item.id ? 'selected' : ''} ${index === 3 ? 'nav-divider' : ''}`}
          onClick={() => setPage(item.id)} aria-current={page === item.id ? 'page' : undefined}>{item.title}</Button>)}</nav>
        <div className="sidebar-bottom"><span className="pilot-label">OMI DESKTOP · 0.2</span>
          <strong><i className={device.connected ? 'connection-dot online' : 'connection-dot'} />{device.connected ? '设备已连接' : '等待设备连接'}</strong>
          <small>{device.demo ? '演示模式 · 模拟设备' : 'USB / Wi-Fi'}</small></div>
      </aside>
      <SidebarResize width={sidebarWidth} change={setSidebarWidth} />
      <div className="workspace">
        <header className="topbar"><span>Omi <span className="breadcrumb">/ {heading.title}</span></span><div className="header-status">
          <Badge appearance="tint" color="informative">{device.demo ? '演示模式' : !device.connected ? 'USB / Wi-Fi' : device.transport === 'wifi' ? 'Wi-Fi' : 'USB'}</Badge>
          <span><i className={device.connected ? 'connection-dot online' : 'connection-dot'} />{device.busy ? '处理中…' : device.connected ? '已连接' : '未连接'}</span>
        </div></header>
        <main key={page} id="page-content"><div className="page-heading"><div><h1>{heading.title}</h1><p>{heading.caption}</p></div>
          <span className="policy-label"><ShieldCheckmark20Regular />{device.demo ? '模拟设备' : '语音优先'}</span></div>
          {page === 'overview' && <>{!setupChecked && !device.demo && <MonitorSetup device={device} firstRun completed={dismissSetup} />}<Overview device={device} light={light} navigate={setPage} /></>}
          {page === 'lights' && <LocalLights device={device} draft={light} change={setLight} />}
          {page === 'monitor-lights' && <MonitorLights key={`${device.endpoint}-${device.connected}`} profile={device.snapshot.monitorProfile}
            enabled={active && Boolean(device.snapshot.state)} connected={device.connected} supported={Boolean(device.snapshot.operations?.includes('monitorProfile'))}
            demo={device.demo} save={profile => void device.send('monitor-profile', profile)} read={() => void device.send('monitor-profile-read')} />}
          {page === 'pairing' && <Pairing device={device} navigate={setPage} />}
          {page === 'diagnostics' && <Diagnostics device={device} />}
          {page === 'settings' && <Settings device={device} themePreference={preference} changeTheme={setPreference} />}
        </main>
        <footer className="app-notice" aria-live="polite"><span className="notice-dot" />{device.notice}</footer>
      </div>
    </div>
  </FluentProvider>;
}

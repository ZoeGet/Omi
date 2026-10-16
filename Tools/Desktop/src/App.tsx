import { useState, type ReactNode } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { Button, Chip, CssBaseline, MenuItem, Paper, Select, Slider, Switch, TextField,
  ThemeProvider, ToggleButton, ToggleButtonGroup, Typography, createTheme } from '@mui/material';
import DashboardOutlined from '@mui/icons-material/DashboardOutlined';
import LightModeOutlined from '@mui/icons-material/LightModeOutlined';
import CableOutlined from '@mui/icons-material/CableOutlined';
import AutoAwesomeOutlined from '@mui/icons-material/AutoAwesomeOutlined';
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded';
import SettingsOutlined from '@mui/icons-material/SettingsOutlined';
import MonitorHeartOutlined from '@mui/icons-material/MonitorHeartOutlined';
import LinkOutlined from '@mui/icons-material/LinkOutlined';
import { useDevice } from './backend';

const theme = createTheme({
  palette: { primary: { main: '#3478f6' }, background: { default: '#f6f8fc' },
    text: { primary: '#182437', secondary: '#8290a4' } },
  typography: { fontFamily: '"Segoe UI", "Microsoft YaHei UI", sans-serif',
    button: { textTransform: 'none', fontWeight: 600 }, body2: { fontSize: 13 } },
  shape: { borderRadius: 14 },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 10, minHeight: 38 } } },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: '1px solid #e8edf4' } } },
    MuiSwitch: { defaultProps: { disableRipple: true } },
  },
});
const effects = { '常亮': 'solid', '彩虹': 'rainbow', '呼吸灯': 'breathe', '跑马灯': 'sweep', '扩散灯': 'centerExpand', '关闭灯光': 'off' };
const colors = ['#FFFFFF', '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF'];
const states = {
  idle: { title: '无任务 / 完成', color: '#20a66a', note: '绿色扩散灯' },
  working: { title: '运行中', color: '#e45d64', note: '红色扩散灯' },
  waitingApproval: { title: '等待操作', color: '#dba32c', note: '审批或回复 · 黄色扩散灯' },
  unknown: { title: '来源异常', color: '#20a66a', note: '绿色扩散灯 · 状态仍为未知' },
};
const pages = [
  { id: 'overview', title: '设备概览', icon: <DashboardOutlined />, caption: '让设备状态清晰可见，让每一次控制简单直接。' },
  { id: 'lights', title: '灯光与灯效', icon: <LightModeOutlined />, caption: '一点颜色，一种氛围。为你的桌面设置合适的光。' },
  { id: 'pairing', title: '无线配对', icon: <LinkOutlined />, caption: 'USB 控制已接入，无线连接仍待开发。' },
  { id: 'diagnostics', title: '连接诊断', icon: <MonitorHeartOutlined />, caption: '查看通信质量、设备健康和操作结果。' },
  { id: 'settings', title: '设置', icon: <SettingsOutlined />, caption: '指定本机 Codex 状态来源，断开连接后可修改。' },
];
function Card({ title, caption, children, className = '' }: {
  title: string; caption?: string; children: ReactNode; className?: string;
}) {
  return <Paper component="section" className={`card ${className}`}>
    <Typography component="h2" variant="subtitle1" sx={{ fontWeight: 650 }}>{title}</Typography>
    {caption && <Typography variant="body2" color="textSecondary" className="caption">{caption}</Typography>}
    {children}
  </Paper>;
}
function LightStrip({ color, off = false }: { color: string; off?: boolean }) {
  return <div className="light-strip" aria-label={off ? '灯带预览：关闭' : `灯带预览：${color}`}>
    {Array.from({ length: 13 }, (_, index) => <span key={index}
      style={{ backgroundColor: off ? '#dce3ee' : color, boxShadow: off ? 'none' : `0 0 12px ${color}55` }} />)}
  </div>;
}
export default function App() {
  const device = useDevice();
  const [page, setPage] = useState('overview');
  const [color, setColor] = useState('#FFFFFF');
  const [brightness, setBrightness] = useState(16);
  const [effect, setEffect] = useState<keyof typeof effects>('常亮');
  const { connected, busy, snapshot, settings } = device;
  const monitoring = Boolean(snapshot.monitorRequested);
  const confirmed = snapshot.state;
  const local = connected && !monitoring && confirmed?.mode === 'local';
  const active = device.ready && connected && !busy;
  const editable = active && local && Boolean(snapshot.operations?.includes('light'));
  const monitorReady = snapshot.monitorLights && snapshot.monitorGreenOff;
  const monitorConnected = monitoring && confirmed?.monitorOutput === 'connected';
  const display = !connected ? { title: '等待连接', color: '#a5b1c3', note: '连接设备后显示实际状态' }
    : !confirmed || monitoring && !monitorConnected ? { title: '连接中断', color: '#a5b1c3', note: '设备检测到断联后关灯，等待重新连接' }
    : !monitoring ? { title: '本地灯光', color: '#3478f6', note: '灯光由手动设置或语音控制' }
    : states[confirmed.displayStatus as keyof typeof states] ?? states.unknown;
  const percent = Math.round(brightness / 255 * 100);
  const heading = pages.find(item => item.id === page)!;
  const diagnostic = snapshot.diagnostics ?? {};
  const health = snapshot.health ?? {};
  const canConfigure = device.ready && !connected && !busy;
  async function choose(directory: boolean) {
    try {
      const path = await open(directory ? { directory: true, multiple: false } : {
        multiple: false, filters: [{ name: 'JSON', extensions: ['json'] }] });
      if (typeof path === 'string') device.settingsChanged(directory ? { root: path } : { bindings: path });
    } catch (error) { device.report(`无法选择路径：${error}`); }
  }
  function applyLight() {
    const rgb = color.slice(1).match(/../g)!.map(value => parseInt(value, 16));
    void device.send('light', { effect: effects[effect], red: rgb[0], green: rgb[1], blue: rgb[2], brightness });
  }
  return <ThemeProvider theme={theme}><CssBaseline />
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-icon"><AutoAwesomeOutlined /></div><div>
          <strong>OmiPet</strong><small>桌面设备控制中心</small>
        </div></div>
        <nav aria-label="主导航">{pages.map(item => <Button key={item.id} startIcon={item.icon}
          className={page === item.id ? 'nav selected' : 'nav'} onClick={() => setPage(item.id)}
          aria-current={page === item.id ? 'page' : undefined}>{item.title}</Button>)}</nav>
        <div className="sidebar-bottom"><span className="pilot-label">OMIPET DESKTOP · 0.2</span>
          <strong>你的桌面，随心而亮。</strong><small>{device.demo ? '演示模式 · 模拟设备' : 'USB 设备控制'}</small></div>
      </aside>
      <div className="workspace">
        <header className="topbar"><span>设备工作台 <span className="breadcrumb">/ OmiPet</span></span>
          <div className="header-status"><Chip label={device.demo ? '演示模式' : 'USB'} size="small" variant="outlined" />
            <span><i className={connected ? 'connection-dot online' : 'connection-dot'} />{busy ? '处理中…' : connected ? '已连接' : '未连接'}</span>
          </div></header>
        <main>
          <div className="page-heading"><div><h1>{heading.title}</h1><p>{heading.caption}</p></div>
            <Chip label={device.demo ? '模拟设备' : '语音始终优先'} size="small" className="demo-chip" /></div>
          {page === 'overview' && <div className="overview-grid">
            <Card title="设备连接" caption="USB 直连 · 能力与状态以设备回执为准">
              <div className="port-row"><Select value={settings.port} displayEmpty size="small" fullWidth
                disabled={!canConfigure} inputProps={{ 'aria-label': 'USB 串口' }}
                onChange={event => device.settingsChanged({ port: event.target.value })}>
                <MenuItem value="">{device.ports.length ? '请选择串口' : '未找到串口'}</MenuItem>
                {device.ports.map(port => <MenuItem key={port.device} value={port.device}>
                  <CableOutlined fontSize="small" className="inline-icon" />{port.device} · {port.description}</MenuItem>)}
              </Select><Button disabled={!canConfigure} onClick={() => void device.refresh()}>刷新</Button></div>
              <div className="button-row"><Button variant="contained" fullWidth disabled={!canConfigure || !settings.port || !settings.root || !settings.bindings}
                onClick={() => void device.send('connect', settings)}>连接设备</Button>
                <Button variant="outlined" fullWidth disabled={!connected || busy} onClick={() => void device.send('disconnect')}>断开连接</Button></div>
            </Card>
            <Card title="控制模式" caption="选择灯光由你控制，或跟随 Codex 状态">
              <div className="mode-list">{([['local', '本地灯光'], ['monitor', 'Codex 监控']] as const).map(([key, text]) =>
                <label className={`mode-row ${(key === 'local' ? local : monitorConnected) ? 'active' : ''}`} key={key}>
                  <span><AutoAwesomeOutlined fontSize="small" />{text}</span>
                  <Switch size="small" checked={Boolean(key === 'local' ? local : monitorConnected)}
                    disabled={!active || key === 'monitor' && !monitorReady} onChange={() => void device.send(key)}
                    slotProps={{ input: { 'aria-label': text } }} />
                </label>)}</div>
              <Typography variant="body2" color="textSecondary">{connected && !monitorReady ? '当前固件不支持监控灯光规则。' : '监控中锁定手动调灯，语音可立即接管。'}</Typography>
            </Card>
            <Card title="监控状态" caption="显示最近一次设备确认的状态">
              <div className="status-display"><span className="status-orb" style={{ color: display.color, backgroundColor: `${display.color}16` }}>●</span>
                <div><h3 role="status">{display.title}</h3><p>{display.note}</p></div></div>
              <div className="legend">{(['idle', 'working', 'waitingApproval'] as const).map(key =>
                <span key={key}><i style={{ backgroundColor: states[key].color }} />{states[key].title}</span>)}</div>
            </Card>
            <Card title="灯光空间" caption="编辑预览，不是设备实时灯光读回">
              <LightStrip color={monitoring ? display.color : color} off={!connected || !confirmed || monitoring && !monitorConnected || !monitoring && effect === '关闭灯光'} />
              <Typography variant="body2" color="textSecondary">{monitoring ? display.note : `${effect} · ${color} · 亮度 ${percent}%`}</Typography>
              <div className="card-action"><Button endIcon={<ArrowForwardRounded />} onClick={() => setPage('lights')}>调整灯光</Button></div>
            </Card>
            <Paper className="metrics">{[['连接方式', device.demo ? '模拟设备' : 'USB'], ['通信超时', `${diagnostic.replyTimeouts ?? 0} 次`],
              ['当前模式', !connected ? '等待连接' : !confirmed ? '待确认' : monitoring ? 'Codex 监控' : '本地灯光'],
              ['输出状态', monitorConnected ? '监控输出' : connected ? '本地控制' : '连接未建立']].map(([key, value]) =>
              <div key={key}><small>{key}</small><strong>{value}</strong></div>)}</Paper>
          </div>}
          {page === 'lights' && <div className="lighting-grid">
            <Card title="编辑灯光" caption="颜色、亮度与灯效一起应用" className="light-editor">
              <div className="field-title"><strong>灯光颜色</strong><label className={`color-picker ${!editable ? 'disabled' : ''}`}>
                <span style={{ backgroundColor: color }} /><span>{color}</span>
                <input aria-label="自定义灯光颜色" type="color" value={color} disabled={!editable} onChange={event => setColor(event.target.value.toUpperCase())} />
              </label></div>
              <div className="swatches">{colors.map(value => <button key={value} aria-label={`选择颜色 ${value}`} aria-pressed={color === value}
                style={{ backgroundColor: value }} disabled={!editable} onClick={() => setColor(value)} />)}</div>
              <div className="field-title"><strong>灯光亮度</strong><span className="percentage">{percent}%</span></div>
              <Slider aria-label="灯光亮度" min={0} max={255} step={1} value={brightness} disabled={!editable}
                onChange={(_, value) => setBrightness(value as number)} />
              <div className="field-title"><strong>灯效</strong></div>
              <ToggleButtonGroup exclusive value={effect} disabled={!editable} className="effect-grid" aria-label="灯光效果"
                onChange={(_, value: keyof typeof effects | null) => { if (value) setEffect(value); }}>
                {Object.keys(effects).map(value => <ToggleButton key={value} value={value}>{value}</ToggleButton>)}
              </ToggleButtonGroup>
              <Typography variant="body2" color="textSecondary" className="editor-note">彩虹使用独立色谱；关闭灯光保留编辑参数。</Typography>
            </Card>
            <Card title="灯光预览" caption="仅预览编辑值，不模拟动态灯效">
              <LightStrip color={color} off={effect === '关闭灯光'} />
              <Typography variant="body2" color="textSecondary">{effect} · {color} · 亮度 {percent}%</Typography>
            </Card>
            <Card title="监控灯光规则">
              <ul className="rules">{(['idle', 'working', 'waitingApproval'] as const).map(key => <li key={key}>
                <i style={{ backgroundColor: states[key].color }} /><span>{states[key].title}</span><strong>{states[key].note}</strong></li>)}</ul>
              <Typography variant="body2" color="textSecondary">来源异常显示绿色；连接断开则关灯。</Typography>
            </Card>
            <Paper className="apply-row"><Typography variant="body2" color="textSecondary">
              {!connected ? '请先连接设备。' : monitoring ? '监控模式已锁定手动灯光，请先切回本地。' : !editable ? '等待设备就绪或确认灯光能力。' : '点击应用后发送，收到设备回执才确认成功。'}</Typography>
              <Button variant="contained" disabled={!editable} onClick={applyLight}>应用灯光设置</Button>
            </Paper>
          </div>}
          {page === 'pairing' && <div className="detail-stack"><Card title="局域网无线配对" caption="尚未接入，不影响现有 USB 控制">
            <p>规划采用设备屏幕显示的六位随机数字码，5 分钟有效，最多 5 次错误。</p>
            <Typography variant="body2" color="textSecondary">仅未配对设备在启动时开放；USB 优先，语音始终优先。此页尚不能配对或重置设备。</Typography>
          </Card></div>}
          {page === 'diagnostics' && <div className="detail-stack">
            <Card title="通信与设备健康" caption="本次连接内的汇总，不保存原始会话内容">
              <dl className="diagnostic-grid">{[['USB 超时', diagnostic.replyTimeouts ?? 0], ['解码错误', diagnostic.decodeIssues ?? 0],
                ['最长往返', `${Math.round(diagnostic.maxRoundTripMs ?? 0)} ms`], ['麦克风', health.microphoneOk ? '已观测正常' : '未观测'],
                ['音频队列异常', health.audioQueueProblem ? '有记录' : '未观测'], ['看门狗 / 崩溃', health.watchdogOrPanic ? '有记录' : '未观测']].map(([name, value]) =>
                <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
              <Typography variant="body2" color="textSecondary">设备能力：{snapshot.operations?.join(' / ') || '等待握手'}</Typography>
            </Card>
            <Card title="操作记录" caption="保留最近 200 条结果"><pre className="operation-log">{device.logs.join('\n') || '暂无操作记录'}</pre></Card>
          </div>}
          {page === 'settings' && <div className="detail-stack"><Card title="Codex 状态来源" caption="断开连接后可修改；监控沿用现有有效期与宿主校验">
            {([['root', '状态目录', true], ['bindings', '宿主绑定文件', false]] as const).map(([key, label, directory]) =>
              <div className="setting-row" key={key}><TextField label={label} value={settings[key]} disabled={!canConfigure} size="small" fullWidth
                onChange={event => device.settingsChanged({ [key]: event.target.value })} />
                <Button variant="outlined" disabled={!canConfigure} onClick={() => void choose(directory)}>浏览</Button></div>)}
            <Typography variant="body2" color="textSecondary">监控期间延续已确认的运行与等待状态，收到结束事件后变绿；持续核对宿主进程。传输有效期 30 秒，保留既有余量；来源异常显示绿色，断联关灯。</Typography>
          </Card></div>}
        </main>
        <footer aria-live="polite">{device.notice}</footer>
      </div>
    </div>
  </ThemeProvider>;
}

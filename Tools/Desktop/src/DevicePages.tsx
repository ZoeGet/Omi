import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { Button, Field, Input } from '@fluentui/react-components';
import { FolderOpen20Regular } from '@fluentui/react-icons';
import { Card, SettingRow, type Device } from './Surface';

export function Pairing({ device, navigate }: { device: Device; navigate: (page: string) => void }) {
  const [address, setAddress] = useState('');
  const [code, setCode] = useState('');
  const [saved, setSaved] = useState<{ address: string; confirmed: boolean }[]>([]);
  const { ready, busy, connected, request } = device;
  const canConfigure = ready && !connected && !busy;
  useEffect(() => {
    if (!ready || busy) return;
    let cancelled = false;
    request('paired-devices').then(reply => { if (!cancelled && reply.ok) setSaved(reply.result as typeof saved); }).catch(() => {});
    return () => { cancelled = true; };
  }, [ready, busy, request]);
  return <div className="detail-stack pairing-grid"><Card title="添加设备" caption="设备与电脑连接同一 Wi-Fi 后，输入屏幕上的地址和配对码">
    <div className="form-stack"><Field label="设备地址"><Input placeholder="例如 192.168.1.20" value={address} disabled={busy || connected} onChange={(_, data) => setAddress(data.value)} /></Field>
      <Field label="六位配对码"><Input type="password" value={code} disabled={busy || connected} autoComplete="off" input={{ inputMode: 'numeric', maxLength: 6 }} onChange={(_, data) => setCode(data.value.replace(/\D/g, '').slice(0, 6))} /></Field>
      <div className="button-row"><Button appearance="primary" disabled={!ready || device.demo || busy || connected || !address.trim() || code.length !== 6}
        onClick={() => { void device.send('pair', { address: address.trim(), code }); setCode(''); }}>配对</Button></div></div>
    <p className="module-note">配对码 5 分钟有效，最多 5 次错误。仅未配对设备在启动时开放；过期后请重启设备。</p>
  </Card><Card title="已保存设备" caption="验证连接会核对设备身份，不改变灯光模式">
    {saved.length ? saved.map(item => <div className="saved-device" key={item.address}><div><strong>{item.address}</strong><p className="muted">{item.confirmed ? '已配对' : '等待最后确认，可验证连接恢复'}</p></div>
      <div className="button-row"><Button disabled={!canConfigure} onClick={() => void device.send('verify-wireless', { address: item.address })}>验证连接</Button>
        <Button appearance="primary" disabled={!canConfigure || !item.confirmed} onClick={() => { void device.send('connect-wireless', { ...device.settings, port: item.address }); navigate('overview'); }}>无线连接</Button></div></div>) : <div className="empty-state"><h3>尚无已保存设备</h3><p>完成配对后，设备会显示在这里。</p></div>}
    <p className="module-note">连接后可使用灯光与 Codex 监控。USB 监控优先，语音可立即接管；无线健康页仅显示通信结果。</p>
  </Card></div>;
}

export function Diagnostics({ device }: { device: Device }) {
  const diagnostic = device.snapshot.diagnostics ?? {};
  const health = device.snapshot.health ?? {};
  return <div className="detail-stack"><Card title="通信与设备健康" caption="本次连接内的汇总，不保存原始会话内容">
    <dl className="diagnostic-grid">{[['通信超时', diagnostic.replyTimeouts ?? 0], ['解码错误', diagnostic.decodeIssues ?? 0],
      ['最长往返', `${Math.round(diagnostic.maxRoundTripMs ?? 0)} ms`], ['麦克风', health.microphoneOk ? '已观测正常' : '未观测'],
      ['音频队列异常', health.audioQueueProblem ? '有记录' : '未观测'], ['看门狗 / 崩溃', health.watchdogOrPanic ? '有记录' : '未观测']].map(([name, value]) => <div key={String(name)}><dt>{name}</dt><dd>{String(value)}</dd></div>)}</dl>
    <p className="module-note">设备能力：{device.snapshot.operations?.join(' / ') || '等待握手'}</p>
  </Card><Card title="操作记录" caption="保留最近 200 条结果"><pre className="operation-log">{device.logs.join('\n') || '暂无操作记录'}</pre></Card></div>;
}

export function Settings({ device }: { device: Device }) {
  const editable = device.ready && !device.connected && !device.busy;
  async function choose(directory: boolean) {
    try {
      const path = await open(directory ? { directory: true, multiple: false } : { multiple: false, filters: [{ name: 'JSON', extensions: ['json'] }] });
      if (typeof path === 'string') device.settingsChanged(directory ? { root: path } : { bindings: path });
    } catch (error) { device.report(`无法选择路径：${error}`); }
  }
  return <div className="detail-stack"><Card title="Codex 状态来源" caption="断开连接后可修改；监控沿用现有有效期与宿主校验">
    {([['root', '状态目录', true], ['bindings', '宿主绑定文件', false]] as const).map(([key, label, directory]) => <SettingRow key={key} title={label}>
      <Input aria-label={label} value={device.settings[key]} disabled={!editable} onChange={(_, data) => device.settingsChanged({ [key]: data.value })} />
      <Button icon={<FolderOpen20Regular />} disabled={!editable} onClick={() => void choose(directory)}>浏览</Button></SettingRow>)}
    <p className="module-note">监控期间延续已确认的运行与等待状态，收到结束事件后显示完成灯效；持续核对宿主进程。传输有效期 30 秒，保留既有余量；来源异常使用设备监控配置，断联关灯。</p>
  </Card><Card title="外观" caption="自动跟随 Windows 系统外观"><SettingRow title="主题" description="浅色系统使用白色，深色系统使用黑色"><span className="muted">跟随系统</span></SettingRow></Card></div>;
}

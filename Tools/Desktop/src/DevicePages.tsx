import { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { Button, Field, Input } from '@fluentui/react-components';
import { FolderOpen20Regular } from '@fluentui/react-icons';
import { Card, SettingRow, type Device } from './Surface';
import type { ThemePreference } from './theme';
import { ThemePicker } from './ThemePicker';
import { MonitorSetup } from './MonitorSetup';
import { WindowSettings } from './WindowSettings';
import { pairingStatusText } from './backend';
import { ConnectionCheck } from './ConnectionCheck';

export function Pairing({ device, navigate }: { device: Device; navigate: (page: string) => void }) {
  const [address, setAddress] = useState('');
  const [code, setCode] = useState('');
  const [rePair, setRePair] = useState(false);
  const [editing, setEditing] = useState('');
  const [newAddress, setNewAddress] = useState('');
  const [inspectionTarget, setInspectionTarget] = useState('');
  const [saved, setSaved] = useState<{ address: string; confirmed: boolean; pendingRepair?: boolean }[]>([]);
  const { ready, busy, connected, request } = device;
  const canConfigure = ready && !connected && !busy;
  let target = '';
  try {
    const url = new URL(address.includes('://') ? address : `wss://${address}`);
    target = `wss://${url.hostname}:${url.port || '8443'}/pair`;
  } catch {}
  const inspection = inspectionTarget === target && device.pairingInspection?.address === target ? device.pairingInspection : undefined;
  const needsRepair = inspection && ['repair-required', 'identity-changed'].includes(inspection.state);
  const canPair = rePair || inspection?.state === 'new';
  function inspect() {
    if (canConfigure && address.trim()) { setInspectionTarget(target); void device.send('inspect-wireless', { address: address.trim() }); }
  }
  useEffect(() => {
    if (!ready || busy) return;
    let cancelled = false;
    request('paired-devices').then(reply => { if (!cancelled && reply.ok) setSaved(reply.result as typeof saved); }).catch(() => {});
    return () => { cancelled = true; };
  }, [ready, busy, request]);
  return <div className="detail-stack">
    {connected && <div className="pairing-connection-note" role="status"><span>{device.transport === 'wifi'
      ? '当前已通过 Wi-Fi 连接。管理配对或更换设备前，请先断开连接。'
      : '当前通过 USB 连接。请先断开 USB 连接，再进行无线连接或配对。'}</span>
      <Button disabled={busy} onClick={() => void device.send('disconnect')}>断开当前连接</Button></div>}
    <div className="pairing-grid"><Card title="已保存设备" caption="直接连接已配对设备，无需再次输入配对码">
      {saved.length ? saved.map(item => {
        let displayAddress = item.address;
        try { displayAddress = new URL(item.address).hostname; } catch {}
        const needsVerification = !item.confirmed || item.pendingRepair;
        return <div className="saved-device" key={item.address}><strong>{displayAddress}</strong>
          <p className="muted">{needsVerification ? '配对待确认，请验证连接；原记录保留' : '已配对'}</p>
          <div className="button-row">{needsVerification
            ? <Button appearance="primary" disabled={!canConfigure || device.demo} onClick={() => void device.send('verify-wireless', { address: item.address })}>验证连接</Button>
            : <Button appearance="primary" disabled={!canConfigure} onClick={() => { void device.send('connect-wireless', { ...device.settings, port: item.address }); navigate('overview'); }}>无线连接</Button>}
            <Button disabled={!canConfigure || device.demo} onClick={() => void device.send('find-wireless', { address: item.address })}>重新查找设备</Button></div>
          <details className="pairing-details"><summary>更多操作</summary>
            <p className="muted">{item.address}</p>
            <p className="muted">查找失败时，可从路由器查看设备 IP，手动更新地址。验证失败会保留原配对。</p>
            {editing === item.address ? <div className="form-stack"><Field label="设备新地址"><Input value={newAddress} placeholder="例如 192.168.2.20" disabled={!canConfigure} onChange={(_, data) => setNewAddress(data.value)} /></Field>
              <div className="button-row"><Button disabled={!canConfigure || device.demo || !newAddress.trim()} onClick={() => { void device.send('relocate-wireless', { previous: editing, address: newAddress.trim() }); setEditing(''); }}>验证并保存地址</Button>
                <Button disabled={busy} onClick={() => setEditing('')}>取消</Button></div></div>
              : <Button disabled={!canConfigure || device.demo} onClick={() => { setEditing(item.address); setNewAddress(''); }}>修改地址</Button>}
          </details>
        </div>;
      }) : <div className="empty-state"><h3>尚无已保存设备</h3><p>完成配对后，设备会显示在这里。</p></div>}
      <p className="module-note">换 Wi-Fi 或连接失败时，重新查找设备，最多约一分钟。</p>
    </Card><Card title={rePair ? '重新配对' : '配对新设备'} caption="唤醒设备后说“开启配对模式”，输入屏幕上的 IP 和六位码。">
      {rePair && <p className="pairing-warning" role="alert">重新配对成功后，旧电脑的配对凭据将失效。仅在换电脑或凭据丢失时使用。</p>}
      <div className="form-stack"><Field label="设备地址"><Input placeholder="例如 192.168.1.20" value={address} disabled={!canConfigure}
        onBlur={() => { if (!rePair && !inspection) inspect(); }} onChange={(_, data) => { setAddress(data.value); setCode(''); setInspectionTarget(''); }} /></Field>
        <Button disabled={!canConfigure || device.demo || !address.trim()} onClick={inspect}>检测配对状态</Button>
        {inspection && <div aria-live="polite"><p>{pairingStatusText[inspection.state] ?? pairingStatusText.unknown}</p>
          {needsRepair && !rePair && <Button disabled={!canConfigure} onClick={() => { setRePair(true); setCode(''); }}>重新配对该设备</Button>}
          {inspection.state === 'pending' && <Button disabled={!canConfigure} onClick={() => void device.send('verify-wireless', { address: target })}>恢复配对确认</Button>}
          {inspection.state === 'paired-here' && <Button disabled={!canConfigure} onClick={() => { void device.send('connect-wireless', { ...device.settings, port: target }); navigate('overview'); }}>无线连接此设备</Button>}
        </div>}
        <Field label="六位配对码"><Input type="password" value={code} disabled={!canConfigure} autoComplete="off" input={{ inputMode: 'numeric', maxLength: 6 }} onChange={(_, data) => setCode(data.value.replace(/\D/g, '').slice(0, 6))} /></Field>
        <Button appearance="primary" disabled={!canConfigure || device.demo || !canPair || !address.trim() || code.length !== 6}
          onClick={() => { void device.send(rePair ? 're-pair' : 'pair', { address: address.trim(), code }); setCode(''); }}>{rePair ? '确认重新配对' : '配对'}</Button></div>
      <p className="module-note">配对码 5 分钟有效，最多尝试 5 次。</p>
      <details className="pairing-details"><summary>配对帮助</summary>
        <p className="muted">电脑与设备需处于可互通的局域网。说“老鼠狒狒”，听到提示音后再说“开启配对模式”，无需 USB。</p>
        <p className="muted">码过期或锁定后可再次语音开启。普通重启可退出配对模式并保留旧绑定；显示 PAIR UNREADY 时，请联网后重试。旧固件与语音模型需先升级。</p>
        <Button appearance="subtle" disabled={!canConfigure || device.demo} onClick={() => { setRePair(!rePair); setCode(''); }}>{rePair ? '返回首次配对' : '重新配对已有设备'}</Button>
      </details>
    </Card></div>
  </div>;
}

export function Diagnostics({ device }: { device: Device }) {
  const diagnostic = device.snapshot.diagnostics ?? {};
  const health = device.snapshot.health ?? {};
  return <div className="detail-stack"><ConnectionCheck device={device} /><Card title="通信与设备健康" caption="本次连接内的汇总，不保存原始会话内容">
    <dl className="diagnostic-grid">{[['通信超时', diagnostic.replyTimeouts ?? 0], ['解码错误', diagnostic.decodeIssues ?? 0],
      ['最长往返', `${Math.round(diagnostic.maxRoundTripMs ?? 0)} ms`], ['麦克风', health.microphoneOk ? '已观测正常' : '未观测'],
      ['音频队列异常', health.audioQueueProblem ? '有记录' : '未观测'], ['看门狗 / 崩溃', health.watchdogOrPanic ? '有记录' : '未观测']].map(([name, value]) => <div key={String(name)}><dt>{name}</dt><dd>{String(value)}</dd></div>)}</dl>
    <p className="module-note">设备能力：{device.snapshot.operations?.join(' / ') || '等待握手'}</p>
  </Card><Card title="操作记录" caption="保留最近 200 条结果"><pre className="operation-log">{device.logs.join('\n') || '暂无操作记录'}</pre></Card></div>;
}

export function Settings({ device, themePreference, changeTheme }: {
  device: Device; themePreference: ThemePreference; changeTheme: (preference: ThemePreference) => void;
}) {
  const editable = device.ready && !device.connected && !device.busy;
  async function choose(directory: boolean) {
    try {
      const path = await open(directory ? { directory: true, multiple: false } : { multiple: false, filters: [{ name: 'JSON', extensions: ['json'] }] });
      if (typeof path === 'string') device.settingsChanged(directory ? { root: path } : { bindings: path });
    } catch (error) { device.report(`无法选择路径：${error}`); }
  }
  return <div className="detail-stack"><Card title="外观" caption="选择应用主题，自动保存到本机">
    <ThemePicker value={themePreference} change={changeTheme} />
    <p className="module-note">浅色使用白色，深色使用黑色；跟随系统会随 Windows 外观自动变化。</p>
  </Card><WindowSettings report={device.report} /><MonitorSetup device={device} /><Card title="Codex 状态来源" caption="断开连接后可修改；监控沿用现有有效期与宿主校验">
    {([['root', '状态目录', true], ['bindings', '宿主绑定文件', false]] as const).map(([key, label, directory]) => <SettingRow key={key} title={label}>
      <Input aria-label={label} value={device.settings[key]} disabled={!editable} onChange={(_, data) => device.settingsChanged({ [key]: data.value })} />
      <Button icon={<FolderOpen20Regular />} disabled={!editable} onClick={() => void choose(directory)}>浏览</Button></SettingRow>)}
    <p className="module-note">监控期间延续已确认的运行与等待状态，收到结束事件后显示完成灯效；持续核对宿主进程。传输有效期 30 秒，保留既有余量；来源异常使用设备监控配置，断联关灯。</p>
  </Card></div>;
}

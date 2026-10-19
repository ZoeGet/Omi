import { useEffect, useState } from 'react';
import { Button } from '@fluentui/react-components';
import { Card, type Device } from './Surface';

type SetupCheck = { state: string; installed?: boolean; hookReceived?: boolean; message: string };
const sourceHints: Record<string, string> = {
  'observation-expired': '任务事件已过期，请让 Codex 执行一次新操作。',
  'delivery-budget-exhausted': '任务事件已超出传输有效期，请触发新事件。',
  'event-binding-unconfirmed': '已收到事件，但尚未确认 Codex 宿主关联。',
  'process-binding-missing': '缺少宿主绑定，请检查监控配置并触发工具事件。',
  'invalid-process-bindings': '宿主绑定记录无效，请在设置中修复监控。',
  'bound-process-unconfirmed': '无法确认绑定的 Codex 进程仍在运行。',
  'source-lock-unavailable': '暂时无法读取任务状态，请稍后重新自检。',
  'source-unavailable': '任务状态文件不可读，请检查监控路径和采集组件。',
  'source-or-capacity-invalid': '任务来源格式或会话数量超出设备支持范围。',
};

export function ConnectionCheck({ device, navigate }: { device: Device; navigate?: (page: string) => void }) {
  const [setup, setSetup] = useState<SetupCheck>();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  async function refresh() {
    setChecking(true); setError(''); setSetup(undefined);
    try {
      const reply = await device.request('monitor-setup-status');
      const value = reply.result as SetupCheck | undefined;
      if (!reply.ok || !value || typeof value.state !== 'string') throw new Error('无法读取监控配置，请重试。');
      setSetup(value);
    } catch { setError('监控检测未完成，请检查后台状态后重试。'); }
    finally { setChecking(false); }
  }
  useEffect(() => { if (device.ready && !device.demo) void refresh(); }, [device.ready, device.demo]);
  const installed = setup?.installed ?? ['ready', 'awaiting-event', 'awaiting-binding'].includes(setup?.state ?? '');
  const received = setup?.hookReceived ?? ['ready', 'awaiting-binding'].includes(setup?.state ?? '');
  const source = device.snapshot.monitorSource?.state;
  const sourceHint = device.snapshot.monitorSource?.reasons.map(reason => sourceHints[reason]).find(Boolean);
  const data = !device.connected ? '等待连接设备' : !device.snapshot.monitorRequested ? '监控未开启'
    : source === 'valid' ? '任务数据有效' : '任务来源不可用';
  const rows = [
    ['设备连接', device.connected ? `${device.transport === 'wifi' ? 'Wi-Fi' : 'USB'} 已连接` : '尚未连接', device.connected ? '握手已完成' : '先在首页连接设备'],
    ['监控组件', checking ? '检测中' : !setup ? '尚未确认' : installed ? '已安装' : '需要配置或修复', (setup?.message ?? error) || '等待检测'],
    ['Hook 事件', !setup ? '尚未确认' : received ? '已收到本次安装的事件' : '尚未收到事件', received ? '收到事件不等于当前任务数据有效' : '请在 Codex 信任 Hook，并执行一次普通操作后重新检测'],
    ['任务数据', data, !device.snapshot.monitorRequested ? '连接成功后开启 Codex 监控'
      : source === 'valid' ? device.snapshot.taskScreenSupported ? '设备支持任务气泡；空闲也属于有效数据' : '当前固件未声明任务屏能力，灯光监控仍可使用'
      : !installed ? '先安装或修复监控组件' : !received ? '等待 Codex 的新事件'
      : setup?.state === 'awaiting-binding' ? '已收到事件，但宿主关联尚未完成；请让 Codex 执行一个工具操作'
      : sourceHint ?? '检查监控路径、宿主关联或事件有效期；这与无线绑定是否成功是不同的步骤'],
  ];
  return <Card title="连接与监控自检" caption={device.demo ? '演示模式不检测本机真实 Hook' : '分别确认连接、组件、事件与当前任务数据'}>
    <ol className="connection-check">{rows.map(([title, state, hint]) => <li key={title}><div><strong>{title}</strong><span>{state}</span></div><p>{hint}</p></li>)}</ol>
    <div className="button-row"><Button disabled={!device.ready || device.demo || checking || device.busy} onClick={() => void refresh()}>重新自检</Button>
      {navigate && <Button disabled={device.busy} onClick={() => navigate('settings')}>配置与修复监控</Button>}</div>
  </Card>;
}

import { useEffect, useRef, useState } from 'react';
import { Button, Checkbox, Field, Input } from '@fluentui/react-components';
import { open } from '@tauri-apps/plugin-dialog';
import { Card, type Device } from './Surface';

type Setup = { state: string; message: string; packaged: boolean; candidates: string[]; images?: string[]; home: string; root: string };

export function MonitorSetup({ device, completed, firstRun = false }: { device: Device; completed?: () => void; firstRun?: boolean }) {
  const [status, setStatus] = useState<Setup>();
  const [images, setImages] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [remove, setRemove] = useState(false);
  const initialCheck = useRef(true);
  const [showIntro, setShowIntro] = useState(!firstRun);
  async function refresh() {
    setPending(true); setError('');
    try {
      const reply = await device.request('monitor-setup-status');
      if (!reply.ok) throw new Error(reply.error);
      const value = reply.result as Setup;
      if (!value || !Array.isArray(value.candidates)) throw new Error('后台未返回有效的监控检测结果。');
      const alreadyInstalled = initialCheck.current && Boolean(value.images?.length);
      initialCheck.current = false;
      if (firstRun && alreadyInstalled) { completed?.(); return; }
      setShowIntro(true);
      setStatus(value); setImages(current => current.length ? current : value.images ?? value.candidates);
      if (value.state === 'ready') { device.report(value.message); completed?.(); }
    } catch (error) { setError(String(error)); }
    finally { setPending(false); }
  }
  useEffect(() => { if (device.ready) void refresh(); }, [device.ready]);
  const editable = device.ready && !device.connected && !device.busy && !device.demo && !pending;
  async function apply(action: 'monitor-setup-install' | 'monitor-setup-uninstall') {
    setPending(true); setError('');
    try {
      const reply = await device.request(action, action === 'monitor-setup-install' ? { images } : null);
      if (!reply.ok) throw new Error(reply.error);
      const result = reply.result as { message: string; backup?: string; root?: string; bindings?: string };
      if (result.root && result.bindings) device.settingsChanged({ root: result.root, bindings: result.bindings });
      device.report(result.message + (result.backup ? ` 备份位置：${result.backup}` : ''));
      setRemove(false);
      await refresh();
    } catch (error) { setError(String(error)); }
    finally { setPending(false); }
  }
  async function browse() {
    try {
      const selected = await open({ multiple: true, filters: [{ name: 'Codex 程序', extensions: ['exe'] }] });
      if (selected) setImages(typeof selected === 'string' ? [selected] : selected);
    } catch (error) { setError(String(error)); }
  }
  if (firstRun && !showIntro && !error) return null;
  return <div className={firstRun ? 'setup-welcome' : undefined}><Card title="配置 Codex 监控" caption="首次使用完成这三步，即可将 Codex 状态同步到设备">
    <p aria-live="polite" className="setup-status">{pending ? '正在检查或配置监控…' : status?.message ?? '等待设备后台就绪'}</p>
    {error && <p role="alert" className="conflict-notice">{error}</p>}
    <ol className="setup-steps"><li><h3>选择 Codex 程序并安装采集组件</h3><p>启动 Codex 后点击重新检测，可找到运行中的程序；也可以手动选择 Codex.exe。支持同时选择桌面版和 CLI。</p>
      <Field label="允许关联的 Codex 程序"><Input value={images.join('；')} readOnly placeholder="尚未检测到，请启动 Codex 或选择程序" /></Field>
      <div className="button-row"><Button disabled={!editable} onClick={() => void browse()}>选择 Codex 程序</Button>
        <Button appearance="primary" disabled={!editable || !status?.packaged || !images.length} onClick={() => void apply('monitor-setup-install')}>{status?.images ? '修复 / 更新监控' : '安装监控组件'}</Button></div>
      <p>点击安装会备份并合并用户级 Hook，替换可明确识别的旧 Omi 采集器，保留其他工具的配置。组件存放在固定目录，移动本软件不影响采集。</p></li>
      <li><h3>在 Codex 中审查并信任 Hook</h3><p>在 Codex 的 Hook 审查界面信任 Omi 处理器；CLI 可输入 <code>/hooks</code>。若未出现新定义，请重新加载配置或重启 Codex。修复或升级后如提示定义变化，请重新审查。</p></li>
      <li><h3>发送一条消息，验证接入</h3><p>让 Codex 执行一次普通操作，然后点击重新检测。只有收到真实事件且宿主关联正常，才显示就绪。</p>
        <Button disabled={!device.ready || pending} onClick={() => void refresh()}>重新检测监控</Button></li></ol>
    {device.connected && <p className="module-note">请先断开设备，再安装、修复或卸载监控。</p>}
    {status?.home && <p className="module-note">Codex 配置目录：{status.home}</p>}
    {status?.images && <div className="setup-remove"><Checkbox checked={remove} disabled={!editable} onChange={(_, data) => setRemove(Boolean(data.checked))} label="我确认移除 Omi 的监控 Hook，停止采集；保留其他 Hook、备份与历史状态" />
      <Button disabled={!editable || !remove} onClick={() => void apply('monitor-setup-uninstall')}>卸载监控接入</Button></div>}
    <p className="module-note">仅记录状态和关联元数据，不保存对话正文、工具参数或回复。尚未收到事件时无法区分未信任与尚未触发，请按上方步骤检查。</p>
  </Card>{firstRun && <Button appearance="subtle" onClick={completed}>稍后配置，以后从设置进入</Button>}</div>;
}

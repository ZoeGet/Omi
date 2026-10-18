import { useEffect, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { Select } from '@fluentui/react-components';
import { Card, SettingRow } from './Surface';

type Preferences = { closeBehavior: 'tray' | 'exit'; trayAvailable: boolean };

export function WindowSettings({ report }: { report: (message: string) => void }) {
  const native = isTauri();
  const [preferences, setPreferences] = useState<Preferences>();
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!native) return;
    let disposed = false;
    invoke<Preferences>('window_control', { action: 'settings', behavior: null })
      .then(value => { if (!disposed) setPreferences(value); })
      .catch(error => { if (!disposed) report(`无法读取关闭行为：${error}`); });
    return () => { disposed = true; };
  }, [native, report]);
  async function saveBehavior(behavior: string) {
    setPending(true);
    try {
      const value = await invoke<Preferences>('window_control', { action: 'close-behavior', behavior });
      setPreferences(value);
      report('窗口关闭行为已保存。');
    } catch (error) { report(`应用操作未完成：${error}`); }
    finally { setPending(false); }
  }
  return <Card title="窗口与托盘" caption="关闭窗口时默认隐藏到托盘，监控在后台继续运行">
    <SettingRow title="关闭窗口时" description="选择会自动保存，重启软件后保留">
      <Select aria-label="窗口关闭行为" value={preferences?.closeBehavior ?? 'tray'} disabled={!native || !preferences || pending}
        onChange={(_, data) => void saveBehavior(data.value)}>
        <option value="tray">隐藏到系统托盘</option><option value="exit">退出软件</option>
      </Select>
    </SettingRow>
    <p className="module-note">单击托盘图标或右键选择“显示主窗口”可恢复窗口。退出软件前会释放设备连接；退出不会卸载已配置的 Codex 采集器。</p>
    {preferences && !preferences.trayAvailable && <p role="alert" className="module-note">系统托盘不可用，关闭窗口时将退出软件，主窗口不会被隐藏。</p>}
    {!native && <p className="module-note">窗口和托盘操作仅在桌面程序内可用。</p>}
  </Card>;
}

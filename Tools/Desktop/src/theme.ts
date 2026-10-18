import { useEffect, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { webDarkTheme, webLightTheme, type Theme } from '@fluentui/react-components';

export const lightTheme: Theme = {
  ...webLightTheme,
  colorNeutralBackground1: '#ffffff',
  colorNeutralBackground2: '#fafafa',
  colorNeutralBackground3: '#f3f3f3',
  colorBrandBackground: '#0067b8',
  colorBrandBackgroundHover: '#005a9e',
};
export const darkTheme: Theme = {
  ...webDarkTheme,
  colorNeutralBackground1: '#000000',
  colorNeutralBackground2: '#141414',
  colorNeutralBackground3: '#1c1c1c',
  colorBrandBackground: '#90c8ff',
  colorBrandBackgroundHover: '#b4daff',
  colorBrandBackgroundPressed: '#6bb5fa',
  colorBrandBackgroundSelected: '#90c8ff',
  colorNeutralForegroundOnBrand: '#082541',
};

export type ThemePreference = 'light' | 'dark' | 'system';
const preferenceKey = 'omi.theme';

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(preferenceKey);
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved;
  } catch {
    //  存储不可用时跟随系统 / Follow the system when storage is unavailable
  }
  return 'system';
}

export function useAppTheme() {
  const [preference, updatePreference] = useState<ThemePreference>(readPreference);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);
  useEffect(() => {
    if (isTauri()) getCurrentWindow().setTheme(preference === 'system' ? null : preference)
      .catch(error => console.error('窗口主题切换失败 / Window theme change failed', error));
  }, [preference]);
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystemDark(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  function setPreference(value: ThemePreference) {
    updatePreference(value);
    try { localStorage.setItem(preferenceKey, value); }
    catch {
      //  存储不可用时仍允许本次切换 / Allow switching for this session when storage is unavailable
    }
  }
  const dark = preference === 'system' ? systemDark : preference === 'dark';
  return { dark, theme: dark ? darkTheme : lightTheme, preference, setPreference };
}

import { useEffect, useState } from 'react';
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

export function useSystemTheme() {
  const [dark, setDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setDark(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return { dark, theme: dark ? darkTheme : lightTheme };
}

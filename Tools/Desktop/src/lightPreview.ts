const cycles: Record<string, number> = { rainbow: 7200, breathe: 3000, sweep: 3600, centerExpand: 4200 };
export const animatedLight = (effect: string) => effect in cycles;

//  按固件的周期和光晕曲线预览，不表示设备实时输出 / Preview firmware cycles and glow curves without claiming live device output
export function previewPixel(effect: string, index: number, elapsed: number) {
  const phase = (elapsed % (cycles[effect] ?? 1)) / (cycles[effect] ?? 1);
  const pingPong = phase < 0.5 ? phase * 2 : (1 - phase) * 2;
  const falloff = (distance: number, radius: number) => 0.5 * (1 + Math.cos(Math.PI * Math.min(1, distance / radius)));
  let glow = 1;
  if (effect === 'breathe') glow = 0.04 + (0.5 - 0.5 * Math.cos(2 * Math.PI * phase)) * 0.96;
  if (effect === 'sweep') glow = 0.10 + 0.90 * falloff(Math.abs(index - 12 * pingPong), 7.2);
  if (effect === 'centerExpand') {
    const distance = Math.abs(Math.abs(index - 6) - 6 * pingPong);
    glow = 0.22 + 0.78 * Math.max(falloff(distance, 1.25), falloff(distance, 3.8) * 0.34);
  }
  return {
    hue: ((Math.floor(phase * 256) + Math.floor(index * 256 / 13)) % 256) / 256 * 360,
    level: effect === 'off' ? 0 : (7 + glow * 248) / 255,
  };
}

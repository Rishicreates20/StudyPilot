/** Minimal OKLCH -> sRGB conversion and WCAG contrast, used only by tests. */

export type Oklch = { l: number; c: number; h: number };

export function parseOklch(value: string): Oklch {
  const match = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)$/.exec(value.trim());
  if (!match) throw new Error(`Unsupported colour (opaque oklch() only): ${value}`);
  return { l: Number(match[1]), c: Number(match[2]), h: Number(match[3]) };
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

/** WCAG relative luminance of an OKLCH colour (out-of-gamut channels are clamped). */
export function relativeLuminance({ l, c, h }: Oklch): number {
  const hue = (h * Math.PI) / 180;
  const a = c * Math.cos(hue);
  const b = c * Math.sin(hue);

  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;

  const r = clamp01(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_);
  const g = clamp01(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_);
  const bl = clamp01(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_);

  return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
}

export function contrastRatio(first: Oklch, second: Oklch): number {
  const [lighter, darker] = [relativeLuminance(first), relativeLuminance(second)].sort(
    (x, y) => y - x,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

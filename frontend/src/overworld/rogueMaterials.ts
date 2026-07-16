/**
 * Pure rogue palette remap — used by PlayerCharacter and unit tests.
 * Turns KayKit neon-green cloak pixels into a dark muted gray-brown hooded look
 * aligned with player-ref.webp (not pure black).
 */

export const ROGUE_FALLBACK_HEX = "#4a4844";

/** Remap a single sRGB pixel (0–255 channels). Returns [r,g,b]. */
export function recolorRoguePixel(
  r: number,
  g: number,
  b: number
): [number, number, number] {
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const sat = max === 0 ? 0 : (max - min) / max;

  const isSkin =
    r > 140 && g > 90 && b > 60 && r > g && g > b && sat < 0.55 && lum > 0.35;

  const isLeather =
    !isSkin &&
    ((r > g && r > b && g > b * 0.7 && lum < 0.55) ||
      (r > 80 && g > 40 && b < 70 && sat > 0.2));

  const isDarkDetail = lum < 0.14;

  let nr: number;
  let ng: number;
  let nb: number;

  if (isSkin) {
    nr = 88 + lum * 48;
    ng = 72 + lum * 38;
    nb = 58 + lum * 28;
  } else if (isLeather) {
    nr = 52 + lum * 70;
    ng = 42 + lum * 52;
    nb = 32 + lum * 38;
  } else if (isDarkDetail) {
    nr = 28 + lum * 40;
    ng = 26 + lum * 36;
    nb = 24 + lum * 32;
  } else {
    // Cloth / cloak / hood: muted charcoal-brown (player-ref silhouette)
    const clothLum = Math.pow(Math.max(lum, 0.08), 0.9) * 0.88;
    const base = 42 + clothLum * 110;
    nr = base * 1.04;
    ng = base * 0.99;
    nb = base * 0.9;
    // Fold detail from original green channel (KayKit atlas)
    const fold = (g / 255 - lum) * 48;
    nr += fold * 0.28;
    ng += fold * 0.32;
    nb += fold * 0.22;
  }

  return [
    Math.max(0, Math.min(255, nr)),
    Math.max(0, Math.min(255, ng)),
    Math.max(0, Math.min(255, nb)),
  ];
}

/** In-place remapping of an ImageData buffer (RGBA). */
export function recolorRogueImageData(imageData: {
  data: Uint8ClampedArray | number[];
  width: number;
  height: number;
}): void {
  const d = imageData.data;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 8) continue;
    const [nr, ng, nb] = recolorRoguePixel(d[i], d[i + 1], d[i + 2]);
    d[i] = nr;
    d[i + 1] = ng;
    d[i + 2] = nb;
  }
}

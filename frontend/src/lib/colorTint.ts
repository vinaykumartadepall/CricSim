// Resolves a hex color or `var(--token)` reference against the live theme.
export function resolveHex(color: string): { r: number; g: number; b: number } | null {
  const varMatch = color.match(/^var\((--[\w-]+)\)$/)
  const resolved = varMatch
    ? getComputedStyle(document.documentElement).getPropertyValue(varMatch[1]).trim()
    : color
  const hex = resolved.match(/^#([0-9a-f]{6})$/i)
  if (!hex) return null
  const n = parseInt(hex[1], 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}

// Blends `color` toward var(--bg) at `percent` opacity, producing a literal
// opaque color rather than a translucent color-mix()/rgba() one - the same
// visual result as a tint over the page background, but without leaving any
// alpha compositing for a renderer to get wrong (this tripped up html2canvas
// during share-screenshot capture even with an explicitly opaque background
// forced at capture time - removing the translucency here, at the source,
// sidesteps that regardless of the exact cause).
export function opaqueTint(color: string, percent: number): string {
  const fg = resolveHex(color) ?? { r: 255, g: 255, b: 255 }
  const bg = resolveHex('var(--bg)') ?? { r: 8, g: 8, b: 8 }
  const a = percent / 100
  const mix = (u: number, o: number) => Math.round(u * (1 - a) + o * a)
  return `rgb(${mix(bg.r, fg.r)}, ${mix(bg.g, fg.g)}, ${mix(bg.b, fg.b)})`
}

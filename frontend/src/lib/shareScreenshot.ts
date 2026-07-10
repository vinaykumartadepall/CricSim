import html2canvas from 'html2canvas-pro'

// html2canvas renders from a cloned copy of the document, and CSS
// animations/transitions don't reliably carry their current (settled) state
// into that clone - elements using this app's .fade-in entrance animation
// (opacity 0 -> 1) come out looking part-way through the fade instead of
// fully visible, even though the live page finished animating well before
// the user ever clicks Share. Freezing all animations/transitions to their
// end state for the moment of capture avoids relying on html2canvas to
// handle something it doesn't reliably support, rather than working around
// the symptom per-component.
function freezeAnimations(): () => void {
  const style = document.createElement('style')
  style.id = 'share-capture-freeze'
  style.textContent = '*, *::before, *::after { animation: none !important; transition: none !important; }'
  document.head.appendChild(style)
  return () => style.remove()
}

interface Rgb { r: number; g: number; b: number }
interface Rgba extends Rgb { a: number }

function parseRgba(value: string): Rgba | null {
  const m = value.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/)
  if (!m) return null
  return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 }
}

function blend(under: Rgb, over: Rgba): Rgb {
  const mix = (u: number, o: number) => Math.round(u * (1 - over.a) + o * over.a)
  return { r: mix(under.r, over.r), g: mix(under.g, over.g), b: mix(under.b, over.b) }
}

// The app's actual dark background is painted on the layout wrapper inside
// <body> (see App.tsx's `background: var(--bg)`), NOT on <html> itself - so
// reading getComputedStyle(document.documentElement) for the page backdrop
// is wrong (returns transparent). Read the real CSS variable directly.
function pageBackgroundColor(): Rgb {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
  const hex = raw.match(/^#([0-9a-f]{6})$/i)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
  }
  return parseRgba(raw) ?? { r: 8, g: 8, b: 8 }
}

// This app uses translucent backgrounds (rgba()/color-mix(), e.g. the result
// banner's tinted cards, table row highlights, badges) in well over a dozen
// places, all designed to show the real dark page background tinted through
// at low opacity. html2canvas doesn't reliably composite these against
// whatever's actually behind them - walk the whole captured subtree once and
// replace every translucent background with its real composited-opaque
// equivalent, resolved via the browser's own getComputedStyle (which
// correctly resolves color-mix() regardless of html2canvas's own handling).
function flattenTranslucentBackgrounds(root: HTMLElement): () => void {
  const pageBg = pageBackgroundColor()
  const restores: Array<() => void> = []

  function nearestOpaqueAncestorColor(el: HTMLElement): Rgb {
    let node: HTMLElement | null = el.parentElement
    while (node) {
      const c = parseRgba(getComputedStyle(node).backgroundColor)
      if (c && c.a >= 0.999) return c
      node = node.parentElement
    }
    return pageBg
  }

  root.querySelectorAll<HTMLElement>('*').forEach(el => {
    const own = parseRgba(getComputedStyle(el).backgroundColor)
    if (!own || own.a <= 0 || own.a >= 0.999) return
    const flat = blend(nearestOpaqueAncestorColor(el), own)
    const prevValue = el.style.getPropertyValue('background-color')
    const prevPriority = el.style.getPropertyPriority('background-color')
    el.style.setProperty('background-color', `rgb(${flat.r}, ${flat.g}, ${flat.b})`, 'important')
    restores.push(() => {
      if (prevValue) el.style.setProperty('background-color', prevValue, prevPriority)
      else el.style.removeProperty('background-color')
    })
  })

  return () => restores.forEach(fn => fn())
}

// Second, independent mitigation for the same symptom: elements combining
// border-radius with overflow:hidden/clip appear to trip up html2canvas's
// clipping path in a way that isn't just about the background color being
// translucent (a card given a fully OPAQUE background via the flatten step
// above has still been observed rendering near-white) - the clip mask
// rendering itself seems to bypass the corrected fill. Neutralizing the
// clip during capture sidesteps that path entirely; the only visible cost
// is square instead of rounded corners in the shared image.
function relaxClipping(root: HTMLElement): () => void {
  const restores: Array<() => void> = []
  root.querySelectorAll<HTMLElement>('*').forEach(el => {
    const cs = getComputedStyle(el)
    const hasRadius = cs.borderRadius !== '0px' && cs.borderRadius !== ''
    const clips = cs.overflow === 'hidden' || cs.overflow === 'clip' ||
                  cs.overflowX === 'hidden' || cs.overflowY === 'hidden'
    if (!hasRadius || !clips) return
    const prevRadius = el.style.getPropertyValue('border-radius')
    const prevOverflow = el.style.getPropertyValue('overflow')
    el.style.setProperty('border-radius', '0px', 'important')
    el.style.setProperty('overflow', 'visible', 'important')
    restores.push(() => {
      if (prevRadius) el.style.setProperty('border-radius', prevRadius)
      else el.style.removeProperty('border-radius')
      if (prevOverflow) el.style.setProperty('overflow', prevOverflow)
      else el.style.removeProperty('overflow')
    })
  })
  return () => restores.forEach(fn => fn())
}

// Many share targets (WhatsApp notably) drop the `text`/`url` fields passed
// to navigator.share() once a file is attached - that's the receiving app's
// choice, not something controllable from here. Stamping a small watermark
// onto the image itself is the only way to guarantee the link survives
// regardless of what the target app does with the other fields.
function stampWatermark(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const barHeight = Math.round(canvas.height * 0.05)
  // Fully opaque, not translucent - if the crop extends even slightly past
  // where real content was painted, that strip is genuinely transparent in
  // the canvas, and a translucent fill drawn over transparent pixels stays
  // partially transparent overall (most viewers render that as washed-out
  // gray/white against their own backdrop, not as a dark bar).
  ctx.fillStyle = '#000000'
  ctx.fillRect(0, canvas.height - barHeight, canvas.width, barHeight)
  ctx.fillStyle = '#FFB700'
  ctx.font = `${Math.round(barHeight * 0.5)}px 'DM Sans', -apple-system, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('cricsimulator.com', canvas.width / 2, canvas.height - barHeight / 2)
}

/**
 * Captures only what's currently visible on screen (not the full scrollable
 * page), excluding the fixed header, as a PNG File for attaching to the
 * native share sheet.
 *
 * Renders the full #page-content element once (its natural full height,
 * already excluding the header/its layout spacer above it - see App.tsx),
 * then slices out just the currently-visible band with the Canvas 2D API
 * directly, rather than relying on html2canvas's own x/y/width/height crop
 * options - this sidesteps any ambiguity about whether those coordinates
 * are element- or document-relative, since the slicing here is plain,
 * unambiguous drawImage(source-rect, dest-rect).
 *
 * Uses html2canvas-pro rather than the original html2canvas because this
 * app's UI relies on color-mix() (e.g. the results banner background), which
 * the unmaintained original doesn't understand and renders as transparent.
 *
 * Returns null on any failure - callers should fall back to a plain
 * text+url share rather than surfacing an error for a non-essential extra.
 */
export async function captureViewportImage(filename: string): Promise<File | null> {
  const target = document.getElementById('page-content') ?? document.body
  const scale = Math.min(window.devicePixelRatio || 1, 2)
  const visibleTopOffset = Math.max(0, -target.getBoundingClientRect().top)
  const viewportHeight = window.innerHeight

  const unfreeze = freezeAnimations()
  const unflatten = flattenTranslucentBackgrounds(target)
  const unclip = relaxClipping(target)
  try {
    const fullCanvas = await html2canvas(target, { scale, useCORS: true, backgroundColor: null })

    const sy = Math.round(visibleTopOffset * scale)
    const sh = Math.min(Math.round(viewportHeight * scale), fullCanvas.height - sy)
    const cropped = document.createElement('canvas')
    cropped.width = fullCanvas.width
    cropped.height = sh
    const ctx = cropped.getContext('2d')
    if (!ctx) return null
    // Fill with the real page background first - guarantees no transparent
    // gaps can reach the final PNG even if the crop extends slightly past
    // where html2canvas actually painted content (backgroundColor: null
    // above leaves anything it didn't paint genuinely transparent).
    const bg = pageBackgroundColor()
    ctx.fillStyle = `rgb(${bg.r}, ${bg.g}, ${bg.b})`
    ctx.fillRect(0, 0, cropped.width, cropped.height)
    ctx.drawImage(fullCanvas, 0, sy, fullCanvas.width, sh, 0, 0, fullCanvas.width, sh)

    stampWatermark(cropped)
    const blob = await new Promise<Blob | null>(resolve => cropped.toBlob(resolve, 'image/png'))
    if (!blob) return null
    return new File([blob], filename, { type: 'image/png' })
  } catch {
    return null
  } finally {
    unclip()
    unflatten()
    unfreeze()
  }
}

/**
 * glass-adaptive.js -- the glass thickens behind bright parts of the photo.
 *
 * iOS 27 fixed a specific thing: glass diffuses complex content MORE, not less.
 * The static-glass version of this site already lifts --glass-blur under the
 * photo backdrop as a whole, but "complex" is not a single global number --
 * a photo has bright and dark areas, and a panel sitting over a sunlit patch
 * needs a thicker material than one sitting over deep shade.
 *
 * This module closes the gap per-panel:
 *   1. Read the photo once into a small canvas, compute a luma grid.
 *   2. For each glass surface (.glass--nav, .glass--panel), map its viewport
 *      centre to that grid.
 *   3. Set a per-element CSS variable --panel-adaptive-tint, which the glass
 *      tokens combine with the user's tint. Bright areas push the panel more
 *      opaque; dark areas leave it clear.
 *
 * The user's slider always wins for the upper bound: --panel-adaptive-tint
 * is ADDED to --glass-tint, never subtracted. So if the user picked "fully
 * tinted" the panel stays opaque; if they picked "ultra-clear", a bright
 * patch will still pull the panel a bit more opaque than a dark one, but
 * never by more than 25%.
 *
 * Inactive when:
 *   - the photo backdrop is not selected (no photo = nothing to sample)
 *   - the user has reduced transparency (already opaque)
 *   - the user has fully tinted via the slider (already at the cap)
 *   - reduce-motion is set (the per-frame recompute is technically idle
 *     work, and a user who asked for less motion is also asking for less
 *     "always-doing-something" feel)
 */

import { getBootstrap } from './bootstrap.js';

const GRID_W = 48;            // columns: finer than wide since panels are tall
const GRID_H = 27;            // 16:9-ish aspect; covers the photo at viewport scale
const MAX_ADAPTIVE_TINT = 25; // percent: a bright patch adds at most this much

/**
 * The backdrop image URL is hard-coded into tokens.css (#radar-refract's
 * sibling: .env-photo). The cleanest way to get it without duplicating the
 * constant is to ask the live element -- but .env-photo has opacity 0 when the
 * backdrop is "solid", so we may not get a background-image at all. Fall back
 * to the documented asset path.
 */
function resolvePhotoUrl() {
  const el = document.querySelector('.env-photo');
  const bg = el && getComputedStyle(el).backgroundImage;
  if (bg && bg !== 'none') {
    const m = /url\("?([^")]+)"?\)/.exec(bg.split(',').pop() || '');
    if (m) return resolveUrl(m[1]);
  }
  // Last resort: the hard-coded path from tokens.css. Relative to the CSS file
  // (site/static/css/), the image is at ../img/...
  const css = document.querySelector('link[rel="stylesheet"][href*="tokens.css"]');
  const base = css ? css.href.replace(/tokens\.css.*/, '') : getBootstrap().basePath;
  return new URL('img/backdrop-night.jpg', base).toString();
}

function resolveUrl(relative) {
  try {
    return new URL(relative, document.baseURI).toString();
  } catch {
    return relative;
  }
}

/** Pull a luma+std-dev grid from the photo. Returns null on any failure. */
async function analysePhoto(url) {
  try {
    const img = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = GRID_W;
    canvas.height = GRID_H;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, GRID_W, GRID_H);
    const { data } = ctx.getImageData(0, 0, GRID_W, GRID_H);

    const luma = new Float32Array(GRID_W * GRID_H);
    const variance = new Float32Array(GRID_W * GRID_H);
    for (let i = 0; i < luma.length; i++) {
      const r = data[i * 4];
      const g = data[i * 4 + 1];
      const b = data[i * 4 + 2];
      // Perceptual luma (Rec.709 weights), 0..1.
      luma[i] = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    }
    // A simple local-complexity proxy: variance of each cell's 4-neighbour
    // luma. Enough to distinguish flat sky from detailed grass.
    for (let y = 0; y < GRID_H; y++) {
      for (let x = 0; x < GRID_W; x++) {
        const here = luma[y * GRID_W + x];
        let sum = 0;
        let n = 0;
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= GRID_W || ny >= GRID_H) continue;
          sum += (here - luma[ny * GRID_W + nx]) ** 2;
          n += 1;
        }
        variance[y * GRID_W + x] = n ? sum / n : 0;
      }
    }
    return { luma, variance };
  } catch (error) {
    console.warn('[glass-adaptive] could not analyse backdrop photo:', error);
    return null;
  }
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('image failed to load'));
    img.src = url;
  });
}

/**
 * Find every panel whose material can absorb adaptive tint. We only apply
 * this to surfaces that the user actually reads through (the top bar, the
 * sidebar rail). Listing cards are too small to show the effect and applying
 * it to every one is wasted work.
 */
const PANEL_SELECTOR = '.glass--nav, .glass--panel, .glass--card';

export async function initAdaptiveGlass() {
  const root = document.documentElement;
  if (!root.hasAttribute('data-backdrop')) return; // wait until backdrop known

  // Honour user choices that would make adaptive work invisible.
  const reduceTransparency = window.matchMedia('(prefers-reduced-transparency: reduce)').matches;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceTransparency) return;
  if (root.hasAttribute('data-transparency')) return;
  if (reduceMotion) return;

  const grid = await analysePhoto(resolvePhotoUrl());
  if (!grid) return;

  // ---- reactive updates ----
  let frame = 0;
  let pending = false;
  const photoRect = () => {
    const el = document.querySelector('.env-photo');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    // .env-photo fills the viewport, so the rect is the viewport itself; the
    // grid maps onto whatever the photo covers. The viewport's photoRect is
    // always 0..100% of the photo.
    return r;
  };
  const update = () => {
    frame = 0;
    pending = false;
    const vw = photoRect();
    if (!vw) return;
    const panels = document.querySelectorAll(PANEL_SELECTOR);
    for (const el of panels) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cx = (r.left + r.right) / 2;
      const cy = (r.top + r.bottom) / 2;
      // Map viewport coordinates to grid coordinates. The photo covers the
      // viewport, so any point inside the viewport maps to the grid.
      const gx = clamp01((cx - vw.left) / vw.width);
      const gy = clamp01((cy - vw.top) / vw.height);
      const ix = Math.min(GRID_W - 1, Math.floor(gx * GRID_W));
      const iy = Math.min(GRID_H - 1, Math.floor(gy * GRID_H));
      const luma = grid.luma[iy * GRID_W + ix];

      // Map luma (0..1) to an additive tint. Bright patches pull the panel
      // up to MAX_ADAPTIVE_TINT %; dark patches leave it alone.
      //
      // The curve is deliberately aggressive at the dark end because the
      // shipped photo is a night scene with mean luma around 0.20: with a
      // gentler slope every panel would land at "barely anything" and the
      // visual difference between "bright sky behind" and "deep shade
      // behind" would be invisible. Shift the baseline down so even modest
      // luma differences register.
      const t = clamp01((luma - 0.10) * 1.4) * MAX_ADAPTIVE_TINT;
      el.style.setProperty('--panel-adaptive-tint', `${t.toFixed(1)}%`);
    }
  };
  const schedule = () => {
    if (pending || frame) return;
    pending = true;
    frame = requestAnimationFrame(update);
  };

  update();
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  // The photo is fixed; the only thing that moves is the viewport. Scroll is
  // the dominant trigger; resize catches orientation changes.

  // Re-arm when backdrop or transparency flips on or off.
  const observe = () => {
    if (!root.hasAttribute('data-backdrop')) {
      for (const el of document.querySelectorAll(PANEL_SELECTOR)) {
        el.style.removeProperty('--panel-adaptive-tint');
      }
      return false;
    }
    if (root.hasAttribute('data-transparency')) return false;
    return true;
  };
  // No mutation observer needed: backdrop + transparency are toggled by
  // theme.js, which already dispatches radar:backdrop / radar:tint events.
  document.addEventListener('radar:backdrop', () => {
    // The photo URL is the same and the grid is cached; just re-trigger.
    schedule();
  });
  document.addEventListener('radar:tint', (event) => {
    if (event.detail.percent >= 100) {
      // Already opaque -- no need for adaptive.
      for (const el of document.querySelectorAll(PANEL_SELECTOR)) {
        el.style.removeProperty('--panel-adaptive-tint');
      }
    } else {
      schedule();
    }
  });

  // Cleanup is exposed for the test harness; nothing on the live page needs
  // to call it.
  return function dispose() {
    if (frame) cancelAnimationFrame(frame);
    window.removeEventListener('scroll', schedule);
    window.removeEventListener('resize', schedule);
    for (const el of document.querySelectorAll(PANEL_SELECTOR)) {
      el.style.removeProperty('--panel-adaptive-tint');
    }
  };
}

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}
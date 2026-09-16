/**
 * theme.js -- appearance preferences.
 *
 * Four independent preferences, each stored separately:
 *
 *   radar.theme          'light' | 'dark'        (absent means follow system)
 *   radar.backdrop       'photo'                 (absent means solid colour)
 *   radar.transparency   'reduced'
 *   radar.motion         'reduced'
 *
 * The initial attribute is set by an inline script in <head> so there is no
 * flash of the wrong theme. This module only handles changes after load and
 * keeps the two theme controls synchronised with each other.
 *
 * "Follow system" is the absence of the key rather than a third stored
 * value, so a user who never touches the control keeps tracking their OS
 * setting even if it changes at midnight. "Solid" is the absence of the
 * backdrop key for the same reason: it is the default, and an absent key
 * means a future change of default reaches everyone who never chose.
 */

const THEME_KEY = 'radar.theme';
const BACKDROP_KEY = 'radar.backdrop';
const TRANSPARENCY_KEY = 'radar.transparency';
const TINT_KEY = 'radar.glass-tint';
const MOTION_KEY = 'radar.motion';

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
const reduceTransparencyQuery = window.matchMedia('(prefers-reduced-transparency: reduce)');
const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Private browsing or a storage-blocked context. The preference applies
    // for this page view and is simply not remembered -- never an error the
    // user needs to see.
  }
}

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function currentThemeChoice() {
  const stored = read(THEME_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'system';
}

export function resolvedTheme() {
  const stored = read(THEME_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return darkQuery.matches ? 'dark' : 'light';
}

/**
 * Apply a theme choice.
 *
 * The resolved theme always lands on data-theme, because the CSS only knows
 * about two concrete themes. The *choice* is reflected in aria-pressed on
 * the segmented control, which is what tells the user "you picked system"
 * as opposed to "system happens to be dark right now".
 */
export function applyTheme(choice) {
  const root = document.documentElement;

  if (choice === 'system') {
    store(THEME_KEY, null);
    root.setAttribute('data-theme', darkQuery.matches ? 'dark' : 'light');
  } else {
    store(THEME_KEY, choice);
    root.setAttribute('data-theme', choice);
  }

  syncThemeControls(choice);
  syncMetaThemeColor();
  document.dispatchEvent(new CustomEvent('radar:theme', { detail: { choice } }));
}

/**
 * How much the material is tinted, as a percentage: 0 keeps the designed
 * clear glass, 100 makes every tier opaque --surface.
 *
 * This replaces the old two-state "reduced transparency" switch. iOS 27 made
 * the same change, and for the same reason: with two states, a user who finds
 * the glass a little too clear has no way to say "a little less", only
 * "none at all". Storing a number instead of a flag is what makes the
 * in-between reachable.
 */
export function applyTint(percent) {
  const clamped = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  const root = document.documentElement;

  root.style.setProperty('--glass-tint', `${clamped}%`);

  // The attribute is kept so the OS-level and in-page paths stay compatible
  // with any CSS that still keys off it, and so "reduced" remains a single
  // well-defined point on the slider rather than a parallel mode.
  if (clamped >= 100) {
    root.setAttribute('data-transparency', 'reduced');
    store(TRANSPARENCY_KEY, 'reduced');
  } else {
    root.removeAttribute('data-transparency');
    // The old flag MUST be cleared here, not just the attribute. Leaving it
    // behind makes currentTint() keep returning 100 on the next load, so a
    // user who slid to fully tinted and then back would find the setting
    // silently snapped to opaque after a reload. Two keys, one concept --
    // whichever is written, the other has to go.
    store(TRANSPARENCY_KEY, null);
    store(TINT_KEY, String(clamped));
    if (clamped === 0) store(TINT_KEY, null);
  }

  syncTintControls(clamped);
  document.dispatchEvent(new CustomEvent('radar:tint', { detail: { percent: clamped } }));
}

export function currentTint() {
  if (read(TRANSPARENCY_KEY) === 'reduced') return 100;
  const stored = read(TINT_KEY);
  const n = Number(stored);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 0;
}

/** Keep the slider and its text readout in step with the applied value. */
function syncTintControls(percent) {
  const label =
    percent >= 100 ? '实色' : percent >= 66 ? '偏实色' : percent >= 33 ? '适中' : percent > 0 ? '略柔和' : '清透';
  for (const slider of document.querySelectorAll('[data-tint-slider]')) {
    if (document.activeElement !== slider) slider.value = String(percent);
    slider.setAttribute('aria-valuetext', label);
  }
  for (const readout of document.querySelectorAll('[data-tint-readout]')) {
    readout.textContent = label;
  }
}

export function currentBackdropChoice() {
  return read(BACKDROP_KEY) === 'photo' ? 'photo' : 'solid';
}

/**
 * Apply the backdrop choice.
 *
 * The attribute goes on <html> and CSS does the rest, including deciding
 * whether to request the image at all -- the url() only appears in a rule
 * guarded by [data-backdrop="photo"], so a visitor who never turns it on
 * never downloads it.
 */
export function applyBackdrop(choice) {
  const root = document.documentElement;
  if (choice === 'photo') {
    root.setAttribute('data-backdrop', 'photo');
    store(BACKDROP_KEY, 'photo');
  } else {
    root.removeAttribute('data-backdrop');
    store(BACKDROP_KEY, null);
  }
  syncBackdropControls(choice);
  document.dispatchEvent(new CustomEvent('radar:backdrop', { detail: { choice } }));
}

function syncBackdropControls(choice) {
  for (const button of document.querySelectorAll('[data-backdrop-choice]')) {
    button.setAttribute('aria-pressed', button.dataset.backdropChoice === choice ? 'true' : 'false');
  }
}

export function applyMotion(reduced) {
  const root = document.documentElement;
  if (reduced) {
    root.setAttribute('data-motion', 'reduced');
    store(MOTION_KEY, 'reduced');
  } else {
    root.removeAttribute('data-motion');
    store(MOTION_KEY, null);
  }
  syncSwitch('[data-motion-toggle]', reduced);
  // The refraction drift is SMIL, which no CSS media query can reach, so it
  // has to be paused from here. A user who asked for less motion should not
  // be given a panel that never stops moving -- that is the specific thing
  // the preference is asking us to stop doing.
  setRefractionMotion(!reduced);
}

/**
 * Pause or resume the <animate> inside the refraction filter.
 *
 * SMIL animation lives on the <svg> element, not on CSS, so
 * prefers-reduced-motion cannot touch it declaratively. pauseAnimations() is
 * the standard way in and costs nothing when the element is absent (Safari
 * and Firefox never resolve url(#radar-refract) in the first place).
 */
function setRefractionMotion(enabled) {
  const svg = document.getElementById('radar-refract-defs');
  if (!svg || typeof svg.pauseAnimations !== 'function') return;
  if (enabled) svg.unpauseAnimations();
  else svg.pauseAnimations();
}

function syncSwitch(selector, checked) {
  for (const input of document.querySelectorAll(selector)) {
    input.checked = Boolean(checked);
  }
}

function syncThemeControls(choice) {
  for (const button of document.querySelectorAll('[data-theme-choice]')) {
    button.setAttribute('aria-pressed', button.dataset.themeChoice === choice ? 'true' : 'false');
  }
}

/**
 * Keep the browser chrome colour in step with the theme.
 *
 * Without this, an installed PWA or a mobile browser shows a light address
 * bar above a dark page. The meta tag may not exist yet in the document
 * head, so it is created on demand.
 */
function syncMetaThemeColor() {
  let meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    document.head.append(meta);
  }
  meta.setAttribute('content', resolvedTheme() === 'dark' ? '#0b1220' : '#eef3f9');
}

/** Wire the controls found in the sidebar and top navigation. */
export function initTheme() {
  for (const button of document.querySelectorAll('[data-theme-choice]')) {
    button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
  }

  for (const button of document.querySelectorAll('[data-backdrop-choice]')) {
    button.addEventListener('click', () => applyBackdrop(button.dataset.backdropChoice));
  }

  for (const slider of document.querySelectorAll('[data-tint-slider]')) {
    slider.addEventListener('input', () => applyTint(slider.value));
  }

  for (const input of document.querySelectorAll('[data-motion-toggle]')) {
    input.checked = document.documentElement.hasAttribute('data-motion');
    input.addEventListener('change', () => applyMotion(input.checked));
  }

  initAppearanceSheet();

  syncThemeControls(currentThemeChoice());
  syncBackdropControls(currentBackdropChoice());
  syncMetaThemeColor();

  // The OS "reduce transparency" preference is an accessibility setting, not
  // a taste setting, so it pins the slider to the opaque end and cannot be
  // overridden by the stored value. Everything else comes from storage.
  if (reduceTransparencyQuery.matches) applyTint(100);
  else applyTint(currentTint());

  // Refraction drift follows the motion preference even when the user never
  // touches the switch, because the OS preference alone should be enough.
  if (motionQuery.matches) applyMotion(true);

  reduceTransparencyQuery.addEventListener?.('change', (event) => {
    if (event.matches) applyTint(100);
    else applyTint(currentTint());
  });

  // When the choice is "system", a live OS theme change must be reflected
  // immediately. When the user picked explicitly, it must not be.
  darkQuery.addEventListener?.('change', () => {
    if (currentThemeChoice() === 'system') {
      document.documentElement.setAttribute('data-theme', darkQuery.matches ? 'dark' : 'light');
      syncMetaThemeColor();
    }
  });
}

/**
 * Open and close the appearance sheet from the phone tab bar.
 *
 * This exists because the sidebar and top navigation are both hidden on a
 * phone, which left the theme, transparency and motion controls with nowhere
 * to live -- dark mode was unreachable. The sheet holds a third copy of the
 * same controls, wired above by the attribute selectors, so nothing else had
 * to change.
 */
function initAppearanceSheet() {
  const sheet = document.getElementById('appearance-sheet');
  if (!sheet) return;

  for (const trigger of document.querySelectorAll('[data-open-appearance]')) {
    trigger.addEventListener('click', () => {
      // A native <dialog> gives focus trapping, Escape-to-close and the top
      // layer for free. It is not nested inside a filtered ancestor, so the
      // backdrop-filter on the page cannot clip it.
      if (typeof sheet.showModal === 'function') {
        sheet.showModal();
      } else {
        // Very old engines: fall back to a plain open so the controls are at
        // least reachable rather than silently unavailable.
        sheet.setAttribute('open', '');
      }
    });
  }

  for (const closer of sheet.querySelectorAll('[data-close-appearance]')) {
    closer.addEventListener('click', () => {
      if (typeof sheet.close === 'function') {
        sheet.close();
      } else {
        sheet.removeAttribute('open');
      }
    });
  }

  // Clicking the backdrop closes the sheet, which is what a sheet should do.
  // The check is on the dialog element itself rather than a wrapper, because
  // a click on any child bubbles up with a different target.
  sheet.addEventListener('click', (event) => {
    if (event.target === sheet) sheet.close?.();
  });
}

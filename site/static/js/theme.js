/**
 * theme.js -- appearance preferences.
 *
 * Three independent preferences, each stored separately:
 *
 *   radar.theme          'light' | 'dark'        (absent means follow system)
 *   radar.transparency   'reduced'
 *   radar.motion         'reduced'
 *
 * The initial attribute is set by an inline script in <head> so there is no
 * flash of the wrong theme. This module only handles changes after load and
 * keeps the two theme controls synchronised with each other.
 *
 * "Follow system" is the absence of the key rather than a third stored
 * value, so a user who never touches the control keeps tracking their OS
 * setting even if it changes at midnight.
 */

const THEME_KEY = 'radar.theme';
const TRANSPARENCY_KEY = 'radar.transparency';
const MOTION_KEY = 'radar.motion';

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

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

export function applyTransparency(reduced) {
  const root = document.documentElement;
  if (reduced) {
    root.setAttribute('data-transparency', 'reduced');
    store(TRANSPARENCY_KEY, 'reduced');
  } else {
    root.removeAttribute('data-transparency');
    store(TRANSPARENCY_KEY, null);
  }
  syncSwitch('[data-transparency-toggle]', reduced);
  document.dispatchEvent(new CustomEvent('radar:transparency', { detail: { reduced } }));
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

  for (const input of document.querySelectorAll('[data-transparency-toggle]')) {
    input.checked = document.documentElement.hasAttribute('data-transparency');
    input.addEventListener('change', () => applyTransparency(input.checked));
  }

  for (const input of document.querySelectorAll('[data-motion-toggle]')) {
    input.checked = document.documentElement.hasAttribute('data-motion');
    input.addEventListener('change', () => applyMotion(input.checked));
  }

  initAppearanceSheet();

  syncThemeControls(currentThemeChoice());
  syncMetaThemeColor();

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

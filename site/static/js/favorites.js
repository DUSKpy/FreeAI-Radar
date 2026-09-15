/**
 * favorites.js -- local-only saved providers.
 *
 * Storage contract, and the reasons for each part:
 *
 *   radar.favorites.v1  ->  { "p_groq": { addedAt: "2026-09-15T..." }, ... }
 *
 *  * Only the provider id and the add timestamp are stored. No names, no
 *    keys, no query text. A name stored here would go stale the moment the
 *    catalog renamed a provider, and the id is what the join needs anyway.
 *  * The key carries a version so a future format change can migrate
 *    instead of guessing.
 *  * Nothing here ever leaves the browser. There is no sync endpoint, and
 *    the module makes no network request of any kind.
 *  * A quota failure (storage full, or Safari private mode) degrades to an
 *    in-memory set for the session and reports it once, rather than
 *    throwing on every star click.
 */

const KEY = 'radar.favorites.v1';
const MAX_ENTRIES = 500;

let memoryFallback = null;
let warned = false;

function readRaw() {
  try {
    const text = localStorage.getItem(KEY);
    if (!text) return {};
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeRaw(value) {
  try {
    localStorage.setItem(KEY, JSON.stringify(value));
    return true;
  } catch (error) {
    if (!warned) {
      warned = true;
      console.warn('[radar] 收藏无法写入本地存储，本次会话的改动不会被保留。', error);
    }
    return false;
  }
}

function current() {
  if (memoryFallback) return memoryFallback;
  return readRaw();
}

/** All saved ids, most recently added first. */
export function list() {
  const data = current();
  return Object.entries(data)
    .map(([id, meta]) => ({ id, addedAt: meta?.addedAt ?? null }))
    .sort((a, b) => String(b.addedAt || '').localeCompare(String(a.addedAt || '')));
}

export function ids() {
  return list().map((entry) => entry.id);
}

export function has(providerId) {
  return Object.prototype.hasOwnProperty.call(current(), providerId);
}

export function count() {
  return Object.keys(current()).length;
}

/**
 * Add or remove a provider.
 *
 * Returns the new state so the caller does not have to read it back, and
 * emits a change event so every star on the page (there can be several for
 * the same provider, e.g. card plus detail header) updates together.
 */
export function toggle(providerId) {
  if (!providerId) return false;

  const data = { ...current() };

  if (Object.prototype.hasOwnProperty.call(data, providerId)) {
    delete data[providerId];
  } else {
    if (Object.keys(data).length >= MAX_ENTRIES) {
      // Refuse rather than silently dropping the oldest: a user who hits
      // this limit should be told, not have data vanish.
      document.dispatchEvent(new CustomEvent('radar:favorites-limit', {
        detail: { limit: MAX_ENTRIES },
      }));
      return false;
    }
    data[providerId] = { addedAt: new Date().toISOString() };
  }

  if (!writeRaw(data)) memoryFallback = data;

  const next = Object.prototype.hasOwnProperty.call(data, providerId);
  document.dispatchEvent(new CustomEvent('radar:favorites', {
    detail: { providerId, saved: next, count: Object.keys(data).length },
  }));
  return next;
}

export function clear() {
  if (!writeRaw({})) memoryFallback = {};
  syncAllCounts();
  document.dispatchEvent(new CustomEvent('radar:favorites', {
    detail: { providerId: null, saved: false, count: 0, cleared: true },
  }));
}

/**
 * Import a previously exported list.
 *
 * Accepts both the wrapped export shape and a bare array, because a user
 * who copies the ids out of the JSON view should not have to guess. Unknown
 * ids are kept: a provider that is temporarily missing from the catalog may
 * come back, and dropping it would lose the user's intent.
 */
export function importIds(payload) {
  let incoming = [];
  if (Array.isArray(payload)) incoming = payload;
  else if (Array.isArray(payload?.favorites)) incoming = payload.favorites.map((entry) => entry?.id ?? entry);
  else if (payload && typeof payload === 'object') incoming = Object.keys(payload);

  const data = { ...current() };
  let added = 0;

  for (const raw of incoming) {
    const id = typeof raw === 'string' ? raw.trim() : '';
    if (!id || !id.startsWith('p_')) continue;
    if (Object.keys(data).length >= MAX_ENTRIES) break;
    if (!Object.prototype.hasOwnProperty.call(data, id)) {
      data[id] = { addedAt: new Date().toISOString() };
      added += 1;
    }
  }

  if (!writeRaw(data)) memoryFallback = data;
  syncAllCounts();
  document.dispatchEvent(new CustomEvent('radar:favorites', {
    detail: { providerId: null, saved: false, count: Object.keys(data).length, imported: added },
  }));
  return added;
}

export function exportPayload() {
  return {
    kind: 'freeai-radar.favorites.v1',
    exported_at: new Date().toISOString(),
    favorites: list(),
  };
}

/**
 * Reflect the count in every place that shows it.
 *
 * Elements are found by data attribute rather than id so the sidebar, the
 * top navigation and the favorites page header can all show it without
 * this module knowing about the layout.
 */
export function syncAllCounts() {
  const total = count();

  for (const node of document.querySelectorAll('[data-favorites-count]')) {
    node.textContent = total > 0 ? String(total) : '';
    node.hidden = total === 0;
  }

  for (const button of document.querySelectorAll('[data-favorite-toggle]')) {
    const saved = has(button.dataset.favoriteToggle);
    button.setAttribute('aria-pressed', saved ? 'true' : 'false');
    button.title = saved ? '取消收藏' : '收藏';
    button.classList.toggle('is-saved', saved);

    const label = button.querySelector('.sr-only');
    if (label) {
      const name = button.closest('.service')?.dataset.name || '';
      label.textContent = saved ? `取消收藏 ${name}` : `收藏 ${name}`;
    }
  }
}

/** Wire every star on the page. Safe to call more than once. */
export function initFavorites() {
  syncAllCounts();

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-favorite-toggle]');
    if (!button) return;
    event.preventDefault();
    const saved = toggle(button.dataset.favoriteToggle);
    syncAllCounts();
    document.dispatchEvent(new CustomEvent('radar:toast', {
      detail: { message: saved ? '已加入收藏（仅保存在本机）' : '已取消收藏' },
    }));
  });

  document.addEventListener('radar:favorites', syncAllCounts);
  document.addEventListener('radar:favorites-limit', () => {
    document.dispatchEvent(new CustomEvent('radar:toast', {
      detail: { message: `收藏数量已达上限（${MAX_ENTRIES}）`, tone: 'warn' },
    }));
  });
}

export const LIMIT = MAX_ENTRIES;

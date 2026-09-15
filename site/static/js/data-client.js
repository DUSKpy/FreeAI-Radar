/**
 * data-client.js -- load and cache the public JSON.
 *
 * Rules this module enforces:
 *
 *  1. manifest.json is read first, and the versioned catalog/changes files
 *     it points at are read second. A page never mixes two dataset versions.
 *  2. Each file is fetched at most once per session. Caching by dataset
 *     version means a filter change never re-hits the network.
 *  3. A failed fetch surfaces as a rejected promise carrying a reason, so
 *     the caller can render an error state with a retry action. It is never
 *     silently converted into an empty array -- "empty" and "failed" are
 *     different states and the brief requires them to stay different.
 *  4. Nothing here contacts any host other than the site's own origin.
 */

import { getBootstrap, url } from './bootstrap.js';

const cache = new Map();

export class DataError extends Error {
  constructor(message, { kind, status, path } = {}) {
    super(message);
    this.name = 'DataError';
    this.kind = kind || 'unknown';
    this.status = status ?? null;
    this.path = path ?? null;
  }
}

/** Fetch a JSON file relative to the project base, with an in-memory cache. */
export async function fetchJson(path, { signal, force = false } = {}) {
  const target = url(path);

  if (!force && cache.has(target)) {
    return cache.get(target);
  }

  const promise = (async () => {
    let response;
    try {
      response = await fetch(target, {
        signal,
        credentials: 'omit',
        cache: 'default',
        headers: { Accept: 'application/json' },
      });
    } catch (error) {
      if (error && error.name === 'AbortError') throw error;
      throw new DataError(`无法读取 ${path}：网络请求失败`, {
        kind: 'network',
        path: target,
      });
    }

    if (!response.ok) {
      throw new DataError(
        response.status === 404
          ? `数据文件不存在：${path}`
          : `读取 ${path} 失败（HTTP ${response.status}）`,
        { kind: response.status === 404 ? 'missing' : 'http', status: response.status, path: target },
      );
    }

    try {
      return await response.json();
    } catch (error) {
      throw new DataError(`数据文件不是合法 JSON：${path}`, {
        kind: 'parse',
        path: target,
      });
    }
  })();

  // Cache the promise, not the value, so two components asking at the same
  // time share one request instead of racing.
  cache.set(target, promise);

  try {
    return await promise;
  } catch (error) {
    cache.delete(target);
    throw error;
  }
}

export async function loadManifest(options) {
  return fetchJson('data/manifest.json', options);
}

/**
 * Load the versioned catalog referenced by the manifest.
 *
 * The version check is the point of this function: if the file on disk is a
 * different dataset version than the manifest claims, the page is stale and
 * must say so rather than rendering a mix.
 */
export async function loadCatalog(options) {
  const manifest = options?.manifest || (await loadManifest(options));
  const href = manifest?.catalog_url;
  if (!href) {
    throw new DataError('manifest 里没有 catalog_url，无法定位目录数据', { kind: 'missing' });
  }

  const relative = href.replace(getBootstrap().basePath || '/', '');
  const catalog = await fetchJson(relative, options);

  if (manifest.dataset_version && catalog.dataset_version
      && catalog.dataset_version !== manifest.dataset_version) {
    throw new DataError(
      '目录数据版本与 manifest 不一致，可能正在发布中。请稍后刷新。',
      { kind: 'version-mismatch' },
    );
  }

  return catalog;
}

export async function loadChanges(options) {
  const manifest = options?.manifest || (await loadManifest(options));
  const href = manifest?.changes_url;
  if (!href) return { changes: [] };

  const relative = href.replace(getBootstrap().basePath || '/', '');
  return fetchJson(relative, options);
}

/**
 * CC Switch configurations, keyed by provider id.
 *
 * This file is large and only needed on the detail page, so it is loaded
 * lazily and never as part of first paint.
 */
export async function loadCCSwitch(options) {
  return fetchJson('data/cc-switch.json', options);
}

export async function loadIndex(options) {
  return fetchJson('data/index.json', options);
}

/** Load a daily report payload by date. */
export async function loadReport(date, options) {
  return fetchJson(`data/reports/${date}.json`, options);
}

/** Drop cached data so a retry after a failure actually re-requests. */
export function invalidate(path) {
  if (path) {
    cache.delete(url(path));
    return;
  }
  cache.clear();
}

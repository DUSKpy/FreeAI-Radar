/**
 * bootstrap.js -- read the server-provided context.
 *
 * The build writes one JSON script tag with the dataset version, base path
 * and CC Switch baseline. Reading it here means no module has to guess the
 * base path from window.location, which breaks on a sub-path deploy.
 */

const ELEMENT_ID = 'radar-bootstrap';

const FALLBACK = Object.freeze({
  basePath: '/',
  datasetVersion: null,
  changesVersion: null,
  ccSwitchVersion: null,
  ccSwitchCommit: null,
  generatedAt: null,
  noDataYet: false,
});

let cached = null;

export function getBootstrap() {
  if (cached) return cached;

  const node = document.getElementById(ELEMENT_ID);
  if (!node) {
    cached = FALLBACK;
    return cached;
  }

  try {
    const parsed = JSON.parse(node.textContent || '{}');
    cached = { ...FALLBACK, ...parsed };
  } catch (error) {
    // A malformed bootstrap block must not take the whole page down. The
    // fallback base path of "/" still resolves every asset on a root
    // deployment, and data requests fail loudly on their own.
    console.error('[radar] bootstrap block is not valid JSON', error);
    cached = FALLBACK;
  }

  return cached;
}

/** Absolute URL for a path inside the project base. */
export function url(path) {
  const base = getBootstrap().basePath || '/';
  const clean = String(path || '').replace(/^\/+/, '');
  return `${base}${clean}`;
}

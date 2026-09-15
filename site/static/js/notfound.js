/**
 * notfound.js -- live search on the 404 page.
 *
 * A 404 on a data site is usually a stale link that once pointed at a real
 * provider, so the most useful thing this page can do is let the visitor
 * search the catalog without navigating. Results are rendered inline with
 * the same card component the directory uses.
 *
 * Only three matches are shown: the goal is to hand the visitor the right
 * link, not to become a second directory.
 */

import { loadCatalog, loadManifest } from './data-client.js';
import { el, serviceCard, stateBlock } from './render.js';
import { getBootstrap } from './bootstrap.js';
import { syncAllCounts } from './favorites.js';

const MAX_RESULTS = 3;

export function initNotFound() {
  const results = document.querySelector('[data-results]');
  const input = document.querySelector('[data-search-input]');
  if (!results || !input) return;

  const basePath = getBootstrap().basePath || '/';

  let services = [];
  let ready = false;

  (async () => {
    try {
      const manifest = await loadManifest();
      const catalog = await loadCatalog({ manifest });
      services = buildIndex(catalog);
      ready = true;

      // If the visitor already typed while the catalog was loading, honour
      // that query now instead of discarding it.
      if (input.value.trim()) search(input.value);
    } catch {
      // A 404 page that also reports a data error is noise. Stay quiet and
      // keep the static navigation links working.
      ready = false;
    }
  })();

  let timer = null;
  input.addEventListener('input', () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => search(input.value), 180);
  });

  function search(query) {
    const text = String(query || '').trim().toLowerCase();

    if (!text) {
      results.replaceChildren();
      return;
    }

    if (!ready) {
      results.replaceChildren(stateBlock('loading', '正在载入目录', '马上就好。'));
      return;
    }

    const tokens = text.split(/\s+/).filter(Boolean);
    const matched = services
      .filter((service) => tokens.every((token) => service.searchText.includes(token)))
      .slice(0, MAX_RESULTS);

    if (!matched.length) {
      results.replaceChildren(stateBlock(
        'empty',
        '没有匹配的服务',
        '换个关键词试试，或者直接浏览完整目录。',
        { actionHref: `${basePath}directory.html`, actionLabel: '浏览目录' },
      ));
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const service of matched) fragment.append(serviceCard(service, { basePath }));
    results.replaceChildren(fragment);
    syncAllCounts();
  }
}

function buildIndex(catalog) {
  const modelsByProvider = new Map();
  for (const model of catalog.models || []) {
    if (!modelsByProvider.has(model.provider_id)) modelsByProvider.set(model.provider_id, []);
    modelsByProvider.get(model.provider_id).push(model);
  }

  const offersByProvider = new Map();
  for (const offer of catalog.offers || []) {
    if (!offersByProvider.has(offer.provider_id)) offersByProvider.set(offer.provider_id, []);
    offersByProvider.get(offer.provider_id).push(offer);
  }

  return (catalog.providers || []).map((provider) => {
    const models = modelsByProvider.get(provider.id) || [];
    const offers = offersByProvider.get(provider.id) || [];

    return {
      providerId: provider.id,
      name: provider.name || provider.slug,
      officialDomain: provider.official_domain,
      domainVerified: Boolean(provider.domain_verified),
      offerTypes: [...new Set(offers.map((offer) => offer.offer_type).filter(Boolean))],
      offerCount: offers.length,
      protocols: [...new Set(offers.flatMap((offer) => offer.protocols || []))].sort(),
      conditions: [],
      modelCount: models.length,
      sampleModels: models.slice(0, 2).map((model) => model.model_id),
      checkedAt: offers.map((offer) => offer.evidence?.[0]?.checked_at).filter(Boolean).sort().pop() || null,
      stale: offers.some((offer) => offer.stale),
      needsReview: offers.some((offer) => offer.needs_review),
      hasConflict: offers.some((offer) => offer.info_status === 'conflicting'),
      searchText: [provider.name, provider.slug, provider.official_domain]
        .filter(Boolean).join(' ').toLowerCase(),
    };
  });
}

/**
 * directory.js -- the filterable, sortable service directory.
 *
 * Design constraints from the brief that shape this module:
 *
 *  * The query lives in the URL. A filtered view must be shareable and a
 *    refresh must restore it exactly, so every filter change writes to
 *    history.replaceState. The directory page is a real HTML file, so the
 *    path never changes and a refresh never 404s.
 *  * Filtering is done on already-loaded data. There is no per-keystroke
 *    request; the whole catalog is a few hundred kilobytes and is loaded
 *    once.
 *  * A zero-result filter is an "empty" state, never an "error" state. The
 *    two are rendered differently because the user's next action differs.
 *  * Facet counts are computed from the *other* active filters, so the
 *    numbers tell the truth about what selecting that facet would yield.
 */

import { loadCatalog, loadManifest, DataError } from './data-client.js';
import { el, serviceCard, stateBlock } from './render.js';
import { OFFER_TYPES, TRI_STATE } from './vocab.js';
import { getBootstrap } from './bootstrap.js';
import { syncAllCounts } from './favorites.js';

const PAGE_SIZE = 24;

const SORTS = {
  name: (a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'),
  models: (a, b) => b.modelCount - a.modelCount || a.name.localeCompare(b.name, 'zh-Hans-CN'),
  checked: (a, b) => String(b.checkedAt || '').localeCompare(String(a.checkedAt || '')) || a.name.localeCompare(b.name, 'zh-Hans-CN'),
  offers: (a, b) => b.offerCount - a.offerCount || a.name.localeCompare(b.name, 'zh-Hans-CN'),
};

/** Read the query string into a normalised filter object. */
function readQuery() {
  const params = new URLSearchParams(window.location.search);
  return {
    q: params.get('q') || '',
    sort: SORTS[params.get('sort')] ? params.get('sort') : 'name',
    offer: params.getAll('offer'),
    protocol: params.getAll('protocol'),
    condition: params.getAll('condition'),
    flag: params.getAll('flag'),
    page: Math.max(1, Number.parseInt(params.get('page') || '1', 10) || 1),
  };
}

function writeQuery(state) {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.sort && state.sort !== 'name') params.set('sort', state.sort);
  for (const value of state.offer) params.append('offer', value);
  for (const value of state.protocol) params.append('protocol', value);
  for (const value of state.condition) params.append('condition', value);
  for (const value of state.flag) params.append('flag', value);
  if (state.page > 1) params.set('page', String(state.page));

  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ''}`;
  window.history.replaceState(null, '', next);
}

/**
 * Turn the catalog into directory view-models.
 *
 * The join is performed once at load. Offers are grouped by provider so the
 * card can show "N types of free access" without walking the offer array
 * per card per render.
 */
function buildServices(catalog) {
  const offersByProvider = new Map();
  for (const offer of catalog.offers || []) {
    if (!offersByProvider.has(offer.provider_id)) offersByProvider.set(offer.provider_id, []);
    offersByProvider.get(offer.provider_id).push(offer);
  }

  const modelsByProvider = new Map();
  for (const model of catalog.models || []) {
    if (!modelsByProvider.has(model.provider_id)) modelsByProvider.set(model.provider_id, []);
    modelsByProvider.get(model.provider_id).push(model);
  }

  return (catalog.providers || []).map((provider) => {
    const offers = offersByProvider.get(provider.id) || [];
    const models = modelsByProvider.get(provider.id) || [];

    const offerTypes = [...new Set(offers.map((offer) => offer.offer_type).filter(Boolean))];

    // Protocols are the union across the provider's offers. An empty union
    // stays empty -- it is never filled in with a guess.
    const protocols = [...new Set(offers.flatMap((offer) => offer.protocols || []))].sort();

    const conditions = new Set();
    for (const offer of offers) {
      const map = offer.conditions || {};
      if (map.credit_card === 'need') conditions.add('credit_card');
      if (map.phone_verification === 'need') conditions.add('phone_verification');
      if (map.registration === 'need') conditions.add('registration');
      if (map.topup_required === 'need') conditions.add('topup_required');
      if (map.credit_card === 'not_need') conditions.add('no_credit_card');
    }

    const checkedAt = offers
      .map((offer) => offer.evidence?.[0]?.checked_at)
      .filter(Boolean)
      .sort()
      .pop() || null;

    const baseUrl = offers.find((offer) => offer.base_url)?.base_url || null;

    return {
      providerId: provider.id,
      name: provider.name || provider.slug,
      slug: provider.slug,
      officialDomain: provider.official_domain,
      homepage: provider.homepage_url,
      domainVerified: Boolean(provider.domain_verified),
      offerTypes,
      offerCount: offers.length,
      protocols,
      conditions: [...conditions].sort(),
      modelCount: models.length,
      sampleModels: models.slice(0, 2).map((model) => model.model_id),
      checkedAt,
      baseUrl,
      stale: offers.some((offer) => offer.stale),
      needsReview: offers.some((offer) => offer.needs_review),
      hasConflict: offers.some((offer) => offer.info_status === 'conflicting'),
      searchText: [
        provider.name,
        provider.slug,
        provider.official_domain,
        ...models.slice(0, 12).map((model) => model.model_id),
      ].filter(Boolean).join(' ').toLowerCase(),
    };
  });
}

/** Apply the text query. Tokens are ANDed; each token may match any field. */
function matchesQuery(service, query) {
  if (!query) return true;
  const haystack = service.searchText;
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(token));
}

/**
 * Apply facet selections.
 *
 * Within one facet group the values are ORed (selecting two offer types
 * shows providers with either). Across groups they are ANDed. That is the
 * convention users expect from faceted search.
 */
function matchesFacets(service, filters) {
  if (filters.offer.length && !filters.offer.some((value) => service.offerTypes.includes(value))) {
    return false;
  }

  if (filters.condition.length && !filters.condition.some((value) => service.conditions.includes(value))) {
    return false;
  }

  if (filters.protocol.length) {
    const wantsDeclared = filters.protocol.includes('__declared__');
    const wantsUndeclared = filters.protocol.includes('__undeclared__');
    const specific = filters.protocol.filter((value) => !value.startsWith('__'));

    const okSpecific = specific.length ? specific.some((value) => service.protocols.includes(value)) : false;
    const okDeclared = wantsDeclared && service.protocols.length > 0;
    const okUndeclared = wantsUndeclared && service.protocols.length === 0;

    if (!okSpecific && !okDeclared && !okUndeclared) return false;
  }

  for (const flag of filters.flag) {
    if (flag === 'verified' && !service.domainVerified) return false;
    if (flag === 'has_models' && service.modelCount === 0) return false;
    if (flag === 'stale' && !service.stale) return false;
    if (flag === 'conflict' && !service.hasConflict) return false;
  }

  return true;
}

/** Total matches per facet value, computed against the other groups. */
function computeFacetCounts(services, filters) {
  const counts = {
    offer_type: new Map(),
    condition: new Map(),
    protocol: new Map(),
    flag: new Map(),
  };

  // For each group, filter out that group's own selection so the counts
  // answer "if I also pick this, how many will I get".
  const others = (group) => {
    const copy = { ...filters, offer: [...filters.offer], protocol: [...filters.protocol], condition: [...filters.condition], flag: [...filters.flag] };
    if (group === 'offer') copy.offer = [];
    if (group === 'protocol') copy.protocol = [];
    if (group === 'condition') copy.condition = [];
    if (group === 'flag') copy.flag = [];
    return copy;
  };

  const offerBase = services.filter((s) => matchesFacets(s, others('offer')));
  const conditionBase = services.filter((s) => matchesFacets(s, others('condition')));
  const protocolBase = services.filter((s) => matchesFacets(s, others('protocol')));
  const flagBase = services.filter((s) => matchesFacets(s, others('flag')));

  for (const service of offerBase) {
    for (const type of service.offerTypes) {
      counts.offer_type.set(type, (counts.offer_type.get(type) || 0) + 1);
    }
  }
  for (const service of conditionBase) {
    for (const value of service.conditions) {
      counts.condition.set(value, (counts.condition.get(value) || 0) + 1);
    }
  }
  for (const service of protocolBase) {
    if (service.protocols.length) {
      counts.protocol.set('__declared__', (counts.protocol.get('__declared__') || 0) + 1);
    } else {
      counts.protocol.set('__undeclared__', (counts.protocol.get('__undeclared__') || 0) + 1);
    }
    for (const value of service.protocols) {
      counts.protocol.set(value, (counts.protocol.get(value) || 0) + 1);
    }
  }
  for (const service of protocolBase) {
    if (service.modelCount > 0) counts.protocol.set('__undeclared__', counts.protocol.get('__undeclared__') || 0);
  }
  for (const service of flagBase) {
    if (service.domainVerified) counts.flag.set('verified', (counts.flag.get('verified') || 0) + 1);
    if (service.modelCount > 0) counts.flag.set('has_models', (counts.flag.get('has_models') || 0) + 1);
    if (service.stale) counts.flag.set('stale', (counts.flag.get('stale') || 0) + 1);
    if (service.hasConflict) counts.flag.set('conflict', (counts.flag.get('conflict') || 0) + 1);
  }

  return counts;
}

const CONDITION_LABELS = {
  credit_card: '需要绑卡',
  no_credit_card: '明确无需绑卡',
  phone_verification: '需要手机验证',
  registration: '需要注册',
  topup_required: '需要先充值',
};

const FLAG_LABELS = {
  verified: '官方域名已核对',
  has_models: '来源明确列出模型',
  stale: '数据可能过期',
  conflict: '来源之间存在冲突',
};

export function initDirectory() {
  const results = document.querySelector('[data-results]');
  if (!results) return;

  const searchInput = document.querySelector('[data-search-input]');
  const sortSelect = document.querySelector('[data-sort-select]');
  const summary = document.querySelector('[data-result-summary]');
  const countNode = document.querySelector('[data-result-count]');
  const pager = document.querySelector('[data-pager]');
  const pageStatus = document.querySelector('[data-page-status]');
  const activeFilters = document.querySelector('[data-active-filters]');
  const activeList = document.querySelector('[data-active-filter-list]');
  const facetsPanel = document.querySelector('[data-facets-toggle]');
  const facetsRoot = document.getElementById('dir-facets');
  const basePath = getBootstrap().basePath || '/';

  let services = [];
  let filters = readQuery();
  let request = null;

  // --- render -----------------------------------------------------------

  function renderFacets(counts) {
    const offerRoot = document.querySelector('[data-facet-group="offer_type"]');
    if (offerRoot) {
      offerRoot.replaceChildren();
      const entries = Object.entries(OFFER_TYPES)
        .filter(([key]) => key !== 'unknown' || counts.offer_type.get(key))
        .sort((a, b) => (counts.offer_type.get(b[0]) || 0) - (counts.offer_type.get(a[0]) || 0));

      for (const [key, meta] of entries) {
        const total = counts.offer_type.get(key) || 0;
        offerRoot.append(facetRow({
          group: 'offer_type',
          value: key,
          label: meta.label,
          count: total,
          checked: filters.offer.includes(key),
        }));
      }
    }

    const conditionRoot = document.querySelector('[data-facet-group="condition"]');
    if (conditionRoot) {
      conditionRoot.replaceChildren();
      for (const [key, text] of Object.entries(CONDITION_LABELS)) {
        const total = counts.condition.get(key) || 0;
        conditionRoot.append(facetRow({
          group: 'condition',
          value: key,
          label: text,
          count: total,
          checked: filters.condition.includes(key),
        }));
      }
    }

    // The two summary protocol facets plus one row per declared protocol.
    const protocolRoot = document.querySelector('[data-facet-group="protocol"]');
    if (protocolRoot) {
      const declared = counts.protocol.get('__declared__') || 0;
      const specific = new Map();
      for (const [key, value] of counts.protocol) {
        if (!key.startsWith('__')) specific.set(key, value);
      }

      protocolRoot.replaceChildren();
      protocolRoot.append(facetRow({
        group: 'protocol', value: '__declared__', label: '至少声明了一种协议',
        count: declared, checked: filters.protocol.includes('__declared__'),
      }));
      protocolRoot.append(facetRow({
        group: 'protocol', value: '__undeclared__', label: '未声明任何协议',
        count: counts.protocol.get('__undeclared__') || 0,
        checked: filters.protocol.includes('__undeclared__'),
      }));

      for (const [key, total] of [...specific].sort((a, b) => b[1] - a[1])) {
        protocolRoot.append(facetRow({
          group: 'protocol', value: key,
          label: `${TRI_STATE && ''}${key.replace(/_/g, ' ')}`,
          count: total, checked: filters.protocol.includes(key),
        }));
      }
    }

    for (const node of document.querySelectorAll('[data-facet-count-for]')) {
      const [group, value] = node.dataset.facetCountFor.split(':');
      const map = counts[group === 'flag' ? 'flag' : group] || new Map();
      node.textContent = String(map.get(value) || 0);
      const row = node.closest('.facet');
      if (row) {
        const total = map.get(value) || 0;
        row.classList.toggle('facet--empty', total === 0);
        const input = row.querySelector('input');
        if (input) input.disabled = total === 0 && !input.checked;
      }
    }

    activeFacetSummary(counts);
  }

  function facetRow({ group, value, label, count, checked }) {
    const input = el('input', { type: 'checkbox', dataset: { facet: group }, value });
    input.checked = checked;
    input.disabled = count === 0 && !checked;

    return el('label', { class: `facet${count === 0 && !checked ? ' facet--empty' : ''}` }, [
      input,
      el('span', { class: 'facet__label', text: label }),
      el('span', { class: 'facet__count tabular', text: String(count) }),
    ]);
  }

  function activeFacetSummary() {
    const tokens = [];

    for (const value of filters.offer) {
      tokens.push(removableChip(OFFER_TYPES[value]?.label ?? value, 'offer', value));
    }
    for (const value of filters.condition) {
      tokens.push(removableChip(CONDITION_LABELS[value] ?? value, 'condition', value));
    }
    for (const value of filters.protocol) {
      const text = value === '__declared__' ? '至少声明了一种协议'
        : value === '__undeclared__' ? '未声明任何协议'
        : value.replace(/_/g, ' ');
      tokens.push(removableChip(text, 'protocol', value));
    }
    for (const value of filters.flag) {
      tokens.push(removableChip(FLAG_LABELS[value] ?? value, 'flag', value));
    }

    if (!activeFilters || !activeList) return;

    activeList.replaceChildren(...tokens);
    activeFilters.hidden = tokens.length === 0;

    if (facetsPanel) {
      const countNodeToggle = facetsPanel.querySelector('[data-facet-count]');
      if (countNodeToggle) {
        countNodeToggle.textContent = tokens.length ? String(tokens.length) : '';
        countNodeToggle.hidden = tokens.length === 0;
      }
    }
  }

  function removableChip(text, group, value) {
    const button = el('button', {
      type: 'button',
      class: 'selected-chip__remove',
      'aria-label': `移除筛选：${text}`,
      dataset: { removeFacet: `${group}:${value}` },
      text: '×',
    });
    return el('span', { class: 'selected-chip' }, [document.createTextNode(text), button]);
  }

  function render() {
    const counts = computeFacetCounts(services, filters);
    renderFacets(counts);

    const matched = services
      .filter((service) => matchesQuery(service, filters.q))
      .filter((service) => matchesFacets(service, filters))
      .sort(SORTS[filters.sort] || SORTS.name);

    const totalPages = Math.max(1, Math.ceil(matched.length / PAGE_SIZE));
    filters.page = Math.min(filters.page, totalPages);
    const start = (filters.page - 1) * PAGE_SIZE;
    const pageItems = matched.slice(start, start + PAGE_SIZE);

    if (matched.length === 0) {
      // Empty is a distinct state from error, with a different next action.
      const hasFilters = filters.q || filters.offer.length || filters.protocol.length
        || filters.condition.length || filters.flag.length;

      results.replaceChildren(stateBlock(
        hasFilters ? 'empty' : 'nodata',
        hasFilters ? '没有符合条件的服务' : '目录还没有数据',
        hasFilters
          ? '试着放宽筛选条件，或者清除搜索词。'
          : '首次采集成功之后，这里会列出所有已收录的免费 AI 服务。',
        hasFilters ? {} : { actionHref: `${basePath}index.html`, actionLabel: '回到概览' },
      ));
    } else {
      const fragment = document.createDocumentFragment();
      for (const service of pageItems) {
        fragment.append(serviceCard(service, { basePath }));
      }
      results.replaceChildren(fragment);
      syncAllCounts();
    }

    if (summary) {
      summary.replaceChildren(
        document.createTextNode('共 '),
        el('span', { class: 'tabular', text: String(matched.length) }),
        document.createTextNode(` 个服务${matched.length !== services.length ? `（全部 ${services.length} 个）` : ''}`),
      );
    }

    if (countNode) countNode.textContent = String(matched.length);

    if (pager) {
      pager.hidden = totalPages <= 1;
      if (pageStatus) {
        pageStatus.textContent = `第 ${filters.page} / ${totalPages} 页`;
      }
      const prev = pager.querySelector('[data-page-prev]');
      const next = pager.querySelector('[data-page-next]');
      if (prev) prev.disabled = filters.page <= 1;
      if (next) next.disabled = filters.page >= totalPages;
    }
  }

  // --- interaction ------------------------------------------------------

  function update(mutate, { resetPage = true } = {}) {
    if (resetPage) filters.page = 1;
    mutate(filters);
    writeQuery(filters);
    render();
    scheduleFocusReturn();
  }

  function toggleFacet(group, value, checked) {
    const key = group === 'offer_type' ? 'offer'
      : group === 'condition' ? 'condition'
      : group === 'protocol' ? 'protocol'
      : 'flag';

    update((state) => {
      const list = state[key];
      const index = list.indexOf(value);
      if (checked && index === -1) list.push(value);
      if (!checked && index !== -1) list.splice(index, 1);
    });
  }

  let focusTarget = null;
  function scheduleFocusReturn() {
    if (!focusTarget) return;
    const selector = focusTarget;
    focusTarget = null;
    requestAnimationFrame(() => {
      const node = document.querySelector(selector);
      if (node) node.focus({ preventScroll: true });
    });
  }

  // Debounced text search: 180ms is long enough to avoid a render per
  // keystroke on a 600-row catalog, short enough to feel immediate.
  let searchTimer = null;
  searchInput?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      update((state) => { state.q = searchInput.value.trim(); });
    }, 180);
  });

  sortSelect?.addEventListener('change', () => {
    update((state) => { state.sort = sortSelect.value; });
  });

  facetsRoot?.addEventListener('change', (event) => {
    const input = event.target.closest('[data-facet]');
    if (!input) return;
    toggleFacet(input.dataset.facet, input.value, input.checked);
  });

  activeList?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-facet]');
    if (!button) return;
    const [group, value] = button.dataset.removeFacet.split(':');
    toggleFacet(group, value, false);
  });

  for (const button of document.querySelectorAll('[data-clear-filters]')) {
    button.addEventListener('click', () => {
      update((state) => {
        state.q = '';
        state.offer = [];
        state.protocol = [];
        state.condition = [];
        state.flag = [];
        state.sort = 'name';
      });
      if (searchInput) searchInput.value = '';
      if (sortSelect) sortSelect.value = 'name';
    });
  }

  pager?.addEventListener('click', (event) => {
    if (event.target.closest('[data-page-prev]')) {
      update((state) => { state.page = Math.max(1, state.page - 1); }, { resetPage: false });
    }
    if (event.target.closest('[data-page-next]')) {
      update((state) => { state.page += 1; }, { resetPage: false });
    }
  });

  facetsPanel?.addEventListener('click', () => {
    const open = facetsRoot?.dataset.open === 'true';
    if (facetsRoot) facetsRoot.dataset.open = open ? 'false' : 'true';
    facetsPanel.setAttribute('aria-expanded', open ? 'false' : 'true');
  });

  // Back/forward navigation must restore the filter state, since it lives
  // in the URL.
  window.addEventListener('popstate', () => {
    filters = readQuery();
    if (searchInput) searchInput.value = filters.q;
    if (sortSelect) sortSelect.value = filters.sort;
    render();
  });

  // --- load -------------------------------------------------------------

  if (searchInput) searchInput.value = filters.q;
  if (sortSelect) sortSelect.value = filters.sort;

  results.replaceChildren(stateBlock('loading', '正在载入目录', '数据从本站 data/ 目录读取，不访问任何外部接口。'));

  request = new AbortController();

  (async () => {
    try {
      const manifest = await loadManifest({ signal: request.signal });
      const catalog = await loadCatalog({ manifest, signal: request.signal });
      services = buildServices(catalog);
      render();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      const detail = error instanceof DataError ? error.message : String(error?.message || error);
      results.replaceChildren(stateBlock(
        'error',
        '目录数据读取失败',
        `${detail} 这通常是发布过程中的短暂状态，稍后重试即可。`,
        { actionHref: window.location.href, actionLabel: '重新加载' },
      ));
      if (summary) summary.textContent = '数据读取失败';
    }
  })();

  return () => request?.abort();
}

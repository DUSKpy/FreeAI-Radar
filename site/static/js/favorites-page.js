/**
 * favorites-page.js -- the local favorites view.
 *
 * The join problem this solves: favorites store ids only, but the page has
 * to show a name, a free type and a status. So the catalog is loaded and
 * each saved id is looked up.
 *
 * An id with no match is NOT deleted. A provider can disappear from a
 * source for a week and come back; silently dropping the user's entry would
 * lose their intent. Instead the row is kept and marked "已不在目录中",
 * with the id shown so they can search for it themselves.
 */

import { loadCatalog, loadManifest, DataError } from './data-client.js';
import { el, chip, serviceCard, stateBlock } from './render.js';
import { OFFER_TYPES, label, tone } from './vocab.js';
import { getBootstrap } from './bootstrap.js';
import { list, clear, exportPayload, importIds, syncAllCounts } from './favorites.js';
import { serviceCard as buildCard } from './render.js';

const MAX_COMPARE = 3;

export function initFavoritesPage() {
  const root = document.querySelector('[data-favorites-root]');
  if (!root) return;

  const compareSection = document.querySelector('[data-compare-section]');
  const compareGrid = document.querySelector('[data-compare-grid]');
  const metaNode = document.querySelector('[data-favorites-meta]');
  const basePath = getBootstrap().basePath || '/';

  let services = new Map();

  wireActions();

  (async () => {
    try {
      const manifest = await loadManifest();
      const catalog = await loadCatalog({ manifest });
      services = indexServices(catalog);
      render();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      // Favorites still work without the catalog: the ids are local, and
      // hiding them because a fetch failed would be wrong.
      render({ degraded: error instanceof DataError ? error.message : String(error?.message || error) });
    }
  })();

  document.addEventListener('radar:favorites', () => render());

  function indexServices(catalog) {
    const byId = new Map();

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

    for (const provider of catalog.providers || []) {
      const offers = offersByProvider.get(provider.id) || [];
      const models = modelsByProvider.get(provider.id) || [];

      byId.set(provider.id, {
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
        searchText: '',
        raw: { provider, offers, models },
      });
    }

    return byId;
  }

  function render({ degraded } = {}) {
    const saved = list();

    if (metaNode) {
      metaNode.textContent = saved.length
        ? `共 ${saved.length} 项，保存在本机浏览器中。`
        : '目前还没有收藏。';
    }

    if (!saved.length) {
      root.replaceChildren(stateBlock(
        'empty',
        '还没有收藏任何服务',
        '在目录页点服务卡片右上角的星标即可加入收藏。收藏只存在这台设备上。',
        { actionHref: `${basePath}directory.html`, actionLabel: '去目录挑选' },
      ));
      if (compareSection) compareSection.hidden = true;
      return;
    }

    if (degraded) {
      root.replaceChildren(
        el('div', { class: 'notice notice--warn' }, [
          el('span', { class: 'notice__icon', 'aria-hidden': 'true', text: '!' }),
          el('div', { class: 'notice__body' }, [
            el('p', { class: 'notice__title', text: '目录数据读取失败' }),
            el('p', { text: `${degraded} 收藏列表本身没有丢失，但它只记录了 ID，暂时无法显示名称。` }),
          ]),
        ]),
        missingList(saved),
      );
      if (compareSection) compareSection.hidden = true;
      return;
    }

    const matched = [];
    const missing = [];

    for (const entry of saved) {
      const service = services.get(entry.id);
      if (service) matched.push({ entry, service });
      else missing.push(entry);
    }

    const fragment = document.createDocumentFragment();

    if (matched.length) {
      const grid = el('div', { class: 'favorites__list' });
      for (const { service } of matched) {
        grid.append(buildCard(service, { basePath }));
      }
      fragment.append(grid);
      syncAllCounts();
    }

    if (missing.length) {
      fragment.append(el('p', { class: 'helper', style: { marginTop: 'var(--space-4)' } }, [
        document.createTextNode(`${missing.length} 项已不在当前目录中（可能只是暂时从来源里消失了）：`),
      ]));
      fragment.append(missingList(missing));
    }

    root.replaceChildren(fragment);

    renderCompare(matched);
  }

  function missingList(entries) {
    const box = el('div', { class: 'favorites__list' });
    for (const entry of entries) {
      box.append(el('div', { class: 'favorite--missing glass glass--card glass--edge' }, [
        el('p', { class: 'mono wrap-anywhere', text: entry.id }),
        el('p', { class: 'helper', text: '这个服务当前不在目录里。它可能会回来，所以我们保留了这个收藏。' }),
        el('button', {
          type: 'button',
          class: 'btn btn--ghost btn--small',
          dataset: { favoriteToggle: entry.id },
          text: '移除',
        }),
      ]));
    }
    return box;
  }

  /**
   * Side-by-side comparison for up to three favorites.
   *
   * Rows are aligned by using one grid with fixed field labels per column,
   * so the reader compares down a column rather than across two separate
   * cards. Only fields that exist for at least one column are shown, which
   * avoids a wall of "未知".
   */
  function renderCompare(matched) {
    if (!compareSection || !compareGrid) return;

    const selected = matched.slice(0, MAX_COMPARE);
    if (selected.length < 2) {
      compareSection.hidden = true;
      return;
    }

    const columns = selected.map(({ service }) => {
      const offer = service.raw.offers[0];
      return {
        service,
        baseUrl: service.raw.offers.find((entry) => entry.base_url)?.base_url ?? null,
        offerType: service.offerTypes[0] ?? null,
        offerLabel: service.offerTypes.length
          ? label(OFFER_TYPES, service.offerTypes[0])
          : '未知',
        conditions: offer?.conditions ?? {},
        quota: offer?.quota ?? null,
        models: service.modelCount,
      };
    });

    const grid = el('div', { class: 'compare__grid' });

    for (const column of columns) {
      const { service } = column;

      const rows = el('dl', { class: 'compare__rows' });

      const addRow = (name, value) => {
        rows.append(el('dt', { text: name }));
        rows.append(el('dd', {}, [typeof value === 'string' ? document.createTextNode(value) : value]));
      };

      addRow('免费类型', chip(column.offerLabel, tone(OFFER_TYPES, column.offerType)));
      addRow('模型数', column.models ? `${column.models} 个` : '未列出');
      addRow('绑卡', column.conditions.credit_card === 'need' ? '需要'
        : column.conditions.credit_card === 'not_need' ? '不需要' : '未知');
      addRow('注册', column.conditions.registration === 'need' ? '需要'
        : column.conditions.registration === 'not_need' ? '不需要' : '未知');
      addRow('协议', service.protocols.length
        ? service.protocols.map((p) => p.replace(/_/g, ' ')).join('、')
        : '未声明');
      addRow('域名核对', service.domainVerified ? '已核对' : '未核对');
      addRow('Base URL', el('span', { class: 'mono wrap-anywhere', text: column.baseUrl || '未提供' }));

      grid.append(el('div', { class: 'compare__col' }, [
        el('div', { class: 'compare__head' }, [
          el('a', {
            href: `${basePath}provider.html?id=${encodeURIComponent(service.providerId)}`,
            text: service.name,
          }),
          el('button', {
            type: 'button',
            class: 'btn btn--icon btn--ghost',
            dataset: { favoriteToggle: service.providerId },
            'aria-pressed': 'true',
            title: '取消收藏',
          }, [el('span', { class: 'sr-only', text: `取消收藏 ${service.name}` })]),
        ]),
        rows,
      ]));
    }

    compareGrid.replaceChildren(grid);
    compareSection.hidden = false;
  }

  function wireActions() {
    for (const button of document.querySelectorAll('[data-favorites-clear]')) {
      button.addEventListener('click', () => {
        if (!window.confirm('确定要清空本机上的全部收藏吗？这个操作无法撤销。')) return;
        clear();
        render();
        document.dispatchEvent(new CustomEvent('radar:toast', { detail: { message: '收藏已清空' } }));
      });
    }

    for (const button of document.querySelectorAll('[data-favorites-export]')) {
      button.addEventListener('click', () => {
        const payload = JSON.stringify(exportPayload(), null, 2);
        const blob = new Blob([payload], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `freeai-radar-favorites-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);

        // Also push the text to the clipboard, because on iPad Safari a
        // download lands in Files and is easy to lose track of.
        navigator.clipboard?.writeText(payload).catch(() => {});
        document.dispatchEvent(new CustomEvent('radar:toast', {
          detail: { message: '已导出文件，并尝试复制到剪贴板' },
        }));
      });
    }
  }
}

/**
 * Reduce a saved entry to the two comparison fields the brief cares about.
 *
 * Exported for the tests: comparing two favorites must never require the
 * caller to know the catalog's internal joins.
 */
export function comparisonFields(service) {
  return {
    name: service.name,
    offerLabel: service.offerTypes?.length ? label(OFFER_TYPES, service.offerTypes[0]) : '未知',
    modelCount: service.modelCount ?? 0,
    protocols: service.protocols ?? [],
  };
}

export { importIds };

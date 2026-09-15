/**
 * provider.js -- the detail page.
 *
 * The page is addressed by ?id=<provider_id>. Everything is rendered from
 * the already-exported catalog and cc-switch files; there is no per-provider
 * static file and no server route.
 *
 * The order of the page is the order a reader needs it in:
 *   1. what is this service and is its domain verified
 *   2. how were these fields obtained  (the honesty notice)
 *   3. free offers
 *   4. models
 *   5. raw source excerpts
 * Configuration generation sits in the right rail, because it is an action,
 * not information.
 */

import { loadCatalog, loadManifest, loadCCSwitch, DataError } from './data-client.js';
import { el, chip, protocolMarkers, offerBlock, evidenceItem, stateBlock, capabilityLabels } from './render.js';
import { INFO_STATUS, label, tone, SOURCE_LEVELS } from './vocab.js';
import { getBootstrap } from './bootstrap.js';
import { has as isFavorite, syncAllCounts, toggle as toggleFavorite } from './favorites.js';
import { openCCSwitchDialog } from './ccswitch-dialog.js';

function qs(id) {
  return document.getElementById(id);
}

export function initProvider() {
  const root = document.querySelector('[data-provider-root]');
  if (!root) return;

  const fallback = document.querySelector('[data-provider-fallback]');
  const basePath = getBootstrap().basePath || '/';
  const providerId = new URLSearchParams(window.location.search).get('id');

  if (!providerId) {
    showFallback('缺少服务 ID', '这个地址没有带上服务 ID。请从目录页点进一个服务，或直接浏览目录。', {
      actionHref: `${basePath}directory.html`, actionLabel: '浏览目录',
    });
    return;
  }

  (async () => {
    try {
      const manifest = await loadManifest();
      const catalog = await loadCatalog({ manifest });

      const provider = (catalog.providers || []).find((entry) => entry.id === providerId);
      if (!provider) {
        showFallback('没有找到这个服务', '目录里没有这个 ID 对应的服务。它可能已经被来源移除，或者链接里的 ID 有误。', {
          actionHref: `${basePath}directory.html`, actionLabel: '返回目录',
        });
        return;
      }

      const models = (catalog.models || []).filter((entry) => entry.provider_id === providerId);
      const offers = (catalog.offers || []).filter((entry) => entry.provider_id === providerId);

      renderIdentity(root, provider, models, offers, basePath);
      renderVerification(root, provider, offers);
      renderOffers(root, offers);
      renderModels(root, models, provider);
      renderEvidence(root, offers);
      renderMeta(root, provider, models, offers, basePath);

      root.hidden = false;
      if (fallback) fallback.hidden = true;

      // The dialog needs the CC Switch configurations only once opened, so
      // the file is fetched lazily rather than on first paint.
      const ccButton = root.querySelector('[data-open-ccswitch]');
      ccButton?.addEventListener('click', async () => {
        ccButton.disabled = true;
        try {
          const ccSwitch = await loadCCSwitch();
          openCCSwitchDialog({
            provider,
            models,
            offers,
            ccSwitch,
            entry: ccSwitch?.entries?.[providerId] ?? null,
          });
        } catch (error) {
          document.dispatchEvent(new CustomEvent('radar:toast', {
            detail: { message: '无法读取配置数据，请稍后重试', tone: 'warn' },
          }));
        } finally {
          ccButton.disabled = false;
        }
      });

      const support = root.querySelector('[data-ccswitch-support]');
      if (support) {
        const entry = null;
        support.textContent = offers.some((offer) => offer.base_url)
          ? '支持的应用取决于来源声明的接口协议。点开后会逐个标注是否可用。'
          : '来源没有提供 Base URL，因此无法生成可导入的配置。';
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;
      showFallback(
        '目录数据读取失败',
        error instanceof DataError ? error.message : String(error?.message || error),
        { actionHref: window.location.href, actionLabel: '重新加载' },
      );
    }
  })();

  function showFallback(title, body, options = {}) {
    root.hidden = true;
    if (!fallback) return;
    fallback.hidden = false;
    fallback.replaceChildren(stateBlock('error', title, body, options));
  }
}

function renderIdentity(root, provider, models, offers, basePath) {
  const nameNode = root.querySelector('[data-provider-name]');
  if (nameNode) nameNode.textContent = provider.name || provider.slug;

  document.title = `${provider.name || provider.slug} · FreeAI Radar`;

  const verifiedNode = root.querySelector('[data-provider-verified]');
  if (verifiedNode) {
    if (provider.domain_verified) {
      verifiedNode.hidden = false;
      verifiedNode.replaceChildren(chip(`官方域名已核对：${provider.official_domain}`, 'ok'));
    } else {
      verifiedNode.hidden = true;
    }
  }

  const domainNode = root.querySelector('[data-provider-domain]');
  if (domainNode) {
    domainNode.textContent = provider.official_domain
      ? provider.official_domain
      : '官方域名未确认（来源没有给出可核对的官网地址）';
  }

  const links = root.querySelector('[data-provider-links]');
  if (links) {
    links.replaceChildren();
    const entries = [
      ['官网', provider.homepage_url],
      ['注册', provider.signup_url],
      ['文档', provider.docs_url],
    ];
    for (const [text, href] of entries) {
      if (!href) continue;
      links.append(el('a', {
        class: 'btn btn--ghost btn--small',
        href,
        rel: 'noopener noreferrer nofollow',
        target: '_blank',
        text: `${text} ↗`,
      }));
    }
    for (const offer of offers.slice(0, 1)) {
      if (offer.base_url) {
        links.append(el('span', { class: 'btn btn--ghost btn--small', text: 'Base URL 见下方', 'aria-hidden': 'true' }));
      }
    }
  }

  // The favorite button in the topbar.
  const favButton = document.querySelector('[data-favorite-toggle-current]');
  if (favButton) {
    favButton.hidden = false;
    favButton.dataset.favoriteToggle = provider.id;
    const labelNode = favButton.querySelector('[data-favorite-label]');
    const refresh = () => {
      const saved = isFavorite(provider.id);
      favButton.setAttribute('aria-pressed', saved ? 'true' : 'false');
      if (labelNode) labelNode.textContent = saved ? '已收藏' : '收藏';
    };
    refresh();
    document.addEventListener('radar:favorites', refresh);
    syncAllCounts();
  }
}

/**
 * The honesty notice.
 *
 * Its wording is generated from the actual evidence rather than being a
 * fixed sentence: if every field came from directory sources, it says so.
 * A generic "data may be inaccurate" line would be ignored; a specific one
 * stating where these particular numbers came from is actionable.
 */
function renderVerification(root, provider, offers) {
  const node = root.querySelector('[data-verification-text]');
  if (!node) return;

  const officialCount = offers.filter((offer) => offer.info_status === 'official_confirmed').length;
  const sources = new Set();
  for (const offer of offers) {
    for (const entry of offer.evidence || []) sources.add(entry.source_id);
  }

  const sourceText = sources.size
    ? `字段来自 ${sources.size} 个公开来源：${[...sources].join('、')}。`
    : '这个服务的字段没有附带来源记录。';

  let confidence;
  if (officialCount > 0) {
    confidence = `${offers.length} 个免费条目中有 ${officialCount} 个已在服务方官方文档中得到确认。`;
  } else if (offers.some((offer) => offer.info_status === 'conflicting')) {
    confidence = '不同来源对某些字段给出了不一致的说法，两侧原话都保留在下方「来源与摘录」里，我们没有替你做取舍。';
  } else {
    confidence = '这些条目都还只是「目录声明」：我们读到了别人的整理列表，但还没有在官方文档中找到对应表述。';
  }

  node.textContent = `${sourceText}${confidence} Radar 不调用上游接口，因此无法确认密钥是否有效、额度是否真的可用。`;
}

function renderOffers(root, offers) {
  const node = root.querySelector('[data-offers]');
  if (!node) return;

  if (!offers.length) {
    node.replaceChildren(el('p', { class: 'muted', text: '来源里没有为这个服务记录免费条目。' }));
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const offer of offers) fragment.append(offerBlock(offer));
  node.replaceChildren(fragment);
}

function renderModels(root, models, provider) {
  const body = root.querySelector('[data-models-body]');
  const note = root.querySelector('[data-models-note]');
  const section = root.querySelector('[data-section="models"]');

  if (!body) return;

  if (!models.length) {
    // Say why it is empty, because "no models listed" has two very
    // different causes and the reader needs to know which one applies.
    if (section) section.hidden = true;
    return;
  }

  if (section) section.hidden = false;
  if (note) note.textContent = `共 ${models.length} 个，全部来自来源的明确列举`;

  const fragment = document.createDocumentFragment();

  for (const model of models.sort((a, b) => a.model_id.localeCompare(b.model_id))) {
    const protocols = model.protocols?.length
      ? model.protocols.map((p) => p.replace(/_/g, ' ')).join(' · ')
      : '未声明';

    const row = el('tr', {}, [
      el('th', { scope: 'row', class: 'mono wrap-anywhere', text: model.model_id }),
      el('td', {
        class: 'tabular',
        text: model.context_window_tokens
          ? `${model.context_window_tokens.toLocaleString('zh-CN')} tokens`
          : '未知',
      }),
      el('td', {
        text: model.declared_capabilities?.length
          ? capabilityLabels(model.declared_capabilities).join(' · ')
          : '未声明',
      }),
      el('td', {
        class: protocols === '未声明' ? 'subtle' : '',
        text: protocols === '未声明' ? '未声明（不代表不支持）' : protocols,
      }),
    ]);
    fragment.append(row);
  }

  body.replaceChildren(fragment);
}

function renderEvidence(root, offers) {
  const node = root.querySelector('[data-evidence]');
  if (!node) return;

  const seen = new Set();
  const items = [];

  for (const offer of offers) {
    for (const entry of offer.evidence || []) {
      const key = `${entry.source_id}|${entry.excerpt}`;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(entry);
    }
  }

  if (!items.length) {
    node.replaceChildren(el('p', { class: 'muted', text: '没有可展示的来源摘录。' }));
    return;
  }

  node.replaceChildren(...items.map(evidenceItem));
}

function renderMeta(root, provider, models, offers, basePath) {
  const meta = root.querySelector('[data-provider-meta]');
  const sources = root.querySelector('[data-provider-sources]');

  if (meta) {
    const rows = [
      ['内部 ID', el('span', { class: 'mono', text: provider.id })],
      ['状态', provider.status === 'active' ? '在目录中' : String(provider.status || '未知')],
      ['别名', provider.aliases?.length ? provider.aliases.join('、') : '无'],
      ['来源家族', provider.source_families?.length ? provider.source_families.join('、') : '未知'],
      ['免费条目数', String(offers.length)],
      ['模型数', String(models.length)],
    ];

    const dl = el('dl', { class: 'deflist' });
    for (const [name, value] of rows) {
      dl.append(el('dt', { text: name }));
      dl.append(el('dd', {}, [typeof value === 'string' ? document.createTextNode(value) : value]));
    }
    meta.replaceChildren(dl);
  }

  if (sources) {
    const families = new Set();
    for (const offer of offers) {
      for (const entry of offer.evidence || []) {
        families.add(`${entry.source_id}\u0000${entry.source_level || 'directory'}`);
      }
    }

    if (!families.size) {
      sources.replaceChildren(el('li', { class: 'muted', text: '没有来源记录' }));
      return;
    }

    sources.replaceChildren(...[...families].map((entry) => {
      const [id, level] = entry.split('\u0000');
      return el('li', {}, [
        el('span', { text: id }),
        document.createTextNode(' · '),
        el('span', { class: 'subtle', text: SOURCE_LEVELS[level] ?? '目录整理' }),
      ]);
    }));
  }
}

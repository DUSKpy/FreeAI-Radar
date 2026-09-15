/**
 * render.js -- DOM builders shared by the directory, favorites and 404 pages.
 *
 * Everything here creates nodes with createElement and textContent. Inner
 * HTML is never used with scraped data: excerpts come from third-party
 * README files, so they are treated as untrusted text at every point.
 *
 * Markup shapes match the Jinja templates exactly. When a server-rendered
 * card and a client-rendered card differ, the transition between them is
 * visible, so the two must be changed together.
 */

import {
  OFFER_TYPES, INFO_STATUS, CALL_STATUS, TRI_STATE,
  PROTOCOLS, CAPABILITIES, label, tone, quotaText, triStateText,
} from './vocab.js';
import { url } from './bootstrap.js';

/** Element helper. Attributes are set as properties to avoid HTML parsing. */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);

  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'style') Object.assign(node.style, value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }

  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }

  return node;
}

export function svg(path, { size = 16, stroke = 1.8, fill = 'none' } = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const node = document.createElementNS(NS, 'svg');
  node.setAttribute('viewBox', '0 0 24 24');
  node.setAttribute('width', String(size));
  node.setAttribute('height', String(size));
  node.setAttribute('fill', fill);
  node.setAttribute('stroke', stroke ? 'currentColor' : 'none');
  node.setAttribute('stroke-width', String(stroke));
  node.setAttribute('stroke-linecap', 'round');
  node.setAttribute('stroke-linejoin', 'round');
  node.setAttribute('aria-hidden', 'true');

  const p = document.createElementNS(NS, 'path');
  p.setAttribute('d', path);
  node.append(p);
  return node;
}

export function chip(text, chipTone = 'neutral', { title, dot = true } = {}) {
  return el('span', { class: `chip chip--${chipTone}`, title }, [
    dot ? el('span', { class: 'chip__dot', 'aria-hidden': 'true' }) : null,
    document.createTextNode(text),
  ]);
}

/**
 * The four protocol markers.
 *
 * A marker for a declared protocol is solid; a marker for an explicitly
 * unsupported one is struck through; an undeclared one is dashed and
 * muted. Three visually distinct states, because "we don't know" and "we
 * were told no" are different facts.
 */
export function protocolMarkers(declared = []) {
  const set = new Set(declared);

  const group = el('span', {
    class: 'proto-group',
    role: 'group',
    'aria-label': '接口协议支持情况',
  });

  for (const protocol of PROTOCOLS) {
    const on = set.has(protocol.key);
    const state = on ? 'on' : 'unknown';
    group.append(
      el('span', {
        class: `proto proto--${on ? 'on' : ''}`,
        dataset: { protocol: protocol.key, state },
        title: on ? `${protocol.full}：来源已声明` : `${protocol.full}：暂无来源声明`,
        'aria-label': on ? `${protocol.full}：来源已声明` : `${protocol.full}：来源未声明，不代表不支持`,
      }, [protocol.short]),
    );
  }

  // Explicitly-note when nothing at all is declared, so the reader is not
  // left to infer it from four identical markers.
  if (set.size === 0) {
    group.setAttribute('title', '来源没有声明任何接口协议，这不等于不支持任何协议');
  }

  return group;
}

/**
 * Build a directory result card.
 *
 * `service` is a view-model assembled by directory.js, not a raw catalog
 * record. Keeping the shape explicit means the card does not need to know
 * about the catalog's internal joins.
 */
export function serviceCard(service, { basePath = '/' } = {}) {
  const card = el('article', {
    class: 'service glass--card glass glass--edge',
    dataset: {
      serviceId: service.providerId,
      search: service.searchText || '',
      offerType: (service.offerTypes || []).join(' '),
      protocols: (service.protocols || []).join(' '),
      conditions: (service.conditions || []).join(' '),
      models: String(service.modelCount ?? 0),
      verified: service.domainVerified ? 'true' : 'false',
      stale: service.stale ? 'true' : 'false',
      conflict: service.hasConflict ? 'true' : 'false',
      name: String(service.name || '').toLowerCase(),
    },
  });

  // --- identity row ------------------------------------------------------
  const favorite = el('button', {
    type: 'button',
    class: 'btn btn--icon btn--ghost',
    dataset: { favoriteToggle: service.providerId },
    'aria-pressed': 'false',
    title: '收藏',
  }, [
    svg('M12 4.6l2.3 4.9 5.2.7-3.8 3.7.9 5.3-4.6-2.5-4.6 2.5.9-5.3L4.5 10.2l5.2-.7z'),
    el('span', { class: 'sr-only', text: `收藏 ${service.name}` }),
  ]);

  card.append(
    el('div', { class: 'service__top' }, [
      el('div', { class: 'service__ident' }, [
        el('h3', { class: 'service__name' }, [
          el('a', {
            href: `${basePath}provider.html?id=${encodeURIComponent(service.providerId)}`,
            text: service.name,
          }),
        ]),
        service.officialDomain
          ? el('p', { class: 'service__domain mono wrap-anywhere', text: service.officialDomain })
          : el('p', { class: 'service__domain', text: '官方域名未确认' }),
      ]),
      favorite,
    ]),
  );

  // --- model line --------------------------------------------------------
  // The count and the sample ids are separate facts: the count comes from
  // an explicit model list when one exists, and is never extrapolated from
  // a number the source mentioned in passing.
  let modelsLine;
  if (service.modelCount > 0) {
    modelsLine = el('p', { class: 'service__models' }, [
      el('span', { class: 'tabular', text: String(service.modelCount) }),
      document.createTextNode(' 个可用模型'),
      service.sampleModels?.length
        ? el('span', {}, [
            document.createTextNode(' · '),
            el('span', { class: 'service__modelid', text: service.sampleModels.join(' · ') }),
          ])
        : null,
    ]);
  } else {
    modelsLine = el('p', { class: 'service__models', text: '模型列表未在来源中明确列出' });
  }
  card.append(modelsLine);

  // --- chips -------------------------------------------------------------
  const chips = el('div', { class: 'service__chips' });

  for (const offerType of service.offerTypes || []) {
    const meta = OFFER_TYPES[offerType];
    chips.append(chip(meta?.label ?? `未知类型（${offerType}）`, meta?.tone ?? 'neutral'));
  }

  chips.append(protocolMarkers(service.protocols || []));

  if (service.domainVerified) chips.append(chip('域名已核对', 'ok'));
  if (service.stale) chips.append(chip('数据可能过期', 'warn', { title: '上次成功采集距今超过阈值' }));
  if (service.hasConflict) chips.append(chip('来源存在冲突', 'warn', { title: '不同来源对该服务的关键字段给出了不同值' }));
  if (service.needsReview) chips.append(chip('待核验', 'info'));

  card.append(chips);

  // --- footer ------------------------------------------------------------
  card.append(
    el('div', { class: 'service__foot' }, [
      el('span', { class: 'helper' }, [
        document.createTextNode('最后核对 '),
        el('time', {
          class: 'tabular',
          datetime: service.checkedAt || '',
          text: service.checkedAt ? service.checkedAt.slice(0, 16).replace('T', ' ') : '未知',
        }),
      ]),
      el('a', {
        class: 'btn btn--small',
        href: `${basePath}provider.html?id=${encodeURIComponent(service.providerId)}`,
        text: '查看详情',
      }),
    ]),
  );

  return card;
}

/**
 * Render one offer inside the detail page.
 *
 * Offers are shown as a table-like block rather than a card grid, because
 * the reader is comparing five parallel fields across one or two offers and
 * a definition list keeps the labels aligned.
 */
export function offerBlock(offer) {
  const rows = [];

  rows.push([
    '免费类型',
    chip(label(OFFER_TYPES, offer.offer_type), tone(OFFER_TYPES, offer.offer_type)),
  ]);
  rows.push(['信息状态', chip(label(INFO_STATUS, offer.info_status), tone(INFO_STATUS, offer.info_status))]);
  rows.push(['调用状态', chip(label(CALL_STATUS, offer.call_status), tone(CALL_STATUS, offer.call_status))]);
  rows.push(['额度', quotaText(offer.quota)]);

  const conditions = offer.conditions || {};
  const conditionRows = [
    ['需要绑卡', conditions.credit_card],
    ['需要手机验证', conditions.phone_verification],
    ['需要注册账号', conditions.registration],
    ['需要先充值', conditions.topup_required],
  ].filter(([, value]) => value !== undefined);

  for (const [name, value] of conditionRows) {
    rows.push([name, chip(triStateText(value), tone(TRI_STATE, value))]);
  }

  if (conditions.topup_minimum) {
    rows.push(['最低充值额', currencyText(conditions.topup_minimum)]);
  }

  if (offer.rate_limits?.length) {
    rows.push([
      '速率限制',
      offer.rate_limits
        .map((limit) => `${formatRateValue(limit.value)} ${limit.metric?.toUpperCase() ?? ''}`.trim())
        .join(' · '),
    ]);
  }

  if (offer.base_url) rows.push(['Base URL', el('span', { class: 'mono wrap-anywhere', text: offer.base_url })]);
  if (offer.region?.length) rows.push(['适用地区', offer.region.join(' · ')]);
  if (offer.effective_from) rows.push(['生效时间', offer.effective_from.slice(0, 10)]);
  if (offer.ends_on) rows.push(['结束时间', offer.ends_on.slice(0, 10)]);
  if (offer.reviewed_at) rows.push(['核验时间', offer.reviewed_at.slice(0, 19).replace('T', ' ')]);

  const dl = el('dl', { class: 'deflist' });
  for (const [name, value] of rows) {
    dl.append(el('dt', { text: name }));
    dl.append(el('dd', {}, [typeof value === 'string' ? document.createTextNode(value) : value]));
  }

  const block = el('div', { class: 'card glass glass--card glass--edge' }, [dl]);

  if (offer.stale) {
    block.prepend(el('div', { class: 'notice notice--warn' }, [
      el('span', { class: 'notice__icon', 'aria-hidden': 'true', text: '!' }),
      el('div', { class: 'notice__body' }, [
        el('p', { text: '这条记录超过新鲜度阈值，来源可能已经变了。' }),
      ]),
    ]));
  }

  if (offer.needs_review) {
    block.prepend(el('div', { class: 'notice notice--info' }, [
      el('span', { class: 'notice__icon', 'aria-hidden': 'true', text: 'i' }),
      el('div', { class: 'notice__body' }, [
        el('p', { text: '这条记录还没有经过人工核验，下面是来源的原话。' }),
      ]),
    ]));
  }

  if (!offer.base_url) {
    block.append(el('p', { class: 'helper', text: '来源没有给出这个服务的 Base URL，因此无法生成导入配置。' }));
  }

  return block;
}

function formatRateValue(value) {
  if (value === null || value === undefined) return '未知';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number % 1_000_000 === 0 ? 0 : 1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(number % 1000 === 0 ? 0 : 1)}K`;
  return String(number);
}

function currencyText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `$${number.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
}

/**
 * One evidence row: where a claim came from, plus the source's own words.
 *
 * The excerpt is the raw text from the upstream README and is inserted with
 * textContent. It is never treated as markup.
 */
export function evidenceItem(entry) {
  const item = el('div', { class: 'evidence__item' });

  item.append(el('p', { class: 'evidence__excerpt', text: entry.excerpt || '（来源未提供摘录）' }));

  const meta = el('p', { class: 'evidence__meta' }, [
    el('span', { text: entry.source_id || '未知来源' }),
    document.createTextNode(' · '),
    el('span', { text: entry.source_level === 'official' ? '官方文档' : '目录整理' }),
    document.createTextNode(' · 于 '),
    el('time', {
      class: 'tabular',
      datetime: entry.checked_at || '',
      text: entry.checked_at ? entry.checked_at.slice(0, 16).replace('T', ' ') : '未知',
    }),
  ]);

  if (entry.http_status) {
    meta.append(document.createTextNode(` · HTTP ${entry.http_status}`));
  }

  item.append(meta);

  if (entry.source_record_url) {
    item.append(el('a', {
      class: 'evidence__link',
      href: entry.source_record_url,
      rel: 'noopener noreferrer nofollow',
      target: '_blank',
      text: '查看来源原文 ↗',
    }));
  }

  return item;
}

/** The four data-state blocks, matching components/state.html. */
export function stateBlock(kind, title, body, { actionHref, actionLabel } = {}) {
  const icons = {
    loading: 'M12 3.6a8.4 8.4 0 108.4 8.4',
    error: 'M12 7.8v5M12 15.9v.1',
    nodata: 'M4.6 6.6v10.8c0 1.5 3.3 2.8 7.4 2.8s7.4-1.3 7.4-2.8V6.6',
    empty: 'M16 16l3.4 3.4',
  };

  const node = el('div', {
    class: 'state',
    dataset: { stateKind: kind },
    'aria-busy': kind === 'loading' ? 'true' : null,
  }, [
    el('span', { class: 'state__icon', 'aria-hidden': 'true' }, [svg(icons[kind] || icons.empty, { size: 26 })]),
    el('p', { class: 'state__title', text: title }),
    el('p', { class: 'state__body', text: body }),
  ]);

  if (actionHref) {
    node.append(el('a', { class: 'btn btn--small', href: actionHref, text: actionLabel || '查看' }));
  }

  return node;
}

/** Capability tags as human labels, ordered by the canonical vocabulary. */
export function capabilityLabels(list = []) {
  return list.map((entry) => CAPABILITIES[entry] ?? entry);
}

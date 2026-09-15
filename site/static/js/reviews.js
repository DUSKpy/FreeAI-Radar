/**
 * reviews.js -- the read-only verification checklist.
 *
 * What this renders: every claim that has no human decision yet, grouped by
 * provider, each with its source excerpt and a direct link to the upstream
 * line it came from.
 *
 * What this must never render: anything that writes. There is no approve
 * button, no reject button, no comment box. The workflow is a commit to
 * config/reviews.yaml, and the commit itself is the audit trail. An
 * in-page control that appeared to decide would be a lie about how the
 * data actually changes.
 *
 * So the only action offered is "read the source", which is the action a
 * reviewer actually performs first.
 */

import { loadCatalog, loadManifest, DataError } from './data-client.js';
import { el, chip, evidenceItem, stateBlock } from './render.js';
import { INFO_STATUS, label, tone } from './vocab.js';
import { getBootstrap } from './bootstrap.js';
import { exportJson } from './download.js';

export function initReviews() {
  const root = document.querySelector('[data-review-list]');
  if (!root) return;

  const countNode = document.querySelector('[data-review-count]');
  const basePath = getBootstrap().basePath || '/';

  (async () => {
    try {
      const manifest = await loadManifest();
      const catalog = await loadCatalog({ manifest });
      render(catalog);
    } catch (error) {
      if (error?.name === 'AbortError') return;
      root.replaceChildren(stateBlock(
        'error',
        '核验清单读取失败',
        error instanceof DataError ? error.message : String(error?.message || error),
        { actionHref: window.location.href, actionLabel: '重新加载' },
      ));
    }
  })();

  function render(catalog) {
    const providers = new Map((catalog.providers || []).map((entry) => [entry.id, entry]));

    // A claim is pending when it is a directory claim with no conflict and
    // no recorded decision. Official confirmations and resolved conflicts
    // are not pending -- they have already been decided.
    const pendingByProvider = new Map();

    for (const claim of catalog.claims || []) {
      if (claim.review_status === 'official_confirmed') continue;
      if (!claim.subject_id) continue;

      if (!pendingByProvider.has(claim.subject_id)) pendingByProvider.set(claim.subject_id, []);
      pendingByProvider.get(claim.subject_id).push(claim);
    }

    // Providers whose offers are flagged for review also belong here, even
    // if no individual claim was raised.
    for (const offer of catalog.offers || []) {
      if (!offer.needs_review) continue;
      if (pendingByProvider.has(offer.provider_id)) continue;
      pendingByProvider.set(offer.provider_id, []);
    }

    const total = pendingByProvider.size;
    if (countNode) countNode.textContent = String(total);

    if (!total) {
      root.replaceChildren(stateBlock(
        'empty',
        '当前没有待核验的条目',
        '所有已采集的字段要么已与官方文档比对过，要么来源本身就给出了明确依据。新采集到的条目会自动出现在这里。',
      ));
      return;
    }

    const groups = [...pendingByProvider.entries()].sort((a, b) => {
      const nameA = providers.get(a[0])?.name ?? a[0];
      const nameB = providers.get(b[0])?.name ?? b[0];
      return nameA.localeCompare(nameB, 'zh-Hans-CN');
    });

    const fragment = document.createDocumentFragment();

    fragment.append(el('div', { class: 'cluster', style: { marginBottom: 'var(--space-4)' } }, [
      el('button', {
        type: 'button',
        class: 'btn btn--ghost btn--small',
        id: 'reviews-export',
        text: '导出待核验清单 JSON',
      }),
      el('span', {
        class: 'helper',
        text: '导出的是只读清单，供你在本地逐条比对。提交结论需要修改仓库里的 config/reviews.yaml。',
      }),
    ]));

    const list = el('ul', { class: 'checklist' });

    for (const [providerId, claims] of groups) {
      const provider = providers.get(providerId);
      const name = provider?.name ?? providerId;

      const detail = claims.length
        ? claims.slice(0, 4).map((claim) => `${claim.field}：${formatValue(claim.value)}`).join('；')
        : '这条记录被标记为需要人工确认。';

      const item = el('li', { class: 'checkitem', dataset: { state: 'open' } }, [
        el('span', { class: 'checkitem__mark', 'aria-hidden': 'true', text: '?' }),
        el('div', { class: 'checkitem__body' }, [
          el('p', { class: 'checkitem__title' }, [
            el('a', { href: `${basePath}provider.html?id=${encodeURIComponent(providerId)}`, text: name }),
            claims.length ? el('span', { class: 'helper', text: ` · ${claims.length} 个待核验字段` }) : null,
          ]),
          el('p', { class: 'checkitem__detail', text: detail }),
        ]),
      ]);

      const evidence = claims.flatMap((claim) => claim.evidence ? [claim.evidence] : []).slice(0, 2);
      if (evidence.length) {
        const box = el('div', { class: 'evidence' });
        for (const entry of evidence) box.append(evidenceItem(entry));
        item.querySelector('.checkitem__body').append(box);
      }

      const actions = el('div', { class: 'checkitem__actions' });
      if (provider?.docs_url) {
        actions.append(el('a', {
          class: 'btn btn--ghost btn--small',
          href: provider.docs_url,
          rel: 'noopener noreferrer nofollow',
          target: '_blank',
          text: '去看官方文档 ↗',
        }));
      }
      const firstEvidence = evidence[0];
      if (firstEvidence?.source_record_url) {
        actions.append(el('a', {
          class: 'btn btn--ghost btn--small',
          href: firstEvidence.source_record_url,
          rel: 'noopener noreferrer nofollow',
          target: '_blank',
          text: '去看来源原文 ↗',
        }));
      }
      if (actions.childElementCount) item.querySelector('.checkitem__body').append(actions);

      list.append(item);
    }

    fragment.append(list);

    // The machine-readable export so a reviewer can work offline. It is
    // generated from the same in-memory data, so it cannot drift from the
    // rendered list.
    const exportPayloadData = {
      kind: 'freeai-radar.review-queue.v1',
      generated_at: new Date().toISOString(),
      dataset_version: catalog.dataset_version ?? null,
      note: '只读待核验清单。结论请提交到仓库的 config/reviews.yaml，本文件不接受任何回写。',
      items: groups.map(([providerId, claims]) => ({
        provider_id: providerId,
        provider_name: providers.get(providerId)?.name ?? providerId,
        fields: claims.map((claim) => ({
          claim_id: claim.id,
          field: claim.field,
          value: claim.value,
          review_status: claim.review_status,
          source_id: claim.evidence?.source_id ?? null,
          source_record_url: claim.evidence?.source_record_url ?? null,
          excerpt: claim.evidence?.excerpt ?? null,
          checked_at: claim.evidence?.checked_at ?? null,
        })),
      })),
    };

    root.replaceChildren(fragment);

    document.getElementById('reviews-export')?.addEventListener('click', () => {
      exportJson(exportPayloadData, `freeai-radar-review-queue-${new Date().toISOString().slice(0, 10)}.json`);
      document.dispatchEvent(new CustomEvent('radar:toast', { detail: { message: '已导出待核验清单' } }));
    });
  }
}

function formatValue(value) {
  if (value === null || value === undefined) return '（空）';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export { INFO_STATUS, label, tone, chip };

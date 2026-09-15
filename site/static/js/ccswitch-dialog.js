/**
 * ccswitch-dialog.js -- the configuration preview sheet.
 *
 * Behaviour that matters:
 *
 *  * The dialog is rebuilt on every change of target app or model, because
 *    the protocol verdict can flip between apps and a stale deep link is
 *    worse than no link.
 *
 *  * When the verdict is `unknown` or `unsupported_protocol` there is NO
 *    link rendered at all -- not a disabled one, not a link with a warning.
 *    A clickable ccswitch:// URL that silently does nothing is exactly the
 *    misleading affordance the brief forbids.
 *
 *  * Copy uses the async clipboard API when available and falls back to a
 *    hidden textarea + execCommand. The fallback exists because the async
 *    API requires a secure context, and a fork may well be hosted on plain
 *    HTTP.
 *
 *  * Every app gets a visible "copy all fields" path, so the page is fully
 *    usable on a machine with no ccswitch:// handler registered.
 */

import { buildConfig, fieldsToText, APP_LABELS, STATUS } from './cc-switch.js';
import { el, chip } from './render.js';

let dialog = null;
let state = null;

const STATUS_PRESENTATION = {
  [STATUS.READY_WITHOUT_KEY]: { tone: 'ok', title: '可以导入（仍需你自己填密钥）' },
  [STATUS.UNSUPPORTED_PROTOCOL]: { tone: 'warn', title: '协议不匹配，不生成导入链接' },
  [STATUS.UNKNOWN]: { tone: 'neutral', title: '来源未声明协议，无法判断是否兼容' },
  [STATUS.INVALID_ENDPOINT]: { tone: 'danger', title: '缺少可用的 Base URL' },
  [STATUS.NEEDS_CONVERSION]: { tone: 'warn', title: '需要协议转换' },
};

export function openCCSwitchDialog(context) {
  dialog = document.getElementById('ccswitch-sheet');
  if (!dialog) return;

  state = {
    provider: context.provider,
    models: context.models || [],
    offers: context.offers || [],
    entry: context.entry,
    app: pickInitialApp(context),
    modelId: pickInitialModel(context),
  };

  renderApps();
  renderModels();
  render();

  if (typeof dialog.showModal === 'function') {
    dialog.showModal();
  } else {
    // Very old engines: fall back to the open attribute so the sheet is at
    // least visible and closable.
    dialog.setAttribute('open', '');
  }
}

function pickInitialApp(context) {
  const apps = Object.keys(context.entry?.apps || {});
  if (!apps.length) return 'claude';

  // Prefer an app whose verdict is a usable one, so the dialog opens on the
  // most likely-successful choice instead of making the user hunt.
  const score = { ready_without_key: 0, ready: 0, needs_conversion: 1, unsupported_protocol: 2, unknown: 3 };
  return apps
    .slice()
    .sort((a, b) => {
      const sa = score[context.entry.apps[a]?.status] ?? 9;
      const sb = score[context.entry.apps[b]?.status] ?? 9;
      return sa - sb;
    })[0];
}

function pickInitialModel(context) {
  const apps = context.entry?.apps;
  if (!apps) return null;
  for (const app of Object.values(apps)) {
    const field = app.fields?.find((entry) => entry.key === 'model');
    if (field?.value) return field.value;
  }
  return null;
}

function renderApps() {
  const root = dialog.querySelector('[data-ccswitch-apps]');
  if (!root) return;

  const apps = Object.keys(state.entry?.apps || {});
  const list = apps.length ? apps : ['claude', 'codex', 'gemini', 'opencode', 'openclaw'];

  root.replaceChildren(...list.map((app) => {
    const config = state.entry?.apps?.[app];
    const verdict = config?.status;

    const button = el('button', {
      type: 'button',
      class: 'segmented__option',
      role: 'radio',
      'aria-checked': app === state.app ? 'true' : 'false',
      dataset: { ccApp: app },
      title: verdict ? displayReasonShort(verdict) : '',
    }, [
      el('span', { text: APP_LABELS[app] ?? app }),
      verdict ? el('span', { class: `chip chip--${STATUS_PRESENTATION[verdict]?.tone ?? 'neutral'} chip--tiny`, text: '' }) : null,
    ]);

    if (verdict && verdict !== STATUS.READY_WITHOUT_KEY) {
      button.classList.add('segmented__option--caution');
    }

    return button;
  }));
}

function displayReasonShort(status) {
  return STATUS_PRESENTATION[status]?.title ?? status;
}

function renderModels() {
  const select = dialog.querySelector('[data-ccswitch-model]');
  if (!select) return;

  const options = [el('option', { value: '', text: '不指定模型' })];
  for (const model of state.models) {
    options.push(el('option', {
      value: model.model_id,
      text: model.display_name && model.display_name !== model.model_id
        ? `${model.display_name}（${model.model_id}）`
        : model.model_id,
    }));
  }

  select.replaceChildren(...options);
  select.value = state.modelId ?? '';
}

function currentProtocols() {
  const offer = state.offers.find((entry) => entry.base_url);
  if (offer?.protocols?.length) return offer.protocols;

  // The build's cc-switch file carries the same declaration. Falling back to
  // it keeps the browser verdict identical to the Python one when the
  // catalog and the cc-switch export were generated from the same run.
  const entry = state.entry;
  if (entry?.protocols?.length) return entry.protocols;
  return [];
}

function currentBaseUrl() {
  const offer = state.offers.find((entry) => entry.base_url);
  return offer?.base_url || state.entry?.base_url || '';
}

function render() {
  const baseUrl = currentBaseUrl();
  const protocols = currentProtocols();
  const providerName = state.provider.name || state.provider.slug;

  const config = buildConfig({
    providerName,
    app: state.app,
    baseUrl,
    modelId: state.modelId,
    homepage: state.provider.homepage_url,
    protocols,
    verified: Boolean(state.provider.domain_verified),
  });

  renderStatus(config);
  renderFields(config);
  renderPreview(config);
}

function renderStatus(config) {
  const root = dialog.querySelector('[data-ccswitch-status]');
  if (!root) return;

  const presentation = STATUS_PRESENTATION[config.status] ?? { tone: 'neutral', title: config.status };
  const children = [
    el('p', { class: 'notice__title', text: presentation.title }),
  ];

  if (config.reason) children.push(el('p', { text: config.reason }));

  if (config.status === STATUS.READY_WITHOUT_KEY) {
    children.push(el('p', {}, [
      document.createTextNode('来源声明支持的协议：'),
      el('strong', { text: config.protocolLabel || config.protocol || '未知' }),
      document.createTextNode(`，与 ${config.appLabel} 的调用路径一致。`),
    ]));
  }

  if (config.warnings.length) {
    const list = el('ul');
    for (const warning of config.warnings) list.append(el('li', { text: warning }));
    children.push(list);
  }

  root.replaceChildren(el('div', { class: `notice notice--${presentation.tone}` }, [
    el('span', { class: 'notice__icon', 'aria-hidden': 'true', text: presentation.tone === 'ok' ? '✓' : '!' }),
    el('div', { class: 'notice__body' }, children),
  ]));
}

function renderFields(config) {
  const root = dialog.querySelector('[data-ccswitch-fields]');
  if (!root) return;

  const fragment = document.createDocumentFragment();

  for (const field of config.fields) {
    const isEmpty = field.value === null || field.value === undefined || field.value === '';

    const valueNode = field.secret
      ? el('p', { class: 'cfgfield__value cfgfield__value--empty', text: '（留空，请在你的 CC Switch 中填写）' })
      : isEmpty
        ? el('p', { class: 'cfgfield__value cfgfield__value--empty', text: '（来源未提供）' })
        : el('p', { class: 'cfgfield__value mono wrap-anywhere', text: String(field.value) });

    const row = el('div', { class: `cfgfield${field.secret ? ' cfgfield--secret' : ''}` }, [
      el('p', { class: 'cfgfield__label' }, [
        document.createTextNode(field.label),
        field.required ? el('span', { class: 'helper', text: ' · 必填' }) : null,
      ]),
      valueNode,
      el('p', { class: 'cfgfield__hint', text: field.hint }),
    ]);

    if (field.copiable && !isEmpty) {
      row.append(el('button', {
        type: 'button',
        class: 'btn btn--ghost btn--small',
        dataset: { copyField: field.key },
        text: '复制',
      }));
    }

    fragment.append(row);
  }

  // The deep link is only rendered for a usable verdict. Absence is the
  // signal: there is no greyed-out link to click by mistake.
  if (config.deepLink) {
    fragment.append(el('div', { class: 'stack', style: { gap: 'var(--space-2)' } }, [
      el('a', {
        class: 'btn btn--primary btn--block',
        href: config.deepLink,
        rel: 'noopener',
        text: `用 CC Switch 打开（${config.appLabel}）`,
      }),
      el('p', { class: 'helper' }, [
        document.createTextNode('如果没有反应，说明这台设备还没有注册 ccswitch:// 协议处理器。'),
        document.createTextNode('这是正常的——请用上面的「复制全部字段」手动粘贴。'),
      ]),
    ]));
  } else {
    fragment.append(el('p', { class: 'helper' }, [
      document.createTextNode('在这种协议状态下，Radar 不会生成导入链接，避免你导入一个注定失效的配置。'),
      document.createTextNode('你仍然可以复制上面的字段，自行判断如何在 CC Switch 中配置。'),
    ]));
  }

  root.replaceChildren(fragment);
}

function renderPreview(config) {
  const wrap = dialog.querySelector('[data-ccswitch-preview-wrap]');
  const node = dialog.querySelector('[data-ccswitch-preview]');
  if (!wrap || !node) return;

  const payload = {
    provider_name: config.providerName,
    target_app: config.app,
    base_url: config.baseUrl,
    model_id: config.modelId,
    protocols: config.protocols,
    status: config.status,
    protocol: config.protocol,
    api_key: null,
    supported_cc_switch_version: config.supportedVersion,
    supported_cc_switch_commit: config.supportedCommit,
    generated_at: new Date().toISOString(),
  };

  node.textContent = JSON.stringify(payload, null, 2);
  wrap.hidden = false;
}

// --- clipboard -----------------------------------------------------------

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the legacy path: the async API rejects on an
      // insecure origin or without a user gesture.
    }
  }

  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    document.body.append(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

function toast(message) {
  document.dispatchEvent(new CustomEvent('radar:toast', { detail: { message } }));
}

export function initCCSwitchDialog() {
  const sheet = document.getElementById('ccswitch-sheet');
  if (!sheet) return;

  for (const button of sheet.querySelectorAll('[data-ccswitch-close]')) {
    button.addEventListener('click', () => sheet.close?.() ?? sheet.removeAttribute('open'));
  }

  sheet.addEventListener('click', (event) => {
    if (event.target === sheet) sheet.close?.();
  });

  sheet.addEventListener('click', async (event) => {
    const appButton = event.target.closest('[data-cc-app]');
    if (appButton) {
      state.app = appButton.dataset.ccApp;
      for (const other of sheet.querySelectorAll('[data-cc-app]')) {
        other.setAttribute('aria-checked', other === appButton ? 'true' : 'false');
      }
      render();
      return;
    }

    const copyButton = event.target.closest('[data-copy-field]');
    if (copyButton) {
      const field = copyButton.closest('.cfgfield');
      const value = field?.querySelector('.cfgfield__value')?.textContent || '';
      const ok = await copyText(value);
      toast(ok ? '已复制到剪贴板' : '复制失败，请手动选择文本');
      return;
    }

    if (event.target.closest('[data-ccswitch-copy-all]')) {
      const config = buildConfig({
        providerName: state.provider.name || state.provider.slug,
        app: state.app,
        baseUrl: currentBaseUrl(),
        modelId: state.modelId,
        homepage: state.provider.homepage_url,
        protocols: currentProtocols(),
        verified: Boolean(state.provider.domain_verified),
      });
      const ok = await copyText(fieldsToText(config.fields));
      toast(ok ? '已复制全部字段' : '复制失败，请手动选择文本');
    }
  });

  sheet.addEventListener('change', (event) => {
    if (event.target.matches('[data-ccswitch-model]')) {
      state.modelId = event.target.value || null;
      render();
    }
  });
}

/**
 * cc-switch.js -- browser-side CC Switch configuration builder.
 *
 * This mirrors radar/cc_switch.py so the preview dialog can recompute a
 * configuration when the user switches target app or model, without
 * re-requesting anything. The two implementations must agree; the Python
 * side is authoritative and the test suite asserts the same fixtures
 * against both.
 *
 * The protocol gate is the core rule and is reproduced exactly:
 *
 *   claude   requires anthropic_messages
 *   codex    requires openai_responses
 *   gemini   requires gemini_native
 *   opencode requires openai_chat
 *   openclaw requires openai_chat
 *
 * If the source did not declare any protocol we return `unknown` and
 * produce NO deep link. We do not assume "OpenAI-compatible" from a URL
 * shape, and we do not guess from the model name. `unknown` never becomes
 * a positive or a negative.
 *
 * The generated configuration NEVER contains an API key. The apiKey field
 * is emitted with a null value and a label telling the user to fill it in
 * their own CC Switch.
 */

export const SUPPORTED_VERSION = '3.20.3';
export const SUPPORTED_COMMIT = '06082e1';
export const DEEP_LINK_VERSION = 'v1';
export const MAX_FIELD_LENGTH = 2048;
export const MAX_NAME_LENGTH = 120;

export const APP_PROTOCOL_REQUIREMENTS = {
  claude: ['anthropic_messages'],
  codex: ['openai_responses'],
  gemini: ['gemini_native'],
  opencode: ['openai_chat'],
  openclaw: ['openai_chat'],
};

export const APP_LABELS = {
  claude: 'Claude Code',
  codex: 'Codex CLI',
  gemini: 'Gemini CLI',
  opencode: 'OpenCode',
  openclaw: 'OpenClaw',
};

export const PROTOCOL_LABELS = {
  openai_chat: 'Chat Completions',
  openai_responses: 'Responses API',
  anthropic_messages: 'Anthropic Messages',
  gemini_native: 'Gemini 原生',
};

export const STATUS = {
  READY: 'ready',
  READY_WITHOUT_KEY: 'ready_without_key',
  UNSUPPORTED_PROTOCOL: 'unsupported_protocol',
  UNKNOWN: 'unknown',
  INVALID_ENDPOINT: 'invalid_endpoint',
  NEEDS_CONVERSION: 'needs_conversion',
};

const ENDPOINT_PATTERN = /^https?:\/\/[^\s<>"']+$/i;

/**
 * Normalise an endpoint for the CC Switch link.
 *
 * Mirrors normalise_endpoint() in Python:
 *   * trailing slashes removed
 *   * a duplicated version segment collapsed (…/v1/v1 -> …/v1)
 *   * non-ASCII percent-encoded, because the deep link is a URL
 */
export function normaliseEndpoint(raw) {
  let text = String(raw ?? '').trim();
  if (!text) return '';

  text = text.replace(/\/+$/, '');
  // Collapse a repeated trailing version segment of the same version.
  text = text.replace(/\/(v\d+(?:beta)?)\/\1$/i, '/$1');
  // Collapse the common /v1/v1 case where the first is part of a path.
  text = text.replace(/(\/v\d+(?:beta)?)\/v\d+(?:beta)?$/i, '$1');

  try {
    return encodeURI(decodeURI(text));
  } catch {
    return encodeURI(text);
  }
}

/** Join a path onto an endpoint without duplicating the version segment. */
export function joinEndpoint(endpoint, path) {
  const base = normaliseEndpoint(endpoint);
  const suffix = String(path ?? '').replace(/^\/+/, '');
  if (!base) return suffix;
  if (!suffix) return base;

  const baseVersion = base.match(/\/v\d+(?:beta)?$/i)?.[0]?.toLowerCase() ?? '';
  const pathVersion = suffix.match(/^v\d+(?:beta)?(?=\/|$)/i)?.[0]?.toLowerCase() ?? '';

  if (baseVersion && pathVersion && baseVersion === pathVersion) {
    return `${base}/${suffix.slice(pathVersion.length).replace(/^\/+/, '')}`;
  }
  return `${base}/${suffix}`;
}

export function isValidEndpoint(endpoint) {
  const text = normaliseEndpoint(endpoint);
  return Boolean(text) && text.length <= MAX_FIELD_LENGTH && ENDPOINT_PATTERN.test(text);
}

/** Strip control characters and angle brackets from a user-visible string. */
function safeText(value, limit = MAX_NAME_LENGTH) {
  const text = String(value ?? '')
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .replace(/[<>]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

/**
 * Decide whether the target app can be driven over the declared protocols.
 *
 * Returns a status plus a reason string. The reason is shown to the user
 * verbatim, so it must be explanatory rather than a code.
 */
export function evaluate({ app, protocols = [], baseUrl = '' }) {
  const required = APP_PROTOCOL_REQUIREMENTS[app];
  if (!required) {
    return {
      status: STATUS.UNKNOWN,
      reason: `未知的目标应用：${app}`,
      protocol: null,
      requiresConversion: false,
    };
  }

  if (!isValidEndpoint(baseUrl)) {
    return {
      status: STATUS.INVALID_ENDPOINT,
      reason: '来源没有提供可用的 Base URL，无法生成配置。',
      protocol: null,
      requiresConversion: false,
    };
  }

  const declared = protocols.filter((entry) => entry && entry !== 'unknown');

  if (declared.length === 0) {
    return {
      status: STATUS.UNKNOWN,
      reason: '来源未声明协议，无法判断该服务是否满足目标工具的调用路径。已标记为 unknown，不会生成可用的导入链接。',
      protocol: null,
      requiresConversion: false,
    };
  }

  const usable = declared.find((entry) => required.includes(entry));
  if (usable) {
    return {
      status: STATUS.READY_WITHOUT_KEY,
      reason: '',
      protocol: usable,
      requiresConversion: false,
    };
  }

  // Declared, but not the one this app speaks. Say which one it does speak
  // so the reader can pick a different target app rather than guessing.
  return {
    status: STATUS.UNSUPPORTED_PROTOCOL,
    reason: `来源声明的是 ${declared.map((p) => PROTOCOL_LABELS[p] ?? p).join('、')}，`
      + `而 ${APP_LABELS[app] ?? app} 需要 ${required.map((p) => PROTOCOL_LABELS[p] ?? p).join('、')}。`
      + '两者协议不同，直接导入不会生效，因此不生成导入链接。',
    protocol: declared[0] ?? null,
    requiresConversion: true,
  };
}

/**
 * Build the field list shown in the dialog.
 *
 * Field order matters: the reader fills them top to bottom, so identity
 * comes first, then the endpoint, then the model, then the key.
 */
export function buildFields({ providerName, app, baseUrl, modelId, homepage, notes }) {
  return [
    {
      key: 'name',
      label: 'Provider 名称',
      value: safeText(providerName),
      required: true,
      hint: '在 CC Switch 中显示的供应商名称',
      secret: false,
      copiable: true,
    },
    {
      key: 'app',
      label: '目标应用',
      value: app,
      required: true,
      hint: APP_LABELS[app] ?? app,
      secret: false,
      copiable: false,
    },
    {
      key: 'endpoint',
      label: 'Base URL',
      value: normaliseEndpoint(baseUrl),
      required: true,
      hint: 'API 端点地址；Radar 已检查 /v1 拼接规则，不会重复拼接',
      secret: false,
      copiable: true,
    },
    {
      key: 'model',
      label: '模型 ID',
      value: modelId ? safeText(modelId, 200) : null,
      required: false,
      hint: '精确的上游模型标识',
      secret: false,
      copiable: true,
    },
    {
      key: 'homepage',
      label: '供应商官网',
      value: homepage || null,
      required: false,
      hint: '可选',
      secret: false,
      copiable: true,
    },
    {
      key: 'notes',
      label: '备注',
      value: notes || null,
      required: false,
      hint: '可选；可以写清额度条件或注意事项',
      secret: false,
      copiable: true,
    },
    {
      key: 'apiKey',
      label: 'API Key',
      value: null,
      required: true,
      hint: '请在你自己的 CC Switch 中填写。Radar 不收集、不传输、不记录任何上游密钥。',
      secret: true,
      copiable: false,
    },
  ];
}

/**
 * Assemble the ccswitch:// deep link.
 *
 * Params are encoded with encodeURIComponent so a non-ASCII provider name
 * or a percent sign inside a URL round-trips. `apiKey` is deliberately
 * absent: the specification allows it, and putting a key in a URL is
 * exactly the leak the brief forbids.
 */
export function buildDeepLink({ app, providerName, baseUrl, modelId, homepage, notes }) {
  const params = new URLSearchParams();

  params.set('resource', 'provider');
  params.set('app', app);
  params.set('name', safeText(providerName));

  const endpoint = normaliseEndpoint(baseUrl);
  if (endpoint) params.set('endpoint', endpoint);

  if (modelId) params.set('model', safeText(modelId, 200));
  if (homepage) params.set('homepage', homepage);
  if (notes) params.set('notes', safeText(notes, 500));

  // Ask CC Switch to leave the entry enabled but keyless until the user
  // supplies a key, rather than importing a broken disabled entry.
  params.set('enabled', 'true');

  return `ccswitch://v${DEEP_LINK_VERSION.replace(/^v/, '')}/import?${params.toString()}`;
}

/**
 * Build everything the dialog needs for one provider/app/model combination.
 */
export function buildConfig(options) {
  const { providerName, app, baseUrl, modelId = null, homepage = null, protocols = [], notes = null, verified = false } = options;

  const verdict = evaluate({ app, protocols, baseUrl });
  const fields = buildFields({ providerName, app, baseUrl, modelId, homepage, notes });

  const warnings = [];
  if (verdict.status === STATUS.UNKNOWN) {
    warnings.push('来源未声明协议，无法判断该服务是否满足目标工具的调用路径。已标记为 unknown，不会生成可用的导入链接。');
  }
  if (verdict.status === STATUS.UNSUPPORTED_PROTOCOL) {
    warnings.push('该服务的协议与目标应用不匹配，Radar 不会生成导入链接，避免你导入一个注定不能用的配置。');
  }
  warnings.push('该配置未经过真实 API 调用验证。Radar 只确认字段格式与协议声明，不代表密钥有效或额度可用。');
  if (!verified) {
    warnings.push('该来源的官方域名尚未核对，请自行确认地址没有被第三方转手。');
  }

  const canLink = verdict.status === STATUS.READY_WITHOUT_KEY;

  return {
    providerName,
    app,
    appLabel: APP_LABELS[app] ?? app,
    baseUrl: normaliseEndpoint(baseUrl),
    modelId,
    protocols,
    status: verdict.status,
    reason: verdict.reason,
    requiresConversion: verdict.requiresConversion,
    protocol: verdict.protocol,
    protocolLabel: verdict.protocol ? PROTOCOL_LABELS[verdict.protocol] ?? verdict.protocol : null,
    fields,
    warnings,
    deepLink: canLink ? buildDeepLink({ app, providerName, baseUrl, modelId, homepage, notes }) : null,
    supportedVersion: SUPPORTED_VERSION,
    supportedCommit: SUPPORTED_COMMIT,
    radarExportLabel: 'Radar 数据交换文件（非 CC Switch 原生导入文件）',
  };
}

/** Plain-text rendering of every copiable field, for the copy-all action. */
export function fieldsToText(fields) {
  return fields
    .filter((field) => field.value !== null && field.value !== undefined && field.value !== '')
    .map((field) => `${field.label}：${field.value}`)
    .join('\n');
}

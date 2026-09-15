/**
 * vocab.js -- the display vocabulary, mirroring radar/vocab.py.
 *
 * This file is the single place where an internal enum value becomes a
 * Chinese label. Two rules are load-bearing and must not be relaxed:
 *
 *  1. Every tri-state enum has three distinct renderings. `unknown` never
 *     borrows the label, the colour, or the icon of `not_need`. An unknown
 *     protocol is not "unsupported"; an unknown credit-card requirement is
 *     not "no card needed".
 *  2. Unknown values render as unknown even when a shorter label would read
 *     better. Concision is never worth implying knowledge we do not have.
 */

/** Stable ordering for the protocol markers, matching the build. */
export const PROTOCOLS = [
  { key: 'openai_chat', short: 'Chat', full: 'Chat Completions（/v1/chat/completions）' },
  { key: 'openai_responses', short: 'Resp', full: 'Responses API（/v1/responses）' },
  { key: 'anthropic_messages', short: 'Anth', full: 'Anthropic Messages（/v1/messages）' },
  { key: 'gemini_native', short: 'Gem', full: 'Gemini 原生（generateContent）' },
];

export const OFFER_TYPES = {
  sustained_free_tier: { label: '持续免费额度', tone: 'ok' },
  recurring_free_quota: { label: '周期性免费额度', tone: 'ok' },
  trial_credit: { label: '限时试用额度', tone: 'warn' },
  one_time_credit: { label: '一次性赠金', tone: 'warn' },
  promotional: { label: '活动期免费', tone: 'warn' },
  community_endpoint: { label: '社区/公共端点', tone: 'info' },
  open_weights_hosted: { label: '开源权重托管', tone: 'info' },
  unknown: { label: '免费类型未知', tone: 'neutral' },
};

export const INFO_STATUS = {
  official_confirmed: { label: '官方已确认', tone: 'ok' },
  directory_claim: { label: '目录声明', tone: 'info' },
  conflicting: { label: '来源冲突', tone: 'warn' },
  rejected: { label: '已驳回', tone: 'danger' },
  unknown: { label: '未知', tone: 'neutral' },
};

export const CALL_STATUS = {
  untested: { label: '未做调用测试', tone: 'neutral' },
  reachable: { label: '可连通（仅一次探测）', tone: 'ok' },
  auth_required: { label: '需要密钥', tone: 'info' },
  unreachable: { label: '不可达', tone: 'danger' },
  unknown: { label: '未知', tone: 'neutral' },
};

export const TRI_STATE = {
  need: { label: '需要', tone: 'warn' },
  not_need: { label: '不需要', tone: 'ok' },
  unknown: { label: '未知', tone: 'neutral' },
};

export const QUOTA_UNITS = {
  tokens: 'tokens',
  requests: '次请求',
  credits: '额度点',
  usd: '美元',
  days: '天',
  rpm: '次/分钟',
  rpd: '次/天',
  tpm: 'tokens/分钟',
  unknown: '单位未知',
};

export const QUOTA_PERIODS = {
  per_minute: '每分钟',
  per_hour: '每小时',
  per_day: '每天',
  per_month: '每月',
  total: '总计',
  unknown: '周期未知',
};

export const CHANGE_TYPES = {
  initial_import: { label: '首次导入', tone: 'info' },
  field_changed: { label: '字段变化', tone: 'accent' },
  added: { label: '新增', tone: 'ok' },
  removed: { label: '移除', tone: 'neutral' },
  missing_from_source: { label: '来源已不再列出', tone: 'warn' },
  conflict_detected: { label: '发现来源冲突', tone: 'warn' },
  conflict_resolved: { label: '来源冲突已澄清', tone: 'ok' },
  staleness_changed: { label: '新鲜度变化', tone: 'neutral' },
  review_recorded: { label: '核验结果更新', tone: 'accent' },
};

export const CAPABILITIES = {
  text: '文本',
  vision: '图像理解',
  image: '图像生成',
  audio: '语音',
  video: '视频',
  reasoning: '推理',
  embedding: '向量',
  rerank: '重排',
  tool_calling: '工具调用',
  json_mode: 'JSON 模式',
};

export const SOURCE_LEVELS = {
  official: '官方文档',
  directory: '目录整理',
  community: '社区来源',
  unknown: '等级未知',
};

/** Look up a label, falling back to the raw value rather than guessing. */
export function label(map, key, fallback = '未知') {
  if (key === null || key === undefined) return fallback;
  return map[key]?.label ?? String(key);
}

export function tone(map, key) {
  return map[key]?.tone ?? 'neutral';
}

/**
 * Render a quota value plus its unit and period.
 *
 * Returns a plain-language string, and returns an explicit unknown string
 * rather than "0" when the value is missing. A missing quota must never be
 * displayed as zero -- that would read as "no free quota at all".
 */
export function quotaText(quota) {
  if (!quota) return '额度未知';

  const raw = (quota.raw || '').trim();
  const value = quota.value;
  const unit = QUOTA_UNITS[quota.unit] ?? quota.unit;
  const period = QUOTA_PERIODS[quota.period] ?? quota.period;

  if (value === null || value === undefined) {
    // The source said something, we just could not turn it into a number.
    return raw ? `${raw}（未解析为数值）` : '额度未知';
  }

  const parts = [`${formatNumber(value)} ${unit}`];
  if (quota.period && quota.period !== 'unknown' && quota.period !== 'total') {
    parts.push(period);
  } else if (quota.period === 'total') {
    parts.push('总计');
  }
  return parts.join(' / ');
}

export function formatNumber(value) {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Number.isInteger(number)) return number.toLocaleString('zh-CN');
  return number.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/**
 * Render a tri-state for a condition row.
 *
 * The `need`/`not_need`/`unknown` distinction is the reason this function
 * exists instead of a boolean: collapsing unknown into false is the single
 * most damaging inaccuracy the brief calls out.
 */
export function triStateText(value) {
  return TRI_STATE[value]?.label ?? '未知';
}

/** A condition row is only "good news" when it is explicitly not needed. */
export function conditionTone(value) {
  if (value === 'not_need') return 'ok';
  if (value === 'need') return 'warn';
  return 'neutral';
}

/**
 * toast.js -- the single polite status region.
 *
 * One element for the whole app, so two confirmations cannot be announced
 * on top of each other. Messages queue rather than replace: a user who
 * clicks two copy buttons in quick succession should see both.
 *
 * The region is aria-live="polite" (set in the template), which means a
 * screen reader finishes the current utterance before reading the message.
 * That is the right behaviour for confirmations. An error that needed
 * immediate attention would use the assertively-announced notice component
 * instead.
 */

const VISIBLE_MS = 2600;
const MAX_QUEUE = 4;

let element = null;
let queue = [];
let timer = null;
let showing = false;

function ensureElement() {
  if (element) return element;
  element = document.getElementById('radar-toast');
  return element;
}

function present(message) {
  const node = ensureElement();
  if (!node) return;

  showing = true;
  node.textContent = message.text;
  node.dataset.visible = 'true';
  node.dataset.tone = message.tone || 'neutral';

  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    node.dataset.visible = 'false';
    showing = false;
    // A short gap before the next message, so consecutive confirmations do
    // not read as one run-on sentence.
    window.setTimeout(drain, 160);
  }, message.duration ?? VISIBLE_MS);
}

function drain() {
  if (showing) return;
  const next = queue.shift();
  if (next) present(next);
}

export function showToast(message, { tone = 'neutral', duration } = {}) {
  const text = String(message ?? '').trim();
  if (!text) return;

  if (queue.length >= MAX_QUEUE) queue.shift();
  queue.push({ text, tone, duration });
  drain();
}

export function initToast() {
  // The element is created by toast.html; if a page omitted it, create one
  // so confirmations are never silently swallowed.
  if (!ensureElement()) {
    const node = document.createElement('div');
    node.id = 'radar-toast';
    node.className = 'toast';
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    node.dataset.visible = 'false';
    document.body.append(node);
    element = node;
  }

  document.addEventListener('radar:toast', (event) => {
    showToast(event.detail?.message, { tone: event.detail?.tone });
  });
}

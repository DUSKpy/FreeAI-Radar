/**
 * app.js -- the single entry point, loaded as a module on every page.
 *
 * Responsibilities, in order:
 *   1. apply the stored appearance preferences
 *   2. wire the shared chrome: toast, theme controls, favorites
 *   3. hydrate whatever page-specific module the current document needs
 *
 * Page detection reads the same `page` value the template used, but falls
 * back to a marker in the DOM (a data attribute on <main> or a known
 * element id) so a template change cannot silently disable a page.
 *
 * Every page module is imported dynamically and only when needed. The
 * overview page never downloads the directory filter engine, and the
 * directory page never downloads the comparison builder.
 */

import { getBootstrap } from './bootstrap.js';
import { initTheme } from './theme.js';
import { initFavorites } from './favorites.js';
import { hydrateMarkdownBlocks } from './markdown.js';
import { initToast } from './toast.js';

function detectPage() {
  const explicit = document.querySelector('[data-page]')?.dataset.page;
  if (explicit) return explicit;

  // Fallback detection by the presence of a page-defining element, so a
  // missing data-page attribute degrades instead of breaking.
  if (document.querySelector('[data-provider-root]')) return 'provider';
  if (document.querySelector('[data-facets-toggle]') || document.querySelector('#dir-facets')) return 'directory';
  if (document.querySelector('[data-favorites-root]')) return 'favorites';
  if (document.querySelector('[data-review-list]')) return 'reviews';
  if (document.querySelector('.notfound')) return 'notfound';
  if (document.querySelector('.report__body')) return 'changes';
  if (document.querySelector('.overview')) return 'overview';
  return 'unknown';
}

async function boot() {
  // 1. appearance first, so nothing re-renders twice
  initTheme();

  // 2. shared chrome
  initToast();
  initFavorites();

  // 3. markdown blocks may exist on any page (report prose, provider notes)
  hydrateMarkdownBlocks();

  const page = detectPage();
  document.documentElement.dataset.renderedPage = page;

  try {
    switch (page) {
      case 'directory': {
        const { initDirectory } = await import('./directory.js');
        initDirectory();
        break;
      }
      case 'provider': {
        const { initProvider } = await import('./provider.js');
        const { initCCSwitchDialog } = await import('./ccswitch-dialog.js');
        initProvider();
        initCCSwitchDialog();
        break;
      }
      case 'favorites': {
        const { initFavoritesPage } = await import('./favorites-page.js');
        initFavoritesPage();
        break;
      }
      case 'reviews': {
        const { initReviews } = await import('./reviews.js');
        initReviews();
        break;
      }
      case 'notfound': {
        const { initNotFound } = await import('./notfound.js');
        initNotFound();
        break;
      }
      case 'changes': {
        // Report prose is already hydrated above; nothing else is needed.
        break;
      }
      case 'overview':
      case 'sources':
      default: {
        break;
      }
    }
  } catch (error) {
    // A page module failing must not blank the whole document. Log it and
    // leave the server-rendered content in place.
    console.error(`[radar] 页面模块 "${page}" 初始化失败`, error);
    document.dispatchEvent(new CustomEvent('radar:toast', {
      detail: { message: '页面部分功能未能初始化，内容仍可阅读', tone: 'warn' },
    }));
  }

  const bootstrap = getBootstrap();
  if (bootstrap.noDataYet) {
    document.dispatchEvent(new CustomEvent('radar:toast', {
      detail: { message: '这个部署还没有完成过任何采集，页面内容为空是正常的', tone: 'warn' },
    }));
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}

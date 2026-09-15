/**
 * download.js -- trigger a client-side file download.
 *
 * Used by the favorites export and the review-queue export. Both are pure
 * client-side views over data the browser already has, so nothing is
 * uploaded and no endpoint is involved.
 *
 * The object URL is revoked on the next task rather than immediately: some
 * engines cancel an in-flight download if the URL is revoked in the same
 * tick as the click.
 */

export function downloadText(text, filename, mime = 'application/json') {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();

  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function exportJson(payload, filename) {
  downloadText(JSON.stringify(payload, null, 2), filename);
}

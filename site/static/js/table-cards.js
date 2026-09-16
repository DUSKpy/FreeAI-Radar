/**
 * table-cards.js -- label every table cell so the phone layout can show it.
 *
 * Why this exists
 * ---------------
 * On a phone the data tables become stacked cards (see responsive.css). A
 * card needs to say which field each value belongs to, and the only place
 * that information exists is the column header. CSS cannot read a header and
 * write it onto a cell, so it has to be copied into a `data-label` attribute
 * once, here.
 *
 * Why it runs on a MutationObserver rather than once at load
 * ----------------------------------------------------------
 * Three of the four tables on this site are filled in by JavaScript after
 * the page loads -- the model list, the sources list, the reviews list. A
 * one-shot pass at DOMContentLoaded would label nothing, because the rows do
 * not exist yet. Observing the tbody catches those renders and labels them as
 * they arrive, without each page module needing to know this exists.
 *
 * The observer is deliberately narrow: it watches for added rows only, not
 * for attribute or text changes, so a page that updates a cell in place (the
 * directory re-rendering a result count, say) cannot cause a loop.
 */

const LABELLED = 'data-label';

/** Copy each column header onto the cells beneath it. */
function labelTable(table) {
  const headerRow = table.querySelector('thead tr');
  if (!headerRow) return;

  // Read the header text once. A header cell may contain an icon or a
  // visually-hidden hint; only its rendered text is wanted.
  const labels = Array.from(headerRow.children).map((cell) =>
    (cell.textContent || '').trim().replace(/\s+/g, ' '),
  );

  for (const row of table.querySelectorAll('tbody tr')) {
    // A row header (`th scope="row"`) is the card title, not a field, and
    // gets no label. Cells are matched by position against the header.
    const cells = Array.from(row.children);
    cells.forEach((cell, index) => {
      if (cell.tagName === 'TH') {
        cell.removeAttribute(LABELLED);
        return;
      }
      const label = labels[index];
      if (label) {
        cell.setAttribute(LABELLED, label);
      }
    });
  }
}

/** Label every table currently in the document. */
export function labelAllTables(root = document) {
  for (const table of root.querySelectorAll('table.data')) {
    labelTable(table);
  }
}

/**
 * Start labelling now, and keep labelling as rows arrive.
 *
 * Returns a function that stops the observer, which the caller does not need
 * in normal use -- the observer lives for the life of the page.
 */
export function initTableCards() {
  labelAllTables();

  // Rows injected after load are the whole reason this module exists.
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        // A whole table may have been added, or a single row into an
        // existing one. Handle both by finding the nearest table.
        const table =
          node.tagName === 'TABLE' ? node : node.closest?.('table.data');
        if (table) {
          labelTable(table);
        } else if (node.tagName === 'TR') {
          const parent = node.closest('table.data');
          if (parent) labelTable(parent);
        }
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  return () => observer.disconnect();
}

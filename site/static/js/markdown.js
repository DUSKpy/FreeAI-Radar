/**
 * markdown.js -- a deliberately small Markdown renderer.
 *
 * Reports are produced by our own build job (radar/diff.py), but they embed
 * text captured from third-party sources. Rather than shipping a Markdown
 * library and then having to sanitise its HTML output, this module parses
 * to a DOM tree directly. The parser can only emit the tags it knows about,
 * so a `<script>` in an excerpt becomes visible text instead of executing.
 *
 * Supported, which is exactly what the generator emits:
 *   headings (# ## ###), paragraphs, unordered and ordered lists,
 *   fenced code blocks, inline code, bold, links, horizontal rules.
 *
 * Everything else is passed through as text.
 */

const INLINE_PATTERNS = [
  { re: /`([^`]+)`/g, tag: 'code' },
  { re: /\*\*([^*]+)\*\*/g, tag: 'strong' },
  { re: /\[([^\]]+)\]\(([^)\s]+)\)/g, tag: 'a' },
];

/** Split a line into text and inline-element nodes. */
function inlineNodes(text) {
  const nodes = [];
  let remaining = text;
  let guard = 0;

  while (remaining && guard < 200) {
    guard += 1;
    let best = null;

    for (const pattern of INLINE_PATTERNS) {
      pattern.re.lastIndex = 0;
      const match = pattern.re.exec(remaining);
      if (match && (best === null || match.index < best.index)) {
        best = { match, tag: pattern.tag };
      }
    }

    if (!best) break;

    if (best.match.index > 0) {
      nodes.push(document.createTextNode(remaining.slice(0, best.match.index)));
    }

    if (best.tag === 'a') {
      const href = best.match[2];
      // Only http(s) links become anchors. A javascript: or data: URI in a
      // scraped excerpt must not become a clickable element.
      if (/^https?:\/\//i.test(href)) {
        const anchor = document.createElement('a');
        anchor.href = href;
        anchor.rel = 'noopener noreferrer nofollow';
        anchor.target = '_blank';
        anchor.textContent = best.match[1];
        nodes.push(anchor);
      } else {
        nodes.push(document.createTextNode(best.match[0]));
      }
    } else {
      const node = document.createElement(best.tag);
      node.textContent = best.match[1];
      nodes.push(node);
    }

    remaining = remaining.slice(best.match.index + best.match[0].length);
  }

  if (remaining) nodes.push(document.createTextNode(remaining));
  return nodes;
}

function paragraph(text) {
  const p = document.createElement('p');
  p.append(...inlineNodes(text));
  return p;
}

/**
 * Render Markdown into a DocumentFragment.
 *
 * Never returns a string, so there is no point at which untrusted text
 * passes through an HTML parser.
 */
export function renderMarkdown(source) {
  const fragment = document.createDocumentFragment();
  const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n');

  let index = 0;
  let listStack = null; // { node, ordered }

  const closeList = () => {
    if (listStack) {
      fragment.append(listStack.node);
      listStack = null;
    }
  };

  while (index < lines.length) {
    const line = lines[index];

    // Fenced code block.
    if (/^```/.test(line.trim())) {
      closeList();
      const buffer = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        buffer.push(lines[index]);
        index += 1;
      }
      index += 1;

      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = buffer.join('\n');
      pre.append(code);
      fragment.append(pre);
      continue;
    }

    // Heading.
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = Math.min(Math.max(heading[1].length, 2), 3); // h1 is the page title
      const node = document.createElement(`h${level}`);
      node.append(...inlineNodes(heading[2].trim()));
      fragment.append(node);
      index += 1;
      continue;
    }

    // Horizontal rule.
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      closeList();
      fragment.append(document.createElement('hr'));
      index += 1;
      continue;
    }

    // List item.
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      if (!listStack || listStack.ordered !== ordered) {
        closeList();
        const node = document.createElement(ordered ? 'ol' : 'ul');
        listStack = { node, ordered };
      }
      const li = document.createElement('li');
      li.append(...inlineNodes((bullet?.[1] ?? numbered?.[1]).trim()));
      listStack.node.append(li);
      index += 1;
      continue;
    }

    // Blank line: closes the current list.
    if (!line.trim()) {
      closeList();
      index += 1;
      continue;
    }

    // Plain paragraph, absorbing continuation lines.
    closeList();
    const buffer = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim()
      && !/^(#{1,6}\s|```|\s*[-*+]\s|\s*\d+[.)]\s)/.test(lines[index])
      && !/^\s*([-*_])\1{2,}\s*$/.test(lines[index])) {
      buffer.push(lines[index].trim());
      index += 1;
    }
    fragment.append(paragraph(buffer.join(' ')));
  }

  closeList();
  return fragment;
}

/**
 * Replace every [data-markdown] block with its rendered form.
 *
 * The raw text is carried in a hidden <pre> so the page is still readable
 * without JS, and the network is not hit again for content the server
 * already had.
 */
export function hydrateMarkdownBlocks(root = document) {
  for (const block of root.querySelectorAll('[data-markdown]')) {
    const source = block.querySelector('pre')?.textContent;
    if (!source) continue;

    block.replaceChildren(renderMarkdown(source));
  }
}

"""HTML parsing helpers built on BeautifulSoup + lxml.

Used for two things:

1. official documentation pages, where we extract short excerpts and any
   numeric limit tables that happen to be present
2. static HTML directories, as a fallback behind the Markdown adapters

The output is always plain text or structured rows. Markup is stripped at the
boundary so that nothing scraped can reach the rendered site as HTML.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from ..textutil import collapse, squash, strip_markup

#: Elements that never contain useful facts but do contain noise.
_DROP_SELECTORS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
    "template",
    "picture",
    "video",
    "audio",
)

#: Class/id fragments that mark promotional or navigational chrome.
_NOISE_PATTERNS = (
    "cookie",
    "consent",
    "banner",
    "promo",
    "advert",
    "sponsor",
    "newsletter",
    "subscribe",
    "social",
    "share",
    "breadcrumb",
    "pagination",
    "sidebar",
    "menu",
    "toolbar",
    "gdpr",
    "privacy-choice",
    "skip-link",
    "announcement",
)

#: Attributes whose *whole value* may be matched loosely (substring).
#:
#: ``id`` and ``aria-label`` are written by people as prose-ish identifiers, so
#: a substring test is a reasonable read of intent: ``id="site-sidebar"`` is a
#: sidebar. They are safe to match loosely because they are short and authored
#: deliberately.
_LOOSE_MATCH_ATTRS = ("id", "aria-label", "data-testid", "role")


@dataclass
class HtmlTable:
    caption: str | None
    headers: list[str]
    rows: list[list[str]]
    links: list[list[str]] = field(default_factory=list)


@dataclass
class HtmlDocument:
    title: str
    text: str
    tables: list[HtmlTable] = field(default_factory=list)
    main_text: str = ""
    canonical_url: str | None = None


def parse_html(document: str) -> HtmlDocument:
    """Parse a page into clean text plus any data tables."""
    soup = BeautifulSoup(document, "lxml")

    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href") if isinstance(canonical, Tag) else None

    for selector in _DROP_SELECTORS:
        for node in soup.find_all(selector):
            node.decompose()

    title = squash(soup.title.get_text(" ")) if soup.title else ""

    main = _find_main(soup)
    _strip_noise(main)

    text = collapse(main.get_text("\n"))
    return HtmlDocument(
        title=title,
        text=text,
        main_text=text,
        tables=_extract_tables(main),
        canonical_url=canonical_url,
    )


def _find_main(soup: BeautifulSoup) -> Tag:
    """Prefer the main content container over the whole page."""
    for selector in ("main", "[role=main]", "article", "#content", ".content", "#main"):
        node = soup.select_one(selector)
        if isinstance(node, Tag) and len(node.get_text(strip=True)) > 200:
            return node
    body = soup.body
    return body if isinstance(body, Tag) else soup


def _class_tokens(class_value: object) -> list[str]:
    """Split a ``class`` attribute into whole tokens, discarding CSS internals.

    This exists because a plain substring test over the raw class string is
    actively dangerous on modern utility-CSS sites. Observed in the wild:

        class="flex w-full pt-[calc(10rem+var(--banner-height,2.5rem))] lg:pt-10"

    The substring ``banner`` appears inside an arbitrary-value utility, and the
    element carrying it held the entire article body. A substring test deleted
    5107 characters of real content and the page was reported as unparseable.

    So: split on whitespace, and only consider the leading token name before any
    ``:``/``[``/``/`` modifier, lowercased. ``banner`` in a class therefore has
    to be an actual class named ``banner`` (or ``banner-*``), never a fragment
    of a bracketed arbitrary value.
    """
    if not class_value:
        return []
    if isinstance(class_value, str):
        raw = class_value.split()
    elif isinstance(class_value, (list, tuple)):
        raw = [str(part) for item in class_value for part in str(item).split()]
    else:
        return []

    tokens: list[str] = []
    for item in raw:
        # Drop any utility modifier/suffix: `md:flex`, `pt-[calc(...)]`,
        # `hover:bg-red-500/50` all reduce to their base name.
        head = item.split(":", 1)[-1]
        head = head.split("[", 1)[0]
        head = head.split("/", 1)[0]
        # A trailing modifier separator can survive the splits above
        # (`pt-[calc(...)]` -> `pt-`). Trim it so tokens are plain names.
        head = head.strip().strip("-").lower()
        if not head:
            continue
        tokens.append(head)
        # Also offer the first hyphen-delimited word so that `banner-ad` still
        # matches the `banner` pattern.
        if "-" in head:
            tokens.append(head.split("-", 1)[0])
    return tokens


def _is_noise(node: Tag) -> bool:
    """True when a node is identifiable as chrome rather than content."""
    # Class names are matched token-wise: a class is only noise if the token
    # *equals* (or begins with) a known noise word. Substrings inside bracketed
    # utility values must never count.
    for token in _class_tokens(node.get("class")):
        if any(token == pattern or token.startswith(f"{pattern}-") for pattern in _NOISE_PATTERNS):
            return True

    # Authored attributes may still be matched loosely.
    for attr in _LOOSE_MATCH_ATTRS:
        value = node.get(attr)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(v) for v in value)
        if not isinstance(value, str) or not value:
            continue
        lowered = value.lower()
        if any(pattern in lowered for pattern in _NOISE_PATTERNS):
            return True
    return False


def _strip_noise(root: Tag) -> None:
    """Remove promotional, navigational and consent chrome.

    This is what the task book means by cleaning ads, footers, navigation and
    promotional link parameters before anything is stored.

    A deliberate safety rule: never decompose a node that holds most of the
    document's text. If a match would remove the bulk of the content, the match
    is wrong, and keeping slightly too much is far better than publishing an
    empty page.
    """
    total_text = len(root.get_text(strip=True))
    # A single node holding this share of the text is content, not chrome.
    protected_share = 0.5

    for node in list(root.find_all(True)):
        if node.parent is None:  # already decomposed via an ancestor
            continue
        if not _is_noise(node):
            continue
        node_text = len(node.get_text(strip=True))
        if total_text and node_text / total_text >= protected_share:
            # Refuse to delete what is evidently the page body. The class/id
            # matched a noise word, but the size says it is the content.
            continue
        node.decompose()

    for node in list(root.find_all("a")):
        if node.parent is None:
            continue
        if not node.get_text(strip=True) and not node.find("img"):
            node.decompose()


def _extract_tables(root: Tag) -> list[HtmlTable]:
    """Convert every ``<table>`` into headers plus text rows.

    Header cells are taken from ``<thead>`` when present, otherwise from the
    first row that contains ``<th>``. Column lookup downstream is by header
    text, so column order may change freely.
    """
    tables: list[HtmlTable] = []
    for element in root.find_all("table"):
        headers = _headers_for(element)
        rows: list[list[str]] = []
        links: list[list[str]] = []

        body_rows = element.find_all("tr")
        for row in body_rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            values = [collapse(cell.get_text(" ")) for cell in cells]
            if _looks_like_header(values) and not rows:
                continue
            if not any(value for value in values):
                continue
            rows.append(values)
            links.append(
                [anchor.get("href") or "" for cell in cells for anchor in cell.find_all("a")]
            )

        if headers and rows:
            tables.append(
                HtmlTable(caption=_caption_for(element), headers=headers, rows=rows, links=links)
            )
    return tables


def _headers_for(table: Tag) -> list[str]:
    head = table.find("thead")
    if isinstance(head, Tag):
        row = head.find("tr")
        if isinstance(row, Tag):
            cells = [collapse(cell.get_text(" ")) for cell in row.find_all(["th", "td"])]
            if any(cells):
                return cells
    first = table.find("tr")
    if isinstance(first, Tag):
        header_cells = first.find_all("th")
        if header_cells:
            return [collapse(cell.get_text(" ")) for cell in header_cells]
    return []


def _caption_for(table: Tag) -> str | None:
    caption = table.find("caption")
    if isinstance(caption, Tag):
        text = squash(caption.get_text(" "))
        if text:
            return text
    return None


def _looks_like_header(values: Iterable[str]) -> bool:
    joined = " ".join(values).lower()
    return bool(
        re.search(r"\b(provider|model|credit card|rate limit|base url|api key|context)\b", joined)
    )


def extract_evidence(text: str, keywords: Iterable[str], *, window: int = 220) -> list[str]:
    """Short excerpts around keyword hits.

    The task book requires only necessary short excerpts, never a full page.
    Each hit is capped at ``window`` characters and de-duplicated.
    """
    found: list[str] = []
    haystack = collapse(text)
    for keyword in keywords:
        for match in re.finditer(re.escape(keyword), haystack, re.IGNORECASE):
            start = max(0, match.start() - window // 2)
            end = min(len(haystack), match.end() + window // 2)
            excerpt = squash(haystack[start:end])
            if excerpt and excerpt not in found:
                found.append(excerpt[:400])
            if len(found) >= 6:
                return found
    return found


def text_blocks(text: str, *, min_length: int = 40) -> list[str]:
    """Paragraph-ish blocks, used to locate limit statements in prose."""
    blocks: list[str] = []
    for raw in re.split(r"\n{2,}", text or ""):
        block = squash(raw)
        if len(block) >= min_length:
            blocks.append(block)
    return blocks


def html_tables_to_markdown_tables(tables: list[HtmlTable]) -> list[dict[str, object]]:
    """Flatten HTML tables into the same shape the Markdown parser produces."""
    flattened: list[dict[str, object]] = []
    for table in tables:
        flattened.append(
            {
                "caption": table.caption,
                "headers": [strip_markup(header) for header in table.headers],
                "rows": [[strip_markup(cell) for cell in row] for row in table.rows],
                "links": table.links,
            }
        )
    return flattened

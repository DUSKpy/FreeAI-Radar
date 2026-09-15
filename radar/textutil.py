"""Text normalisation shared by the Markdown and HTML parsers.

Everything fetched from the network goes through here before it reaches a
model. Markup is never carried into stored evidence, and the helpers are
deliberately small so their behaviour is easy to test.
"""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_MD_CODE = re.compile(r"`([^`]*)`")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(?=\S)(.*?)(?<=\S)\1", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ANCHOR = re.compile(
    r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)
_WS = re.compile(r"[ \t\u00a0\u2007\u202f]+")
_BLANKS = re.compile(r"\n{3,}")

#: Values that mean "the source declined to answer", not "FALSE" or "0".
NULL_LIKE = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "–",
        "n/a",
        "na",
        "n.a.",
        "unknown",
        "none",
        "null",
        "nil",
        "?",
        "tbd",
        "tba",
        "not stated",
        "not specified",
        "not published",
        "not listed",
        "see provider",
        "varies",
        "unspecified",
    }
)


def is_null_like(value: str | None) -> bool:
    return (value or "").strip().lower() in NULL_LIKE


def unescape(text: str) -> str:
    return html.unescape(text or "")


def strip_markup(text: str | None) -> str:
    """Reduce a Markdown/HTML cell to plain readable text.

    Links collapse to their label. Images collapse to their alt text. HTML
    anchors are unwrapped before the generic tag strip so that evidence never
    contains markup.
    """
    if not text:
        return ""
    blob = unescape(text)
    blob = _MD_IMAGE.sub(lambda m: m.group(1), blob)
    blob = _MD_LINK.sub(lambda m: m.group(1), blob)
    blob = _HTML_ANCHOR.sub(lambda m: m.group(2), blob)
    blob = _MD_CODE.sub(lambda m: m.group(1), blob)
    blob = _MD_HEADING.sub("", blob)
    blob = _MD_HTML_TAG.sub(" ", blob)
    blob = _MD_EMPHASIS.sub(lambda m: m.group(2), blob)
    blob = blob.replace("\\|", "|").replace("\\*", "*").replace("\\_", "_")
    return collapse(blob)


def collapse(text: str) -> str:
    """Collapse runs of whitespace. Keeps paragraphs readable."""
    return _WS.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def squash(text: str) -> str:
    """Collapse all whitespace including newlines into single spaces."""
    return " ".join((text or "").split())


def cell_text(cell: str | None) -> str:
    """Canonical form for a table cell.

    Null-like values become an empty string so callers can treat them as
    "unknown" without special-casing every dash variant.
    """
    if cell is None:
        return ""
    text = strip_markup(cell)
    if is_null_like(text):
        return ""
    return text


def first_url(text: str | None) -> str | None:
    """First URL in a Markdown cell, HTML anchor or bare text."""
    if not text:
        return None
    for match in _MD_LINK.finditer(text):
        candidate = match.group(2).strip().strip("<>")
        if candidate.startswith(("http://", "https://")):
            return candidate
    for match in _HTML_ANCHOR.finditer(text):
        candidate = unescape(match.group(1)).strip()
        if candidate.startswith(("http://", "https://")):
            return candidate
    for match in re.finditer(r"https?://[^\s<>\)\]\"']+", text):
        return match.group(0).rstrip(".,;:")
    return None


def all_urls(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for pattern in (_MD_LINK, _HTML_ANCHOR):
        for match in pattern.finditer(text):
            candidate = (match.group(2) if pattern is _MD_LINK else match.group(1)).strip()
            candidate = unescape(candidate).strip("<>")
            if candidate.startswith(("http://", "https://")) and candidate not in found:
                found.append(candidate)
    for match in re.finditer(r"https?://[^\s<>\)\]\"']+", text):
        candidate = match.group(0).rstrip(".,;:")
        if candidate not in found:
            found.append(candidate)
    return found


def normalise_header(header: str) -> str:
    """Fold a column header to a comparison key.

    ``Credit Card?`` -> ``creditcard``; ``Free Models`` -> ``freemodels``.
    Punctuation and case are removed so that alias matching survives the
    cosmetic drift these READMEs go through.
    """
    text = unicodedata.normalize("NFKD", strip_markup(header)).casefold()
    text = re.sub(r"\(.*?\)", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def normalise_model_id(value: str | None) -> str:
    """Canonical upstream model identifier.

    Wrapping backticks, surrounding quotes and leading/trailing dots are
    removed. Case is preserved because model ids are case-sensitive.
    """
    text = strip_markup(value)
    text = text.strip().strip("`'\"")
    text = re.sub(r"^[\s.:,;]+|[\s.:,;]+$", "", text)
    return text


def normalise_host(url: str | None) -> str | None:
    """Registrable-ish host, lowercased, without ``www.``."""
    if not url:
        return None
    host = urlsplit(url).hostname
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def same_site(left: str | None, right: str | None) -> bool:
    """Whether two hosts belong to the same registrable site.

    Used to decide whether a provider homepage matches its official domain.
    Only the last two labels are compared, which is adequate for the domains in
    scope and deliberately conservative (it will under-match rather than
    over-match).
    """
    left_host = normalise_host(left)
    right_host = normalise_host(right)
    if not left_host or not right_host:
        return False
    return (
        left_host == right_host
        or left_host.endswith("." + right_host)
        or right_host.endswith("." + left_host)
    )


def resolve_url(base: str, target: str | None) -> str | None:
    """Resolve a possibly relative href against the page it appeared on.

    Dangerous schemes are rejected outright so that a scraped ``javascript:``
    href can never reach an anchor in the rendered site.
    """
    if not target:
        return None
    text = target.strip()
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith(("javascript:", "data:", "mailto:", "#", "file:", "ftp:", "blob:")):
        return None
    if not base:
        return None
    resolved = urljoin(base, text)
    if not resolved.startswith(("http://", "https://")):
        return None
    return resolved


def truncate(text: str, limit: int = 400) -> str:
    text = squash(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

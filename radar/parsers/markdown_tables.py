"""Markdown table parsing helpers.

Source READMEs are hand-maintained documents, not data files. The helpers here
absorb the messiness the task book calls out:

* column order changes -- matched by field alias, never by index
* optional ``<!--SENTINEL-->`` blocks mark the tables we care about
* multi-row tables where the provider cell is blank on continuation rows
* cells that mix prose, Markdown links and HTML anchors
* numeric limits embedded in free text such as ``30 RPM, 250 RPD``

No single giant regex is used. Each source defines its own alias set, and the
generic parser only supplies the mechanics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from ..textutil import (
    cell_text,
    first_url,
    normalise_header,
    strip_markup,
)

_SEPARATOR_ROW = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_SENTINEL = re.compile(r"<!--\s*([A-Z0-9_:.-]+)\s*-->")


@dataclass
class Table:
    """One parsed Markdown table with its header and rows."""

    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None
    sentinel: str | None = None
    #: Detected column that acts as the row's identity (the provider column).
    key_column: int = 0

    def column(self, *aliases: str) -> int | None:
        """Index of the first header matching any alias.

        Matching is done on a normalized form so that ``Credit Card?``,
        ``credit_card`` and ``creditcard`` are equivalent.
        """
        wanted = {normalise_header(alias) for alias in aliases}
        for index, header in enumerate(self.headers):
            if normalise_header(header) in wanted:
                return index
        # Second pass: substring match, so "Daily Limit" still finds
        # "Daily Limit (USD)" as columns drift over time.
        for index, header in enumerate(self.headers):
            normalized = normalise_header(header)
            if any(alias in normalized for alias in wanted if len(alias) > 4):
                return index
        return None

    def value(self, row: list[str], *aliases: str) -> str | None:
        index = self.column(*aliases)
        if index is None or index >= len(row):
            return None
        return cell_text(row[index])

    def carry_forward(self, index: int) -> list[list[str]]:
        """Fill a blank identity cell from the row above.

        The awesome-freellm-apis "Best Free Models" table lists several models
        per provider with the provider cell left empty on continuation rows.
        """
        previous: str | None = None
        filled: list[list[str]] = []
        for row in self.rows:
            if index < len(row):
                candidate = cell_text(row[index])
                if candidate:
                    previous = row[index]
                elif previous is not None:
                    patched = list(row)
                    patched[index] = previous
                    filled.append(patched)
                    continue
            filled.append(list(row))
        return filled


def parse_tables(
    markdown: str,
    *,
    limited_to_sentinels: Iterable[str] | None = None,
) -> list[Table]:
    """Extract every Markdown table from a document.

    ``limited_to_sentinels`` restricts the result to tables found between a
    matching ``<!--START-->`` sentinel and its ``END`` partner.
    """
    lines = markdown.splitlines()
    wanted = {s.upper() for s in limited_to_sentinels} if limited_to_sentinels else None

    tables: list[Table] = []
    active_sentinel: str | None = None
    pending_sentinel: str | None = None
    heading: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        for match in _SENTINEL.finditer(line):
            token = match.group(1).upper()
            if token.endswith("START") or token.endswith("BEGIN"):
                pending_sentinel = token
                active_sentinel = None
            elif token.endswith("END"):
                pending_sentinel = None
                active_sentinel = None

        if line.lstrip().startswith("#"):
            heading = strip_markup(line.lstrip("#").strip()) or heading

        if line.strip().startswith("|") and index + 1 < len(lines):
            if _looks_like_separator(lines[index + 1]):
                table_lines = [line]
                cursor = index + 1
                while cursor < len(lines) and lines[cursor].strip().startswith("|"):
                    table_lines.append(lines[cursor])
                    cursor += 1

                if (pending_sentinel and pending_sentinel.endswith("START")) or (
                    pending_sentinel and pending_sentinel.endswith("BEGIN")
                ):
                    active_sentinel = pending_sentinel

                keep = True
                if wanted is not None:
                    keep = bool(active_sentinel) and any(
                        active_sentinel.startswith(name) for name in wanted
                    )
                if keep:
                    table = _build_table(table_lines, heading, active_sentinel)
                    if table is not None:
                        tables.append(table)

                if active_sentinel and active_sentinel.endswith("START"):
                    active_sentinel = None
                index = cursor
                continue

        index += 1

    return tables


def _looks_like_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return bool(_SEPARATOR_ROW.match(stripped)) and "-" in stripped


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    # Split on unescaped pipes so "\|" inside a cell survives.
    parts = re.split(r"(?<!\\)\|", text)
    return [part.replace("\\|", "|") for part in parts]


def _build_table(table_lines: list[str], heading: str | None, sentinel: str | None) -> Table | None:
    if len(table_lines) < 3:
        return None
    headers = [
        strip_markup(_split_row(table_lines[0])[i]) if i < len(_split_row(table_lines[0])) else ""
        for i in range(len(_split_row(table_lines[0])))
    ]
    headers = list(headers)
    body = [_split_row(line) for line in table_lines[2:] if line.strip()]
    rows = [row for row in body if any(cell_text(cell) for cell in row)]
    if not headers or not rows:
        return None
    return Table(headers=headers, rows=rows, caption=heading, sentinel=sentinel)


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

_RPM = re.compile(r"([\d.,]+)\s*(?:k\b)?\s*rpm\b", re.IGNORECASE)
_RPD = re.compile(r"([\d.,]+)\s*(?:k\b)?\s*rpd\b", re.IGNORECASE)
_TPM = re.compile(r"([\d.,]+)\s*(?:k|m|million|billion)?\s*tpm\b", re.IGNORECASE)
_TPD = re.compile(r"([\d.,]+)\s*(?:k|m|million|billion)?\s*tpd\b", re.IGNORECASE)
_RPS = re.compile(r"([\d.,]+)\s*(?:k\b)?\s*(?:rps|request(?:s)?\s*/\s*second)\b", re.IGNORECASE)
_NUM = re.compile(r"(-?\d[\d,]*\.?\d*)")
_MULTIPLIER = re.compile(r"([\d.,]+)\s*([kKmM])\b")


def _to_number(text: str) -> float | None:
    cleaned = (text or "").replace(",", "").replace("_", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_rate_limits(text: str) -> list[dict[str, object]]:
    """Pull numeric limits out of free text such as ``30 RPM, 250 RPD``.

    Only explicit numbers are returned. ``Not published`` and ``See provider``
    produce nothing at all rather than a zero.
    """
    limits: list[dict[str, object]] = []
    seen: set[tuple[str, float]] = set()
    blob = text or ""

    def add(metric: str, value: float | None, period: str) -> None:
        if value is None:
            return
        marker = (metric, value)
        if marker in seen:
            return
        seen.add(marker)
        limits.append({"metric": metric, "value": value, "period": period})

    for pattern, metric, period in (
        (_RPM, "rpm", "per_minute"),
        (_RPD, "rpd", "per_day"),
        (_TPM, "tpm", "per_minute"),
        (_TPD, "tpd", "per_day"),
        (_RPS, "rps", "per_second"),
    ):
        for match in pattern.finditer(blob):
            add(metric, _scaled(match), period)

    return limits


def _scaled(match: re.Match[str]) -> float | None:
    """Read a number, honouring a ``k``/``M`` suffix that sits after it."""
    tail = match.group(0)
    value = _to_number(match.group(1))
    if value is None:
        return None
    suffix = re.search(r"([kKmM])\b", tail)
    if suffix:
        factor = 1000 if suffix.group(1).lower() == "k" else 1_000_000
        value *= factor
    return value


def first_number(text: str) -> float | None:
    match = _NUM.search(text or "")
    return _to_number(match.group(1)) if match else None


def extract_context_window(text: str) -> int | None:
    """Context windows are written as ``1M``, ``262K``, ``128,000`` or ``-``."""
    blob = (text or "").strip()
    if not blob or blob in {"-", "—", "n/a", "N/A", "unknown", "Not published", "See provider"}:
        return None
    multiplier = _MULTIPLIER.search(blob)
    if multiplier:
        base = _to_number(multiplier.group(1))
        if base is None:
            return None
        factor = 1000 if multiplier.group(2).lower() == "k" else 1_000_000
        return int(base * factor)
    plain = _NUM.search(blob)
    if not plain:
        return None
    value = _to_number(plain.group(1))
    if value is None or value <= 0:
        return None
    # Reject values that are clearly not token counts (e.g. a stray year).
    return int(value) if value >= 512 else None


_TRI_NEED = re.compile(
    r"\b(yes|required|needed|require[sd]?|must|phone\s*verification|registration|sign[- ]?up|card\s*on\s*file)\b",
    re.IGNORECASE,
)
_TRI_NOT_NEED = re.compile(
    r"\b(no|not required|none|no card|without|free of charge|nothing)\b", re.IGNORECASE
)
_TRI_UNKNOWN = re.compile(
    r"^\s*(-|—|n/?a|unknown|unclear|not (?:published|stated|specified|listed)|see provider|varies)\s*$",
    re.IGNORECASE,
)


def tri_state(text: str | None) -> str:
    """Map a condition cell onto need / not_need / unknown.

    A blank cell, a dash or "not published" is **unknown**, never ``not_need``.
    The task book forbids reading an omission as a negative.
    """
    blob = cell_text(text)
    if not blob or _TRI_UNKNOWN.match(blob):
        return "unknown"
    if _TRI_NOT_NEED.search(blob) and not _TRI_NEED.search(blob):
        return "not_need"
    if _TRI_NEED.search(blob):
        return "need"
    return "unknown"


_MODALITY_VOCAB = {
    "audio": "audio",
    "speech": "audio",
    "code": "coding",
    "coding": "coding",
    "embedding": "embedding",
    "embeddings": "embedding",
    "image": "image",
    "vision": "vision",
    "pdf": "pdf",
    "reasoning": "reasoning",
    "rerank": "rerank",
    "text": "text",
    "video": "video",
}


def extract_capabilities(text: str) -> list[str]:
    """Capability tags strictly as declared by the source.

    Nothing is inferred from a model name. An empty list means "the source did
    not say", which the record stores as ``capabilities_unknown = True``.
    """
    blob = (text or "").lower()
    found: list[str] = []
    for token in re.split(r"[,;/|\s]+", blob):
        mapped = _MODALITY_VOCAB.get(token.strip())
        if mapped and mapped not in found:
            found.append(mapped)
    return found


_NOT_PUBLISHED = re.compile(
    r"^\s*(-|—|n/?a|unknown|not published|not fully published|see provider|"
    r"unspecified|varies|dashboard[- ]only|dynamic|credit[- ]based|fair use)\b",
    re.IGNORECASE,
)


def is_not_published(text: str | None) -> bool:
    """True for cells that explicitly decline to state a value."""
    blob = cell_text(text)
    if not blob:
        return True
    return bool(_NOT_PUBLISHED.match(blob))


def link_and_text(cell: str) -> tuple[str | None, str]:
    """Return the first URL in a cell plus the human-readable text."""
    return first_url(cell), strip_markup(cell)


@dataclass
class Provenance:
    """Where a parsed field came from, used to build evidence excerpts."""

    source_id: str
    source_record_url: str
    observed_at: str
    source_level: str = "directory"
    source_family: str | None = None
    rows_parsed: int = 0
    warnings: list[str] = field(default_factory=list)

    def excerpt(self, *parts: str) -> str:
        joined = " | ".join(part for part in parts if part)
        return " ".join(joined.split())[:400]


def iter_rows_with_key(table: Table) -> Iterator[list[str]]:
    """Yield rows with the identity column carried forward."""
    return iter(table.carry_forward(table.key_column))

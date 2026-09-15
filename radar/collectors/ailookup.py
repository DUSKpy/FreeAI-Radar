"""Adapter 3 -- AILookup/free-llm-resources (per-provider prose sections).

Third real source with a third structure: no sentinel tables, no unified
schema. Each provider gets its own ``## Heading`` section with a prose line
describing the access path, a "Last verified" date, and one or more
provider-specific tables of numeric limits.

LICENCE CAUTION
---------------
As of first check this repository publishes **no LICENSE file**. The task book
requires that, absent a licence, no large content is copied and nothing is
mirrored. This adapter therefore extracts *facts only*:

* provider display name
* numeric rate-limit rows that are already tabular
* the "Last verified" date and the access-requirement prose line

It never stores prose paragraphs, never stores the provider's own commentary,
and never mirrors the file. ``config/sources.yaml`` keeps the source disabled
by default so a maintainer opts in only after the licence question is settled.
"""

from __future__ import annotations

import re

from ..ids import slugify
from ..models import CandidateRecord
from ..parsers.markdown_tables import (
    Table,
    extract_rate_limits,
    first_url,
    parse_tables,
    tri_state,
)
from ..textutil import cell_text, normalise_model_id, squash
from ..vocab import AccessType, OfferType, QuotaPeriod, QuotaUnit
from .base import BaseAdapter, ParseResult, register

_LAST_VERIFIED = re.compile(r"Last verified:\s*\*{0,2}([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE)
_ACCESS_LINE = re.compile(r"^(.*?)(?:·|\|)\s*OpenAI SDK compatible\s*(?:·|\|)?(.*)$", re.IGNORECASE)
_NO_SDK = re.compile(r"OpenAI SDK", re.IGNORECASE)

#: Sections that are not providers and must be skipped.
_SKIP_SECTIONS = frozenset(
    {
        "quick comparison",
        "search, crawl, and extraction apis",
        "trial credits and recurring tiny credits",
        "self-hosted",
        "terms",
        "selection rules",
        "tavily",
        "exa",
        "firecrawl",
    }
)

#: Table headers that indicate a per-model limit matrix.
_MODEL_LIMIT_HEADERS = ("model", "rpm", "rpd", "tpm", "tpd")


@register
class AilookupMarkdownAdapter(BaseAdapter):
    name = "ailookup_markdown"
    version = "1.0.0"

    def parse(self, document: str, *, observed_at: str) -> ParseResult:
        result = ParseResult()
        prov = self.provenance(observed_at)

        sections = _split_sections(document)
        if not sections:
            result.structure_ok = False
            result.warnings.append("no level-2 sections found")
            return result

        tables_by_section = _tables_by_section(document)

        for heading, body in sections:
            key = slugify(heading)
            if heading.lower().strip() in _SKIP_SECTIONS:
                continue
            if key in {"", "unknown"}:
                continue

            verified = None
            match = _LAST_VERIFIED.search(body)
            if match:
                verified = match.group(1)

            access_note = _access_requirement(body)
            fact_url = first_url(body)

            section_tables = tables_by_section.get(heading, [])
            model_rows: list[tuple[str, list[dict[str, object]]]] = []
            flat_limits: list[dict[str, object]] = []

            for table in section_tables:
                headers_lower = " ".join(table.headers or []).lower()
                if "model" in headers_lower and any(
                    metric in headers_lower for metric in ("rpm", "rpd", "tpm", "tpd")
                ):
                    for row in table.rows:
                        model_name = normalise_model_id(cell_text(row[0]))
                        if not model_name:
                            continue
                        limits = []
                        for column in table.headers[1:]:
                            index = table.headers.index(column)
                            if index >= len(row):
                                continue
                            cell = cell_text(row[index])
                            if not cell:
                                continue
                            metric = _metric_from_header(column)
                            if metric is None:
                                continue
                            from ..parsers.markdown_tables import first_number

                            number = first_number(cell)
                            if number is None:
                                continue
                            limits.append(
                                {
                                    "metric": metric,
                                    "value": number,
                                    "period": _period_for(metric),
                                }
                            )
                        model_rows.append((model_name, limits))
                        flat_limits.extend(limits)
                else:
                    # A single-column model list, e.g. SambaNova's flat tier.
                    if table.headers and len(table.headers) == 1 and "model" in headers_lower:
                        for row in table.rows:
                            model_name = normalise_model_id(cell_text(row[0]))
                            if model_name:
                                model_rows.append((model_name, []))
                    else:
                        for row in table.rows:
                            flat_limits.extend(
                                extract_rate_limits(" ".join(cell_text(c) for c in row))
                            )

            # The flat-tier prose often states limits in the section text.
            flat_limits.extend(extract_rate_limits(body[:600]))

            offer_type = OfferType.SUSTAINED_FREE_TIER
            if re.search(r"trial|expires?|one[- ]time", body[:400], re.IGNORECASE):
                offer_type = OfferType.ONE_TIME_TRIAL

            value, unit, period = _primary_limit(flat_limits)
            card_state = _card_state(access_note)

            common = {
                "source_id": self.spec.id,
                "source_record_url": f"{self.spec.url}#{slugify(heading)}",
                "provider_name": heading,
                "official_url": fact_url,
                "access_type": AccessType.API,
                "offer_type": offer_type,
                "quota_raw": squash(access_note)[:200],
                "quota_value": value,
                "quota_unit": unit,
                "quota_period": period,
                "rate_limits": flat_limits[:12],
                "credit_card": card_state,
                "registration": "unknown",
                "phone_verification": "unknown",
                "condition_notes": (verified and f"source last verified {verified}") or None,
                "evidence_excerpt": prov.excerpt(
                    heading,
                    access_note[:160] if access_note else "",
                    f"verified {verified}" if verified else "",
                    f"limits {_summarise(flat_limits)}" if flat_limits else "",
                ),
                "observed_at": observed_at,
            }

            if model_rows:
                for model_name, limits in model_rows:
                    overrides = dict(common)
                    overrides["model_id"] = model_name
                    overrides["display_name"] = model_name
                    if limits:
                        overrides["rate_limits"] = limits
                    result.candidates.append(CandidateRecord(**overrides))
            else:
                result.candidates.append(CandidateRecord(**common))

            result.provider_facts[key] = {
                "name": heading,
                "homepage_url": fact_url,
                "official_domain": None,
                "source_family": self.spec.source_family,
                "source_verified_on": verified,
                "access_note": squash(access_note)[:200] if access_note else None,
                "license": None,
                "note": "source has no published LICENSE; facts-only extraction",
            }

        if not result.candidates:
            result.structure_ok = False
            result.warnings.append("sections found but no provider rows extracted")
        return result


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _split_sections(document: str) -> list[tuple[str, str]]:
    """Split on ``## Heading`` lines, ignoring code fences."""
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    buffer: list[str] = []
    in_fence = False

    for line in document.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^##\s+\S", line) and not line.startswith("###"):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(buffer)))
            current_heading = re.sub(r"^##\s+", "", line).strip()
            buffer = []
            continue
        buffer.append(line)

    if current_heading is not None:
        sections.append((current_heading, "\n".join(buffer)))
    return sections


def _tables_by_section(document: str) -> dict[str, list[Table]]:
    """Attribute each parsed table to the level-2 heading above it."""
    mapping: dict[str, list[Table]] = {}
    lines = document.splitlines()
    bounds: list[tuple[int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^##\s+\S", line) and not line.startswith("###"):
            bounds.append((index, re.sub(r"^##\s+", "", line).strip()))

    for table in parse_tables(document):
        # Locate the heading directly above this table by matching its first
        # header row text.
        needle = "|".join(table.headers)[:40]
        position = None
        for index, line in enumerate(lines):
            if needle and needle.split("|")[0] in line and line.strip().startswith("|"):
                position = index
                break
        if position is None:
            continue
        owner = None
        for start, heading in bounds:
            if start <= position:
                owner = heading
            else:
                break
        if owner:
            mapping.setdefault(owner, []).append(table)
    return mapping


def _access_requirement(body: str) -> str:
    """First non-empty prose line of a section, which states the conditions."""
    for line in body.splitlines():
        text = squash(line)
        if not text or text.startswith(("|", "#", ">", "-", "<")):
            continue
        if re.match(r"^Last verified", text, re.IGNORECASE):
            continue
        return text
    return ""


def _card_state(access_note: str) -> str:
    """Derive need / not_need / unknown from the access prose."""
    if not access_note:
        return "unknown"
    lowered = access_note.lower()
    if "no credit card" in lowered or "no card" in lowered:
        return "not_need"
    if "credit card" in lowered and "no " not in lowered:
        return "need"
    return tri_state(access_note)


def _metric_from_header(header: str) -> str | None:
    lowered = squash(header).lower()
    for metric in ("rpm", "rpd", "tpm", "tpd", "rps"):
        if metric in lowered:
            return metric
    return None


def _period_for(metric: str) -> str:
    return {
        "rpm": "per_minute",
        "tpm": "per_minute",
        "rpd": "per_day",
        "tpd": "per_day",
        "rps": "per_second",
    }.get(metric, "unknown")


def _primary_limit(
    limits: list[dict[str, object]],
) -> tuple[float | None, QuotaUnit, QuotaPeriod]:
    for metric in ("rpd", "rpm", "tpd", "tpm"):
        for limit in limits:
            if limit["metric"] == metric:
                unit = QuotaUnit.TOKENS if metric in {"tpm", "tpd"} else QuotaUnit.REQUESTS
                return float(limit["value"]), unit, QuotaPeriod(str(limit["period"]))
    return None, QuotaUnit.UNKNOWN, QuotaPeriod.UNKNOWN


def _summarise(limits: list[dict[str, object]], limit: int = 3) -> str:
    parts = []
    for entry in limits[:limit]:
        value = entry["value"]
        rendered = int(value) if float(value).is_integer() else value
        parts.append(f"{rendered} {str(entry['metric']).upper()}")
    return ", ".join(parts)

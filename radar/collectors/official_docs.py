"""Official-source parser used for verification (task book section 10).

The verification loop is:

    maintainer configures an official source  ->  collect  ->  field rules
    ->  compare against the directory claim  ->  produce a conclusion

Most official pages do not expose a stable machine-readable limit table. When
no field rule matches, this adapter still returns a short excerpt plus a link
so a maintainer can confirm the field through ``config/reviews.yaml``. It never
guesses and never marks something verified on its own.
"""

from __future__ import annotations

import re

from ..ids import slugify
from ..models import CandidateRecord
from ..parsers.html_docs import extract_evidence, parse_html
from ..parsers.markdown_tables import extract_rate_limits
from ..textutil import squash
from ..vocab import AccessType, SourceLevel
from .base import BaseAdapter, ParseResult, register

#: Prose cues that a page is talking about a free tier / rate limits.
_LIMIT_CUES = (
    "rate limit",
    "rate limits",
    "requests per",
    "requests/minute",
    "requests per minute",
    "requests per day",
    "rpm",
    "rpd",
    "tpm",
    "tpd",
    "free tier",
    "free plan",
    "quota",
    "credits",
)

#: Cues about registration conditions.
_CONDITION_CUES = (
    "credit card",
    "no credit card",
    "phone verification",
    "verify your phone",
    "billing",
    "free of charge",
)

_FREE_TIER = re.compile(
    r"\b(free[- ]of[- ]charge|free tier|free plan|no[- ]cost|free credits?)\b", re.IGNORECASE
)


@register
class OfficialDocsGenericAdapter(BaseAdapter):
    """Best-effort extractor for official documentation pages."""

    name = "official_docs_generic"
    version = "1.0.0"

    def parse(self, document: str, *, observed_at: str) -> ParseResult:
        result = ParseResult()
        prov = self.provenance(observed_at)
        prov.source_level = SourceLevel.OFFICIAL.value

        doc = parse_html(document)
        if not doc.main_text.strip():
            result.structure_ok = False
            result.warnings.append("no readable text extracted")
            return result

        provider_slug = self.spec.provider_slug or slugify(doc.title or self.spec.id)

        limit_excerpts = extract_evidence(doc.main_text, _LIMIT_CUES)
        condition_excerpts = extract_evidence(doc.main_text, _CONDITION_CUES)

        limits = extract_rate_limits(doc.main_text)

        # Official pages rarely enumerate models in a parseable way. Only rows
        # that come from a real table with a model column are used.
        model_rows = _model_rows_from_tables(doc.tables)

        evidence = (
            prov.excerpt(
                (limit_excerpts[0] if limit_excerpts else "")[:200],
                (condition_excerpts[0] if condition_excerpts else "")[:160],
            )
            or squash(doc.main_text)[:200]
        )

        result.provider_facts[provider_slug] = {
            "name": doc.title or provider_slug,
            "official_domain": _host(self.spec.url),
            "source_level": SourceLevel.OFFICIAL.value,
            "documented_rate_limits": limits,
            "documented_excerpt": evidence,
            "detected_free_tier_language": bool(_FREE_TIER.search(doc.main_text)),
            "evidence_url": doc.canonical_url or self.spec.url,
        }

        # The evidence goes into the verification queue rather than straight
        # onto a claim: without a field rule a human confirms it.
        result.review_notes.append(
            {
                "source_id": self.spec.id,
                "provider_slug": provider_slug,
                "field": "rate_limits",
                "excerpts": limit_excerpts,
                "observed_at": observed_at,
                "evidence_url": doc.canonical_url or self.spec.url,
                "reason": "official page excerpt; confirm through config/reviews.yaml",
            }
        )

        if condition_excerpts:
            result.review_notes.append(
                {
                    "source_id": self.spec.id,
                    "provider_slug": provider_slug,
                    "field": "conditions",
                    "excerpts": condition_excerpts,
                    "observed_at": observed_at,
                    "evidence_url": doc.canonical_url or self.spec.url,
                    "reason": "official page excerpt; confirm through config/reviews.yaml",
                }
            )

        # Emit a candidate only for models the official page actually lists in
        # a table. Otherwise the official source contributes facts, not rows.
        for model_id, context in model_rows:
            result.candidates.append(
                CandidateRecord(
                    source_id=self.spec.id,
                    source_record_url=doc.canonical_url or self.spec.url,
                    provider_name=doc.title or provider_slug,
                    official_url=None,
                    model_id=model_id,
                    display_name=model_id,
                    context_window_tokens=context,
                    access_type=AccessType.API,
                    rate_limits=limits,
                    evidence_excerpt=evidence,
                    observed_at=observed_at,
                )
            )

        if not limit_excerpts and not model_rows and not condition_excerpts:
            result.warnings.append(
                "official page yielded no limit or condition cues; recorded as link-only"
            )
        return result


def _model_rows_from_tables(tables: list[object]) -> list[tuple[str, int | None]]:
    """Pull (model_id, context) pairs out of tables that clearly have them."""
    from ..parsers.markdown_tables import extract_context_window

    rows: list[tuple[str, int | None]] = []
    for table in tables:  # type: ignore[assignment]
        headers = [squash(h).lower() for h in getattr(table, "headers", [])]
        model_index = next((i for i, h in enumerate(headers) if "model" in h and "id" in h), None)
        if model_index is None:
            model_index = next((i for i, h in enumerate(headers) if h == "model"), None)
        if model_index is None:
            continue
        context_index = next(
            (i for i, h in enumerate(headers) if "context" in h or "token" in h), None
        )
        for row in getattr(table, "rows", []):
            if model_index >= len(row):
                continue
            model_id = squash(row[model_index]).strip("`")
            if not model_id or len(model_id) > 120:
                continue
            context = None
            if context_index is not None and context_index < len(row):
                context = extract_context_window(row[context_index])
            rows.append((model_id, context))
    return rows


def _host(url: str) -> str | None:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname

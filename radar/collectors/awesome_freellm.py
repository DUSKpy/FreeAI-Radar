"""Adapter 2 -- awesome-freellm-apis (``open-free-llm-api`` GitHub README).

Independent real source with a different structure from adapter 1, which is
what makes the two genuinely independent rather than two views of one file.

Sentinel blocks used:

    BEGIN_PERMANENT_FREE   Provider | Free Models | Credit Card? | Max Context | Modalities | Get API Key
    BEGIN_RENEWABLE        Provider | Free Models | Credit Model | Max Context | Modalities | Get API Key
    BEGIN_QUICK_REF        Provider | Base URL | Get API Key | Credit Card?
    BEGIN_BEST_MODELS      Provider | Best Free Model | Model ID | Max Context | Rate Limit

Distinctive features handled here:

* ``BEGIN_*`` / ``END_*`` comments instead of ``<!--TABLE:x:START-->``.
* The Best Free Models table is **multi-row per provider** with a blank
  provider cell on continuation rows -- :meth:`Table.carry_forward` fills it.
* ``Free Models`` is an integer count, stored as a provider-level fact and
  never expanded into that many fabricated model records.
* ``Modalities`` gives source-declared capability tags (text, reasoning,
  vision, image, video, audio, code, pdf, rerank, embedding).
* ``Model ID`` cells are backticked and are the authoritative identifier.
"""

from __future__ import annotations

import re

from ..ids import slugify
from ..models import CandidateRecord
from ..parsers.markdown_tables import (
    Table,
    extract_capabilities,
    extract_context_window,
    extract_rate_limits,
    first_url,
    is_not_published,
    parse_tables,
    tri_state,
)
from ..textutil import cell_text, normalise_model_id
from ..vocab import AccessType, OfferType, QuotaPeriod, QuotaUnit
from .base import BaseAdapter, ParseResult, register

SENTINELS = (
    "BEGIN_PERMANENT_FREE",
    "BEGIN_RENEWABLE",
    "BEGIN_QUICK_REF",
    "BEGIN_BEST_MODELS",
    "BEGIN_TRIAL",
)

_KEY_PREFIX = re.compile(r"^(permanent|renewable|quick|best|trial)", re.IGNORECASE)


def _classify(table: Table) -> str | None:
    sentinel = (table.sentinel or "").upper()

    # The upstream file mixes BEGIN_/START_ styles; normalise both.
    token = re.sub(r"^(BEGIN|START)[_:]", "", sentinel)
    if token.startswith("PERMANENT") or token.startswith("FREE_TIER"):
        return "permanent"
    if token.startswith("RENEWABLE"):
        return "renewable"
    if token.startswith("TRIAL"):
        return "trial"
    if token.startswith("QUICK"):
        return "quickref"
    if token.startswith("BEST"):
        return "best_models"

    joined = " ".join(table.headers or []).lower()
    if "base url" in joined:
        return "quickref"
    if "model id" in joined:
        return "best_models"
    if "free models" in joined and "credit model" in joined:
        return "renewable"
    if "free models" in joined:
        return "permanent"
    return None


@register
class AwesomeFreellmMarkdownAdapter(BaseAdapter):
    name = "awesome_freellm_markdown"
    version = "1.0.0"

    def parse(self, document: str, *, observed_at: str) -> ParseResult:
        result = ParseResult()
        prov = self.provenance(observed_at)

        tables = parse_tables(document)
        if not tables:
            result.structure_ok = False
            result.warnings.append("no markdown tables found")
            return result

        quick: dict[str, dict[str, str | None]] = {}
        models_by_provider: dict[str, list[dict[str, object]]] = {}
        pending: list[tuple[str, Table, list[str]]] = []

        for table in tables:
            kind = _classify(table)
            if kind is None:
                result.warnings.append(f"unclassified table: {table.caption or '(no caption)'}")
                continue

            if kind == "quickref":
                for row in table.rows:
                    name = cell_text(row[0])
                    if not name:
                        continue
                    key = slugify(name)
                    base = cell_text(table.value(row, "Base URL"))
                    base_code = _code_or_url(table.value(row, "Base URL"))
                    quick[key] = {
                        "base_url": base_code or (base if base.startswith("http") else None),
                        "signup_url": first_url(table.value(row, "Get API Key", "API Key")),
                        "credit_card": cell_text(
                            table.value(row, "Credit Card?", "Credit Card", "Card")
                        ),
                    }
                continue

            if kind == "best_models":
                table.key_column = 0
                rows = table.carry_forward(0)
                for row in rows:
                    provider_name = cell_text(row[0]) if row else ""
                    if not provider_name:
                        continue
                    key = slugify(provider_name)
                    upstream = normalise_model_id(
                        cell_text(table.value(row, "Model ID", "Model", "ID"))
                    )
                    if not upstream:
                        continue
                    display = (
                        cell_text(table.value(row, "Best Free Model", "Model Name")) or upstream
                    )
                    context = extract_context_window(
                        cell_text(table.value(row, "Max Context", "Context"))
                    )
                    rate_text = cell_text(table.value(row, "Rate Limit", "Limits"))
                    models_by_provider.setdefault(key, []).append(
                        {
                            "model_id": upstream,
                            "display_name": display,
                            "context": context,
                            "rate_text": rate_text,
                            "rate_limits": extract_rate_limits(rate_text),
                            "link": first_url(table.value(row, "Best Free Model")) or None,
                        }
                    )
                continue

            for row in table.rows:
                pending.append((kind, table, row))

        for kind, table, row in pending:
            provider_name = cell_text(row[0]) if row else ""
            if not provider_name:
                continue
            key = slugify(provider_name)

            free_count_text = cell_text(table.value(row, "Free Models", "Free Model Count"))
            credit_card = cell_text(table.value(row, "Credit Card?", "Credit Card")) or (
                quick.get(key, {}).get("credit_card") or ""
            )
            context = extract_context_window(cell_text(table.value(row, "Max Context", "Context")))
            modalities = cell_text(table.value(row, "Modalities"))
            capabilities = extract_capabilities(modalities)
            credit_model = cell_text(table.value(row, "Credit Model", "Credit")) or cell_text(
                table.value(row, "Free Offer", "Offer")
            )
            signup = first_url(table.value(row, "Get API Key", "API Key")) or quick.get(
                key, {}
            ).get("signup_url")
            base_url = quick.get(key, {}).get("base_url")

            free_count: int | None = None
            if free_count_text and not is_not_published(free_count_text):
                match = re.search(r"\d+", free_count_text)
                if match:
                    free_count = int(match.group(0))

            limits = extract_rate_limits(credit_model)
            offer_type = (
                OfferType.RECURRING_FREE_CREDIT
                if kind == "renewable"
                else OfferType.SUSTAINED_FREE_TIER
            )
            if kind == "trial":
                offer_type = OfferType.ONE_TIME_TRIAL

            value, unit, period = _primary_limit(limits, kind)

            homepage = first_url(row[0])
            evidence = prov.excerpt(
                provider_name,
                f"free models: {free_count_text}" if free_count_text else "",
                f"card: {credit_card or 'not stated'}",
                f"context: {context}" if context else "",
                f"modalities: {modalities}" if modalities else "",
                f"credit: {credit_model}" if credit_model else "",
            )

            common = {
                "source_id": self.spec.id,
                "source_record_url": self.spec.url,
                "provider_name": provider_name,
                "official_url": homepage,
                "signup_url": signup,
                "base_url": base_url,
                "access_type": AccessType.API,
                "offer_type": offer_type,
                "quota_raw": credit_model,
                "quota_value": value,
                "quota_unit": unit,
                "quota_period": period,
                "rate_limits": limits,
                "credit_card": tri_state(credit_card),
                "registration": (
                    "need"
                    if re.search(r"registration|sign", credit_card, re.IGNORECASE)
                    else "unknown"
                ),
                "phone_verification": ("need" if "phone" in credit_card.lower() else "unknown"),
                "capabilities": capabilities,  # type: ignore[arg-type]
                "region": [],
                "free_model_count": free_count,
                "modalities": [m.strip() for m in modalities.split(",") if m.strip()],
                "evidence_excerpt": evidence,
                "observed_at": observed_at,
            }

            published_models = models_by_provider.get(key, [])
            if published_models:
                for model in published_models:
                    model_rate_limits = model["rate_limits"] or limits
                    overrides = dict(common)
                    overrides.update(
                        {
                            "model_id": str(model["model_id"]),
                            "display_name": str(model["display_name"]),
                            "context_window_tokens": model["context"] or context,
                            "rate_limits": model_rate_limits,
                            "evidence_excerpt": prov.excerpt(
                                provider_name,
                                f"best model: {model['display_name']}",
                                f"model id: {model['model_id']}",
                                f"context: {model['context']}" if model["context"] else "",
                                f"rate: {model['rate_text']}" if model["rate_text"] else "",
                            ),
                        }
                    )
                    result.candidates.append(CandidateRecord(**overrides))
            else:
                # Provider-level row only. The free-model *count* is recorded as
                # a fact; it is never expanded into that many model records.
                overrides = dict(common)
                overrides["context_window_tokens"] = context
                result.candidates.append(CandidateRecord(**overrides))

            result.provider_facts[key] = {
                "name": provider_name,
                "homepage_url": homepage,
                "signup_url": signup,
                "base_url": base_url,
                "free_model_count": free_count,
                "context_window_tokens": context,
                "modalities": capabilities,
                "official_domain": None,
                "source_family": self.spec.source_family,
                "note": (
                    f"source reports {free_count} free models; ids listed for "
                    f"{len(published_models)}"
                )
                if free_count
                else None,
            }

        result.candidates = _dedupe(result.candidates)
        if not result.candidates:
            result.structure_ok = False
            result.warnings.append("tables present but zero rows extracted")
        return result


def _code_or_url(cell: str | None) -> str | None:
    """Base URL cells are code spans, occasionally wrapped in an anchor."""
    if not cell:
        return None
    url = first_url(cell)
    if url:
        return url
    for match in re.finditer(r"`([^`]+)`", cell):
        candidate = match.group(1).strip()
        if candidate.startswith(("http://", "https://")):
            return candidate
    text = cell_text(cell)
    if text.startswith(("http://", "https://")):
        return text.split()[0]
    return None


def _primary_limit(
    limits: list[dict[str, object]], kind: str
) -> tuple[float | None, QuotaUnit, QuotaPeriod]:
    preference = ("rpd", "rpm", "tpd", "tpm")
    for metric in preference:
        for limit in limits:
            if limit["metric"] == metric:
                unit = QuotaUnit.TOKENS if metric in {"tpm", "tpd"} else QuotaUnit.REQUESTS
                return float(limit["value"]), unit, QuotaPeriod(str(limit["period"]))
    return None, QuotaUnit.UNKNOWN, QuotaPeriod.UNKNOWN


def _dedupe(candidates: list[CandidateRecord]) -> list[CandidateRecord]:
    """Collapse duplicate (provider, model) pairs.

    Also drops the provider-level placeholder when real model rows exist for
    the same provider, so a provider is not double-counted.
    """
    by_key: dict[tuple[str, str], CandidateRecord] = {}
    providers_with_models: set[str] = set()

    for candidate in candidates:
        key = (slugify(candidate.provider_name), candidate.model_id or "")
        if candidate.model_id:
            providers_with_models.add(slugify(candidate.provider_name))
        previous = by_key.get(key)
        if previous is None or _richer(candidate, previous):
            by_key[key] = candidate

    ordered: list[CandidateRecord] = []
    for (provider_key, model_key), candidate in by_key.items():
        if not model_key and provider_key in providers_with_models:
            continue
        ordered.append(candidate)
    return ordered


def _richer(candidate: CandidateRecord, previous: CandidateRecord) -> bool:
    """Prefer the record carrying more usable fields."""

    def score(record: CandidateRecord) -> int:
        return sum(
            1
            for value in (
                record.base_url,
                record.signup_url,
                record.context_window_tokens,
                record.quota_value,
                record.capabilities,
                record.evidence_excerpt,
            )
            if value
        )

    return score(candidate) > score(previous)

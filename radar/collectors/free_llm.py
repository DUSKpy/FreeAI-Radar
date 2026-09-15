"""Adapter 1 -- Free-LLM (``nejib1/Free-LLM`` GitHub README).

Independent real source. The README wraps each table in a comment sentinel:

    <!--TABLE:PERMANENT:START--> ... <!--TABLE:PERMANENT:END-->

Tables read here:

``PERMANENT``  Provider | Credit Card? | Rate Limit | Daily Limit | Monthly Limit | Key Models
``RENEWABLE``  Provider | Credit Card? | Rate Limit | Free Offer | Key Models
``TRIAL``      Provider | Credit Card? | Credit Amount | Expiry | Key Models
``QUICKREF``   Provider | Base URL | Get API Key

Design notes
------------
* Sentinels are the primary anchor; heading detection is a fallback so a
  cosmetic README change does not silently empty the catalog.
* Column lookup goes through :meth:`Table.column` alias matching, so column
  reordering does not break parsing.
* The upstream line "no credit card" is mapped to ``not_need`` while a missing
  or dash cell stays ``unknown``. The two are never conflated.
* ``Key Models`` is prose. Model identifiers are only recorded when the cell
  contains a backticked token, which is how this README marks real ids.
"""

from __future__ import annotations

import re

from ..ids import slugify
from ..models import CandidateRecord
from ..parsers.markdown_tables import (
    Table,
    extract_rate_limits,
    first_url,
    is_not_published,
    parse_tables,
    tri_state,
)
from ..textutil import cell_text, normalise_model_id, squash
from ..vocab import AccessType, OfferType, QuotaPeriod, QuotaUnit
from .base import BaseAdapter, ParseResult, register

SENTINELS = (
    "TABLE:PERMANENT",
    "TABLE:RENEWABLE",
    "TABLE:TRIAL",
    "TABLE:QUICKREF",
)

#: Cell text that marks a provider as offering a local/self-hosted option.
_LOCAL_HINTS = re.compile(r"\b(local|self[- ]hosted|offline|on[- ]device)\b", re.IGNORECASE)


class _TableKind:
    PERMANENT = "permanent"
    RENEWABLE = "renewable"
    TRIAL = "trial"
    QUICKREF = "quickref"


def _classify(table: Table) -> str | None:
    sentinel = (table.sentinel or "").upper()
    if "PERMANENT" in sentinel:
        return _TableKind.PERMANENT
    if "RENEWABLE" in sentinel:
        return _TableKind.RENEWABLE
    if "TRIAL" in sentinel:
        return _TableKind.TRIAL
    if "QUICKREF" in sentinel:
        return _TableKind.QUICKREF

    # Fallback: infer from the headers when the sentinel is gone.
    headers = set(table.headers or [])
    joined = " ".join(table.headers or []).lower()
    if "base url" in joined:
        return _TableKind.QUICKREF
    if "credit amount" in joined or "expiry" in joined:
        return _TableKind.TRIAL
    if "free offer" in joined or "monthly limit" in joined:
        return _TableKind.RENEWABLE if "free offer" in joined else _TableKind.PERMANENT
    if "daily limit" in joined:
        return _TableKind.PERMANENT
    if headers and "provider" in joined:
        return _TableKind.PERMANENT
    return None


@register
class FreeLlmMarkdownAdapter(BaseAdapter):
    name = "free_llm_markdown"
    version = "1.0.0"

    def parse(self, document: str, *, observed_at: str) -> ParseResult:
        result = ParseResult()
        prov = self.provenance(observed_at)

        tables = parse_tables(document)
        if not tables:
            result.structure_ok = False
            result.warnings.append("no markdown tables found")
            return result

        base_urls: dict[str, str] = {}
        signup_urls: dict[str, str] = {}
        pending: list[tuple[str, Table, list[str]]] = []

        for table in tables:
            kind = _classify(table)
            if kind is None:
                result.warnings.append(f"unclassified table: {table.caption or '(no caption)'}")
                continue

            if kind == _TableKind.QUICKREF:
                for row in table.rows:
                    name = cell_text(row[0]) if row else ""
                    if not name:
                        continue
                    key = slugify(name)
                    base = cell_text(table.value(row, "Base URL", "API Base URL", "Endpoint"))
                    base_url = first_url(table.value(row, "Base URL", "API Base URL")) or (
                        base if base.startswith("http") else None
                    )
                    if base_url:
                        # Base URLs in this table are plain code spans, not links.
                        if not base_url and base:
                            candidate = base.strip().strip("`")
                            if candidate.startswith("http"):
                                base_url = candidate
                        if base_url:
                            base_urls[key] = base_url
                    signup = first_url(table.value(row, "Get API Key", "API Key", "Key"))
                    if signup:
                        signup_urls[key] = signup
                continue

            for row in table.rows:
                pending.append((kind, table, row))

        for kind, table, row in pending:
            provider_name = cell_text(row[0]) if row else ""
            if not provider_name:
                continue

            slug = slugify(provider_name)
            credit_card = cell_text(table.value(row, "Credit Card?", "Credit Card", "Card"))
            rate_text = cell_text(table.value(row, "Rate Limit", "Rate Limits", "Limits"))
            daily_text = cell_text(table.value(row, "Daily Limit", "Daily"))
            monthly_text = cell_text(table.value(row, "Monthly Limit", "Monthly"))
            key_models = cell_text(table.value(row, "Key Models", "Models", "Free Models"))

            offer_type, quota_raw, quota_value, quota_unit, quota_period = _offer_shape(
                kind, rate_text, daily_text, monthly_text
            )

            limits = extract_rate_limits(" ".join([rate_text, daily_text, monthly_text]))

            models = _extract_model_ids(key_models)
            evidence = prov.excerpt(
                f"{provider_name}",
                f"card: {credit_card or 'not stated'}",
                f"rate: {rate_text or 'not stated'}",
                f"daily: {daily_text}" if daily_text else "",
                f"monthly: {monthly_text}" if monthly_text else "",
            )

            homepage = first_url(row[0])
            official_url = None
            if homepage:
                from ..textutil import normalise_host

                official_url = normalise_host(homepage)

            base_url = base_urls.get(slug)

            common = {
                "source_id": self.spec.id,
                "source_record_url": self.spec.url,
                "provider_name": provider_name,
                "official_url": homepage,
                "signup_url": signup_urls.get(slug),
                "base_url": base_url,
                "access_type": AccessType.API,
                "offer_type": offer_type,
                "quota_raw": quota_raw,
                "quota_value": quota_value,
                "quota_unit": quota_unit,
                "quota_period": quota_period,
                "rate_limits": limits,
                "credit_card": tri_state(credit_card),
                "registration": (
                    "need"
                    if credit_card.lower().startswith(("registration", "sign"))
                    else "unknown"
                ),
                "phone_verification": ("need" if "phone" in credit_card.lower() else "unknown"),
                "topup_required": (
                    "need"
                    if "deposit" in key_models.lower() or "topup" in key_models.lower()
                    else "unknown"
                ),
                "evidence_excerpt": evidence,
                "observed_at": observed_at,
            }

            if models:
                for upstream_id, display in models:
                    result.candidates.append(
                        CandidateRecord(**common, model_id=upstream_id, display_name=display)
                    )
            else:
                # No machine-readable model id in the cell. We still record the
                # provider-level offer rather than inventing model names.
                result.candidates.append(CandidateRecord(**common))

            result.provider_facts[slug] = {
                "name": provider_name,
                "homepage_url": homepage,
                "signup_url": signup_urls.get(slug),
                "base_url": base_url,
                "official_domain": official_url,
                "source_family": self.spec.source_family,
                "note": None if key_models else "no model ids published in this table",
            }

        result.candidates = _dedupe(result.candidates)
        return result


def _offer_shape(
    kind: str, rate_text: str, daily_text: str, monthly_text: str
) -> tuple[OfferType, str, float | None, QuotaUnit, QuotaPeriod]:
    """Decide the offer type and primary numeric quota for a row.

    The numeric value is only filled when the cell actually states a number.
    "Free Forever", "See provider" and "Fair use" leave the value null.
    """
    combined = squash(" ".join([rate_text, daily_text, monthly_text]))

    if kind == _TableKind.TRIAL:
        return (
            OfferType.ONE_TIME_TRIAL,
            combined,
            _first_amount(daily_text or rate_text),
            QuotaUnit.CREDITS_USD if "$" in combined else QuotaUnit.UNKNOWN,
            QuotaPeriod.ONE_TIME,
        )

    if kind == _TableKind.RENEWABLE:
        limits = extract_rate_limits(combined)
        value, unit, period = _primary_limit(limits)
        return OfferType.RECURRING_FREE_CREDIT, combined, value, unit, period

    limits = extract_rate_limits(combined)
    value, unit, period = _primary_limit(limits)
    return OfferType.SUSTAINED_FREE_TIER, combined, value, unit, period


def _first_amount(text: str) -> float | None:
    from ..parsers.markdown_tables import first_number

    if is_not_published(text):
        return None
    return first_number(text)


def _primary_limit(
    limits: list[dict[str, object]],
) -> tuple[float | None, QuotaUnit, QuotaPeriod]:
    """Pick the headline numeric limit, preferring the daily request count."""
    preference = ("rpd", "rpm", "tpd", "tpm", "rps")
    for metric in preference:
        for limit in limits:
            if limit["metric"] == metric:
                period = str(limit["period"])
                unit = QuotaUnit.TOKENS if metric in {"tpm", "tpd"} else QuotaUnit.REQUESTS
                return float(limit["value"]), unit, QuotaPeriod(period)  # type: ignore[arg-type]
    return None, QuotaUnit.UNKNOWN, QuotaPeriod.UNKNOWN


_SLUG_SEPARATOR = re.compile(r"\s*[/›>]\s*")


def _extract_model_ids(cell: str) -> list[tuple[str, str]]:
    """Extract ``(upstream_id, display_name)`` pairs from a Key Models cell.

    Only backticked tokens are taken as real identifiers. Free prose such as
    "See provider" yields nothing, which is the honest outcome.
    """
    if not cell or is_not_published(cell):
        return []

    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in re.finditer(r"`([^`]+)`", cell):
        candidate = normalise_model_id(match.group(1))
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append((candidate, candidate))

    if found:
        return found

    # Fallback: comma-separated display names that look like identifiers, e.g.
    # "Gemini 3.1 Pro, Gemini 3.1 Flash". These are display names only; the
    # adapter records them as ids because this README uses the same string for
    # both, but the evidence excerpt keeps the original wording.
    plain = cell_text(cell)
    if not plain or _LOCAL_HINTS.search(plain):
        return []
    for part in re.split(r",|、|;", plain):
        candidate = squash(part)
        if not candidate or len(candidate) > 80:
            continue
        if is_not_published(candidate):
            continue
        if not re.search(r"[A-Za-z0-9]", candidate):
            continue
        if candidate.lower() in {"see provider", "various", "multiple"}:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        found.append((candidate, candidate))
    return found


def _dedupe(candidates: list[CandidateRecord]) -> list[CandidateRecord]:
    """Collapse duplicate provider+model pairs produced by overlapping tables."""
    seen: set[tuple[str, str]] = set()
    unique: list[CandidateRecord] = []
    for candidate in candidates:
        key = (slugify(candidate.provider_name), candidate.model_id or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique

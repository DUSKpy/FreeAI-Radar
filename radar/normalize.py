"""Normalisation, de-duplication and official verification.

This module turns a pile of per-source :class:`CandidateRecord` rows into the
normalized entity graph. The rules encoded here come straight from the task
book and are the difference between a useful catalog and a misleading one:

1. **Providers are matched on verified official domain, never on display name
   alone.** Aggregators and original vendors are distinct providers. A
   heuristic alias match is recorded as a *manual review candidate* instead of
   being merged silently.

2. **A provider-level free quota is never copied onto each of its models.**
   ``Offer.model_id`` stays ``null`` unless a source explicitly enumerated the
   covered models.

3. **Mirrored content is not independent evidence.** Two rows that originate
   from the same ``source_family`` give one attestation, not two.

4. **Official material beats a directory, but only when region, plan, model
   and effective date line up.** When official and directory disagree, both
   evidences are kept and the offer is marked ``source_conflict``.

5. **An official page that is silent about a field does not prove the answer
   is negative.** Silence leaves the value ``unknown``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from .ids import (
    claim_id,
    iso_utc,
    normalise_name,
    short_hash,
    slugify,
    utcnow,
)
from .ids import (
    model_id as make_model_id,
)
from .ids import (
    offer_id as make_offer_id,
)
from .ids import (
    provider_id as make_provider_id,
)
from .models import (
    CandidateRecord,
    ClaimEvidenceRecord,
    ClaimRecord,
    ConditionsRecord,
    ModelRecord,
    OfferRecord,
    ProviderRecord,
    QuotaRecord,
    SourceStateRecord,
)
from .textutil import normalise_host
from .vocab import (
    CapabilityTag,  # noqa: F401  (re-exported for adapters)
    EntityStatus,
    InfoStatus,
    Protocol,
    ReviewStatus,
    SourceLevel,
    TriState,
)

#: Fields that, when different between sources, produce a conflict rather than
#: a silent overwrite. These are the fields that affect whether a call works.
CONFLICT_FIELDS = ("base_url", "protocols", "model_id", "quota", "conditions")

#: Which candidate fields become tracked claims.
CLAIM_FIELDS = (
    "base_url",
    "access_type",
    "offer_type",
    "quota_raw",
    "credit_card",
    "phone_verification",
    "registration",
    "topup_required",
    "api_format",
    "context_window_tokens",
    "capabilities",
)


@dataclass
class ProviderAlias:
    """Manual alias table entry: slug -> canonical slug."""

    canonical: str
    aliases: set[str] = field(default_factory=set)


@dataclass
class NormalisationResult:
    providers: list[ProviderRecord] = field(default_factory=list)
    models: list[ModelRecord] = field(default_factory=list)
    offers: list[OfferRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    #: Free-text notes for the human verification queue.
    review_queue: list[dict[str, object]] = field(default_factory=list)
    #: Suspicious name collisions that were NOT auto-merged.
    merge_candidates: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SourceContext:
    """Everything normalisation needs to know about the source of a row."""

    source_id: str
    source_family: str
    source_level: SourceLevel
    source_record_url: str
    parser_version: str = "1.0.0"
    license: str | None = None


def default_protocols(api_format: str) -> list[Protocol]:
    """Map a loose ``api_format`` string onto explicit protocol values.

    A single "openai compatible" boolean is never stored. Only Chat
    Completions is assumed when a source says ``openai``, because assuming
    Responses support would be a fabricated compatibility claim.
    """
    text = (api_format or "").strip().lower()
    if not text or text == "unknown":
        return []
    if "openai" in text or text in {"openai", "chat", "chat_completions"}:
        return [Protocol.OPENAI_CHAT]
    if "anthropic" in text or "claude" in text or "messages" in text:
        return [Protocol.ANTHROPIC_MESSAGES]
    if "gemini" in text or "google" in text:
        return [Protocol.GEMINI_NATIVE]
    if "responses" in text:
        return [Protocol.OPENAI_RESPONSES]
    return []


def normalise(
    candidates: Iterable[CandidateRecord],
    contexts: dict[str, SourceContext],
    *,
    provider_facts: dict[str, dict[str, dict[str, object]]] | None = None,
    alias_table: dict[str, str] | None = None,
    official_domain_index: dict[str, str] | None = None,
    observed_at: str | None = None,
) -> NormalisationResult:
    """Build the entity graph from per-source candidates.

    ``provider_facts`` is keyed ``source_id -> provider_slug -> facts`` and
    carries provider-level data (Base URL, free-model count, modalities) that
    must not be flattened onto individual models.
    """
    result = NormalisationResult()
    moment = observed_at or iso_utc()
    alias_table = alias_table or {}
    official_domain_index = official_domain_index or {}
    facts = provider_facts or {}

    # -- 1. establish providers -------------------------------------------
    provider_index, merge_candidates = _build_providers(
        candidates, contexts, facts, alias_table, official_domain_index
    )
    result.merge_candidates.extend(merge_candidates)

    # -- 2. models and offers ---------------------------------------------
    model_index: dict[tuple[str, str], ModelRecord] = {}
    offer_index: dict[str, OfferRecord] = {}
    #: (provider_id, field) -> list of (value, evidence, source_family)
    claim_values: dict[tuple[str, str], list[tuple[object, ClaimEvidenceRecord]]] = defaultdict(
        list
    )
    model_claim_values: dict[tuple[str, str, str], list[tuple[object, ClaimEvidenceRecord]]] = (
        defaultdict(list)
    )

    for candidate in candidates:
        context = contexts.get(candidate.source_id)
        if context is None:
            result.warnings.append(f"candidate from unknown source {candidate.source_id!r}")
            continue

        provider = _resolve_provider(candidate, provider_index, alias_table)
        if provider is None:
            continue

        evidence = ClaimEvidenceRecord(
            source_id=context.source_id,
            source_level=context.source_level,
            source_record_url=candidate.source_record_url or context.source_record_url,
            excerpt=candidate.evidence_excerpt,
            observed_at=candidate.observed_at or moment,
            checked_at=moment,
            source_family=context.source_family,
        )

        # -- model ---------------------------------------------------------
        model_key: str | None = None
        if candidate.model_id:
            model_key = _upsert_model(candidate, provider, model_index, contexts, evidence, result)

        # -- offer ---------------------------------------------------------
        _upsert_offer(
            candidate,
            provider,
            model_key,
            offer_index,
            contexts,
            evidence,
            facts,
            result,
        )

        # -- provider-level claims ----------------------------------------
        for field_name in CLAIM_FIELDS:
            value = getattr(candidate, field_name, None)
            if field_name == "capabilities":
                value = [
                    c.value if hasattr(c, "value") else str(c)
                    for c in (candidate.capabilities or [])
                ]
            if value in (None, "", [], "unknown") or value is TriState.UNKNOWN:
                continue
            if hasattr(value, "value"):
                value = value.value
            claim_values[(provider.id, field_name)].append((value, evidence))

        if model_key:
            for field_name in ("context_window_tokens", "protocols", "capabilities"):
                value = getattr(candidate, field_name, None)
                if field_name == "capabilities":
                    value = [
                        c.value if hasattr(c, "value") else str(c)
                        for c in (candidate.capabilities or [])
                    ]
                if field_name == "protocols":
                    value = [
                        p.value if hasattr(p, "value") else str(p)
                        for p in (candidate.protocols or [])
                    ]
                if value in (None, "", []):
                    continue
                if hasattr(value, "value"):
                    value = value.value
                model_claim_values[(model_key, field_name, provider.id)].append((value, evidence))

    # -- 3. claims and conflicts ------------------------------------------
    result.claims = _build_claims(
        claim_values, model_claim_values, provider_index, model_index, contexts, result
    )

    # -- 4. promote verified claims onto offers ---------------------------
    _apply_claim_conclusions(offer_index, result.claims)

    result.providers = sorted(provider_index.values(), key=lambda p: p.slug)
    result.models = sorted(model_index.values(), key=lambda m: (m.provider_id, m.model_id))
    result.offers = sorted(offer_index.values(), key=lambda o: (o.provider_id, o.id))
    return result


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _build_providers(
    candidates: Iterable[CandidateRecord],
    contexts: dict[str, SourceContext],
    facts: dict[str, dict[str, dict[str, object]]],
    alias_table: dict[str, str],
    official_domain_index: dict[str, str],
) -> tuple[dict[str, ProviderRecord], list[dict[str, str]]]:
    """Create one provider per distinct domain/alias, never per display name."""
    providers: dict[str, ProviderRecord] = {}
    #: domain -> provider id, used to merge on verified official domain.
    by_domain: dict[str, str] = dict(official_domain_index)
    #: family-scoped display name -> provider id, for the alias fallback.
    by_name: dict[str, str] = {}
    merge_candidates: list[dict[str, str]] = []

    seen_pairs: list[tuple[str, str, str]] = []

    for candidate in candidates:
        context = contexts.get(candidate.source_id)
        family = context.source_family if context else "unknown"

        raw_slug = slugify(candidate.provider_name)
        canonical = alias_table.get(raw_slug, raw_slug)
        domain = normalise_host(candidate.official_url)

        provider: ProviderRecord | None = None

        # Rule 1: a verified official domain is the strongest identity signal.
        if domain and domain in by_domain:
            provider = providers.get(by_domain[domain])

        # Rule 2: the manual alias table.
        if provider is None and canonical in providers:
            provider = providers[canonical]

        # Rule 3: same-family display name, which is safe because within one
        # family the names come from one editorial voice.
        if provider is None:
            name_key = f"{family}:{normalise_name(candidate.provider_name)}"
            if name_key in by_name:
                provider = providers.get(by_name[name_key])

        if provider is None:
            provider = ProviderRecord(
                id=make_provider_id(canonical),
                slug=canonical,
                name=candidate.provider_name,
                official_domain=domain,
                homepage_url=candidate.official_url,
                signup_url=candidate.signup_url,
                docs_url=candidate.docs_url,
                aliases=[],
                domain_verified=bool(domain),
                status=EntityStatus.ACTIVE,
                source_families=[],
            )
            providers[canonical] = provider
            if domain:
                by_domain[domain] = canonical
            by_name[f"{family}:{normalise_name(candidate.provider_name)}"] = canonical
        else:
            if domain and not provider.official_domain:
                provider.official_domain = domain
                provider.domain_verified = True
                by_domain[domain] = provider.slug
            if candidate.official_url and not provider.homepage_url:
                provider.homepage_url = candidate.official_url
            if candidate.signup_url and not provider.signup_url:
                provider.signup_url = candidate.signup_url
            if candidate.docs_url and not provider.docs_url:
                provider.docs_url = candidate.docs_url
            if candidate.provider_name != provider.name:
                if candidate.provider_name not in provider.aliases:
                    provider.aliases.append(candidate.provider_name)

        if family not in provider.source_families:
            provider.source_families.append(family)

        seen_pairs.append((provider.slug, candidate.provider_name, family))

    # Attach provider-level facts gathered by the adapters.
    for source_id, per_provider in facts.items():
        context = contexts.get(source_id)
        if context is None:
            continue
        for raw_slug, fact in per_provider.items():
            canonical = alias_table.get(raw_slug, raw_slug)
            provider = providers.get(canonical)
            if provider is None:
                continue
            if not provider.official_domain and fact.get("official_domain"):
                domain = str(fact["official_domain"])
                existing = by_domain.get(domain)
                if existing and existing != provider.slug:
                    merge_candidates.append(
                        {
                            "reason": "same official domain claimed by two providers",
                            "left": existing,
                            "right": provider.slug,
                            "domain": domain,
                        }
                    )
                else:
                    provider.official_domain = domain
                    provider.domain_verified = True
                    by_domain[domain] = provider.slug
            if not provider.homepage_url and fact.get("homepage_url"):
                provider.homepage_url = str(fact["homepage_url"])
            if not provider.signup_url and fact.get("signup_url"):
                provider.signup_url = str(fact["signup_url"])

    # Flag name collisions across DIFFERENT families. These are reported, never
    # auto-merged, because two aggregators may legitimately use the same words.
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for slug, name, family in seen_pairs:
        grouped[normalise_name(name)].append((slug, name, family))
    for _key, entries in grouped.items():
        slugs = {entry[0] for entry in entries}
        families = {entry[2] for entry in entries}
        if len(slugs) > 1 and len(families) > 1:
            merge_candidates.append(
                {
                    "reason": "same display name used by providers in different source families",
                    "name": entries[0][1],
                    "slugs": ",".join(sorted(slugs)),
                    "families": ",".join(sorted(families)),
                    "note": "not merged automatically; add an alias in config/aliases.yaml",
                }
            )

    return providers, merge_candidates


def _resolve_provider(
    candidate: CandidateRecord,
    providers: dict[str, ProviderRecord],
    alias_table: dict[str, str],
) -> ProviderRecord | None:
    raw_slug = slugify(candidate.provider_name)
    canonical = alias_table.get(raw_slug, raw_slug)
    provider = providers.get(canonical)
    if provider is not None:
        return provider
    domain = normalise_host(candidate.official_url)
    if domain:
        for entry in providers.values():
            if entry.official_domain and entry.official_domain == domain:
                return entry
    return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _upsert_model(
    candidate: CandidateRecord,
    provider: ProviderRecord,
    index: dict[tuple[str, str], ModelRecord],
    contexts: dict[str, SourceContext],
    evidence: ClaimEvidenceRecord,
    result: NormalisationResult,
) -> str:
    """Model identity is (provider, exact upstream model_id)."""
    upstream = candidate.model_id or ""
    key = (provider.slug, upstream)

    model = index.get(key)
    if model is None:
        capabilities = list(candidate.capabilities or [])
        model = ModelRecord(
            id=make_model_id(provider.slug, upstream),
            provider_id=provider.id,
            model_id=upstream,
            display_name=candidate.display_name or upstream,
            declared_capabilities=capabilities,
            capabilities_unknown=not capabilities,
            context_window_tokens=candidate.context_window_tokens,
            protocols=list(candidate.protocols) or default_protocols(candidate.api_format),
            free=True,
            status=EntityStatus.ACTIVE,
        )
        index[key] = model
        return model.id

    # Merge: fill gaps, never downgrade a known value to unknown.
    if not model.declared_capabilities and candidate.capabilities:
        model.declared_capabilities = list(candidate.capabilities)
        model.capabilities_unknown = False
    if model.context_window_tokens is None and candidate.context_window_tokens:
        model.context_window_tokens = candidate.context_window_tokens
    for protocol in candidate.protocols or default_protocols(candidate.api_format):
        if protocol not in model.protocols:
            model.protocols.append(protocol)
    if candidate.display_name and len(candidate.display_name) > len(model.display_name):
        if candidate.display_name not in model.display_name:
            model.display_name = candidate.display_name
    return model.id


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


def _upsert_offer(
    candidate: CandidateRecord,
    provider: ProviderRecord,
    model_key: str | None,
    index: dict[str, OfferRecord],
    contexts: dict[str, SourceContext],
    evidence: ClaimEvidenceRecord,
    facts: dict[str, dict[str, dict[str, object]]],
    result: NormalisationResult,
) -> str:
    """Create or merge an offer.

    Critically: when ``candidate.model_id`` is absent the offer stays
    provider-level (``model_id = null``). It is NOT copied onto each model.
    """
    offer_type = (
        candidate.offer_type.value
        if hasattr(candidate.offer_type, "value")
        else str(candidate.offer_type)
    )
    oid = make_offer_id(provider.slug, candidate.model_id, offer_type)

    offer = index.get(oid)
    if offer is None:
        facts_for_provider = _facts_for(facts, contexts, provider)
        base_url = candidate.base_url or facts_for_provider.get("base_url")
        offer = OfferRecord(
            id=oid,
            provider_id=provider.id,
            model_id=model_key,
            model_ids=[model_key] if model_key else [],
            offer_type=offer_type,
            info_status=InfoStatus.DIRECTORY_CLAIM,
            conditions=ConditionsRecord(
                credit_card=_tri(candidate.credit_card),
                phone_verification=_tri(candidate.phone_verification),
                registration=_tri(candidate.registration),
                topup_required=_tri(candidate.topup_required),
                topup_minimum=candidate.topup_minimum,
                notes=candidate.condition_notes,
            ),
            quota=QuotaRecord(
                value=candidate.quota_value,
                unit=candidate.quota_unit,
                period=candidate.quota_period,
                raw=candidate.quota_raw or "",
            ),
            rate_limits=list(candidate.rate_limits),
            region=list(candidate.region),
            ends_on=candidate.ends_on,
            base_url=base_url,
            evidence=[evidence],
            reviewed_at=None,
        )
        index[oid] = offer
        return oid

    # Merge evidence from additional sources.
    if not any(
        item.source_id == evidence.source_id and item.excerpt == evidence.excerpt
        for item in offer.evidence
    ):
        offer.evidence.append(evidence)

    # Conditions tighten monotonically: a "need" from any source is never
    # softened to "not_need" by a silent source.
    offer.conditions.credit_card = _tighten(
        offer.conditions.credit_card, _tri(candidate.credit_card)
    )
    offer.conditions.phone_verification = _tighten(
        offer.conditions.phone_verification, _tri(candidate.phone_verification)
    )
    offer.conditions.registration = _tighten(
        offer.conditions.registration, _tri(candidate.registration)
    )
    offer.conditions.topup_required = _tighten(
        offer.conditions.topup_required, _tri(candidate.topup_required)
    )

    if offer.quota.value is None and candidate.quota_value is not None:
        offer.quota = QuotaRecord(
            value=candidate.quota_value,
            unit=candidate.quota_unit,
            period=candidate.quota_period,
            raw=candidate.quota_raw or offer.quota.raw,
        )
    elif (
        candidate.quota_value is not None
        and offer.quota.value is not None
        and candidate.quota_value != offer.quota.value
        and candidate.quota_unit == offer.quota.unit
        and candidate.quota_period == offer.quota.period
    ):
        # Same unit and period but a different number: two directories disagree.
        _mark_conflict(offer, "quota")
        result.warnings.append(
            f"quota conflict for {provider.slug}: "
            f"{offer.quota.value} vs {candidate.quota_value} ({offer.quota.unit})"
        )

    if offer.base_url and candidate.base_url and offer.base_url != candidate.base_url:
        _mark_base_url_conflict(offer, candidate.base_url, result, provider.slug)
    elif not offer.base_url and candidate.base_url:
        offer.base_url = candidate.base_url

    for limit in candidate.rate_limits:
        if limit not in offer.rate_limits:
            offer.rate_limits.append(limit)

    if model_key and model_key not in offer.model_ids:
        offer.model_ids.append(model_key)

    if not candidate.model_id and offer.model_id is None and model_key is None:
        # Provider-level offer confirmed; nothing to attach.
        pass

    return oid


def _facts_for(
    facts: dict[str, dict[str, dict[str, object]]],
    contexts: dict[str, SourceContext],
    provider: ProviderRecord,
) -> dict[str, object]:
    """Merge provider-level facts from every source that knows this provider."""
    merged: dict[str, object] = {}
    for source_id, per_provider in facts.items():
        if source_id not in contexts:
            continue
        for raw_slug, fact in per_provider.items():
            if slugify(raw_slug) != provider.slug:
                continue
            for key, value in fact.items():
                if key not in merged or merged[key] in (None, "", [], {}):
                    if value not in (None, "", [], {}):
                        merged[key] = value
    return merged


def _tri(value: object) -> TriState:
    if isinstance(value, TriState):
        return value
    text = str(value or "unknown")
    try:
        return TriState(text)
    except ValueError:
        return TriState.UNKNOWN


def _tighten(current: TriState, incoming: TriState) -> TriState:
    """Combine two tri-states so that an explicit answer wins over silence.

    ``need`` and ``not_need`` are genuine answers; ``unknown`` is absence of
    information. Two conflicting answers stay as the first answer and the
    conflict is surfaced separately rather than being silently resolved.
    """
    if current == TriState.UNKNOWN:
        return incoming
    if incoming == TriState.UNKNOWN:
        return current
    return current


def _mark_conflict(offer: OfferRecord, field: str) -> None:
    offer.info_status = InfoStatus.SOURCE_CONFLICT
    offer.needs_review = True


def _mark_base_url_conflict(
    offer: OfferRecord,
    candidate_url: str,
    result: NormalisationResult,
    provider_slug: str,
) -> None:
    """A disagreeing Base URL is a call-affecting conflict, so it is surfaced."""
    offer.info_status = InfoStatus.SOURCE_CONFLICT
    offer.needs_review = True
    result.review_queue.append(
        {
            "provider_slug": provider_slug,
            "field": "base_url",
            "existing": offer.base_url,
            "candidate": candidate_url,
            "reason": "sources disagree on the API base URL",
        }
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def _build_claims(
    provider_claims: dict[tuple[str, str], list[tuple[object, ClaimEvidenceRecord]]],
    model_claims: dict[tuple[str, str, str], list[tuple[object, ClaimEvidenceRecord]]],
    providers: dict[str, ProviderRecord],
    models: dict[tuple[str, str], ModelRecord],
    contexts: dict[str, SourceContext],
    result: NormalisationResult,
) -> list[ClaimRecord]:
    """Materialise claims and detect cross-family disagreement."""
    claims: list[ClaimRecord] = []

    for (provider_id_value, field_name), entries in provider_claims.items():
        provider = next((p for p in providers.values() if p.id == provider_id_value), None)
        if provider is None:
            continue
        claims.extend(
            _claims_for(
                entries,
                subject_type="provider",
                subject_id=provider.id,
                subject_key=provider.slug,
                field=field_name,
                result=result,
            )
        )

    for (model_key, field_name, provider_id_value), entries in model_claims.items():
        model = models.get((provider_id_value, model_key))
        if model is None:
            model = next((m for m in models.values() if m.id == model_key), None)
        if model is None:
            continue
        claims.extend(
            _claims_for(
                entries,
                subject_type="model",
                subject_id=model.id,
                subject_key=model.model_id,
                field=field_name,
                result=result,
            )
        )

    return claims


def _claims_for(
    entries: list[tuple[object, ClaimEvidenceRecord]],
    *,
    subject_type: str,
    subject_id: str,
    subject_key: str,
    field: str,
    result: NormalisationResult,
) -> list[ClaimRecord]:
    """One claim per (evidence, value) with cross-family conflicts noted."""
    claims: list[ClaimRecord] = []
    # family -> list of values, so a mirror of the same upstream counts once.
    by_family: dict[str, list[object]] = defaultdict(list)
    representatives: dict[str, ClaimEvidenceRecord] = {}

    for value, evidence in entries:
        family = evidence.source_family or evidence.source_id
        by_family[family].append(value)
        representatives.setdefault(family, evidence)

    families = sorted(by_family)
    distinct_values: set[str] = set()
    # Only the values matter here; the family grouping was already applied by
    # building `by_family` above.
    for values in by_family.values():
        for value in values:
            distinct_values.add(short_hash(value))

    conflict = len(distinct_values) > 1 and len(families) > 1

    for family, values in by_family.items():
        evidence = representatives[family]
        primary = values[0]
        cid = claim_id(evidence.source_id, subject_type, subject_key, field)
        status = (
            ReviewStatus.NEEDS_REVIEW
            if conflict
            else (
                ReviewStatus.OFFICIAL_CONFIRMED
                if evidence.source_level == SourceLevel.OFFICIAL
                else ReviewStatus.DIRECTORY_CLAIM
            )
        )
        claims.append(
            ClaimRecord(
                id=cid,
                subject_type=subject_type,  # type: ignore[arg-type]
                subject_id=subject_id,
                field=field,
                value=_serialisable(primary),
                evidence=evidence,
                review_status=status,
            )
        )

    if conflict:
        result.warnings.append(
            f"cross-source conflict on {subject_type} {subject_key} field {field}: "
            f"{len(distinct_values)} distinct values across {len(families)} families"
        )
        result.review_queue.append(
            {
                "subject_type": subject_type,
                "subject_key": subject_key,
                "field": field,
                "reason": "sources disagree",
                "values": [
                    {"family": family, "value": _serialisable(values[0])}
                    for family, values in sorted(by_family.items())
                ],
            }
        )
    return claims


def _serialisable(value: object) -> object:
    if isinstance(value, list | tuple):
        return [_serialisable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _apply_claim_conclusions(offers: dict[str, OfferRecord], claims: list[ClaimRecord]) -> None:
    """Let confirmed official claims override the directory defaults.

    Only claims whose status is ``official_confirmed`` move an offer to
    confirmed. Everything else stays a directory claim until a maintainer acts
    through ``config/reviews.yaml``.
    """
    confirmed_subjects = {
        claim.subject_id
        for claim in claims
        if claim.review_status == ReviewStatus.OFFICIAL_CONFIRMED
    }
    for offer in offers.values():
        if offer.info_status == InfoStatus.SOURCE_CONFLICT:
            continue
        if offer.provider_id in confirmed_subjects:
            offer.info_status = InfoStatus.OFFICIAL_CONFIRMED


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def mark_staleness(
    offers: list[OfferRecord],
    provider_records: list[ProviderRecord],
    source_states: list[SourceStateRecord],
    *,
    now: str | None = None,
    source_stale_hours: int = 168,
    offer_stale_days: int = 30,
) -> None:
    """Apply the staleness thresholds from the task book.

    * a provider is stale when no source has successfully checked it for
      ``source_stale_hours``
    * an offer needs review when its free conditions were not re-verified for
      ``offer_stale_days``
    """
    from datetime import timedelta

    moment = _parse(now) or utcnow()
    success_times = [
        _parse(state.last_success_at)
        for state in source_states
        if state.enabled and state.last_success_at
    ]
    success_times = [item for item in success_times if item is not None]
    latest = max(success_times) if success_times else None

    if latest is not None and (moment - latest) > timedelta(hours=source_stale_hours):
        for provider in provider_records:
            if provider.status == EntityStatus.ACTIVE:
                provider.status = EntityStatus.STALE

    for offer in offers:
        reference = _parse(offer.reviewed_at)
        if reference is None:
            evidence_times = [_parse(item.observed_at) for item in offer.evidence]
            evidence_times = [item for item in evidence_times if item is not None]
            reference = max(evidence_times) if evidence_times else None
        if reference is not None and (moment - reference) > timedelta(days=offer_stale_days):
            offer.stale = True
            if offer.info_status not in {InfoStatus.SOURCE_CONFLICT, InfoStatus.OFFICIAL_CONFIRMED}:
                offer.needs_review = True


def _parse(value: str | None) -> object | None:
    from .ids import parse_iso

    return parse_iso(value)

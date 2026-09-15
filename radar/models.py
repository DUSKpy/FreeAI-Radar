"""Pydantic models for the internal and public data shapes.

Two families live here:

``CandidateRecord``
    What an adapter emits, before any cross-source reconciliation. Kept loose
    because sources vary; the task book's example record is a subset of it.

``*Record`` / ``*Public``
    The normalized entities that get persisted and exported. These are strict:
    every field the public contract promises exists here.

The export step copies through an explicit allowlist, so nothing here should be
assumed to reach the browser untouched.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .vocab import (
    AccessType,
    CallStatus,
    CapabilityTag,
    EntityStatus,
    InfoStatus,
    OfferType,
    Protocol,
    QuotaPeriod,
    QuotaUnit,
    ReviewDecision,
    ReviewStatus,
    SourceLevel,
    SourceStatus,
    SourceType,
    TriState,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Adapter output
# ---------------------------------------------------------------------------


class CandidateRecord(Strict):
    """One row parsed out of one source.

    This is a *claim*, not a fact. It carries the excerpt that justifies it so
    the browser can show evidence and so reviewers can act on it.
    """

    source_id: str
    source_record_url: str
    provider_name: str

    official_url: str | None = None
    signup_url: str | None = None
    docs_url: str | None = None
    base_url: str | None = None

    model_id: str | None = None
    display_name: str | None = None
    context_window_tokens: int | None = None

    access_type: AccessType = AccessType.API
    offer_type: OfferType = OfferType.UNKNOWN

    quota_raw: str | None = None
    quota_value: float | None = None
    quota_unit: QuotaUnit = QuotaUnit.UNKNOWN
    quota_period: QuotaPeriod = QuotaPeriod.UNKNOWN

    rate_limits: list[dict[str, Any]] = Field(default_factory=list)

    credit_card: TriState = TriState.UNKNOWN
    phone_verification: TriState = TriState.UNKNOWN
    registration: TriState = TriState.UNKNOWN
    topup_required: TriState = TriState.UNKNOWN
    topup_minimum: str | None = None
    condition_notes: str | None = None

    api_format: str = "unknown"
    protocols: list[Protocol] = Field(default_factory=list)

    capabilities: list[CapabilityTag] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    ends_on: str | None = None

    free_model_count: int | None = None
    modalities: list[str] = Field(default_factory=list)

    evidence_excerpt: str = ""
    observed_at: str

    @field_validator("evidence_excerpt")
    @classmethod
    def _trim_excerpt(cls, value: str) -> str:
        # Only short evidence is retained. Full page mirrors are never stored.
        collapsed = " ".join((value or "").split())
        return collapsed[:400]

    @field_validator("provider_name", "display_name", "model_id")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Normalized entities
# ---------------------------------------------------------------------------


class ProviderRecord(Strict):
    """A provider is either an original vendor or an aggregator, never merged blindly."""

    id: str
    slug: str
    name: str
    official_domain: str | None = None
    homepage_url: str | None = None
    signup_url: str | None = None
    docs_url: str | None = None
    aliases: list[str] = Field(default_factory=list)
    domain_verified: bool = False
    status: EntityStatus = EntityStatus.ACTIVE
    #: Distinct source families that independently attest this provider.
    #: Two mirrors of one upstream count once.
    source_families: list[str] = Field(default_factory=list)


class ModelRecord(Strict):
    id: str
    provider_id: str
    model_id: str
    display_name: str
    declared_capabilities: list[CapabilityTag] = Field(default_factory=list)
    capabilities_unknown: bool = True
    context_window_tokens: int | None = None
    protocols: list[Protocol] = Field(default_factory=list)
    streaming: TriState = TriState.UNKNOWN
    tool_calling: TriState = TriState.UNKNOWN
    multimodal: TriState = TriState.UNKNOWN
    free: bool = False
    status: EntityStatus = EntityStatus.ACTIVE


class QuotaRecord(Strict):
    """Numeric value plus unit plus period plus the original wording.

    Units are never force-converted between each other.
    """

    value: float | None = None
    unit: QuotaUnit = QuotaUnit.UNKNOWN
    period: QuotaPeriod = QuotaPeriod.UNKNOWN
    raw: str = ""

    @field_validator("value")
    @classmethod
    def _no_zero_for_unknown(cls, value: float | None) -> float | None:
        # Unknown is null. Writing 0 would read as "no quota at all".
        return value


class ConditionsRecord(Strict):
    credit_card: TriState = TriState.UNKNOWN
    phone_verification: TriState = TriState.UNKNOWN
    registration: TriState = TriState.UNKNOWN
    topup_required: TriState = TriState.UNKNOWN
    topup_minimum: str | None = None
    notes: str | None = None


class ClaimEvidenceRecord(Strict):
    source_id: str
    source_level: SourceLevel
    source_record_url: str
    excerpt: str
    observed_at: str
    checked_at: str | None = None
    http_status: int | None = None
    source_family: str | None = None


class OfferRecord(Strict):
    id: str
    provider_id: str
    model_id: str | None = None
    #: Only populated when a source explicitly enumerates the covered models.
    #: A provider-level quota is NOT copied onto every model.
    model_ids: list[str] = Field(default_factory=list)
    offer_type: OfferType = OfferType.UNKNOWN
    info_status: InfoStatus = InfoStatus.DIRECTORY_CLAIM
    call_status: CallStatus = CallStatus.UNTESTED
    conditions: ConditionsRecord = Field(default_factory=ConditionsRecord)
    quota: QuotaRecord = Field(default_factory=QuotaRecord)
    rate_limits: list[dict[str, Any]] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    ends_on: str | None = None
    effective_from: str | None = None
    base_url: str | None = None
    evidence: list[ClaimEvidenceRecord] = Field(default_factory=list)
    reviewed_at: str | None = None
    stale: bool = False
    needs_review: bool = False


class ClaimRecord(Strict):
    id: str
    subject_type: Literal["provider", "model", "offer"]
    subject_id: str
    field: str
    value: Any = None
    evidence: ClaimEvidenceRecord
    review_status: ReviewStatus = ReviewStatus.DIRECTORY_CLAIM
    conflict_with: list[str] = Field(default_factory=list)


class ReviewRecord(Strict):
    id: str
    claim_id: str | None = None
    claim_fingerprint: str
    decision: ReviewDecision
    reason: str | None = None
    reviewer: str | None = None
    created_at: str
    evidence_url: str | None = None
    scope: dict[str, Any] = Field(
        default_factory=lambda: {"region": [], "plan": None, "model_id": None}
    )


class ChangeRecord(Strict):
    id: str
    fingerprint: str
    subject_type: Literal["provider", "model", "offer", "source"]
    subject_id: str
    subject_label: str | None = None
    provider_id: str | None = None
    field: str
    old_value: Any = None
    new_value: Any = None
    change_type: str
    detected_at: str
    observed_at: str
    source_id: str
    evidence_fingerprint: str | None = None
    evidence_ref: str | None = None
    confirmed: bool = False
    note: str | None = None


class SnapshotRecord(Strict):
    """Persisted snapshot metadata. Holds hashes and short extracts only."""

    id: str
    source_id: str
    fetched_at: str
    http_status: int | None = None
    content_hash: str
    etag: str | None = None
    last_modified: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)


class SourceStateRecord(Strict):
    id: str
    name: str
    url: str
    type: SourceType
    source_family: str
    enabled: bool = True
    parser: str
    parser_version: str = "1.0.0"
    allowed_domains: list[str] = Field(default_factory=list)
    license: str | None = None
    license_url: str | None = None
    terms_url: str | None = None
    first_checked_at: str | None = None
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    status: SourceStatus = SourceStatus.NEVER_RUN
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    record_count: int | None = None
    last_record_count: int | None = None
    stale: bool = False


class SourceResult(Strict):
    source_id: str
    status: Literal["ok", "not_modified", "failed", "parse_error", "skipped"]
    http_status: int | None = None
    record_count: int | None = None
    error: str | None = None


class JobRunRecord(Strict):
    id: str
    job_type: str
    started_at: str
    finished_at: str
    outcome: str
    counts: dict[str, int] = Field(default_factory=dict)
    source_results: list[SourceResult] = Field(default_factory=list)


class CollectionMeta(Strict):
    last_successful_collection_at: str | None = None
    last_complete_collection_at: str | None = None
    initial_import_done: bool = False
    retention_days: int = 90
    null_result_streaks: dict[str, int] = Field(default_factory=dict)


class RadarState(Strict):
    """The whole persisted state. Kept compact on purpose."""

    schema_version: int = 1
    state_version: str = "sha256:0"
    created_at: str
    updated_at: str
    runs: list[JobRunRecord] = Field(default_factory=list)
    sources: list[SourceStateRecord] = Field(default_factory=list)
    snapshots: list[SnapshotRecord] = Field(default_factory=list)
    providers: list[ProviderRecord] = Field(default_factory=list)
    models: list[ModelRecord] = Field(default_factory=list)
    offers: list[OfferRecord] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    reviews: list[ReviewRecord] = Field(default_factory=list)
    changes: list[ChangeRecord] = Field(default_factory=list)
    collection_meta: CollectionMeta = Field(default_factory=CollectionMeta)

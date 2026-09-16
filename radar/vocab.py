"""Shared domain vocabulary for FreeAI Radar.

Every enum here exists to keep concepts that are easy to conflate separate.
The task book is explicit that these must never be merged:

* access type is NOT free type (a web-only chat is not a free API)
* free type is NOT info status (a directory claim is not official confirmation)
* info status is NOT call status (docs verified is not a successful call)
* agent compatibility is a three-part ladder, not one boolean

Unknown is always representable and is never coerced into a negative answer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

STATE_SCHEMA_VERSION: Final[int] = 1

#: Retention window for the change log persisted on the catalog-data branch.
DEFAULT_RETENTION_DAYS: Final[int] = 90

#: A source whose last successful check is older than this is shown as stale.
DEFAULT_STALE_SOURCE_HOURS: Final[int] = 168  # 7 days

#: An offer whose free conditions were not re-reviewed within this window
#: is flagged needs_review. Configurable.
DEFAULT_STALE_OFFER_DAYS: Final[int] = 30

#: Same-source manual refresh cooldown.
DEFAULT_MANUAL_COOLDOWN_MINUTES: Final[int] = 10

#: Polling / fetch guardrails required by the task book.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 20.0
DEFAULT_MAX_BODY_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MiB decompressed
DEFAULT_PER_DOMAIN_CONCURRENCY: Final[int] = 1
DEFAULT_GLOBAL_CONCURRENCY: Final[int] = 3


class TriState(StrEnum):
    """Three-valued logic for conditions.

    ``UNKNOWN`` must survive all the way to the UI. Reading a missing mention
    in official docs as ``NOT_NEED`` is explicitly forbidden by the task book.
    """

    NEED = "need"
    NOT_NEED = "not_need"
    UNKNOWN = "unknown"


class AccessType(StrEnum):
    """How a user reaches the service."""

    API = "api"
    WEB_CHAT_ONLY = "web_chat_only"
    LOCAL = "local"
    UNKNOWN = "unknown"


class OfferType(StrEnum):
    """What kind of free thing this is.

    "Free forever" is never modelled. The closest honest value is
    ``SUSTAINED_FREE_TIER``, meaning the currently published policy has an
    ongoing free tier -- which can change.
    """

    SUSTAINED_FREE_TIER = "sustained_free_tier"
    RECURRING_FREE_CREDIT = "recurring_free_credit"
    ONE_TIME_TRIAL = "one_time_trial"
    LIMITED_TIME_PROMO = "limited_time_promo"
    REQUIRES_TOPUP = "requires_topup"
    UNKNOWN = "unknown"


class InfoStatus(StrEnum):
    """Where the information came from and how much it is trusted."""

    DIRECTORY_CLAIM = "directory_claim"
    OFFICIAL_CONFIRMED = "official_confirmed"
    NEEDS_REVIEW = "needs_review"
    SOURCE_CONFLICT = "source_conflict"
    EXPIRED = "expired"


class CallStatus(StrEnum):
    """Result of an actual network call. Untested by default."""

    UNTESTED = "untested"
    SUCCESS = "success"
    CREDENTIAL_ERROR = "credential_error"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    NETWORK_ERROR = "network_error"
    SERVICE_ERROR = "service_error"


class Protocol(StrEnum):
    """Wire protocols stored independently.

    A single "OpenAI compatible" boolean is not enough: only supporting Chat
    Completions does not mean a service works on a path that needs Responses.
    """

    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_NATIVE = "gemini_native"


class CapabilityTag(StrEnum):
    """Capability labels declared by a source.

    Never inferred from a model's name. If nothing is declared the model
    records ``capabilities_unknown = True`` instead of receiving invented scores.
    """

    CODING = "coding"
    REASONING = "reasoning"
    VISION = "vision"
    AUDIO = "audio"
    EMBEDDING = "embedding"
    IMAGE = "image"
    VIDEO = "video"
    PDF = "pdf"
    RERANK = "rerank"
    TEXT = "text"


class QuotaUnit(StrEnum):
    REQUESTS = "requests"
    TOKENS = "tokens"
    NEURONS = "neurons"
    CREDITS_USD = "credits_usd"
    AUDIO_SECONDS = "audio_seconds"
    MESSAGES = "messages"
    UNKNOWN = "unknown"


class QuotaPeriod(StrEnum):
    PER_SECOND = "per_second"
    PER_MINUTE = "per_minute"
    PER_HOUR = "per_hour"
    PER_DAY = "per_day"
    PER_MONTH = "per_month"
    WEEKLY = "weekly"
    SESSION = "session"
    ONE_TIME = "one_time"
    UNKNOWN = "unknown"


class CapabilityLevel(StrEnum):
    """Three-level agent compatibility ladder.

    These three must never be presented as one thing. Importing a config file
    is not protocol verification, and protocol verification is not a passing
    real call.
    """

    CONFIG_IMPORTABLE = "config_importable"
    PROTOCOL_VERIFIED = "protocol_verified"
    CALL_VERIFIED = "call_verified"


class SourceType(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"
    JSON = "json"
    API = "api"
    RSS = "rss"


class SourceStatus(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"
    FAILED = "failed"
    PARSE_ERROR = "parse_error"
    NEVER_RUN = "never_run"
    STALE = "stale"


class SourceLevel(StrEnum):
    """Evidence weight. Mirrors of the same upstream content are not独立 evidence."""

    OFFICIAL = "official"
    DIRECTORY = "directory"
    MIRROR = "mirror"


class ReviewDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    NEEDS_REVIEW = "needs_review"


class ReviewStatus(StrEnum):
    DIRECTORY_CLAIM = "directory_claim"
    OFFICIAL_CONFIRMED = "official_confirmed"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ChangeType(StrEnum):
    """Change taxonomy. A source dropping an entry is never reported as an API shutdown."""

    INITIAL_IMPORT = "initial_import"
    NEW_PROVIDER = "new_provider"
    NEW_MODEL = "new_model"
    QUOTA_CHANGED = "quota_changed"
    CONDITION_CHANGED = "condition_changed"
    OFFICIAL_CONFLICT = "official_conflict"
    PROMO_ENDED = "promo_ended"
    MISSING_FROM_SOURCE = "missing_from_source"
    REAPPEARED = "reappeared"
    REVIEW_CONFIRMED = "review_confirmed"
    REVIEW_REJECTED = "review_rejected"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    CONFLICT = "conflict"
    REMOVED_FROM_SOURCE = "removed_from_source"


class JobOutcome(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobType(StrEnum):
    COLLECT = "collect"
    BUILD_ONLY = "build_only"
    INITIAL_IMPORT = "initial_import"
    ROLLBACK = "rollback"


class CCApp(StrEnum):
    """Target applications understood by the CC Switch ``app`` deep link param.

    Sourced from the official V1 protocol documentation, anchored in
    docs/cc-switch.md. Values outside this list cannot be linked.
    """

    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    OPENCODE = "opencode"
    OPENCLAW = "openclaw"


class CCResource(StrEnum):
    PROVIDER = "provider"
    MCP = "mcp"
    PROMPT = "prompt"
    SKILL = "skill"


class CCStatus(StrEnum):
    """Outcome of building a CC Switch import payload."""

    READY = "ready"
    READY_WITHOUT_KEY = "ready_without_key"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    MISSING_FIELDS = "missing_fields"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"

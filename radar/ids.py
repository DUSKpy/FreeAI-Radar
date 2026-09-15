"""Deterministic ids and content hashes.

Ids never depend on display names or sort order, so renaming a provider's
display name does not orphan its records. Slugs keep aliases instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

#: Fields stripped before hashing a payload to decide *semantic* change.
#: ``generated_at`` and friends must never make two identical datasets differ.
VOLATILE_FIELDS = frozenset(
    {
        "generated_at",
        "build_commit",
        "finished_at",
        "started_at",
        "last_attempt_at",
        "checked_at",
        "job_run_id",
        "run_id",
    }
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    """ISO 8601 with a trailing Z, second precision."""
    moment = value or utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def canonical_json(payload: Any, *, drop_volatile: bool = True) -> str:
    """Stable JSON used for hashing.

    Key order is normalized so that dict insertion order cannot fake a change.
    """

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if drop_volatile and key in VOLATILE_FIELDS:
                    continue
                out[key] = scrub(value)
            return {key: out[key] for key in sorted(out)}
        if isinstance(node, list):
            return [scrub(item) for item in node]
        return node

    return json.dumps(scrub(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(payload: Any, *, drop_volatile: bool = True) -> str:
    digest = hashlib.sha256(
        canonical_json(payload, drop_volatile=drop_volatile).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def short_hash(*parts: Any, length: int = 16) -> str:
    """Deterministic short hex digest over arbitrary parts."""
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(canonical_json(part).encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()[:length]


def slugify(text: str, *, fallback: str = "unknown") -> str:
    """ASCII slug. Non-ASCII input yields the fallback rather than mojibake."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_only).strip("-")
    return slug or fallback


def normalise_name(text: str) -> str:
    """Loose key for alias matching. Display-name merging is never automatic."""
    lowered = (text or "").casefold()
    stripped = re.sub(r"[\s_\-.:()（）【】\[\]/|,，]+", "", lowered)
    return stripped or "unknown"


def provider_id(slug: str) -> str:
    return f"p_{slug}"


def model_id(provider_slug: str, upstream_model_id: str) -> str:
    """Unique key is (provider, exact model_id). Display names never feed this."""
    return f"m_{short_hash(provider_slug, upstream_model_id)}"


def offer_id(provider_slug: str, upstream_model_id: str | None, offer_type: str) -> str:
    return f"o_{short_hash(provider_slug, upstream_model_id or '', offer_type)}"


def claim_id(
    source_id: str,
    subject_type: str,
    subject_key: str,
    field: str,
) -> str:
    return f"c_{short_hash(source_id, subject_type, subject_key, field)}"


def change_fingerprint(
    subject_type: str,
    subject_id: str,
    field: str,
    old_value: Any,
    new_value: Any,
    evidence_fingerprint: str | None,
) -> str:
    """Idempotency key for a change event.

    Re-running a collection over unchanged input produces the same fingerprint
    and therefore adds nothing. A *later* change to the same field yields a
    different fingerprint and is kept as an independent event.
    """
    return "fp_" + short_hash(
        subject_type, subject_id, field, old_value, new_value, evidence_fingerprint or ""
    )


def claim_fingerprint(
    subject_type: str,
    subject_key: str,
    field: str,
    source_level: str,
    excerpt: str,
) -> str:
    """Fingerprint of a verified field, bound to its evidence.

    When the evidence text changes the fingerprint changes, which is what moves
    an old review into ``needs_review`` instead of leaving it verified forever.
    """
    return "rf_" + short_hash(
        subject_type, subject_key, field, source_level, (excerpt or "").strip()
    )


def change_id(fingerprint: str, detected_at: str) -> str:
    return f"ch_{short_hash(fingerprint, detected_at)}"


def snapshot_id(source_id: str, content_hash_value: str) -> str:
    return f"sn_{short_hash(source_id, content_hash_value)}"


def run_id(job_type: str, started_at: str) -> str:
    return f"run_{short_hash(job_type, started_at)}"


def shanghai_date(value: datetime | str | None = None) -> str:
    """Daily reports use the Asia/Shanghai calendar day; storage stays UTC."""
    moment = value
    if moment is None:
        moment = utcnow()
    if isinstance(moment, str):
        parsed = parse_iso(moment)
        moment = utcnow() if parsed is None else parsed
    assert isinstance(moment, datetime)
    # Fixed +08:00 offset. China does not observe daylight saving.
    from datetime import timedelta

    return (moment.astimezone(UTC) + timedelta(hours=8)).strftime("%Y-%m-%d")

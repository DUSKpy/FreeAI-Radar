"""Configuration loading and validation.

Loads ``config/sources.yaml``, ``config/reviews.yaml`` and the optional alias
table. Validation is strict and loud:

* ``parser`` must reference a parser registered in this project -- remote
  scripts are never executed
* ``id``, ``url`` and ``source_family`` are required
* duplicate ids are refused
* an unknown entity or illegal field in ``reviews.yaml`` is a *build failure*,
  not a warning, because a stale override silently outranking real data is
  exactly the failure mode the task book warns about
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .collectors.base import PARSER_REGISTRY, get_adapter
from .ids import parse_iso, slugify
from .textutil import normalise_host
from .vocab import DEFAULT_RETENTION_DAYS, ReviewDecision, SourceType


class ConfigError(RuntimeError):
    """Raised for any invalid configuration. Always fatal."""


@dataclass
class SourceConfig:
    id: str
    name: str
    url: str
    type: str
    source_family: str
    parser: str
    enabled: bool = True
    role: str = "directory"
    allowed_domains: list[str] = field(default_factory=list)
    mirrors: list[str] = field(default_factory=list)
    license: str | None = None
    license_url: str | None = None
    terms_url: str | None = None
    provider_slug: str | None = None
    notes: str | None = None
    parser_version: str = "1.0.0"

    @property
    def source_level(self) -> str:
        return "official" if self.role == "official" else "directory"


@dataclass
class FetchDefaults:
    timeout_seconds: float = 20.0
    max_body_bytes: int = 5 * 1024 * 1024
    per_domain_concurrency: int = 1
    global_concurrency: int = 3
    manual_cooldown_minutes: int = 10
    daily_collection: bool = True
    respect_retry_after: bool = True
    follow_redirects: bool = True
    max_redirects: int = 4


@dataclass
class ReviewOverride:
    """A confirmed field from ``reviews.yaml``.

    ``evidence_url`` plus the scope (region / plan / model) are what make the
    confirmation applicable. The fingerprint is recomputed from those inputs,
    so a later evidence change automatically invalidates the review.
    """

    subject_type: str
    subject_key: str
    field: str
    value: Any
    decision: str
    evidence_url: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None
    region: list[str] = field(default_factory=list)
    plan: str | None = None
    model_id: str | None = None
    reason: str | None = None


@dataclass
class BuildConfig:
    staleness: dict[str, int] = field(
        default_factory=lambda: {
            "source_stale_hours": 168,
            "offer_stale_days": 30,
            "retention_days": DEFAULT_RETENTION_DAYS,
        }
    )
    site: dict[str, Any] = field(default_factory=dict)
    cc_switch: dict[str, Any] = field(default_factory=dict)


@dataclass
class RadarConfig:
    sources: list[SourceConfig]
    defaults: FetchDefaults
    aliases: dict[str, str]
    reviews: list[ReviewOverride]
    build: BuildConfig
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled_sources(self) -> list[SourceConfig]:
        return [source for source in self.sources if source.enabled]

    def by_id(self, source_id: str) -> SourceConfig | None:
        return next((s for s in self.sources if s.id == source_id), None)


def load_config(
    *,
    sources_path: str | Path,
    reviews_path: str | Path | None = None,
    aliases_path: str | Path | None = None,
) -> RadarConfig:
    """Load and validate the whole configuration set."""
    sources_file = Path(sources_path)
    if not sources_file.exists():
        raise ConfigError(f"sources config not found: {sources_file}")

    raw = _load_yaml(sources_file)
    if not isinstance(raw, dict):
        raise ConfigError(f"{sources_file} must contain a mapping")

    sources = _parse_sources(raw.get("sources"), sources_file)
    defaults = _parse_defaults(raw.get("defaults"))
    build = _parse_build(raw.get("build") or raw.get("settings") or {})

    aliases: dict[str, str] = {}
    if aliases_path is not None:
        alias_file = Path(aliases_path)
        if alias_file.exists():
            aliases = _parse_aliases(_load_yaml(alias_file), alias_file)
    # Inline aliases are also accepted inside sources.yaml.
    if raw.get("aliases"):
        aliases.update(_parse_aliases(raw["aliases"], sources_file))

    reviews: list[ReviewOverride] = []
    if reviews_path is not None:
        review_file = Path(reviews_path)
        if review_file.exists():
            reviews = _parse_reviews(_load_yaml(review_file), review_file)

    return RadarConfig(
        sources=sources,
        defaults=defaults,
        aliases=aliases,
        reviews=reviews,
        build=build,
        raw=raw if isinstance(raw, dict) else {},
    )


def _load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


def _parse_sources(entries: Any, path: Path) -> list[SourceConfig]:
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: 'sources' must be a non-empty list")

    parsed: list[SourceConfig] = []
    seen: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: sources[{index}] must be a mapping")

        for required in ("id", "url", "type", "source_family", "parser"):
            if not entry.get(required):
                raise ConfigError(f"{path}: sources[{index}] missing required key {required!r}")

        source_id = str(entry["id"]).strip()
        if source_id in seen:
            raise ConfigError(f"{path}: duplicate source id {source_id!r}")
        seen.add(source_id)

        if not _valid_source_id(source_id):
            raise ConfigError(
                f"{path}: source id {source_id!r} must match ^[a-z0-9][a-z0-9-]{{1,63}}$"
            )

        parser_name = str(entry["parser"]).strip()
        if parser_name not in PARSER_REGISTRY:
            raise ConfigError(
                f"{path}: source {source_id!r} references unregistered parser "
                f"{parser_name!r}; registered parsers: {sorted(PARSER_REGISTRY)}. "
                "Remote scripts are never executed."
            )

        source_type = str(entry["type"]).strip().lower()
        if source_type not in {member.value for member in SourceType}:
            raise ConfigError(f"{path}: source {source_id!r} has unsupported type {source_type!r}")

        role = str(entry.get("role", "directory")).strip().lower()
        if role not in {"directory", "official"}:
            raise ConfigError(
                f"{path}: source {source_id!r} role must be 'directory' or 'official'"
            )

        url = str(entry["url"]).strip()
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"{path}: source {source_id!r} url must be http(s)")

        allowed = [str(d).strip().lower() for d in (entry.get("allowed_domains") or [])]
        host = normalise_host(url)
        if (
            allowed
            and host
            and not any(host == domain or host.endswith("." + domain) for domain in allowed)
        ):
            raise ConfigError(
                f"{path}: source {source_id!r} url host {host!r} is not covered by "
                f"allowed_domains {allowed}"
            )

        parsed.append(
            SourceConfig(
                id=source_id,
                name=str(entry.get("name") or source_id),
                url=url,
                type=source_type,
                source_family=str(entry["source_family"]).strip(),
                parser=parser_name,
                enabled=bool(entry.get("enabled", True)),
                role=role,
                allowed_domains=allowed,
                mirrors=[str(m) for m in (entry.get("mirrors") or [])],
                license=entry.get("license"),
                license_url=entry.get("license_url"),
                terms_url=entry.get("terms_url"),
                provider_slug=entry.get("provider_slug"),
                notes=entry.get("notes"),
                parser_version=str(getattr(get_adapter(parser_name), "version", "1.0.0")),
            )
        )
    return parsed


def _valid_source_id(value: str) -> bool:
    import re

    return bool(re.match(r"^[a-z0-9][a-z0-9-]{1,63}$", value))


def _parse_defaults(entries: Any) -> FetchDefaults:
    if not isinstance(entries, dict):
        return FetchDefaults()
    defaults = FetchDefaults()
    for key in (
        "timeout_seconds",
        "max_body_bytes",
        "per_domain_concurrency",
        "global_concurrency",
        "manual_cooldown_minutes",
        "respect_retry_after",
        "follow_redirects",
        "max_redirects",
        "daily_collection",
    ):
        if key in entries and entries[key] is not None:
            setattr(defaults, key, entries[key])
    return defaults


def _parse_build(entries: Any) -> BuildConfig:
    config = BuildConfig()
    if not isinstance(entries, dict):
        return config
    for key, value in entries.items():
        if key in config.staleness and isinstance(value, int):
            config.staleness[key] = value
    for key in ("site", "cc_switch"):
        if isinstance(entries.get(key), dict):
            setattr(config, key, entries[key])
    return config


def _parse_aliases(entries: Any, path: Path) -> dict[str, str]:
    """``aliases.yaml`` maps alternate slugs onto a canonical slug.

    Also accepts a nested ``{canonical: [alias, ...]}`` shape.
    """
    result: dict[str, str] = {}
    if not isinstance(entries, dict):
        raise ConfigError(f"{path}: aliases must be a mapping")

    payload = entries.get("aliases", entries)
    if not isinstance(payload, dict):
        raise ConfigError(f"{path}: 'aliases' must be a mapping")

    for key, value in payload.items():
        canonical = slugify(str(key))
        if isinstance(value, list | tuple):
            for alias in value:
                alias_slug = slugify(str(alias))
                if alias_slug == canonical:
                    continue
                if alias_slug in result and result[alias_slug] != canonical:
                    raise ConfigError(f"{path}: alias {alias_slug!r} maps to two canonical slugs")
                result[alias_slug] = canonical
        elif isinstance(value, str):
            # Shape {alias: canonical}
            result[slugify(str(key))] = slugify(value)
    return result


def _parse_reviews(entries: Any, path: Path) -> list[ReviewOverride]:
    """Parse ``reviews.yaml``.

    A rule that references a field outside the allowed set, or that lacks the
    evidence needed to be applicable, fails the build.
    """
    if entries is None:
        return []
    if not isinstance(entries, dict):
        raise ConfigError(f"{path}: reviews must be a mapping")

    raw_reviews = entries.get("reviews")
    if raw_reviews is None:
        return []
    if not isinstance(raw_reviews, list):
        raise ConfigError(f"{path}: 'reviews' must be a list")

    allowed_fields = {
        "base_url",
        "protocols",
        "model_id",
        "quota",
        "conditions",
        "credit_card",
        "phone_verification",
        "registration",
        "topup_required",
        "offer_type",
        "region",
        "rate_limits",
        "context_window_tokens",
        "capabilities",
    }
    allowed_decisions = {member.value for member in ReviewDecision}

    parsed: list[ReviewOverride] = []
    for index, entry in enumerate(raw_reviews):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: reviews[{index}] must be a mapping")

        subject_type = str(entry.get("subject_type") or "provider").strip()
        if subject_type not in {"provider", "model", "offer"}:
            raise ConfigError(f"{path}: reviews[{index}] subject_type must be provider/model/offer")

        subject_key = str(entry.get("subject") or entry.get("provider") or "").strip()
        if not subject_key:
            raise ConfigError(f"{path}: reviews[{index}] missing 'subject'")

        field_name = str(entry.get("field") or "").strip()
        if field_name not in allowed_fields:
            raise ConfigError(
                f"{path}: reviews[{index}] field {field_name!r} is not overridable; "
                f"allowed: {sorted(allowed_fields)}"
            )

        decision = str(entry.get("decision") or "confirm").strip().lower()
        if decision not in allowed_decisions:
            raise ConfigError(
                f"{path}: reviews[{index}] decision {decision!r} invalid; "
                f"allowed: {sorted(allowed_decisions)}"
            )

        if "value" not in entry:
            raise ConfigError(f"{path}: reviews[{index}] missing 'value'")

        reviewed_at = entry.get("reviewed_at")
        if reviewed_at and parse_iso(str(reviewed_at)) is None:
            raise ConfigError(
                f"{path}: reviews[{index}] reviewed_at {reviewed_at!r} is not ISO 8601"
            )

        scope = entry.get("scope") or {}
        if not isinstance(scope, dict):
            raise ConfigError(f"{path}: reviews[{index}] scope must be a mapping")

        parsed.append(
            ReviewOverride(
                subject_type=subject_type,
                subject_key=subject_key,
                field=field_name,
                value=entry["value"],
                decision=decision,
                evidence_url=entry.get("evidence_url"),
                reviewer=entry.get("reviewer"),
                reviewed_at=reviewed_at,
                region=[str(r) for r in (scope.get("region") or [])],
                plan=scope.get("plan"),
                model_id=scope.get("model_id"),
                reason=entry.get("reason"),
            )
        )
    return parsed


def load_alias_table(path: str | Path | None) -> dict[str, str]:
    """Convenience wrapper for a standalone aliases file."""
    if path is None:
        return {}
    alias_path = Path(path)
    if not alias_path.exists():
        return {}
    return _parse_aliases(_load_yaml(alias_path), alias_path)


def summarise_sources(sources: Iterable[SourceConfig]) -> list[dict[str, Any]]:
    """Compact summary used in the job summary and docs."""
    rows = []
    for source in sources:
        rows.append(
            {
                "id": source.id,
                "type": source.type,
                "role": source.role,
                "family": source.source_family,
                "enabled": source.enabled,
                "parser": f"{source.parser}@{source.parser_version}",
                "license": source.license or "UNSPECIFIED",
            }
        )
    return rows

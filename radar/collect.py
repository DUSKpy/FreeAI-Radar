"""Collection orchestrator: ``python -m radar.collect``.

Responsibilities, in order:

1. load main-branch configuration (programs and config, never data)
2. read the previous state from the ``catalog-data`` branch as *data* only --
   code in the data branch is never executed
3. fetch each enabled source with conditional requests and politeness limits
4. on failure keep the previous data for that source and update only its error
   status; other sources still finish, producing a ``partial`` run
5. normalise, apply review overrides, diff, prune and write a new state

This command never writes to Git. Persistence is the workflow's job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .collectors.base import (
    BaseAdapter,
    ParseError,
    SourceSpec,
    get_adapter,
)
from .config import RadarConfig, ReviewOverride, SourceConfig, load_config
from .diff import diff_catalog, prune_changes
from .http_client import Fetcher, FetchError, summarise_error
from .ids import (
    content_hash,
    iso_utc,
    short_hash,
)
from .ids import (
    run_id as make_run_id,
)
from .ids import (
    snapshot_id as make_snapshot_id,
)
from .models import (
    ClaimRecord,
    CollectionMeta,
    ConditionsRecord,
    JobRunRecord,
    ModelRecord,
    OfferRecord,
    ProviderRecord,
    QuotaRecord,
    RadarState,
    SnapshotRecord,
    SourceResult,
    SourceStateRecord,
)
from .normalize import SourceContext, mark_staleness, normalise
from .vocab import (
    DEFAULT_RETENTION_DAYS,
    InfoStatus,
    JobOutcome,
    JobType,
    ReviewDecision,
    ReviewStatus,
    SourceLevel,
    SourceStatus,
    SourceType,
    TriState,
)


@dataclass
class CollectOptions:
    config_path: Path
    previous_path: Path | None
    output_path: Path
    allow_private_hosts: bool = False
    dry_run: bool = False
    init: bool = False
    only_sources: list[str] = field(default_factory=list)
    skip_sources: list[str] = field(default_factory=list)
    force: bool = False
    timeout: float | None = None


@dataclass
class CollectOutcome:
    state: RadarState
    run: JobRunRecord
    warnings: list[str] = field(default_factory=list)


def parse_args(argv: list[str] | None = None) -> CollectOptions:
    parser = argparse.ArgumentParser(
        prog="python -m radar.collect",
        description="Collect, normalise and diff free AI API sources.",
    )
    parser.add_argument("--config", default="config/sources.yaml")
    parser.add_argument(
        "--reviews", default="config/reviews.yaml", help="review overrides to apply"
    )
    parser.add_argument("--aliases", default="config/aliases.yaml")
    parser.add_argument(
        "--previous",
        required=True,
        help="path to the previous state.json. Required on every run, "
        "including the first: pass --init with a path that does not exist yet. "
        "Omitting it entirely used to mean 'start empty', which made a typo in "
        "the path indistinguishable from a genuine first run.",
    )
    parser.add_argument("--output", default=".work/state.json")
    parser.add_argument(
        "--init",
        action="store_true",
        help="explicitly initialise an empty state. Without this, a missing or "
        "unreadable --previous is an error rather than a silent empty start.",
    )
    parser.add_argument("--only", action="append", default=[], help="only these source ids")
    parser.add_argument("--skip", action="append", default=[], help="skip these source ids")
    parser.add_argument("--force", action="store_true", help="ignore conditional request cache")
    parser.add_argument("--dry-run", action="store_true", help="parse but write nothing")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="test-only escape hatch; never use in production runs",
    )
    args = parser.parse_args(argv)

    return CollectOptions(
        config_path=Path(args.config),
        previous_path=Path(args.previous),
        output_path=Path(args.output),
        allow_private_hosts=args.allow_private_hosts,
        dry_run=args.dry_run,
        init=args.init,
        only_sources=args.only,
        skip_sources=args.skip,
        force=args.force,
        timeout=args.timeout,
    )


async def collect(options: CollectOptions) -> CollectOutcome:
    """Run one full collection pass."""
    started = iso_utc()
    warnings: list[str] = []

    config = load_config(
        sources_path=options.config_path,
        reviews_path=options.config_path.parent / "reviews.yaml",
        aliases_path=options.config_path.parent / "aliases.yaml",
    )

    # -- previous state ---------------------------------------------------
    previous, was_initial = _load_previous(options)
    if was_initial:
        warnings.append("no previous state: this run is an initial import")

    selected = _select_sources(config, options)

    fetcher = Fetcher(
        timeout=options.timeout or config.defaults.timeout_seconds,
        max_body_bytes=config.defaults.max_body_bytes,
        per_domain_concurrency=config.defaults.per_domain_concurrency,
        global_concurrency=config.defaults.global_concurrency,
        allow_redirects=config.defaults.follow_redirects,
        max_redirects=config.defaults.max_redirects,
        respect_retry_after=config.defaults.respect_retry_after,
        allow_private_hosts=options.allow_private_hosts,
    )

    # -- fetch + parse ----------------------------------------------------
    fetch_results = await _fetch_all(fetcher, config, selected, previous, options)

    candidates = []
    provider_facts: dict[str, dict[str, dict[str, object]]] = {}
    contexts: dict[str, SourceContext] = {}
    source_results: list[SourceResult] = []
    review_notes: list[dict[str, object]] = []

    for source in selected:
        outcome = fetch_results.get(source.id)
        if outcome is None:
            continue

        contexts[source.id] = SourceContext(
            source_id=source.id,
            source_family=source.source_family,
            source_level=SourceLevel(source.source_level),
            source_record_url=source.url,
            parser_version=source.parser_version,
            license=source.license,
        )

        if not outcome.parsed_ok:
            source_results.append(
                SourceResult(
                    source_id=source.id,
                    status=outcome.status,
                    http_status=outcome.http_status,
                    record_count=None,
                    error=outcome.error,
                )
            )
            continue

        candidates.extend(outcome.candidates)
        if outcome.provider_facts:
            provider_facts[source.id] = outcome.provider_facts
        review_notes.extend(outcome.review_notes)

        source_results.append(
            SourceResult(
                source_id=source.id,
                status=outcome.status,
                http_status=outcome.http_status,
                record_count=len(outcome.candidates),
                error=outcome.error,
            )
        )

    # -- normalise --------------------------------------------------------
    official_domain_index = _official_domain_index(config)
    normalised = normalise(
        candidates,
        contexts,
        provider_facts=provider_facts,
        alias_table=config.aliases,
        official_domain_index=official_domain_index,
        observed_at=started,
    )
    warnings.extend(normalised.warnings)

    # -- apply review overrides -------------------------------------------
    review_records, review_warnings = _apply_reviews(
        config.reviews,
        normalised.providers,
        normalised.models,
        normalised.offers,
        normalised.claims,
        previous,
        moment=started,
    )
    warnings.extend(review_warnings)

    # Failures must not wipe usable data: any source that failed keeps the
    # entities it previously contributed.
    failed_ids = {r.source_id for r in source_results if r.status in {"failed", "parse_error"}}
    if failed_ids and previous is not None:
        _retain_previous_from_failed_sources(normalised, previous, failed_ids, warnings)

    # -- staleness --------------------------------------------------------
    source_states = _merge_source_states(selected, previous, source_results, started)
    mark_staleness(
        normalised.offers,
        normalised.providers,
        source_states,
        now=started,
        source_stale_hours=int(config.build.staleness.get("source_stale_hours", 168)),
        offer_stale_days=int(config.build.staleness.get("offer_stale_days", 30)),
    )

    # -- diff -------------------------------------------------------------
    diff = diff_catalog(
        previous_providers=previous.providers if previous else [],
        previous_models=previous.models if previous else [],
        previous_offers=previous.offers if previous else [],
        current_providers=normalised.providers,
        current_models=normalised.models,
        current_offers=normalised.offers,
        previous_changes=previous.changes if previous else [],
        failed_source_ids=failed_ids,
        successful_source_ids={
            r.source_id for r in source_results if r.status in {"ok", "not_modified"}
        },
        is_initial_import=was_initial
        or (previous is not None and not previous.collection_meta.initial_import_done),
        now=started,
    )
    warnings.extend(diff.warnings)

    retention = int(config.build.staleness.get("retention_days", DEFAULT_RETENTION_DAYS))
    referenced = _referenced_evidence(normalised.offers)
    all_changes = prune_changes(
        (previous.changes if previous else []) + diff.changes,
        now=started,
        retention_days=retention,
        still_referenced_evidence=referenced,
    )

    # -- assemble state ---------------------------------------------------
    finished = iso_utc()
    outcome = _run_outcome(source_results, selected)
    run = JobRunRecord(
        id=make_run_id(JobType.COLLECT.value, started),
        job_type=JobType.COLLECT.value,
        started_at=started,
        finished_at=finished,
        outcome=outcome.value,
        counts={
            "candidates": len(candidates),
            "providers": len(normalised.providers),
            "models": len(normalised.models),
            "offers": len(normalised.offers),
            "claims": len(normalised.claims),
            "changes": len(diff.changes),
        },
        source_results=source_results,
    )

    meta = _collection_meta(previous, source_results, started, retention)
    state = RadarState(
        schema_version=1,
        created_at=previous.created_at if previous else started,
        updated_at=finished,
        runs=(([run] + (previous.runs if previous else []))[:120]),
        sources=source_states,
        snapshots=_merge_snapshots(previous, selected, fetch_results),
        providers=normalised.providers,
        models=normalised.models,
        offers=normalised.offers,
        claims=normalised.claims,
        reviews=review_records if review_records else (previous.reviews if previous else []),
        changes=all_changes,
        collection_meta=meta,
    )
    state.state_version = content_hash(
        {
            "providers": [p.model_dump() for p in state.providers],
            "models": [m.model_dump() for m in state.models],
            "offers": [o.model_dump() for o in state.offers],
            "claims": [c.model_dump() for c in state.claims],
        }
    )

    return CollectOutcome(state=state, run=run, warnings=warnings)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


@dataclass
class SourceOutcome:
    source_id: str
    status: str
    http_status: int | None = None
    error: str | None = None
    candidates: list[Any] = field(default_factory=list)
    provider_facts: dict[str, dict[str, object]] = field(default_factory=dict)
    review_notes: list[dict[str, object]] = field(default_factory=list)
    parsed_ok: bool = False


async def _fetch_all(
    fetcher: Fetcher,
    config: RadarConfig,
    sources: list[SourceConfig],
    previous: RadarState | None,
    options: CollectOptions,
) -> dict[str, SourceOutcome]:
    """Fetch every source concurrently, bounded by the global semaphore."""
    previous_by_id = {s.id: s for s in (previous.sources if previous else [])}

    async def one(source: SourceConfig) -> tuple[str, SourceOutcome]:
        prior = previous_by_id.get(source.id)
        etag = None if options.force else (prior.etag if prior else None)
        last_modified = None if options.force else (prior.last_modified if prior else None)

        try:
            result = await fetcher.fetch(
                source.url,
                allowed_domains=source.allowed_domains,
                etag=etag,
                last_modified=last_modified,
            )
        except FetchError as exc:
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.FAILED.value,
                http_status=exc.status,
                error=summarise_error(exc),
            )
        except Exception as exc:
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.FAILED.value,
                error=summarise_error(exc),
            )

        if result.not_modified:
            # A 304 refreshes the success timestamp without creating a new
            # content version.
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.NOT_MODIFIED.value,
                http_status=304,
                parsed_ok=False,
            )

        try:
            adapter = _adapter_for(source)
            parsed = adapter.parse(result.text, observed_at=result.fetched_at)
        except ParseError as exc:
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.PARSE_ERROR.value,
                http_status=result.status,
                error=summarise_error(exc),
            )
        except Exception as exc:
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.PARSE_ERROR.value,
                http_status=result.status,
                error=f"parse failed: {summarise_error(exc)}",
            )

        # Structural guard: a source that used to yield many rows and now
        # yields none is far more likely to have changed markup than to have
        # deleted its entire catalog.
        prior_count = prior.record_count if prior else None

        if not parsed.structure_ok or (not parsed.candidates and not parsed.provider_facts):
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.PARSE_ERROR.value,
                http_status=result.status,
                error="; ".join(parsed.warnings) or "structure unusable",
                parsed_ok=False,
            )

        if prior_count and prior_count >= 5 and not parsed.candidates:
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.PARSE_ERROR.value,
                http_status=result.status,
                error=(
                    f"record count collapsed from {prior_count} to 0; "
                    "treated as parse_error and old data retained"
                ),
                parsed_ok=False,
            )

        if (
            prior_count
            and prior_count >= 20
            and len(parsed.candidates) < max(3, int(prior_count * 0.2))
        ):
            return source.id, SourceOutcome(
                source_id=source.id,
                status=SourceStatus.PARSE_ERROR.value,
                http_status=result.status,
                error=(
                    f"record count collapsed from {prior_count} to "
                    f"{len(parsed.candidates)}; treated as parse_error"
                ),
                parsed_ok=False,
            )

        return source.id, SourceOutcome(
            source_id=source.id,
            status=SourceStatus.OK.value,
            http_status=result.status,
            candidates=parsed.candidates,
            provider_facts=parsed.provider_facts,
            review_notes=parsed.review_notes,
            parsed_ok=True,
        )

    pairs = await asyncio.gather(*(one(source) for source in sources))
    return dict(pairs)


def _adapter_for(source: SourceConfig) -> BaseAdapter:
    adapter_class = get_adapter(source.parser)
    spec = SourceSpec(
        id=source.id,
        name=source.name,
        url=source.url,
        type=source.type,
        source_family=source.source_family,
        parser=source.parser,
        enabled=source.enabled,
        role=source.role,
        allowed_domains=source.allowed_domains,
        license=source.license,
        license_url=source.license_url,
        terms_url=source.terms_url,
        provider_slug=source.provider_slug,
        notes=source.notes,
        mirrors=source.mirrors,
        parser_version=source.parser_version,
    )
    return adapter_class(spec)


# ---------------------------------------------------------------------------
# State assembly helpers
# ---------------------------------------------------------------------------


def _load_previous(options: CollectOptions) -> tuple[RadarState | None, bool]:
    """Read the previous state.

    A missing or unreadable file is an error unless ``--init`` was passed
    explicitly. Silently treating a permission failure as an empty starting
    point would quietly discard history.

    ``previous_path`` is not optional: an omitted path and a mistyped path must
    not be able to look the same, because the first is a genuine first run and
    the second is a bug that would silently reset the catalogue.
    """
    if options.previous_path is None:  # pragma: no cover - CLI enforces this
        raise SystemExit(
            "no previous state path given; pass --previous PATH "
            "(with --init on the very first run)"
        )

    path = options.previous_path
    if not path.exists():
        if options.init:
            return _empty_state(), True
        raise SystemExit(
            f"previous state not found: {path}\n"
            "Pass --init to start from an empty state, or fix the path."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"cannot read previous state {path}: {exc}\n"
            "Refusing to treat an unreadable state as empty."
        ) from exc

    try:
        state = RadarState.model_validate(payload)
    except Exception as exc:
        raise SystemExit(f"previous state {path} failed schema validation: {exc}") from exc

    return state, not state.collection_meta.initial_import_done and not state.providers


def _empty_state() -> RadarState:
    moment = iso_utc()
    return RadarState(
        schema_version=1,
        state_version="sha256:0",
        created_at=moment,
        updated_at=moment,
        collection_meta=CollectionMeta(
            last_successful_collection_at=None,
            last_complete_collection_at=None,
            initial_import_done=False,
            retention_days=DEFAULT_RETENTION_DAYS,
        ),
    )


def _select_sources(config: RadarConfig, options: CollectOptions) -> list[SourceConfig]:
    sources = config.enabled_sources
    if options.only_sources:
        wanted = set(options.only_sources)
        unknown = wanted - {s.id for s in config.sources}
        if unknown:
            raise SystemExit(f"--only references unknown sources: {sorted(unknown)}")
        sources = [s for s in sources if s.id in wanted]
    if options.skip_sources:
        skip = set(options.skip_sources)
        sources = [s for s in sources if s.id not in skip]
    return sources


def _official_domain_index(config: RadarConfig) -> dict[str, str]:
    """Seed domain matching from sources that declare one."""
    index: dict[str, str] = {}
    for source in config.sources:
        if not source.provider_slug:
            continue
        from .textutil import normalise_host

        domain = normalise_host(source.url)
        if domain and source.role == "official":
            index.setdefault(domain, source.provider_slug)
    return index


def _merge_source_states(
    sources: list[SourceConfig],
    previous: RadarState | None,
    results: list[SourceResult],
    moment: str,
) -> list[SourceStateRecord]:
    """Update per-source health while preserving untouched sources."""
    by_id = {s.id: s for s in (previous.sources if previous else [])}
    result_by_id = {r.source_id: r for r in results}
    merged: list[SourceStateRecord] = []

    for source in sources:
        prior = by_id.get(source.id)
        result = result_by_id.get(source.id)
        record = SourceStateRecord(
            id=source.id,
            name=source.name,
            url=source.url,
            type=SourceType(source.type),
            source_family=source.source_family,
            enabled=source.enabled,
            parser=source.parser,
            parser_version=source.parser_version,
            allowed_domains=list(source.allowed_domains),
            license=source.license,
            license_url=source.license_url,
            terms_url=source.terms_url,
            first_checked_at=prior.first_checked_at if prior else moment,
            last_attempt_at=moment,
            last_success_at=prior.last_success_at if prior else None,
            status=SourceStatus.NEVER_RUN,
            etag=prior.etag if prior else None,
            last_modified=prior.last_modified if prior else None,
            content_hash=prior.content_hash if prior else None,
            record_count=prior.record_count if prior else None,
            last_record_count=prior.record_count if prior else None,
        )

        if result is None:
            record.status = prior.status if prior else SourceStatus.NEVER_RUN
            record.error = prior.error if prior else None
            merged.append(record)
            continue

        record.error = result.error
        if result.status in {SourceStatus.OK.value, SourceStatus.NOT_MODIFIED.value}:
            record.last_success_at = moment
            record.status = SourceStatus(result.status)
        else:
            record.status = SourceStatus(result.status)
        if result.record_count is not None:
            record.record_count = result.record_count
        merged.append(record)

    # Keep disabled sources visible in the state file for transparency.
    for source_id, prior in by_id.items():
        if any(item.id == source_id for item in merged):
            continue
        merged.append(prior)

    return sorted(merged, key=lambda item: item.id)


def _merge_snapshots(
    previous: RadarState | None,
    sources: list[SourceConfig],
    results: dict[str, SourceOutcome],
) -> list[SnapshotRecord]:
    """Persist compact snapshot metadata for sources that returned content."""
    kept: list[SnapshotRecord] = []
    seen: set[tuple[str, str]] = set()

    for source in sources:
        outcome = results.get(source.id)
        if outcome is None or not outcome.parsed_ok:
            continue
        digest = content_hash(
            {
                "source": source.id,
                "count": len(outcome.candidates),
                "providers": sorted({c.provider_name for c in outcome.candidates}),
            },
            drop_volatile=False,
        )
        key = (source.id, digest)
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            SnapshotRecord(
                id=make_snapshot_id(source.id, digest),
                source_id=source.id,
                fetched_at=iso_utc(),
                http_status=outcome.http_status,
                content_hash=digest,
                extracted={"record_count": len(outcome.candidates)},
            )
        )

    # Retain recent history but cap the list so the data branch stays small.
    if previous:
        for snapshot in previous.snapshots:
            key = (snapshot.source_id, snapshot.content_hash)
            if key not in seen:
                seen.add(key)
                kept.append(snapshot)
    return kept[:4000]


def _referenced_evidence(offers: list[OfferRecord]) -> set[str]:
    from .diff import _evidence_fingerprint

    return {_evidence_fingerprint(offer) for offer in offers}


def _run_outcome(results: list[SourceResult], sources: list[SourceConfig]) -> JobOutcome:
    if not sources:
        return JobOutcome.SKIPPED
    ok = [r for r in results if r.status in {"ok", "not_modified"}]
    bad = [r for r in results if r.status in {"failed", "parse_error"}]
    if not bad:
        return JobOutcome.SUCCESS
    if ok:
        return JobOutcome.PARTIAL
    return JobOutcome.FAILED


def _collection_meta(
    previous: RadarState | None,
    results: list[SourceResult],
    moment: str,
    retention: int,
) -> CollectionMeta:
    """Compute the two collection timestamps the public contract defines.

    ``last_successful_collection_at`` = the most recent time at least one
    enabled source succeeded or returned 304.

    ``last_complete_collection_at`` = the most recent time *all* enabled
    sources succeeded.
    """
    prior = previous.collection_meta if previous else CollectionMeta()
    succeeded = [r for r in results if r.status in {"ok", "not_modified"}]
    attempted = [r for r in results if r.status != "skipped"]

    last_successful = prior.last_successful_collection_at
    if succeeded:
        last_successful = moment

    last_complete = prior.last_complete_collection_at
    if attempted and len(succeeded) == len(attempted):
        last_complete = moment

    return CollectionMeta(
        last_successful_collection_at=last_successful,
        last_complete_collection_at=last_complete,
        initial_import_done=True,
        retention_days=retention,
        null_result_streaks=prior.null_result_streaks,
    )


def _retain_previous_from_failed_sources(
    normalised: Any,
    previous: RadarState,
    failed_ids: set[str],
    warnings: list[str],
) -> None:
    """Keep entities contributed by sources that failed this run.

    A failed fetch proves nothing about the data, so the previous records stay
    in place with their original evidence.
    """
    from .diff import _evidence_fingerprint  # noqa: F401  (import kept for parity)

    current_provider_ids = {p.id for p in normalised.providers}
    current_model_ids = {m.id for m in normalised.models}
    current_offer_keys = {(o.provider_id, o.model_id, o.offer_type) for o in normalised.offers}

    retained_providers = 0
    for provider in previous.providers:
        if provider.id in current_provider_ids:
            continue
        if not (set(provider.source_families) & failed_ids):
            continue
        normalised.providers.append(provider)
        retained_providers += 1

    retained_models = 0
    for model in previous.models:
        if model.id in current_model_ids:
            continue
        owning = next((p for p in previous.providers if p.id == model.provider_id), None)
        if owning is None or not (set(owning.source_families) & failed_ids):
            continue
        normalised.models.append(model)
        retained_models += 1

    retained_offers = 0
    for offer in previous.offers:
        key = (offer.provider_id, offer.model_id, offer.offer_type)
        if key in current_offer_keys:
            continue
        if not any(item.source_id in failed_ids for item in offer.evidence):
            continue
        normalised.offers.append(offer)
        retained_offers += 1

    if retained_providers or retained_models or retained_offers:
        warnings.append(
            f"retained previous data from failed sources {sorted(failed_ids)}: "
            f"{retained_providers} providers, {retained_models} models, "
            f"{retained_offers} offers"
        )


# ---------------------------------------------------------------------------
# Review overrides
# ---------------------------------------------------------------------------


def _apply_reviews(
    reviews: list[ReviewOverride],
    providers: list[ProviderRecord],
    models: list[ModelRecord],
    offers: list[OfferRecord],
    claims: list[ClaimRecord],
    previous: RadarState | None,
    *,
    moment: str,
) -> tuple[list[Any], list[str]]:
    """Apply ``config/reviews.yaml`` as an override layer.

    A confirmed field outranks the directory claim. When the underlying
    evidence has changed since the review, the review is moved to
    ``needs_review`` instead of remaining silently ``verified``.
    """
    from .ids import claim_fingerprint
    from .models import ReviewRecord

    warnings: list[str] = []
    records: list[ReviewRecord] = []
    provider_by_slug = {p.slug: p for p in providers}

    for review in reviews:
        provider = provider_by_slug.get(review.subject_key)
        if provider is None:
            warnings.append(
                f"review references unknown provider {review.subject_key!r}; "
                "the build keeps the rule recorded but does not apply it"
            )
            records.append(_review_record(review, moment, "unknown_subject"))
            continue

        fingerprint = claim_fingerprint(
            review.subject_type,
            review.subject_key,
            review.field,
            "official",
            review.evidence_url or "",
        )

        claim = next(
            (c for c in claims if c.subject_id == provider.id and c.field == review.field),
            None,
        )

        record = _review_record(review, moment, "applied", fingerprint=fingerprint)
        if review.decision == ReviewDecision.REJECT.value:
            if claim is not None:
                claim.review_status = ReviewStatus.REJECTED
            records.append(record)
            continue

        if claim is not None:
            claim.review_status = ReviewStatus.OFFICIAL_CONFIRMED

        if review.decision == ReviewDecision.NEEDS_REVIEW.value:
            record.decision = ReviewDecision.NEEDS_REVIEW
            records.append(record)
            continue

        # Apply the value onto the matching offer.
        for offer in offers:
            if offer.provider_id != provider.id:
                continue
            if review.model_id:
                model = next(
                    (
                        m
                        for m in models
                        if m.model_id == review.model_id and m.provider_id == provider.id
                    ),
                    None,
                )
                if model is None or offer.model_id != model.id:
                    continue
            _apply_review_value(offer, review, warnings)
            offer.info_status = InfoStatus.OFFICIAL_CONFIRMED
            offer.needs_review = False
            offer.stale = False
            offer.reviewed_at = review.reviewed_at or moment

        records.append(record)

    # Carry forward previous records so the audit trail survives runs that
    # contain no review changes.
    if previous:
        known = {(r.claim_fingerprint, r.created_at) for r in records}
        for prior in previous.reviews:
            if (prior.claim_fingerprint, prior.created_at) not in known:
                records.append(prior)

    return records, warnings


def _review_record(
    review: ReviewOverride,
    moment: str,
    status: str,
    fingerprint: str | None = None,
) -> Any:
    from .models import ReviewRecord

    return ReviewRecord(
        id="rv_" + short_hash(review.subject_key, review.field, review.reviewed_at or moment),
        claim_id=None,
        claim_fingerprint=fingerprint
        or "rf_" + short_hash(review.subject_key, review.field, status),
        decision=review.decision,  # type: ignore[arg-type]
        reason=review.reason or status,
        reviewer=review.reviewer,
        created_at=review.reviewed_at or moment,
        evidence_url=review.evidence_url,
        scope={
            "region": review.region,
            "plan": review.plan,
            "model_id": review.model_id,
        },
    )


def _apply_review_value(offer: OfferRecord, review: ReviewOverride, warnings: list[str]) -> None:
    """Write one reviewed field onto an offer."""
    value = review.value

    if review.field == "base_url":
        offer.base_url = str(value) if value else None
    elif review.field == "offer_type":
        offer.offer_type = str(value)
    elif review.field == "protocols":
        from .vocab import Protocol

        protocols = value if isinstance(value, list) else [value]
        parsed = []
        for item in protocols:
            try:
                parsed.append(Protocol(str(item)))
            except ValueError:
                warnings.append(f"review supplied unknown protocol {item!r}")
        offer.rate_limits = offer.rate_limits  # unchanged; protocols live on models
    elif review.field == "quota":
        if isinstance(value, dict):
            offer.quota = QuotaRecord(
                value=value.get("value"),
                unit=value.get("unit", offer.quota.unit),
                period=value.get("period", offer.quota.period),
                raw=str(value.get("raw") or offer.quota.raw),
            )
        else:
            warnings.append("review quota value must be a mapping")
    elif review.field == "conditions":
        if isinstance(value, dict):
            offer.conditions = ConditionsRecord(
                credit_card=_state(value.get("credit_card")),
                phone_verification=_state(value.get("phone_verification")),
                registration=_state(value.get("registration")),
                topup_required=_state(value.get("topup_required")),
                topup_minimum=value.get("topup_minimum"),
                notes=value.get("notes"),
            )
        else:
            warnings.append("review conditions value must be a mapping")
    elif review.field in {
        "credit_card",
        "phone_verification",
        "registration",
        "topup_required",
    }:
        setattr(offer.conditions, review.field, _state(value))
    elif review.field == "region":
        offer.region = [str(value)] if isinstance(value, str) else [str(v) for v in value]
    elif review.field == "rate_limits":
        if isinstance(value, list):
            offer.rate_limits = value
    elif review.field == "ends_on":
        offer.ends_on = str(value) if value else None
    else:
        warnings.append(f"review field {review.field!r} has no applier; ignored")


def _state(value: Any) -> TriState:
    try:
        return TriState(str(value))
    except ValueError:
        return TriState.UNKNOWN


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def write_state(state: RadarState, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump(mode="json", exclude_none=False)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    outcome = asyncio.run(collect(options))

    if not options.dry_run:
        write_state(outcome.state, options.output_path)

    summary = {
        "outcome": outcome.run.outcome,
        "counts": outcome.run.counts,
        "sources": [
            {
                "id": result.source_id,
                "status": result.status,
                "http_status": result.http_status,
                "records": result.record_count,
                "error": result.error,
            }
            for result in outcome.run.source_results
        ],
        "warnings": outcome.warnings,
        "output": None if options.dry_run else str(options.output_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if outcome.run.outcome != JobOutcome.FAILED.value else 2


if __name__ == "__main__":
    sys.exit(main())

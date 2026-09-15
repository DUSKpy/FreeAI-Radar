"""Change detection and daily reports.

Rules the task book is specific about, and which this module enforces:

* an initial import is labelled ``initial_import`` -- the whole catalog is never
  announced as "new today"
* a source dropping an entry is reported as
  ``missing_from_source`` ("that source no longer lists it"), never as "the API
  was shut down" or "it became paid"
* a failed collection produces no deletion events at all
* events carry an idempotency fingerprint over (entity, field, old, new,
  evidence version), so re-running a collection adds nothing
* the same field changing again later yields a *new, independent* event
* the rolling window is 90 days and is pruned on every run
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .ids import (
    change_fingerprint,
    change_id,
    iso_utc,
    parse_iso,
    shanghai_date,
    short_hash,
)
from .models import (
    ChangeRecord,
    ModelRecord,
    OfferRecord,
    ProviderRecord,
)
from .vocab import ChangeType, InfoStatus

#: Offer fields whose change is worth a daily-report line.
TRACKED_OFFER_FIELDS = (
    "offer_type",
    "quota",
    "conditions",
    "base_url",
    "region",
    "ends_on",
    "info_status",
)


@dataclass
class DiffResult:
    changes: list[ChangeRecord] = field(default_factory=list)
    #: Fingerprints already present in the previous state, for idempotency.
    seen_fingerprints: set[str] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add(self, record: ChangeRecord) -> bool:
        """Add an event unless its fingerprint was already recorded.

        Returns True when the event was new.
        """
        if record.fingerprint in self.seen_fingerprints:
            return False
        self.seen_fingerprints.add(record.fingerprint)
        self.changes.append(record)
        self.counts[record.change_type] = self.counts.get(record.change_type, 0) + 1
        return True


def diff_catalog(
    *,
    previous_providers: list[ProviderRecord],
    previous_models: list[ModelRecord],
    previous_offers: list[OfferRecord],
    current_providers: list[ProviderRecord],
    current_models: list[ModelRecord],
    current_offers: list[OfferRecord],
    previous_changes: list[ChangeRecord],
    failed_source_ids: Iterable[str] = (),
    successful_source_ids: Iterable[str] = (),
    is_initial_import: bool = False,
    now: str | None = None,
) -> DiffResult:
    """Compare two catalog snapshots and emit idempotent change events."""
    result = DiffResult()
    moment = now or iso_utc()
    failed = set(failed_source_ids)
    successful = set(successful_source_ids)

    # Seed the fingerprint set with everything already recorded, so a re-run
    # over identical input adds nothing.
    for existing in previous_changes:
        if existing.fingerprint:
            result.seen_fingerprints.add(existing.fingerprint)

    prev_provider_by_id = {p.id: p for p in previous_providers}
    prev_model_by_id = {m.id: m for m in previous_models}
    prev_offer_by_id = {o.id: o for o in previous_offers}
    current_provider_ids = {p.id for p in current_providers}
    current_model_ids = {m.id for m in current_models}
    {o.id for o in current_offers}

    # -- initial import ---------------------------------------------------
    if is_initial_import:
        for provider in current_providers:
            _emit(
                result,
                subject_type="provider",
                subject_id=provider.id,
                subject_label=provider.name,
                provider_id=provider.id,
                field="*",
                old=None,
                new=provider.name,
                change_type=ChangeType.INITIAL_IMPORT,
                moment=moment,
                source_id=_primary_source(provider),
                confirmed=False,
                note="first import; not a new release today",
                evidence_fingerprint=None,
            )
        return result

    # -- new providers ----------------------------------------------------
    for provider in current_providers:
        if provider.id in prev_provider_by_id:
            continue
        _emit(
            result,
            subject_type="provider",
            subject_id=provider.id,
            subject_label=provider.name,
            provider_id=provider.id,
            field="*",
            old=None,
            new=provider.name,
            change_type=ChangeType.NEW_PROVIDER,
            moment=moment,
            source_id=_primary_source(provider),
            confirmed=False,
            note=None,
            evidence_fingerprint=None,
        )

    # -- new models -------------------------------------------------------
    for model in current_models:
        if model.id in prev_model_by_id:
            continue
        provider = next((p for p in current_providers if p.id == model.provider_id), None)
        _emit(
            result,
            subject_type="model",
            subject_id=model.id,
            subject_label=model.display_name,
            provider_id=model.provider_id,
            field="model_id",
            old=None,
            new=model.model_id,
            change_type=ChangeType.NEW_MODEL,
            moment=moment,
            source_id=_primary_source(provider),
            confirmed=False,
            note=None,
            evidence_fingerprint=None,
        )

    # -- changed offers ---------------------------------------------------
    for offer in current_offers:
        previous = prev_offer_by_id.get(offer.id)
        provider = next((p for p in current_providers if p.id == offer.provider_id), None)
        label = provider.name if provider else offer.provider_id
        if previous is None:
            continue
        for field_name in TRACKED_OFFER_FIELDS:
            old_value = _serialise(getattr(previous, field_name, None))
            new_value = _serialise(getattr(offer, field_name, None))
            if old_value == new_value:
                continue
            change_type = _classify_offer_change(field_name, old_value, new_value)
            evidence_fp = _evidence_fingerprint(offer)
            _emit(
                result,
                subject_type="offer",
                subject_id=offer.id,
                subject_label=label,
                provider_id=offer.provider_id,
                field=field_name,
                old=old_value,
                new=new_value,
                change_type=change_type,
                moment=moment,
                source_id=_source_for_offer(offer),
                confirmed=offer.info_status == InfoStatus.OFFICIAL_CONFIRMED,
                note=_change_note(change_type),
                evidence_fingerprint=evidence_fp,
            )

    # -- missing entities, only from sources that actually succeeded ------
    for provider in previous_providers:
        if provider.id in current_provider_ids:
            continue
        if _only_seen_by_failed_source(provider, failed):
            continue
        current_source_count = sum(
            1 for source in successful if source in _sources_for_provider(provider)
        )
        if successful and not current_source_count:
            # No successful source that knows this provider ran, so absence
            # proves nothing. Skip rather than announce a false removal.
            continue
        _emit(
            result,
            subject_type="provider",
            subject_id=provider.id,
            subject_label=provider.name,
            provider_id=provider.id,
            field="*",
            old=provider.name,
            new=None,
            change_type=ChangeType.MISSING_FROM_SOURCE,
            moment=moment,
            source_id=_primary_source(provider),
            confirmed=False,
            note="no longer listed by this source; not a confirmed shutdown",
            evidence_fingerprint=None,
        )

    for model in previous_models:
        if model.id in current_model_ids:
            continue
        if _only_seen_by_failed_source(model, failed):
            continue
        provider = next((p for p in current_providers if p.id == model.provider_id), None)
        _emit(
            result,
            subject_type="model",
            subject_id=model.id,
            subject_label=model.display_name,
            provider_id=model.provider_id,
            field="model_id",
            old=model.model_id,
            new=None,
            change_type=ChangeType.MISSING_FROM_SOURCE,
            moment=moment,
            source_id=_primary_source(provider),
            confirmed=False,
            note="no longer listed by this source; not a confirmed shutdown",
            evidence_fingerprint=None,
        )

    # -- reappearance -----------------------------------------------------
    previous_missing = {
        change.subject_id
        for change in previous_changes
        if change.change_type == ChangeType.MISSING_FROM_SOURCE and change.new_value is None
    }
    for provider in current_providers:
        if provider.id in previous_missing and provider.id not in prev_provider_by_id:
            _emit(
                result,
                subject_type="provider",
                subject_id=provider.id,
                subject_label=provider.name,
                provider_id=provider.id,
                field="*",
                old=None,
                new=provider.name,
                change_type=ChangeType.REAPPEARED,
                moment=moment,
                source_id=_primary_source(provider),
                confirmed=False,
                note=None,
                evidence_fingerprint=None,
            )

    return result


def _emit(
    result: DiffResult,
    *,
    subject_type: str,
    subject_id: str,
    subject_label: str | None,
    provider_id: str | None,
    field: str,
    old: Any,
    new: Any,
    change_type: ChangeType,
    moment: str,
    source_id: str,
    confirmed: bool,
    note: str | None,
    evidence_fingerprint: str | None,
) -> None:
    fingerprint = change_fingerprint(
        subject_type, subject_id, field, old, new, evidence_fingerprint
    )
    result.add(
        ChangeRecord(
            id=change_id(fingerprint, moment),
            fingerprint=fingerprint,
            subject_type=subject_type,  # type: ignore[arg-type]
            subject_id=subject_id,
            subject_label=subject_label,
            provider_id=provider_id,
            field=field,
            old_value=old,
            new_value=new,
            change_type=change_type.value,
            detected_at=moment,
            observed_at=moment,
            source_id=source_id,
            evidence_fingerprint=evidence_fingerprint,
            confirmed=confirmed,
            note=note,
        )
    )


def _classify_offer_change(field: str, old: Any, new: Any) -> ChangeType:
    """Pick the most specific change type the data supports."""
    if field == "quota":
        if new in (None, "", {}, []) or (
            isinstance(new, dict)
            and new.get("value") is None
            and (old or {}).get("value") is not None
        ):
            # A quota disappearing is a source omission, not proof the free
            # tier ended. The daily report words it accordingly.
            return ChangeType.MISSING_FROM_SOURCE
        return ChangeType.QUOTA_CHANGED
    if field == "conditions":
        return ChangeType.CONDITION_CHANGED
    if field == "info_status":
        if new == InfoStatus.SOURCE_CONFLICT.value:
            return ChangeType.OFFICIAL_CONFLICT
        return ChangeType.CONDITION_CHANGED
    if field == "ends_on":
        if new and not old:
            return ChangeType.PROMO_ENDED
        return ChangeType.CONDITION_CHANGED
    if field == "offer_type":
        return ChangeType.CONDITION_CHANGED
    return ChangeType.CONDITION_CHANGED


def _change_note(change_type: ChangeType) -> str | None:
    if change_type == ChangeType.MISSING_FROM_SOURCE:
        return "value no longer stated by the source; it does not prove the offer ended"
    if change_type == ChangeType.OFFICIAL_CONFLICT:
        return "official material and the directory disagree; both evidences retained"
    return None


def _serialise(value: Any) -> Any:
    """Stable, JSON-safe representation for comparison and storage."""
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, list | tuple):
        return [_serialise(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _serialise(v) for k, v in sorted(value.items())}
    if hasattr(value, "model_dump"):
        return _serialise(value.model_dump())
    return value


def _evidence_fingerprint(offer: OfferRecord) -> str:
    """Hash of the offer's evidence, so re-observation does not re-fire."""
    payload = [
        {
            "source_id": item.source_id,
            "excerpt": item.excerpt,
            "observed_at": item.observed_at,
        }
        for item in offer.evidence
    ]
    return "ev_" + short_hash(payload)


def _primary_source(provider: ProviderRecord | None) -> str:
    if provider is None or not provider.source_families:
        return "unknown"
    return provider.source_families[0]


def _sources_for_provider(provider: ProviderRecord) -> set[str]:
    return set(provider.source_families)


def _source_for_offer(offer: OfferRecord) -> str:
    if offer.evidence:
        return offer.evidence[0].source_id
    return "unknown"


def _only_seen_by_failed_source(entity: Any, failed: set[str]) -> bool:
    """Whether every source that knew this entity failed this run."""
    if not failed:
        return False
    families = getattr(entity, "source_families", None) or []
    evidence = getattr(entity, "evidence", None) or []
    known = set(families) | {item.source_id for item in evidence}
    if not known:
        return False
    return known.issubset(failed)


def prune_changes(
    changes: list[ChangeRecord],
    *,
    now: str | None = None,
    retention_days: int = 90,
    still_referenced_evidence: set[str] | None = None,
) -> list[ChangeRecord]:
    """Keep only the rolling window.

    An event outside the window is retained when its evidence is still
    referenced by a live entity, so the audit trail does not develop holes.
    """
    moment = parse_iso(now) or datetime.now(UTC)
    cutoff = moment - timedelta(days=retention_days)
    keep: list[ChangeRecord] = []
    referenced = still_referenced_evidence or set()

    for change in changes:
        detected = parse_iso(change.detected_at)
        if detected is None or detected >= cutoff:
            keep.append(change)
            continue
        if change.evidence_fingerprint and change.evidence_fingerprint in referenced:
            keep.append(change)
    return keep


# ---------------------------------------------------------------------------
# Daily report
# ---------------------------------------------------------------------------


@dataclass
class DailyReport:
    date: str
    generated_at: str
    markdown: str
    payload: dict[str, Any]


def build_daily_report(
    changes: list[ChangeRecord],
    *,
    providers: list[ProviderRecord],
    sources: list[dict[str, Any]],
    generated_at: str | None = None,
    data_cutoff: str | None = None,
    day: str | None = None,
) -> DailyReport:
    """Compose the daily report shown on the site and offered for download.

    Contents: new entries, important changes, items awaiting confirmation,
    collection success rate and the data cutoff time. Re-running a collection
    produces no duplicate lines because the input ``changes`` are already
    de-duplicated by fingerprint.
    """
    moment = generated_at or iso_utc()
    report_day = day or shanghai_date(moment)
    provider_names = {p.id: p.name for p in providers}

    daily = [change for change in changes if shanghai_date(change.detected_at) == report_day]

    new_entries = [
        change
        for change in daily
        if change.change_type in {ChangeType.NEW_PROVIDER.value, ChangeType.NEW_MODEL.value}
    ]
    important = [
        change
        for change in daily
        if change.change_type
        in {
            ChangeType.QUOTA_CHANGED.value,
            ChangeType.CONDITION_CHANGED.value,
            ChangeType.OFFICIAL_CONFLICT.value,
            ChangeType.PROMO_ENDED.value,
            ChangeType.REAPPEARED.value,
            ChangeType.MISSING_FROM_SOURCE.value,
        }
    ]
    pending = [change for change in daily if not change.confirmed]

    enabled = [source for source in sources if source.get("enabled")]
    succeeded = [source for source in enabled if source.get("status") in {"ok", "not_modified"}]
    rate = (len(succeeded) / len(enabled) * 100) if enabled else 0.0

    lines: list[str] = []
    lines.append(f"# FreeAI Radar 每日报告 · {report_day}")
    lines.append("")
    lines.append(f"- 数据截止时间（UTC）：{data_cutoff or moment}")
    lines.append(f"- 报告生成时间（UTC）：{moment}")
    lines.append(f"- 采集成功率：{len(succeeded)}/{len(enabled)} （{rate:.0f}%）")
    lines.append(f"- 今日事件总数：{len(daily)}")
    lines.append("")

    lines.append("## 新增条目")
    lines.append("")
    if new_entries:
        for change in new_entries:
            label = change.subject_label or change.subject_id
            owner = provider_names.get(change.provider_id or "", "")
            suffix = f"（{owner}）" if owner and owner != label else ""
            lines.append(f"- **{label}**{suffix} — {change.change_type}")
    else:
        lines.append("- 今日暂无新增条目。")
    lines.append("")

    lines.append("## 重要变化")
    lines.append("")
    if important:
        for change in important:
            label = change.subject_label or change.subject_id
            owner = provider_names.get(change.provider_id or "", "")
            suffix = f"（{owner}）" if owner and owner != label else ""
            old = _render_value(change.old_value)
            new = _render_value(change.new_value)
            note = f" — {change.note}" if change.note else ""
            lines.append(f"- **{label}**{suffix} · `{change.field}`：{old} → {new}{note}")
    else:
        lines.append("- 今日暂无重要变化。")
    lines.append("")

    lines.append("## 待确认事项")
    lines.append("")
    if pending:
        for change in pending:
            label = change.subject_label or change.subject_id
            lines.append(f"- {label} · `{change.field}`（{change.change_type}）")
    else:
        lines.append("- 无待确认事项。")
    lines.append("")

    lines.append("## 来源状态")
    lines.append("")
    lines.append("| 来源 | 状态 | 记录数 | 说明 |")
    lines.append("|---|---|---|---|")
    for source in sources:
        lines.append(
            "| {name} | {status} | {count} | {note} |".format(
                name=source.get("name") or source.get("id"),
                status=source.get("status", "unknown"),
                count=source.get("record_count") if source.get("record_count") is not None else "—",
                note=(source.get("error") or "").replace("|", "/") or "—",
            )
        )
    lines.append("")
    lines.append(
        "> 说明：来源不再列出某条目时只标记为“该来源不再列出”，" "不代表 API 下线或转为收费。"
    )

    payload = {
        "date": report_day,
        "generated_at": moment,
        "data_cutoff": data_cutoff or moment,
        "collection": {
            "enabled_sources": len(enabled),
            "succeeded_sources": len(succeeded),
            "success_rate_percent": round(rate, 1),
        },
        "counts": {
            "new": len(new_entries),
            "important": len(important),
            "pending": len(pending),
            "total": len(daily),
        },
        "new_entries": [_change_payload(change) for change in new_entries],
        "important_changes": [_change_payload(change) for change in important],
        "pending": [_change_payload(change) for change in pending],
    }

    return DailyReport(
        date=report_day,
        generated_at=moment,
        markdown="\n".join(lines) + "\n",
        payload=payload,
    )


def _change_payload(change: ChangeRecord) -> dict[str, Any]:
    return {
        "id": change.id,
        "type": change.change_type,
        "subject_type": change.subject_type,
        "subject_id": change.subject_id,
        "subject_label": change.subject_label,
        "provider_id": change.provider_id,
        "field": change.field,
        "old": change.old_value,
        "new": change.new_value,
        "detected_at": change.detected_at,
        "source_id": change.source_id,
        "confirmed": change.confirmed,
        "note": change.note,
    }


def _render_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        import json

        return "`" + json.dumps(value, ensure_ascii=False, sort_keys=True)[:120] + "`"
    return str(value)


def group_changes_by_day(
    changes: Iterable[ChangeRecord], *, limit_days: int = 30
) -> list[tuple[str, list[ChangeRecord]]]:
    """Group events by Asia/Shanghai calendar day for the timeline page."""
    buckets: dict[str, list[ChangeRecord]] = defaultdict(list)
    for change in changes:
        buckets[shanghai_date(change.detected_at)].append(change)

    ordered = sorted(buckets.items(), key=lambda item: item[0], reverse=True)[:limit_days]
    return [
        (day, sorted(items, key=lambda c: c.detected_at, reverse=True)) for day, items in ordered
    ]

"""Public export: ``python -m radar.export_public``.

Turns the internal state into the public, versioned JSON the browser reads.

The task book requires a **field allowlist** rather than copying the internal
store or the collection directory into ``dist``. Everything that leaves this
module passes through an explicit list, so a new internal field cannot leak by
accident. Explicitly forbidden from the output:

* API keys, GitHub tokens, cookies, admin configuration
* full cached pages or raw HTML
* private test content
* local filesystem paths

Evidence is reduced to the necessary short fragment plus a source link.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .diff import build_daily_report
from .ids import content_hash, iso_utc, shanghai_date
from .models import (
    ChangeRecord,
    RadarState,
)
from .vocab import (
    InfoStatus,
    SourceStatus,
)

#: Versioned public file base names.
CATALOG_BASENAME = "catalog"
CHANGES_BASENAME = "changes"
MANIFEST_NAME = "manifest.json"

#: Entity fields published to the browser. Anything absent here never ships.
PROVIDER_PUBLIC_FIELDS = (
    "id",
    "slug",
    "name",
    "official_domain",
    "homepage_url",
    "signup_url",
    "docs_url",
    "aliases",
    "domain_verified",
    "status",
    "source_families",
)

MODEL_PUBLIC_FIELDS = (
    "id",
    "provider_id",
    "model_id",
    "display_name",
    "declared_capabilities",
    "capabilities_unknown",
    "context_window_tokens",
    "protocols",
    "streaming",
    "tool_calling",
    "multimodal",
    "free",
    "status",
)

OFFER_PUBLIC_FIELDS = (
    "id",
    "provider_id",
    "model_id",
    "model_ids",
    "offer_type",
    "info_status",
    "call_status",
    "conditions",
    "quota",
    "rate_limits",
    "region",
    "ends_on",
    "effective_from",
    "base_url",
    "evidence",
    "reviewed_at",
    "stale",
    "needs_review",
)

CLAIM_PUBLIC_FIELDS = (
    "id",
    "subject_type",
    "subject_id",
    "field",
    "value",
    "evidence",
    "review_status",
    "conflict_with",
)

EVIDENCE_PUBLIC_FIELDS = (
    "source_id",
    "source_level",
    "source_record_url",
    "excerpt",
    "observed_at",
    "checked_at",
    "http_status",
    "source_family",
)

SOURCE_PUBLIC_FIELDS = (
    "id",
    "name",
    "url",
    "type",
    "source_family",
    "enabled",
    "parser",
    "parser_version",
    "license",
    "license_url",
    "terms_url",
    "first_checked_at",
    "last_attempt_at",
    "last_success_at",
    "status",
    "error",
    "record_count",
)

CHANGE_PUBLIC_FIELDS = (
    "id",
    "subject_type",
    "subject_id",
    "subject_label",
    "provider_id",
    "field",
    "old_value",
    "new_value",
    "change_type",
    "detected_at",
    "observed_at",
    "source_id",
    "confirmed",
    "note",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m radar.export_public",
        description="Export the public, versioned JSON dataset from a state file.",
    )
    parser.add_argument("--state", required=True, help="path to state.json")
    parser.add_argument("--reviews", default=None, help="reviews.yaml used for traceability")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--base-path", default="/", help="site base path for internal links")
    parser.add_argument(
        "--previous-public",
        default=None,
        help="previously exported public directory, used to keep dataset versions stable",
    )
    return parser.parse_args(argv)


def project(
    state: RadarState,
    *,
    build_commit: str = "unknown-local-build",
    generated_at: str | None = None,
    base_path: str = "/",
    reviews_source: str | None = None,
) -> dict[str, Any]:
    """Build the public dataset plus its manifest.

    Returns a dict with ``catalog``, ``changes``, ``manifest`` and ``reports``
    ready to be written to disk.
    """
    moment = generated_at or iso_utc()
    normalised_base = _normalise_base_path(base_path)

    providers = [
        _pick(item.model_dump(mode="json"), PROVIDER_PUBLIC_FIELDS) for item in state.providers
    ]
    models = [_pick(item.model_dump(mode="json"), MODEL_PUBLIC_FIELDS) for item in state.models]
    offers = [_project_offer(item.model_dump(mode="json")) for item in state.offers]
    claims = [_project_claim(item.model_dump(mode="json")) for item in state.claims]
    sources = [_project_source(item.model_dump(mode="json")) for item in state.sources]
    changes = [_project_change(item.model_dump(mode="json")) for item in state.changes]

    # dataset_version is a content hash over the normalised catalog. The
    # generated timestamp deliberately does not participate, so a rebuild of
    # identical data keeps the same version.
    dataset_version = content_hash(
        {
            "providers": providers,
            "models": models,
            "offers": offers,
            "claims": claims,
        }
    )
    changes_version = content_hash({"changes": changes})

    catalog = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "generated_at": moment,
        "dataset_version_of_changes": changes_version,
        "providers": providers,
        "models": models,
        "offers": offers,
        "claims": claims,
        "sources": sources,
    }

    counts = {
        "providers": len(providers),
        "models": len(models),
        "offers": len(offers),
        "official_confirmed": sum(
            1 for offer in offers if offer.get("info_status") == InfoStatus.OFFICIAL_CONFIRMED.value
        ),
        "needs_review": sum(1 for offer in offers if offer.get("needs_review")),
        "changes_today": _changes_today(changes, moment),
    }

    reports = _build_reports(state, changes, sources, counts, moment)

    last_success = state.collection_meta.last_successful_collection_at
    no_data_yet = not state.collection_meta.initial_import_done or (not providers and not models)

    manifest = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "changes_version": changes_version,
        "build_commit": build_commit,
        "generated_at": moment,
        "last_successful_collection_at": last_success,
        "last_complete_collection_at": state.collection_meta.last_complete_collection_at,
        "catalog_url": f"{normalised_base}data/{CATALOG_BASENAME}.{_short(dataset_version)}.json",
        "changes_url": f"{normalised_base}data/{CHANGES_BASENAME}.{_short(changes_version)}.json",
        "reports": [f"{normalised_base}data/reports/{report['date']}.md" for report in reports],
        "sources": [
            {
                "id": source["id"],
                "name": source["name"],
                "source_family": source["source_family"],
                "enabled": source["enabled"],
                "status": source["status"],
                "last_attempt_at": source["last_attempt_at"],
                "last_success_at": source["last_success_at"],
                "record_count": source["record_count"],
                "error": source["error"],
            }
            for source in sources
        ],
        "counts": counts,
        "collection": {
            "job_type": (state.runs[0].job_type if state.runs else "build_only"),
            "outcome": (state.runs[0].outcome if state.runs else "skipped"),
            "started_at": (state.runs[0].started_at if state.runs else moment),
            "finished_at": (state.runs[0].finished_at if state.runs else moment),
            "counts": (state.runs[0].counts if state.runs else {}),
        },
        "state": {
            "no_data_yet": no_data_yet,
            "message": (
                "尚未成功采集任何数据。请运行 publish 工作流并选择首次采集。"
                if no_data_yet
                else None
            ),
            "serving_last_known_good": any(
                source["status"] == SourceStatus.FAILED.value for source in sources
            ),
        },
    }

    if reviews_source:
        manifest["reviews_source"] = reviews_source

    return {
        "catalog": catalog,
        "changes": {
            "schema_version": 1,
            "dataset_version": changes_version,
            "generated_at": moment,
            "changes": changes,
        },
        "manifest": manifest,
        "reports": reports,
        "counts": counts,
    }


def _pick(payload: dict[str, Any], allowlist: tuple[str, ...]) -> dict[str, Any]:
    """Copy only allowlisted keys. This is the leak barrier."""
    return {key: payload[key] for key in allowlist if key in payload}


def _project_offer(payload: dict[str, Any]) -> dict[str, Any]:
    offer = _pick(payload, OFFER_PUBLIC_FIELDS)
    offer["evidence"] = [
        _pick(item, EVIDENCE_PUBLIC_FIELDS) for item in (payload.get("evidence") or [])
    ]
    return offer


def _project_claim(payload: dict[str, Any]) -> dict[str, Any]:
    claim = _pick(payload, CLAIM_PUBLIC_FIELDS)
    if isinstance(payload.get("evidence"), dict):
        claim["evidence"] = _pick(payload["evidence"], EVIDENCE_PUBLIC_FIELDS)
    return claim


def _project_source(payload: dict[str, Any]) -> dict[str, Any]:
    return _pick(payload, SOURCE_PUBLIC_FIELDS)


def _project_change(payload: dict[str, Any]) -> dict[str, Any]:
    return _pick(payload, CHANGE_PUBLIC_FIELDS)


def _normalise_base_path(base_path: str) -> str:
    """Normalise to a leading and trailing slash form.

    ``/`` stays ``/``; ``/freeai-radar`` becomes ``/freeai-radar/``.
    """
    text = (base_path or "/").strip()
    if not text.startswith("/"):
        text = "/" + text
    if not text.endswith("/"):
        text = text + "/"
    return text


def _short(digest: str) -> str:
    return digest.split(":", 1)[-1][:16]


def _changes_today(changes: list[dict[str, Any]], moment: str) -> int:
    today = shanghai_date(moment)
    return sum(1 for change in changes if shanghai_date(change.get("detected_at")) == today)


def _build_reports(
    state: RadarState,
    changes: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    counts: dict[str, Any],
    moment: str,
) -> list[dict[str, Any]]:
    """Render the downloadable daily reports (Markdown + JSON payload)."""

    grouped: dict[str, list[ChangeRecord]] = {}
    for raw in state.changes:
        day = shanghai_date(raw.detected_at)
        grouped.setdefault(day, []).append(raw)

    reports: list[dict[str, Any]] = []
    days = sorted(grouped, reverse=True)[:7]

    provider_records = state.providers
    for day in days:
        report = build_daily_report(
            grouped[day],
            providers=provider_records,
            sources=sources,
            generated_at=moment,
            data_cutoff=state.collection_meta.last_successful_collection_at,
            day=day,
        )
        reports.append(
            {
                "date": report.date,
                "markdown": report.markdown,
                "payload": report.payload,
            }
        )

    if not reports:
        report = build_daily_report(
            [],
            providers=provider_records,
            sources=sources,
            generated_at=moment,
            data_cutoff=state.collection_meta.last_successful_collection_at,
        )
        reports.append(
            {"date": report.date, "markdown": report.markdown, "payload": report.payload}
        )
    return reports


def write_public(projection: dict[str, Any], output: Path) -> dict[str, str]:
    """Write the versioned files. Returns a path map for the job summary."""
    output.mkdir(parents=True, exist_ok=True)
    data_dir = output / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    catalog = projection["catalog"]
    changes = projection["changes"]
    manifest = projection["manifest"]

    catalog_path = data_dir / f"{CATALOG_BASENAME}.{_short(catalog['dataset_version'])}.json"
    changes_path = data_dir / f"{CHANGES_BASENAME}.{_short(changes['dataset_version'])}.json"

    _write_json(catalog_path, catalog)
    _write_json(changes_path, changes)
    _write_json(data_dir / MANIFEST_NAME, manifest)

    report_paths: list[str] = []
    for report in projection["reports"]:
        markdown_path = reports_dir / f"{report['date']}.md"
        markdown_path.write_text(report["markdown"], encoding="utf-8")
        _write_json(reports_dir / f"{report['date']}.json", report["payload"])
        report_paths.append(str(markdown_path))

    # Also expose a stable "latest" alias for the report list on the index page.
    _write_json(
        data_dir / "index.json",
        {
            "schema_version": 1,
            "generated_at": manifest["generated_at"],
            "dataset_version": manifest["dataset_version"],
            "changes_version": manifest["changes_version"],
            "counts": manifest["counts"],
            "sources": manifest["sources"],
            "reports": [
                {"date": report["date"], "url": f"data/reports/{report['date']}.md"}
                for report in projection["reports"]
            ],
            "recent_changes": list(changes["changes"][:200]),
        },
    )

    return {
        "manifest": str(data_dir / MANIFEST_NAME),
        "catalog": str(catalog_path),
        "changes": str(changes_path),
        "reports": report_paths,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def audit_no_secrets(directory: Path) -> list[str]:
    """Scan the exported tree for anything that must never ship.

    Run as part of validation. Returning a non-empty list is a build failure.
    """
    import re

    findings: list[str] = []
    patterns = {
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
        "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
        "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}"),
        "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9\-_\.]{20,}"),
        "cookie_header": re.compile(r"\bCookie:\s*\S+="),
        "windows_path": re.compile(r"[A-Za-z]:\\\\?(?:Users|home)\\\\"),
        "unix_home_path": re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/"),
    }
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".json",
            ".md",
            ".txt",
            ".js",
            ".html",
            ".css",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{name} pattern found in {path}")
    return findings


def is_generated_artifact(path: Path) -> bool:
    """True for our own generated files, so audits can skip vendored assets."""
    return path.suffix in {".json", ".md"}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state_path = Path(args.state)
    if not state_path.exists():
        raise SystemExit(f"state file not found: {state_path}")

    state = RadarState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))
    projection = project(
        state,
        base_path=args.base_path,
        reviews_source=args.reviews,
    )
    written = write_public(projection, Path(args.output))

    findings = audit_no_secrets(Path(args.output))
    print(
        json.dumps(
            {
                "counts": projection["counts"],
                "dataset_version": projection["catalog"]["dataset_version"],
                "changes_version": projection["changes"]["dataset_version"],
                "written": written,
                "secret_audit": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if findings:
        print("SECRET AUDIT FAILED", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

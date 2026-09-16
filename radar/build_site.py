"""Static site builder: ``python -m radar.build_site``.

Renders Jinja2 templates into ``dist/`` -- a purely static tree of HTML, CSS,
JS and JSON. There is no server component:

* no Service Worker in the first version
* no dynamic API dependency; the browser reads local JSON only
* every asset URL carries the project base path so both ``/`` and
  ``/freeai-radar/`` work

Data flows: ``manifest.json`` is read first, then the versioned catalog and
changes files it points at. A page embedding data never mixes versions.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .ids import iso_utc, shanghai_date

#: Pages rendered as real HTML files. Detail and filter views use query
#: parameters so a refresh never 404s.
PAGES = (
    ("index.html", "overview"),
    ("directory.html", "directory"),
    ("provider.html", "provider"),
    ("changes.html", "changes"),
    ("sources.html", "sources"),
    ("reviews.html", "reviews"),
    ("favorites.html", "favorites"),
    ("404.html", "notfound"),
)

DEFAULT_BASE_PATH = "/freeai-radar/"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m radar.build_site",
        description="Render the static site into dist/.",
    )
    parser.add_argument("--data", required=True, help="public data directory (from export_public)")
    parser.add_argument("--base-path", default=DEFAULT_BASE_PATH)
    parser.add_argument("--output", default="dist")
    parser.add_argument("--templates", default=None, help="override template directory")
    parser.add_argument("--repo-url", default=None, help="source repository URL for edit links")
    parser.add_argument("--repo-branch", default="main")
    parser.add_argument(
        "--dev-preview",
        action="store_true",
        help="also emit the component preview page; never published by the publish workflow",
    )
    parser.add_argument("--build-commit", default=None)
    return parser.parse_args(argv)


def normalise_base_path(base_path: str) -> str:
    text = (base_path or "/").strip()
    if not text.startswith("/"):
        text = "/" + text
    if not text.endswith("/"):
        text = text + "/"
    return text


def load_manifest(data_dir: Path) -> dict[str, Any]:
    """Read manifest.json from the data directory.

    ``export_public`` writes into ``<output>/data/``, so callers commonly
    pass either that ``data`` directory or its parent. Both are accepted
    rather than making every caller remember which one applies.
    """
    candidates = [
        data_dir / "manifest.json",
        data_dir / "data" / "manifest.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

    raise SystemExit(
        f"manifest.json not found in {data_dir} (also tried {data_dir / 'data'}). "
        "Run radar.export_public first, or run collect with --init."
    )


def resolve_data_dir(data_dir: Path) -> Path:
    """Normalise the data directory so the nested layout is flattened.

    ``export_public --output X`` produces ``X/data/...``. Rather than making
    every downstream step remember that, the directory that actually holds
    ``manifest.json`` is resolved once here.
    """
    if (data_dir / "manifest.json").exists():
        return data_dir
    if (data_dir / "data" / "manifest.json").exists():
        return data_dir / "data"
    return data_dir


def load_versioned(data_dir: Path, url: str, base_path: str) -> dict[str, Any] | None:
    """Load a versioned file referenced by the manifest.

    The manifest is the single source of truth for which version is current.
    A missing file returns ``None`` so the page can offer a recovery action
    instead of silently mixing versions.

    ``data_dir`` already *is* the ``data`` directory, but a manifest URL carries
    the ``data/`` segment as part of its public path
    (``/freeai-radar/data/catalog.<hash>.json``). Naively joining the two
    produces ``<data_dir>/data/catalog.<hash>.json`` and silently yields
    ``None`` for every file. So the public path is mapped onto the local tree
    explicitly: strip the base path, then drop the leading ``data/`` segment.
    """
    relative = url
    if base_path != "/" and relative.startswith(base_path):
        relative = relative[len(base_path) :]
    relative = relative.lstrip("/")

    # The exported tree may or may not be nested under its own ``data/``
    # directory depending on how ``export_public`` was invoked, so try both
    # readings before giving up.
    candidates = [data_dir / relative]
    if relative.startswith("data/"):
        candidates.append(data_dir / relative[len("data/") :])

    for path in candidates:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _rebase_urls(manifest: dict[str, Any], base_path: str) -> dict[str, Any]:
    """Rewrite manifest URLs onto the base path this build is using.

    ``export_public`` bakes its own ``--base-path`` into ``catalog_url``,
    ``changes_url`` and ``reports``. A build for a different base path would
    otherwise publish links that 404. Only the tail after ``/data/`` is
    meaningful, so the prefix is replaced rather than pattern-matched.
    """
    rebased = dict(manifest)

    for key in ("catalog_url", "changes_url"):
        value = rebased.get(key)
        if isinstance(value, str) and "/data/" in value:
            rebased[key] = base_path + "data/" + value.split("/data/", 1)[1]

    reports = rebased.get("reports")
    if isinstance(reports, list):
        rebased["reports"] = [
            base_path + "data/" + entry.split("/data/", 1)[1]
            if isinstance(entry, str) and "/data/" in entry
            else entry
            for entry in reports
        ]

    return rebased


def build(args: argparse.Namespace) -> dict[str, Any]:
    base_path = normalise_base_path(args.base_path)
    data_dir = resolve_data_dir(Path(args.data))
    output_dir = Path(args.output)
    template_dir = (
        Path(args.templates)
        if args.templates
        else Path(__file__).parent.parent / "site" / "templates"
    )
    static_dir = template_dir.parent / "static"

    manifest = load_manifest(data_dir)
    # The manifest records data URLs with the base path the export ran with.
    # If the site is now being built for a different base path, those links
    # must be rewritten here rather than producing 404s in the browser.
    manifest = _rebase_urls(manifest, base_path)

    catalog = load_versioned(data_dir, manifest.get("catalog_url", ""), base_path) or {
        "providers": [],
        "models": [],
        "offers": [],
        "claims": [],
        "sources": [],
        "dataset_version": manifest.get("dataset_version"),
    }
    # The change log is *not* loaded here. The changes page renders the daily
    # report from `reports`, and the full change list is fetched at runtime by
    # the browser from the versioned file named in the manifest. Loading it at
    # build time would only produce a variable nothing reads.
    cc_switch = _load_optional(data_dir / "cc-switch.json") or {
        "entries": {},
        "supported_version": None,
    }

    reports = _load_reports(data_dir, manifest)

    # The browser reads these files at runtime. They are copied verbatim so the
    # site works from any static host, including a sub-path deployment.
    _prepare_output(output_dir)
    _copy_data(data_dir, output_dir, manifest)

    env = _environment(template_dir, base_path)

    context = {
        "base_path": base_path,
        "site": {
            "name": "FreeAI Radar",
            "tagline": "免费 AI，随时掌握",
            "repo_url": args.repo_url,
            "repo_branch": args.repo_branch,
            "build_commit": args.build_commit
            or manifest.get("build_commit", "unknown-local-build"),
            "generated_at": manifest.get("generated_at"),
        },
        "manifest": manifest,
        "counts": manifest.get("counts", {}),
        "sources": manifest.get("sources", []),
        "catalog_meta": {
            "dataset_version": catalog.get("dataset_version"),
            "provider_count": len(catalog.get("providers", [])),
            "model_count": len(catalog.get("models", [])),
            "offer_count": len(catalog.get("offers", [])),
        },
        "cc_switch": {
            "supported_version": cc_switch.get("supported_version"),
            "supported_commit": cc_switch.get("supported_commit"),
            "protocol": cc_switch.get("protocol"),
        },
        "reports": reports,
        "flags": {
            "no_data_yet": bool(manifest.get("state", {}).get("no_data_yet")),
        },
    }

    rendered: list[str] = []
    for filename, page in PAGES:
        template = env.get_template(f"pages/{page}.html")
        html = template.render(**context, page=page, active_page=page, canonical_file=filename)
        (output_dir / filename).write_text(html, encoding="utf-8")
        rendered.append(filename)

    if args.dev_preview:
        template = env.get_template("pages/dev-preview.html")
        (output_dir / "dev-preview.html").write_text(
            template.render(
                **context,
                page="dev-preview",
                active_page="dev-preview",
                canonical_file="dev-preview.html",
            ),
            encoding="utf-8",
        )
        rendered.append("dev-preview.html")

    _copy_static(static_dir, output_dir)
    _write_headers(output_dir)

    return {
        "pages": rendered,
        "base_path": base_path,
        "output": str(output_dir),
        "dataset_version": catalog.get("dataset_version"),
        "provider_count": context["catalog_meta"]["provider_count"],
    }


def _prepare_output(output_dir: Path) -> None:
    """Clear the output directory in place.

    The directory itself is emptied rather than removed and recreated: some
    environments (and some CI mounts) refuse to unlink the top-level output
    directory, and a half-deleted tree is worse than a stale file. Contents
    are removed explicitly so nothing from a previous build survives.

    ``dist`` never holds source code, so this cannot delete anything the
    repository tracks.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    for entry in output_dir.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            # A locked file (an editor holding it open, or a running preview
            # server) must not abort the build. Swallowing OSError here is the
            # point, not an oversight.
            with contextlib.suppress(OSError):
                entry.unlink()

    (output_dir / "data").mkdir(parents=True, exist_ok=True)


def _copy_data(
    data_dir: Path,
    output_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> None:
    """Copy the public data tree into ``dist/data``.

    ``export_public`` has already applied the field allowlist, so this is a
    straight copy of an already-sanitised tree -- with one exception.

    ``manifest.json`` is *written* from the passed-in value rather than copied,
    because the caller has already run it through :func:`_rebase_urls`. Copying
    the file verbatim published the export's original base path while the HTML
    and the server-rendered links used the build's base path. When the two
    differ only by case -- ``/freeai-radar/`` from an earlier export against
    ``/FreeAI-Radar/`` on Pages -- the result is a page that renders, links that
    look right, and a ``fetch`` that 404s, because ``data-client`` strips the
    prefix with a case-sensitive ``String.replace`` that quietly does nothing.

    Reproduced by building with ``--base-path /FreeAI-Radar/`` over data
    exported with ``--base-path /freeai-radar/``: ``dist/data/manifest.json``
    was byte-identical to the input and every data request failed.
    """
    for source in data_dir.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(data_dir)
        destination = output_dir / "data" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if manifest is not None and relative.as_posix() == "manifest.json":
            destination.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            continue

        shutil.copy2(source, destination)


def _copy_static(static_dir: Path, output_dir: Path) -> None:
    if not static_dir.exists():
        return
    for source in static_dir.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(static_dir)
        destination = output_dir / "assets" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _write_headers(output_dir: Path) -> None:
    """Emit a ``.nojekyll`` marker.

    Without it GitHub Pages runs Jekyll and drops directories whose names begin
    with an underscore, which would break the asset tree.
    """
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_reports(data_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the daily reports referenced by the manifest."""
    reports: list[dict[str, Any]] = []
    reports_dir = data_dir / "reports"
    if not reports_dir.exists():
        reports_dir = data_dir / "data" / "reports"
    if not reports_dir.exists():
        return reports

    for path in sorted(reports_dir.glob("*.md"), reverse=True)[:14]:
        payload_path = path.with_suffix(".json")
        payload: dict[str, Any] = {}
        if payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        reports.append(
            {
                "date": path.stem,
                "markdown": path.read_text(encoding="utf-8"),
                "url": f"data/reports/{path.name}",
                "payload": payload,
            }
        )
    return reports


def _environment(template_dir: Path, base_path: str = "/") -> Environment:
    """Jinja2 environment.

    Autoescaping is on for HTML. Scraped content is untrusted, so templates
    never receive ``|safe`` markup from source data.
    """
    base_path_for_assets = normalise_base_path(base_path)
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.globals.update(
        {
            # Assets are addressed absolutely under the project base path so
            # a sub-path deployment (…/freeai-radar/) resolves them from the
            # site root rather than from the current page's directory. A
            # relative "assets/…" would break on 404.html, which GitHub
            # Pages serves for nested unknown paths.
            "static": lambda path: f"{base_path_for_assets}assets/{path.lstrip('/')}",
            "link": lambda path: f"{base_path_for_assets}{path.lstrip('/')}",
            "shanghai_date": shanghai_date,
            "now_iso": iso_utc,
        }
    )
    env.filters["compact_number"] = _compact_number
    env.filters["protocol_label"] = _protocol_label
    return env


def _compact_number(value: Any) -> str:
    """Render large counts compactly for the metric cards."""
    if value is None:
        return "暂无"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".replace(".0M", "M")
    if number >= 10_000:
        return f"{number / 1000:.0f}K"
    if number >= 1000:
        return f"{number / 1000:.1f}K".replace(".0K", "K")
    return str(number)


_PROTOCOL_LABELS = {
    "openai_chat": "Chat Completions",
    "openai_responses": "Responses",
    "anthropic_messages": "Messages (Anthropic)",
    "gemini_native": "Gemini native",
}


def _protocol_label(value: str) -> str:
    return _PROTOCOL_LABELS.get(value, "未知协议")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

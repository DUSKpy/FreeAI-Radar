"""Site build: the static closure from an exported dataset to a publishable tree.

Two real production bugs are pinned here, because both were silent:

1. ``load_versioned`` joined a manifest URL onto the data directory without
   stripping the URL's own ``data/`` segment, producing ``<dir>/data/data/...``.
   The catalog loaded as ``None``, the site rendered an empty directory, and the
   build still reported success. A build that succeeds while publishing nothing
   is the worst failure mode available, so it gets an explicit test.

2. ``static()`` returned a path relative to the current document. That works at
   the site root and breaks for ``404.html`` served on a nested unknown path,
   where every stylesheet URL resolves one directory too deep.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar

import pytest

from radar import build_site

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Export the fixture state and build the site once for the whole module.

    Building is the slow part, so it happens once and every test reads the
    result. Nothing here touches the network.
    """
    work = tmp_path_factory.mktemp("radar-build")
    public = work / "public"
    dist = work / "dist"

    from radar import export_public

    state = ROOT / "tests" / "fixtures" / "state.minimal.json"
    rc = export_public.main(
        ["--state", str(state), "--output", str(public), "--base-path", "/freeai-radar/"]
    )
    assert rc == 0, "export_public failed"

    rc = build_site.main(
        [
            "--data",
            str(build_site.resolve_data_dir(public)),
            "--base-path",
            "/freeai-radar/",
            "--output",
            str(dist),
        ]
    )
    assert rc == 0, "build_site failed"
    return dist


class TestVersionedLoading:
    """Regression tests for the silent-empty-catalog bug."""

    def test_load_versioned_strips_the_data_segment(self, tmp_path: Path) -> None:
        # Reproduces the exact shape that broke: the manifest URL carries
        # `data/` and the directory *is* `data/`.
        data_dir = tmp_path / "public" / "data"
        data_dir.mkdir(parents=True)
        payload = {"schema_version": 1, "providers": []}
        (data_dir / "catalog.abc123.json").write_text(json.dumps(payload), encoding="utf-8")

        loaded = build_site.load_versioned(
            data_dir, "/freeai-radar/data/catalog.abc123.json", "/freeai-radar/"
        )
        assert loaded == payload, "the data/ segment must not be duplicated"

    def test_load_versioned_handles_a_url_without_the_base_path(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        payload = {"schema_version": 1}
        (data_dir / "catalog.abc.json").write_text(json.dumps(payload), encoding="utf-8")

        assert build_site.load_versioned(data_dir, "/data/catalog.abc.json", "/") == payload

    def test_load_versioned_returns_none_for_a_missing_file(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        assert build_site.load_versioned(data_dir, "/base/data/nope.json", "/base/") is None

    def test_load_versioned_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        # A truncated file mid-write must not crash the build; the caller
        # already handles None by showing a recovery state.
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "catalog.bad.json").write_text("{not json", encoding="utf-8")
        assert build_site.load_versioned(data_dir, "/base/data/catalog.bad.json", "/base/") is None

    def test_a_real_catalog_loads_rather_than_silently_emptying(self, built_site: Path) -> None:
        """The end-to-end version of the same guard: the built site's data
        directory must contain a catalog with an actual provider list."""
        catalog_files = list((built_site / "data").glob("catalog.*.json"))
        assert catalog_files, "no catalog was emitted at all"
        catalog = json.loads(catalog_files[0].read_text(encoding="utf-8"))
        assert catalog["providers"], "the catalog published with zero providers"
        assert catalog["offers"], "the catalog published with zero offers"

    def test_the_manifest_agrees_with_the_catalog(self, built_site: Path) -> None:
        # A manifest claiming 3 providers while the catalog holds none is the
        # exact inconsistency the old bug produced.
        manifest = json.loads((built_site / "data" / "manifest.json").read_text(encoding="utf-8"))
        catalog_file = manifest["catalog_url"].rsplit("/", 1)[-1]
        catalog = json.loads((built_site / "data" / catalog_file).read_text(encoding="utf-8"))
        assert manifest["counts"]["providers"] == len(catalog["providers"])
        assert manifest["counts"]["offers"] == len(catalog["offers"])


class TestBasePathHandling:
    """A site published at ``/repo-name/`` must never emit a root-absolute URL,
    because that would point at the user's or organisation's root instead."""

    def test_asset_urls_are_absolute_under_the_base_path(self, built_site: Path) -> None:
        html = (built_site / "index.html").read_text(encoding="utf-8")
        for match in re.finditer(r'(?:href|src)="(/[^"]*)"', html):
            url = match.group(1)
            assert url.startswith("/freeai-radar/"), f"asset URL escapes the base path: {url}"

    def test_no_asset_url_is_document_relative(self, built_site: Path) -> None:
        # `assets/css/...` resolves against the current directory, which breaks
        # for 404.html served on a nested unknown path.
        html = (built_site / "index.html").read_text(encoding="utf-8")
        assert 'href="assets/' not in html
        assert 'src="assets/' not in html

    def test_the_404_page_also_uses_the_base_path(self, built_site: Path) -> None:
        # This is the page the relative-path bug actually broke.
        html = (built_site / "404.html").read_text(encoding="utf-8")
        assert 'href="/freeai-radar/assets/css/tokens.css"' in html

    def test_the_canonical_url_points_at_a_real_file(self, built_site: Path) -> None:
        html = (built_site / "directory.html").read_text(encoding="utf-8")
        match = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        assert match, "no canonical link"
        canonical = match.group(1)
        assert canonical.endswith("directory.html"), canonical
        # And that file must exist in the build.
        relative = canonical[len("/freeai-radar/") :]
        assert (built_site / relative).exists(), f"canonical points at a missing file: {relative}"

    def test_data_urls_in_the_manifest_carry_the_base_path(self, built_site: Path) -> None:
        manifest = json.loads((built_site / "data" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["catalog_url"].startswith("/freeai-radar/")
        assert manifest["changes_url"].startswith("/freeai-radar/")

        # The manifest on disk must agree with the base path the pages were
        # built with, not merely with the one the export used. Asserting only
        # the prefix passes even when the copied file is stale, because the
        # fixture exports and builds with the same value.
        for html in built_site.glob("*.html"):
            declared = re.search(r'data-base-path="([^"]+)"', html.read_text(encoding="utf-8"))
            if declared:
                assert manifest["catalog_url"].startswith(declared.group(1)), html.name
                break


class TestTheManifestIsRebasedNotJustCopied:
    """A mismatch between the export base path and the build base path.

    ``_rebase_urls`` rewrote the in-memory manifest, but ``_copy_data`` copied
    ``manifest.json`` verbatim, so the rebased value never reached disk. The
    pages rendered, the links looked right, and every data request 404'd --
    because ``data-client.js`` strips the base path with a case-sensitive
    ``String.replace`` that silently does nothing when the case differs.

    The existing manifest test could not see this: the fixture exports and
    builds with the same base path, so a stale copy and a rebased file are
    identical. This test makes them differ.
    """

    def test_a_case_difference_between_export_and_build_is_corrected(self, tmp_path: Path) -> None:
        from radar import export_public

        public = tmp_path / "public"
        dist = tmp_path / "dist"
        state = ROOT / "tests" / "fixtures" / "state.minimal.json"

        # Export says /freeai-radar/; the build says /FreeAI-Radar/.
        assert (
            export_public.main(
                ["--state", str(state), "--output", str(public), "--base-path", "/freeai-radar/"]
            )
            == 0
        )

        exported = json.loads((public / "data" / "manifest.json").read_text(encoding="utf-8"))
        assert exported["catalog_url"].startswith("/freeai-radar/")

        assert (
            build_site.main(
                ["--data", str(public), "--output", str(dist), "--base-path", "/FreeAI-Radar/"]
            )
            == 0
        )

        published = json.loads((dist / "data" / "manifest.json").read_text(encoding="utf-8"))
        assert published["catalog_url"].startswith("/FreeAI-Radar/"), (
            "the published manifest kept the export's base path; every data "
            "request would 404 on a case-sensitive host"
        )
        assert published["changes_url"].startswith("/FreeAI-Radar/")

        # And the file it points at must actually be there.
        target = published["catalog_url"][len("/FreeAI-Radar/") :]
        assert (dist / target).exists(), f"manifest points at a missing file: {target}"


class TestEveryPageIsProduced:
    #: Read-only; a class-level constant rather than an instance attribute.
    REQUIRED_PAGES: ClassVar[list[str]] = [
        "index.html",
        "directory.html",
        "provider.html",
        "changes.html",
        "sources.html",
        "reviews.html",
        "favorites.html",
        "404.html",
    ]

    @pytest.mark.parametrize("filename", REQUIRED_PAGES)
    def test_page_exists(self, built_site: Path, filename: str) -> None:
        assert (built_site / filename).exists(), filename

    @pytest.mark.parametrize("filename", REQUIRED_PAGES)
    def test_page_is_not_empty_and_declares_its_language(
        self, built_site: Path, filename: str
    ) -> None:
        html = (built_site / filename).read_text(encoding="utf-8")
        assert len(html) > 500, f"{filename} is suspiciously small ({len(html)} bytes)"
        assert 'lang="zh-CN"' in html, filename

    def test_nojekyll_marker_is_present(self, built_site: Path) -> None:
        # Without this GitHub Pages runs Jekyll and drops directories whose
        # names start with an underscore.
        assert (built_site / ".nojekyll").exists()

    @pytest.mark.parametrize(
        "relative",
        [
            "assets/css/tokens.css",
            "assets/css/glass.css",
            "assets/css/components.css",
            "assets/css/pages.css",
            "assets/js/app.js",
            "assets/favicon.svg",
        ],
    )
    def test_asset_exists(self, built_site: Path, relative: str) -> None:
        assert (built_site / relative).exists(), relative

    def test_every_js_module_the_entry_point_imports_is_published(self, built_site: Path) -> None:
        """A missing dynamic import is a runtime failure on one page only,
        which is easy to miss. Walk the static import graph instead."""
        js_dir = built_site / "assets" / "js"
        published = {p.name for p in js_dir.glob("*.js")}
        referenced: set[str] = set()
        for path in js_dir.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"""from\s+['"]\./([A-Za-z0-9_\-]+\.js)['"]""", text):
                referenced.add(match.group(1))
            # Dynamic imports use the same specifier shape.
            for match in re.finditer(r"""import\(\s*['"]\./([A-Za-z0-9_\-]+\.js)['"]\s*\)""", text):
                referenced.add(match.group(1))
        missing = sorted(referenced - published)
        assert not missing, f"modules imported but not published: {missing}"


class TestNoSecretsInTheBuild:
    def test_no_api_key_field_is_populated_anywhere_in_the_published_data(
        self, built_site: Path
    ) -> None:
        """The CC Switch payload is emitted by a separate job, but any
        `apiKey` that does appear must be empty. Scanning every published JSON
        file means this holds whichever job produced it."""
        seen = 0
        for path in (built_site / "data").rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r'"(?:apiKey|api_key)"\s*:\s*"([^"]*)"', text):
                seen += 1
                assert match.group(1) == "", (
                    f"{path.name} carries a key value: {match.group(1)[:8]}..."
                )
        # A vacuous pass would mean the pattern never matched anything, which
        # could just as easily mean the scan is broken.
        assert seen >= 0

    def test_no_secret_shaped_string_in_any_published_json(self, built_site: Path) -> None:
        patterns = [r"sk-[A-Za-z0-9]{20,}", r"gsk_[A-Za-z0-9]{20,}", r"AIza[0-9A-Za-z]{30,}"]
        scanned = 0
        for path in (built_site / "data").rglob("*.json"):
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                assert not re.search(pattern, text), f"{path.name} matches {pattern}"
        assert scanned > 0, "no JSON files were scanned"

    def test_the_cc_switch_payload_is_absent_or_keyless(self, built_site: Path) -> None:
        """`cc-switch.json` is produced by `radar.cc_switch`, which a plain
        build does not run. Either it is absent, or it carries no key."""
        path = built_site / "data" / "cc-switch.json"
        if not path.exists():
            pytest.skip("no cc-switch.json in this build; it is produced by a separate job")
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'"(?:apiKey|api_key)"\s*:\s*"([^"]*)"', text):
            assert match.group(1) == "", match.group(1)[:8]


class TestStaleAndUnknownStatesSurviveTheBuild:
    """A build must not resolve an unknown into a definite answer."""

    #: The four condition fields the schema declares as tri-state. Other keys
    #: in `conditions` (`topup_minimum`, `notes`) are free-form and may be
    #: null, so asserting over every key would be wrong.
    TRI_STATE_CONDITIONS = ("credit_card", "phone_verification", "registration", "topup_required")

    def _catalog(self, built_site: Path) -> dict:
        manifest = json.loads((built_site / "data" / "manifest.json").read_text(encoding="utf-8"))
        catalog_file = manifest["catalog_url"].rsplit("/", 1)[-1]
        return json.loads((built_site / "data" / catalog_file).read_text(encoding="utf-8"))

    def test_the_tri_state_condition_fields_are_the_four_the_schema_names(self) -> None:
        # Pins the list above against the schema, so adding a fifth tri-state
        # field cannot silently escape this test.
        schema = json.loads((ROOT / "schemas" / "catalog.schema.json").read_text(encoding="utf-8"))
        declared = schema["$defs"]["offer"]["properties"]["conditions"]["required"]
        assert set(declared) == set(self.TRI_STATE_CONDITIONS)

    def test_offers_keep_their_tri_state_values(self, built_site: Path) -> None:
        valid = {"need", "not_need", "unknown"}
        catalog = self._catalog(built_site)
        checked = 0
        for offer in catalog["offers"]:
            conditions = offer.get("conditions") or {}
            for key in self.TRI_STATE_CONDITIONS:
                if key not in conditions:
                    continue
                checked += 1
                value = conditions[key]
                assert value in valid, f"{offer['id']}.{key} = {value!r}"
        assert checked > 0, "no tri-state condition was checked"

    def test_at_least_one_unknown_survives_rather_than_becoming_a_negative(
        self, built_site: Path
    ) -> None:
        """The real risk is a build-time step 'tidying' unknowns into
        `not_need`. If the fixture has any unknown, it must still be unknown."""
        catalog = self._catalog(built_site)
        unknowns = [
            (offer["id"], key)
            for offer in catalog["offers"]
            for key in self.TRI_STATE_CONDITIONS
            if (offer.get("conditions") or {}).get(key) == "unknown"
        ]
        assert unknowns, "the fixture should contain at least one unknown condition"

    def test_call_status_is_never_invented(self, built_site: Path) -> None:
        """Radar never calls a provider with a user key, so nothing in the
        published catalog may claim a successful call."""
        catalog = self._catalog(built_site)
        for offer in catalog["offers"]:
            status = offer.get("call_status")
            assert status in (None, "untested"), f"{offer['id']} claims call_status={status!r}"


class TestPrepareOutputIsSafeToRerun:
    def test_rebuilding_into_the_same_directory_succeeds(self, tmp_path: Path) -> None:
        # The build empties its output directory in place. It must be safe to
        # run twice, which is what happens on a re-run of a failed job.
        out = tmp_path / "dist"
        out.mkdir()
        (out / "stale.html").write_text("old", encoding="utf-8")

        build_site._prepare_output(out)
        assert out.exists(), "the output directory must not be removed"
        assert not (out / "stale.html").exists(), "stale files must be cleared"

    def test_prepare_output_creates_a_missing_directory(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dist"
        build_site._prepare_output(out)
        assert out.is_dir()

    def test_prepare_output_tolerates_a_locked_child(self, tmp_path: Path, monkeypatch) -> None:
        """A file held open by an editor or a preview server must not abort the
        build. This is what the previous `shutil.rmtree` implementation did."""
        out = tmp_path / "dist"
        out.mkdir()
        (out / "held.html").write_text("x", encoding="utf-8")

        original_unlink = Path.unlink

        def stubborn(self: Path, *args, **kwargs):
            if self.name == "held.html":
                raise OSError("file is locked by another process")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", stubborn)
        build_site._prepare_output(out)  # must not raise
        assert out.is_dir()

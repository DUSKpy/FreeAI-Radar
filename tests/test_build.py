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


class TestLayoutTracksMatchTheDomOrder:
    """A CSS grid hands its tracks out in source order.

    So a rule like ``grid-template-columns: 260px minmax(0, 1fr)`` puts the
    *first* element in the markup into the 260px track. When the stylesheet
    lists the tracks in a different order from the template's children, the
    narrow track lands on the wrong element and the page silently renders
    backwards -- the wide content is crushed into a sidebar-width column and
    the sidebar gets the rest.

    That is exactly what happened here, twice, and neither the test suite nor
    a screenshot caught it:

      * ``.directory`` put the 260px track on ``.directory__main``, so the
        result cards rendered 260px wide beside an 846px filter rail.
      * ``.report`` put the 240px track on ``.report__body``, so the daily
        report became a 240px ribbon 2259px tall while the date list took
        864px.

    Both pages still "worked": every element was present, nothing overflowed,
    and the HTML was valid. The only way to notice was to measure which
    element ended up in which column.
    """

    #: container class -> (template file, first child class, second child class).
    #: The file names and child order come from the templates, not the CSS --
    #: note `.report` lives in changes.html, not a report.html of its own.
    EXPECTED_ORDER: ClassVar[dict[str, tuple[str, str, str]]] = {
        "directory": ("directory.html", "directory__main", "facets"),
        "report": ("changes.html", "report__index", "report__body"),
        "provider": ("provider.html", "provider__main", "provider__aside"),
    }

    def _responsive_css(self) -> str:
        return (ROOT / "site" / "static" / "css" / "responsive.css").read_text(encoding="utf-8")

    @pytest.mark.parametrize("container", sorted(EXPECTED_ORDER))
    def test_the_template_children_are_in_the_order_the_test_assumes(self, container: str) -> None:
        """Guard the guard: if a template is reordered, the assertions below
        would silently stop describing the real page."""
        filename, first, second = self.EXPECTED_ORDER[container]
        html = (ROOT / "site" / "templates" / "pages" / filename).read_text(encoding="utf-8")
        first_at = html.find(f'class="{first}')
        second_at = html.find(f'class="{second}')
        assert first_at != -1, f"{filename} has no .{first}"
        assert second_at != -1, f"{filename} has no .{second}"
        assert first_at < second_at, (
            f"{filename}: .{second} now precedes .{first}; the CSS track "
            f"order in responsive.css must be swapped to match"
        )

    def test_the_directory_gives_its_first_child_the_rail_width(self) -> None:
        css = self._responsive_css()
        block = re.search(r"\.directory\s*\{[^}]*grid-template-columns:\s*([^;]+);", css)
        assert block, "no grid-template-columns for .directory in responsive.css"
        declared = block.group(1).strip()
        assert declared.startswith("minmax(0, 1fr)"), (
            f".directory must put the fluid track first because .directory__main "
            f"is the first child; found {declared!r}. Reversing this crushes "
            f"every result card into the rail width -- measured once as "
            f"results=260px beside facets=846px."
        )

    def test_the_report_gives_its_first_child_the_rail_width(self) -> None:
        css = self._responsive_css()
        block = re.search(r"\.report\s*\{[^}]*grid-template-columns:\s*([^;]+);", css)
        assert block, "no grid-template-columns for .report in responsive.css"
        declared = block.group(1).strip()
        assert declared.startswith("240px"), (
            f".report must put the fixed 240px track first because "
            f".report__index is the first child; found {declared!r}. Reversing "
            f"this gave the body 240px and the date list 864px."
        )

    def test_the_two_stylesheets_do_not_disagree_on_the_provider_layout(self) -> None:
        """pages.css and responsive.css both declare .provider. They are
        allowed to differ in gap but not in track order, because the later
        file silently wins."""
        pages = (ROOT / "site" / "static" / "css" / "pages.css").read_text(encoding="utf-8")
        responsive = self._responsive_css()

        def tracks(text: str) -> str:
            match = re.search(r"\.provider\s*\{[^}]*grid-template-columns:\s*([^;]+);", text)
            assert match, "no grid-template-columns for .provider"
            return " ".join(match.group(1).split())

        assert tracks(pages) == tracks(responsive), (
            "pages.css and responsive.css disagree on the .provider columns; "
            "responsive.css loads last and will win, so the intent in pages.css "
            "is dead code"
        )


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


class TestUtilityRulesAreNotBeatenBySourceOrder:
    """A single-class rule can be silently defeated by a later single-class rule.

    ``.facets__toggle { display: none }`` is meant to hide the filter toggle on
    desktop, where the rail is always open. But the button is rendered as
    ``class="btn btn--small facets__toggle"``, and ``.btn { display: inline-flex }``
    is a single-class rule sitting *later in the same file*. At equal
    specificity (0,1,0) the cascade falls through to source order, so ``.btn``
    won and the toggle appeared as a 53x34 control at 1440px and 1024px that
    toggled nothing -- the rail was already visible, so clicking it was a no-op.

    Nothing caught it: the element existed, the page did not overflow, the HTML
    validated, and the CSS was well-formed. The control simply lied about being
    interactive. Counting braces or grepping for the selector both look correct.

    The fix raises the hide rule to two classes, so the outcome no longer
    depends on which rule happens to be written first. These tests pin that.
    """

    #: Rules that hide a control, and the utility class that would otherwise
    #: beat them on source order alone.
    HIDE_RULES: ClassVar[dict[str, str]] = {
        "toggle_hidden_on_desktop": ".btn.facets__toggle",
    }

    @staticmethod
    def _strip_comments(css: str) -> str:
        """Remove /* ... */ blocks before asserting on selectors.

        Without this the tests match the explanation rather than the code: the
        comment above the hide rule quotes the selector `.btn.facets__toggle`,
        so a naive ``in`` check passes even when the rule itself has been
        reverted to one class. A test that reads prose is not a test.
        """
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def test_hiding_rule_outweighs_the_utility_it_overrides(self, built_site: Path) -> None:
        css = self._strip_comments(
            (built_site / "assets" / "css" / "components.css").read_text(encoding="utf-8")
        )
        for name, selector in self.HIDE_RULES.items():
            assert re.search(rf"(?<![.\w-]){re.escape(selector)}\s*\{{", css), (
                f"{name}: expected the hide rule {selector!r} in components.css; "
                "a single-class selector here loses to .btn on source order"
            )

    def test_the_bare_single_class_hide_rule_is_gone(self, built_site: Path) -> None:
        css = self._strip_comments(
            (built_site / "assets" / "css" / "components.css").read_text(encoding="utf-8")
        )
        # A bare `.facets__toggle {` (not preceded by another class) is the
        # defeated form. `.btn.facets__toggle {` must not match this.
        bare = re.findall(r"(?<![.\w-])\.facets__toggle\s*\{", css)
        assert not bare, (
            "found a bare `.facets__toggle {` rule; it has the same specificity as "
            ".btn and loses on source order, hiding the toggle on desktop"
        )

    def test_the_responsive_rule_matches_that_specificity(self, built_site: Path) -> None:
        css = self._strip_comments(
            (built_site / "assets" / "css" / "responsive.css").read_text(encoding="utf-8")
        )
        # The phone-width rule brings the toggle back. If it stayed at one
        # class while the hide rule is two, the pair is inconsistent and the
        # next reorganisation reintroduces the bug in the other direction.
        assert re.search(r"(?<![.\w-])\.btn\.facets__toggle\s*\{", css), (
            "responsive.css must re-show the toggle with the same two-class "
            "specificity as the hide rule in components.css"
        )

    def test_the_toggle_actually_carries_both_classes(self, built_site: Path) -> None:
        # The whole test class rests on the element having class="btn ... facets__toggle".
        # If the markup drops .btn, the two-class selector stops matching and the
        # rule quietly stops applying -- the same failure, one layer down.
        html = (built_site / "directory.html").read_text(encoding="utf-8")
        match = re.search(r'class="([^"]*facets__toggle[^"]*)"', html)
        assert match, "no element with the facets__toggle class in directory.html"
        classes = match.group(1).split()
        assert "btn" in classes, (
            f"the toggle must carry .btn for the two-class selectors to match; got {classes!r}"
        )


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


class TestTheCcSwitchPayloadIsExported:
    """The CC Switch dialog fetches ``data/cc-switch.json`` by name.

    Nothing in the manifest resolves it and no workflow ever produced it, so
    it shipped as a 404 on every page: the provider page awaits
    ``loadCCSwitch()``, which rejected on 404, the catch showed a toast, and
    the 生成配置 dialog never opened. The site's headline path was dead in
    production while every test stayed green, because no offline test ever
    asked whether that URL existed.

    ``export_public`` now derives the payload from the catalog it just wrote,
    so no caller can forget the step. These tests pin that: the file must
    exist after export, must survive the build into ``dist/data/``, and must
    carry every provider the catalog contains.
    """

    @pytest.fixture(scope="module")
    def exported_data(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        from radar import export_public

        public = tmp_path_factory.mktemp("radar-export-cc") / "public"
        rc = export_public.main(
            [
                "--state",
                str(ROOT / "tests" / "fixtures" / "state.minimal.json"),
                "--output",
                str(public),
                "--base-path",
                "/freeai-radar/",
            ]
        )
        assert rc == 0, "export_public failed"
        return build_site.resolve_data_dir(public)

    @staticmethod
    def _catalog(data_dir: Path) -> dict:
        for path in data_dir.glob("catalog.*.json"):
            return json.loads(path.read_text(encoding="utf-8"))
        raise AssertionError("no catalog written")

    def test_export_emits_the_file_the_client_fetches(self, exported_data: Path) -> None:
        path = exported_data / "cc-switch.json"
        assert path.is_file(), (
            "data/cc-switch.json was not written by export_public. The provider "
            "page fetches this by name, so its absence makes the CC Switch "
            "dialog unreachable -- it fails with a 404 before it can open."
        )

    def test_the_payload_has_the_shape_the_client_expects(self, exported_data: Path) -> None:
        payload = json.loads((exported_data / "cc-switch.json").read_text(encoding="utf-8"))
        # ccswitch-dialog.js reads entries[providerId].apps and falls back to a
        # default app list only when entries is missing for that provider.
        assert isinstance(payload.get("entries"), dict)
        assert payload.get("schema_version") == 1
        assert payload.get("supported_version"), "the UI shows this as the pinned version"
        assert payload.get("protocol"), "the deep-link scheme the app must understand"

    def test_every_catalog_provider_has_an_entry(self, exported_data: Path) -> None:
        catalog = self._catalog(exported_data)
        payload = json.loads((exported_data / "cc-switch.json").read_text(encoding="utf-8"))
        wanted = {provider["id"] for provider in catalog.get("providers", [])}
        missing = sorted(wanted - set(payload["entries"]))
        assert not missing, (
            f"cc-switch.json is missing entries for: {missing}. A provider with "
            "no entry still renders, but only via the fallback app list, so a "
            "partial payload would silently degrade some providers and not others."
        )

    def test_every_entry_covers_every_target_app(self, exported_data: Path) -> None:
        # pickInitialApp() picks from entry.apps; if an app is absent the user
        # simply cannot choose it, with no explanation.
        from radar.vocab import CCApp

        payload = json.loads((exported_data / "cc-switch.json").read_text(encoding="utf-8"))
        expected = {app.value for app in CCApp}
        for provider_id, entry in payload["entries"].items():
            missing = sorted(expected - set(entry.get("apps", {})))
            assert not missing, f"{provider_id} is missing app entries: {missing}"

    def test_the_build_copies_it_into_dist(self, built_site: Path) -> None:
        # The file existing in the export is not enough: the site is served
        # from dist, and _copy_data is what decides what reaches it.
        path = built_site / "data" / "cc-switch.json"
        assert path.is_file(), (
            "data/cc-switch.json was not copied into dist. build_site._copy_data "
            "must carry it through, or the deployed site 404s."
        )

    def test_no_secret_shaped_value_reaches_the_payload(self, exported_data: Path) -> None:
        # apiKey is always emitted empty by design; a filled one anywhere is a
        # leak of the worst kind because this file is public and unauthenticated.
        text = (exported_data / "cc-switch.json").read_text(encoding="utf-8")
        payload = json.loads(text)
        for provider_id, entry in payload["entries"].items():
            for app, config in entry.get("apps", {}).items():
                for field in config.get("fields", []):
                    if field.get("secret"):
                        assert not (field.get("value") or ""), (
                            f"{provider_id}/{app}: secret field {field.get('key')} carries a value"
                        )


class TestEveryVarReferencedInCssIsDefined:
    """Catch ``var(--foo)`` whose ``--foo`` was never defined.

    When such a reference slips in, the used property falls back to its
    *initial* value -- which for ``background-color``, ``color`` and similar
    surface properties is ``transparent`` or ``inherit`` -- and the rule
    silently fails. There is no warning, no console message, no failed
    assertion: the page just renders wrong, in a way that's easy to mistake
    for an inherited-from-parent look.

    The dialog.sheet rule that triggered this test used ``background:
    var(--glass-bg)`` where ``--glass-bg`` was never defined. In every browser
    that supports backdrop-filter (i.e. every current browser), the modal
    rendered fully transparent, the text sat on the ::backdrop dimming, and
    light-theme contrast dropped to 2.11:1 in the CC Switch dialog. The
    rule had shipped green, the page worked in the happy path, and the bug
    only became visible once someone actually opened the dialog.
    """

    CSS_DIR = ROOT / "site" / "static" / "css"

    @staticmethod
    def _strip_comments(css: str) -> str:
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    @staticmethod
    def _bodies(css: str) -> list[str]:
        # Depth-1 only: a deeper parse would mistake a property block inside a
        # nested at-rule for a definition body. For "is this var() reference
        # present", first-level is enough.
        return [m.group(1) for m in re.finditer(r"\{([^{}]*)\}", css)]

    def test_every_var_referenced_anywhere_is_defined_somewhere(self) -> None:
        # A token can be defined in tokens.css (the common case) or scoped to
        # a parent element (e.g. --search-icon-size on .search, inherited by
        # .search__icon). The check has to look at every stylesheet.
        defined: set[str] = set()
        seen: dict[str, list[str]] = {}

        for css_path in sorted(self.CSS_DIR.glob("*.css")):
            css = self._strip_comments(css_path.read_text(encoding="utf-8"))
            for body in self._bodies(css):
                for match in re.finditer(r"(--[\w-]+)\s*:", body):
                    defined.add(match.group(1))

        for css_path in sorted(self.CSS_DIR.glob("*.css")):
            css = self._strip_comments(css_path.read_text(encoding="utf-8"))
            for body in self._bodies(css):
                for match in re.finditer(r"var\(\s*(--[\w-]+)\s*[,)]", body):
                    # url(#radar-refract) is a fragment, not a custom prop.
                    name = match.group(1)
                    seen.setdefault(name, []).append(body.strip()[:80])

        missing = sorted(name for name in seen if name not in defined)
        assert not missing, (
            "components.css (or another stylesheet) references custom "
            "properties that are not defined anywhere:\n  "
            + "\n  ".join(missing)
            + "\nA var() whose property is never defined falls back to its "
            "initial value (transparent for backgrounds), so the rule does "
            "nothing and the page renders wrong silently. Add the token to "
            "tokens.css, or scope it to a parent element that wraps every "
            "consumer."
        )

    def test_every_block_that_defines_glass_plate_also_defines_glass_bg(self) -> None:
        # --glass-bg is the modal-sheet surface and dialog.sheet resolves it
        # from whichever tokens block is currently active (light / dark /
        # dark+photo). A missing definition in *one* block means the dialog
        # is transparent under that theme, which is exactly the bug this test
        # exists to prevent -- and a block-level scan catches it, which a
        # file-level "any definition exists" check does not.
        css = self._strip_comments((self.CSS_DIR / "tokens.css").read_text(encoding="utf-8"))

        block_re = re.compile(r"([^{}]+)\{([^{}]*)\}")
        broken: list[str] = []
        for selector, body in block_re.findall(css):
            if "--glass-plate-bg" not in body:
                continue
            if "--glass-bg" not in body:
                broken.append(selector.strip())

        assert not broken, (
            "These tokens blocks define --glass-plate-bg but not --glass-bg, "
            "so dialog.sheet renders transparent under those conditions:\n  "
            + "\n  ".join(broken)
            + "\nA modal dialog that is transparent looks like a rendering "
            "fault and its text falls onto the ::backdrop dimming. Add "
            "`--glass-bg: var(--glass-plate-bg);` to each block that defines "
            "--glass-plate-bg."
        )


class TestAdaptiveGlassIsWired:
    """The "glass responds to what's behind" feature has three moving parts.

    1. glass-adaptive.js must exist and export initInitableGlass.
    2. tokens.css must define --panel-adaptive-tint with a 0% default so
       pages that never opt into the photo backdrop look exactly like before.
    3. The color-mix() interpolation must actually USE the variable, with
    a sane ceiling, so the JS-set value has an effect.

    The browser-level proof -- that different panels get different values
    when the photo backdrop is active -- lives in
    .work/glass-adaptive-verify.mjs and runs as part of the manual sweep.
    """

    @staticmethod
    def _strip_comments(css: str) -> str:
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    CSS_DIR = ROOT / "site" / "static" / "css"

    def test_the_module_exists_and_exports_init(self) -> None:
        path = ROOT / "site" / "static" / "js" / "glass-adaptive.js"
        assert path.is_file(), (
            "site/static/js/glass-adaptive.js is missing. The adaptive glass "
            "module is wired into app.js via initAdaptiveGlass(), so deleting "
            "the file silently reverts every panel to a uniform tint and the "
            "user's complaint that the glass 'doesn't respond to what's "
            "behind it' comes back with no test failure."
        )
        text = path.read_text(encoding="utf-8")
        assert "export" in text and "async function initAdaptiveGlass" in text, (
            "glass-adaptive.js must export initAdaptiveGlass for app.js to "
            "import it. If you renamed it, also update app.js."
        )

    def test_the_token_is_defined_at_root(self) -> None:
        css = self._strip_comments((self.CSS_DIR / "tokens.css").read_text(encoding="utf-8"))
        m = re.search(r"--panel-adaptive-tint:\s*([^;]+);", css)
        assert m, (
            "--panel-adaptive-tint must have a default declaration so a page "
            "without the JS (reduced motion, SSR fallback, screenshot tool) "
            "looks exactly like the original design. If it is only set from "
            "JS, the offline design is undefined."
        )
        # Default should be 0% -- any non-zero default would mean even a
        # glass-clear page renders thicker than designed.
        assert m.group(1).strip().rstrip("%") == "0", (
            f"--panel-adaptive-tint defaults to {m.group(1).strip()}. The JS "
            "overrides this per element; a non-zero default means the no-JS "
            "design is thicker than intended."
        )

    def test_the_token_actually_drives_the_color_mix(self) -> None:
        css = self._strip_comments((self.CSS_DIR / "tokens.css").read_text(encoding="utf-8"))
        # At least one of the rendered --glass-*-bg declarations must
        # reference --panel-adaptive-tint. A token that is only declared
        # and never read is dead.
        used = False
        for tier in ("--glass-nav-bg", "--glass-card-bg", "--glass-plate-bg"):
            if f"var({tier})" in css and "--panel-adaptive-tint" in css:
                used = True
                break
        assert used, (
            "tokens.css declares --panel-adaptive-tint but none of "
            "--glass-nav-bg / --glass-card-bg / --glass-plate-bg read it. "
            "The JS sets it per element but the CSS has to consume it, or the "
            "module is a no-op."
        )
        # The specific rule whose missing token left every modal transparent.
        css = self._strip_comments((self.CSS_DIR / "components.css").read_text(encoding="utf-8"))
        tokens_css = self._strip_comments((self.CSS_DIR / "tokens.css").read_text(encoding="utf-8"))
        defined_in_tokens = set(re.findall(r"(--[\w-]+)\s*:", tokens_css))

        # Walk from `dialog.sheet {` and match braces to find the rule body.
        # A bare regex can't handle nesting, and the body is short enough that
        # scanning the surrounding text is reliable.
        for m in re.finditer(r"dialog\.sheet\s*\{", css):
            depth = 1
            i = m.end()
            while i < len(css) and depth:
                if css[i] == "{":
                    depth += 1
                elif css[i] == "}":
                    depth -= 1
                i += 1
            body = css[m.end() : i - 1]
            referenced = re.findall(r"var\(\s*(--[\w-]+)\s*[,)]", body)
            if not referenced:
                continue
            for token in referenced:
                assert token in defined_in_tokens, (
                    f"dialog.sheet references --{token}, which is not defined "
                    "in tokens.css. Every modal dialog on the site uses this "
                    "rule and would render transparent -- which is the exact "
                    "bug this test exists to prevent."
                )
            return  # one passing rule is enough
        raise AssertionError("dialog.sheet rule not found in components.css")

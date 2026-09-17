"""The photo backdrop must not be able to break text contrast.

Every other colour in this design is a token we control. The photographic
backdrop is the one surface that is *not*: the user picks an arbitrary image and
it goes behind the whole page. The glass is translucent, so a bright photo
brightens the panel behind light text, and a dark photo darkens the panel behind
dark text.

Measured in a real browser, the first version of the feature broke 40 text
elements: 37 in dark theme (a bright patch of the photo behind the sidebar and
the topbar, dropping .sidebar__label from 5.97:1 on the solid backdrop to
3.48:1) and 3 in light theme (a dark patch, dropping .howto__body to 4.34:1).
Neither is a colour anybody chose; both fall out of the photo.

Two mechanisms hold the line, and this file pins both:

1. A GUARD PLATE for text that has no surface of its own -- report prose,
   section headings, pagination, the footer. Each such block gets
   --photo-guard painted behind it, so the guarantee is LOCAL: it has to
   satisfy the text it sits behind, not the worst-placed text anywhere on the
   page. A page-wide scrim has to be priced for the worst case, and every pixel
   of the photo pays that price -- which is why the cards read as opaque even
   though they were translucent.

2. A BLEND FLOOR for the light theme (--photo-floor, applied with
   `background-blend-mode: lighten`). A card is a translucent surface carrying
   dark text, so a dark photo behind it drags the card's own fill down with it:
   at a 30% card over a pure black photo the fill lands at rgb(97) and
   --text-muted measures 1.17:1. Bounding the photo from BELOW fixes that
   without covering the picture up. Dark theme keeps a scrim instead, because
   its failure direction is the opposite and the mirror-image blend would
   flatten the highlights its night photo is made of.

The browser audit (see docs/delivery.md) remains the authoritative check -- it
measures rendered pixels. What this file does is run the same arithmetic offline
in milliseconds, so the realistic regression, someone editing a scrim or a glass
token, fails immediately instead of in a screenshot nobody re-reads.

On the model: composite = source-over, with the panel tint over the scrimmed
photo. It deliberately ignores backdrop-filter (blur, saturate) and the colour
blob layer. Those are not nothing -- the model reads about 3% high against
rendered pixels -- which is why the assertions demand headroom above 4.5 rather
than landing exactly on it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_token_contrast import contrast_ratio, parse_hex, tokens_in_block

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "site" / "static" / "css" / "tokens.css"

#: WCAG 2.1 AA for normal text. Every token checked here is used at normal size
#: somewhere (.sidebar__label is 11px), so the stricter bar applies throughout.
AA = 4.5

#: How optimistic the offline model is against rendered pixels, as a fraction.
#: Measured at about 3%, in the optimistic direction, so the assertions require
#: the model to clear 4.5 by this much. A token edit that leaves the model at
#: 4.55 is not a pass; it is a value the browser will render below AA.
MODEL_OPTIMISM = 0.03
REQUIRED = AA * (1 + MODEL_OPTIMISM)


def parse_rgb_function(value: str) -> tuple[tuple[int, int, int], float]:
    """Parse ``rgb(R G B / A%)`` or ``rgb(R, G, B)`` into (channels, alpha).

    The token sheet uses the modern space-separated form with a percentage
    alpha, which neither ``parse_hex`` nor a naive comma split handles.
    """
    m = re.search(r"rgb\(\s*([^)]+)\)", value)
    if not m:
        raise ValueError(f"not an rgb() colour: {value!r}")
    body = m.group(1).replace("/", " ")
    parts = [p for p in re.split(r"[,\s]+", body.strip()) if p]
    if len(parts) not in (3, 4):
        raise ValueError(f"expected 3 or 4 components: {value!r}")
    channels = tuple(round(float(p)) for p in parts[:3])
    if len(parts) == 4:
        raw = parts[3]
        alpha = float(raw.rstrip("%")) / 100 if raw.endswith("%") else float(raw)
    else:
        alpha = 1.0
    return channels, alpha  # type: ignore[return-value]


def over(fg: tuple[int, int, int], alpha: float, bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Source-over compositing with straight alpha, rounded to 8-bit."""
    return tuple(  # type: ignore[return-value]
        round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg, strict=True)
    )


def _css() -> str:
    return TOKENS.read_text(encoding="utf-8")


def _css_without_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", _css(), flags=re.DOTALL)


@pytest.fixture(scope="module")
def light() -> dict[str, str]:
    return tokens_in_block(_css(), ":root")


@pytest.fixture(scope="module")
def dark() -> dict[str, str]:
    """Dark theme tokens with the photo-mode overrides already merged in.

    Merging here rather than in each test means the tests exercise the values
    that actually render under a photo. A test that read the base dark block and
    separately remembered to apply the override would be one refactor away from
    checking a configuration that never occurs.
    """
    css = _css()
    merged = dict(tokens_in_block(css, '[data-theme="dark"]'))
    merged.update(tokens_in_block(css, '[data-theme="dark"][data-backdrop="photo"]'))
    return merged


#: The photo each theme has to survive. A photo is unbounded, so the honest
#: worst case is the extreme, not the image we happen to ship.
#:
#: light -- risk is a DARK photo: --text-muted is #47566c, so a darkened backdrop
#:          costs contrast. Pure black is the darkest possible.
#: dark  -- risk is a BRIGHT photo: --text-muted is #adbed4, so a brightened
#:          backdrop costs contrast. Pure white is the brightest possible.
WORST_PHOTO: dict[str, tuple[int, int, int]] = {
    "light": (0, 0, 0),
    "dark": (255, 255, 255),
}

#: Themes whose photo layer is bounded from BELOW by a blend floor instead of
#: from above by a scrim. Listed explicitly rather than inferred, because the
#: difference is a deliberate asymmetry: the light theme can bound from below
#: (`lighten` keeps the highlights, which is the half that still reads), and the
#: dark theme cannot (`darken` would keep the shadows of a night photo, i.e.
#: almost nothing). TestTheFixIsActuallyWiredUp pins the blend modes that make
#: this list true.
FLOOR_THEMES = ("light",)

#: Which text tokens actually sit on which tier. Traced from the stylesheets
#: and the browser scan (.work/glass-sweep.mjs), not assumed.
#:
#:   nav   --text-subtle at 11px: .sidebar__label, .navlink__count,
#:          .topbar__eyebrow
#:   card  --text and --text-muted only. The card carries no --text-subtle, and
#:          that matters: the dark card fill is rgb(44,58,82), whose luminance
#:          is above the ceiling --text-subtle needs, so a --text-subtle label
#:          inside a card could not reach AA at ANY tier opacity. Checking a
#:          pairing that does not exist would force the card to be opaque to
#:          satisfy a constraint nothing actually imposes.
#:   plate --text-subtle at 13.5px: .sitefoot__disclaimer, .plate prose
TIER_TEXT_TOKENS: dict[str, tuple[str, ...]] = {
    "--glass-nav-clear": ("--text", "--text-muted", "--text-subtle"),
    "--glass-card-clear": ("--text", "--text-muted"),
    "--glass-plate-clear": ("--text", "--text-muted", "--text-subtle"),
}

#: The CLEAR end of each tier. The rendered tier (--glass-*-bg) is a
#: color-mix() of this and --surface, driven by --glass-tint; at the default
#: tint of 0% the mix is the clear value exactly, which is what this model
#: assumes. TestTintDefaultsToClear pins that assumption.
GLASS_TIERS = ("--glass-nav-clear", "--glass-card-clear", "--glass-plate-clear")


def backdrop_under(theme: str, tokens: dict[str, str]) -> tuple[int, int, int]:
    """The photo as it actually reaches the page.

    Two steps, in the order the browser applies them: the blend floor bounds
    the photo from below, then the scrim softens the top end.
    """
    worst = WORST_PHOTO[theme]
    if theme in FLOOR_THEMES:
        floor = parse_hex(tokens["--photo-floor"])
        # `background-blend-mode: lighten` keeps whichever pixel is brighter,
        # so the DARKEST a backdrop pixel can be is the floor's own colour --
        # which is the case this model has to check.
        worst = tuple(max(f, w) for f, w in zip(floor, worst, strict=True))
    scrim, alpha = parse_rgb_function(tokens["--photo-scrim"])
    return over(scrim, alpha, worst)


def guard_fill(theme: str, tokens: dict[str, str]) -> tuple[int, int, int]:
    """A guard plate's rendered fill: --photo-guard over the backdrop."""
    guard, alpha = parse_rgb_function(tokens["--photo-guard"])
    return over(guard, alpha, backdrop_under(theme, tokens))


def glass_fill(theme: str, tokens: dict[str, str], tier: str) -> tuple[int, int, int]:
    """A glass panel's rendered fill: its own tint over the backdrop."""
    tint, alpha = parse_rgb_function(tokens[tier])
    return over(tint, alpha, backdrop_under(theme, tokens))


class TestBareBackgroundTextSurvivesAnyPhoto:
    """The guard plate's whole job.

    These are the elements with no panel behind them: report prose, section
    headings, pagination, the footer. Nothing else can protect them, so the
    guard is the only lever -- and because the guard is local, it can be
    opaque enough to work without dimming the whole photo.
    """

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_text_muted_on_a_guard_plate_meets_aa(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        tokens = request.getfixturevalue(theme)
        bg = guard_fill(theme, tokens)
        ratio = contrast_ratio(parse_hex(tokens["--text-muted"]), bg)
        assert ratio >= REQUIRED, (
            f"{theme}: --text-muted on a guard plate is {ratio:.2f}:1 "
            f"(plate fill rgb{bg} from --photo-guard {tokens['--photo-guard']} "
            f"over a photo of {WORST_PHOTO[theme]}). Needs {REQUIRED:.2f} to "
            f"clear AA once the model's {MODEL_OPTIMISM:.0%} optimism is "
            f"allowed for. .howto__body, .directory__count and the report prose "
            f"all sit on a guard plate with no panel under it."
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_text_subtle_on_a_guard_plate_meets_aa(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        # --text-subtle is the lightest grey in the palette, so it is the
        # binding constraint, not --text-muted. It is used at 13.5px on the
        # guard plates (.helper, .directory__count, the footer disclaimer).
        tokens = request.getfixturevalue(theme)
        bg = guard_fill(theme, tokens)
        ratio = contrast_ratio(parse_hex(tokens["--text-subtle"]), bg)
        assert ratio >= REQUIRED, (
            f"{theme}: --text-subtle on a guard plate is {ratio:.2f}:1 "
            f"(plate fill rgb{bg}). It is the lightest grey the design uses, "
            f"so it sets how opaque the guard has to be."
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_a_thin_scrim_is_backed_by_something_else(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        # A scrim below 50% cannot bound an arbitrary photo on its own, and a
        # fully opaque one means the photo never renders at all -- i.e. the
        # feature is silently dead. So either the scrim does the job itself, or
        # something else must, and the test insists that something exists.
        tokens = request.getfixturevalue(theme)
        _, alpha = parse_rgb_function(tokens["--photo-scrim"])
        assert alpha < 1.0, (
            f"{theme}: --photo-scrim is opaque, so the photo is invisible and "
            f"the feature does nothing."
        )
        if alpha >= 0.5:
            return
        assert theme in FLOOR_THEMES, (
            f"{theme}: --photo-scrim is {alpha:.2f}, which does not bound an "
            f"arbitrary photo, and this theme is not listed as having a blend "
            f"floor either. Either raise the scrim or add a floor -- and if the "
            f"floor is added, add the theme to FLOOR_THEMES and pin the blend "
            f"mode that makes it real."
        )
        assert "--photo-floor" in tokens, (
            f"{theme}: FLOOR_THEMES claims a blend floor but --photo-floor is "
            f"not defined in this theme's tokens."
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_the_guard_is_actually_a_guard(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        # Below 0.5 the plate stops protecting the text; at 1.0 the photo is
        # gone from behind every text block, which is the state this whole
        # change moved away from.
        tokens = request.getfixturevalue(theme)
        _, alpha = parse_rgb_function(tokens["--photo-guard"])
        assert 0.5 <= alpha < 1.0, (
            f"{theme}: --photo-guard alpha is {alpha:.2f}. Below 0.5 it cannot "
            f"protect text from an arbitrary photo; at 1.0 every text block "
            f"becomes an opaque card again."
        )


class TestGlassTextSurvivesAnyPhoto:
    """Panels protect their own contents; the guard must not cover for them."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_every_text_token_on_every_glass_tier_meets_aa(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        tokens = request.getfixturevalue(theme)
        failures: list[str] = []
        for tier, fg_names in TIER_TEXT_TOKENS.items():
            fill = glass_fill(theme, tokens, tier)
            for fg_name in fg_names:
                ratio = contrast_ratio(parse_hex(tokens[fg_name]), fill)
                if ratio < REQUIRED:
                    failures.append(
                        f"{fg_name} on {tier}: {ratio:.2f}:1 (fill rgb{fill}, tint {tokens[tier]})"
                    )
        assert not failures, (
            f"{theme}: text on glass drops below AA when the worst-case photo "
            f"({WORST_PHOTO[theme]}) is behind it:\n  "
            + "\n  ".join(failures)
            + "\nA photo makes the backdrop unpredictable, so the material has "
            "to do more of the work, not less. Fix it by thickening the tier in "
            'the [data-theme="dark"][data-backdrop="photo"] block -- the scrim '
            "cannot reach inside a panel."
        )


class TestTheFixIsActuallyWiredUp:
    """Guards against the fix being deleted while the tests stay green.

    Every assertion above reads tokens. If someone removes the photo-mode block
    or the blend mode, the fixtures would silently fall back to values that no
    longer render -- which is the desired failure, but only if the wiring is
    really what the fixtures read. These tests make that explicit.
    """

    def test_the_light_photo_layer_is_blended_against_the_floor(self) -> None:
        css = _css_without_comments()
        # The floor only bounds the photo if the layer is actually blended
        # against it. `lighten` is what makes the darkest possible backdrop
        # equal the floor colour; without it --photo-floor is an unused token
        # and the light theme falls back to a 12% scrim over an arbitrary
        # photo, which is exactly the 1.17:1 failure the floor exists to stop.
        m = re.search(r'\[data-backdrop="photo"\]\s*\.env-photo\s*\{([^}]*)\}', css)
        assert m, (
            'The [data-backdrop="photo"] .env-photo rule is gone, so the floor '
            "is never applied and the light theme has no lower bound."
        )
        assert "lighten" in m.group(1), (
            f"the photo layer is not blended against the floor (found "
            f"{m.group(1).strip()!r}). Without `lighten` the floor does nothing."
        )

    def test_the_dark_photo_layer_does_not_take_the_floor(self) -> None:
        css = _css_without_comments()
        m = re.search(
            r'\[data-theme="dark"\]\[data-backdrop="photo"\]\s*\.env-photo\s*\{([^}]*)\}', css
        )
        assert m, (
            "The dark theme's photo-layer override is gone. It has to state "
            "`normal, normal` explicitly, because the light rule above it also "
            "matches this element."
        )
        assert "normal, normal" in m.group(1), (
            f"the dark photo layer blends as {m.group(1).strip()!r}. `darken` "
            f"would flatten the highlights of the night photo and keep its "
            f"shadows, i.e. the picture would disappear."
        )

    def test_the_dark_photo_override_block_exists_and_is_thicker(
        self, light: dict[str, str], dark: dict[str, str]
    ) -> None:
        css = _css()
        assert '[data-theme="dark"][data-backdrop="photo"]' in css, (
            "The dark photo-mode glass override is gone. Without it the dark "
            "theme renders text below AA under a photo."
        )
        base = tokens_in_block(css, '[data-theme="dark"]')
        # tokens_in_block returns the FIRST match, which is the base dark block
        # (the override selector is longer, so it cannot match first).
        for tier in GLASS_TIERS:
            _, base_alpha = parse_rgb_function(base[tier])
            _, photo_alpha = parse_rgb_function(dark[tier])
            assert photo_alpha > base_alpha, (
                f"{tier} is {photo_alpha:.2f} under a photo but {base_alpha:.2f} "
                f"without one. The override must be *thicker* -- a photo makes "
                f"the backdrop unpredictable, so the material has to do more of "
                f"the work, not less."
            )

    def test_reduced_transparency_still_outranks_the_photo_override(self) -> None:
        # The trap this exists for: the override is (0,2,0). The
        # reduced-transparency token block was (0,1,0) and would have LOST to
        # it, so picking both "reduced transparency" and "photo backdrop" would
        # have re-introduced translucent panels -- the one combination where
        # that is exactly the wrong answer.
        css = _css()
        assert ':root[data-transparency="reduced"]' in css, (
            "The reduced-transparency token block lost its :root prefix, so it "
            'is back to (0,1,0) and loses to [data-theme="dark"]'
            '[data-backdrop="photo"] at (0,2,0).'
        )
        assert css.index('[data-theme="dark"][data-backdrop="photo"]') < css.index(
            ':root[data-transparency="reduced"]'
        ), (
            "The reduced-transparency block must come AFTER the photo override, "
            "so that equal specificity is decided in its favour by source order."
        )

    def test_the_photo_is_opt_in_and_never_downloaded_by_default(self) -> None:
        # The url() must live inside a selector guarded by [data-backdrop=photo],
        # or every visitor pays for a 150KB image they never asked to see.
        css = _css_without_comments()
        for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
            selector, body = m.group(1), m.group(2)
            if "url(" not in body or ".env-photo" not in selector:
                continue
            assert '[data-backdrop="photo"]' in selector, (
                f"A backdrop image is loaded by the unguarded selector "
                f"{selector.strip()!r}. It must be behind "
                f'[data-backdrop="photo"] so the default page requests nothing.'
            )


class TestTintDefaultsToClear:
    """The slider must start at the clear end.

    --glass-*-bg is a color-mix() of --surface and the clear value, so at
    tint 0% the rendered material equals the clear value -- which is exactly
    what every assertion in this file models. If the default tint ever moved,
    the real material would be thicker than the model and these tests would
    still be green while understating the fill. Pin the default so the model
    and the stylesheet cannot drift apart.
    """

    def test_the_default_tint_is_zero(self) -> None:
        css = _css_without_comments()
        m = re.search(r"--glass-tint:\s*([^;]+);", css)
        assert m, "--glass-tint is not defined; the tiers cannot be mixed"
        value = m.group(1).strip().rstrip("%")
        assert float(value) == 0, (
            f"--glass-tint defaults to {value}%. Every ratio in this file is "
            "computed from the CLEAR tier values, so a non-zero default means "
            "the real panels are thicker than the model and the measured "
            "headroom here is overstated."
        )

    def test_the_clear_end_is_defined_for_every_tier_and_theme(self) -> None:
        css = _css_without_comments()
        light = tokens_in_block(css, ":root")
        dark = tokens_in_block(css, '[data-theme="dark"]')
        for name, tokens in (("light", light), ("dark", dark)):
            for tier in GLASS_TIERS:
                assert tier in tokens, f"{name}: {tier} missing"
                # Must be a real rgb() with an alpha, or the mix has nothing
                # to interpolate toward.
                _channels, alpha = parse_rgb_function(tokens[tier])
                assert 0 < alpha <= 1, f"{name}: {tier} has alpha {alpha}"


class TestTheModelIsSound:
    """Guard the guard: if the colour maths is wrong, everything above is noise."""

    def test_rgb_function_parsing(self) -> None:
        assert parse_rgb_function("rgb(239 244 251 / 88%)") == ((239, 244, 251), 0.88)
        assert parse_rgb_function("rgb(8 14 26 / 82%)") == ((8, 14, 26), 0.82)
        assert parse_rgb_function("rgb(255, 255, 255)") == ((255, 255, 255), 1.0)

    def test_compositing_endpoints(self) -> None:
        # Fully transparent must return the backdrop untouched; fully opaque
        # must return the source untouched. If either is off, every modelled
        # fill is wrong in a way that would still look plausible.
        assert over((10, 20, 30), 0.0, (200, 210, 220)) == (200, 210, 220)
        assert over((10, 20, 30), 1.0, (200, 210, 220)) == (10, 20, 30)

    def test_the_light_floor_bounds_the_backdrop(self) -> None:
        # The whole guarantee of the light theme in one assertion: because the
        # photo layer is composited with `lighten` against the floor, no photo
        # pixel can come out darker than the floor. If the scrim ever made the
        # backdrop DARKER than the floor, the floor would be doing nothing.
        #
        # Note what is deliberately NOT asserted: that --text-muted clears AA
        # on this backdrop. It does not -- it measures about 4.0:1 -- and it
        # does not have to, because no text sits directly on the backdrop any
        # more. The text that used to is on a guard plate now, which
        # TestBareBackgroundTextSurvivesAnyPhoto checks. Demanding AA here
        # would force the scrim back up to 88% and undo the entire change.
        light = tokens_in_block(_css(), ":root")
        floor = parse_hex(light["--photo-floor"])
        bg = backdrop_under("light", light)
        assert all(b >= f for b, f in zip(bg, floor, strict=True)), (
            f"backdrop rgb{bg} is darker than the floor rgb{floor}; the scrim "
            f"is subtracting instead of adding, so the floor is not bounding "
            f"anything."
        )
        # And the floor has to do real work rather than sit just under the raw
        # photo. Against a black photo the backdrop IS the floor plus the
        # scrim, so it has to come out clearly bright -- the dark text on the
        # glass above it depends on that.
        assert all(b >= 100 for b in bg), (
            f"the light backdrop renders rgb{bg} under a black photo, which is "
            f"too dark for the dark text sitting on glass above it. Raise "
            f"--photo-floor."
        )

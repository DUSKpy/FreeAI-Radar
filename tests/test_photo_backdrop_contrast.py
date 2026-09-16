"""The photo backdrop must not be able to break text contrast.

Every other colour in this design is a token we control. The photographic
backdrop is the one surface that is *not*: the user picks an arbitrary image and
it goes behind the whole page. That is a new class of risk, because the glass is
translucent -- a bright photo brightens the panel behind light text, and a dark
photo darkens the panel behind dark text.

Measured in a real browser, the first version of the feature broke 40 text
elements: 37 in dark theme (a bright patch of the photo behind the sidebar and
the topbar, dropping .sidebar__label from 5.97:1 on the solid backdrop to
3.48:1) and 3 in light theme (a dark patch, dropping .howto__body to 4.34:1).
Neither is a colour anybody chose; both fall out of the photo.

The fix has two parts, and this file pins both:

1. The scrim is sized against the WORST photo, not the one we ship. Text that
   sits straight on the page background -- .howto__body and .directory__count,
   both --text-muted -- has no panel behind it, so the scrim is the only thing
   between it and whatever image the user picks. That makes its opacity
   computable: it must hold the backdrop's luminance inside a band for a
   pure-black photo (light theme) or a pure-white one (dark theme).

2. Dark theme additionally thickens all three glass tiers under a photo, which
   is what iOS does over busy content. Light theme does not need this: its scrim
   is 88% of a near-white, so a dark photo barely moves the backdrop, and moving
   it darker only *helps* dark text.

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
#: Measured: 5.14 modelled vs 5.00 rendered for light --text-muted on the bare
#: backdrop, and 5.26 vs 5.16 for dark --text-subtle on the nav tier. Both are
#: about 3%, and both in the optimistic direction, so the assertions require the
#: model to clear 4.5 by this much. A token edit that leaves the model at 4.55
#: is not a pass; it is a value the browser will render below AA.
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

#: Text tokens that are actually painted on a glass panel. Sourced from the
#: ancestor trace in .work/panel-trace.mjs and the browser audit, not guessed:
#: .sidebar__label and .topbar__eyebrow (--text-subtle) sit on the nav tier,
#: .sitefoot__disclaimer (--text-subtle) on the panel tier, and card titles and
#: descriptions (--text, --text-muted) on the card tier.
GLASS_TEXT_TOKENS = ("--text", "--text-muted", "--text-subtle")

GLASS_TIERS = ("--glass-nav-bg", "--glass-card-bg", "--glass-plate-bg")


def backdrop_under(theme: str, tokens: dict[str, str]) -> tuple[int, int, int]:
    """The page background with the photo on: the scrim over the worst photo."""
    scrim, alpha = parse_rgb_function(tokens["--photo-scrim"])
    return over(scrim, alpha, WORST_PHOTO[theme])


def glass_fill(theme: str, tokens: dict[str, str], tier: str) -> tuple[int, int, int]:
    """A glass panel's rendered fill: its own tint over the backdrop."""
    tint, alpha = parse_rgb_function(tokens[tier])
    return over(tint, alpha, backdrop_under(theme, tokens))


class TestBareBackgroundTextSurvivesAnyPhoto:
    """The scrim's whole job. Nothing else can protect these elements."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_text_muted_on_the_page_background_meets_aa(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        tokens = request.getfixturevalue(theme)
        bg = backdrop_under(theme, tokens)
        ratio = contrast_ratio(parse_hex(tokens["--text-muted"]), bg)
        assert ratio >= REQUIRED, (
            f"{theme}: --text-muted on the photo backdrop is {ratio:.2f}:1 "
            f"(backdrop rgb{bg} from --photo-scrim {tokens['--photo-scrim']} over "
            f"a photo of {WORST_PHOTO[theme]}). Needs {REQUIRED:.2f} to clear AA "
            f"once the model's {MODEL_OPTIMISM:.0%} optimism is allowed for. "
            f".howto__body and .directory__count sit directly on this surface "
            f"with no panel to thicken, so the scrim is the only lever."
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_the_scrim_is_actually_a_scrim(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        # A scrim below 50% does not bound anything, and a fully opaque one
        # would mean the photo never renders at all -- i.e. the feature is
        # silently dead. Both are real failure modes worth failing loudly.
        tokens = request.getfixturevalue(theme)
        _, alpha = parse_rgb_function(tokens["--photo-scrim"])
        assert 0.5 <= alpha < 1.0, (
            f"{theme}: --photo-scrim alpha is {alpha:.2f}. Below 0.5 it cannot "
            f"bound an arbitrary photo; at 1.0 the photo is invisible and the "
            f"feature does nothing."
        )


class TestGlassTextSurvivesAnyPhoto:
    """Panels protect themselves; the scrim must not have to cover for them."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_every_text_token_on_every_glass_tier_meets_aa(
        self, theme: str, request: pytest.FixtureRequest
    ) -> None:
        tokens = request.getfixturevalue(theme)
        failures: list[str] = []
        for tier in GLASS_TIERS:
            fill = glass_fill(theme, tokens, tier)
            for fg_name in GLASS_TEXT_TOKENS:
                ratio = contrast_ratio(parse_hex(tokens[fg_name]), fill)
                if ratio < REQUIRED:
                    failures.append(
                        f"{fg_name} on {tier}: {ratio:.2f}:1 (fill rgb{fill}, tint {tokens[tier]})"
                    )
        assert not failures, (
            f"{theme}: text on glass drops below AA when the worst-case photo "
            f"({WORST_PHOTO[theme]}) is behind it:\n  "
            + "\n  ".join(failures)
            + "\nThis is the dark-theme failure mode the photo backdrop "
            "introduced: a bright photo behind a translucent panel raises the "
            "panel's fill until light text on it is no longer readable. Fix it "
            "by thickening the tier in the "
            '[data-theme="dark"][data-backdrop="photo"] block, not by making '
            "the scrim opaque -- the scrim cannot reach inside a panel."
        )


class TestTheFixIsActuallyWiredUp:
    """Guards against the fix being deleted while the tests stay green.

    Every assertion above reads tokens. If someone removes the photo-mode block,
    the dark fixture would silently fall back to the base glass values and
    TestGlassTextSurvivesAnyPhoto would start failing -- which is the desired
    behaviour, but only if the fixture is really reading that block. These tests
    make the wiring explicit rather than incidental.
    """

    def test_the_dark_photo_override_block_exists_and_is_thicker(
        self, light: dict[str, str], dark: dict[str, str]
    ) -> None:
        css = _css()
        assert '[data-theme="dark"][data-backdrop="photo"]' in css, (
            "The dark photo-mode glass override is gone. Without it the dark "
            "theme renders 37 text elements below AA under a photo."
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
        css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.DOTALL)
        for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
            selector, body = m.group(1), m.group(2)
            if "url(" not in body or ".env-photo" not in selector:
                continue
            assert '[data-backdrop="photo"]' in selector, (
                f"A backdrop image is loaded by the unguarded selector "
                f"{selector.strip()!r}. It must be behind "
                f'[data-backdrop="photo"] so the default page requests nothing.'
            )


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

    def test_a_black_photo_through_the_light_scrim_matches_the_measurement(self) -> None:
        # Reference value taken from the browser sweep against a synthetic black
        # photo (.work/glass-sweep.mjs RADAR_PHOTO=black), which rendered the
        # bare backdrop at rgb(202,208,216) and 5.00:1 for --text-muted. The
        # model says 5.14: that gap is MODEL_OPTIMISM, and pinning it here means
        # a change to the compositing maths cannot quietly widen it.
        css = _css()
        light = tokens_in_block(css, ":root")
        bg = backdrop_under("light", light)
        assert bg == (210, 215, 221), f"model drifted: backdrop is now rgb{bg}"
        ratio = contrast_ratio(parse_hex(light["--text-muted"]), bg)
        measured = 5.00
        assert ratio > measured, (
            "The model must stay optimistic relative to rendered pixels; if it "
            "reads lower than the browser it is modelling something else."
        )
        assert ratio / measured - 1 <= MODEL_OPTIMISM + 0.01, (
            f"Model is now {ratio / measured - 1:.1%} optimistic, above the "
            f"{MODEL_OPTIMISM:.0%} the assertions allow for. Either tighten the "
            f"model or raise MODEL_OPTIMISM so REQUIRED stays honest."
        )

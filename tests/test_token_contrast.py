"""Design-token contrast: every text colour must be readable on its surface.

The browser-based pixel audit (930 elements measured across 6 pages and 2
themes) proved the *current* rendering passes WCAG AA. That audit needs a real
browser, so it cannot live in this offline suite -- it stays a manual/CI-browser
check.

What CAN be tested here is the far more likely regression: someone edits a
colour token. Tokens are the single source of every text and surface colour, so
checking each text token against each surface it may sit on catches the mistake
at the source, in milliseconds, with no browser.

Thresholds are WCAG 2.1 AA: 4.5:1 for body text, 3:1 for large text (>=24px, or
>=18.66px when bold). Every text token here is used at normal size somewhere, so
4.5:1 is the bar. This is deliberately stricter than the bare minimum.

The numbers are not guesses -- the rendered result was measured from real pixels
(see docs/delivery.md), and these assertions encode the same conclusion so it
cannot silently drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "site" / "static" / "css" / "tokens.css"


def _srgb(channel: float) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def parse_hex(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        raise ValueError(f"not a 6-digit hex colour: {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def tokens_in_block(css: str, selector: str) -> dict[str, str]:
    """Extract custom properties from the rule whose selector matches.

    Deliberately simple: the token file defines light values at the top level
    and dark values inside a ``[data-theme="dark"]`` block, and those are the
    only two blocks these tests care about.
    """
    # Find `selector { ... }` and take the first brace-balanced body.
    idx = css.find(selector)
    if idx == -1:
        raise AssertionError(f"selector {selector!r} not found in tokens.css")
    start = css.index("{", idx)
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                body = css[start + 1 : i]
                break
    else:
        raise AssertionError(f"unbalanced braces for {selector!r}")

    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    out: dict[str, str] = {}
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body):
        out[m.group(1)] = m.group(2).strip()
    return out


@pytest.fixture(scope="module")
def light_tokens() -> dict[str, str]:
    css = TOKENS.read_text(encoding="utf-8")
    return tokens_in_block(css, ":root")


@pytest.fixture(scope="module")
def dark_tokens() -> dict[str, str]:
    css = TOKENS.read_text(encoding="utf-8")
    return tokens_in_block(css, '[data-theme="dark"]')


#: text token -> the surface tokens it is actually used against.
#:
#: Sourced by grepping the CSS for each pairing, not guessed. This distinction
#: matters: an invented pairing is not harmlessly neutral. Asserting
#: ``--text`` on ``--surface-sunken`` (which nothing does -- ``--text`` is only
#: ever painted on ``--surface`` and ``--surface-soft``) passes at 14.49:1 and
#: therefore covers nothing, while the pairings that DO occur went unchecked.
#: A green assertion against a combination that does not exist is worse than no
#: assertion, because it looks like coverage.
#:
#: Pairings come in two shapes, and the distinction is what
#: TestThePairingsDescribeRealUsage enforces:
#:
#: DECLARED -- the text and its surface appear as ``color:`` and
#:   ``background:`` in the SAME rule, so the pairing is self-evident in the
#:   source and greppable without following the cascade:
#:     --text-subtle / --surface-sunken   components.css:129 .navlink__count
#:                                        (11px/650 -- small text, so 4.5:1 applies)
#:     --text-muted  / --surface-sunken   components.css:737
#:     --accent-fg   / --accent-bg        components.css:668 .chip--accent,
#:                                        components.css:688 .proto--on
#:     --on-accent   / --accent           the CTA button
#:
#: INHERITED -- the text token is set on an element that sits on a surface
#:   declared by an ancestor (or by the page itself), so no single rule
#:   contains both declarations. These are equally real -- the pixels are the
#:   same -- but a same-rule grep cannot see them, and pretending otherwise
#:   would mean either dropping real coverage or writing a fake grep:
#:     --text          / --surface, --surface-soft
#:     --text-muted    / --surface, --surface-soft
#:     --text-subtle   / --surface, --surface-soft
#:       e.g. .sidebar__label (components.css:93), .topbar__eyebrow (:461)
#:       and .sitefoot__disclaimer (:339) all set --text-subtle and inherit an
#:       unset background, i.e. they render on the page surface.
PAIRINGS: dict[str, tuple[str, ...]] = {
    "--text": ("--surface", "--surface-soft"),
    "--text-muted": ("--surface", "--surface-soft", "--surface-sunken"),
    "--text-subtle": ("--surface", "--surface-soft", "--surface-sunken"),
    "--on-accent": ("--accent",),
    "--accent-fg": ("--accent-bg",),
}

#: The subset of PAIRINGS whose two tokens appear in one and the same rule.
#: Checked by grep in TestThePairingsDescribeRealUsage; the rest are inherited
#: and are covered by that class's second test instead.
DECLARED_PAIRINGS: frozenset[tuple[str, str]] = frozenset(
    {
        ("--text-subtle", "--surface-sunken"),
        ("--text-muted", "--surface-sunken"),
        ("--accent-fg", "--accent-bg"),
        ("--on-accent", "--accent"),
    }
)


class TestDesignTokensMeetWcagAa:
    def _check(self, tokens: dict[str, str], theme: str) -> None:
        for fg_name, bg_names in PAIRINGS.items():
            if fg_name not in tokens:
                continue
            fg = parse_hex(tokens[fg_name])
            for bg_name in bg_names:
                if bg_name not in tokens:
                    continue
                bg = parse_hex(tokens[bg_name])
                ratio = contrast_ratio(fg, bg)
                assert ratio >= 4.5, (
                    f"{theme}: {fg_name} on {bg_name} is {ratio:.2f}:1, below the "
                    f"WCAG AA minimum of 4.5:1. {fg_name}={tokens[fg_name]}, "
                    f"{bg_name}={tokens[bg_name]}"
                )

    def test_light_theme_text_is_readable_on_every_surface(
        self, light_tokens: dict[str, str]
    ) -> None:
        self._check(light_tokens, "light")

    def test_dark_theme_text_is_readable_on_every_surface(
        self, dark_tokens: dict[str, str]
    ) -> None:
        self._check(dark_tokens, "dark")

    def test_the_primary_button_is_readable_in_both_themes(
        self, light_tokens: dict[str, str], dark_tokens: dict[str, str]
    ) -> None:
        # The single most important control on the site. Dark theme inverts it
        # (light fill, dark label), so this pairing must be checked per theme
        # rather than assumed from the light values.
        for name, tokens in (("light", light_tokens), ("dark", dark_tokens)):
            ratio = contrast_ratio(parse_hex(tokens["--on-accent"]), parse_hex(tokens["--accent"]))
            assert ratio >= 4.5, f"{name}: CTA label on --accent is {ratio:.2f}:1"

    def test_the_contrast_helper_agrees_with_known_values(self) -> None:
        # Guard the guard: if the luminance maths is wrong, every other
        # assertion above is meaningless. These are hand-checked reference
        # values.
        assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0, abs=0.001)
        # White on the accent blue, verified from rendered pixels.
        assert contrast_ratio((255, 255, 255), (10, 102, 232)) == pytest.approx(5.15, abs=0.02)

    def test_the_pairings_actually_exist(self, light_tokens: dict[str, str]) -> None:
        # A typo in a token name would make _check() silently skip the pairing,
        # turning this whole file into a no-op that always passes.
        for fg_name, bg_names in PAIRINGS.items():
            assert fg_name in light_tokens, f"text token {fg_name} missing from :root"
            for bg_name in bg_names:
                assert bg_name in light_tokens, f"surface token {bg_name} missing from :root"

    def test_the_surfaces_are_distinguishable_from_each_other(
        self, light_tokens: dict[str, str]
    ) -> None:
        # --surface and --surface-soft must not be the same colour, or the
        # glass layering collapses into a single flat plate.
        assert light_tokens["--surface"] != light_tokens["--surface-soft"]
        assert light_tokens["--surface-soft"] != light_tokens["--surface-sunken"]


class TestThePairingsDescribeRealUsage:
    """Guards against the exact mistake this file already made once.

    ``PAIRINGS`` first asserted ``--text`` on ``--surface-sunken``. Nothing in
    the CSS paints ``--text`` on a sunken surface -- that combination was
    imagined. It passed at 14.49:1, so the suite stayed green and the invented
    row looked like coverage while the real pairings (``--text-subtle`` and
    ``--text-muted`` on the same surface) were never checked at all.

    An assertion that cannot fail is not evidence. These tests require each
    asserted pairing to be corroborated by the stylesheets, so a future
    invented row is caught immediately instead of quietly padding the suite.

    Two shapes are corroborated differently, which is why
    ``DECLARED_PAIRINGS`` exists rather than a single blanket rule:

    * DECLARED pairings sit in one rule as ``color:`` + ``background:``, so
      they are greppable directly.
    * INHERITED pairings cannot be greppable that way -- the surface is set by
      an ancestor or by the page, and no single rule names both. The honest
      check for those is that the text token really is used as a ``color:``
      somewhere AND the surface token really is used as a ``background:``
      somewhere, which is the strongest claim the source supports.
    """

    CSS_DIR = ROOT / "site" / "static" / "css"
    TOKEN_FILE = CSS_DIR / "tokens.css"

    @staticmethod
    def _strip_comments(css: str) -> str:
        # Comments quote declarations in prose -- this file's own docstrings do
        # it too -- and matching prose instead of code is exactly how a test
        # stops testing.
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def _sheets(self) -> list[str]:
        """Every stylesheet except tokens.css, comments stripped.

        tokens.css is excluded on purpose: it *defines* the values, and a
        definition is not a use. Counting it would let ``--surface-sunken``
        appear "used" purely because it is declared, which is the same class of
        vacuous pass this class exists to prevent.
        """
        return [
            self._strip_comments(p.read_text(encoding="utf-8"))
            for p in sorted(self.CSS_DIR.glob("*.css"))
            if p != self.TOKEN_FILE
        ]

    @staticmethod
    def _rule_bodies(css: str) -> list[str]:
        # Depth-1 bodies only. The token sheet's nesting is shallow and the
        # component sheets need no deeper handling for a colour pairing.
        return [m.group(1) for m in re.finditer(r"\{([^{}]*)\}", css)]

    def test_every_declared_pairing_appears_in_one_rule(self) -> None:
        bodies = [b for css in self._sheets() for b in self._rule_bodies(css)]
        missing: list[str] = []

        for fg_name, bg_name in sorted(DECLARED_PAIRINGS):
            found = any(
                re.search(rf"color:\s*var\({re.escape(fg_name)}\)", body)
                and re.search(rf"background(?:-color)?:\s*var\({re.escape(bg_name)}\)", body)
                for body in bodies
            )
            if not found:
                missing.append(f"{fg_name} on {bg_name}")

        assert not missing, (
            "Declared in DECLARED_PAIRINGS but no single rule paints the text "
            "token on that surface:\n  "
            + "\n  ".join(missing)
            + "\nEither the CSS changed (update the constant) or the pairing "
            "was imagined (remove it). An assertion against a combination that "
            "does not occur always passes."
        )

    def test_every_inherited_pairing_uses_both_tokens_somewhere(self) -> None:
        # For pairings that span the cascade, the strongest supportable claim
        # is that both tokens are genuinely in play -- the text token as a
        # colour, the surface token as a background.
        combined = "\n".join(self._sheets())
        problems: list[str] = []

        for fg_name, bg_names in PAIRINGS.items():
            for bg_name in bg_names:
                if (fg_name, bg_name) in DECLARED_PAIRINGS:
                    continue
                if not re.search(rf"color:\s*var\({re.escape(fg_name)}\)", combined):
                    problems.append(f"{fg_name} is never used as a color")
                if not re.search(
                    rf"background(?:-color)?:\s*var\({re.escape(bg_name)}\)", combined
                ):
                    problems.append(f"{bg_name} is never used as a background")

        assert not problems, (
            "Pairings asserted in PAIRINGS reference tokens that are not in "
            "use:\n  " + "\n  ".join(sorted(set(problems)))
        )

    def test_declared_pairings_are_a_subset_of_all_pairings(self) -> None:
        # A typo here would silently move a pairing into the weaker check, so
        # the stronger grep would stop running for it without anyone noticing.
        for fg_name, bg_name in DECLARED_PAIRINGS:
            assert fg_name in PAIRINGS, f"{fg_name} in DECLARED_PAIRINGS but not PAIRINGS"
            assert bg_name in PAIRINGS[fg_name], (
                f"{fg_name}/{bg_name} declared together in DECLARED_PAIRINGS but "
                f"PAIRINGS does not list {bg_name} under {fg_name}"
            )

    def test_the_text_token_is_not_asserted_on_a_surface_it_never_touches(
        self,
    ) -> None:
        # Encode the specific regression: --text belongs on --surface and
        # --surface-soft only. If someone adds --surface-sunken back to that
        # tuple, this fails before the invented row can pad the suite.
        assert "--surface-sunken" not in PAIRINGS["--text"], (
            "--text is not painted on --surface-sunken anywhere in the CSS; "
            "asserting it there is invented coverage, not real coverage."
        )
        # And the pairings that ARE real must stay covered.
        assert "--surface-sunken" in PAIRINGS["--text-subtle"]
        assert "--surface-sunken" in PAIRINGS["--text-muted"]

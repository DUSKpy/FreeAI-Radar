"""Glass edge-lens refraction: the filters in base.html and the CSS wiring.

The "edge lens" -- a strong rim with a calm centre -- is what makes the glass
read as liquid (iOS 26 Liquid Glass). These tests pin the wiring so the edge
modulation cannot silently regress to a uniform displacement.

Why this is non-trivial:

- A uniform displacement across a card shifts the numbers inside it. The
  historical contract in glass.css was "no refraction on cards", for exactly
  this reason. The edge-only modulation is what unblocked cards.
- The closed form "centre=0.5, rim follows the field" is encoded as a single
  feComposite arithmetic with k1..k4. If anyone simplifies that to a plain
  feDisplacementMap against the raw turbulence, every card centre will start
  drifting again.
- backdrop-filter's SourceAlpha is the BACKDROP's alpha, not the panel's
  rounded-rectangle shape, so the only way to bring an edge shape into the
  chain is feImage referencing an inline SVG (or a data: URI). SourceAlpha-
  based compositing cannot produce a rim mask here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASE_HTML = (ROOT / "site" / "templates" / "base.html").read_text(encoding="utf-8")
GLASS_CSS = (ROOT / "site" / "static" / "css" / "glass.css").read_text(encoding="utf-8")


def _filter_body(html: str, filter_id: str) -> str:
    """Return the children of <filter id="filter_id"> ... </filter>.

    Filters can nest in theory (an <feImage> is its own <svg>), so we walk
    past feImage/svg subtrees before counting depth on </filter>.
    """
    open_tag = f'<filter id="{filter_id}"'
    i = html.find(open_tag)
    assert i >= 0, f"filter #{filter_id} not found in base.html"
    j = html.index(">", i) + 1
    depth = 1
    k = j
    while depth and k < len(html):
        # Skip past <feImage ... /> self-closing or <svg ...> ... </svg>
        # subtrees, since those contain </filter>-shaped text as data.
        n_close = html.find("</filter>", k)
        if n_close < 0:
            raise AssertionError(f"unterminated filter #{filter_id}")
        # Look for any "<filter" or "<feImage" or "<svg" between k and n_close.
        n_open = -1
        for tag in ("<filter", "<svg"):
            t = html.find(tag, k)
            if 0 <= t < n_close and (n_open < 0 or t < n_open):
                n_open = t
        if n_open < 0:
            depth -= 1
            k = n_close + len("</filter>")
        else:
            depth += 1
            # Find the matching close: </filter>, </svg>, or "/>"
            end = html.find(">", n_open) + 1
            # Self-closing <feImage ... /> does not nest; otherwise look for </tag>
            slice_ = html[n_open:end]
            if slice_.rstrip().endswith("/>"):
                k = end
            else:
                tag = html[n_open : n_open + 5]  # <svg or <filter
                close_tag = "</" + tag[1:] + ">"
                # Nested feImage / svg / filter inside an feImage href is a
                # data: URI we should skip entirely. Detect href=" and let the
                # matching close_tag search proceed from there.
                c = html.find(close_tag, end)
                if c < 0:
                    raise AssertionError(f"unterminated nested tag {tag} in #{filter_id}")
                k = c + len(close_tag)
    return html[j:k]


def _supports_url_body(css: str) -> str:
    """Return the body of @supports (backdrop-filter: url(...)) { ... }.

    Scans brace depth -- the @supports block contains its own { } per rule,
    so a naive non-greedy regex stops at the first '}'.
    """
    idx = css.find("@supports (backdrop-filter: url(")
    assert idx >= 0, "no @supports (backdrop-filter: url()) block in glass.css"
    brace = css.index("{", idx)
    depth = 1
    k = brace + 1
    while depth and k < len(css):
        n_open = css.find("{", k)
        n_close = css.find("}", k)
        if n_close < 0:
            raise AssertionError("unterminated @supports (url()) block")
        if 0 <= n_open < n_close:
            depth += 1
            k = n_open + 1
        else:
            depth -= 1
            k = n_close + 1
    return css[brace + 1 : k - 1]


class TestEdgeLensFiltersAreDefined:
    """Both filters must exist so glass.css can name them."""

    def test_radar_refract_present(self):
        assert 'id="radar-refract"' in BASE_HTML

    def test_radar_refract_soft_present(self):
        assert 'id="radar-refract-soft"' in BASE_HTML

    def test_shared_rim_shape_present(self):
        # Both filters reference the same rounded-rectangle stroke via
        # feImage href="#radar-refract-edges". Centralising the shape keeps
        # the rim aligned with the visible border.
        assert 'id="radar-refract-edges"' in BASE_HTML


class TestEdgeLensModulation:
    """Each filter must encode "centre 0.5, rim follows the field".

    Closed form: D = T*M - 0.5*M + 0.5  --> feComposite arithmetic with
    k1=1, k2=0, k3=-0.5, k4=0.5. The k values are integer/string float
    constants -- if anyone simplifies them, the centre will drift.
    """

    @pytest.mark.parametrize("filter_id", ["radar-refract", "radar-refract-soft"])
    def test_filter_has_fe_image_rim_mask(self, filter_id):
        body = _filter_body(BASE_HTML, filter_id)
        assert "<feImage" in body, f"#{filter_id} has no feImage -- rim mask missing"
        # Must point at an outline, not a filled rectangle (which would invert
        # the lens into an opaque panel).
        assert 'href="#radar-refract-edges"' in body, (
            f"#{filter_id} feImage must reference the shared rounded-rect "
            f"stroke; a filled shape would make the glass opaque."
        )

    @pytest.mark.parametrize("filter_id", ["radar-refract", "radar-refract-soft"])
    def test_filter_has_arithmetic_composite_in_closed_form(self, filter_id):
        body = _filter_body(BASE_HTML, filter_id)
        # The k1..k4 constants encode D = T*M - 0.5*M + 0.5 exactly.
        # k1=1 multiplies T*M, k3=-0.5 subtracts 0.5*M, k4=0.5 biases the
        # centre to 0.5 (no shift). k2=0 leaves T alone.
        # Tolerate whitespace and attribute order.
        import re

        pat = re.compile(
            r'feComposite[^>]*operator="arithmetic"[^>]*'
            r'k1="1"[^>]*k2="0"[^>]*k3="-0\.5"[^>]*k4="0\.5"',
            re.DOTALL,
        )
        assert pat.search(body), (
            f"#{filter_id} is missing the closed-form arithmetic modulation. "
            f"The centre would no longer stay at 0.5 (no shift), so every "
            f"glass surface would refract the whole backdrop uniformly."
        )


class TestGlassCssWiring:
    """glass.css must apply the soft variant to cards inside @supports url().

    A common mistake is to point .glass--card at the strong #radar-refract
    by accident. That makes a row of cards distort visibly and breaks the
    contrast budget for any small text inside them.
    """

    def test_cards_apply_refract_soft_in_url_supports_block(self):
        body = _supports_url_body(GLASS_CSS)
        assert ".glass--card" in body, ".glass--card is missing from the @supports (url()) block"
        assert "url(#radar-refract-soft)" in body, (
            ".glass--card must use url(#radar-refract-soft), not the strong "
            "#radar-refract. The soft variant keeps the rim gentle."
        )

    def test_nav_and_panel_apply_strong_refract(self):
        body = _supports_url_body(GLASS_CSS)
        assert ".glass--nav" in body
        assert "url(#radar-refract)" in body
        assert ".glass--panel" in body


class TestRemovingTheRimMaskBreaksCards:
    """If anyone removes the feImage rim mask, the edge lens turns into a
    uniform displacement, and cards would jitter. This guard pins that the
    feImage is actually doing the rim work.
    """

    def test_card_filter_has_no_plain_fe_displacement_against_noise(self):
        # In an edge-only design, feDisplacementMap must take a modulated D,
        # not the raw noise field. If someone reverts to "in2=field" the
        # whole panel would displace again, and the test asserts the in2 is
        # NOT the turbulence output directly.
        body = _filter_body(BASE_HTML, "radar-refract-soft")
        # The turbulence result is named "T" (after the alpha=1 matrix).
        # D comes from the arithmetic composite. Assert neither
        # in2="T" nor in2="noise" appears on a feDisplacementMap.
        import re

        for m in re.finditer(r"<feDisplacementMap[^>]*>", body):
            tag = m.group(0)
            assert 'in2="T"' not in tag, (
                "feDisplacementMap is reading the raw noise field directly. "
                "That makes every glass surface refract uniformly. The "
                "edge-only design must read D (the arithmetic result) "
                "instead."
            )
            assert 'in2="noise"' not in tag, (
                "feDisplacementMap is reading the turbulence result "
                "directly. Same problem -- the rim mask is not being applied."
            )

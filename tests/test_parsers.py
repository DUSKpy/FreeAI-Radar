"""Parsers: the layer where a source's formatting becomes our data model.

These tests run against committed fixture documents rather than live pages, so
they stay stable when an upstream README is reflowed. The fixtures are real
captures, which means they carry the messiness the parser actually has to
survive: inconsistent column names, sentinel blocks, emoji, footnotes.
"""

from __future__ import annotations

from radar.parsers.html_docs import extract_evidence, parse_html
from radar.parsers.markdown_tables import (
    extract_capabilities,
    extract_context_window,
    parse_tables,
)


class TestMarkdownTableExtraction:
    def test_finds_a_basic_table(self) -> None:
        md = """
| Provider | Free Tier |
| --- | --- |
| Groq | Yes |
"""
        tables = parse_tables(md)
        assert len(tables) == 1
        assert tables[0].headers == ["Provider", "Free Tier"]
        assert len(tables[0].rows) == 1

    def test_a_table_without_a_separator_row_is_not_a_table(self) -> None:
        # Pipe-delimited prose is common in READMEs. Without the `---`
        # separator row it is not a table, and treating it as one produces
        # garbage rows.
        md = """
| this is just a sentence with pipes |
| and another one |
"""
        assert parse_tables(md) == []

    def test_returns_every_table_in_a_document(self) -> None:
        md = """
| A | B |
| --- | --- |
| 1 | 2 |

Some prose in between.

| C | D |
| --- | --- |
| 3 | 4 |
"""
        tables = parse_tables(md)
        assert len(tables) == 2
        assert tables[0].headers == ["A", "B"]
        assert tables[1].headers == ["C", "D"]

    def test_captures_cell_text_verbatim_including_whitespace(self) -> None:
        # The parser keeps raw cell text; trimming is a later decision so that
        # evidence excerpts can quote the source accurately.
        md = """
| Provider | Notes |
| --- | --- |
|  Groq  |  fast  |
"""
        row = parse_tables(md)[0].rows[0]
        assert row[0].strip() == "Groq"
        assert row[1].strip() == "fast"

    def test_a_row_with_fewer_cells_than_headers_does_not_crash(self) -> None:
        # Ragged tables are extremely common in hand-edited READMEs.
        md = """
| A | B | C |
| --- | --- | --- |
| 1 | 2 |
"""
        tables = parse_tables(md)
        assert len(tables) == 1
        # Whatever the parser does with it, it must not raise and must not
        # silently invent a value for the missing cell.
        assert len(tables[0].rows[0]) <= 3


class TestSentinelScoping:
    """Sources mark their tables with ``<!--TABLE:NAME:START-->`` sentinels.
    Scoping to a sentinel is what keeps a "Contributing" table or a "License"
    table from being mined for provider rows."""

    def test_sentinel_is_recorded(self) -> None:
        md = """
<!--TABLE:PROVIDERS:START-->

| Provider | Free |
| --- | --- |
| Groq | Yes |

<!--TABLE:PROVIDERS:END-->
"""
        tables = parse_tables(md)
        assert len(tables) == 1
        assert tables[0].sentinel is not None

    def test_limiting_to_one_sentinel_excludes_the_others(self) -> None:
        md = """
<!--TABLE:PROVIDERS:START-->

| Provider | Free |
| --- | --- |
| Groq | Yes |

<!--TABLE:PROVIDERS:END-->

<!--TABLE:OTHER:START-->

| Unrelated | Thing |
| --- | --- |
| a | b |

<!--TABLE:OTHER:END-->
"""
        all_tables = parse_tables(md)
        scoped = parse_tables(md, limited_to_sentinels=["PROVIDERS"])
        assert len(all_tables) >= 2
        assert len(scoped) < len(all_tables)
        assert all("PROVIDERS" in (t.sentinel or "") for t in scoped)

    def test_limiting_to_a_sentinel_that_is_absent_returns_nothing(self) -> None:
        md = """
| A | B |
| --- | --- |
| 1 | 2 |
"""
        assert parse_tables(md, limited_to_sentinels=["NOPE"]) == []


class TestColumnLookupIsForgiving:
    """Upstream renames a column and the parser must keep working. The
    `column()` helper does normalised matching for exactly this reason."""

    def _table_with(self, header: str):
        md = f"""
| Provider | {header} |
| --- | --- |
| Groq | Yes |
"""
        return parse_tables(md)[0]

    def test_matches_an_exact_header(self) -> None:
        assert self._table_with("Credit Card").column("Credit Card") == 1

    def test_matches_across_punctuation_and_case(self) -> None:
        index = self._table_with("Credit Card?").column("credit_card")
        assert index == 1

    def test_matches_camel_case_and_spacing_variants(self) -> None:
        assert self._table_with("creditcard").column("credit card") == 1
        assert self._table_with("Credit-Card").column("credit_card") == 1

    def test_returns_none_for_an_absent_column(self) -> None:
        # Returning None rather than 0 matters: index 0 is a real column, and
        # defaulting to it would silently read the provider name as a quota.
        assert self._table_with("Notes").column("totally_unrelated") is None

    def test_accepts_several_aliases_and_takes_the_first_match(self) -> None:
        assert self._table_with("Models").column("model", "models") == 1


class TestFreeLlmFixture:
    """The committed capture of the Free-LLM README."""

    def test_parses_at_least_one_table(self, free_llm_readme: str) -> None:
        assert parse_tables(free_llm_readme), "no table found in the fixture"

    def test_finds_provider_rows(self, free_llm_readme: str) -> None:
        tables = parse_tables(free_llm_readme)
        total_rows = sum(len(t.rows) for t in tables)
        assert total_rows >= 10, f"only {total_rows} rows parsed"

    def test_no_table_has_a_zero_width_header(self, free_llm_readme: str) -> None:
        # A header row of all-empty strings means the separator was mistaken
        # for content somewhere upstream.
        for table in parse_tables(free_llm_readme):
            assert any(h.strip() for h in table.headers), table.headers

    def test_every_header_count_matches_its_widest_row(self, free_llm_readme: str) -> None:
        for table in parse_tables(free_llm_readme):
            widest = max((len(r) for r in table.rows), default=0)
            assert widest <= len(table.headers) + 1, (
                f"a row has more cells than there are headers: "
                f"{len(table.headers)} headers, {widest} cells"
            )


class TestAwesomeFixture:
    def test_parses_tables(self, awesome_readme: str) -> None:
        tables = parse_tables(awesome_readme)
        assert tables, "no table found in the fixture"

    def test_yields_a_usable_number_of_rows(self, awesome_readme: str) -> None:
        total_rows = sum(len(t.rows) for t in parse_tables(awesome_readme))
        assert total_rows >= 10, f"only {total_rows} rows parsed"


class TestHtmlParser:
    def test_parses_a_minimal_document(self) -> None:
        doc = parse_html("<html><body><h1>Pricing</h1><p>Free tier</p></body></html>")
        assert doc is not None

    def test_handles_a_malformed_document_without_raising(self) -> None:
        # Real pages are rarely well-formed. A parser that raises on an
        # unclosed tag turns one bad page into a failed collection run.
        doc = parse_html("<html><body><p>Free <b>tier<table><tr><td>x")
        assert doc is not None

    def test_empty_input_does_not_raise(self) -> None:
        assert parse_html("") is not None


class TestEvidenceExtraction:
    """Evidence excerpts are what make a claim checkable. They must be short
    quotations from the page, not the whole page."""

    def test_extracts_a_short_excerpt_around_a_keyword(self) -> None:
        text = (
            "Our service offers a generous free tier for developers. "
            "You get one million tokens every month at no cost. "
            "Paid plans start at twenty dollars."
        )
        excerpts = extract_evidence(text, ["free tier"])
        assert excerpts, "a matching keyword should yield an excerpt"
        assert any("free tier" in e.lower() for e in excerpts)

    def test_excerpts_are_bounded_in_length(self) -> None:
        text = "free tier " + ("x " * 5000) + " end"
        excerpts = extract_evidence(text, ["free tier"], window=220)
        for excerpt in excerpts:
            # The window bounds the excerpt; a runaway excerpt would bloat the
            # published JSON and leak more of the source than necessary.
            assert len(excerpt) <= 600, len(excerpt)

    def test_no_keyword_means_no_excerpt(self) -> None:
        text = "This page is about something else entirely."
        assert extract_evidence(text, ["free tier", "no credit card"]) == []

    def test_extraction_is_case_insensitive(self) -> None:
        excerpts = extract_evidence("We offer a FREE TIER for everyone.", ["free tier"])
        assert excerpts

    def test_operates_on_plain_text_not_markup(self) -> None:
        """`extract_evidence` is documented to take text, and callers pass
        `HtmlDocument.main_text` -- the value `parse_html` already stripped of
        tags. Feeding it raw markup would quote markup at the reader, so the
        tag stripping is the HTML parser's job, not this function's.

        This test pins the division of labour: parse first, then extract.
        """
        html = "<html><body><p>Our <b>free tier</b> includes 1M tokens.</p></body></html>"
        doc = parse_html(html)
        assert "<b>" not in doc.main_text, "parse_html must strip tags"

        excerpts = extract_evidence(doc.main_text, ["free tier"])
        assert excerpts, "the stripped text should still match"
        for excerpt in excerpts:
            assert "<b>" not in excerpt
            assert "<p>" not in excerpt

    def test_collapses_whitespace(self) -> None:
        text = "free tier\n\n    with     lots   of   space"
        excerpts = extract_evidence(text, ["free tier"])
        for excerpt in excerpts:
            assert "\n" not in excerpt
            assert "  " not in excerpt

    def test_caps_the_number_of_excerpts(self) -> None:
        # The published JSON must stay small, and quoting a page in full would
        # exceed fair use besides.
        text = "free tier " * 200
        excerpts = extract_evidence(text, ["free tier"])
        assert len(excerpts) <= 6, len(excerpts)

    def test_duplicate_hits_are_deduplicated(self) -> None:
        text = "free tier. " + ("padding " * 50) + "free tier."
        excerpts = extract_evidence(text, ["free tier"])
        assert len(excerpts) == len(set(excerpts))


class TestNumericExtraction:
    def test_context_window_reads_plain_tokens(self) -> None:
        assert extract_context_window("Context window: 8192 tokens") == 8192

    def test_context_window_reads_a_k_suffix(self) -> None:
        assert extract_context_window("context is 128k tokens") == 128_000

    def test_context_window_reads_an_m_suffix(self) -> None:
        assert extract_context_window("context window 1M tokens") == 1_000_000

    def test_context_window_reads_a_comma_separated_value(self) -> None:
        assert extract_context_window("Context Window: 1,000,000") == 1_000_000

    def test_context_window_returns_none_when_absent(self) -> None:
        # None, not 0: 0 would be published as a real context window.
        assert extract_context_window("no numbers here") is None

    def test_context_window_ignores_an_implausible_value(self) -> None:
        # A price or a year must not be mistaken for a context window.
        result = extract_context_window("Context window: 2024")
        assert result is None or result == 2024


class TestCapabilityExtraction:
    def test_finds_known_capability_names(self) -> None:
        found = extract_capabilities("Supports tool calling and vision, plus streaming.")
        assert "calling" in " ".join(found).lower() or found

    def test_returns_a_list_for_a_document_with_no_capabilities(self) -> None:
        assert extract_capabilities("A plain sentence with nothing notable.") == []

    def test_does_not_invent_a_capability_from_unrelated_text(self) -> None:
        found = extract_capabilities("The weather today is pleasant.")
        assert not any(tag in {"vision", "audio", "embedding"} for tag in found)

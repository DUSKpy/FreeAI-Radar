"""Test the review mechanism end-to-end.

config/reviews.yaml is the one place in the system where a human (or anyone
who can show evidence) can override what a directory source says. Until now
nothing exercised it: the file is empty, and so was the test file.

These tests prove the mechanism works. They do NOT pretend a real review
exists -- they write a temporary review, run the application, and check
the result. The point is the wiring, not the data.

A real reviews.yaml in production is the user's job, not this test's.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from radar import collect
from radar.config import ReviewOverride, _parse_reviews
from radar.models import RadarState, ReviewDecision

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "state.minimal.json"


def _load_state() -> RadarState:
    """Load the fixture as a real RadarState.

    The fixture is a JSON dump; collect parses it back. Going through the
    parser means the test exercises the same path the pipeline does.
    """
    import json as _json

    raw = _json.loads(FIXTURE.read_text(encoding="utf-8"))
    return RadarState.model_validate(raw)


def _first_claim(state: RadarState, slug: str, field: str):
    """Find a claim for the given provider slug + field, or fail loudly."""
    provider = next((p for p in state.providers if p.slug == slug), None)
    assert provider is not None, f"fixture has no provider with slug {slug!r}"
    claim = next(
        (c for c in state.claims if c.subject_id == provider.id and c.field == field),
        None,
    )
    assert claim is not None, f"fixture has no claim for {slug}.{field}; pick a different field"
    return provider, claim


def _now() -> str:
    from radar.ids import iso_utc

    return iso_utc()


def _confirm_review(
    provider, value, evidence_url: str, reason: str = "test only"
) -> ReviewOverride:
    return ReviewOverride(
        subject_type="provider",
        subject_key=provider.slug,
        field="base_url",
        value=value,
        decision=ReviewDecision.CONFIRM.value,
        evidence_url=evidence_url,
        reviewer="radar-test",
        reviewed_at=_now(),
        reason=reason,
    )


class TestReviewMechanism:
    """A review can promote a claim from directory_claim to official_confirmed."""

    def test_confirm_changes_review_status_to_official_confirmed(self) -> None:
        state = _load_state()
        provider, claim = _first_claim(state, "aion-labs", "base_url")

        assert claim.review_status.value == "directory_claim", (
            "fixture assumption broken: this test needs a directory_claim "
            "to promote. If the fixture changed, pick a different field."
        )

        review = _confirm_review(
            provider,
            claim.value,
            "https://example.com/aion-labs-docs",
            reason="test only: confirms a directory_claim into official_confirmed",
        )
        records, warnings = collect._apply_reviews(
            [review],
            state.providers,
            state.models,
            state.offers,
            state.claims,
            state,
            moment=_now(),
        )
        assert not warnings, f"unexpected warnings: {warnings}"

        after = next(
            c for c in state.claims if c.subject_id == provider.id and c.field == "base_url"
        )
        assert after.review_status.value == "official_confirmed", (
            f"expected official_confirmed, got {after.review_status}"
        )
        assert len(records) == 1, f"expected 1 review record, got {len(records)}"
        assert records[0].decision == ReviewDecision.CONFIRM
        # claim_fingerprint is derived from the evidence_url; changing it
        # would change the fingerprint, which the next test verifies.
        assert records[0].claim_fingerprint, "review record must carry a fingerprint"

    def test_reject_changes_review_status_to_rejected(self) -> None:
        state = _load_state()
        provider, _claim = _first_claim(state, "aion-labs", "base_url")

        review = ReviewOverride(
            subject_type="provider",
            subject_key=provider.slug,
            field="base_url",
            value=_claim.value,
            decision=ReviewDecision.REJECT.value,
            evidence_url="https://example.com/aion-labs-rejected",
            reviewer="radar-test",
            reviewed_at=_now(),
            reason="test only: rejects a directory_claim",
        )
        collect._apply_reviews(
            [review],
            state.providers,
            state.models,
            state.offers,
            state.claims,
            state,
            moment=_now(),
        )

        after = next(
            c for c in state.claims if c.subject_id == provider.id and c.field == "base_url"
        )
        assert after.review_status.value == "rejected", (
            f"expected rejected, got {after.review_status}"
        )

    def test_review_referencing_unknown_provider_is_recorded_but_does_nothing(self) -> None:
        state = _load_state()
        review = ReviewOverride(
            subject_type="provider",
            subject_key="nonexistent-provider-xyz",
            field="base_url",
            value="https://example.com",
            decision=ReviewDecision.CONFIRM.value,
            evidence_url="https://example.com/nope",
            reviewer="radar-test",
            reviewed_at=_now(),
        )
        records, warnings = collect._apply_reviews(
            [review],
            state.providers,
            state.models,
            state.offers,
            state.claims,
            state,
            moment=_now(),
        )

        # The rule is kept (a maintainer wants to see what was tried) but
        # no claim gets touched, because there is no matching provider. The
        # status surfaces in the record's reason, not its decision.
        assert any(r.reason == "unknown_subject" for r in records), (
            f"expected an unknown_subject record, got reasons: {[r.reason for r in records]}"
        )
        assert any("nonexistent-provider-xyz" in w for w in warnings), (
            f"expected a warning naming the unknown provider, got: {warnings}"
        )
        # No claim's review_status moved to official_confirmed.
        for claim in state.claims:
            assert claim.review_status.value != "official_confirmed", (
                f"unknown review leaked into {claim.subject_id}.{claim.field}"
            )

    def test_fingerprint_reflects_the_evidence_url(self) -> None:
        """A stale review with the same claim cannot survive an evidence change.

        This is the "review expires" property: the fingerprint includes the
        evidence_url, so when the URL changes the fingerprint changes and the
        review can no longer be reused to re-confirm an updated page. The
        downside is that the fingerprint changes the moment the maintainer
        re-saves the file; that is intentional -- it forces a fresh review.
        """
        state = _load_state()
        provider, _claim = _first_claim(state, "aion-labs", "base_url")
        moment = _now()

        review = _confirm_review(provider, _claim.value, "https://example.com/first-look")
        records, _warnings = collect._apply_reviews(
            [review],
            state.providers,
            state.models,
            state.offers,
            state.claims,
            state,
            moment=moment,
        )
        first_fingerprint = records[0].claim_fingerprint

        # Same claim, same decision, same reviewer's stamp -- only the URL
        # changes. The fingerprint MUST change.
        review2 = _confirm_review(provider, _claim.value, "https://example.com/second-look")
        records2, _w2 = collect._apply_reviews(
            [review2],
            state.providers,
            state.models,
            state.offers,
            state.claims,
            state,
            moment=moment,
        )

        assert first_fingerprint != records2[0].claim_fingerprint, (
            "the same rule with a different evidence_url produced the same "
            "fingerprint, which means a stale review would be accepted as "
            "fresh -- the whole point of including the URL in the fingerprint"
        )

    def test_yaml_loader_round_trips_a_review(self, tmp_path: Path) -> None:
        """A real reviews.yaml written and read back should produce the same record.

        The mechanism is only useful if a maintainer can edit YAML, save the
        file, and have it survive the loader. This catches schema drift.
        """
        yaml_path = tmp_path / "reviews.yaml"
        yaml_path.write_text(
            """reviews:
  - subject_type: provider
    subject: aion-labs
    field: base_url
    value: https://api.aionlabs.example/v1
    decision: confirm
    evidence_url: https://example.com/aion-labs-docs
    reviewer: radar-test
    reviewed_at: 2026-09-15T20:00:00Z
    reason: automated verification against the docs page
""",
            encoding="utf-8",
        )

        parsed = _parse_reviews(yaml.safe_load(yaml_path.read_text(encoding="utf-8")), yaml_path)
        assert len(parsed) == 1
        r = parsed[0]
        assert r.subject_type == "provider"
        assert r.subject_key == "aion-labs"
        assert r.field == "base_url"
        assert r.decision == ReviewDecision.CONFIRM.value
        assert r.reviewer == "radar-test"
        assert r.evidence_url == "https://example.com/aion-labs-docs"
        # reason is preserved -- the loader does not require it, but the
        # field is what tells a future maintainer (or auditor) why the
        # decision was made.
        assert r.reason and "automated" in r.reason

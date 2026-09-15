"""The invariants that make this project trustworthy rather than just current.

Every test here traces to a rule in the task book. They are grouped by the rule
they defend, because when one fails the useful information is *which promise
broke*, not which function returned the wrong value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate(instance: object, schema: dict) -> list[str]:
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'} :: {e.message}"
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


class TestStateSchemaIsClosed:
    """A schema with `additionalProperties: true` at the top level would let a
    collector smuggle anything into the published state, including a field
    nobody meant to publish. The schema must be closed."""

    def test_state_schema_forbids_unknown_top_level_keys(self) -> None:
        schema = load_schema("state.schema.json")
        assert schema.get("additionalProperties") is False

    def test_state_schema_lists_every_required_key(self) -> None:
        schema = load_schema("state.schema.json")
        required = set(schema["required"])
        # These are the keys the exporters and templates read. If one stops
        # being required, a partial state file could pass validation and then
        # fail deep inside a build.
        assert {
            "schema_version",
            "state_version",
            "created_at",
            "updated_at",
            "runs",
            "sources",
            "snapshots",
            "providers",
            "models",
            "offers",
            "claims",
            "reviews",
            "changes",
            "collection_meta",
        } <= required

    def test_unknown_top_level_key_is_rejected(self, minimal_state: dict) -> None:
        schema = load_schema("state.schema.json")
        instance = dict(minimal_state)
        instance["surprise"] = {"nested": "value"}
        assert validate(instance, schema), "an unknown top-level key must fail validation"

    def test_fixture_validates(self, minimal_state: dict) -> None:
        problems = validate(minimal_state, load_schema("state.schema.json"))
        assert problems == [], "\n".join(problems)


class TestCatalogSchemaIsClosed:
    def test_catalog_schema_is_closed(self) -> None:
        schema = load_schema("catalog.schema.json")
        assert schema.get("additionalProperties") is False

    def test_manifest_schema_is_closed(self) -> None:
        schema = load_schema("manifest.schema.json")
        assert schema.get("additionalProperties") is False


class TestTriStateIsNeverCollapsed:
    """The single most important semantic rule in the project: 'unknown' is not
    'no'. A source that omits a requirement field tells us nothing about
    whether the requirement exists, and the schema must not force a boolean.
    """

    def test_tri_state_enum_has_exactly_three_values(self) -> None:
        from radar.vocab import TriState

        assert {member.value for member in TriState} == {"need", "not_need", "unknown"}

    def test_unknown_is_distinct_from_not_need(self) -> None:
        from radar.vocab import TriState

        assert TriState.UNKNOWN != TriState.NOT_NEED

    def test_tighten_never_turns_unknown_into_a_negative(self) -> None:
        """Merging two observations must not invent a 'no'.

        `_tighten` is called when the same offer is seen twice. If one sighting
        says 'need' and another says 'unknown', the honest merge is 'need' --
        an explicit observation outranks silence. But 'unknown' merged with
        'unknown' must stay 'unknown', never become 'not_need'.
        """
        from radar.normalize import _tighten
        from radar.vocab import TriState

        assert _tighten(TriState.UNKNOWN, TriState.UNKNOWN) == TriState.UNKNOWN
        assert _tighten(TriState.NEED, TriState.UNKNOWN) == TriState.NEED
        assert _tighten(TriState.UNKNOWN, TriState.NEED) == TriState.NEED
        assert _tighten(TriState.NOT_NEED, TriState.UNKNOWN) == TriState.NOT_NEED
        assert _tighten(TriState.NEED, TriState.NOT_NEED) == TriState.NEED

    def test_tri_parsing_of_none_is_unknown(self) -> None:
        """A missing field must parse to `unknown`.

        This is the exact line where a careless implementation writes
        `return TriState.NOT_NEED if value is None else ...`, which silently
        asserts "this provider does not need a card" about a provider nobody
        has information about.

        Note the signature: `_tri` takes the raw cell text, not a bool. An
        empty cell, a dash and a question mark are all "the source did not
        say", and none of them may become a negative.
        """
        from radar.normalize import _tri
        from radar.vocab import TriState

        assert _tri(None) == TriState.UNKNOWN
        assert _tri("") == TriState.UNKNOWN
        assert _tri("unknown") == TriState.UNKNOWN
        # A value nobody has taught us about is also unknown, not a negative.
        assert _tri("maybe-later") == TriState.UNKNOWN

        # Explicit answers are preserved.
        assert _tri(TriState.NEED) == TriState.NEED
        assert _tri("need") == TriState.NEED
        assert _tri("not_need") == TriState.NOT_NEED


class TestProtocolsStayDistinct:
    """The four protocols are wire formats, not marketing categories. Merging
    `openai_chat` with `openai_responses` would tell a user their client works
    when it does not, which is the specific failure the task book forbids."""

    def test_four_protocols_exist(self) -> None:
        from radar.vocab import Protocol

        assert {p.value for p in Protocol} == {
            "openai_chat",
            "openai_responses",
            "anthropic_messages",
            "gemini_native",
        }

    def test_chat_and_responses_are_not_the_same_protocol(self) -> None:
        from radar.vocab import Protocol

        assert Protocol.OPENAI_CHAT != Protocol.OPENAI_RESPONSES

    def test_default_protocols_are_explicit_not_guessed(self) -> None:
        """An unrecognised api_format must not be mapped onto a working
        protocol. Guessing here is how 'compatible' gets fabricated."""
        from radar.normalize import default_protocols

        known = default_protocols("openai")
        assert known, "an explicitly OpenAI-shaped source should yield a protocol"

        # Anything nobody has taught us about yields nothing rather than a
        # plausible-looking default.
        assert default_protocols("something-nobody-has-seen") == []


class TestOfferTypesAreSeparated:
    """'Free' is five different things. A `one_time_trial` presented with the
    same chip as a `sustained_free_tier` is the single most misleading thing
    this site could do."""

    def test_offer_types_include_the_distinctions_that_matter(self) -> None:
        from radar.vocab import OfferType

        values = {t.value for t in OfferType}
        assert "sustained_free_tier" in values
        assert "one_time_trial" in values
        assert "requires_topup" in values

    def test_trial_and_sustained_are_different_types(self) -> None:
        from radar.vocab import OfferType

        assert OfferType.ONE_TIME_TRIAL != OfferType.SUSTAINED_FREE_TIER

    def test_requires_topup_is_not_grouped_with_free_tiers(self) -> None:
        # `requires_topup` is a real offer but it is not free. It must remain
        # its own type so the UI cannot accidentally filter it in.
        from radar.vocab import OfferType

        assert OfferType.REQUIRES_TOPUP in set(OfferType)


class TestFiveDimensionsStaySeparate:
    """Access type, free type, info status, call status and agent compatibility
    are five independent axes. Collapsing any pair into one field loses the
    information that makes the site useful."""

    def test_info_status_and_call_status_are_different_enums(self) -> None:
        from radar.vocab import CallStatus, InfoStatus

        assert {s.value for s in InfoStatus} & {s.value for s in CallStatus} == set()

    def test_call_status_defaults_to_untested(self) -> None:
        from radar.vocab import CallStatus

        # Radar never calls a provider with a user's key, so `untested` is the
        # only honest default.
        assert CallStatus.UNTESTED.value == "untested"

    def test_info_status_distinguishes_official_from_directory(self) -> None:
        from radar.vocab import InfoStatus

        assert InfoStatus.OFFICIAL_CONFIRMED != InfoStatus.DIRECTORY_CLAIM

    def test_access_type_separates_api_from_web_chat(self) -> None:
        from radar.vocab import AccessType

        # A free web chat is not a free API. This distinction is the point.
        assert AccessType.API != AccessType.WEB_CHAT_ONLY


class TestEvidenceIsRequired:
    """A claim with no evidence is a rumour. The schema must require the
    evidence array so an unbacked claim cannot be published.

    Both catalog arrays use `$ref` into `$defs`, so the constraints live on the
    definition rather than on the array's `items`. Reading `items["required"]`
    would find nothing and the test would pass vacuously -- which is exactly the
    failure mode a schema test must not have.
    """

    @staticmethod
    def _def(name: str) -> dict:
        return load_schema("catalog.schema.json")["$defs"][name]

    def test_offer_definition_requires_evidence(self) -> None:
        """An offer with no source is an assertion nobody can check.

        This was a real gap: `claim` required evidence and `offer` did not, so
        an offer could be published with no traceable origin at all. The
        exporter happened to always emit the field, which is exactly why the
        omission went unnoticed -- behaviour no test pins down is behaviour
        that can silently change.
        """
        assert "evidence" in self._def("offer")["required"]

    def test_claim_definition_requires_evidence(self) -> None:
        assert "evidence" in self._def("claim")["required"]

    def test_stripping_evidence_from_an_offer_fails_validation(self) -> None:
        """Prove the requirement bites, against the real exported catalog.

        A schema assertion that only checks the `required` list would still
        pass if the array were moved under a different key, so this mutates a
        genuine catalog and requires the validator to object.
        """
        import copy

        catalog_path = next((ROOT / ".work" / "public" / "data").glob("catalog.*.json"), None)
        if catalog_path is None:
            pytest.skip("no exported catalog on disk; run radar.export_public first")

        schema = load_schema("catalog.schema.json")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert validate(catalog, schema) == [], "the real catalog must validate as-is"

        mutated = copy.deepcopy(catalog)
        assert mutated["offers"], "catalog has no offers to test with"
        mutated["offers"][0].pop("evidence", None)

        problems = validate(mutated, schema)
        assert problems, "an offer with no evidence must fail validation"
        assert any("evidence" in p for p in problems), problems

    def test_definitions_are_closed(self) -> None:
        # `additionalProperties: false` on every entity definition is what
        # stops a collector publishing a field nobody reviewed.
        for name in ("provider", "model", "offer", "claim", "publicSource"):
            assert self._def(name).get("additionalProperties") is False, name

    def test_catalog_arrays_reference_definitions(self) -> None:
        # Guards against someone inlining the entities and losing the $defs
        # constraints in the process.
        schema = load_schema("catalog.schema.json")
        for name in ("providers", "models", "offers", "claims", "sources"):
            items = schema["properties"][name]["items"]
            assert items.get("$ref", "").startswith("#/$defs/"), name

    def test_a_claim_without_evidence_fails_validation(self) -> None:
        """Prove the constraint actually bites, rather than trusting that the
        keyword is present."""
        schema = load_schema("catalog.schema.json")
        bad = {
            "schema_version": schema["properties"]["schema_version"].get("const", 1),
            "dataset_version": "sha256:" + "0" * 64,
            "generated_at": "2026-01-01T00:00:00Z",
            "providers": [],
            "models": [],
            "offers": [],
            "sources": [],
            "claims": [
                {
                    "id": "c_test",
                    "subject_type": "provider",
                    "subject_id": "p_test",
                    "field": "free",
                    "value": "yes",
                    "review_status": "directory_claim",
                    # no `evidence`
                }
            ],
        }
        problems = validate(bad, schema)
        assert problems, "a claim with no evidence must not validate"
        assert any("evidence" in p for p in problems), problems

    def test_every_offer_in_the_fixture_has_evidence(self, minimal_state: dict) -> None:
        for offer in minimal_state["offers"]:
            assert offer.get("evidence"), f"offer {offer['id']} has no evidence"

    def test_every_claim_in_the_fixture_has_evidence(self, minimal_state: dict) -> None:
        for claim in minimal_state["claims"]:
            assert claim.get("evidence"), f"claim {claim['id']} has no evidence"


class TestNoSecretsInState:
    """Internal state is not published, but it is committed to the repository,
    so it must not carry credentials either.

    Two subtleties this check has to get right:

    * It looks at declared *property names*, not the raw file text. A substring
      scan matches the sentence "Never contains keys, tokens, cookies", which
      is a description of the guarantee rather than a violation of it.
    * Matching is on whole words, not substrings. `tokens` is a legitimate
      quota unit and `context_window_tokens` is a legitimate field; neither is
      a credential. A substring test flags both.
    """

    # Whole words only. A credential field would be named one of these.
    FORBIDDEN_NAMES: ClassVar[set[str]] = {
        "apikey",
        "api_key",
        "key",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "bearer",
        "credential",
        "credentials",
        "auth",
        "authorization",
        "private_key",
    }

    @staticmethod
    def _collect_property_names(node: object, found: set[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    found.update(value.keys())
                TestNoSecretsInState._collect_property_names(value, found)
        elif isinstance(node, list):
            for entry in node:
                TestNoSecretsInState._collect_property_names(entry, found)

    def _assert_no_credential_field(self, schema_name: str) -> None:
        names: set[str] = set()
        self._collect_property_names(load_schema(schema_name), names)
        offenders = sorted(
            name for name in names if name.lower().replace("-", "_") in self.FORBIDDEN_NAMES
        )
        assert not offenders, f"{schema_name} declares credential field(s): {offenders}"

    def test_state_schema_declares_no_credential_property(self) -> None:
        self._assert_no_credential_field("state.schema.json")

    def test_catalog_schema_declares_no_credential_property(self) -> None:
        self._assert_no_credential_field("catalog.schema.json")

    def test_manifest_schema_declares_no_credential_property(self) -> None:
        self._assert_no_credential_field("manifest.schema.json")

    def test_the_check_would_notice_a_credential_field(self) -> None:
        """A guard that never fires is not a guard. Prove it fires."""
        planted = {"type": "object", "properties": {"apiKey": {"type": "string"}}}
        names: set[str] = set()
        self._collect_property_names(planted, names)
        offenders = [n for n in names if n.lower() in self.FORBIDDEN_NAMES]
        assert offenders == ["apiKey"], offenders

    def test_quota_unit_tokens_is_not_a_false_positive(self) -> None:
        # Pins the exact case that made a substring check unusable.
        names: set[str] = set()
        self._collect_property_names(load_schema("catalog.schema.json"), names)
        assert "context_window_tokens" in names
        assert "context_window_tokens".lower() not in self.FORBIDDEN_NAMES

    def test_fixture_contains_no_key_shaped_string(self, minimal_state: dict) -> None:
        import re

        text = json.dumps(minimal_state, ensure_ascii=False)
        for pattern in (r"sk-[A-Za-z0-9]{20,}", r"gsk_[A-Za-z0-9]{20,}", r"AIza[0-9A-Za-z]{30,}"):
            assert not re.search(pattern, text), f"fixture matches {pattern}"

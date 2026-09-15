"""CC Switch integration: the rules that decide whether we tell a user
"this will work" or "we do not know".

The dangerous failure here is a false positive. Telling someone their Claude
Code client will work against an OpenAI-only endpoint wastes their time and
destroys trust in every other claim on the site. These tests pin the gates that
prevent it.
"""

from __future__ import annotations

from radar.cc_switch import (
    APP_PROTOCOL_REQUIREMENTS,
    DEEP_LINK_VERSION,
    SUPPORTED_CC_SWITCH_COMMIT,
    SUPPORTED_CC_SWITCH_VERSION,
    build_config,
    build_deep_link,
    join_endpoint,
    normalise_endpoint,
)
from radar.vocab import CCStatus, Protocol


class TestAppProtocolGates:
    """Each app speaks exactly one protocol family. A provider that does not
    speak it must be reported unsupported, not coerced."""

    def test_every_app_declares_its_required_protocol(self) -> None:
        assert set(APP_PROTOCOL_REQUIREMENTS) == {
            "claude",
            "codex",
            "gemini",
            "opencode",
            "openclaw",
        }

    def test_claude_requires_anthropic_messages(self) -> None:
        assert APP_PROTOCOL_REQUIREMENTS["claude"] == {Protocol.ANTHROPIC_MESSAGES}

    def test_codex_requires_responses_not_chat(self) -> None:
        # Codex speaks the Responses API. A provider offering only
        # `openai_chat` must NOT be reported as Codex-compatible, which is the
        # exact conflation the task book calls out.
        required = APP_PROTOCOL_REQUIREMENTS["codex"]
        assert Protocol.OPENAI_RESPONSES in required
        assert Protocol.OPENAI_CHAT not in required

    def test_an_openai_chat_provider_is_unsupported_for_claude(self) -> None:
        config = build_config(
            provider_name="Some OpenAI-shaped provider",
            app="claude",
            base_url="https://api.example.com/v1",
            protocols=["openai_chat"],
        )
        assert config.status == CCStatus.UNSUPPORTED_PROTOCOL.value

    def test_an_anthropic_provider_is_ready_for_claude(self) -> None:
        config = build_config(
            provider_name="An Anthropic-shaped provider",
            app="claude",
            base_url="https://api.example.com",
            protocols=["anthropic_messages"],
        )
        assert config.status in {
            CCStatus.READY.value,
            CCStatus.READY_WITHOUT_KEY.value,
        }

    def test_an_unknown_app_is_reported_unknown_not_ready(self) -> None:
        config = build_config(
            provider_name="X",
            app="some-app-nobody-has-heard-of",
            base_url="https://api.example.com",
            protocols=["openai_chat"],
        )
        assert config.status == CCStatus.UNKNOWN.value


class TestNoProtocolsMeansNoClaim:
    """The tri-state rule applied to CC Switch.

    There are two distinct "no" situations here and conflating them would be a
    lie in one direction or the other:

    * The provider's protocols are *known* and none of them is the one this app
      speaks  -> ``unsupported_protocol``. That is a real negative answer.
    * The provider's protocols are *unknown* (nothing declared) -> ``unknown``.
      We cannot say the app is unsupported, because we never found out what
      the provider speaks.

    Collapsing the second case into the first is precisely the mistake the task
    book forbids: writing "not supported" about something nobody checked.
    """

    def test_undeclared_protocols_yield_unknown_not_unsupported(self) -> None:
        for app in APP_PROTOCOL_REQUIREMENTS:
            config = build_config(
                provider_name="Provider with unknown protocols",
                app=app,
                base_url="https://api.example.com",
                protocols=[],
            )
            assert config.status == CCStatus.UNKNOWN.value, app
            assert config.reason == "protocol_unknown", app

    def test_a_known_but_wrong_protocol_yields_unsupported(self) -> None:
        # `openai_chat` is a real protocol; it is simply not the one Claude
        # Code speaks. That is a definite negative, not an unknown.
        config = build_config(
            provider_name="X",
            app="claude",
            base_url="https://api.example.com",
            protocols=["openai_chat"],
        )
        assert config.status == CCStatus.UNSUPPORTED_PROTOCOL.value
        assert config.reason == "protocol_not_supported"

    def test_a_protocol_string_nobody_recognises_is_not_a_match(self) -> None:
        # An unparseable protocol must not accidentally satisfy a requirement,
        # and must not be reported as a definite negative either.
        config = build_config(
            provider_name="X",
            app="claude",
            base_url="https://api.example.com",
            protocols=["something_we_have_never_seen"],
        )
        assert config.status == CCStatus.UNKNOWN.value
        assert not config.ok

    def test_neither_negative_state_is_ever_actionable(self) -> None:
        for app in APP_PROTOCOL_REQUIREMENTS:
            unknown = build_config(
                provider_name="X", app=app, base_url="https://a.example.com", protocols=[]
            )
            unsupported = build_config(
                provider_name="X",
                app=app,
                base_url="https://a.example.com",
                protocols=["openai_chat"],
            )
            # `openclaw`/`opencode` legitimately accept openai_chat, so skip
            # them when asserting the unsupported branch.
            if app not in {"opencode", "openclaw"}:
                assert not unsupported.ok, app
            assert not unknown.ok, app


class TestNoKeyEverLeaves:
    """Radar never handles a user's key. These tests are the enforcement."""

    def test_config_reports_ready_without_key_by_default(self) -> None:
        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        assert config.status == CCStatus.READY_WITHOUT_KEY.value
        assert config.ok

    def test_the_key_field_is_a_secret_placeholder_not_a_value(self) -> None:
        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        key_fields = [f for f in config.fields if f.secret or "key" in f.key.lower()]
        assert key_fields, "the config should tell the user where to put their key"
        for item in key_fields:
            # A secret field must be marked secret so the UI masks it, and must
            # not ship a real value.
            assert item.secret, item.key
            assert not (item.value or "").startswith("sk-"), item.key

    def test_no_field_carries_a_real_key_by_default(self) -> None:
        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        for item in config.fields:
            assert "sk-" not in (item.value or ""), item.key

    def test_deep_link_omits_api_key_when_no_key_is_supplied(self) -> None:
        link = build_deep_link(
            resource="provider",
            app="opencode",
            name="Groq",
            endpoint="https://api.groq.com/openai/v1",
        )
        assert "apiKey" not in link

    def test_deep_link_uses_an_obvious_placeholder_when_asked(self) -> None:
        # The placeholder must be self-evidently not a key, so a user who
        # pastes it in and forgets to replace it gets a clear failure.
        link = build_deep_link(
            resource="provider",
            app="opencode",
            name="Groq",
            endpoint="https://api.groq.com/openai/v1",
            include_key_placeholder=True,
        )
        assert "YOUR_API_KEY" in link

    def test_radar_export_never_contains_a_key_value(self) -> None:
        """The export carries an `api_key` *key* whose value is always null.

        That field is deliberate: it documents where a key would go without
        ever carrying one, and the null is what makes the absence explicit
        rather than ambiguous. Asserting "the string api_key never appears"
        would fail on a correct implementation, so the real invariant is that
        no key ever has a value.
        """
        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        export = config.radar_export
        assert "apiKey" not in export, "the camelCase CC Switch key must not be used"
        assert export.get("api_key") is None, export
        # And nothing else in the export carries a credential either.
        serialised = str(export)
        for marker in ("sk-", "gsk_", "AIza", "Bearer "):
            assert marker not in serialised, marker

    def test_the_ready_deep_link_does_not_carry_a_key(self) -> None:
        """The one case a deep link is emitted is `ready_without_key`, so the
        generated link must not contain an apiKey parameter at all."""
        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        assert config.deep_link, "a ready_without_key config should offer a link"
        assert "apiKey" not in config.deep_link


class TestDeepLinkProtocol:
    """The deep link is a URL other software parses. It must match the
    documented V1 shape exactly."""

    def test_scheme_and_version(self) -> None:
        link = build_deep_link(resource="provider", app="claude", name="X")
        assert link.startswith(f"ccswitch://{DEEP_LINK_VERSION}/import?")

    def test_required_parameters_are_present(self) -> None:
        link = build_deep_link(
            resource="provider",
            app="claude",
            name="X",
            endpoint="https://api.example.com",
        )
        for key in ("resource=", "app=", "name=", "endpoint="):
            assert key in link, key

    def test_chinese_names_are_percent_encoded(self) -> None:
        # A raw Chinese character in a query string is a bug that only shows up
        # for some users, so it is worth an explicit test.
        link = build_deep_link(resource="provider", app="claude", name="智谱 AI")
        assert "智谱" not in link
        assert "%" in link
        # And it must round-trip.
        from urllib.parse import parse_qs, urlsplit

        parsed = parse_qs(urlsplit(link).query)
        assert parsed["name"] == ["智谱 AI"]

    def test_an_endpoint_with_its_own_query_is_encoded_not_injected(self) -> None:
        # A base URL containing `&` must not be able to inject extra params.
        link = build_deep_link(
            resource="provider",
            app="claude",
            name="X",
            endpoint="https://api.example.com/v1?a=1&b=2",
        )
        from urllib.parse import parse_qs, urlsplit

        parsed = parse_qs(urlsplit(link).query)
        assert parsed["endpoint"] == ["https://api.example.com/v1?a=1&b=2"]
        # `b` must not have leaked out as a top-level parameter.
        assert "b" not in parsed


class TestEndpointNormalisation:
    def test_trailing_slash_is_removed(self) -> None:
        assert normalise_endpoint("https://api.example.com/v1/") == "https://api.example.com/v1"

    def test_missing_scheme_is_left_alone_not_guessed(self) -> None:
        # Guessing `https://` would change what the user's client connects to.
        # Better to surface the value as-is and let the user fix it.
        result = normalise_endpoint("api.example.com/v1")
        assert result is None or result == "api.example.com/v1"

    def test_none_passes_through(self) -> None:
        assert normalise_endpoint(None) is None

    def test_join_endpoint_does_not_double_the_slash(self) -> None:
        joined = join_endpoint("https://api.example.com/v1/", "/chat/completions")
        assert "//chat" not in joined
        assert joined.endswith("/chat/completions")

    def test_join_endpoint_handles_a_suffix_without_a_leading_slash(self) -> None:
        joined = join_endpoint("https://api.example.com/v1", "chat/completions")
        assert joined == "https://api.example.com/v1/chat/completions"


class TestVersionPinning:
    """The compatibility claim names a specific CC Switch version. If that
    constant drifts without the docs being re-verified, the claim becomes a
    guess -- so it is pinned here."""

    def test_supported_version_is_pinned(self) -> None:
        assert SUPPORTED_CC_SWITCH_VERSION == "3.20.3"
        assert SUPPORTED_CC_SWITCH_COMMIT == "06082e1"

    def test_config_reports_the_pinned_version(self) -> None:
        config = build_config(
            provider_name="X",
            app="claude",
            base_url="https://api.example.com",
            protocols=["anthropic_messages"],
        )
        assert config.supported_version == SUPPORTED_CC_SWITCH_VERSION
        assert config.supported_commit == SUPPORTED_CC_SWITCH_COMMIT


class TestMissingFieldsAreNamed:
    def test_no_endpoint_is_reported_as_missing_fields(self) -> None:
        config = build_config(
            provider_name="X",
            app="claude",
            base_url=None,
            protocols=["anthropic_messages"],
        )
        assert config.status == CCStatus.MISSING_FIELDS.value
        assert config.reason == "missing_endpoint"
        assert not config.ok

    def test_an_actionable_config_carries_fields(self) -> None:
        config = build_config(
            provider_name="Groq",
            app="openclaw",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        assert config.ok
        assert config.fields, "an actionable config must expose copyable fields"

    def test_every_field_has_a_label_and_a_key(self) -> None:
        # The UI renders these directly; a field with no label would show up as
        # a blank row.
        config = build_config(
            provider_name="Groq",
            app="openclaw",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        for item in config.fields:
            assert item.key, item
            assert item.label, item

    def test_a_non_actionable_config_is_never_described_as_ok(self) -> None:
        cases = [
            {"app": "claude", "base_url": "https://a.example.com", "protocols": []},
            {"app": "claude", "base_url": "https://a.example.com", "protocols": ["openai_chat"]},
            {"app": "claude", "base_url": None, "protocols": ["anthropic_messages"]},
            {"app": "nope", "base_url": "https://a.example.com", "protocols": ["openai_chat"]},
        ]
        for case in cases:
            config = build_config(provider_name="X", **case)
            assert not config.ok, case
            assert config.status != CCStatus.READY.value, case

    def test_to_dict_is_json_serialisable(self) -> None:
        import json

        config = build_config(
            provider_name="Groq",
            app="opencode",
            base_url="https://api.groq.com/openai/v1",
            protocols=["openai_chat"],
        )
        payload = config.to_dict()
        json.dumps(payload)  # must not raise
        # The export is labelled as a Radar exchange file, not a native CC
        # Switch import, so nobody mistakes one for the other.
        assert "雷达" in payload["radar_export_label"] or "Radar" in payload["radar_export_label"]

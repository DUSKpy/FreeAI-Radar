"""The safety guard is the only thing standing between a malicious source and
this machine's internal network. These tests are the highest-value tests in the
suite, so they cover the awkward cases rather than the happy path.

The API has two entry points and they are not interchangeable:

* ``check_url`` validates scheme and *literal* host only, with no DNS lookup.
  It returns a :class:`UrlCheck`; call ``.require()`` to turn a refusal into an
  exception. Collectors use it before any request is made.
* ``check_url_resolved`` adds DNS resolution and validates every returned
  address, which is what stops a public hostname that resolves to 127.0.0.1.

``check_evidence_link`` is deliberately weaker than both: a link that is only
ever rendered into an anchor needs the scheme checked, not the network.
"""

from __future__ import annotations

import pytest

from radar.safety import (
    UnsafeUrlError,
    check_evidence_link,
    check_url,
    check_url_resolved,
    dns_proxy_allowed,
    strip_tracking_params,
)


def refusal(url: str, **kwargs) -> str:
    """Return the refusal reason, or fail the test if the URL was allowed."""
    result = check_url(url, **kwargs)
    assert not result.ok, f"expected {url!r} to be refused"
    return result.reason


class TestSchemeAndHost:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://localhost/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_loopback_is_refused(self, url: str) -> None:
        assert refusal(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.5.5/",
        ],
    )
    def test_private_and_link_local_are_refused(self, url: str) -> None:
        assert refusal(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.com/",
            "ftp://example.com/",
            "data:text/html,<script>",
        ],
    )
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        assert refusal(url)

    def test_plain_https_is_allowed(self) -> None:
        result = check_url("https://api.groq.com/openai/v1")
        assert result.ok, result.reason
        assert result.host == "api.groq.com"

    def test_missing_host_is_refused(self) -> None:
        # `http:///path` has a scheme and no host. Fetching it would fail in a
        # confusing way much later, so it is refused up front.
        assert refusal("http:///path")

    @pytest.mark.parametrize("host", ["box.internal", "printer.local", "thing.localhost"])
    def test_internal_suffixes_are_refused(self, host: str) -> None:
        assert refusal(f"https://{host}/data")

    def test_require_raises_the_refusal_reason(self) -> None:
        # The exception message is what a collection report shows a maintainer,
        # so it must name the reason rather than being a bare ValueError.
        with pytest.raises(UnsafeUrlError, match="loopback"):
            check_url("http://localhost/").require()


class TestDomainAllowlist:
    def test_host_outside_the_allowlist_is_refused(self) -> None:
        reason = refusal(
            "https://evil.example.net/data.json",
            allowed_domains=["raw.githubusercontent.com"],
        )
        assert "allowed_domains" in reason

    def test_host_inside_the_allowlist_passes(self) -> None:
        result = check_url(
            "https://raw.githubusercontent.com/owner/repo/main/README.md",
            allowed_domains=["raw.githubusercontent.com"],
        )
        assert result.ok, result.reason
        assert result.host == "raw.githubusercontent.com"

    def test_subdomain_of_an_allowed_host_passes(self) -> None:
        # An allowlist entry names a domain, and its subdomains are the same
        # operator. Refusing `api.groq.com` because only `groq.com` is listed
        # would make the allowlist useless.
        result = check_url("https://api.groq.com/openai/v1", allowed_domains=["groq.com"])
        assert result.ok, result.reason
        assert result.host == "api.groq.com"

    def test_a_lookalike_suffix_is_refused(self) -> None:
        # `notgroq.com` must not pass just because it ends with `groq.com`.
        # A naive `host.endswith(entry)` check gets this wrong.
        assert refusal("https://notgroq.com/", allowed_domains=["groq.com"])

    def test_none_allowlist_means_no_restriction(self) -> None:
        # `None` is "this source is not domain-scoped" (the exporter checking
        # stored links); an empty list is a different thing -- see below.
        result = check_url("https://example.com/x", allowed_domains=None)
        assert result.ok, result.reason


class TestDnsProxyRanges:
    """Clash/Surge style DNS proxies answer with fake-IP addresses in
    198.18.0.0/15. Those look private to a naive guard, which would break
    collection for anyone behind such a proxy. The escape hatch is opt-in and
    must default to off.
    """

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FA_RADAR_ALLOW_DNS_PROXY", raising=False)
        assert dns_proxy_allowed() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_opt_in_requires_an_affirmative_value(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("FA_RADAR_ALLOW_DNS_PROXY", value)
        assert dns_proxy_allowed() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
    def test_falsey_values_do_not_opt_in(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        # A set-but-falsey value must not enable the escape hatch. This is the
        # case a `bool(os.environ.get(...))` gets wrong: `"0"` is truthy.
        monkeypatch.setenv("FA_RADAR_ALLOW_DNS_PROXY", value)
        assert dns_proxy_allowed() is False

    def test_fake_ip_is_blocked_without_the_opt_in(self) -> None:
        assert refusal("http://198.18.0.5/")

    def test_fake_ip_is_allowed_with_the_opt_in(self) -> None:
        # The literal host check must honour the opt-in, otherwise a source
        # written with a fake-IP URL could never be collected.
        result = check_url("http://198.18.0.5/", allowed_domains=None)
        assert not result.ok, "the literal check stays strict by design"
        # The resolved check is where the opt-in applies, since that is where
        # addresses are inspected with the environment flag.
        resolved = check_url_resolved(
            "http://public.example.com/",
            resolver=lambda host, port: [(2, 1, 6, "", ("198.18.0.5", 0))],
            allow_dns_proxy=True,
        )
        assert resolved.ok, resolved.reason


class TestResolvedAddresses:
    """The DNS check is what defeats a public hostname pointed at a private
    address, which is the actual attack this guard exists to stop."""

    def test_public_host_resolving_to_loopback_is_refused(self) -> None:
        result = check_url_resolved(
            "https://innocent.example.com/",
            resolver=lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))],
            allow_dns_proxy=False,
        )
        assert not result.ok
        assert "blocked address" in result.reason

    def test_public_host_resolving_to_rfc1918_is_refused(self) -> None:
        result = check_url_resolved(
            "https://innocent.example.com/",
            resolver=lambda host, port: [(2, 1, 6, "", ("10.1.2.3", 0))],
            allow_dns_proxy=False,
        )
        assert not result.ok

    def test_one_bad_address_among_several_is_enough_to_refuse(self) -> None:
        # A host with both a public and a private A record must be refused:
        # the fetch could land on either.
        result = check_url_resolved(
            "https://mixed.example.com/",
            resolver=lambda host, port: [
                (2, 1, 6, "", ("93.184.216.34", 0)),
                (2, 1, 6, "", ("192.168.0.9", 0)),
            ],
            allow_dns_proxy=False,
        )
        assert not result.ok

    def test_public_host_resolving_to_a_public_address_passes(self) -> None:
        result = check_url_resolved(
            "https://public.example.com/",
            resolver=lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
            allow_dns_proxy=False,
        )
        assert result.ok, result.reason

    def test_dns_failure_is_a_refusal_not_a_crash(self) -> None:
        import socket

        def failing(host, port):
            raise socket.gaierror("name not known")

        result = check_url_resolved(
            "https://missing.example.com/",
            resolver=failing,
            allow_dns_proxy=False,
        )
        assert not result.ok
        assert "DNS resolution failed" in result.reason

    def test_a_literal_private_host_never_reaches_the_resolver(self) -> None:
        # The cheap check runs first and short-circuits, so a private literal
        # host is refused without a DNS lookup happening at all.
        calls: list[str] = []

        def recording(host, port):
            calls.append(host)
            return [(2, 1, 6, "", ("93.184.216.34", 0))]

        result = check_url_resolved("http://10.0.0.1/", resolver=recording)
        assert not result.ok
        assert calls == [], "resolver must not be called for a blocked literal host"


class TestEvidenceLinks:
    """Evidence links are rendered, never fetched. Checking the scheme stops
    `javascript:` and `data:` reaching an anchor; blocking private hosts here
    would be wrong, because a maintainer's own notes may legitimately live on a
    LAN address."""

    def test_evidence_link_must_be_http_or_https(self) -> None:
        assert not check_evidence_link("javascript:alert(1)").ok
        assert not check_evidence_link("data:text/html,<script>alert(1)</script>").ok
        assert check_evidence_link("https://api.groq.com/pricing").ok

    def test_evidence_link_allows_a_private_host(self) -> None:
        result = check_evidence_link("https://192.168.0.10/notes")
        assert result.ok, result.reason

    def test_evidence_link_requires_a_host(self) -> None:
        assert not check_evidence_link("https:///nohost").ok


class TestTrackingParamStripping:
    def test_removes_known_trackers(self) -> None:
        cleaned = strip_tracking_params(
            "https://example.com/p?utm_source=x&utm_medium=y&id=42&fbclid=z"
        )
        assert "utm_source" not in cleaned
        assert "utm_medium" not in cleaned
        assert "fbclid" not in cleaned
        # Real parameters must survive: they can change what the page says.
        assert "id=42" in cleaned

    def test_keeps_a_url_without_trackers_unchanged(self) -> None:
        url = "https://example.com/pricing?plan=free"
        assert strip_tracking_params(url) == url

    def test_keeps_fragment_and_path(self) -> None:
        cleaned = strip_tracking_params("https://example.com/docs/page?utm_source=n#section-3")
        assert cleaned.endswith("#section-3")
        assert "/docs/page" in cleaned

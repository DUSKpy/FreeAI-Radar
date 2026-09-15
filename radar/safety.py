"""URL and content safety guards.

Fetched pages are treated as untrusted input throughout. This module is the
single place that decides whether a URL may be requested at all.

Runtime checks (applied to every real request):

* scheme must be http or https
* host must resolve to a public address
* private, loopback, link-local, reserved, multicast and cloud-metadata
  addresses are refused
* redirects are re-validated hop by hop

Tests inject ``httpx.MockTransport`` and therefore never open a socket, but the
production guards stay switched on -- the task book forbids disabling them for
the convenience of fixtures.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Cloud instance metadata endpoints. Never reachable from a collector.
METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)

#: Link-local / special-purpose ranges that must never be contacted.
_BLOCKED_V4 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
)

#: Ranges used by local DNS proxies for fake-IP mode (Clash, Surge, sing-box
#: and similar tools map every hostname into a reserved range and proxy the
#: connection themselves). On a machine configured that way, refusing these
#: addresses would block every public source.
#:
#: ``FA_RADAR_ALLOW_DNS_PROXY=1`` accepts exactly these two ranges, and nothing
#: else -- private, loopback, link-local and cloud-metadata addresses stay
#: blocked either way. The task book requires the guards to remain in force
#: for fixtures; this flag exists for real collection on a proxied machine and
#: is never enabled in the test suite.
DNS_PROXY_RANGES_V4 = (
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.19.0.0/16"),
)
DNS_PROXY_RANGES_V6 = (ipaddress.ip_network("fdfe:dcba:9876::/48"),)

DNS_PROXY_ENV = "FA_RADAR_ALLOW_DNS_PROXY"


def dns_proxy_allowed() -> bool:
    """Whether the operator has opted into accepting local DNS proxy ranges."""
    import os

    return os.environ.get(DNS_PROXY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


_BLOCKED_V6 = (
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("64:ff9b::/96"),
)


class UnsafeUrlError(ValueError):
    """Raised when a URL may not be fetched. Never swallowed silently."""


@dataclass(frozen=True)
class UrlCheck:
    ok: bool
    reason: str = ""
    scheme: str = ""
    host: str = ""

    def require(self) -> None:
        if not self.ok:
            raise UnsafeUrlError(self.reason)


def _is_blocked_address(raw: str, *, allow_dns_proxy: bool = False) -> bool:
    """Whether an address is off limits.

    ``allow_dns_proxy`` narrows the block list by exactly the fake-IP ranges a
    local DNS proxy uses. Everything genuinely dangerous -- loopback, private
    RFC1918, link-local, cloud metadata, multicast, reserved -- stays blocked.
    """
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False

    if allow_dns_proxy and _is_dns_proxy_range(address):
        return False

    if address.version == 4:
        return any(address in net for net in _BLOCKED_V4)
    if address.is_loopback or address.is_link_local:
        return True
    return any(address in net for net in _BLOCKED_V6)


def _is_dns_proxy_range(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.version == 4:
        return any(address in net for net in DNS_PROXY_RANGES_V4)
    return any(address in net for net in DNS_PROXY_RANGES_V6)


def check_url(url: str, *, allowed_domains: Iterable[str] | None = None) -> UrlCheck:
    """Validate scheme and literal host without performing DNS.

    Use :func:`check_url_resolved` for a full check that also inspects the
    resolved addresses. Keeping the two separate lets the build-time exporter
    validate stored links cheaply while collectors do the expensive check.
    """
    parts = urlsplit((url or "").strip())

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return UrlCheck(False, f"scheme not allowed: {parts.scheme or '(none)'}")

    host = (parts.hostname or "").lower()
    if not host:
        return UrlCheck(False, "missing host", parts.scheme, "")

    if host in METADATA_HOSTS:
        return UrlCheck(False, f"cloud metadata host refused: {host}", parts.scheme, host)

    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return UrlCheck(False, f"loopback host refused: {host}", parts.scheme, host)

    if host.endswith(".internal") or host.endswith(".local"):
        return UrlCheck(False, f"internal host refused: {host}", parts.scheme, host)

    if _is_blocked_address(host):
        return UrlCheck(False, f"private/reserved address refused: {host}", parts.scheme, host)

    if allowed_domains:
        allowlist = {d.lower().lstrip(".") for d in allowed_domains}
        if allowlist and not any(
            host == entry or host.endswith("." + entry) for entry in allowlist
        ):
            return UrlCheck(
                False,
                f"host {host} outside allowed_domains {sorted(allowlist)}",
                parts.scheme,
                host,
            )

    return UrlCheck(True, "", parts.scheme, host)


def check_url_resolved(
    url: str,
    *,
    allowed_domains: Iterable[str] | None = None,
    resolver: object | None = None,
    allow_dns_proxy: bool | None = None,
) -> UrlCheck:
    """Full check including DNS resolution and every returned address.

    ``resolver`` may be replaced in tests to avoid touching the network.
    ``allow_dns_proxy`` defaults to the environment opt-in described above.
    """
    basic = check_url(url, allowed_domains=allowed_domains)
    if not basic.ok:
        return basic

    if allow_dns_proxy is None:
        allow_dns_proxy = dns_proxy_allowed()

    lookup = resolver or socket.getaddrinfo
    try:
        infos = lookup(basic.host, None)  # type: ignore[operator]
    except (socket.gaierror, OSError) as exc:
        return UrlCheck(
            False, f"DNS resolution failed for {basic.host}: {exc}", basic.scheme, basic.host
        )

    seen: set[str] = set()
    for info in infos:  # type: ignore[union-attr]
        try:
            address = info[4][0]
        except (IndexError, TypeError):
            continue
        if address in seen:
            continue
        seen.add(address)
        if _is_blocked_address(address, allow_dns_proxy=allow_dns_proxy):
            return UrlCheck(
                False,
                f"host {basic.host} resolves to blocked address {address}",
                basic.scheme,
                basic.host,
            )
    return basic


def check_evidence_link(url: str) -> UrlCheck:
    """Evidence links shown in the UI get the cheap check.

    Scheme must be http/https so that ``javascript:`` and ``data:`` cannot be
    smuggled into an anchor, but internal hosts are allowed here because the
    link is only rendered, never requested by the site.
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return UrlCheck(False, f"evidence scheme not allowed: {parts.scheme or '(none)'}")
    if not parts.hostname:
        return UrlCheck(False, "evidence link missing host", parts.scheme, "")
    return UrlCheck(True, "", parts.scheme, parts.hostname.lower())


def strip_tracking_params(url: str) -> str:
    """Remove campaign and referral parameters left over from source pages."""
    from urllib.parse import parse_qsl, urlencode, urlunsplit

    tracking = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "referrer",
        "ref_src",
        "ref_url",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "aff_id",
        "affiliate",
        "via",
        "spm",
        "from",
    }
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in tracking
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))

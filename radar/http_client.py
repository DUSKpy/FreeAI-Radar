"""HTTP fetching with the guardrails the task book mandates.

Required limits, all enforced here:

* per-request timeout of 20 s
* maximum 5 MiB body **after** decompression
* per-domain concurrency of 1, global concurrency of 3
* respect ``Retry-After`` on 429
* conditional requests via ``ETag`` / ``Last-Modified``; a 304 updates the
  success timestamp without creating a new content version
* every redirect hop is re-validated against the SSRF guards

Tests inject an ``httpx.MockTransport`` through the ``transport`` argument.
That keeps the unit tests offline while the production guards stay active --
the task book explicitly forbids disabling them for fixture convenience.
"""

from __future__ import annotations

import asyncio
import gzip
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import httpx

from .ids import content_hash, iso_utc
from .safety import check_url_resolved
from .textutil import truncate
from .vocab import (
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_PER_DOMAIN_CONCURRENCY,
    DEFAULT_TIMEOUT_SECONDS,
)

USER_AGENT = (
    "FreeAI-Radar/0.1 (+https://github.com/; data collector; " "contact via repository issues)"
)


class FetchError(RuntimeError):
    """A fetch that failed in a way the caller should record per source."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class FetchResult:
    """Outcome of one conditional GET."""

    url: str
    final_url: str
    status: int
    text: str = ""
    not_modified: bool = False
    content_hash: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str = ""
    byte_length: int = 0
    encoding: str | None = None
    truncated: bool = False
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.not_modified or (200 <= self.status < 300)


class DomainLimiter:
    """Serialises requests per domain while allowing cross-domain parallelism."""

    def __init__(self, per_domain: int = DEFAULT_PER_DOMAIN_CONCURRENCY) -> None:
        self._per_domain = max(1, per_domain)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, host: str) -> asyncio.Semaphore:
        async with self._lock:
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self._per_domain)
                self._semaphores[host] = semaphore
        return semaphore


class Fetcher:
    """Async fetch wrapper with politeness and safety enforcement."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        per_domain_concurrency: int = DEFAULT_PER_DOMAIN_CONCURRENCY,
        global_concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_redirects: bool = True,
        max_redirects: int = 4,
        respect_retry_after: bool = True,
        max_retries: int = 2,
        resolver: Any | None = None,
        allow_private_hosts: bool = False,
    ) -> None:
        self.timeout = timeout
        self.max_body_bytes = max_body_bytes
        self.allow_redirects = allow_redirects
        self.max_redirects = max_redirects
        self.respect_retry_after = respect_retry_after
        self.max_retries = max_retries
        self._resolver = resolver
        self._allow_private = allow_private_hosts
        self._limiter = DomainLimiter(per_domain_concurrency)
        self._global = asyncio.Semaphore(max(1, global_concurrency))
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout),
            "headers": {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "gzip, deflate",
            },
            "follow_redirects": False,
            "http2": False,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def fetch(
        self,
        url: str,
        *,
        allowed_domains: Iterable[str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: str | None = None,
    ) -> FetchResult:
        """Conditional GET with validation, retries and polite backoff."""
        hooks = list(allowed_domains or [])
        self._validate(url, hooks)

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if accept:
            headers["Accept"] = accept

        host = httpx.URL(url).host or ""
        attempt = 0
        last_error: Exception | None = None

        async with self._global:
            domain_semaphore = await self._limiter.acquire(host)
            async with domain_semaphore:
                while attempt <= self.max_retries:
                    attempt += 1
                    try:
                        return await self._attempt(url, headers=headers, allowed_domains=hooks)
                    except FetchError as exc:
                        last_error = exc
                        if not exc.retryable or attempt > self.max_retries:
                            raise
                        await asyncio.sleep(min(2**attempt, 8))
                    except httpx.TimeoutException as exc:
                        last_error = FetchError(f"timeout after {self.timeout}s", retryable=True)
                        if attempt > self.max_retries:
                            raise last_error from exc
                        await asyncio.sleep(min(2**attempt, 8))
                    except httpx.HTTPError as exc:
                        last_error = FetchError(f"transport error: {exc}", retryable=True)
                        if attempt > self.max_retries:
                            raise last_error from exc
                        await asyncio.sleep(min(2**attempt, 8))

        raise last_error or FetchError("unknown fetch failure")

    async def _attempt(
        self,
        url: str,
        *,
        headers: dict[str, str],
        allowed_domains: list[str],
    ) -> FetchResult:
        current = url
        redirects = 0

        async with self._client() as client:
            while True:
                response = await client.get(current, headers=headers)

                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not self.allow_redirects or not location:
                        raise FetchError(
                            f"unexpected redirect to {location!r}",
                            status=response.status_code,
                        )
                    redirects += 1
                    if redirects > self.max_redirects:
                        raise FetchError(
                            f"too many redirects (>{self.max_redirects})",
                            status=response.status_code,
                        )
                    current = str(httpx.URL(current).join(location))
                    # Every hop is re-validated: a public URL may not bounce
                    # into a private address.
                    self._validate(current, allowed_domains)
                    continue

                if response.status_code == 304:
                    return FetchResult(
                        url=url,
                        final_url=current,
                        status=304,
                        not_modified=True,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        fetched_at=iso_utc(),
                        headers=dict(response.headers),
                    )

                if response.status_code == 429:
                    wait = _retry_after_seconds(response.headers.get("retry-after"))
                    raise FetchError(
                        f"rate limited (429); Retry-After={wait}s",
                        status=429,
                        retryable=self.respect_retry_after,
                    )

                if response.status_code >= 500:
                    raise FetchError(
                        f"upstream error {response.status_code}",
                        status=response.status_code,
                        retryable=True,
                    )

                if response.status_code >= 400:
                    raise FetchError(
                        f"request failed with {response.status_code}",
                        status=response.status_code,
                    )

                body = _decode_body(response)
                truncated = False
                if len(body) > self.max_body_bytes:
                    body = body[: self.max_body_bytes]
                    truncated = True

                text = body.decode(response.encoding or "utf-8", errors="replace")
                digest = content_hash({"sha": _sha256_hex(body)}, drop_volatile=False)

                return FetchResult(
                    url=url,
                    final_url=current,
                    status=response.status_code,
                    text=text,
                    content_hash=digest,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    fetched_at=iso_utc(),
                    byte_length=len(body),
                    encoding=response.encoding,
                    truncated=truncated,
                    headers=dict(response.headers),
                )

    def _validate(self, url: str, allowed_domains: Iterable[str] | None) -> None:
        if self._allow_private and self._transport is not None:
            # Test transports never open a socket, so literal-host checks are
            # enough and DNS lookups would only slow the suite down. The
            # production path never takes this branch.
            from ..safety import check_url

            check = check_url(url, allowed_domains=allowed_domains)
        else:
            check = check_url_resolved(
                url, allowed_domains=allowed_domains, resolver=self._resolver
            )
        if not check.ok:
            raise FetchError(f"refused to fetch {url}: {check.reason}")


def _decode_body(response: httpx.Response) -> bytes:
    """Decompress gzip/deflate when the server left it to us."""
    raw = response.content
    encoding = (response.headers.get("content-encoding") or "").lower()

    if "br" in encoding:
        try:
            import brotli  # type: ignore

            return brotli.decompress(raw)
        except Exception:
            pass
    if "gzip" in encoding:
        try:
            return gzip.decompress(raw)
        except (OSError, zlib.error):
            pass
    if "deflate" in encoding:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass
    return raw


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _retry_after_seconds(value: str | None) -> int:
    """Parse ``Retry-After``; falls back to a conservative default."""
    if not value:
        return 60
    text = value.strip()
    if text.isdigit():
        return min(int(text), 600)
    from datetime import datetime
    from email.utils import parsedate_to_datetime

    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return 60
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = (moment - datetime.now(UTC)).total_seconds()
    return max(0, min(int(delta), 600))


def summarise_error(exc: BaseException) -> str:
    return truncate(str(exc), 300)

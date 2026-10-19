"""Guarded fetch with a pinned transport — an SSRF-safe GET for caller-supplied URLs.

Fetching a URL that someone else handed you is a server-side request forgery hole: the
URL can point at ``localhost``, at a private network, or at cloud metadata
(``169.254.169.254``). The usual guard — resolve the host, check the addresses, then let
an HTTP client connect — has two gaps:

- **DNS rebinding.** The client resolves the host *again* when it connects, and an
  attacker's DNS answers "public" to the check and ``127.0.0.1`` to the connect.
- **Redirects.** A public URL answers ``302 Location: http://169.254.169.254/``, and a
  client that follows redirects by itself never shows the hop to the guard.

This module closes both by owning the transport. Each hop's host is resolved **once**,
**every** resolved address is checked, and the socket is opened to exactly the address
that was checked — while the request still carries the original ``Host`` header and the
TLS handshake still sends the original name (SNI) and verifies the certificate against
it. Redirects are never followed by a library; each ``Location`` goes back through the
same check.

>>> body = guarded_fetch('https://example.com/data.json')  # doctest: +SKIP
>>> guarded_fetch('http://169.254.169.254/latest/meta-data/')
Traceback (most recent call last):
    ...
graze.guarded.UnsafeTarget: refusing http://169.254.169.254/latest/meta-data/: address 169.254.169.254 is not allowed
>>> guarded_fetch('file:///etc/passwd')
Traceback (most recent call last):
    ...
graze.guarded.UnsafeTarget: refusing file:///etc/passwd: scheme 'file' is not allowed (allowed: https, http)

:func:`guarded_fetch` returns the body as bytes. :func:`guarded_open` returns a
:class:`GuardedResponse` to stream from (``iter_chunks``) when the body is large, and
exposes the final URL, the status, the headers, and the address actually connected to.

The seams, all keyword-only:

- ``is_allowed_address`` — the address policy. :func:`default_public_only` by default;
  pass an allow-list for tests or for a self-hosted deployment that must reach a LAN host.
- ``resolver`` — host name to addresses. :func:`system_resolver` (``getaddrinfo``) by
  default; a fake one makes rebinding testable offline.
- ``connector`` and ``ssl_context`` — how the pinned socket is opened and wrapped.

Like :mod:`graze.share_links` and :mod:`graze.content_kind`, this module uses the
standard library only (``http.client``, ``ssl``, ``socket``, ``ipaddress``). It reads no
proxy settings from the environment, on purpose: a proxy would resolve the host itself,
and the pin would be meaningless.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Mapping, Optional
from urllib.parse import urljoin, urlsplit

__all__ = [
    "GuardedFetchError",
    "UnsafeTarget",
    "FetchLimitExceeded",
    "FetchFailed",
    "HTTPStatusError",
    "GuardedResponse",
    "guarded_fetch",
    "guarded_open",
    "default_public_only",
    "system_resolver",
    "DFLT_ALLOWED_SCHEMES",
    "DFLT_ALLOWED_PORTS",
    "DFLT_MAX_REDIRECTS",
    "DFLT_TIMEOUT_S",
    "DFLT_MAX_BYTES",
    "DFLT_CHUNK_SIZE",
]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressPolicy = Callable[[IPAddress], bool]
Resolver = Callable[[str, int], Iterable[str]]
Connector = Callable[[tuple, float], socket.socket]

DFLT_ALLOWED_SCHEMES = ("https", "http")
#: Ports a fetch may target. ``None`` (passed as ``allow_ports``) allows any port.
DFLT_ALLOWED_PORTS = (443, 80)
DFLT_MAX_REDIRECTS = 5
#: Wall-clock budget for the whole fetch, redirects and body included, in seconds.
DFLT_TIMEOUT_S = 30.0
DFLT_MAX_BYTES = 50 * 1024 * 1024
DFLT_CHUNK_SIZE = 64 * 1024

_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
#: Request headers that must not follow a redirect to a different origin.
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})
#: IPv6 prefixes that embed an IPv4 address a gateway may translate to (RFC 6052 NAT64,
#: and the deprecated IPv4-compatible ``::a.b.c.d``). ``ipaddress`` calls some of these
#: global, so the embedded address is checked as well.
_IPV4_EMBEDDING_PREFIXES = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("::/96"),
)


class GuardedFetchError(Exception):
    """Base class of everything :func:`guarded_fetch` raises on purpose."""


class UnsafeTarget(GuardedFetchError, ValueError):
    """The URL, or a redirect hop of it, points somewhere a fetch must not go."""


class FetchLimitExceeded(GuardedFetchError):
    """The fetch ran over its byte, time, or redirect budget."""


class FetchFailed(GuardedFetchError, OSError):
    """The target was allowed but the network part failed (refused, reset, TLS...)."""


class HTTPStatusError(GuardedFetchError):
    """The server answered with an error status (4xx or 5xx)."""

    def __init__(self, message: str, *, status: int, url: str):
        super().__init__(message)
        self.status = status
        self.url = url


# --------------------------------------------------------------------------------------
# Address policy and resolution


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    """The IPv4 address an IPv6 address stands for, if it is one of the embedding forms."""
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]  # the client address
    if any(ip in prefix for prefix in _IPV4_EMBEDDING_PREFIXES):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def default_public_only(ip: IPAddress) -> bool:
    """True iff ``ip`` is a globally routable unicast address.

    Refuses loopback, private, link-local (cloud metadata lives there), carrier-grade
    NAT, reserved, unspecified and multicast addresses. An IPv6 address that embeds an
    IPv4 one (``::ffff:127.0.0.1``, 6to4, Teredo, NAT64) is judged by the embedded
    address too — explicitly, because ``ipaddress`` only learned to look through
    IPv4-mapped addresses in CPython 3.10.14 / 3.11.9 / 3.12.3 (CVE-2024-4032).

    >>> default_public_only(ipaddress.ip_address('93.184.216.34'))
    True
    >>> [default_public_only(ipaddress.ip_address(a)) for a in
    ...  ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1')]
    [False, False, False, False, False]
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:  # it *is* the IPv4 address, on the wire
            return default_public_only(ip.ipv4_mapped)
        embedded = _embedded_ipv4(ip)
        if embedded is not None and not default_public_only(embedded):
            return False
    return ip.is_global and not ip.is_multicast


def system_resolver(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to, via the system's ``getaddrinfo``."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _parse_address(raw: str) -> IPAddress:
    # A scoped IPv6 address ('fe80::1%eth0') keeps its zone; ipaddress accepts it.
    return ipaddress.ip_address(raw)


def _resolve_and_check(
    url: str,
    host: str,
    port: int,
    *,
    resolver: Resolver,
    is_allowed_address: AddressPolicy,
) -> list[IPAddress]:
    """Resolve ``host`` once and return its addresses, all of which passed the policy.

    One disallowed address refuses the whole host: a name answering both a public and
    a private address is exactly what a rebinding attack looks like.
    """
    try:
        addresses = [_parse_address(host)]  # an IP literal needs no resolution
    except ValueError:
        try:
            raw_addresses = list(resolver(host, port))
        except (OSError, UnicodeError) as e:
            raise FetchFailed(f"cannot resolve host {host!r} of {url}: {e}") from e
        if not raw_addresses:
            raise FetchFailed(f"host {host!r} of {url} resolved to no address")
        try:
            addresses = [_parse_address(str(a)) for a in raw_addresses]
        except ValueError as e:
            raise UnsafeTarget(f"refusing {url}: resolver returned {e}") from e
    for address in addresses:
        if not is_allowed_address(address):
            raise UnsafeTarget(f"refusing {url}: address {address} is not allowed")
    return addresses


# --------------------------------------------------------------------------------------
# The pinned transport


def _pinned_connection(
    scheme: str,
    host: str,
    port: int,
    addresses: list[IPAddress],
    *,
    timeout: float,
    connector: Connector,
    ssl_context: Optional[ssl.SSLContext],
) -> http.client.HTTPConnection:
    """An ``http.client`` connection to ``host`` that dials only the checked addresses.

    ``host`` stays the connection's host, so ``http.client`` writes it in the ``Host``
    header and TLS uses it for SNI and certificate verification. Only the socket is
    pinned: it is opened to the first of ``addresses`` that accepts it, which is then
    recorded as the connection's ``pinned_address``.
    """

    def open_pinned_socket(connection) -> socket.socket:
        last_error: Optional[OSError] = None
        for address in addresses:
            try:
                sock = connector((str(address), port), timeout)
            except OSError as e:
                last_error = e
                continue
            connection.pinned_address = str(address)
            return sock
        raise FetchFailed(f"cannot connect to {host}:{port}: {last_error}")

    if scheme == "https":
        context = ssl_context or ssl.create_default_context()

        class _PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                self.sock = context.wrap_socket(
                    open_pinned_socket(self), server_hostname=self.host
                )

        return _PinnedHTTPS(host, port, timeout=timeout, context=context)

    class _PinnedHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = open_pinned_socket(self)

    return _PinnedHTTP(host, port, timeout=timeout)


def _default_connector(address: tuple, timeout: float) -> socket.socket:
    return socket.create_connection(address, timeout=timeout)


# --------------------------------------------------------------------------------------
# The response


@dataclass
class GuardedResponse:
    """An open response from :func:`guarded_open`, with its budgets still enforced.

    Use it as a context manager, and read it with :meth:`iter_chunks` (streaming) or
    :meth:`read` (everything). Reading past ``max_bytes`` or past the deadline raises
    :class:`FetchLimitExceeded`.
    """

    url: str  #: the final URL, after redirects
    status: int
    reason: str
    headers: http.client.HTTPMessage
    address: str  #: the IP the socket was actually connected to
    max_bytes: int
    deadline: float  #: a ``time.monotonic()`` value
    _response: http.client.HTTPResponse = field(repr=False)
    _connection: http.client.HTTPConnection = field(repr=False)
    _bytes_read: int = field(default=0, repr=False)

    def iter_chunks(self, chunk_size: int = DFLT_CHUNK_SIZE) -> Iterator[bytes]:
        """Yield the body in chunks of at most ``chunk_size`` bytes, within budget."""
        while True:
            remaining_s = self.deadline - time.monotonic()
            if remaining_s <= 0:
                raise FetchLimitExceeded(
                    f"fetching {self.url} ran over its time budget"
                )
            if self._connection.sock is not None:
                self._connection.sock.settimeout(remaining_s)
            try:
                chunk = self._response.read(chunk_size)
            except TimeoutError as e:
                raise FetchLimitExceeded(
                    f"fetching {self.url} ran over its time budget"
                ) from e
            except (OSError, http.client.HTTPException) as e:
                raise FetchFailed(f"reading {self.url} failed: {e}") from e
            if not chunk:
                return
            self._bytes_read += len(chunk)
            if self._bytes_read > self.max_bytes:
                raise FetchLimitExceeded(
                    f"{self.url} is larger than the {self.max_bytes}-byte limit"
                )
            yield chunk

    def read(self) -> bytes:
        """The whole (remaining) body."""
        return b"".join(self.iter_chunks())

    def close(self) -> None:
        self._response.close()
        self._connection.close()

    def __enter__(self) -> GuardedResponse:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# --------------------------------------------------------------------------------------
# The fetch


def _check_url(url: str, *, allow_schemes, allow_ports) -> tuple[str, str, int, str]:
    """``(scheme, host, port, path_and_query)`` of ``url``, or :class:`UnsafeTarget`."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UnsafeTarget(f"refusing {url}: {e}") from e
    scheme = parts.scheme.lower()
    if scheme not in allow_schemes or scheme not in _DEFAULT_PORTS:
        raise UnsafeTarget(
            f"refusing {url}: scheme {scheme!r} is not allowed "
            f"(allowed: {', '.join(allow_schemes)})"
        )
    host = parts.hostname
    if not host:
        raise UnsafeTarget(f"refusing {url}: no host")
    port = port or _DEFAULT_PORTS[scheme]
    if allow_ports is not None and port not in allow_ports:
        raise UnsafeTarget(f"refusing {url}: port {port} is not allowed")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return scheme, host, port, path


def _origin(url: str) -> tuple:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, parts.hostname, parts.port or _DEFAULT_PORTS.get(scheme)


def guarded_open(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[bytes] = None,
    allow_schemes: Iterable[str] = DFLT_ALLOWED_SCHEMES,
    allow_ports: Optional[Iterable[int]] = DFLT_ALLOWED_PORTS,
    max_redirects: int = DFLT_MAX_REDIRECTS,
    timeout: float = DFLT_TIMEOUT_S,
    max_bytes: int = DFLT_MAX_BYTES,
    is_allowed_address: AddressPolicy = default_public_only,
    resolver: Resolver = system_resolver,
    connector: Connector = _default_connector,
    ssl_context: Optional[ssl.SSLContext] = None,
    raise_for_status: bool = True,
) -> GuardedResponse:
    """Open ``url`` through the guard and return the response, body not yet read.

    Every hop — the URL and each redirect — is checked: scheme in ``allow_schemes``,
    port in ``allow_ports`` (``None`` allows any), host resolved once by ``resolver``,
    every address accepted by ``is_allowed_address``, and the socket opened to one of
    exactly those addresses. ``timeout`` is a wall-clock budget for the whole fetch,
    including reading the body; ``max_bytes`` caps the body.

    Redirects follow browser rules (303, and 301/302 after a POST, become a GET without
    a body), and ``Authorization`` / ``Cookie`` headers are dropped when a redirect
    leaves the original origin.
    """
    allow_schemes = tuple(s.lower() for s in allow_schemes)
    allow_ports = None if allow_ports is None else frozenset(allow_ports)
    deadline = time.monotonic() + timeout
    request_headers = {"Accept-Encoding": "identity", **dict(headers or {})}
    original_origin = _origin(url)
    current = url

    for _ in range(max_redirects + 1):
        scheme, host, port, path = _check_url(
            current, allow_schemes=allow_schemes, allow_ports=allow_ports
        )
        addresses = _resolve_and_check(
            current,
            host,
            port,
            resolver=resolver,
            is_allowed_address=is_allowed_address,
        )
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            raise FetchLimitExceeded(f"fetching {url} ran over its time budget")
        connection = _pinned_connection(
            scheme,
            host,
            port,
            addresses,
            timeout=remaining_s,
            connector=connector,
            ssl_context=ssl_context,
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
        except GuardedFetchError:
            connection.close()
            raise
        except TimeoutError as e:
            connection.close()
            raise FetchLimitExceeded(f"fetching {url} ran over its time budget") from e
        except (OSError, http.client.HTTPException) as e:
            connection.close()
            raise FetchFailed(f"fetching {current} failed: {e}") from e

        if response.status in _REDIRECT_STATUSES:
            location = response.getheader("Location")
            response.close()
            connection.close()
            if not location:
                raise FetchFailed(f"{current} redirected without a Location")
            current = urljoin(current, location).split("#", 1)[0]
            if response.status == 303 or (
                response.status in (301, 302) and method.upper() == "POST"
            ):
                method, body = "GET", None
            if _origin(current) != original_origin:
                request_headers = {
                    k: v
                    for k, v in request_headers.items()
                    if k.lower() not in _CREDENTIAL_HEADERS
                }
            continue

        guarded = GuardedResponse(
            url=current,
            status=response.status,
            reason=response.reason,
            headers=response.headers,
            address=connection.pinned_address,
            max_bytes=max_bytes,
            deadline=deadline,
            _response=response,
            _connection=connection,
        )
        try:
            if raise_for_status and response.status >= 400:
                raise HTTPStatusError(
                    f"{current} answered HTTP {response.status} {response.reason}",
                    status=response.status,
                    url=current,
                )
            declared_length = response.getheader("Content-Length")
            if declared_length and declared_length.isdigit():
                if int(declared_length) > max_bytes:
                    raise FetchLimitExceeded(
                        f"{current} declares {declared_length} bytes, over the "
                        f"{max_bytes}-byte limit"
                    )
        except GuardedFetchError:
            guarded.close()
            raise
        return guarded

    raise FetchLimitExceeded(f"{url} redirected more than {max_redirects} times")


def guarded_fetch(url: str, **kwargs) -> bytes:
    """The body of ``url`` as bytes, fetched through the guard.

    Takes the same keyword arguments as :func:`guarded_open`, which is the one to use
    for a large body (stream it with ``iter_chunks``) or to see the final URL, status
    and headers.
    """
    with guarded_open(url, **kwargs) as response:
        return response.read()

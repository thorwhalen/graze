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

``timeout`` is a **wall-clock** budget for the whole fetch — resolution, connection, TLS
handshake, redirects, headers and body. A per-read socket timeout alone is not one: a
server trickling a byte just inside it can hold a worker for as long as it likes. So on
top of the socket timeouts, a watchdog shuts the socket down when the budget runs out.

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
import inspect
import ipaddress
import socket
import ssl
import threading
import time
import math
import queue
import re
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
    "check_target",
    "default_public_only",
    "system_resolver",
    "DFLT_ALLOWED_SCHEMES",
    "DFLT_ALLOWED_PORTS",
    "DFLT_MAX_REDIRECTS",
    "DFLT_TIMEOUT_S",
    "DFLT_MAX_BYTES",
    "DFLT_CHUNK_SIZE",
    "CROSS_ORIGIN_SAFE_HEADERS",
]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressPolicy = Callable[[IPAddress], bool]
Resolver = Callable[[str, int], Iterable[str]]
#: ``(address, timeout) -> socket``; ``timeout`` is what is left of the budget.
Connector = Callable[[tuple, float], socket.socket]

DFLT_ALLOWED_SCHEMES = ("https", "http")
#: Ports a fetch may target. ``None`` (passed as ``allow_ports``) allows any port.
DFLT_ALLOWED_PORTS = (443, 80)
DFLT_MAX_REDIRECTS = 5
#: Wall-clock budget for the whole fetch, redirects and body included, in seconds.
#: Raise it with ``max_bytes``: the defaults together assume about 1.7 MB/s.
DFLT_TIMEOUT_S = 30.0
DFLT_MAX_BYTES = 50 * 1024 * 1024
DFLT_CHUNK_SIZE = 64 * 1024
#: The only caller headers that follow a redirect to a different origin. Anything else
#: (``Authorization``, ``Cookie``, an ``X-Api-Key``...) was meant for the first origin.
CROSS_ORIGIN_SAFE_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "user-agent",
        "content-type",
        "range",  # so a resumed download survives a CDN redirect
        "if-range",
        "if-none-match",
        "if-modified-since",
    }
)

#: What parsers disagree on: backslashes, whitespace and controls (and userinfo, below).
#: ``urlsplit`` reads ``http://169.254.169.254\\@a.example/`` as host ``a.example``;
#: urllib3 reads it as the metadata address.
_AMBIGUOUS_URL = re.compile(r"[\\\s\x00-\x1f\x7f]")

_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
#: IPv6 prefixes that embed an IPv4 address a gateway may translate to: RFC 6052 NAT64,
#: SIIT's IPv4-translated ``::ffff:0:a.b.c.d``, and the deprecated IPv4-compatible
#: ``::a.b.c.d``. ``ipaddress`` calls some of these global, so the embedded address is
#: checked as well.
_IPV4_EMBEDDING_PREFIXES = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("::ffff:0:0:0/96"),
    ipaddress.IPv6Network("::/96"),
)
#: Ranges ``ipaddress`` reports as global that are not ordinary public unicast:
#: deprecated IPv6 site-local, and the deprecated 6to4 relay anycast.
_DENIED_NETWORKS = (
    ipaddress.IPv6Network("fec0::/10"),
    ipaddress.IPv4Network("192.88.99.0/24"),
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
    IPv4 one (``::ffff:127.0.0.1``, 6to4, Teredo, NAT64, SIIT) is judged by the embedded
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
    if any(ip in network for network in _DENIED_NETWORKS):
        return False
    return ip.is_global and not ip.is_multicast


def system_resolver(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to, via the system's ``getaddrinfo``."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _resolve_within(resolver: Resolver, host: str, port: int, *, deadline: float):
    """``resolver(host, port)``, given up on when the deadline passes.

    ``getaddrinfo`` takes no timeout, so it runs in a daemon thread that is abandoned
    (not killed — nothing can kill it) if it outlives the budget. A daemon, so an
    abandoned lookup cannot hold up interpreter exit either.
    """
    results: queue.Queue = queue.Queue(maxsize=1)

    def resolve():
        try:
            results.put((True, list(resolver(host, port))))
        except BaseException as e:  # handed to the caller, re-raised there
            results.put((False, e))

    threading.Thread(target=resolve, daemon=True).start()
    try:
        ok, value = results.get(timeout=max(0.0, deadline - time.monotonic()))
    except queue.Empty:
        raise TimeoutError(f"resolving {host!r} did not finish in time") from None
    if not ok:
        raise value
    return value


def _resolve_and_check(
    url: str,
    host: str,
    port: int,
    *,
    resolver: Resolver,
    is_allowed_address: AddressPolicy,
    deadline: float,
) -> list[IPAddress]:
    """Resolve ``host`` once and return its addresses, all of which passed the policy.

    One disallowed address refuses the whole host: a name answering both a public and
    a private address is exactly what a rebinding attack looks like.
    """
    try:
        addresses = [ipaddress.ip_address(host)]  # an IP literal needs no resolution
    except ValueError:
        try:
            raw_addresses = _resolve_within(resolver, host, port, deadline=deadline)
        except TimeoutError as e:
            raise FetchLimitExceeded(
                f"resolving {host!r} of {url} ran over the time budget"
            ) from e
        except (OSError, UnicodeError) as e:
            raise FetchFailed(f"cannot resolve host {host!r} of {url}: {e}") from e
        if not raw_addresses:
            raise FetchFailed(f"host {host!r} of {url} resolved to no address")
        try:
            # A scoped IPv6 address ('fe80::1%eth0') keeps its zone; ipaddress takes it.
            addresses = [ipaddress.ip_address(str(a)) for a in raw_addresses]
        except ValueError as e:
            raise UnsafeTarget(f"refusing {url}: resolver returned {e}") from e
    for address in addresses:
        if not is_allowed_address(address):
            raise UnsafeTarget(f"refusing {url}: address {address} is not allowed")
    return addresses


# --------------------------------------------------------------------------------------
# The wall-clock budget


class _Watchdog:
    """Shuts the current socket down when the deadline passes, unblocking any read.

    A socket timeout bounds one ``recv``; this bounds them all. Whoever then sees a
    failed or empty read asks :attr:`fired` to tell "out of time" from "server hung up".
    """

    def __init__(self, deadline: float):
        self.deadline = deadline
        self.fired = False
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._fire)
        self._timer.daemon = True
        self._timer.start()

    def watch(self, sock: socket.socket) -> socket.socket:
        with self._lock:
            self._sock = sock
            if self.fired:
                self._shutdown(sock)
        return sock

    def release(self) -> None:
        """Forget the current socket; call it before closing that socket.

        Shutting down and forgetting both happen under the lock, so the timer can never
        reach a closed socket's file descriptor after the OS has handed it to another.
        """
        with self._lock:
            self._sock = None

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def cancel(self) -> None:
        self._timer.cancel()
        self.release()

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            if self._sock is not None:
                self._shutdown(self._sock)

    @staticmethod
    def _shutdown(sock: socket.socket) -> None:
        try:
            # The base-class method, so an SSLSocket's TLS state is left alone: only the
            # file descriptor is shut, which is what a blocked read is waiting on.
            socket.socket.shutdown(sock, socket.SHUT_RDWR)
        except (OSError, TypeError):
            pass


# --------------------------------------------------------------------------------------
# The pinned transport


def _pinned_connection(
    scheme: str,
    host: str,
    port: int,
    addresses: list[IPAddress],
    *,
    watchdog: _Watchdog,
    connector: Connector,
    ssl_context: Optional[ssl.SSLContext],
) -> http.client.HTTPConnection:
    """An ``http.client`` connection to ``host`` that dials only the checked addresses.

    ``host`` stays the connection's host, so ``http.client`` writes it in the ``Host``
    header and TLS uses it for SNI and certificate verification. Only the socket is
    pinned: it is opened to the first of ``addresses`` that accepts it, which is then
    recorded as the connection's ``pinned_address``. Each attempt gets what is left of
    the budget, not a fresh one.
    """

    def open_pinned_socket(connection) -> socket.socket:
        last_error: Optional[OSError] = None
        for address in addresses:
            remaining_s = watchdog.remaining()
            if remaining_s <= 0:
                break
            try:
                sock = connector((str(address), port), remaining_s)
            except OSError as e:
                last_error = e
                continue
            connection.pinned_address = str(address)
            return watchdog.watch(sock)
        if watchdog.remaining() <= 0:
            raise FetchLimitExceeded(
                f"connecting to {host}:{port} ran over the time budget"
            )
        raise FetchFailed(f"cannot connect to {host}:{port}: {last_error}")

    if scheme == "https":
        context = ssl_context or ssl.create_default_context()

        class _PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                sock = open_pinned_socket(self)
                tls = context.wrap_socket(
                    sock, server_hostname=self.host, do_handshake_on_connect=False
                )
                self.sock = watchdog.watch(tls)  # before the handshake can block
                tls.do_handshake()

        return _PinnedHTTPS(host, port, timeout=watchdog.remaining(), context=context)

    class _PinnedHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = open_pinned_socket(self)

    return _PinnedHTTP(host, port, timeout=watchdog.remaining())


def _default_connector(address: tuple, timeout: float) -> socket.socket:
    return socket.create_connection(address, timeout=timeout)


# --------------------------------------------------------------------------------------
# The response


@dataclass
class GuardedResponse:
    """An open response from :func:`guarded_open`, with its budgets still enforced.

    Use it as a context manager, and read it with :meth:`iter_chunks` (streaming) or
    :meth:`read` (everything). Reading past ``max_bytes`` or past the deadline raises
    :class:`FetchLimitExceeded`. ``max_bytes`` counts bytes as they arrive, so a caller
    who overrides ``Accept-Encoding`` caps the compressed size. The time budget keeps
    running while the caller handles a chunk, so a slow consumer (writing to a slow
    disk, say) should ask for a ``timeout`` that covers its own work too.
    """

    url: str  #: the final URL, after redirects
    status: int
    reason: str
    headers: http.client.HTTPMessage
    address: str  #: the IP the socket was actually connected to
    max_bytes: int
    _response: http.client.HTTPResponse = field(repr=False)
    _connection: http.client.HTTPConnection = field(repr=False)
    _watchdog: _Watchdog = field(repr=False)
    _bytes_read: int = field(default=0, repr=False)

    def _out_of_time(self) -> FetchLimitExceeded:
        return FetchLimitExceeded(f"fetching {self.url} ran over its time budget")

    def iter_chunks(self, chunk_size: int = DFLT_CHUNK_SIZE) -> Iterator[bytes]:
        """Yield the body in chunks of at most ``chunk_size`` bytes, within budget."""
        while True:
            if self._watchdog.remaining() <= 0:
                raise self._out_of_time()
            try:
                chunk = self._response.read(chunk_size)
            except (OSError, http.client.HTTPException, ValueError) as e:
                if self._watchdog.fired or isinstance(e, TimeoutError):
                    raise self._out_of_time() from e
                raise FetchFailed(f"reading {self.url} failed: {e}") from e
            if not chunk:
                if self._watchdog.fired:  # an empty read, but only because we cut it
                    raise self._out_of_time()
                if self._response.length:  # http.client's count of declared bytes left
                    raise FetchFailed(
                        f"{self.url} ended {self._response.length} bytes short of its "
                        "declared Content-Length"
                    )
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
        self._watchdog.cancel()  # also releases the socket, before it is closed
        self._response.close()
        self._connection.close()

    def __enter__(self) -> GuardedResponse:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# --------------------------------------------------------------------------------------
# The fetch


@dataclass(frozen=True)
class _Target:
    url: str
    scheme: str
    host: str
    port: int
    path: str  # path and query, as it goes on the request line

    @property
    def origin(self) -> tuple:
        return self.scheme, self.host, self.port


def _check_url(url: str, *, allow_schemes, allow_ports) -> _Target:
    """The parsed ``url``, or :class:`UnsafeTarget` if it may not be fetched."""
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
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if allow_ports is not None and port not in allow_ports:
        raise UnsafeTarget(f"refusing {url}: port {port} is not allowed")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return _Target(url, scheme, host, port, path)


def _redirect_target(current: str, location: str) -> str:
    try:
        return urljoin(current, location).split("#", 1)[0]
    except ValueError as e:
        raise UnsafeTarget(f"refusing redirect from {current} to {location!r}: {e}")


def _check_hop(
    url: str, *, allow_schemes, allow_ports, is_allowed_address, resolver, deadline
) -> tuple[_Target, list[IPAddress]]:
    """One hop's whole check: the URL itself, then its host's resolved addresses."""
    target = _check_url(url, allow_schemes=allow_schemes, allow_ports=allow_ports)
    addresses = _resolve_and_check(
        url,
        target.host,
        target.port,
        resolver=resolver,
        is_allowed_address=is_allowed_address,
        deadline=deadline,
    )
    return target, addresses


def _check_timeout(timeout) -> None:
    if not (
        isinstance(timeout, (int, float))
        and math.isfinite(timeout)
        and 0 < timeout <= threading.TIMEOUT_MAX
    ):
        raise ValueError(
            f"timeout must be a finite number of seconds > 0, not {timeout!r}"
        )


def _normalized_policy(allow_schemes, allow_ports):
    """``(allow_schemes, allow_ports)`` as the tuple and frozenset the checks expect."""
    return (
        tuple(sch.lower() for sch in allow_schemes),
        None if allow_ports is None else frozenset(allow_ports),
    )


def check_target(
    url: str,
    *,
    allow_schemes: Iterable[str] = DFLT_ALLOWED_SCHEMES,
    allow_ports: Optional[Iterable[int]] = DFLT_ALLOWED_PORTS,
    timeout: float = DFLT_TIMEOUT_S,
    is_allowed_address: AddressPolicy = default_public_only,
    resolver: Resolver = system_resolver,
) -> list[IPAddress]:
    """The guard's check on ``url`` alone, without connecting: its resolved addresses.

    For callers that hand the URL to another fetcher (so cannot pin) or that validate a
    URL when it is stored. It is the very check :func:`guarded_open` makes on its first
    hop, so "allowed target" has one definition and its defaults cannot drift. Only that
    hop, and this is a validation of the *URL*, not a safe fetch: the other fetcher
    resolves the host again (DNS rebinding) and follows redirects unchecked. Pin the
    returned addresses if it lets you. Because that fetcher may parse the URL differently
    from :func:`urllib.parse.urlsplit`, a URL with userinfo (``@``), a backslash,
    whitespace or control characters is refused outright.

    Raises :class:`UnsafeTarget` for a bad scheme, port, host or address,
    :class:`FetchFailed` if the host does not resolve, and :class:`FetchLimitExceeded`
    if resolving takes longer than ``timeout``.

    >>> check_target('http://169.254.169.254/')
    Traceback (most recent call last):
        ...
    graze.guarded.UnsafeTarget: refusing http://169.254.169.254/: address 169.254.169.254 is not allowed
    >>> check_target('https://example.com/', resolver=lambda host, port: ['93.184.216.34'])
    [IPv4Address('93.184.216.34')]
    """
    _check_timeout(timeout)
    if isinstance(allow_schemes, str):
        raise TypeError(f"allow_schemes must be a collection, not {allow_schemes!r}")
    allow_schemes, allow_ports = _normalized_policy(allow_schemes, allow_ports)
    if not isinstance(url, str):
        raise TypeError(f"url must be a str, not {type(url).__name__}")
    # '@' is ambiguous only before the first '/' after '//' (a path like '/@user' is fine);
    # '#' and '?' do not end that span, since some parsers do not stop at them.
    authority_span = url.partition("//")[2].partition("/")[0]
    if _AMBIGUOUS_URL.search(url) or "@" in authority_span:
        raise UnsafeTarget(
            f"refusing {url!r}: userinfo, backslash, whitespace or control characters "
            "are parsed differently by different fetchers"
        )
    _, addresses = _check_hop(
        url,
        allow_schemes=allow_schemes,
        allow_ports=allow_ports,
        is_allowed_address=is_allowed_address,
        resolver=resolver,
        deadline=time.monotonic() + timeout,
    )
    return addresses


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
    a body). When a redirect leaves the original origin, only the caller headers in
    :data:`CROSS_ORIGIN_SAFE_HEADERS` go with it.
    """
    _check_timeout(timeout)
    if max_redirects < 0:
        raise ValueError(f"max_redirects must be >= 0, not {max_redirects}")
    allow_schemes, allow_ports = _normalized_policy(allow_schemes, allow_ports)
    request_headers = {"Accept-Encoding": "identity", **dict(headers or {})}
    watchdog = _Watchdog(time.monotonic() + timeout)
    try:
        return _open_following_redirects(
            url,
            method=method,
            body=body,
            request_headers=request_headers,
            allow_schemes=allow_schemes,
            allow_ports=allow_ports,
            max_redirects=max_redirects,
            max_bytes=max_bytes,
            is_allowed_address=is_allowed_address,
            resolver=resolver,
            connector=connector,
            ssl_context=ssl_context,
            raise_for_status=raise_for_status,
            watchdog=watchdog,
        )
    except BaseException:
        watchdog.cancel()
        raise


def _open_following_redirects(
    url: str,
    *,
    method,
    body,
    request_headers,
    allow_schemes,
    allow_ports,
    max_redirects,
    max_bytes,
    is_allowed_address,
    resolver,
    connector,
    ssl_context,
    raise_for_status,
    watchdog: _Watchdog,
) -> GuardedResponse:
    original = _check_url(url, allow_schemes=allow_schemes, allow_ports=allow_ports)
    current = url

    def out_of_time():
        return FetchLimitExceeded(f"fetching {url} ran over its time budget")

    for _ in range(max_redirects + 1):
        target, addresses = _check_hop(
            current,
            allow_schemes=allow_schemes,
            allow_ports=allow_ports,
            is_allowed_address=is_allowed_address,
            resolver=resolver,
            deadline=watchdog.deadline,
        )
        if watchdog.remaining() <= 0:
            raise out_of_time()
        connection = _pinned_connection(
            target.scheme,
            target.host,
            target.port,
            addresses,
            watchdog=watchdog,
            connector=connector,
            ssl_context=ssl_context,
        )
        try:
            connection.request(method, target.path, body=body, headers=request_headers)
            response = connection.getresponse()
        except GuardedFetchError:
            watchdog.release()
            connection.close()
            raise
        except (OSError, http.client.HTTPException, ValueError) as e:
            watchdog.release()
            connection.close()
            if watchdog.fired or isinstance(e, TimeoutError):
                raise out_of_time() from e
            raise FetchFailed(f"fetching {current} failed: {e}") from e

        if response.status in _REDIRECT_STATUSES:
            location = response.getheader("Location")
            response.close()
            watchdog.release()
            connection.close()
            if not location:
                raise FetchFailed(f"{current} redirected without a Location")
            current = _redirect_target(current, location)
            if response.status == 303 or (
                response.status in (301, 302) and method.upper() == "POST"
            ):
                method, body = "GET", None
            next_target = _check_url(
                current, allow_schemes=allow_schemes, allow_ports=allow_ports
            )
            if next_target.origin != original.origin:
                request_headers = {
                    k: v
                    for k, v in request_headers.items()
                    if k.lower() in CROSS_ORIGIN_SAFE_HEADERS
                }
            continue

        guarded = GuardedResponse(
            url=current,
            status=response.status,
            reason=response.reason,
            headers=response.headers,
            address=connection.pinned_address,
            max_bytes=max_bytes,
            _response=response,
            _connection=connection,
            _watchdog=watchdog,
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


guarded_fetch.__signature__ = inspect.signature(guarded_open).replace(
    return_annotation=bytes
)

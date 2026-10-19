# graze.guarded

Guarded fetch with a pinned transport — an SSRF-safe GET for caller-supplied URLs.

Fetching a URL that someone else handed you is a server-side request forgery hole: the
URL can point at `localhost`, at a private network, or at cloud metadata
(`169.254.169.254`). The usual guard — resolve the host, check the addresses, then let
an HTTP client connect — has two gaps:

- **DNS rebinding.** The client resolves the host *again* when it connects, and an
  attacker’s DNS answers “public” to the check and `127.0.0.1` to the connect.
- **Redirects.** A public URL answers `302 Location: http://169.254.169.254/`, and a
  client that follows redirects by itself never shows the hop to the guard.

This module closes both by owning the transport. Each hop’s host is resolved **once**,
**every** resolved address is checked, and the socket is opened to exactly the address
that was checked — while the request still carries the original `Host` header and the
TLS handshake still sends the original name (SNI) and verifies the certificate against
it. Redirects are never followed by a library; each `Location` goes back through the
same check.

```pycon
>>> body = guarded_fetch('https://example.com/data.json')
>>> guarded_fetch('http://169.254.169.254/latest/meta-data/')
Traceback (most recent call last):
    ...
graze.guarded.UnsafeTarget: refusing http://169.254.169.254/latest/meta-data/: address 169.254.169.254 is not allowed
>>> guarded_fetch('file:///etc/passwd')
Traceback (most recent call last):
    ...
graze.guarded.UnsafeTarget: refusing file:///etc/passwd: scheme 'file' is not allowed (allowed: https, http)
```

[`guarded_fetch()`](#graze.guarded.guarded_fetch) returns the body as bytes. [`guarded_open()`](#graze.guarded.guarded_open) returns a
[`GuardedResponse`](#graze.guarded.GuardedResponse) to stream from (`iter_chunks`) when the body is large, and
exposes the final URL, the status, the headers, and the address actually connected to.

`timeout` is a **wall-clock** budget for the whole fetch — resolution, connection, TLS
handshake, redirects, headers and body. A per-read socket timeout alone is not one: a
server trickling a byte just inside it can hold a worker for as long as it likes. So on
top of the socket timeouts, a watchdog shuts the socket down when the budget runs out.

The seams, all keyword-only:

- `is_allowed_address` — the address policy. [`default_public_only()`](#graze.guarded.default_public_only) by default;
  pass an allow-list for tests or for a self-hosted deployment that must reach a LAN host.
- `resolver` — host name to addresses. [`system_resolver()`](#graze.guarded.system_resolver) (`getaddrinfo`) by
  default; a fake one makes rebinding testable offline.
- `connector` and `ssl_context` — how the pinned socket is opened and wrapped.

Like [`graze.share_links`](graze.share_links.html.md#module-graze.share_links) and [`graze.content_kind`](graze.content_kind.html.md#module-graze.content_kind), this module uses the
standard library only (`http.client`, `ssl`, `socket`, `ipaddress`). It reads no
proxy settings from the environment, on purpose: a proxy would resolve the host itself,
and the pin would be meaningless.

### Module Attributes

| [`DFLT_ALLOWED_PORTS`](#graze.guarded.DFLT_ALLOWED_PORTS)        | Ports a fetch may target.                                                       |
|----------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`DFLT_TIMEOUT_S`](#graze.guarded.DFLT_TIMEOUT_S)            | Wall-clock budget for the whole fetch, redirects and body included, in seconds. |
| [`CROSS_ORIGIN_SAFE_HEADERS`](#graze.guarded.CROSS_ORIGIN_SAFE_HEADERS) | The only caller headers that follow a redirect to a different origin.           |

### Functions

| [`guarded_fetch`](#graze.guarded.guarded_fetch)(url, \*[, method, headers, ...])   | The body of `url` as bytes, fetched through the guard.                   |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`guarded_open`](#graze.guarded.guarded_open)(url, \*[, method, headers, ...])    | Open `url` through the guard and return the response, body not yet read. |
| [`default_public_only`](#graze.guarded.default_public_only)(ip)                          | True iff `ip` is a globally routable unicast address.                    |
| [`system_resolver`](#graze.guarded.system_resolver)(host, port)                      | Every address `host` resolves to, via the system's `getaddrinfo`.        |

### Classes

| [`GuardedResponse`](#graze.guarded.GuardedResponse)(url, status, reason, ...[, ...])   | An open response from [`guarded_open()`](#graze.guarded.guarded_open), with its budgets still enforced.   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|

### Exceptions

| [`GuardedFetchError`](#graze.guarded.GuardedFetchError)                         | Base class of everything [`guarded_fetch()`](#graze.guarded.guarded_fetch) raises on purpose.   |
|--------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`UnsafeTarget`](#graze.guarded.UnsafeTarget)                              | The URL, or a redirect hop of it, points somewhere a fetch must not go.                                        |
| [`FetchLimitExceeded`](#graze.guarded.FetchLimitExceeded)                        | The fetch ran over its byte, time, or redirect budget.                                                         |
| [`FetchFailed`](#graze.guarded.FetchFailed)                               | The target was allowed but the network part failed (refused, reset, TLS...).                                   |
| [`HTTPStatusError`](#graze.guarded.HTTPStatusError)(message, \*, status, url) | The server answered with an error status (4xx or 5xx).                                                         |

### graze.guarded.CROSS_ORIGIN_SAFE_HEADERS *= frozenset({'accept', 'accept-encoding', 'accept-language', 'content-type', 'if-modified-since', 'if-none-match', 'if-range', 'range', 'user-agent'})*

The only caller headers that follow a redirect to a different origin. Anything else
(`Authorization`, `Cookie`, an `X-Api-Key`…) was meant for the first origin.

### graze.guarded.DFLT_ALLOWED_PORTS *= (443, 80)*

Ports a fetch may target. `None` (passed as `allow_ports`) allows any port.

### graze.guarded.DFLT_TIMEOUT_S *= 30.0*

Wall-clock budget for the whole fetch, redirects and body included, in seconds.
Raise it with `max_bytes`: the defaults together assume about 1.7 MB/s.

### *exception* graze.guarded.FetchFailed

Bases: [`GuardedFetchError`](#graze.guarded.GuardedFetchError), [`OSError`](https://docs.python.org/3/builtins/exceptions.html#OSError)

The target was allowed but the network part failed (refused, reset, TLS…).

### *exception* graze.guarded.FetchLimitExceeded

Bases: [`GuardedFetchError`](#graze.guarded.GuardedFetchError)

The fetch ran over its byte, time, or redirect budget.

### *exception* graze.guarded.GuardedFetchError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Base class of everything [`guarded_fetch()`](#graze.guarded.guarded_fetch) raises on purpose.

### *class* graze.guarded.GuardedResponse(url, status, reason, headers, address, max_bytes, \_response, \_connection, \_watchdog, \_bytes_read=0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An open response from [`guarded_open()`](#graze.guarded.guarded_open), with its budgets still enforced.

Use it as a context manager, and read it with [`iter_chunks()`](#graze.guarded.GuardedResponse.iter_chunks) (streaming) or
[`read()`](#graze.guarded.GuardedResponse.read) (everything). Reading past `max_bytes` or past the deadline raises
[`FetchLimitExceeded`](#graze.guarded.FetchLimitExceeded). `max_bytes` counts bytes as they arrive, so a caller
who overrides `Accept-Encoding` caps the compressed size. The time budget keeps
running while the caller handles a chunk, so a slow consumer (writing to a slow
disk, say) should ask for a `timeout` that covers its own work too.

#### address *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

the IP the socket was actually connected to

#### iter_chunks(chunk_size=65536)

Yield the body in chunks of at most `chunk_size` bytes, within budget.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

#### read()

The whole (remaining) body.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

the final URL, after redirects

### *exception* graze.guarded.HTTPStatusError(message, , status, url)

Bases: [`GuardedFetchError`](#graze.guarded.GuardedFetchError)

The server answered with an error status (4xx or 5xx).

### *exception* graze.guarded.UnsafeTarget

Bases: [`GuardedFetchError`](#graze.guarded.GuardedFetchError), [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The URL, or a redirect hop of it, points somewhere a fetch must not go.

### graze.guarded.default_public_only(ip)

True iff `ip` is a globally routable unicast address.

Refuses loopback, private, link-local (cloud metadata lives there), carrier-grade
NAT, reserved, unspecified and multicast addresses. An IPv6 address that embeds an
IPv4 one (`::ffff:127.0.0.1`, 6to4, Teredo, NAT64, SIIT) is judged by the embedded
address too — explicitly, because `ipaddress` only learned to look through
IPv4-mapped addresses in CPython 3.10.14 / 3.11.9 / 3.12.3 (CVE-2024-4032).

```pycon
>>> default_public_only(ipaddress.ip_address('93.184.216.34'))
True
>>> [default_public_only(ipaddress.ip_address(a)) for a in
...  ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1')]
[False, False, False, False, False]
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### graze.guarded.guarded_fetch(url, \*, method='GET', headers=None, body=None, allow_schemes=('https', 'http'), allow_ports=(443, 80), max_redirects=5, timeout=30.0, max_bytes=52428800, is_allowed_address=<function default_public_only>, resolver=<function system_resolver>, connector=<function \_default_connector>, ssl_context=None, raise_for_status=True)

The body of `url` as bytes, fetched through the guard.

Takes the same keyword arguments as [`guarded_open()`](#graze.guarded.guarded_open), which is the one to use
for a large body (stream it with `iter_chunks`) or to see the final URL, status
and headers.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### graze.guarded.guarded_open(url, \*, method='GET', headers=None, body=None, allow_schemes=('https', 'http'), allow_ports=(443, 80), max_redirects=5, timeout=30.0, max_bytes=52428800, is_allowed_address=<function default_public_only>, resolver=<function system_resolver>, connector=<function \_default_connector>, ssl_context=None, raise_for_status=True)

Open `url` through the guard and return the response, body not yet read.

Every hop — the URL and each redirect — is checked: scheme in `allow_schemes`,
port in `allow_ports` (`None` allows any), host resolved once by `resolver`,
every address accepted by `is_allowed_address`, and the socket opened to one of
exactly those addresses. `timeout` is a wall-clock budget for the whole fetch,
including reading the body; `max_bytes` caps the body.

Redirects follow browser rules (303, and 301/302 after a POST, become a GET without
a body). When a redirect leaves the original origin, only the caller headers in
[`CROSS_ORIGIN_SAFE_HEADERS`](#graze.guarded.CROSS_ORIGIN_SAFE_HEADERS) go with it.

* **Return type:**
  [`GuardedResponse`](#graze.guarded.GuardedResponse)

### graze.guarded.system_resolver(host, port)

Every address `host` resolves to, via the system’s `getaddrinfo`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

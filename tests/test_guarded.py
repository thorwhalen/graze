"""Offline tests for the guarded fetch (`graze.guarded`).

Nothing here touches the internet. Host names are answered by a fake resolver, and a
recording connector sends every pinned socket to a local HTTP server while remembering
which address the guard *asked* to connect to. That address is the thing under test: the
guard must only ever dial an address it has checked.
"""

import doctest
import http.server
import ipaddress
import json
import socket
import ssl
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest

import graze.guarded as guarded
from graze.guarded import (
    FetchFailed,
    FetchLimitExceeded,
    HTTPStatusError,
    UnsafeTarget,
    default_public_only,
    guarded_fetch,
    guarded_open,
    check_target,
)

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        if parts.path == "/ok":
            self._send(200, b"hello")
        elif parts.path == "/redirect":
            status = int(query.get("status", ["302"])[0])
            self._send(status, headers=[("Location", query["to"][0])])
        elif parts.path == "/loop":
            self._send(302, headers=[("Location", "/loop")])
        elif parts.path == "/headers":
            self._send(200, json.dumps(dict(self.headers.items())).encode())
        elif parts.path == "/big":
            self._send(200, b"x" * 10_000)
        elif parts.path == "/big-undeclared":
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"x" * 10_000)
        elif parts.path == "/short":  # promises 1000 bytes, sends 9, hangs up
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"only-9-b!")
        elif parts.path == "/missing":
            self._send(404, b"nope")
        else:
            self._send(500)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.do_GET()


@pytest.fixture(scope="module")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


class Recorder:
    """A connector that records the pinned address and dials the local server instead."""

    def __init__(self, server):
        self.port = server.server_address[1]
        self.dialed = []

    def __call__(self, address, timeout):
        self.dialed.append(address[0])
        return socket.create_connection(("127.0.0.1", self.port), timeout=timeout)


class _PlainAsTLS(socket.socket):
    """A plain socket posing as a TLS one: the handshake is a no-op."""

    def do_handshake(self):
        pass


def trickle_server(head, *, interval, total):
    """A one-connection server that sends ``head`` then trickles ``total`` bytes slowly.

    Each byte arrives well inside any per-read timeout, which is exactly how a server
    holds a worker that only has per-read timeouts. Returns ``(port, stop)``.
    """
    listener = socket.create_server(("127.0.0.1", 0))
    stop = threading.Event()

    def serve():
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            try:
                conn.sendall(head)
                for _ in range(total):
                    if stop.wait(interval):
                        return
                    conn.sendall(b"x")
            except OSError:
                return

    threading.Thread(target=serve, daemon=True).start()

    def close():
        stop.set()
        listener.close()

    return listener.getsockname()[1], close


def to_port(port):
    return lambda address, timeout: socket.create_connection(
        ("127.0.0.1", port), timeout=timeout
    )


def fixed_resolver(table):
    """A resolver answering from ``table`` (host -> list of addresses), counting calls."""

    def resolve(host, port):
        resolve.calls.append(host)
        return table[host]

    resolve.calls = []
    return resolve


def rebinding_resolver(*answers):
    """A resolver answering ``answers[0]`` the first time, ``answers[1]`` the next..."""
    answers = list(answers)

    def resolve(host, port):
        resolve.calls.append(host)
        return answers.pop(0) if len(answers) > 1 else answers[0]

    resolve.calls = []
    return resolve


@pytest.fixture
def recorder(server):
    return Recorder(server)


# --------------------------------------------------------------------------------------
# The acceptance cases of thorwhalen/graze#12


class TestRebinding:
    def test_rebinding_resolver_never_reaches_loopback(self, recorder):
        # A check-then-connect fetcher resolves twice: public for the check, loopback for
        # the connect. The guard resolves once and dials what it checked.
        resolver = rebinding_resolver([PUBLIC_IP], ["127.0.0.1"])
        body = guarded_fetch(
            "http://rebind.example/ok", resolver=resolver, connector=recorder
        )
        assert body == b"hello"
        assert resolver.calls == ["rebind.example"]
        assert recorder.dialed == [PUBLIC_IP]

    def test_rebinding_on_a_redirect_hop_is_refused(self, recorder):
        # The second resolution of the same name (for the redirect hop) answers loopback.
        resolver = rebinding_resolver([PUBLIC_IP], ["127.0.0.1"])
        with pytest.raises(UnsafeTarget, match="127.0.0.1 is not allowed"):
            guarded_fetch(
                "http://rebind.example/redirect?to=http://rebind.example/ok",
                resolver=resolver,
                connector=recorder,
            )
        assert recorder.dialed == [PUBLIC_IP]

    def test_a_name_answering_public_and_loopback_is_refused(self, recorder):
        resolver = fixed_resolver({"mixed.example": [PUBLIC_IP, "127.0.0.1"]})
        with pytest.raises(UnsafeTarget, match="127.0.0.1 is not allowed"):
            guarded_fetch(
                "http://mixed.example/ok", resolver=resolver, connector=recorder
            )
        assert recorder.dialed == []


class TestRedirects:
    def test_redirect_to_cloud_metadata_is_refused(self, recorder):
        resolver = fixed_resolver({"public.example": [PUBLIC_IP]})
        with pytest.raises(UnsafeTarget, match="169.254.169.254 is not allowed"):
            guarded_fetch(
                "http://public.example/redirect?to=http://169.254.169.254/latest/",
                resolver=resolver,
                connector=recorder,
            )
        assert recorder.dialed == [PUBLIC_IP]

    def test_redirect_to_a_name_resolving_to_metadata_is_refused(self, recorder):
        resolver = fixed_resolver(
            {"public.example": [PUBLIC_IP], "meta.example": ["169.254.169.254"]}
        )
        with pytest.raises(UnsafeTarget, match="169.254.169.254"):
            guarded_fetch(
                "http://public.example/redirect?to=http://meta.example/",
                resolver=resolver,
                connector=recorder,
            )

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_redirect_to_a_public_host_is_followed(self, recorder, status):
        resolver = fixed_resolver(
            {"a.example": [PUBLIC_IP], "b.example": [OTHER_PUBLIC_IP]}
        )
        with guarded_open(
            f"http://a.example/redirect?status={status}&to=http://b.example/ok",
            resolver=resolver,
            connector=recorder,
        ) as response:
            assert response.read() == b"hello"
            assert response.url == "http://b.example/ok"
            assert response.address == OTHER_PUBLIC_IP
        assert recorder.dialed == [PUBLIC_IP, OTHER_PUBLIC_IP]

    def test_redirect_to_file_scheme_is_refused(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(UnsafeTarget, match="scheme 'file'"):
            guarded_fetch(
                "http://a.example/redirect?to=file:///etc/passwd",
                resolver=resolver,
                connector=recorder,
            )

    def test_redirect_loop_runs_out_of_budget(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(FetchLimitExceeded, match="redirected more than 2 times"):
            guarded_fetch(
                "http://a.example/loop",
                resolver=resolver,
                connector=recorder,
                max_redirects=2,
            )
        assert len(recorder.dialed) == 3

    def test_credentials_are_dropped_on_a_cross_origin_redirect(self, recorder):
        resolver = fixed_resolver(
            {"a.example": [PUBLIC_IP], "b.example": [OTHER_PUBLIC_IP]}
        )
        secret = {
            "Authorization": "Bearer s3cret",
            "Cookie": "sid=1",
            "X-Api-Key": "k",
            "User-Agent": "graze-test",
            "Range": "bytes=100-",
        }
        same = json.loads(
            guarded_fetch(
                "http://a.example/redirect?to=/headers",
                headers=secret,
                resolver=resolver,
                connector=recorder,
            )
        )
        assert same["Authorization"] == "Bearer s3cret"
        cross = json.loads(
            guarded_fetch(
                "http://a.example/redirect?to=http://b.example/headers",
                headers=secret,
                resolver=resolver,
                connector=recorder,
            )
        )
        assert not {"Authorization", "Cookie", "X-Api-Key"} & set(cross)
        assert cross["User-Agent"] == "graze-test"
        assert cross["Range"] == "bytes=100-"  # a resumed download survives a CDN hop


class TestRefusedTargets:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://a.example/x",
            "gopher://a.example/x",
            "data:text/plain,hi",
        ],
    )
    def test_non_http_schemes_are_refused(self, url, recorder):
        with pytest.raises(UnsafeTarget, match="scheme"):
            guarded_fetch(url, connector=recorder)
        assert recorder.dialed == []

    @pytest.mark.parametrize(
        "url",
        [
            "http://[::ffff:127.0.0.1]/",  # IPv6-mapped loopback
            "http://[::ffff:169.254.169.254]/",  # IPv6-mapped metadata
            "http://[::1]/",
            "http://127.0.0.1/",
            "http://0.0.0.0/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://100.64.0.1/",  # carrier-grade NAT
            "http://[fe80::1]/",
            "http://[fd00::1]/",
            "http://[2002:7f00:1::]/",  # 6to4 wrapping 127.0.0.1
            "http://[64:ff9b::a9fe:a9fe]/",  # NAT64 wrapping 169.254.169.254
            "http://[::7f00:1]/",  # IPv4-compatible 127.0.0.1
            "http://224.0.0.1/",  # multicast
        ],
    )
    def test_internal_literals_are_refused(self, url, recorder):
        with pytest.raises(UnsafeTarget, match="is not allowed"):
            guarded_fetch(url, connector=recorder)
        assert recorder.dialed == []

    def test_name_resolving_to_mapped_loopback_is_refused(self, recorder):
        resolver = fixed_resolver({"sneaky.example": ["::ffff:127.0.0.1"]})
        with pytest.raises(UnsafeTarget):
            guarded_fetch(
                "http://sneaky.example/", resolver=resolver, connector=recorder
            )

    def test_mapped_loopback_refused_on_an_unpatched_interpreter(self, monkeypatch):
        # Before CVE-2024-4032 was fixed, ``::ffff:127.0.0.1`` reported is_global=True.
        monkeypatch.setattr(
            ipaddress.IPv6Address,
            "is_global",
            property(lambda self: self.ipv4_mapped is not None),
        )
        assert ipaddress.ip_address("::ffff:127.0.0.1").is_global is True
        assert not default_public_only(ipaddress.ip_address("::ffff:127.0.0.1"))

    def test_disallowed_port_is_refused(self, recorder):
        with pytest.raises(UnsafeTarget, match="port 6379"):
            guarded_fetch("http://a.example:6379/", connector=recorder)
        assert recorder.dialed == []

    @pytest.mark.parametrize(
        "url", ["http://a.example:99999/", "http://a.example:abc/", "http://[::1/"]
    )
    def test_malformed_url_is_an_unsafe_target(self, url):
        with pytest.raises(UnsafeTarget):
            guarded_fetch(url)

    def test_malformed_redirect_location_is_an_unsafe_target(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(UnsafeTarget):
            guarded_fetch(
                "http://a.example/redirect?to=http://a.example:99999/",
                resolver=resolver,
                connector=recorder,
            )

    @pytest.mark.parametrize(
        "address",
        [
            "::ffff:0:7f00:1",  # SIIT IPv4-translated 127.0.0.1
            "fec0::1",  # deprecated site-local
            "192.88.99.1",  # deprecated 6to4 relay anycast
        ],
    )
    def test_translated_and_deprecated_ranges_are_refused(self, address):
        assert not default_public_only(ipaddress.ip_address(address))

    def test_port_zero_is_not_silently_port_80(self, recorder):
        with pytest.raises(UnsafeTarget, match="port 0"):
            guarded_fetch("http://a.example:0/", connector=recorder)

    def test_negative_max_redirects_is_a_usage_error(self):
        with pytest.raises(ValueError, match="max_redirects"):
            guarded_fetch("http://a.example/", max_redirects=-1)

    def test_url_without_host_is_refused(self):
        with pytest.raises(UnsafeTarget, match="no host"):
            guarded_fetch("http:///ok")


# --------------------------------------------------------------------------------------
# Budgets, statuses, seams


class TestBudgets:
    def test_declared_length_over_the_cap_is_refused_before_reading(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(FetchLimitExceeded, match="declares 10000 bytes"):
            guarded_fetch(
                "http://a.example/big",
                resolver=resolver,
                connector=recorder,
                max_bytes=1000,
            )

    def test_undeclared_length_over_the_cap_is_refused_while_reading(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(FetchLimitExceeded, match="larger than the 1000-byte"):
            guarded_fetch(
                "http://a.example/big-undeclared",
                resolver=resolver,
                connector=recorder,
                max_bytes=1000,
            )

    def test_a_body_cut_short_of_its_content_length_is_not_returned(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(FetchFailed, match="991 bytes short"):
            guarded_fetch(
                "http://a.example/short", resolver=resolver, connector=recorder
            )

    @pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 1e12, None])
    def test_an_unusable_timeout_is_a_usage_error(self, timeout):
        with pytest.raises(ValueError, match="timeout"):
            guarded_fetch("http://a.example/", timeout=timeout)

    def test_streaming_respects_the_cap(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with guarded_open(
            "http://a.example/big-undeclared", resolver=resolver, connector=recorder
        ) as response:
            chunks = list(response.iter_chunks(chunk_size=1024))
        assert sum(map(len, chunks)) == 10_000
        assert max(map(len, chunks)) <= 1024

    def test_slow_server_runs_out_of_time(self, recorder):
        listener = socket.create_server(("127.0.0.1", 0))  # accepts, never answers
        port = listener.getsockname()[1]
        try:
            with pytest.raises(FetchLimitExceeded, match="time budget"):
                guarded_fetch(
                    "http://slow.example/",
                    resolver=fixed_resolver({"slow.example": [PUBLIC_IP]}),
                    connector=lambda address, timeout: socket.create_connection(
                        ("127.0.0.1", port), timeout=timeout
                    ),
                    timeout=0.3,
                )
        finally:
            listener.close()


class TestWallClockBudget:
    """Findings 1-3 of the adversarial review: the budget is for the whole fetch."""

    @pytest.mark.parametrize(
        "head",
        [
            b"",  # headers trickle
            b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n",  # body, no length
            b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n",  # body, a length
        ],
        ids=["slow-headers", "slow-body-close", "slow-body-length"],
    )
    def test_a_trickling_server_cannot_outlast_the_budget(self, head):
        port, close = trickle_server(
            head or b"HTTP/1.1 200 OK\r\nX: ", interval=0.05, total=1000
        )
        start = time.monotonic()
        try:
            with pytest.raises(FetchLimitExceeded, match="time budget"):
                guarded_fetch(
                    "http://slow.example/",
                    resolver=fixed_resolver({"slow.example": [PUBLIC_IP]}),
                    connector=to_port(port),
                    timeout=0.5,
                )
        finally:
            close()
        assert time.monotonic() - start < 2

    def test_many_unreachable_addresses_share_one_budget(self):
        dialed = []

        def hang(address, timeout):
            dialed.append(address[0])
            time.sleep(timeout)
            raise TimeoutError("timed out")

        addresses = [f"93.184.216.{i}" for i in range(1, 9)]
        start = time.monotonic()
        with pytest.raises(FetchLimitExceeded, match="time budget"):
            guarded_fetch(
                "http://many.example/",
                resolver=fixed_resolver({"many.example": addresses}),
                connector=hang,
                timeout=0.3,
            )
        assert time.monotonic() - start < 1
        assert len(dialed) < len(addresses)

    def test_a_hanging_resolver_runs_out_of_time(self):
        def hang(host, port):
            time.sleep(2)
            return [PUBLIC_IP]

        start = time.monotonic()
        with pytest.raises(FetchLimitExceeded, match="resolving"):
            guarded_fetch("http://dns.example/", resolver=hang, timeout=0.2)
        assert time.monotonic() - start < 1


class TestStatusesAndSeams:
    def test_error_status_raises_with_the_status(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(HTTPStatusError) as caught:
            guarded_fetch(
                "http://a.example/missing", resolver=resolver, connector=recorder
            )
        assert caught.value.status == 404

    def test_error_status_can_be_read_instead(self, recorder):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with guarded_open(
            "http://a.example/missing",
            resolver=resolver,
            connector=recorder,
            raise_for_status=False,
        ) as response:
            assert (response.status, response.read()) == (404, b"nope")

    def test_host_header_is_the_original_name(self, recorder):
        resolver = fixed_resolver({"named.example": [PUBLIC_IP]})
        seen = json.loads(
            guarded_fetch(
                "http://named.example/headers", resolver=resolver, connector=recorder
            )
        )
        assert seen["Host"] == "named.example"
        assert recorder.dialed == [PUBLIC_IP]

    def test_allow_list_admits_a_lan_host(self, server):
        # The seam a self-hosted deployment (or a test) uses to reach a private address.
        lan = ipaddress.ip_network("127.0.0.0/8")
        body = guarded_fetch(
            f"http://127.0.0.1:{server.server_address[1]}/ok",
            allow_ports=None,
            is_allowed_address=lambda ip: ip in lan,
        )
        assert body == b"hello"

    def test_unreachable_address_is_a_fetch_failure(self):
        def refuse(address, timeout):
            raise ConnectionRefusedError("refused")

        with pytest.raises(FetchFailed, match="cannot connect"):
            guarded_fetch(
                "http://a.example/",
                resolver=fixed_resolver({"a.example": [PUBLIC_IP]}),
                connector=refuse,
            )

    def test_tls_uses_the_original_name_for_sni(self, recorder):
        class RecordingContext:
            """Stands in for an SSLContext; records the SNI name, skips the handshake."""

            # What http.client's HTTPSConnection reads off a context on 3.10-3.12.
            check_hostname = True
            verify_mode = ssl.CERT_REQUIRED
            post_handshake_auth = None

            def __init__(self):
                self.server_hostnames = []

            def wrap_socket(self, sock, server_hostname=None, **kwargs):
                self.server_hostnames.append(server_hostname)
                timeout = sock.gettimeout()  # detach() would drop it, as TLS doesn't
                tls = _PlainAsTLS(fileno=sock.detach())
                tls.settimeout(timeout)
                return tls

        context = RecordingContext()
        resolver = fixed_resolver({"tls.example": [PUBLIC_IP]})
        body = guarded_fetch(
            "https://tls.example/ok",
            resolver=resolver,
            connector=recorder,
            ssl_context=context,
        )
        assert body == b"hello"
        assert context.server_hostnames == ["tls.example"]
        assert recorder.dialed == [PUBLIC_IP]


class TestCheckTarget:
    def test_returns_the_checked_addresses(self):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP, OTHER_PUBLIC_IP]})
        got = check_target("https://a.example/x", resolver=resolver)
        assert got == [
            ipaddress.ip_address(PUBLIC_IP),
            ipaddress.ip_address(OTHER_PUBLIC_IP),
        ]
        assert resolver.calls == ["a.example"]

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://a.example/",
            "http://a.example:8080/",
            "http:///nohost",
            "http://169.254.169.254/",
            "http://[::1]/",
            "http://a.example:notaport/",
        ],
    )
    def test_refuses_what_the_fetch_refuses(self, url):
        resolver = fixed_resolver({"a.example": [PUBLIC_IP]})
        with pytest.raises(UnsafeTarget):
            check_target(url, resolver=resolver)

    def test_one_private_address_refuses_the_host(self):
        resolver = fixed_resolver({"m.example": [PUBLIC_IP, "10.0.0.1"]})
        with pytest.raises(UnsafeTarget, match="10.0.0.1"):
            check_target("http://m.example/", resolver=resolver)

    def test_agrees_with_guarded_open(self, recorder):
        resolver = fixed_resolver(
            {"p.example": [PUBLIC_IP], "q.example": ["127.0.0.1"]}
        )
        for url, ok in [("http://p.example/ok", True), ("http://q.example/ok", False)]:
            if ok:
                check_target(url, resolver=resolver)
                guarded_fetch(url, resolver=resolver, connector=recorder)
            else:
                with pytest.raises(UnsafeTarget):
                    check_target(url, resolver=resolver)
                with pytest.raises(UnsafeTarget):
                    guarded_fetch(url, resolver=resolver, connector=recorder)

    def test_policy_seams(self):
        resolver = fixed_resolver({"lan.example": ["10.0.0.1"]})
        got = check_target(
            "http://lan.example:8080/",
            allow_ports=None,
            allow_schemes=["HTTP"],
            is_allowed_address=lambda ip: True,
            resolver=resolver,
        )
        assert got == [ipaddress.ip_address("10.0.0.1")]

    def test_unresolvable_and_malformed_hosts_raise_graze_errors(self):
        def failing(host, port):
            raise socket.gaierror("no such host")

        with pytest.raises(FetchFailed):
            check_target("http://gone.example/", resolver=failing)

        def bad_label(host, port):
            raise UnicodeError("label empty or too long")

        with pytest.raises(FetchFailed):
            check_target("http://a..b/", resolver=bad_label)

    def test_resolver_over_the_timeout_is_a_budget_error(self):
        def slow(host, port):
            time.sleep(1)
            return [PUBLIC_IP]

        with pytest.raises(FetchLimitExceeded):
            check_target("http://s.example/", resolver=slow, timeout=0.05)

    @pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), "5"])
    def test_bad_timeout_is_a_value_error(self, timeout):
        with pytest.raises(ValueError):
            check_target("http://a.example/", timeout=timeout)


def test_module_doctests():
    failures, _ = doctest.testmod(guarded, optionflags=doctest.ELLIPSIS)
    assert failures == 0

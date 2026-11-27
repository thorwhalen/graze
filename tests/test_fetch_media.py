"""fetch_media: share link resolved, guarded fetch, bytes checked (against a local server)."""

import http.server
import threading
from urllib.parse import urlsplit

import pytest

from graze import ResolvedShareLink, ShareLinkKind
from graze.content_kind import ContentKindMismatch
from graze.media import FETCH_MEDIA_ERRORS, fetch_media
from graze.guarded import FetchLimitExceeded, HTTPStatusError, UnsafeTarget
from graze.share_links import ShareLinkResolutionError

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 600
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + b"\x00" * 600
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 600
ROUTES = {
    "/memo.mp3": (200, MP3, [("Content-Type", "audio/mpeg")]),
    "/dl": (200, M4A, [("Content-Disposition", "attachment; filename*=UTF-8''New%20Recording%203.m4a")]),
    "/page": (200, b"<!doctype html><html><body>Sign in</body></html>", [("Content-Type", "text/html")]),
    "/zip": (200, b"PK\x03\x04" + b"\x00" * 600, []),
    "/picture": (200, PNG, [("Content-Type", "image/png")]),
    "/private": (403, b"no", []),
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        status, body, headers = ROUTES.get(urlsplit(self.path).path, (404, b"", []))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def base():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


LOCAL = dict(is_allowed_address=lambda ip: True, allow_ports=None)


def _share_host(base):
    """A share provider whose links point at the local server, as Dropbox's dl=1 would."""

    def resolve(url):
        if url.startswith("https://share.test/"):
            return ResolvedShareLink(
                url=url,
                provider="testshare",
                kind=ShareLinkKind.FILE,
                direct_url=base + urlsplit(url).path,
                download_endpoint=True,
            )

    return {"testshare": resolve}


def test_a_plain_audio_link(base):
    media = fetch_media(f" {base}/memo.mp3 ", expect_kind="audio", **LOCAL)
    assert (media.data, media.filename, media.content_type, media.provider) == (MP3, "memo.mp3", "audio/mpeg", "http")


def test_a_share_link_takes_the_attachment_name(base):
    media = fetch_media("https://share.test/dl", expect_kind="audio", resolvers=_share_host(base), **LOCAL)
    assert media.filename == "New Recording 3.m4a"
    assert media.provider == "testshare" and media.size == len(M4A)


def test_the_share_hosts_own_page_is_refused(base):
    with pytest.raises(ContentKindMismatch, match="not shared publicly"):
        fetch_media("https://share.test/page", resolvers=_share_host(base), **LOCAL)


def test_a_plain_web_page_is_refused(base):
    with pytest.raises(ContentKindMismatch, match="HTML page"):
        fetch_media(f"{base}/page", **LOCAL)


def test_an_archive_is_refused(base):
    with pytest.raises(ContentKindMismatch, match="archive"):
        fetch_media(f"{base}/zip", expect_kind="audio", **LOCAL)


def test_another_kind_is_refused(base):
    with pytest.raises(ContentKindMismatch):
        fetch_media(f"{base}/picture", expect_kind="audio", **LOCAL)


def test_a_private_share_link_says_so(base):
    with pytest.raises(ShareLinkResolutionError, match="not public"):
        fetch_media("https://share.test/private", resolvers=_share_host(base), **LOCAL)
    with pytest.raises(HTTPStatusError):  # a plain URL keeps the plain status error
        fetch_media(f"{base}/private", **LOCAL)


def test_folders_and_unknown_links_are_refused_before_any_fetch():
    with pytest.raises(ShareLinkResolutionError, match="folder"):
        fetch_media("https://www.dropbox.com/scl/fo/x9/y?rlkey=zz&dl=0")
    with pytest.raises(ShareLinkResolutionError, match="onedrive"):
        fetch_media("https://1drv.ms/u/s!AbCd")


def test_the_guard_still_holds():
    with pytest.raises(UnsafeTarget):
        fetch_media("http://169.254.169.254/latest/meta-data/")


def test_the_byte_budget_passes_through(base):
    with pytest.raises(FetchLimitExceeded):
        fetch_media(f"{base}/memo.mp3", max_bytes=100, **LOCAL)


def test_every_refusal_is_one_of_the_declared_errors(base):
    for url in (f"{base}/page", f"{base}/zip", f"{base}/private", "http://10.0.0.1/x.mp3"):
        with pytest.raises(FETCH_MEDIA_ERRORS):
            fetch_media(url, **(LOCAL if url.startswith(base) else {}))

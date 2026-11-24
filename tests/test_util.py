"""Offline tests for ``graze.util`` (urllib and requests are replaced by fakes)."""

import io
import urllib.request

import pytest

from graze import util
from graze.share_links import ShareLinkResolutionError
from graze.util import (
    add_special_url_route,
    chks_of_url_contents,
    clog,
    download_from_google_drive,
    download_from_special_url,
    download_url_contents,
    get_content_size,
    google_drive_download_url,
    handle_missing_dir,
    human_readable_bytes,
    inner_most_key,
    is_special_url,
    last_element,
    original_url_of_tiny_url,
    special_url_routes,
    tiny_url,
    url_with_virus_scan_confirmation_token,
)


class _FakeResponse(io.BytesIO):
    headers = {}

    def getheader(self, name):
        return self.headers.get(name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Serve ``payloads[url]`` (bytes) for any urlopen; record the requests made."""
    payloads, seen = {}, []

    def urlopen(req, *a, **kw):
        seen.append(req)
        resp = _FakeResponse(payloads[req.full_url])
        resp.headers = {"Content-Length": str(len(payloads[req.full_url]))}
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return payloads, seen


def test_last_element():
    assert last_element([1, 2, 3]) == 3
    assert last_element([], default="d") == "d"


def test_inner_most_key_walks_wrapped_stores():
    class Inner:
        def _id_of_key(self, k):
            return f"inner-{k}"

    class Outer:
        store = Inner()

        def _id_of_key(self, k):
            return f"outer-{k}"

    assert inner_most_key(Outer(), "k") == "inner-outer-k"
    assert inner_most_key(object(), "k") is None


def test_clog():
    out = []
    clog(True, "a", log_func=out.append)
    clog(False, "b", log_func=out.append)
    clog(True, log_func=out.append)("c")
    assert out == ["a", "c"]


def test_human_readable_bytes_edge_cases():
    assert human_readable_bytes(0) == "~0.000B"
    assert human_readable_bytes(999) == "~999.000B"


def test_handle_missing_dir(tmp_path, monkeypatch):
    existing = tmp_path / "there"
    existing.mkdir()
    handle_missing_dir(str(existing))  # nothing to do
    new = tmp_path / "new"
    handle_missing_dir(str(new), ask_first=False, verbose=False)
    assert new.is_dir()

    declined = tmp_path / "declined"
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    handle_missing_dir(str(declined), verbose=False)
    assert not declined.exists()

    accepted = tmp_path / "accepted"
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # default is yes
    handle_missing_dir(str(accepted), verbose=False)
    assert accepted.is_dir()


def test_chunks_and_download(fake_urlopen, tmp_path):
    payloads, seen = fake_urlopen
    payloads["http://x/f"] = b"abcdefghij"
    assert list(chks_of_url_contents("http://x/f", chk_size=4)) == [
        b"abcd",
        b"efgh",
        b"ij",
    ]
    assert seen[0].get_header("User-agent") == util.DFLT_USER_AGENT

    assert download_url_contents("http://x/f") == b"abcdefghij"
    target = tmp_path / "sub" / "dir" / "f.bin"
    assert download_url_contents("http://x/f", str(target)) == str(target)
    assert target.read_bytes() == b"abcdefghij"
    buf = io.BytesIO()
    assert download_url_contents("http://x/f", buf) is buf
    assert buf.getvalue() == b"abcdefghij"
    assert util.bytes_of_url_content("http://x/f") == b"abcdefghij"


def test_get_content_size(fake_urlopen):
    payloads, _ = fake_urlopen
    payloads["http://x/f"] = b"12345"
    assert get_content_size("http://x/f") == 5


def test_first_bytes_and_is_html_doc(tmp_path):
    assert util._first_bytes(b"abcdef", 3) == b"abc"
    p = tmp_path / "a.html"
    p.write_bytes(b"<!DOCTYPE html><html/>")
    assert util._first_bytes(str(p), 4) == b"<!DO"
    assert util._is_html_doc(str(p))
    assert not util._is_html_doc(b"plain text file contents")


def test_first_bytes_of_a_file_like_object():
    import io

    assert util._first_bytes(io.BytesIO(b"abcdef"), 3) == b"abc"


def test_first_bytes_peeks_a_seekable_file_like_object_without_consuming_it():
    import io

    f = io.BytesIO(b"<!DOCTYPE html><p>x</p>")
    assert util._is_html_doc(f)
    assert f.tell() == 0 and f.read() == b"<!DOCTYPE html><p>x</p>"
    f.seek(5)
    assert util._first_bytes(f, 3) == b"TYP"
    assert f.tell() == 5


def test_virus_scan_confirmation_token():
    html = '<a href="/uc?export=download&confirm=AbC_-1&id=x">'
    assert (
        url_with_virus_scan_confirmation_token("http://u?x=1", html)
        == "http://u?x=1&confirm=AbC_-1"
    )
    with pytest.raises(ValueError, match="confirmation token"):
        url_with_virus_scan_confirmation_token("http://u", "<html/>")


def test_google_drive_url_resolution():
    assert (
        google_drive_download_url("https://drive.google.com/file/d/1Ab/view")
        == "https://drive.google.com/uc?export=download&id=1Ab"
    )
    with pytest.raises(ValueError, match="Not a Google Drive url"):
        google_drive_download_url("https://example.com/x")
    with pytest.raises(ShareLinkResolutionError):
        google_drive_download_url("https://drive.google.com/drive/folders/abc123")


def test_download_from_google_drive_follows_virus_scan_page(fake_urlopen):
    payloads, seen = fake_urlopen
    first = "https://drive.google.com/uc?export=download&id=1Ab"
    payloads[first] = b'<!DOCTYPE html><a href="x?confirm=TOK&id=1">'
    payloads[first + "&confirm=TOK"] = b"REAL"
    url = "https://drive.google.com/file/d/1Ab/view"
    assert download_from_google_drive(url) == payloads[first]  # no skipping asked
    assert (
        download_from_google_drive(url, skip_virus_scan_confirmation_page=True)
        == b"REAL"
    )


def test_special_url_routes(monkeypatch):
    monkeypatch.setattr(util, "special_url_routes", dict(special_url_routes))
    assert is_special_url("https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&dl=0")
    assert not is_special_url("https://example.com/data.csv")
    with pytest.raises(ValueError, match="Unsupported url"):
        download_from_special_url("https://example.com/data.csv")

    add_special_url_route(
        lambda u: u.startswith("custom://"), lambda u, f, **kw: ("got", u)
    )
    assert is_special_url("custom://thing")
    assert download_from_special_url("custom://thing") == ("got", "custom://thing")


def test_tiny_url_with_fake_requests(monkeypatch):
    import requests

    class R:
        def __init__(self, status, text="", url=""):
            self.status_code, self.text, self.url = status, text, url

    monkeypatch.setattr(requests, "get", lambda *a, **kw: R(200, "http://tiny/x"))
    assert tiny_url("http://long") == "http://tiny/x"
    monkeypatch.setattr(requests, "get", lambda *a, **kw: R(500))
    assert "500" in tiny_url("http://long")

    def boom(*a, **kw):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    assert "Network or request error" in tiny_url("http://long")

    monkeypatch.setattr(requests, "head", lambda *a, **kw: R(200, url="http://long"))
    assert original_url_of_tiny_url("http://tiny/x") == "http://long"
    monkeypatch.setattr(requests, "head", boom)
    assert "Error expanding URL" in original_url_of_tiny_url("http://tiny/x")

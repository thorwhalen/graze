"""Offline tests for share-link resolution (`graze.share_links`).

Every test here is pure string -> string. Nothing in this file opens a socket --
that is the entire reason resolution is a separate layer from transport, so a test
that needed the network would be evidence of a design regression, not a flaky test.
"""

import doctest

import pytest

import graze.util as util
from graze.share_links import (
    ResolvedShareLink,
    ShareLinkKind,
    ShareLinkResolutionError,
    add_share_link_resolver,
    direct_download_url,
    resolve_share_url,
    share_link_resolvers,
)


# --------------------------------------------------------------------------------------
# Dropbox
#
# Regression guard for the `/s/`-only regex: `is_dropbox_url` used to be
# `https?://www\.dropbox\.com/s/.+\?dl=(0|1)$`, which is False for every modern
# (`/scl/`) share link, for any link with a trailing parameter, and for any link
# copied without `?dl=`.


@pytest.mark.parametrize(
    "url,kind",
    [
        # modern forms -- the whole family the old regex missed
        (
            "https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz&st=q9&dl=0",
            ShareLinkKind.FILE,
        ),
        (
            "https://www.dropbox.com/scl/fo/q7x/AAB?rlkey=zz&st=q9&dl=0",
            ShareLinkKind.ARCHIVE,
        ),
        # legacy forms
        ("https://www.dropbox.com/s/a1b2/data.csv?dl=0", ShareLinkKind.FILE),
        ("https://www.dropbox.com/sh/a1b2/AAAhash?dl=0", ShareLinkKind.ARCHIVE),
        # no `dl` param at all
        ("https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz", ShareLinkKind.FILE),
        ("https://www.dropbox.com/s/a1b2/data.csv", ShareLinkKind.FILE),
        # trailing params after `dl`, and `dl` already correct
        (
            "https://www.dropbox.com/s/a1b2/data.csv?dl=1&st=q9",
            ShareLinkKind.FILE,
        ),
        # http, and the host without `www.`
        ("http://www.dropbox.com/s/a1b2/data.csv?dl=0", ShareLinkKind.FILE),
        ("https://dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz", ShareLinkKind.FILE),
    ],
)
def test_dropbox_links_are_recognised_and_forced_to_dl_1(url, kind):
    resolved = resolve_share_url(url)
    assert resolved.provider == "dropbox"
    assert resolved.kind is kind
    assert util.is_dropbox_url(url) is True
    # `dl=1` is a correctness requirement: `dl=0` serves the archive or an HTML page
    # depending on the User-Agent.
    assert resolved.direct_url.endswith("dl=1")
    assert "dl=0" not in resolved.direct_url


def test_dropbox_folder_link_is_an_archive_not_a_file():
    """A folder link downloads as one ZIP of N members -- a different operation."""
    file_link = resolve_share_url("https://www.dropbox.com/scl/fi/a1/x.mp4?rlkey=z")
    folder_link = resolve_share_url("https://www.dropbox.com/scl/fo/a1/x?rlkey=z")
    assert file_link.kind is ShareLinkKind.FILE
    assert folder_link.kind is ShareLinkKind.ARCHIVE
    assert file_link.kind is not folder_link.kind


def test_dropbox_rewrite_preserves_every_other_parameter_verbatim():
    """`rlkey` is a bearer secret: corrupting it makes the link a 404."""
    url = "https://www.dropbox.com/scl/fo/q7x/AAB?rlkey=aB-_9~x&st=q9&dl=0#frag"
    direct = resolve_share_url(url).direct_url
    assert (
        direct == "https://www.dropbox.com/scl/fo/q7x/AAB?rlkey=aB-_9~x&st=q9&dl=1#frag"
    )


def test_dropbox_duplicate_dl_params_collapse_to_one():
    url = "https://www.dropbox.com/s/a1/x.csv?dl=0&st=q&dl=0"
    assert resolve_share_url(url).direct_url == (
        "https://www.dropbox.com/s/a1/x.csv?st=q&dl=1"
    )


def test_non_share_dropbox_urls_fall_through_to_passthrough():
    """A Dropbox web page is not a share link; don't claim it."""
    resolved = resolve_share_url("https://www.dropbox.com/home")
    assert resolved.provider == "http"
    assert util.is_dropbox_url("https://www.dropbox.com/home") is False


def test_unknown_dropbox_scl_subtype_is_refused_not_guessed():
    resolved = resolve_share_url("https://www.dropbox.com/scl/zz/a1/x?rlkey=z")
    assert resolved.provider == "dropbox"
    assert resolved.kind is ShareLinkKind.UNKNOWN
    assert resolved.direct_url is None
    assert "add_share_link_resolver" in resolved.reason


# --------------------------------------------------------------------------------------
# Google Drive
#
# Regression guard for the folder branch: `google_drive_download_url` used to build
# a *file* download URL out of a *folder* id.


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/1AbC/view",
        "https://drive.google.com/file/d/1AbC/edit",
        "https://drive.google.com/file/d/1AbC/preview",
        "https://drive.google.com/file/d/1AbC",
        "https://drive.google.com/file/d/1AbC/view?usp=sharing",
        "https://drive.google.com/open?id=1AbC",
    ],
)
def test_google_drive_file_links_resolve_to_the_download_endpoint(url):
    resolved = resolve_share_url(url)
    assert resolved.provider == "google_drive"
    assert resolved.kind is ShareLinkKind.FILE
    assert resolved.direct_url == "https://drive.google.com/uc?export=download&id=1AbC"


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/uc?export=download&id=1AbC",
        "https://drive.usercontent.google.com/download?id=1AbC&export=download",
    ],
)
def test_already_direct_google_drive_urls_pass_through_untouched(url):
    """Rebuilding them would drop whatever extra parameters they carry."""
    resolved = resolve_share_url(url)
    assert resolved.provider == "google_drive"
    assert resolved.direct_url == url


def test_google_drive_resourcekey_is_preserved():
    """Link-shared files created before Drive's 2021 change need it to be readable."""
    url = "https://drive.google.com/file/d/1AbC/view?usp=sharing&resourcekey=0-xY_z"
    assert resolve_share_url(url).direct_url == (
        "https://drive.google.com/uc?export=download&id=1AbC&resourcekey=0-xY_z"
    )


@pytest.mark.parametrize(
    "url,folder_id",
    [
        ("https://drive.google.com/drive/folders/1FoLdEr", "1FoLdEr"),
        ("https://drive.google.com/drive/u/0/folders/1FoLdEr", "1FoLdEr"),
        ("https://drive.google.com/drive/u/12/folders/1FoLdEr", "1FoLdEr"),
    ],
)
def test_google_drive_folder_is_refused_never_resolved_as_a_file(url, folder_id):
    resolved = resolve_share_url(url)
    assert resolved.provider == "google_drive"
    assert resolved.kind is ShareLinkKind.FOLDER
    # The precise defect being guarded: a folder id in a *file* download URL.
    assert resolved.direct_url is None
    assert resolved.direct_url != (
        f"https://drive.google.com/uc?export=download&id={folder_id}"
    )
    assert "Drive API" in resolved.reason
    with pytest.raises(ShareLinkResolutionError):
        direct_download_url(url)
    with pytest.raises(ShareLinkResolutionError):
        util.google_drive_download_url(url)
    # ...but it is still *recognised*, so the route fires and the caller gets the
    # error instead of silently downloading Drive's HTML folder page.
    assert util.is_google_drive_url(url) is True


@pytest.mark.parametrize(
    "url,app",
    [
        ("https://docs.google.com/document/d/1Do/edit", "document"),
        ("https://docs.google.com/spreadsheets/d/1Sh/edit#gid=0", "spreadsheets"),
        ("https://docs.google.com/presentation/d/1Pr/edit", "presentation"),
        ("https://docs.google.com/forms/d/1Fo/viewform", "forms"),
    ],
)
def test_google_workspace_docs_are_refused_not_mis_resolved(url, app):
    resolved = resolve_share_url(url)
    assert resolved.provider == "google_drive"
    assert resolved.direct_url is None
    assert app in resolved.reason
    assert util.is_google_drive_url(url) is True


def test_google_drive_download_url_rejects_a_non_drive_url():
    with pytest.raises(ValueError):
        util.google_drive_download_url("https://example.com/file.mp4")


# --------------------------------------------------------------------------------------
# Host spoofing
#
# Regression guard: `_google_drive_id` used to `.search()` the raw URL string, so any
# URL merely *containing* "drive.google.com/file/d/<id>" was routed to Drive -- i.e.
# graze fetched from a host the user never named.


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/x?u=drive.google.com/file/d/1AbC",
        "https://evil.example.com/drive.google.com/file/d/1AbC/view",
        "https://drive.google.com.evil.example.com/file/d/1AbC/view",
        "https://example.com/s/a1b2/data.csv?dl=0",
        "https://www.dropbox.com.evil.example.com/scl/fi/a1/x?dl=0",
    ],
)
def test_a_lookalike_host_is_never_treated_as_the_provider(url):
    resolved = resolve_share_url(url)
    assert resolved.provider == "http"
    assert resolved.direct_url == url
    assert util.is_google_drive_url(url) is False
    assert util.is_dropbox_url(url) is False


def test_host_matching_ignores_case_and_port():
    resolved = resolve_share_url("https://Drive.Google.com:443/file/d/1AbC/view")
    assert resolved.provider == "google_drive"


# --------------------------------------------------------------------------------------
# OneDrive -- recognised, and honestly refused


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://1drv.ms/f/s!AbCd", ShareLinkKind.FOLDER),
        ("https://1drv.ms/u/s!AbCd", ShareLinkKind.UNKNOWN),
        ("https://1drv.ms/v/s!AbCd", ShareLinkKind.UNKNOWN),
        (
            "https://contoso-my.sharepoint.com/:f:/g/personal/a/EaB",
            ShareLinkKind.FOLDER,
        ),
        (
            "https://contoso-my.sharepoint.com/:v:/g/personal/a/EaB",
            ShareLinkKind.UNKNOWN,
        ),
        ("https://onedrive.live.com/?id=root&cid=ABC", ShareLinkKind.UNKNOWN),
    ],
)
def test_onedrive_links_are_recognised_and_refused(url, kind):
    resolved = resolve_share_url(url)
    assert resolved.provider == "onedrive"
    assert resolved.kind is kind
    assert resolved.direct_url is None
    assert "UNVERIFIED" in resolved.reason
    assert util.is_onedrive_url(url) is True


def test_an_ordinary_sharepoint_path_is_not_a_share_link():
    url = "https://contoso.sharepoint.com/sites/x/Shared%20Documents/clip.mp4"
    assert resolve_share_url(url).provider == "http"


# --------------------------------------------------------------------------------------
# Plain URLs, and non-URLs


def test_plain_https_url_passes_through():
    url = "https://example.com/assets/video.mp4?token=abc"
    resolved = resolve_share_url(url)
    assert (resolved.provider, resolved.kind) == ("http", ShareLinkKind.FILE)
    assert resolved.direct_url == url
    assert direct_download_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/a.mp4", "file:///etc/hosts", "not a url", "", "example.com/a"],
)
def test_non_http_inputs_are_refused_with_a_reason(url):
    resolved = resolve_share_url(url)
    assert resolved.provider == "unknown"
    assert resolved.direct_url is None
    assert resolved.reason
    with pytest.raises(ShareLinkResolutionError):
        direct_download_url(url)


def test_surrounding_whitespace_is_stripped():
    resolved = resolve_share_url("  https://www.dropbox.com/s/a1/x.csv?dl=0\n")
    assert resolved.url == "https://www.dropbox.com/s/a1/x.csv?dl=0"
    assert resolved.direct_url == "https://www.dropbox.com/s/a1/x.csv?dl=1"


# --------------------------------------------------------------------------------------
# The data model and the registry


def test_an_unresolved_link_must_carry_a_reason():
    """An adapter that refuses silently is a bug; the dataclass enforces it."""
    with pytest.raises(ValueError, match="must carry a reason"):
        ResolvedShareLink("https://x/y", "nope", ShareLinkKind.UNKNOWN)


def test_resolved_property_tracks_direct_url():
    assert ResolvedShareLink("u", "http", ShareLinkKind.FILE, "u").resolved is True
    assert (
        ResolvedShareLink("u", "p", ShareLinkKind.UNKNOWN, None, "why").resolved
        is False
    )


def test_share_link_kind_str_equals_its_value():
    """`str, Enum` formatting changed in 3.11; pin it so messages don't drift."""
    assert str(ShareLinkKind.ARCHIVE) == "archive"
    assert f"{ShareLinkKind.ARCHIVE}" == "archive"
    assert ShareLinkKind.ARCHIVE == "archive"


def test_resolvers_can_be_injected_without_touching_the_global_registry():
    def only_mine(url):
        if url.startswith("https://mine.example/"):
            return ResolvedShareLink(
                url=url,
                provider="mine",
                kind=ShareLinkKind.FILE,
                direct_url=url + "?raw=1",
            )

    resolvers = {"mine": only_mine}
    assert resolve_share_url(
        "https://mine.example/x", resolvers=resolvers
    ).provider == ("mine")
    # Dropbox is not in the injected registry, so it falls through to pass-through.
    assert (
        resolve_share_url(
            "https://www.dropbox.com/s/a1/x.csv?dl=0", resolvers=resolvers
        ).provider
        == "http"
    )
    assert "mine" not in share_link_resolvers


def test_add_share_link_resolver_extends_the_default_registry():
    def resolve_example(url):
        if url.startswith("https://newhost.example/"):
            return ResolvedShareLink(
                url=url, provider="newhost", kind=ShareLinkKind.ARCHIVE, direct_url=url
            )

    add_share_link_resolver("newhost", resolve_example)
    try:
        resolved = resolve_share_url("https://newhost.example/bundle")
        assert (resolved.provider, resolved.kind) == ("newhost", ShareLinkKind.ARCHIVE)
        assert util.is_share_url_of("newhost")("https://newhost.example/bundle") is True
    finally:
        del share_link_resolvers["newhost"]


def test_every_default_resolver_returns_none_for_a_foreign_url():
    """ "Not mine" must be `None`, so the next adapter gets a turn."""
    for provider, resolve in share_link_resolvers.items():
        assert resolve("https://example.com/a.mp4") is None, provider


# --------------------------------------------------------------------------------------
# The transport-side routing that consumes the resolution


def _no_network(*args, **kwargs):
    raise AssertionError("a share-link test attempted a network download")


def test_special_url_routes_resolve_before_downloading(monkeypatch):
    seen = []
    monkeypatch.setattr(
        util, "download_url_contents", lambda url, file, **kw: seen.append(url)
    )
    util.download_from_special_url("https://www.dropbox.com/scl/fo/a1/x?rlkey=z&dl=0")
    assert seen == ["https://www.dropbox.com/scl/fo/a1/x?rlkey=z&dl=1"]


def test_an_unresolvable_route_raises_instead_of_fetching_the_share_page(monkeypatch):
    """The failure mode being prevented: storing an HTML page as if it were the asset."""
    monkeypatch.setattr(util, "download_url_contents", _no_network)
    for url in (
        "https://1drv.ms/f/s!AbCd",
        "https://drive.google.com/drive/folders/1FoLdEr",
        "https://docs.google.com/document/d/1Do/edit",
    ):
        assert util.is_special_url(url) is True
        with pytest.raises(ShareLinkResolutionError):
            util.download_from_special_url(url)


def test_a_plain_url_is_not_routed_as_special():
    """Pass-through is the fallback, not a registered route -- otherwise every URL
    in the world would be a "special url" and `Internet` would reroute all of them."""
    assert util.is_special_url("https://example.com/a.mp4") is False
    assert util.is_special_url("https://raw.githubusercontent.com/a/b/c.py") is False


# --------------------------------------------------------------------------------------
# Doctests
#
# `testpaths = ["tests"]`, so CI's `--doctest-modules` never reaches `graze/`.
# Run the module's doctests explicitly so its examples are actually gated.


def test_share_links_doctests():
    import graze.share_links

    results = doctest.testmod(
        graze.share_links,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    assert results.failed == 0, f"{results.failed} doctest failure(s)"


def test_util_share_link_doctests():
    results = doctest.testmod(
        util,
        optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE,
    )
    assert results.failed == 0, f"{results.failed} doctest failure(s)"

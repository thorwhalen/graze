"""Pure (network-free) resolution of cloud share links to direct-download URLs.

A *share link* is what a person copies out of Dropbox / Google Drive / OneDrive.
It is **not** a download URL: fetching it usually gets you an HTML preview page,
and — worse — what you get can depend on your ``User-Agent`` rather than on the
link. This module maps a pasted share link to a description of what it actually
denotes::

    share link  ->  ResolvedShareLink(provider, kind, direct_url, reason)

Everything here is a ``str -> description`` mapping. **No function in this module
opens a socket**, which is the whole point: resolution is deterministic and
testable offline, while fetching (redirect policy, byte caps, content-type
assertions, SSRF protection) is a separate concern that belongs to the transport
layer, and archive expansion (a folder link is a ZIP, see :class:`ShareLinkKind`)
belongs to the caller.

The two things a caller needs to know before fetching:

- **the direct URL** — or, honestly, that there isn't one (some links genuinely
  need a provider API, and this module refuses rather than guess);
- **the kind** — a *file* and a *folder* are different operations. A Dropbox
  folder link downloads as a single ZIP that must be expanded into N assets.

Simple use — give me something I can fetch, or tell me why not:

>>> direct_download_url('https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz&dl=0')
'https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz&dl=1'

>>> direct_download_url('https://drive.google.com/drive/folders/1AbCdEf')
Traceback (most recent call last):
    ...
graze.share_links.ShareLinkResolutionError: Cannot resolve this google_drive link...

Full use — the whole description, including what kind of thing it is:

>>> r = resolve_share_url('https://www.dropbox.com/scl/fo/x9/y?rlkey=zz&dl=0')
>>> r.provider, r.kind.value, r.resolved
('dropbox', 'archive', True)
>>> r.direct_url
'https://www.dropbox.com/scl/fo/x9/y?rlkey=zz&dl=1'

``kind == 'archive'`` is the signal that the bytes are a ZIP of many members,
not one asset -- ``dol.FilesOfZip`` is the tool for that half.

A URL that is nobody's share link passes through unchanged:

>>> r = resolve_share_url('https://example.com/video.mp4')
>>> r.provider, r.direct_url
('http', 'https://example.com/video.mp4')

Adding a provider is open-closed -- register an adapter, no core edits:

>>> def resolve_my_host(url):
...     if url.startswith('https://my.host/dl/'):
...         return ResolvedShareLink(
...             url=url, provider='my_host', kind=ShareLinkKind.FILE,
...             direct_url=url + '?raw=1',
...         )
>>> add_share_link_resolver('my_host', resolve_my_host)
>>> resolve_share_url('https://my.host/dl/thing').direct_url
'https://my.host/dl/thing?raw=1'
>>> del share_link_resolvers['my_host']  # (cleaning up after the example)

Note: this module is **not** a security boundary. It will happily hand back a URL
pointing anywhere; validating scheme/port/address and re-validating every redirect
hop is the transport layer's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit, unquote


# --------------------------------------------------------------------------------------
# The vocabulary


class ShareLinkKind(str, Enum):
    """What a share link denotes -- a file, an archive, a folder, or unknown.

    ``ARCHIVE`` is a refinement of ``FILE``: the URL still resolves to one blob,
    but that blob is a ZIP the caller must expand into N assets. Providers render
    *folder* links this way (Dropbox does so even for a single-file folder).

    ``FOLDER`` is the honest answer when a link denotes a folder and the provider
    offers **no** URL that downloads it -- listing it needs an API credential.

    >>> ShareLinkKind.ARCHIVE.value
    'archive'
    >>> ShareLinkKind('folder') is ShareLinkKind.FOLDER
    True
    """

    FILE = "file"
    ARCHIVE = "archive"
    FOLDER = "folder"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        # Keeps str()/format() equal to the value on every Python version
        # (bare `str, Enum` mixins changed __format__ behaviour in 3.11).
        return self.value


class ShareLinkResolutionError(ValueError):
    """Raised when a share link cannot be resolved to a direct-download URL."""


@dataclass(frozen=True)
class ResolvedShareLink:
    """What a share URL denotes, and how (or whether) to fetch it.

    Args:
        url: The share URL as given (stripped of surrounding whitespace).
        provider: Provider slug, e.g. ``'dropbox'``, ``'google_drive'``,
            ``'onedrive'``, ``'http'`` (a plain URL that is nobody's share link),
            or ``'unknown'``.
        kind: See :class:`ShareLinkKind`.
        direct_url: A URL whose response body is the content -- or ``None`` when
            the link cannot be resolved without a provider API.
        reason: Why ``direct_url`` is ``None``. Required whenever it is.

    ``direct_url`` and ``kind`` are independent: a Google Workspace document is a
    ``FILE`` that still has no resolvable download URL.

    >>> r = ResolvedShareLink('https://x/y', 'http', ShareLinkKind.FILE, 'https://x/y')
    >>> r.resolved
    True

    An unresolved link must say why -- an adapter that refuses silently is a bug:

    >>> ResolvedShareLink('https://x/y', 'nope', ShareLinkKind.UNKNOWN)
    Traceback (most recent call last):
        ...
    ValueError: An unresolved ResolvedShareLink must carry a reason (url: https://x/y)
    """

    url: str
    provider: str
    kind: ShareLinkKind
    direct_url: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self):
        if self.direct_url is None and not self.reason:
            raise ValueError(
                f"An unresolved ResolvedShareLink must carry a reason (url: {self.url})"
            )

    @property
    def resolved(self) -> bool:
        """True when there is a direct URL to fetch."""
        return self.direct_url is not None


#: An adapter: given a URL, return its resolution, or ``None`` for "not mine".
ShareLinkResolver = Callable[[str], Optional[ResolvedShareLink]]


# --------------------------------------------------------------------------------------
# URL string surgery (verbatim-preserving: share links carry bearer secrets)


def _force_query_param(url: str, key: str, value: str) -> str:
    """Set query param ``key`` to ``value``, leaving every other byte untouched.

    Deliberately does *not* round-trip through ``parse_qsl``/``urlencode``: share
    links carry credentials in the query (Dropbox's ``rlkey``, Drive's
    ``resourcekey``) and re-encoding them is a needless way to corrupt one.

    >>> _force_query_param('https://x.com/a?rlkey=Z_-9&dl=0', 'dl', '1')
    'https://x.com/a?rlkey=Z_-9&dl=1'
    >>> _force_query_param('https://x.com/a', 'dl', '1')
    'https://x.com/a?dl=1'
    >>> _force_query_param('https://x.com/a?dl=0&st=q&dl=0#frag', 'dl', '1')
    'https://x.com/a?st=q&dl=1#frag'
    """
    parts = urlsplit(url)
    kept = [
        component
        for component in parts.query.split("&")
        if component and component.split("=", 1)[0] != key
    ]
    kept.append(f"{key}={value}")
    return urlunsplit(parts._replace(query="&".join(kept)))


def _query_value(query: str, key: str) -> Optional[str]:
    """First value of ``key`` in a raw query string, percent-decoded, else None.

    >>> _query_value('export=download&id=1A-b_C', 'id')
    '1A-b_C'
    >>> _query_value('export=download', 'id') is None
    True
    """
    for component in query.split("&"):
        name, _, value = component.partition("=")
        if name == key:
            return unquote(value)
    return None


def _host_of(url: str) -> str:
    """Lower-cased host of a URL, without port or userinfo.

    Parsing the host is what stops a substring match from being spoofable:
    ``https://evil.example/?u=drive.google.com/file/d/x`` is not a Drive link.

    >>> _host_of('https://Drive.Google.com:443/file/d/x')
    'drive.google.com'
    >>> _host_of('https://evil.example/?u=drive.google.com/file/d/x')
    'evil.example'
    """
    return (urlsplit(url).hostname or "").lower()


# --------------------------------------------------------------------------------------
# Dropbox
#
# Measured (2026-08-06, live links): www.dropbox.com answers every share link with a
# 302 to a *.dl.dropboxusercontent.com host; a FOLDER link's final response is
# `content-type: application/zip` + `content-disposition: attachment;
# filename="<folder>.zip"` + magic PK\x03\x04 -- i.e. an archive, not a listing.
# And `dl=0` is User-Agent dependent (a wget UA got the zip; a browser UA got 224 KB
# of HTML), while `dl=1` returned the archive for every client tested. Forcing dl=1
# is therefore a *correctness* requirement, not a convenience.

DROPBOX_HOSTS = ("www.dropbox.com", "dropbox.com")

#: Share-link path prefixes -> what they denote. ``/s/`` + ``/sh/`` are the legacy
#: forms; ``/scl/fi/`` + ``/scl/fo/`` are the ones Dropbox issues today.
DROPBOX_PATH_KINDS = (
    ("/scl/fi/", ShareLinkKind.FILE),
    ("/scl/fo/", ShareLinkKind.ARCHIVE),
    ("/s/", ShareLinkKind.FILE),
    ("/sh/", ShareLinkKind.ARCHIVE),
)

_DROPBOX_SHARE_NAMESPACES = ("/scl/", "/s/", "/sh/")


def resolve_dropbox(url: str) -> Optional[ResolvedShareLink]:
    """Resolve a Dropbox share link by forcing ``dl=1``.

    Both the modern ``/scl/`` forms and the legacy ``/s/`` + ``/sh/`` forms; every
    other query parameter (notably ``rlkey``, which is a bearer secret) is kept
    byte-for-byte.

    >>> r = resolve_dropbox('https://www.dropbox.com/s/a1/data.csv?dl=0')
    >>> r.kind.value, r.direct_url
    ('file', 'https://www.dropbox.com/s/a1/data.csv?dl=1')

    A folder link is an *archive* -- one ZIP holding N members:

    >>> r = resolve_dropbox('https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&st=t1')
    >>> r.kind.value, r.direct_url
    ('archive', 'https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&st=t1&dl=1')

    Non-share Dropbox URLs are not this adapter's business:

    >>> resolve_dropbox('https://www.dropbox.com/home') is None
    True
    >>> resolve_dropbox('https://example.com/s/a1/data.csv?dl=0') is None
    True
    """
    if _host_of(url) not in DROPBOX_HOSTS:
        return None
    path = urlsplit(url).path
    for prefix, kind in DROPBOX_PATH_KINDS:
        if path.startswith(prefix):
            return ResolvedShareLink(
                url=url,
                provider="dropbox",
                kind=kind,
                direct_url=_force_query_param(url, "dl", "1"),
            )
    if any(path.startswith(namespace) for namespace in _DROPBOX_SHARE_NAMESPACES):
        return ResolvedShareLink(
            url=url,
            provider="dropbox",
            kind=ShareLinkKind.UNKNOWN,
            reason=(
                "Unrecognised Dropbox share-link form. graze knows /scl/fi/ and /s/ "
                "(file) and /scl/fo/ and /sh/ (folder, downloads as a ZIP); this path "
                f"is {path!r}. Measure what the link serves, then register an adapter "
                "with add_share_link_resolver."
            ),
        )
    return None


# --------------------------------------------------------------------------------------
# Google Drive

GOOGLE_DRIVE_HOSTS = ("drive.google.com", "drive.usercontent.google.com")
GOOGLE_WORKSPACE_HOST = "docs.google.com"

_gdrive_file_path_re = re.compile(r"^/file/d/([\w-]+)")
_gdrive_folder_path_re = re.compile(r"^/drive/(?:u/\d+/)?folders/([\w-]+)")
_gworkspace_app_re = re.compile(r"^/(document|spreadsheets|presentation|forms)/d/")

#: A Workspace path that already names an export / publish endpoint (`/export`,
#: `/export/pdf`, `/pub`, `/pubhtml`, `/gviz/tq`) is a *direct* URL: the caller has
#: already made the format choice this module otherwise refuses to make for them.
_gworkspace_direct_re = re.compile(r"/(?:export|pub[a-z]*|gviz)(?:/|$)")

#: Paths that are already direct-download endpoints -- pass them through untouched
#: rather than rebuild them, so any extra parameters they carry survive.
_GDRIVE_DIRECT_PATH_RES = {
    "drive.google.com": re.compile(r"^/(?:u/\d+/)?uc$"),
    "drive.usercontent.google.com": re.compile(r"^/download$"),
}


def _google_drive_file_url(file_id: str, *, resource_key: Optional[str] = None) -> str:
    """Build Drive's direct-download URL for a file id.

    >>> _google_drive_file_url('1AbC')
    'https://drive.google.com/uc?export=download&id=1AbC'
    >>> _google_drive_file_url('1AbC', resource_key='0-xy')
    'https://drive.google.com/uc?export=download&id=1AbC&resourcekey=0-xy'
    """
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    if resource_key:
        url += f"&resourcekey={resource_key}"
    return url


def resolve_google_drive(url: str) -> Optional[ResolvedShareLink]:
    """Resolve a Google Drive / Google Workspace URL.

    Files resolve; **folders and Workspace documents are refused**, because
    neither has a plain-URL download and pretending otherwise is how a folder id
    ends up in a file-download URL.

    >>> resolve_google_drive('https://drive.google.com/file/d/1AbC/view').direct_url
    'https://drive.google.com/uc?export=download&id=1AbC'

    A ``resourcekey`` (required by link-shared files created before 2021) is kept:

    >>> r = resolve_google_drive('https://drive.google.com/file/d/1AbC/view?resourcekey=0-x')
    >>> r.direct_url
    'https://drive.google.com/uc?export=download&id=1AbC&resourcekey=0-x'

    A folder is a folder -- refused, with the reason and the id to hand:

    >>> r = resolve_google_drive('https://drive.google.com/drive/folders/1FoLd')
    >>> r.kind.value, r.direct_url is None
    ('folder', True)
    >>> print(r.reason)  # doctest: +ELLIPSIS
    Google Drive folder links have no direct-download URL...

    So is a native Google doc -- a file, but not a downloadable one:

    >>> r = resolve_google_drive('https://docs.google.com/spreadsheets/d/1Sh/edit')
    >>> r.kind.value, r.direct_url is None
    ('file', True)

    ...*unless* the caller already chose a format, which is the only thing the
    refusal above was ever about:

    >>> u = 'https://docs.google.com/spreadsheets/d/1Sh/export?format=csv&gid=0'
    >>> resolve_google_drive(u).direct_url == u
    True

    >>> resolve_google_drive('https://example.com/file/d/1AbC/view') is None
    True
    """
    host = _host_of(url)
    parts = urlsplit(url)

    if host == GOOGLE_WORKSPACE_HOST:
        app_match = _gworkspace_app_re.match(parts.path)
        if app_match is None:
            return None
        if _gworkspace_direct_re.search(parts.path):
            # The caller already picked a format -- that is the whole decision this
            # adapter declines to make, so there is nothing left to refuse.
            return ResolvedShareLink(
                url=url,
                provider="google_drive",
                kind=ShareLinkKind.FILE,
                direct_url=url,
            )
        app = app_match.group(1)
        return ResolvedShareLink(
            url=url,
            provider="google_drive",
            kind=ShareLinkKind.FILE,
            reason=(
                f"Google Workspace ({app}) documents are not stored as files: they "
                "have to be exported, and the export format is a caller decision "
                "(and some apps offer no export at all). graze refuses rather than "
                "pick a format for you. Pass the export endpoint itself -- e.g. "
                ".../export?format=<fmt>, .../pub?output=<fmt>, .../gviz/tq?... -- "
                "and graze will fetch it as given."
            ),
        )

    if host not in GOOGLE_DRIVE_HOSTS:
        return None

    # Total: every host in GOOGLE_DRIVE_HOSTS is a key, and we returned above otherwise.
    if _GDRIVE_DIRECT_PATH_RES[host].match(parts.path) and _query_value(
        parts.query, "id"
    ):
        return ResolvedShareLink(
            url=url,
            provider="google_drive",
            kind=ShareLinkKind.FILE,
            direct_url=url,  # already a download endpoint; keep its parameters
        )

    folder_match = _gdrive_folder_path_re.match(parts.path)
    if folder_match:
        folder_id = folder_match.group(1)
        return ResolvedShareLink(
            url=url,
            provider="google_drive",
            kind=ShareLinkKind.FOLDER,
            reason=(
                "Google Drive folder links have no direct-download URL: enumerating "
                "a folder needs the Drive API (files.list with "
                f"q=\"'{folder_id}' in parents\") and a credential. graze refuses "
                "rather than resolve a folder id as if it were a file id."
            ),
        )

    file_match = _gdrive_file_path_re.match(parts.path)
    file_id = file_match.group(1) if file_match else None
    if file_id is None and parts.path == "/open":
        file_id = _query_value(parts.query, "id")
    if file_id is None:
        return None

    return ResolvedShareLink(
        url=url,
        provider="google_drive",
        kind=ShareLinkKind.FILE,
        direct_url=_google_drive_file_url(
            file_id, resource_key=_query_value(parts.query, "resourcekey")
        ),
    )


# --------------------------------------------------------------------------------------
# OneDrive / SharePoint
#
# Recognised but NOT resolved, on purpose. graze has no *measured* contract for this
# provider (unlike Dropbox above), and a share link fetched directly generally returns
# an HTML page rather than the file -- so passing it through as an ordinary URL would
# silently store a web page as if it were the asset. Refusing says so out loud.

ONEDRIVE_HOSTS = ("1drv.ms", "onedrive.live.com")
_SHAREPOINT_HOST_SUFFIX = ".sharepoint.com"

#: `1drv.ms/f/...` and `<tenant>.sharepoint.com/:f:/...` are the folder markers.
_onedrive_short_re = re.compile(r"^/(?P<marker>[a-zA-Z])/")
_sharepoint_share_re = re.compile(r"^/:(?P<marker>[a-zA-Z]):/")
_ONEDRIVE_FOLDER_MARKER = "f"

ONEDRIVE_UNRESOLVED_REASON = (
    "graze has no measured resolution rule for OneDrive/SharePoint share links, so "
    "it refuses rather than guess -- fetching one directly generally returns an HTML "
    "page, not the file. The candidate rule to measure (UNVERIFIED) is the anonymous "
    "share endpoint https://api.onedrive.com/v1.0/shares/u!<b>/root/content, where "
    "<b> is the base64url encoding of the share URL with '=' padding stripped. "
    "Measure it against a live link, then register an adapter with "
    "add_share_link_resolver."
)


def resolve_onedrive(url: str) -> Optional[ResolvedShareLink]:
    """Recognise a OneDrive / SharePoint share link, and refuse it.

    >>> r = resolve_onedrive('https://1drv.ms/f/s!AbCd')
    >>> r.provider, r.kind.value, r.direct_url is None
    ('onedrive', 'folder', True)

    >>> r = resolve_onedrive('https://contoso-my.sharepoint.com/:v:/g/personal/x/EaB')
    >>> r.provider, r.kind.value
    ('onedrive', 'unknown')

    An ordinary SharePoint document path is not a share link:

    >>> resolve_onedrive('https://contoso.sharepoint.com/sites/x/clip.mp4') is None
    True
    """
    host = _host_of(url)
    path = urlsplit(url).path
    if host in ONEDRIVE_HOSTS:
        match = _onedrive_short_re.match(path) if host == "1drv.ms" else None
    elif host.endswith(_SHAREPOINT_HOST_SUFFIX):
        match = _sharepoint_share_re.match(path)
        if match is None:
            return None
    else:
        return None
    marker = match.group("marker").lower() if match else None
    kind = (
        ShareLinkKind.FOLDER
        if marker == _ONEDRIVE_FOLDER_MARKER
        else ShareLinkKind.UNKNOWN
    )
    return ResolvedShareLink(
        url=url,
        provider="onedrive",
        kind=kind,
        reason=ONEDRIVE_UNRESOLVED_REASON,
    )


# --------------------------------------------------------------------------------------
# The registry


#: Provider adapters, tried in order; the first non-``None`` result wins. Open-closed:
#: extend it with :func:`add_share_link_resolver` instead of editing this module.
share_link_resolvers: dict[str, ShareLinkResolver] = {
    "dropbox": resolve_dropbox,
    "google_drive": resolve_google_drive,
    "onedrive": resolve_onedrive,
}


def add_share_link_resolver(provider: str, resolver: ShareLinkResolver) -> None:
    """Register (or replace) a provider adapter.

    ``resolver`` takes a URL and returns a :class:`ResolvedShareLink`, or ``None``
    to mean "not mine, try the next one". Replacing an existing provider keeps its
    position in the try-order; a new one is appended (so it is tried last).
    """
    share_link_resolvers[provider] = resolver


#: Schemes a plain URL may pass through with. Anything else is refused: this module
#: describes *fetchable web resources*, and unknown schemes are not that.
PASSTHROUGH_SCHEMES = ("http", "https")


def _resolve_plain_url(url: str) -> ResolvedShareLink:
    """Fallback for a URL that is nobody's share link: pass it through.

    ``kind`` is ``FILE`` in the sense of "one blob" -- whether that blob turns out
    to be a ZIP is a property of the *response*, which only the transport layer
    can see. Guessing it from a file extension here would be exactly the kind of
    silent mis-resolution this module exists to remove.

    >>> _resolve_plain_url('https://example.com/a.mp4').direct_url
    'https://example.com/a.mp4'
    >>> _resolve_plain_url('not a url').provider
    'unknown'
    """
    parts = urlsplit(url)
    if parts.scheme.lower() in PASSTHROUGH_SCHEMES and parts.netloc:
        return ResolvedShareLink(
            url=url, provider="http", kind=ShareLinkKind.FILE, direct_url=url
        )
    return ResolvedShareLink(
        url=url,
        provider="unknown",
        kind=ShareLinkKind.UNKNOWN,
        reason=(
            "Not an http(s) URL with a host, so there is nothing to fetch "
            f"(scheme={parts.scheme!r})."
        ),
    )


def resolve_share_url(
    url: str, *, resolvers: Optional[dict[str, ShareLinkResolver]] = None
) -> ResolvedShareLink:
    """Describe what a share URL denotes and how (or whether) to fetch it.

    Args:
        url: The URL as a user pasted it. Surrounding whitespace is stripped.
        resolvers: Adapters to try, in order. Defaults to
            :data:`share_link_resolvers`; pass your own to test in isolation.

    Returns:
        A :class:`ResolvedShareLink`. Never raises for an unresolvable link --
        the refusal is in the return value (``direct_url is None`` plus a
        ``reason``). Use :func:`direct_download_url` when you want the raise.

    >>> resolve_share_url('  https://www.dropbox.com/s/a1/x.csv?dl=0  ').direct_url
    'https://www.dropbox.com/s/a1/x.csv?dl=1'
    >>> resolve_share_url('https://example.com/a.mp4').provider
    'http'
    >>> resolve_share_url('ftp://example.com/a.mp4').resolved
    False
    """
    if resolvers is None:
        resolvers = share_link_resolvers
    url = url.strip()
    for resolve in resolvers.values():
        resolved = resolve(url)
        if resolved is not None:
            return resolved
    return _resolve_plain_url(url)


def direct_download_url(
    url: str, *, resolvers: Optional[dict[str, ShareLinkResolver]] = None
) -> str:
    """The URL to actually fetch, or raise :class:`ShareLinkResolutionError`.

    >>> direct_download_url('https://drive.google.com/file/d/1AbC/view')
    'https://drive.google.com/uc?export=download&id=1AbC'
    >>> direct_download_url('https://1drv.ms/u/s!AbCd')
    Traceback (most recent call last):
        ...
    graze.share_links.ShareLinkResolutionError: Cannot resolve this onedrive link...
    """
    resolved = resolve_share_url(url, resolvers=resolvers)
    if resolved.direct_url is None:
        raise ShareLinkResolutionError(
            f"Cannot resolve this {resolved.provider} link to a direct-download URL "
            f"({resolved.url}). {resolved.reason}"
        )
    return resolved.direct_url

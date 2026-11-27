"""Fetch one media file from a URL someone pasted: share link resolved, fetch guarded, bytes checked.

Three graze modules each answer one question about a caller-supplied URL;
:func:`fetch_media` asks them in order, so an app does not keep its own copy of the
glue (graze#18):

1. :mod:`graze.share_links` -- *what does the link denote?* A Dropbox or Google Drive
   share link becomes its direct-download URL; a folder link, or a link with no known
   rule (OneDrive, a Google Doc), is refused with the reason, before any network.
2. :mod:`graze.guarded` -- *is it safe to fetch?* Every hop is checked against the
   address policy (no localhost, private networks or cloud metadata), within a byte
   and a wall-clock budget.
3. :mod:`graze.content_kind` -- *did we get the thing?* The share host's sign-in or
   preview page, and a ZIP where one file was meant, are refused instead of being kept
   as media.

>>> media = fetch_media('https://www.dropbox.com/scl/fi/a1/memo.m4a?rlkey=z&dl=0',
...                     expect_kind='audio')  # doctest: +SKIP
>>> media.filename, media.provider  # doctest: +SKIP
('memo.m4a', 'dropbox')

What it raises is one of :data:`FETCH_MEDIA_ERRORS`, each with a message meant for the
person who pasted the link:

>>> fetch_media('https://drive.google.com/drive/folders/1AbC')
Traceback (most recent call last):
    ...
graze.share_links.ShareLinkResolutionError: That google_drive link is a folder; share the single file instead...

Messages from this module name a link by :func:`redact_url` only (scheme, host, first path
segment): share links carry bearer secrets in their path and query, and these messages are
meant to be shown. Errors raised by :mod:`graze.guarded` itself still carry the full URL and
the resolved address, so a web surface should word those itself rather than echo them.

Every keyword argument of :func:`graze.guarded.guarded_open` passes through (``max_bytes``,
``timeout``, ``is_allowed_address``, ``connector``...), so tests and self-hosted setups
use the same seams.
"""

from __future__ import annotations

import posixpath
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional
from urllib.parse import unquote, urlsplit

from graze.content_kind import (
    SNIFF_BYTES,
    ContentKindMismatch,
    assert_content_kind,
    sniff_content_family,
)
from graze.guarded import GuardedFetchError, HTTPStatusError, guarded_open
from graze.share_links import (
    ShareLinkKind,
    ShareLinkResolutionError,
    ShareLinkResolver,
    is_host_page,
    resolve_share_url,
)

__all__ = [
    "FetchedMedia",
    "fetch_media",
    "FETCH_MEDIA_ERRORS",
    "DFLT_REFUSE",
    "redact_url",
    "clean_filename",
]

#: What :func:`fetch_media` raises on purpose; catch this tuple at a surface.
FETCH_MEDIA_ERRORS = (ShareLinkResolutionError, ContentKindMismatch, GuardedFetchError)
#: Content families refused whatever ``expect_kind`` is: a web page is the share host's
#: sign-in or preview page, an archive is a folder link's ZIP.
DFLT_REFUSE = ("html", "archive")
_NOT_PUBLIC_STATUSES = frozenset({401, 403})
#: Declared types that mean "a page or a message", not media, when the bytes say nothing.
_TEXT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
MAX_FILENAME_CHARS = 255


def redact_url(url: str) -> str:
    """The URL with what can carry a secret removed: scheme, host and first path segment.

    >>> redact_url('https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=SECRET&dl=0')
    'https://www.dropbox.com/scl/…'
    >>> redact_url('not a url')
    '(a link)'
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(a link)"
    if not parts.scheme or not parts.hostname:
        return "(a link)"
    first = parts.path.lstrip("/").split("/", 1)[0]
    return f"{parts.scheme}://{parts.hostname}/{first + '/' if first else ''}…"


def clean_filename(name: str) -> str:
    """A file name safe to keep and show: no path, no control or format characters, bounded.

    >>> clean_filename('../../etc/passwd'), clean_filename('..'), clean_filename('a\\x07b.mp3')
    ('passwd', '', 'ab.mp3')
    """
    name = posixpath.basename(name.replace("\\", "/"))
    name = "".join(
        c for c in name if unicodedata.category(c) not in ("Cc", "Cf")
    ).strip()
    if name in (".", ".."):
        return ""
    if len(name) > MAX_FILENAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        keep = (
            MAX_FILENAME_CHARS - len(dot + ext)
            if dot and len(ext) <= 16
            else MAX_FILENAME_CHARS
        )
        name = (stem[:keep] + dot + ext) if dot and len(ext) <= 16 else name[:keep]
    return name


@dataclass(frozen=True)
class FetchedMedia:
    """The bytes of one fetched file, and what is known about them."""

    data: bytes = field(repr=False)
    filename: (
        str  #: from Content-Disposition, else the URL's last path segment ('' if none)
    )
    content_type: str  #: as the server declared it ('' if it did not)
    url: str  #: the final URL, after redirects
    provider: str  #: the share-link provider ('dropbox', 'google_drive'...) or 'http'

    @property
    def size(self) -> int:
        return len(self.data)


def _filename(headers, *urls: str) -> str:
    """The file name the server gave (RFC 6266, ``filename*`` included), else the URL's."""
    name = (
        clean_filename(headers.get_filename() or "")
        if hasattr(headers, "get_filename")
        else ""
    )
    if name:
        return name
    for url in urls:
        segment = clean_filename(unquote(urlsplit(url).path))
        if "." in segment:
            return segment
    return ""


def _content_type(headers: Mapping[str, str]) -> str:
    value = headers.get("Content-Type") or ""
    return value.split(";", 1)[0].strip().lower()


def fetch_media(
    url: str,
    *,
    expect_kind: Optional[str] = None,
    refuse: Iterable[str] = DFLT_REFUSE,
    resolvers: Optional[dict[str, ShareLinkResolver]] = None,
    **guarded_open_options,
) -> FetchedMedia:
    """Fetch the one file ``url`` points at (a share link or a plain URL).

    Args:
        url: What the person pasted. Surrounding whitespace is ignored.
        expect_kind: ``'audio'``, ``'video'``, ``'image'``... when given, recognised bytes
            of another family are refused (audio and video containers pass for each other,
            see :mod:`graze.content_kind`); unrecognised bytes pass.
        refuse: Content families refused in any case (default :data:`DFLT_REFUSE`).
        resolvers: Share-link adapters (default: :data:`graze.share_links.share_link_resolvers`).
        **guarded_open_options: Passed to :func:`graze.guarded.guarded_open`.

    An HTML page and an empty body are always refused when ``expect_kind`` is given (that is
    :func:`graze.content_kind.assert_content_kind`'s rule); ``refuse`` adds families refused
    in any case.

    Raises one of :data:`FETCH_MEDIA_ERRORS`.
    """
    if isinstance(refuse, str):
        raise TypeError(f"refuse takes families, not a string: refuse=({refuse!r},)")
    refuse = frozenset(refuse)
    try:
        resolved = resolve_share_url(url.strip(), resolvers=resolvers)
    except ShareLinkResolutionError:
        raise
    except (
        Exception
    ) as error:  # a malformed URL (urlsplit), or a resolver's own failure
        raise ShareLinkResolutionError(
            f"That is not a link that can be fetched ({type(error).__name__})."
        ) from error
    shown = redact_url(resolved.url)
    if resolved.kind in (ShareLinkKind.FOLDER, ShareLinkKind.ARCHIVE):
        raise ShareLinkResolutionError(
            f"That {resolved.provider} link is a folder; share the single file instead "
            f"({shown})."
        )
    if resolved.direct_url is None:
        raise ShareLinkResolutionError(
            f"Cannot fetch this {resolved.provider} link ({shown}). {resolved.reason}"
        )
    try:
        response = guarded_open(resolved.direct_url, **guarded_open_options)
    except HTTPStatusError as error:
        if resolved.provider != "http" and error.status in _NOT_PUBLIC_STATUSES:
            raise ShareLinkResolutionError(
                f"That {resolved.provider} link is not public (HTTP {error.status}): set it "
                f"to 'anyone with the link' and try again."
            ) from error
        raise
    with response:
        if is_host_page(resolved, response.headers):
            raise ContentKindMismatch(
                f"That {resolved.provider} link ({shown}) answered with its own page, not the file: "
                f"it is probably not shared publicly (or the file is too large to download "
                f"without signing in).",
                family="html",
                expect_kind=expect_kind,
            )
        data = response.read()
        declared = _content_type(response.headers)
        if not data:
            raise ContentKindMismatch(
                f"{shown} answered with an empty file.",
                family=None,
                expect_kind=expect_kind,
            )
        head = data[:SNIFF_BYTES]
        family = sniff_content_family(head)
        if family is None and declared in _TEXT_TYPES:
            family = (
                "html"  # a page or a message the sniffer could not place: not media
            )
        if family in refuse or (expect_kind and family == "html"):
            # assert_content_kind words the html and archive cases for the person
            if family == "html":
                head = b"<!doctype html>"
            assert_content_kind(head, expect_kind=expect_kind or "media", url=shown)
            raise ContentKindMismatch(
                f"got {family} bytes from {shown}",
                family=family,
                expect_kind=expect_kind,
            )
        if expect_kind:
            assert_content_kind(head, expect_kind=expect_kind, url=shown)
        return FetchedMedia(
            data=data,
            filename=_filename(
                response.headers, response.url, resolved.direct_url, resolved.url
            ),
            content_type=declared,
            url=response.url,
            provider=resolved.provider,
        )

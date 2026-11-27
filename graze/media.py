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

Every keyword argument of :func:`graze.guarded.guarded_open` passes through (``max_bytes``,
``timeout``, ``is_allowed_address``, ``connector``...), so tests and self-hosted setups
use the same seams.
"""

from __future__ import annotations

import posixpath
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

__all__ = ["FetchedMedia", "fetch_media", "FETCH_MEDIA_ERRORS", "DFLT_REFUSE"]

#: What :func:`fetch_media` raises on purpose; catch this tuple at a surface.
FETCH_MEDIA_ERRORS = (ShareLinkResolutionError, ContentKindMismatch, GuardedFetchError)
#: Content families refused whatever ``expect_kind`` is: a web page is the share host's
#: sign-in or preview page, an archive is a folder link's ZIP.
DFLT_REFUSE = ("html", "archive")
_NOT_PUBLIC_STATUSES = frozenset({401, 403})


@dataclass(frozen=True)
class FetchedMedia:
    """The bytes of one fetched file, and what is known about them."""

    data: bytes = field(repr=False)
    filename: str  #: from Content-Disposition, else the URL's last path segment ('' if none)
    content_type: str  #: as the server declared it ('' if it did not)
    url: str  #: the final URL, after redirects
    provider: str  #: the share-link provider ('dropbox', 'google_drive'...) or 'http'

    @property
    def size(self) -> int:
        return len(self.data)


def _filename(headers, *urls: str) -> str:
    """The file name the server gave (RFC 6266, ``filename*`` included), else the URL's."""
    name = headers.get_filename() if hasattr(headers, "get_filename") else None
    if name:
        return posixpath.basename(name.replace("\\", "/"))
    for url in urls:
        segment = posixpath.basename(unquote(urlsplit(url).path))
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

    Raises one of :data:`FETCH_MEDIA_ERRORS`.
    """
    resolved = resolve_share_url(url.strip(), resolvers=resolvers)
    if resolved.kind in (ShareLinkKind.FOLDER, ShareLinkKind.ARCHIVE):
        raise ShareLinkResolutionError(
            f"That {resolved.provider} link is a folder; share the single file instead "
            f"({resolved.url})."
        )
    if resolved.direct_url is None:
        raise ShareLinkResolutionError(
            f"Cannot fetch this {resolved.provider} link ({resolved.url}). {resolved.reason}"
        )
    refuse = frozenset(refuse)
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
                f"That {resolved.provider} link answered with its own page, not the file: "
                f"it is probably not shared publicly (or the file is too large to download "
                f"without signing in)."
            )
        data = response.read()
        head = data[:SNIFF_BYTES]
        family = sniff_content_family(head)
        if family in refuse:
            # assert_content_kind words the html and archive cases for the person
            assert_content_kind(head, expect_kind=expect_kind or "media", url=resolved.url)
            raise ContentKindMismatch(f"got {family} bytes from {resolved.url}")
        if expect_kind:
            assert_content_kind(head, expect_kind=expect_kind, url=resolved.url)
        return FetchedMedia(
            data=data,
            filename=_filename(response.headers, response.url, resolved.direct_url, resolved.url),
            content_type=_content_type(response.headers),
            url=response.url,
            provider=resolved.provider,
        )

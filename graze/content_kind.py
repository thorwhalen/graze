"""What the bytes actually turned out to be — magic-byte sniffing and kind assertion.

:mod:`graze.share_links` answers *what does this link denote* before a fetch. This module
answers the question one step later: **what did these bytes turn out to be**, and is that
what the caller asked for. Together they close the gap that makes cloud share links
treacherous — a share URL commonly answers ``HTTP 200`` with a *web page* (a sign-in
interstitial, a preview, a virus-scan warning), so an unguarded fetch "succeeds" and
stores an HTML document as if it were media.

Three things, in increasing order of usefulness:

>>> sniff_content_family(b'\\xff\\xd8\\xff\\xe0')      # what is it?
'image'

>>> assert_content_kind(b'<!doctype html><html>', expect_kind='video')
Traceback (most recent call last):
    ...
graze.content_kind.ContentKindMismatch: expected video bytes, got an HTML page...

>>> list(kind_checked([b'\\x89PNG\\r\\n\\x1a\\n', b'rest'], expect_kind='image'))
[b'\\x89PNG\\r\\n\\x1a\\nrest']

:func:`kind_checked` is the one to reach for: it asserts a stream's head **before any
chunk escapes**, so the guard holds for a consumer that writes incrementally, not only for
one that buffers.

Two deliberate design choices, both of which trade a missed catch for never refusing
something genuine:

- **Unknown is permissive.** An unrecognised payload passes. An exotic-but-legitimate
  codec must not be refused merely because this table has not heard of it.
- **Audio and video are not distinguished.** Magic bytes identify a *container*, and
  ISO-BMFF, Matroska and Ogg all carry audio-only and video streams alike — an audio-only
  ``.mp4`` opens with an ``ftyp`` a table cannot tell from a video's. Deciding needs the
  track list. Refusing on that evidence would reject real audio, which is strictly worse
  than declining to catch a mislabelled kind. Images are *not* in that pair; their
  signatures are unambiguous.

This module is dependency-free and network-free, like :mod:`graze.share_links`.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

__all__ = [
    "ContentKindMismatch",
    "SNIFF_BYTES",
    "sniff_content_family",
    "assert_content_kind",
    "kind_checked",
]


class ContentKindMismatch(ValueError):
    """The fetched bytes are not the kind of thing that was asked for."""


#: How many leading bytes are enough to classify a payload. Every signature this module
#: knows lives well inside the first 64; the margin absorbs a BOM plus leading whitespace
#: on a text-shaped payload.
SNIFF_BYTES = 512


_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),  # JPEG
    (b"GIF87a", "image"),
    (b"GIF89a", "image"),
    (b"BM", "image"),  # BMP
    (b"II*\x00", "image"),  # TIFF little-endian
    (b"MM\x00*", "image"),  # TIFF big-endian
    (b"\x1a\x45\xdf\xa3", "video"),  # Matroska / WebM
    (b"FLV\x01", "video"),
    (b"ID3", "audio"),  # MP3 with an ID3 tag
    (b"fLaC", "audio"),
    (b"OggS", "audio"),
    (b"PK\x03\x04", "archive"),
    (b"PK\x05\x06", "archive"),  # empty ZIP
    (b"Rar!\x1a\x07", "archive"),
    (b"\x1f\x8b", "archive"),  # gzip
    (b"7z\xbc\xaf\x27\x1c", "archive"),
)

# ISO base media (``....ftyp<brand>``). The brand, not the container, decides the family:
# an .m4a and an .mp4 are the same container.
_FTYP_AUDIO_BRANDS = frozenset({b"M4A ", b"M4B ", b"M4P ", b"F4A ", b"F4B "})
_FTYP_IMAGE_BRANDS = frozenset(
    {b"avif", b"avis", b"heic", b"heix", b"heim", b"heis", b"hevc", b"mif1", b"msf1"}
)

#: An HTML page is never the media a caller asked for, whatever kind that was.
_HTML_PREFIXES = (b"<!doctype html", b"<html", b"<!--", b"<?xml", b"<head", b"<body")

# Deliberately only ``{`` and ``[``. A looser rule (``t`` for ``true``, digits for a bare
# number) misfires on ordinary text and on binary payloads that happen to start with an
# ASCII letter — and a top-level JSON scalar is not a plausible artifact. Under-detecting
# JSON costs nothing here: unknown is permissive.
_JSON_FIRST_BYTES = (b"{", b"[")

#: Families a *container* signature genuinely cannot tell apart — see the module docstring.
_CONTAINER_AMBIGUOUS = frozenset({"audio", "video"})


def sniff_content_family(head: bytes) -> Optional[str]:
    """Classify the leading bytes of a payload, or ``None`` when unrecognised.

    Returns one of ``'image'``, ``'video'``, ``'audio'``, ``'json'``, ``'html'``,
    ``'archive'`` — or ``None``, which means *unknown*, not *bad*.

    >>> sniff_content_family(b'\\xff\\xd8\\xff\\xe0')
    'image'
    >>> sniff_content_family(b'\\x00\\x00\\x00\\x18ftypmp42')
    'video'
    >>> sniff_content_family(b'\\x00\\x00\\x00\\x18ftypM4A ')
    'audio'
    >>> sniff_content_family(b'RIFF\\x24\\x08\\x00\\x00WAVE')
    'audio'
    >>> sniff_content_family(b'  \\n<!DOCTYPE HTML PUBLIC>')
    'html'
    >>> sniff_content_family(b'PK\\x03\\x04\\x14\\x00')
    'archive'
    >>> sniff_content_family(b'{"a": 1}')
    'json'
    >>> sniff_content_family(b'\\x00\\x01\\x02\\x03') is None
    True
    """
    if not head:
        return None
    for prefix, family in _MAGIC_PREFIXES:
        if head.startswith(prefix):
            return family
    # RIFF containers carry the family in bytes 8..12.
    if head.startswith(b"RIFF") and len(head) >= 12:
        form = head[8:12]
        if form == b"WAVE":
            return "audio"
        if form == b"WEBP":
            return "image"
        if form == b"AVI ":
            return "video"
    # ISO base media: ``....ftyp<brand>``.
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _FTYP_AUDIO_BRANDS:
            return "audio"
        if brand in _FTYP_IMAGE_BRANDS:
            return "image"
        return "video"
    # MP3 frame sync (no ID3 tag).
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "audio"
    # Text-shaped payloads. Strip a UTF-8 BOM and leading whitespace first — a share-link
    # interstitial is served with neither, but a proxy's error page may carry both.
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if text[:1] == b"<":
        lowered = text[:16].lower()
        if any(lowered.startswith(p) for p in _HTML_PREFIXES):
            return "html"
        return None
    if text[:1] in _JSON_FIRST_BYTES:
        return "json"
    return None


def assert_content_kind(
    head: bytes, *, expect_kind: str, url: Optional[str] = None
) -> None:
    """Raise :class:`ContentKindMismatch` unless ``head`` looks like ``expect_kind``.

    The rule, branch by branch:

    - an **HTML** payload is refused for every kind — this is the exact shape of the
      silent corruption a share link produces (``HTTP 200``, ``text/html``, a couple of
      hundred KB of sign-in page);
    - an **archive** is refused with a message naming it, because that is what a *folder*
      share link resolves to (see :class:`graze.share_links.ShareLinkKind` ``ARCHIVE``);
    - a recognised media family that **disagrees** with ``expect_kind`` is refused — the
      assertion is against what was asked for, not merely against "not a web page";
    - **except audio against video**, allowed both ways (see the module docstring);
    - an **unrecognised** payload passes.

    Args:
        head: The leading bytes of the payload (see :data:`SNIFF_BYTES`).
        expect_kind: The declared kind — typically image/video/audio/json.
        url: Included in the message when given, so an operator can tell *which* fetch was
            refused without correlating logs.

    >>> assert_content_kind(b'\\x89PNG\\r\\n\\x1a\\n', expect_kind='image')  # passes
    >>> assert_content_kind(b'\\x00\\x00\\x00\\x18ftypisom', expect_kind='audio')  # ambiguous, passes
    >>> assert_content_kind(b'PK\\x03\\x04', expect_kind='video')
    Traceback (most recent call last):
        ...
    graze.content_kind.ContentKindMismatch: expected video bytes, got an archive...
    """
    family = sniff_content_family(head)
    if family is None or family == expect_kind:
        return
    if family in _CONTAINER_AMBIGUOUS and expect_kind in _CONTAINER_AMBIGUOUS:
        return
    where = f" from {url}" if url else ""
    if family == "html":
        raise ContentKindMismatch(
            f"expected {expect_kind} bytes{where}, got an HTML page. The server answered "
            f"with a web page (an error, login or preview page) rather than the media "
            f"itself — refusing to store it as a {expect_kind}. The usual cause is a "
            f"share link that is not public: set it to anyone-with-the-link, or use a "
            f"direct-download URL."
        )
    if family == "archive":
        raise ContentKindMismatch(
            f"expected {expect_kind} bytes{where}, got an archive (ZIP/gzip). A folder "
            f"share link downloads as a single archive of many files — expand it into one "
            f"asset per member, or share the individual file instead."
        )
    raise ContentKindMismatch(
        f"expected {expect_kind} bytes{where}, got {family} — refusing to store it under "
        f"the wrong kind."
    )


def kind_checked(
    chunks: Iterable[bytes], *, expect_kind: str, url: Optional[str] = None
) -> Iterator[bytes]:
    """Wrap a byte stream so its head is asserted **before any chunk escapes**.

    Buffers until it holds at least :data:`SNIFF_BYTES`, runs :func:`assert_content_kind`,
    and only then starts yielding. Checking before yielding — rather than after the stream
    drains — is what makes the guard independent of the consumer: it holds even for one
    that writes incrementally.

    **On memory**: the buffer is bounded by :data:`SNIFF_BYTES` *plus one producer chunk* —
    the length is checked after appending, so a producer that hands over one enormous chunk
    has it held whole. That is not avoidable (the bytes are already in memory by then) and
    is harmless for the chunked readers this is meant for, but it means the bound is a
    function of the producer's chunk size, not of :data:`SNIFF_BYTES` alone. A stream whose
    *total* is under :data:`SNIFF_BYTES` is likewise drained completely.

    The bytes are preserved exactly; only the *chunking* changes, since the head is
    re-emitted as one buffered piece:

    >>> list(kind_checked([b'\\x89PNG\\r\\n\\x1a\\n', b'rest'], expect_kind='image'))
    [b'\\x89PNG\\r\\n\\x1a\\nrest']

    A bad stream raises before anything is yielded, so a partial file is never written:

    >>> next(kind_checked([b'<html><body>nope'], expect_kind='video'))
    Traceback (most recent call last):
        ...
    graze.content_kind.ContentKindMismatch: expected video bytes, got an HTML page...
    """
    head = bytearray()
    stream = iter(chunks)
    for chunk in stream:
        head += chunk
        if len(head) >= SNIFF_BYTES:
            break
    assert_content_kind(bytes(head), expect_kind=expect_kind, url=url)
    if head:
        yield bytes(head)
    yield from stream

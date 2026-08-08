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
    # BMP is NOT here: its magic is the 2 bytes "BM", too short to be evidence on its own
    # (it matches ordinary prose). See _looks_like_bmp, which checks the size field too.
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
    {
        b"avif",
        b"avis",
        b"heic",
        b"heix",
        b"heim",
        b"heis",
        b"hevc",
        b"hevx",
        b"heif",
        b"avio",
        b"mif1",
        b"msf1",
        b"crx ",  # Canon CR3 raw photo
    }
)
#: Video brands are listed EXPLICITLY rather than used as the fallback, because the ISO
#: brand registry is open-ended: an unrecognised brand must classify as unknown (permissive)
#: rather than be asserted to be video, which would hard-refuse a genuine image.
_FTYP_VIDEO_BRANDS = frozenset(
    {
        b"isom",
        b"iso2",
        b"iso4",
        b"iso5",
        b"iso6",
        b"mp41",
        b"mp42",
        b"avc1",
        b"qt  ",
        b"M4V ",
        b"M4VH",
        b"M4VP",
        b"mmp4",
        b"dash",
        b"3gp4",
        b"3gp5",
        b"3gp6",
        b"3g2a",
    }
)

#: Root elements that make a markup document an HTML *page*. A sign-in interstitial does
#: not reliably open with ``<html>`` — a meta-refresh redirect, a script bounce, or a bare
#: ``<title>`` are all common — so the set is deliberately broader than the obvious two.
_HTML_ROOT_TAGS = frozenset(
    {
        "html",
        "head",
        "body",
        "meta",
        "script",
        "title",
        "link",
        "div",
        "span",
        "p",
        "a",
        "table",
        "form",
        "center",
        "frameset",
        "noscript",
        "style",
    }
)

#: Markup root elements that are *not* HTML pages, mapped to what they actually are. SVG is
#: the load-bearing entry: it is a legitimate image, and classifying it as ``html`` would
#: refuse a real asset with an actively misleading diagnosis.
_MARKUP_ROOT_FAMILIES = {"svg": "image"}

#: Byte-order marks that prove a payload is *text*, and the codec to read it with. Checked
#: before any binary signature: a UTF-16 BOM (``\xff\xfe``) otherwise trips the MP3
#: frame-sync test, and because audio/video are mutually permissive that made a UTF-16
#: sign-in page pass as media — defeating the entire point of this module.
_TEXT_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)

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
    # A byte-order mark PROVES text, so it is checked before every binary signature. Doing
    # this later let `\xff\xfe` (UTF-16LE) reach the MP3 frame-sync test and classify as
    # audio — and since audio/video are mutually permissive, a UTF-16 sign-in page then
    # passed `assert_content_kind` as media. That is the exact corruption this module
    # exists to prevent, so the BOM check goes first.
    for bom, codec in _TEXT_BOMS:
        if head.startswith(bom):
            return _classify_text(head[len(bom) :].decode(codec, errors="replace"))
    for prefix, family in _MAGIC_PREFIXES:
        if head.startswith(prefix):
            return family
    if head.startswith(b"BM") and _looks_like_bmp(head):
        return "image"
    # RIFF containers carry the family in bytes 8..12.
    if head.startswith(b"RIFF") and len(head) >= 12:
        form = head[8:12]
        if form == b"WAVE":
            return "audio"
        if form == b"WEBP":
            return "image"
        if form == b"AVI ":
            return "video"
    # ISO base media: ``....ftyp<brand>``. An UNRECOGNISED brand returns None rather than
    # guessing 'video': the brand registry is open-ended, images are excluded from the
    # audio/video ambiguity exemption, and so a wrong guess of 'video' HARD-REFUSES a
    # genuine image (a Canon CR3 photo is `ftypcrx `). Unknown must stay permissive.
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _FTYP_AUDIO_BRANDS:
            return "audio"
        if brand in _FTYP_IMAGE_BRANDS:
            return "image"
        if brand in _FTYP_VIDEO_BRANDS:
            return "video"
        return None
    if _looks_like_mp3_frame(head):
        return "audio"
    return _classify_text(head.decode("utf-8", errors="replace"))


def _looks_like_bmp(head: bytes) -> bool:
    """True iff ``head`` is a BMP, checked past the 2-byte ``BM`` magic.

    ``BM`` alone is far too short to be evidence — it matches ordinary prose ("BMW service
    manual"). The file-size field at 2..6 is not enough either: that phrase's bytes there
    decode to a perfectly plausible 1.7 GB. The **pixel-data offset** at 10..14 is what
    settles it — in a real BMP it is a small header offset (54 for the common
    BITMAPINFOHEADER, more with a palette), and text almost never lands in that range.
    """
    if len(head) < 14:
        return False
    size = int.from_bytes(head[2:6], "little")
    data_offset = int.from_bytes(head[10:14], "little")
    return (
        26 <= size <= (1 << 31)  # 26 = smallest possible BMP (header + 1 pixel)
        and 14 <= data_offset <= 4096  # header + at most a 1024-entry palette
        and data_offset <= size
    )


def _looks_like_mp3_frame(head: bytes) -> bool:
    """True iff ``head`` opens with a plausible MPEG audio frame header.

    The 11-bit sync word alone is not enough — it matches a UTF-16 BOM, among other things.
    Reserved values in the version, layer, bitrate-index and sampling-rate-index fields are
    all rejected, which is what separates a real frame from a coincidence.
    """
    if len(head) < 3 or head[0] != 0xFF or (head[1] & 0xE0) != 0xE0:
        return False
    version = (head[1] >> 3) & 0b11
    layer = (head[1] >> 1) & 0b11
    bitrate_index = (head[2] >> 4) & 0b1111
    sampling_index = (head[2] >> 2) & 0b11
    return (
        version != 0b01  # reserved MPEG version
        and layer != 0b00  # reserved layer
        and bitrate_index not in (0b0000, 0b1111)  # 'free' and 'bad'
        and sampling_index != 0b11  # reserved sampling rate
    )


def _classify_text(text: str) -> Optional[str]:
    """Classify an already-decoded payload as ``'html'``, ``'image'``, ``'json'`` or None.

    Markup is classified by its **root element**, not by a fixed list of opening byte
    strings. An XML declaration and comments are skipped first, so ``<?xml ...?><svg>`` and
    a bare ``<svg>`` agree — the older prefix rule called the former ``html`` and refused a
    legitimate SVG image with a diagnosis about share-link permissions.
    """
    text = text.lstrip()
    if text[:1] in ("{", "["):
        return "json"
    if text[:1] != "<":
        return None
    if text[:9].lower() == "<!doctype":
        # Tolerant of any whitespace run, unlike a literal '<!doctype html' prefix match.
        rest = text[9:].lstrip().lower()
        return "html" if rest.startswith("html") else None
    body = _strip_markup_preamble(text)
    tag = _root_tag_name(body)
    if tag is None:
        return None
    if tag in _MARKUP_ROOT_FAMILIES:
        return _MARKUP_ROOT_FAMILIES[tag]
    return "html" if tag in _HTML_ROOT_TAGS else None


def _strip_markup_preamble(text: str) -> str:
    """Drop a leading XML declaration, processing instructions, comments and doctype."""
    while True:
        text = text.lstrip()
        if text.startswith("<?"):
            end = text.find("?>")
            if end == -1:
                return ""
            text = text[end + 2 :]
        elif text.startswith("<!--"):
            end = text.find("-->")
            if end == -1:
                return ""
            text = text[end + 3 :]
        elif text[:9].lower() == "<!doctype":
            end = text.find(">")
            if end == -1:
                return ""
            text = text[end + 1 :]
        else:
            return text


def _root_tag_name(text: str) -> Optional[str]:
    """The lowercased name of the first element in ``text``, or None."""
    if not text.startswith("<"):
        return None
    name = []
    for ch in text[1:]:
        if ch.isalnum() or ch in "-_:":
            name.append(ch)
        else:
            break
    if not name:
        return None
    return "".join(name).lower().rpartition(":")[2]  # drop any namespace prefix


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

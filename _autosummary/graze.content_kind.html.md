# graze.content_kind

What the bytes actually turned out to be — magic-byte sniffing and kind assertion.

[`graze.share_links`](graze.share_links.html.md#module-graze.share_links) answers *what does this link denote* before a fetch. This module
answers the question one step later: **what did these bytes turn out to be**, and is that
what the caller asked for. Together they close the gap that makes cloud share links
treacherous — a share URL commonly answers `HTTP 200` with a *web page* (a sign-in
interstitial, a preview, a virus-scan warning), so an unguarded fetch “succeeds” and
stores an HTML document as if it were media.

Three things, in increasing order of usefulness:

```pycon
>>> sniff_content_family(b'\xff\xd8\xff\xe0')      # what is it?
'image'
```

```pycon
>>> assert_content_kind(b'<!doctype html><html>', expect_kind='video')
Traceback (most recent call last):
    ...
graze.content_kind.ContentKindMismatch: expected video bytes, got an HTML page...
```

```pycon
>>> list(kind_checked([b'\x89PNG\r\n\x1a\n', b'rest'], expect_kind='image'))
[b'\x89PNG\r\n\x1a\nrest']
```

[`kind_checked()`](#graze.content_kind.kind_checked) is the one to reach for: it asserts a stream’s head \*\*before any
chunk escapes\*\*, so the guard holds for a consumer that writes incrementally, not only for
one that buffers.

Two deliberate design choices, both of which trade a missed catch for never refusing
something genuine:

- **Unknown is permissive.** An unrecognised payload passes. An exotic-but-legitimate
  codec must not be refused merely because this table has not heard of it.
- **Audio and video are not distinguished.** Magic bytes identify a *container*, and
  ISO-BMFF, Matroska and Ogg all carry audio-only and video streams alike — an audio-only
  `.mp4` opens with an `ftyp` a table cannot tell from a video’s. Deciding needs the
  track list. Refusing on that evidence would reject real audio, which is strictly worse
  than declining to catch a mislabelled kind. Images are *not* in that pair; their
  signatures are unambiguous.

This module is dependency-free and network-free, like [`graze.share_links`](graze.share_links.html.md#module-graze.share_links).

### Module Attributes

| [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES)   | How many leading bytes are enough to classify a payload.   |
|----------------------------------------------------------------|------------------------------------------------------------|

### Functions

| [`sniff_content_family`](#graze.content_kind.sniff_content_family)(head)                        | Classify the leading bytes of a payload, or `None` when unrecognised.                                              |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`assert_content_kind`](#graze.content_kind.assert_content_kind)(head, \*, expect_kind[, url]) | Raise [`ContentKindMismatch`](#graze.content_kind.ContentKindMismatch) unless `head` looks like `expect_kind`. |
| [`kind_checked`](#graze.content_kind.kind_checked)(chunks, \*, expect_kind[, url])      | Wrap a byte stream so its head is asserted **before any chunk escapes**.                                           |

### Exceptions

| [`ContentKindMismatch`](#graze.content_kind.ContentKindMismatch)   | The fetched bytes are not the kind of thing that was asked for.   |
|------------------------------------------------------------------------|-------------------------------------------------------------------|

### *exception* graze.content_kind.ContentKindMismatch

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The fetched bytes are not the kind of thing that was asked for.

### graze.content_kind.SNIFF_BYTES *= 512*

How many leading bytes are enough to classify a payload. Every signature this module
knows lives well inside the first 64; the margin absorbs a BOM plus leading whitespace
on a text-shaped payload.

### graze.content_kind.assert_content_kind(head, , expect_kind, url=None)

Raise [`ContentKindMismatch`](#graze.content_kind.ContentKindMismatch) unless `head` looks like `expect_kind`.

The rule, branch by branch:

- an **HTML** payload is refused for every kind — this is the exact shape of the
  silent corruption a share link produces (`HTTP 200`, `text/html`, a couple of
  hundred KB of sign-in page);
- an **archive** is refused with a message naming it, because that is what a *folder*
  share link resolves to (see [`graze.share_links.ShareLinkKind`](graze.share_links.html.md#graze.share_links.ShareLinkKind) `ARCHIVE`);
- a recognised media family that **disagrees** with `expect_kind` is refused — the
  assertion is against what was asked for, not merely against “not a web page”;
- **except audio against video**, allowed both ways (see the module docstring);
- an **unrecognised** payload passes.

* **Parameters:**
  * **head** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The leading bytes of the payload (see [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES)).
  * **expect_kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The declared kind — typically image/video/audio/json.
  * **url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Included in the message when given, so an operator can tell *which* fetch was
    refused without correlating logs.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> assert_content_kind(b'\x89PNG\r\n\x1a\n', expect_kind='image')  # passes
>>> assert_content_kind(b'\x00\x00\x00\x18ftypisom', expect_kind='audio')  # ambiguous, passes
>>> assert_content_kind(b'PK\x03\x04', expect_kind='video')
Traceback (most recent call last):
    ...
graze.content_kind.ContentKindMismatch: expected video bytes, got an archive...
```

### graze.content_kind.kind_checked(chunks, , expect_kind, url=None)

Wrap a byte stream so its head is asserted **before any chunk escapes**.

Buffers until it holds at least [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES), runs [`assert_content_kind()`](#graze.content_kind.assert_content_kind),
and only then starts yielding. Checking before yielding — rather than after the stream
drains — is what makes the guard independent of the consumer: it holds even for one
that writes incrementally.

**On memory**: the buffer is bounded by [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES) *plus one producer chunk* —
the length is checked after appending, so a producer that hands over one enormous chunk
has it held whole. That is not avoidable (the bytes are already in memory by then) and
is harmless for the chunked readers this is meant for, but it means the bound is a
function of the producer’s chunk size, not of [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES) alone. A stream whose
*total* is under [`SNIFF_BYTES`](#graze.content_kind.SNIFF_BYTES) is likewise drained completely.

The bytes are preserved exactly; only the *chunking* changes, since the head is
re-emitted as one buffered piece:

```pycon
>>> list(kind_checked([b'\x89PNG\r\n\x1a\n', b'rest'], expect_kind='image'))
[b'\x89PNG\r\n\x1a\nrest']
```

A bad stream raises before anything is yielded, so a partial file is never written:

```pycon
>>> next(kind_checked([b'<html><body>nope'], expect_kind='video'))
Traceback (most recent call last):
    ...
graze.content_kind.ContentKindMismatch: expected video bytes, got an HTML page...
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### graze.content_kind.sniff_content_family(head)

Classify the leading bytes of a payload, or `None` when unrecognised.

Returns one of `'image'`, `'video'`, `'audio'`, `'json'`, `'html'`,
`'archive'` — or `None`, which means *unknown*, not *bad*.

```pycon
>>> sniff_content_family(b'\xff\xd8\xff\xe0')
'image'
>>> sniff_content_family(b'\x00\x00\x00\x18ftypmp42')
'video'
>>> sniff_content_family(b'\x00\x00\x00\x18ftypM4A ')
'audio'
>>> sniff_content_family(b'RIFF\x24\x08\x00\x00WAVE')
'audio'
>>> sniff_content_family(b'  \n<!DOCTYPE HTML PUBLIC>')
'html'
>>> sniff_content_family(b'PK\x03\x04\x14\x00')
'archive'
>>> sniff_content_family(b'{"a": 1}')
'json'
>>> sniff_content_family(b'\x00\x01\x02\x03') is None
True
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

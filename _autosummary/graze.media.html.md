# graze.media

Fetch one media file from a URL someone pasted: share link resolved, fetch guarded, bytes checked.

Three graze modules each answer one question about a caller-supplied URL;
[`fetch_media()`](#graze.media.fetch_media) asks them in order, so an app does not keep its own copy of the
glue (graze#18):

1. [`graze.share_links`](graze.share_links.html.md#module-graze.share_links) – *what does the link denote?* A Dropbox or Google Drive
   share link becomes its direct-download URL; a folder link, or a link with no known
   rule (OneDrive, a Google Doc), is refused with the reason, before any network.
2. [`graze.guarded`](graze.guarded.html.md#module-graze.guarded) – *is it safe to fetch?* Every hop is checked against the
   address policy (no localhost, private networks or cloud metadata), within a byte
   and a wall-clock budget.
3. [`graze.content_kind`](graze.content_kind.html.md#module-graze.content_kind) – *did we get the thing?* The share host’s sign-in or
   preview page, and a ZIP where one file was meant, are refused instead of being kept
   as media.

```pycon
>>> media = fetch_media('https://www.dropbox.com/scl/fi/a1/memo.m4a?rlkey=z&dl=0',
...                     expect_kind='audio')
>>> media.filename, media.provider
('memo.m4a', 'dropbox')
```

What it raises is one of [`FETCH_MEDIA_ERRORS`](#graze.media.FETCH_MEDIA_ERRORS), each with a message meant for the
person who pasted the link:

```pycon
>>> fetch_media('https://drive.google.com/drive/folders/1AbC')
Traceback (most recent call last):
    ...
graze.share_links.ShareLinkResolutionError: That google_drive link is a folder; share the single file instead...
```

Messages from this module name a link by [`redact_url()`](#graze.media.redact_url) only (scheme, host, first path
segment): share links carry bearer secrets in their path and query, and these messages are
meant to be shown. Errors raised by [`graze.guarded`](graze.guarded.html.md#module-graze.guarded) itself still carry the full URL and
the resolved address, so a web surface should word those itself rather than echo them.

Every keyword argument of [`graze.guarded.guarded_open()`](graze.guarded.html.md#graze.guarded.guarded_open) passes through (`max_bytes`,
`timeout`, `is_allowed_address`, `connector`…), so tests and self-hosted setups
use the same seams.

### Module Attributes

| [`FETCH_MEDIA_ERRORS`](#graze.media.FETCH_MEDIA_ERRORS)   | What [`fetch_media()`](#graze.media.fetch_media) raises on purpose; catch this tuple at a surface.   |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_REFUSE`](#graze.media.DFLT_REFUSE)          | a web page is the share host's sign-in or preview page, an archive is a folder link's ZIP.                              |

### Functions

| [`fetch_media`](#graze.media.fetch_media)(url, \*[, expect_kind, refuse, ...])   | Fetch the one file `url` points at (a share link or a plain URL).                     |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`redact_url`](#graze.media.redact_url)(url)                                    | The URL with what can carry a secret removed: scheme, host and first path segment.    |
| [`clean_filename`](#graze.media.clean_filename)(name)                               | A file name safe to keep and show: no path, no control or format characters, bounded. |

### Classes

| [`FetchedMedia`](#graze.media.FetchedMedia)(data, filename, content_type, ...)   | The bytes of one fetched file, and what is known about them.   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------|

### graze.media.DFLT_REFUSE *= ('html', 'archive')*

a web page is the share host’s
sign-in or preview page, an archive is a folder link’s ZIP.

* **Type:**
  Content families refused whatever `expect_kind` is

### graze.media.FETCH_MEDIA_ERRORS *= (<class 'graze.share_links.ShareLinkResolutionError'>, <class 'graze.content_kind.ContentKindMismatch'>, <class 'graze.guarded.GuardedFetchError'>)*

What [`fetch_media()`](#graze.media.fetch_media) raises on purpose; catch this tuple at a surface.

### *class* graze.media.FetchedMedia(data, filename, content_type, url, provider)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The bytes of one fetched file, and what is known about them.

#### content_type *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

as the server declared it (’’ if it did not)

#### filename *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

from Content-Disposition, else the URL’s last path segment (’’ if none)

#### provider *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

the share-link provider (‘dropbox’, ‘google_drive’…) or ‘http’

#### url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

the final URL, after redirects

### graze.media.clean_filename(name)

A file name safe to keep and show: no path, no control or format characters, bounded.

```pycon
>>> clean_filename('../../etc/passwd'), clean_filename('..'), clean_filename('a\x07b.mp3')
('passwd', '', 'ab.mp3')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### graze.media.fetch_media(url, , expect_kind=None, refuse=('html', 'archive'), resolvers=None, \*\*guarded_open_options)

Fetch the one file `url` points at (a share link or a plain URL).

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What the person pasted. Surrounding whitespace is ignored.
  * **expect_kind** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `'audio'`, `'video'`, `'image'`… when given, recognised bytes
    of another family are refused (audio and video containers pass for each other,
    see [`graze.content_kind`](graze.content_kind.html.md#module-graze.content_kind)); unrecognised bytes pass.
  * **refuse** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Content families refused in any case (default [`DFLT_REFUSE`](#graze.media.DFLT_REFUSE)).
  * **resolvers** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ResolvedShareLink`](graze.share_links.html.md#graze.share_links.ResolvedShareLink)]]]]) – Share-link adapters (default: [`graze.share_links.share_link_resolvers`](graze.share_links.html.md#graze.share_links.share_link_resolvers)).
  * **\*\*guarded_open_options** – Passed to [`graze.guarded.guarded_open()`](graze.guarded.html.md#graze.guarded.guarded_open).
* **Return type:**
  [`FetchedMedia`](#graze.media.FetchedMedia)

An HTML page and an empty body are always refused when `expect_kind` is given (that is
[`graze.content_kind.assert_content_kind()`](graze.content_kind.html.md#graze.content_kind.assert_content_kind)’s rule); `refuse` adds families refused
in any case.

Raises one of [`FETCH_MEDIA_ERRORS`](#graze.media.FETCH_MEDIA_ERRORS).

### graze.media.redact_url(url)

The URL with what can carry a secret removed: scheme, host and first path segment.

```pycon
>>> redact_url('https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=SECRET&dl=0')
'https://www.dropbox.com/scl/…'
>>> redact_url('not a url')
'(a link)'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

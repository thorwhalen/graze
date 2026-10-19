# graze.share_links

Pure (network-free) resolution of cloud share links to direct-download URLs.

A *share link* is what a person copies out of Dropbox / Google Drive / OneDrive.
It is **not** a download URL: fetching it usually gets you an HTML preview page,
and — worse — what you get can depend on your `User-Agent` rather than on the
link. This module maps a pasted share link to a description of what it actually
denotes:

```default
share link  ->  ResolvedShareLink(provider, kind, direct_url, reason)
```

Everything here is a `str -> description` mapping. \*\*No function in this module
opens a socket\*\*, which is the whole point: resolution is deterministic and
testable offline, while fetching (redirect policy, byte caps, content-type
assertions, SSRF protection) is a separate concern that belongs to the transport
layer, and archive expansion (a folder link is a ZIP, see [`ShareLinkKind`](#graze.share_links.ShareLinkKind))
belongs to the caller.

The two things a caller needs to know before fetching:

- **the direct URL** — or, honestly, that there isn’t one (some links genuinely
  need a provider API, and this module refuses rather than guess);
- **the kind** — a *file* and a *folder* are different operations. A Dropbox
  folder link downloads as a single ZIP that must be expanded into N assets.

Simple use — give me something I can fetch, or tell me why not:

```pycon
>>> direct_download_url('https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz&dl=0')
'https://www.dropbox.com/scl/fi/a1b2/clip.mp4?rlkey=zz&dl=1'
```

```pycon
>>> direct_download_url('https://drive.google.com/drive/folders/1AbCdEf')
Traceback (most recent call last):
    ...
graze.share_links.ShareLinkResolutionError: Cannot resolve this google_drive link...
```

Full use — the whole description, including what kind of thing it is:

```pycon
>>> r = resolve_share_url('https://www.dropbox.com/scl/fo/x9/y?rlkey=zz&dl=0')
>>> r.provider, r.kind.value, r.resolved
('dropbox', 'archive', True)
>>> r.direct_url
'https://www.dropbox.com/scl/fo/x9/y?rlkey=zz&dl=1'
```

`kind == 'archive'` is the signal that the bytes are a ZIP of many members,
not one asset – `dol.FilesOfZip` is the tool for that half.

A URL that is nobody’s share link passes through unchanged:

```pycon
>>> r = resolve_share_url('https://example.com/video.mp4')
>>> r.provider, r.direct_url
('http', 'https://example.com/video.mp4')
```

Adding a provider is open-closed – register an adapter, no core edits:

```pycon
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
```

#### NOTE
this module is **not** a security boundary. It will happily hand back a URL
pointing anywhere; validating scheme/port/address and re-validating every redirect
hop is the transport layer’s job.

### Module Attributes

| [`ShareLinkResolver`](#graze.share_links.ShareLinkResolver)    | given a URL, return its resolution, or `None` for "not mine".                      |
|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`DROPBOX_PATH_KINDS`](#graze.share_links.DROPBOX_PATH_KINDS)   | Share-link path prefixes -> what they denote.                                      |
| [`share_link_resolvers`](#graze.share_links.share_link_resolvers) | Provider adapters, tried in order; the first non-`None` result wins.               |
| [`PASSTHROUGH_SCHEMES`](#graze.share_links.PASSTHROUGH_SCHEMES)  | this module describes *fetchable web resources*, and unknown schemes are not that. |

### Functions

| [`add_share_link_resolver`](#graze.share_links.add_share_link_resolver)(provider, resolver)   | Register (or replace) a provider adapter.                                                                      |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`direct_download_url`](#graze.share_links.direct_download_url)(url, \*[, resolvers])     | The URL to actually fetch, or raise [`ShareLinkResolutionError`](#graze.share_links.ShareLinkResolutionError). |
| [`resolve_dropbox`](#graze.share_links.resolve_dropbox)(url)                          | Resolve a Dropbox share link by forcing `dl=1`.                                                                |
| [`resolve_google_drive`](#graze.share_links.resolve_google_drive)(url)                     | Resolve a Google Drive / Google Workspace URL.                                                                 |
| [`resolve_onedrive`](#graze.share_links.resolve_onedrive)(url)                         | Recognise a OneDrive / SharePoint share link, and refuse it.                                                   |
| [`resolve_share_url`](#graze.share_links.resolve_share_url)(url, \*[, resolvers])       | Describe what a share URL denotes and how (or whether) to fetch it.                                            |

### Classes

| [`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)(url, provider, kind[, ...])   | What a share URL denotes, and how (or whether) to fetch it.            |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`ShareLinkKind`](#graze.share_links.ShareLinkKind)(\*values)                         | What a share link denotes -- a file, an archive, a folder, or unknown. |

### Exceptions

| [`ShareLinkResolutionError`](#graze.share_links.ShareLinkResolutionError)   | Raised when a share link cannot be resolved to a direct-download URL.   |
|-----------------------------------------------------------------------------|-------------------------------------------------------------------------|

### graze.share_links.DROPBOX_PATH_KINDS *= (('/scl/fi/', ShareLinkKind.FILE), ('/scl/fo/', ShareLinkKind.ARCHIVE), ('/s/', ShareLinkKind.FILE), ('/sh/', ShareLinkKind.ARCHIVE))*

Share-link path prefixes -> what they denote. `/s/` + `/sh/` are the legacy
forms; `/scl/fi/` + `/scl/fo/` are the ones Dropbox issues today.

### graze.share_links.PASSTHROUGH_SCHEMES *= ('http', 'https')*

this module
describes *fetchable web resources*, and unknown schemes are not that.

* **Type:**
  Schemes a plain URL may pass through with. Anything else is refused

### *class* graze.share_links.ResolvedShareLink(url, provider, kind, direct_url=None, reason=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a share URL denotes, and how (or whether) to fetch it.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The share URL as given (stripped of surrounding whitespace).
  * **provider** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provider slug, e.g. `'dropbox'`, `'google_drive'`,
    `'onedrive'`, `'http'` (a plain URL that is nobody’s share link),
    or `'unknown'`.
  * **kind** ([`ShareLinkKind`](#graze.share_links.ShareLinkKind)) – See [`ShareLinkKind`](#graze.share_links.ShareLinkKind).
  * **direct_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A URL whose response body is the content – or `None` when
    the link cannot be resolved without a provider API.
  * **reason** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Why `direct_url` is `None`. Required whenever it is.

`direct_url` and `kind` are independent: a Google Workspace document is a
`FILE` that still has no resolvable download URL.

```pycon
>>> r = ResolvedShareLink('https://x/y', 'http', ShareLinkKind.FILE, 'https://x/y')
>>> r.resolved
True
```

An unresolved link must say why – an adapter that refuses silently is a bug:

```pycon
>>> ResolvedShareLink('https://x/y', 'nope', ShareLinkKind.UNKNOWN)
Traceback (most recent call last):
    ...
ValueError: An unresolved ResolvedShareLink must carry a reason (url: https://x/y)
```

#### *property* resolved *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True when there is a direct URL to fetch.

### *class* graze.share_links.ShareLinkKind(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

What a share link denotes – a file, an archive, a folder, or unknown.

`ARCHIVE` is a refinement of `FILE`: the URL still resolves to one blob,
but that blob is a ZIP the caller must expand into N assets. Providers render
*folder* links this way (Dropbox does so even for a single-file folder).

`FOLDER` is the honest answer when a link denotes a folder and the provider
offers **no** URL that downloads it – listing it needs an API credential.

```pycon
>>> ShareLinkKind.ARCHIVE.value
'archive'
>>> ShareLinkKind('folder') is ShareLinkKind.FOLDER
True
```

### *exception* graze.share_links.ShareLinkResolutionError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when a share link cannot be resolved to a direct-download URL.

### graze.share_links.ShareLinkResolver

given a URL, return its resolution, or `None` for “not mine”.

* **Type:**
  An adapter

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ResolvedShareLink`](#graze.share_links.ResolvedShareLink) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### graze.share_links.add_share_link_resolver(provider, resolver)

Register (or replace) a provider adapter.

`resolver` takes a URL and returns a [`ResolvedShareLink`](#graze.share_links.ResolvedShareLink), or `None`
to mean “not mine, try the next one”. Replacing an existing provider keeps its
position in the try-order; a new one is appended (so it is tried last).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### graze.share_links.direct_download_url(url, , resolvers=None)

The URL to actually fetch, or raise [`ShareLinkResolutionError`](#graze.share_links.ShareLinkResolutionError).

```pycon
>>> direct_download_url('https://drive.google.com/file/d/1AbC/view')
'https://drive.google.com/uc?export=download&id=1AbC'
>>> direct_download_url('https://1drv.ms/u/s!AbCd')
Traceback (most recent call last):
    ...
graze.share_links.ShareLinkResolutionError: Cannot resolve this onedrive link...
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### graze.share_links.resolve_dropbox(url)

Resolve a Dropbox share link by forcing `dl=1`.

Both the modern `/scl/` forms and the legacy `/s/` + `/sh/` forms; every
other query parameter (notably `rlkey`, which is a bearer secret) is kept
byte-for-byte.

```pycon
>>> r = resolve_dropbox('https://www.dropbox.com/s/a1/data.csv?dl=0')
>>> r.kind.value, r.direct_url
('file', 'https://www.dropbox.com/s/a1/data.csv?dl=1')
```

A folder link is an *archive* – one ZIP holding N members:

```pycon
>>> r = resolve_dropbox('https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&st=t1')
>>> r.kind.value, r.direct_url
('archive', 'https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&st=t1&dl=1')
```

Non-share Dropbox URLs are not this adapter’s business:

```pycon
>>> resolve_dropbox('https://www.dropbox.com/home') is None
True
>>> resolve_dropbox('https://example.com/s/a1/data.csv?dl=0') is None
True
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)]

### graze.share_links.resolve_google_drive(url)

Resolve a Google Drive / Google Workspace URL.

Files resolve; **folders and Workspace documents are refused**, because
neither has a plain-URL download and pretending otherwise is how a folder id
ends up in a file-download URL.

```pycon
>>> resolve_google_drive('https://drive.google.com/file/d/1AbC/view').direct_url
'https://drive.google.com/uc?export=download&id=1AbC'
```

A `resourcekey` (required by link-shared files created before 2021) is kept:

```pycon
>>> r = resolve_google_drive('https://drive.google.com/file/d/1AbC/view?resourcekey=0-x')
>>> r.direct_url
'https://drive.google.com/uc?export=download&id=1AbC&resourcekey=0-x'
```

A folder is a folder – refused, with the reason and the id to hand:

```pycon
>>> r = resolve_google_drive('https://drive.google.com/drive/folders/1FoLd')
>>> r.kind.value, r.direct_url is None
('folder', True)
>>> print(r.reason)
Google Drive folder links have no direct-download URL...
```

So is a native Google doc – a file, but not a downloadable one:

```pycon
>>> r = resolve_google_drive('https://docs.google.com/spreadsheets/d/1Sh/edit')
>>> r.kind.value, r.direct_url is None
('file', True)
```

…\*unless\* the caller already chose a format, which is the only thing the
refusal above was ever about:

```pycon
>>> u = 'https://docs.google.com/spreadsheets/d/1Sh/export?format=csv&gid=0'
>>> resolve_google_drive(u).direct_url == u
True
```

```pycon
>>> resolve_google_drive('https://example.com/file/d/1AbC/view') is None
True
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)]

### graze.share_links.resolve_onedrive(url)

Recognise a OneDrive / SharePoint share link, and refuse it.

```pycon
>>> r = resolve_onedrive('https://1drv.ms/f/s!AbCd')
>>> r.provider, r.kind.value, r.direct_url is None
('onedrive', 'folder', True)
```

```pycon
>>> r = resolve_onedrive('https://contoso-my.sharepoint.com/:v:/g/personal/x/EaB')
>>> r.provider, r.kind.value
('onedrive', 'unknown')
```

An ordinary SharePoint document path is not a share link:

```pycon
>>> resolve_onedrive('https://contoso.sharepoint.com/sites/x/clip.mp4') is None
True
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)]

### graze.share_links.resolve_share_url(url, , resolvers=None)

Describe what a share URL denotes and how (or whether) to fetch it.

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The URL as a user pasted it. Surrounding whitespace is stripped.
  * **resolvers** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)]]]]) – Adapters to try, in order. Defaults to
    [`share_link_resolvers`](#graze.share_links.share_link_resolvers); pass your own to test in isolation.
* **Return type:**
  [`ResolvedShareLink`](#graze.share_links.ResolvedShareLink)
* **Returns:**
  A [`ResolvedShareLink`](#graze.share_links.ResolvedShareLink). Never raises for an unresolvable link –
  the refusal is in the return value (`direct_url is None` plus a
  `reason`). Use [`direct_download_url()`](#graze.share_links.direct_download_url) when you want the raise.

```pycon
>>> resolve_share_url('  https://www.dropbox.com/s/a1/x.csv?dl=0  ').direct_url
'https://www.dropbox.com/s/a1/x.csv?dl=1'
>>> resolve_share_url('https://example.com/a.mp4').provider
'http'
>>> resolve_share_url('ftp://example.com/a.mp4').resolved
False
```

### graze.share_links.share_link_resolvers *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[[str](https://docs.python.org/3/builtins/stdtypes.html#str)], [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[ResolvedShareLink](#graze.share_links.ResolvedShareLink)]]]* *= {'dropbox': <function resolve_dropbox>, 'google_drive': <function resolve_google_drive>, 'onedrive': <function resolve_onedrive>}*

Provider adapters, tried in order; the first non-`None` result wins. Open-closed:
extend it with [`add_share_link_resolver()`](#graze.share_links.add_share_link_resolver) instead of editing this module.

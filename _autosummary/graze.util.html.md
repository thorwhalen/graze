# graze.util

Utils

### Functions

| [`add_special_url_route`](#graze.util.add_special_url_route)(condition, ...)             | Add a special url route, i.e. a function that downloads a url's contents for a specific condition on the url.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`chks_of_url_contents`](#graze.util.chks_of_url_contents)(url, \*[, chk_size, ...])    | Yield chunks of a url's contents.                                                                               |
| [`clog`](#graze.util.clog)(condition, \*args[, log_func])               | Conditional log                                                                                                 |
| [`download_from_google_drive`](#graze.util.download_from_google_drive)(url[, file, ...])      | Download a file from a Google Drive URL.                                                                        |
| [`download_from_share_link`](#graze.util.download_from_share_link)(url[, file, ...])        | Resolve a share link to its direct-download URL, then download that.                                            |
| [`download_from_special_url`](#graze.util.download_from_special_url)(url[, file, ...])       | Download a url's contents, using a special url route.                                                           |
| [`download_url_contents`](#graze.util.download_url_contents)(url[, file, chk_size, ...]) | Download url contents into a `file` object, or return bytes if `file` is None.                                  |
| [`get_content_size`](#graze.util.get_content_size)(url, \*[, default])              | Get the content size of a url, if available, without downloading the content.                                   |
| [`google_drive_download_url`](#graze.util.google_drive_download_url)(url)                    | Get the direct-download url of a Google Drive FILE url.                                                         |
| `handle_missing_dir`(dirpath[, prefix_msg, ...])                                                   |                                                                                                                 |
| [`human_readable_bytes`](#graze.util.human_readable_bytes)(num_of_bytes, \*[, ...])     | Convert a number of bytes into a human-readable format with units.                                              |
| `inner_most`(store, arg, method)                                                                   |                                                                                                                 |
| [`is_dropbox_url`](#graze.util.is_dropbox_url)(url)                               | Whether `url` is a dropbox share link.                                                                          |
| [`is_google_drive_url`](#graze.util.is_google_drive_url)(url)                          | Whether `url` is a google_drive share link.                                                                     |
| [`is_onedrive_url`](#graze.util.is_onedrive_url)(url)                              | Whether `url` is a onedrive share link.                                                                         |
| [`is_share_url_of`](#graze.util.is_share_url_of)(provider)                         | Make a predicate: "is this URL a share link of `provider`?".                                                    |
| [`is_special_url`](#graze.util.is_special_url)(url)                               | Check if a url is a special url, i.e. if it has a special url route.                                            |
| [`last_element`](#graze.util.last_element)(iterable, \*[, default])             | Returns the last element of an iterable, or a default if the iterable is empty.                                 |
| [`original_url_of_tiny_url`](#graze.util.original_url_of_tiny_url)(tiny_url)                | Expands a short URL by making a HEAD request and following the redirection.                                     |
| `store_trans_path`(store, arg, method)                                                             |                                                                                                                 |
| [`tiny_url`](#graze.util.tiny_url)(long_url)                                | Shortens a long URL by directly calling the TinyURL API endpoint.                                               |
| `url_with_virus_scan_confirmation_token`(url, ...)                                                 |                                                                                                                 |

### graze.util.add_special_url_route(condition, url_download_func)

Add a special url route, i.e. a function that downloads a url’s contents
for a specific condition on the url.

### graze.util.bytes_of_url_content(url, , file=None, chk_size=1024, user_agent='Wget/1.16 (linux-gnu)')

Download url contents into a `file` object, or return bytes if `file` is None.

### graze.util.chks_of_url_contents(url, , chk_size=1024, user_agent='Wget/1.16 (linux-gnu)')

Yield chunks of a url’s contents.

### graze.util.clog(condition, \*args, log_func=<built-in function print>, \*\*kwargs)

Conditional log

```pycon
>>> clog(False, "logging this")
>>> clog(True, "logging this")
logging this
```

One common usage is when there’s a verbose flag that allows the user to specify
whether they want to log or not. Instead of having to litter your code with
`if verbose:` statements you can just do this:

```pycon
>>> verbose = True  # say versbose is True
>>> _clog = clog(verbose)  # makes a clog with a fixed condition
>>> _clog("logging this")
logging this
```

You can also choose a different log function:

```pycon
>>> _clog = clog(True, log_func=lambda x: print(f"hello {x}"))
>>> _clog("logging this")
hello logging this
```

### graze.util.download_from_google_drive(url, file=None, , chk_size=1024, user_agent='Wget/1.16 (linux-gnu)', skip_virus_scan_confirmation_page=False)

Download a file from a Google Drive URL.
Will write the downloaded contents bytes to `file`, which can be a local file path
or file-like object.
If `file=None`, returns the bytes of the contents of the url.

Only FILE urls (`...drive.google.com/file/d/{file_id}...`, `/open?id=`, and the
already-direct `/uc?...id=` and `drive.usercontent.google.com/download?id=` forms)
can be downloaded. A *folder* url, or a Google Workspace document (docs, sheets,
slides, forms), raises `ShareLinkResolutionError` – see
`google_drive_download_url`.

### graze.util.download_from_share_link(url, file=None, , chk_size=1024, user_agent='Wget/1.16 (linux-gnu)')

Resolve a share link to its direct-download URL, then download that.

Raises `ShareLinkResolutionError` (a `ValueError`) when the link cannot be
resolved without a provider API – deliberately, in preference to fetching the
share URL itself and silently storing an HTML preview page as if it were the
asset.

Note that what comes back may be an *archive*: a Dropbox folder link downloads
as a single ZIP holding every member. Check
`resolve_share_url(url).kind == ShareLinkKind.ARCHIVE` and expand it (e.g. with
`dol.FilesOfZip`) rather than treating those bytes as one asset.

### graze.util.download_from_special_url(url, file=None, chk_size=1024, user_agent='Wget/1.16 (linux-gnu)')

Download a url’s contents, using a special url route.

### graze.util.download_url_contents(url, file=None, , chk_size=1024, user_agent='Wget/1.16 (linux-gnu)')

Download url contents into a `file` object, or return bytes if `file` is None.

### graze.util.get_content_size(url, , default=None)

Get the content size of a url, if available, without downloading the content.

### graze.util.google_drive_download_url(url)

Get the direct-download url of a Google Drive FILE url.

Raises `ShareLinkResolutionError` for a *folder* URL (enumerating one needs the
Drive API) and for a Google Workspace document (those must be exported, and the
format is a caller decision) – rather than build a file-download URL out of a
folder id, which is what graze used to do.

```pycon
>>> google_drive_download_url('https://drive.google.com/file/d/1Ab/view')
'https://drive.google.com/uc?export=download&id=1Ab'
```

### graze.util.human_readable_bytes(num_of_bytes, , approx_marker='~', n_digits=4, base=1000, units=('B', 'KB', 'MB', 'GB', 'TB', 'PB'))

Convert a number of bytes into a human-readable format with units.

* **Parameters:**
  * **num_of_bytes** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The number of bytes.
  * **approx_marker** ([*str*](https://docs.python.org/3/builtins/stdtypes.html#str) *,* *optional*) – Marker indicating approximation. Defaults to “~”.
  * **n_digits** ([*int*](https://docs.python.org/3/builtins/functions.html#int) *,* *optional*) – Number of significant digits in the output. Defaults to 4.
  * **base** ([*int*](https://docs.python.org/3/builtins/functions.html#int) *,* *optional*) – Conversion base, 1024 or 1000. Defaults to 1000.
  * **units** ([*tuple*](https://docs.python.org/3/builtins/stdtypes.html#tuple) *,* *optional*) – Units for conversion. Defaults to (‘B’, ‘KB’, ‘MB’, ‘GB’, ‘TB’, ‘PB’).
* **Returns:**
  Human-readable string representing the number of bytes.
* **Return type:**
  [*str*](https://docs.python.org/3/builtins/stdtypes.html#str)

### Examples

```pycon
>>> human_readable_bytes(123456)
'~123.456KB'
>>> human_readable_bytes(123456789)
'~123.457MB'
```

Using `base=1000` (default) is the International System of Units (SI) standard.
But base=1024 is a common practice in computing.

```pycon
>>> human_readable_bytes(123456789, base=1024)
'~117.738MB'
```

```pycon
>>> human_readable_bytes(1234567890123)
'~1.235TB'
```

#### TIP
Use `functools.partial` to customize the function to your needs.

```pycon
>>> from functools import partial
>>> readable = partial(
...     human_readable_bytes,
...     approx_marker='approximately ',
...     units=(' bytes', ' kilobytes')
... )
>>> readable(123456)
'approximately 123.456 kilobytes'
```

Note how the function starts using the scientific notation when it runs out of
units.

```pycon
>>> readable(123456789)
'approximately 1.235e+08 kilobytes'
```

### graze.util.is_dropbox_url(url)

Whether `url` is a dropbox share link.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### graze.util.is_google_drive_url(url)

Whether `url` is a google_drive share link.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### graze.util.is_onedrive_url(url)

Whether `url` is a onedrive share link.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### graze.util.is_share_url_of(provider)

Make a predicate: “is this URL a share link of `provider`?”.

```pycon
>>> is_dropbox = is_share_url_of('dropbox')
>>> is_dropbox('https://www.dropbox.com/scl/fo/q7/z?rlkey=abc&dl=0')
True
>>> is_dropbox('https://example.com/data.csv')
False
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### graze.util.is_special_url(url)

Check if a url is a special url, i.e. if it has a special url route.

### graze.util.last_element(iterable, , default=None)

Returns the last element of an iterable, or a default if the iterable is empty.

### graze.util.original_url_of_tiny_url(tiny_url)

Expands a short URL by making a HEAD request and following the redirection.

* **Parameters:**
  **tiny_url** ([*str*](https://docs.python.org/3/builtins/stdtypes.html#str)) – The shortened TinyURL.
* **Returns:**
  The original long URL, or an error message if expansion fails.
* **Return type:**
  [*str*](https://docs.python.org/3/builtins/stdtypes.html#str)

### graze.util.tiny_url(long_url)

Shortens a long URL by directly calling the TinyURL API endpoint.

* **Parameters:**
  **long_url** ([*str*](https://docs.python.org/3/builtins/stdtypes.html#str)) – The URL to be shortened.
* **Returns:**
  The shortened TinyURL, or an error message.
* **Return type:**
  [*str*](https://docs.python.org/3/builtins/stdtypes.html#str)

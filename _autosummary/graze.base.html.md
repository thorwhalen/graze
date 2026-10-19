# graze.base

Base functionality

### Functions

| `DFLT_URL_TO_CONTENT`(url[, response_func])                                                  |                                                                                                                |
|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`graze`](#graze.base.graze)(url[, cache, cache_key, source, ...]) | Get the contents of the url (persisting the results in a local file or cache, for next time you'll ask for it) |
| `key_egress_print_downloading_message`(url)                                                  |                                                                                                                |
| `key_egress_print_downloading_message_with_size`(url)                                        |                                                                                                                |
| [`localpath_to_url`](#graze.base.localpath_to_url)(path)                      |                                                                                                                |
| `return_contents`(filepath, contents, url)                                                   |                                                                                                                |
| `return_filepath`(filepath, contents, url)                                                   |                                                                                                                |
| [`selenium_url_to_contents`](#graze.base.selenium_url_to_contents)(url[, ...])        | Function to get contents from a url, using selenium.                                                           |
| [`url_to_file_download`](#graze.base.url_to_file_download)(url[, filepath, ...])  | Helper to make a url-to-file download functions (using partial).                                               |
| [`url_to_filepath`](#graze.base.url_to_filepath)(url[, rootdir, download])   | Get the file path for the url.                                                                                 |
| [`url_to_localpath`](#graze.base.url_to_localpath)(url)                       |                                                                                                                |

### Classes

| [`Gettable`](#graze.base.Gettable)(\*args, \*\*kwargs)                     | Protocol for objects with \_\_getitem_\_ method.                                              |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| [`Graze`](#graze.base.Graze)(self[, rootdir, source, key_ingress, ...]) | A data access object that will get data from the internet if it's not already stored locally. |
| [`GrazeBase`](#graze.base.GrazeBase)([cache, source, key_ingress, ...])     | Base class for Graze that wraps the graze() function.                                         |
| [`GrazeWithDataRefresh`](#graze.base.GrazeWithDataRefresh)(self[, rootdir, ...])       |                                                                                               |
| `Internet`([url_to_contents, url_to_file_download])                                               |                                                                                               |
| [`LocalFiles`](#graze.base.LocalFiles)([rootdir])                            | Store to read/write/delete local files, creating directories on write.                        |
| [`LocalGrazed`](#graze.base.LocalGrazed)([rootdir])                           | LocalFiles using url as keys                                                                  |
| [`url_to_contents`](#graze.base.url_to_contents)()                                | A place to contain url_to_contents functions.                                                 |

### Exceptions

| [`RequestFailure`](#graze.base.RequestFailure)   | To be used when the request to get the contents of a url failed   |
|-------------------------------------------------------------------|-------------------------------------------------------------------|

### *class* graze.base.Gettable(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Protocol for objects with \_\_getitem_\_ method.

### *class* graze.base.Graze(self, rootdir='/home/runner/.cache/graze', source=<graze.base.Internet object>, \*, key_ingress=None, return_filepaths=False)

Bases: [`GrazeBase`](#graze.base.GrazeBase)

A data access object that will get data from the internet if it’s not
already stored locally.

The interface of `Graze` instances is a `typing.Mapping` (i.e. `dict`-like).
When you list (or iterate over) keys, you’ll get the urls
whose contents are stored locally.
When you get a value, you’ll get the contents of the url (in bytes).
`Graze` will first look if the contents are stored locally, and return that,
if not it will get the contents from the internet and store it locally,
then return those bytes.

This class now extends GrazeBase and delegates most work to the graze() function.

#### filepath_of(url)

Get the filepath of where graze stored (or would store) the contents for a url locally.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### filepath_of_url_downloading_if_necessary(url)

Get the file path for the url, downloading contents before hand if necessary.

Use case:

Sometimes you need to specify a filepath as a resource for some python object.
For example, some font definition file, or configuration file, or such.
You can provide the file for the user, or can tell them where they can find
such a file if needed…
Use `filepath_of_url_downloading_if_necessary` to get that local filepath,
ensuring that the data is there before hand.

### *class* graze.base.GrazeBase(cache=None, \*, source=None, key_ingress=None, url_to_cache_key=<function url_to_localpath>, cache_key_to_url=<function localpath_to_url>, refresh=False)

Bases: [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

Base class for Graze that wraps the graze() function.

This class provides a MutableMapping interface (dict-like) where:

- Keys are URLs
- Values are the contents of those URLs (bytes)
- Items are cached locally (in folder, Files, or dict)

The key design principle: All actual work is delegated to the graze() function.
This class just provides the Mapping interface and state management.

* **Parameters:**
  * **cache** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – 

    Where to cache contents. Can be:
    - str: folder path for file-based caching
    - MutableMapping: custom cache (e.g., Files, dict)
    - None: uses DFLT_GRAZE_DIR
  * **source** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable), [`Gettable`](#graze.base.Gettable)]) – Where to get contents if not cached. Defaults to Internet().
  * **key_ingress** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Function to call on URL before downloading.
  * **url_to_cache_key** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Function to convert URL to cache key.
    Defaults to url_to_localpath.
  * **cache_key_to_url** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Function to convert cache key back to URL.
    Defaults to localpath_to_url.

### Examples

```pycon
>>> # With folder cache (default)
>>> g = GrazeBase(cache='~/my_cache')
>>> content = g['http://example.com/data.json']
```

```pycon
>>> # With Files cache
>>> from dol import Files
>>> g = GrazeBase(cache=Files('~/cache'))
```

```pycon
>>> # With dict cache (in-memory)
>>> g = GrazeBase(cache={})
```

### *class* graze.base.GrazeWithDataRefresh(self, rootdir='/home/runner/.cache/graze', source=<graze.base.Internet object>, \*, key_ingress=None, return_filepaths=False)

Bases: [`Graze`](#graze.base.Graze)

### *class* graze.base.LocalFiles(rootdir='/home/runner/.cache/graze')

Bases: `Store`

Store to read/write/delete local files, creating directories on write.

#### is_valid_key(k, \*args, \_\_name='is_valid_key', \*\*kwargs)

`is_valid_key` on the inner key – see `mk_relative_path_store`.

#### validate_key(k, \*args, \_\_name='validate_key', \*\*kwargs)

`validate_key` on the inner key – see `mk_relative_path_store`.

### *class* graze.base.LocalGrazed(rootdir='/home/runner/.cache/graze')

Bases: `Store`

LocalFiles using url as keys

#### is_valid_key(k, \*args, \_\_name='is_valid_key', \*\*kwargs)

`is_valid_key` on the inner key – see `mk_relative_path_store`.

#### validate_key(k, \*args, \_\_name='validate_key', \*\*kwargs)

`validate_key` on the inner key – see `mk_relative_path_store`.

### *exception* graze.base.RequestFailure

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

To be used when the request to get the contents of a url failed

### graze.base.graze(url, cache=None, , cache_key=None, source=None, key_ingress=None, refresh=False, max_age=None, return_key=False, rootdir=None, return_filepaths=None)

Get the contents of the url (persisting the results in a local file or cache,
for next time you’ll ask for it)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to download from
  * **cache** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – 

    Where to store the contents. Can be:
    - None: use DFLT_GRAZE_DIR as folder path (unless cache_key is full filepath)
    - str: folder path for file-based caching
    - MutableMapping: custom cache object (e.g., Files, dict)
  * **cache_key** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – 

    The key to use in the cache. Can be:
    - None: auto-generate using url_to_localpath
    - str: explicit cache key (or full filepath if starts with / or ~)
    - Callable: function to generate cache key from url
  * **source** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable), [`Gettable`](#graze.base.Gettable)]) – 

    Where to get the contents from if not cached. Can be:
    - None: use default Internet() instance
    - Callable: function that takes url and returns contents
    - Gettable: object with \_\_getitem_\_ method
  * **key_ingress** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Function to call on the url before downloading.
    Typically used to notify user that download is happening.
  * **refresh** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)]) – 

    Whether to re-download even if cached. Can be:
    - bool: True to always refresh, False to use cache if available
    - Callable: function(cache_key, url) -> bool to decide dynamically
  * **max_age** ([`int`](https://docs.python.org/3/builtins/functions.html#int) | [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – If not None, number of seconds cached data is considered fresh.
    If cached data is older, it will be re-downloaded. Cannot be used with refresh.
  * **return_key** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, return the cache_key instead of contents.
  * **rootdir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – (DEPRECATED) Use ‘cache’ instead. Folder path for caching.
  * **return_filepaths** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – (DEPRECATED) Use ‘return_key’ instead.

### Examples

```pycon
>>> # Basic usage - caches to default directory
>>> content = graze('http://example.com/data.json')
```

```pycon
>>> # Cache to specific folder
>>> content = graze('http://example.com/data.json', cache='~/my_cache')
```

```pycon
>>> # Cache to specific file (cache defaults to None automatically)
>>> content = graze('http://example.com/data.json', cache_key='~/data/my_data.json')
```

```pycon
>>> # Use custom cache object
>>> from dol import Files
>>> my_cache = Files('~/cache')
>>> content = graze('http://example.com/data.json', cache=my_cache, cache_key='data.json')
```

```pycon
>>> # Force refresh
>>> content = graze('http://example.com/data.json', refresh=True)
```

```pycon
>>> # Conditional refresh based on age
>>> content = graze('http://example.com/data.json', max_age=3600)
```

### graze.base.localpath_to_url(path)

```pycon
>>> localpath_to_url('http/www.example.com_f/subdir1_f/subdir2_f/file.txt')
'http://www.example.com/subdir1/subdir2/file.txt'
>>> localpath_to_url('https://www.example.com_f/subdir1_f/subdir2_f/file.txt_f/')
'https:/www.example.com/subdir1/subdir2/file.txt/'
>>> localpath_to_url('www.example.com/subdir1_f/subdir2_f/file.txt')
'www.example.com/subdir1/subdir2/file.txt'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### graze.base.selenium_url_to_contents(url, response_func=<function \_dflt_selenium_response_func>, browser='Chrome')

Function to get contents from a url, using selenium.

To work, selenium needs to be installed an setup (browser drivers (default is
Chrome)).

See: [https://selenium-python.readthedocs.io/](https://selenium-python.readthedocs.io/)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to fetch
  * **response_func** – The function to call on browser object to return html.
    The default is attrgetter(‘page_source’) which just returns the page_source
    attribute. But a custom function can be specified to check for status first,
    or wait a number of seconds, etc.
  * **browser** – 

    If a string, will use it as a `selenium.webdriver` attribute.
    It’s the user’s responsibility to have the necessary drivers for this to
    work. When using a string, a browser is made and closed once the page is
    fetched. This is inefficient if many pages need to be fetched.
    To reuse the same browser, or a browser with specific properties, one
    can specify a already made browser.

    \`\`
    b = selenium.webdriver.Chrome(…)
    my_selenium = functools.partial(url_to_contents.selenium, browser=b)
    \`\`

    When doing so, the browser is made/opened when `b` is made, and
    won’t be closed by `url_to_contents.selenium`.
    It’s up to the user to close it (`b.close()`) when they don’t need it
    anymore.

### *class* graze.base.url_to_contents

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A place to contain url_to_contents functions. Not meant to be intantiated.
The only reason for it’s existence is to make it easier for a user to choose
available url_to_contents functions using tab suggestions.

The first argument of a url_to_contents function is a URL, and is the only
argument that an Internet object, where these are used, will use.

Any extra arguments in url_to_contents functions are meant to be used with
their defaults or be set by currying (e.g. with `functools.partial`).

For example, one can use a custom `response_func` to get the data in a particular
way, and or wait for a page to load, etc.

#### *static* selenium_chrome(url, response_func=<function \_dflt_selenium_response_func>, \*, browser='Chrome')

Function to get contents from a url, using selenium.

To work, selenium needs to be installed an setup (browser drivers (default is
Chrome)).

See: [https://selenium-python.readthedocs.io/](https://selenium-python.readthedocs.io/)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to fetch
  * **response_func** – The function to call on browser object to return html.
    The default is attrgetter(‘page_source’) which just returns the page_source
    attribute. But a custom function can be specified to check for status first,
    or wait a number of seconds, etc.
  * **browser** – 

    If a string, will use it as a `selenium.webdriver` attribute.
    It’s the user’s responsibility to have the necessary drivers for this to
    work. When using a string, a browser is made and closed once the page is
    fetched. This is inefficient if many pages need to be fetched.
    To reuse the same browser, or a browser with specific properties, one
    can specify a already made browser.

    \`\`
    b = selenium.webdriver.Chrome(…)
    my_selenium = functools.partial(url_to_contents.selenium, browser=b)
    \`\`

    When doing so, the browser is made/opened when `b` is made, and
    won’t be closed by `url_to_contents.selenium`.
    It’s up to the user to close it (`b.close()`) when they don’t need it
    anymore.

#### *static* selenium_firefox(url, response_func=<function \_dflt_selenium_response_func>, \*, browser='Firefox')

Function to get contents from a url, using selenium.

To work, selenium needs to be installed an setup (browser drivers (default is
Chrome)).

See: [https://selenium-python.readthedocs.io/](https://selenium-python.readthedocs.io/)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to fetch
  * **response_func** – The function to call on browser object to return html.
    The default is attrgetter(‘page_source’) which just returns the page_source
    attribute. But a custom function can be specified to check for status first,
    or wait a number of seconds, etc.
  * **browser** – 

    If a string, will use it as a `selenium.webdriver` attribute.
    It’s the user’s responsibility to have the necessary drivers for this to
    work. When using a string, a browser is made and closed once the page is
    fetched. This is inefficient if many pages need to be fetched.
    To reuse the same browser, or a browser with specific properties, one
    can specify a already made browser.

    \`\`
    b = selenium.webdriver.Chrome(…)
    my_selenium = functools.partial(url_to_contents.selenium, browser=b)
    \`\`

    When doing so, the browser is made/opened when `b` is made, and
    won’t be closed by `url_to_contents.selenium`.
    It’s up to the user to close it (`b.close()`) when they don’t need it
    anymore.

#### *static* selenium_opera(url, response_func=<function \_dflt_selenium_response_func>, \*, browser='Opera')

Function to get contents from a url, using selenium.

To work, selenium needs to be installed an setup (browser drivers (default is
Chrome)).

See: [https://selenium-python.readthedocs.io/](https://selenium-python.readthedocs.io/)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to fetch
  * **response_func** – The function to call on browser object to return html.
    The default is attrgetter(‘page_source’) which just returns the page_source
    attribute. But a custom function can be specified to check for status first,
    or wait a number of seconds, etc.
  * **browser** – 

    If a string, will use it as a `selenium.webdriver` attribute.
    It’s the user’s responsibility to have the necessary drivers for this to
    work. When using a string, a browser is made and closed once the page is
    fetched. This is inefficient if many pages need to be fetched.
    To reuse the same browser, or a browser with specific properties, one
    can specify a already made browser.

    \`\`
    b = selenium.webdriver.Chrome(…)
    my_selenium = functools.partial(url_to_contents.selenium, browser=b)
    \`\`

    When doing so, the browser is made/opened when `b` is made, and
    won’t be closed by `url_to_contents.selenium`.
    It’s up to the user to close it (`b.close()`) when they don’t need it
    anymore.

#### *static* selenium_safari(url, response_func=<function \_dflt_selenium_response_func>, \*, browser='Safari')

Function to get contents from a url, using selenium.

To work, selenium needs to be installed an setup (browser drivers (default is
Chrome)).

See: [https://selenium-python.readthedocs.io/](https://selenium-python.readthedocs.io/)

* **Parameters:**
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The url to fetch
  * **response_func** – The function to call on browser object to return html.
    The default is attrgetter(‘page_source’) which just returns the page_source
    attribute. But a custom function can be specified to check for status first,
    or wait a number of seconds, etc.
  * **browser** – 

    If a string, will use it as a `selenium.webdriver` attribute.
    It’s the user’s responsibility to have the necessary drivers for this to
    work. When using a string, a browser is made and closed once the page is
    fetched. This is inefficient if many pages need to be fetched.
    To reuse the same browser, or a browser with specific properties, one
    can specify a already made browser.

    \`\`
    b = selenium.webdriver.Chrome(…)
    my_selenium = functools.partial(url_to_contents.selenium, browser=b)
    \`\`

    When doing so, the browser is made/opened when `b` is made, and
    won’t be closed by `url_to_contents.selenium`.
    It’s up to the user to close it (`b.close()`) when they don’t need it
    anymore.

### graze.base.url_to_file_download(url, filepath=None, \*, url_to_contents=<function url_to_contents.requests_get>, write_contents_to_file=<function \_write_to_file>, url_to_path=<function url_to_localpath>, overwrite=True, url_egress=None, rootdir='/home/runner/.cache/graze', ensure_dirs=True, read_contents_of_file=<function \_read_file>, return_func=<function return_contents>)

Helper to make a url-to-file download functions (using partial).

* **Parameters:**
  * **url** – The url to download from
  * **filepath** – The local file path to download to. If None, will be derived from url
  * **url_to_contents** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The function to get the contents from the url
  * **write_contents_to_file** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – The function to write the contents to a file
  * **url_to_path** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)) – The function to get the local file path from the url
  * **overwrite** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool) | [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Whether to overwrite the file if it exists.
    Can be a boolean, or a function that takes a LocalPath and Url and returns
    a boolean. For example, one can use this to only redownload and overwrite
    the data if the file hasn’t been modified for X days (i.e. stale contents).
  * **url_egress** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The function to call on the url before getting the contents from it.
    This can, for example, be used to notify the user that data is being
    downloaded, or to modify the url before fetching the contents.
    Note you do NOT need it to normalize share links: `graze.share_links`
    already resolves those (Dropbox’s `dl=1` among them) on the way in.
  * **rootdir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The root directory where the file will be stored
  * **ensure_dirs** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether to ensure the directories of the file exist
  * **read_contents_of_file** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The function to read the contents of a file
  * **return_func** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – The function that determines what to return.
    The default is to return the contents, but could be any function of
    filepath, contents and url.

A few recipes:

Download in chunks, and possibly to multiple files in a directory?
You can make `url_to_contents` return the url itself, and `write_contents_to_file`
do the work of opening url and filepath, and launch a get-chunk-write-chunk
process.

Need to decide how to download the url based on some characteristics of the url?
Put this in the url_to_contents logic – or, for a *provider* rule (this is a
Dropbox folder link, so it needs dl=1 and comes back as a ZIP), register an
adapter with `graze.add_share_link_resolver` and let `special_url_routes`
dispatch to it.

### graze.base.url_to_filepath(url, rootdir='/home/runner/.cache/graze', , download=None)

Get the file path for the url.

* **Parameters:**
  * **rootdir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Where to store the contents locally.
  * **download** – Controls when to download the file.
    If None (default), will download only if “necessary”

```pycon
>>> filepath = url_to_filepath(url_of_resource)
```

Use case:

Sometimes you need to specify a filepath as a resource for some python object.
For example, some font definition file, or configuration file, or such.
You can provide the file for the user, or can tell them where they can find
such a file if needed… or you can use the following for the best of both worlds.

```pycon
>>> filepath = url_to_filepath(url_of_resource, download=None)
```

If you want to download the file whether it’s there or not, use:

```pycon
>>> filepath = url_to_filepath(url_of_resource, download=True)
```

### graze.base.url_to_localpath(url)

```pycon
>>> url_to_localpath('http://www.example.com/subdir1/subdir2/file.txt')
'http/www.example.com_f/subdir1_f/subdir2_f/file.txt'
>>> url_to_localpath('https://www.example.com/subdir1/subdir2/file.txt/')
'https/www.example.com_f/subdir1_f/subdir2_f/file.txt'
>>> url_to_localpath('www.example.com/subdir1/subdir2/file.txt')
'www.example.com/subdir1_f/subdir2_f/file.txt'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

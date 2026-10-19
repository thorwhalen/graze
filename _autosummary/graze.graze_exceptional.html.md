# graze.graze_exceptional

Exceptional URLs for Graze

Lightweight support for pre-existing cached data. Uses `_exceptions.json` convention
in cache directory to map URLs to existing files.

Quick start:

```pycon
>>> from graze.graze_exceptional import graze_cache, add_exception
>>>
>>> # Add an exception
>>> add_exception('~/graze', 'http://example.com/data', '/local/data.txt')
>>>
>>> # Use cache (auto-discovers _exceptions.json)
>>> cache = graze_cache('~/graze')
>>> data = cache['http://example.com/data']  # Uses /local/data.txt
```

Module Contents:

graze_exceptional.py
├── \_load_exceptions_from_path()      # Load JSON
├── \_discover_exceptions()            # Auto-discover for Files
├── \_make_exception_getter()          # Create wrapper function
├── \_wrap_with_exceptions()           # Wrap cache
├── graze_cache()                     # Main API
├── add_exception()                   # Management
└── list_exceptions()                 # Management

For more info on design and implementation, see:
[https://github.com/thorwhalen/graze/issues/8](https://github.com/thorwhalen/graze/issues/8)

### Functions

| [`graze_cache`](#graze.graze_exceptional.graze_cache)(cache_or_rootdir, \*[, ...])           | Create or wrap a cache with exceptional URL support.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| [`add_exception`](#graze.graze_exceptional.add_exception)(cache_or_rootdir, url, filepath, \*) | Add an exceptional URL to the cache's exceptions file. |
| [`list_exceptions`](#graze.graze_exceptional.list_exceptions)(cache_or_rootdir, \*[, ...])       | List exceptional URLs in a cache.                      |

### graze.graze_exceptional.add_exception(cache_or_rootdir, url, filepath, , exceptions_filename='_exceptions.json')

Add an exceptional URL to the cache’s exceptions file.

* **Parameters:**
  * **cache_or_rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Cache or rootdir string
  * **url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – URL to map
  * **filepath** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to existing file
  * **exceptions_filename** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of exceptions file in cache directory

### Examples

```pycon
>>> import tempfile
>>> cache_dir = tempfile.mkdtemp()
>>> data_fd, data_path = tempfile.mkstemp()
>>> os.close(data_fd)
>>>
>>> add_exception(cache_dir, 'http://example.com/data', data_path)
>>>
>>> # Verify
>>> exceptions_path = Path(cache_dir) / '_exceptions.json'
>>> exceptions = json.loads(exceptions_path.read_text())
>>> # The stored path should be the resolved absolute path
>>> stored_path = exceptions['http://example.com/data']
>>> Path(stored_path).resolve() == Path(data_path).resolve()
True
>>>
>>> # Cleanup
>>> os.unlink(exceptions_path)
>>> os.unlink(data_path)
>>> os.rmdir(cache_dir)
```

### graze.graze_exceptional.graze_cache(cache_or_rootdir, , exceptions=None, url_to_cache_key=None)

Create or wrap a cache with exceptional URL support.

* **Parameters:**
  * **cache_or_rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Either a cache (MutableMapping) to wrap, or a rootdir string for Files
  * **exceptions** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`None`](https://docs.python.org/3/builtins/constants.html#None), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – 
    - None (default): auto-discover from {rootdir}/_exceptions.json
    - str: path to exceptions JSON file
    - dict: explicit URL -> filepath mapping
  * **url_to_cache_key** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Function to convert URLs to cache keys.
    Only needed if exceptions use URLs and cache uses transformed keys.
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)
* **Returns:**
  Cache with exceptional URL support

### Examples

```pycon
>>> # Auto-discover exceptions
>>> cache = graze_cache('~/graze')
```

```pycon
>>> # Explicit exceptions
>>> cache = graze_cache('~/graze', exceptions={'http://example.com/data': '/local.txt'})
```

```pycon
>>> # Wrap existing cache
>>> from dol import Files
>>> cache = graze_cache(Files('~/graze'))
```

```pycon
>>> # Custom cache (dict example)
>>> my_cache = {'url1': b'data'}
>>> exceptions = {'url2': '/path/to/file.txt'}
>>> cache = graze_cache(my_cache, exceptions=exceptions)
```

### graze.graze_exceptional.list_exceptions(cache_or_rootdir, , exceptions_filename='_exceptions.json', show_paths=False)

List exceptional URLs in a cache.

* **Parameters:**
  * **cache_or_rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Cache or rootdir string
  * **exceptions_filename** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of exceptions file
  * **show_paths** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, return (url, filepath) tuples
* **Returns:**
  List of URLs or list of (url, filepath) tuples

### Examples

```pycon
>>> import tempfile
>>> cache_dir = tempfile.mkdtemp()
>>> data_fd, data_path = tempfile.mkstemp()
>>> os.close(data_fd)
>>>
>>> add_exception(cache_dir, 'http://example.com/data', data_path)
>>> urls = list_exceptions(cache_dir)
>>> urls
['http://example.com/data']
>>>
>>> urls_with_paths = list_exceptions(cache_dir, show_paths=True)
>>> len(urls_with_paths)
1
>>>
>>> # Cleanup
>>> os.unlink(Path(cache_dir) / '_exceptions.json')
>>> os.unlink(data_path)
>>> os.rmdir(cache_dir)
```

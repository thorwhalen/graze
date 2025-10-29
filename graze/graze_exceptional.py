"""
Exceptional URLs for Graze

Lightweight support for pre-existing cached data. Uses `_exceptions.json` convention
in cache directory to map URLs to existing files.

Quick start:

    >>> from graze_exceptional import graze_cache, add_exception
    >>>
    >>> # Add an exception
    >>> add_exception('~/graze', 'http://example.com/data', '/local/data.txt')  # doctest: +SKIP
    >>>
    >>> # Use cache (auto-discovers _exceptions.json)
    >>> cache = graze_cache('~/graze')  # doctest: +SKIP
    >>> data = cache['http://example.com/data']  # Uses /local/data.txt  # doctest: +SKIP

Module Contents:

graze_exceptional.py
├── _load_exceptions_from_path()      # Load JSON
├── _discover_exceptions()            # Auto-discover for Files
├── _make_exception_getter()          # Create wrapper function
├── _wrap_with_exceptions()           # Wrap cache
├── graze_cache()                     # Main API
├── add_exception()                   # Management
└── list_exceptions()                 # Management

For more info on design and implementation, see:
https://github.com/thorwhalen/graze/issues/8

"""

from typing import Union, Dict, Callable
from pathlib import Path
from collections.abc import MutableMapping
import json
import os


def _load_exceptions_from_path(path: Union[str, Path]) -> Dict[str, str]:
    """
    Load exceptions from a JSON file.

    >>> import tempfile
    >>> fd, path = tempfile.mkstemp(suffix='.json')
    >>> with os.fdopen(fd, 'w') as f:
    ...     json.dump({'http://example.com/data': '/tmp/data.txt'}, f)
    >>> exceptions = _load_exceptions_from_path(path)
    >>> exceptions['http://example.com/data']
    '/tmp/data.txt'
    >>> os.unlink(path)
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return {}

    with open(path, 'r') as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


def _discover_exceptions(cache) -> Dict[str, str]:
    """
    Auto-discover exceptions from cache directory.

    For file-based caches, looks for {rootdir}/_exceptions.json
    For other caches, returns empty dict.
    """
    if hasattr(cache, '_rootdir'):
        exceptions_path = Path(cache._rootdir) / '_exceptions.json'
        return _load_exceptions_from_path(exceptions_path)
    return {}


def _make_exception_getter(exceptions: Dict[str, str], original_getitem: Callable):
    """
    Create a __getitem__ wrapper that checks exceptions first.

    >>> exceptions = {'url1': '/tmp/does_not_exist.txt'}
    >>> original = {'url2': b'original data'}.__getitem__
    >>> getter = _make_exception_getter({}, original)
    >>> getter('url2')
    b'original data'
    """
    # Filter to only include files that exist
    valid_exceptions = {
        url: filepath
        for url, filepath in exceptions.items()
        if Path(filepath).expanduser().exists()
    }

    # Warn about missing files
    missing = set(exceptions.keys()) - set(valid_exceptions.keys())
    if missing:
        import warnings

        warnings.warn(
            f"Excluded {len(missing)} exceptional URLs with missing files: {missing}"
        )

    def get_with_exceptions(key):
        """Check exceptions first, then fall back to original."""
        if key in valid_exceptions:
            filepath = valid_exceptions[key]
            with open(Path(filepath).expanduser(), 'rb') as f:
                return f.read()
        return original_getitem(key)

    return get_with_exceptions


def _wrap_with_exceptions(
    cache: MutableMapping, exceptions: Dict[str, str]
) -> MutableMapping:
    """
    Wrap a cache to check exceptions before normal lookup.

    >>> cache = {'url1': b'cached data'}
    >>> import tempfile
    >>> fd, path = tempfile.mkstemp()
    >>> with os.fdopen(fd, 'w') as f:
    ...     _ = f.write('exceptional data')
    >>> exceptions = {'url2': path}
    >>> wrapped = _wrap_with_exceptions(cache, exceptions)
    >>> wrapped['url1']
    b'cached data'
    >>> wrapped['url2']
    b'exceptional data'
    >>> os.unlink(path)
    """
    if not exceptions:
        return cache

    # Try to use dol's wrap_kvs for cleaner wrapping
    try:
        from dol import wrap_kvs

        original_getitem = cache.__getitem__
        getter = _make_exception_getter(exceptions, original_getitem)

        # Use wrap_kvs with obj_of_data to intercept reads
        return wrap_kvs(cache, obj_of_data=lambda data: getter)

    except (ImportError, TypeError):
        # Fallback: simple wrapper class
        class CacheWithExceptions(MutableMapping):
            def __init__(self, cache, exceptions):
                self._cache = cache
                self._getter = _make_exception_getter(exceptions, cache.__getitem__)

            def __getitem__(self, key):
                return self._getter(key)

            def __setitem__(self, key, value):
                self._cache[key] = value

            def __delitem__(self, key):
                del self._cache[key]

            def __iter__(self):
                return iter(self._cache)

            def __len__(self):
                return len(self._cache)

        return CacheWithExceptions(cache, exceptions)


def graze_cache(
    cache_or_rootdir: Union[MutableMapping, str],
    *,
    exceptions: Union[None, str, Dict[str, str]] = None,
) -> MutableMapping:
    """
    Create or wrap a cache with exceptional URL support.

    Args:
        cache_or_rootdir: Either a cache (MutableMapping) to wrap, or a rootdir string for Files
        exceptions:
            - None (default): auto-discover from {rootdir}/_exceptions.json
            - str: path to exceptions JSON file
            - dict: explicit URL -> filepath mapping

    Returns:
        Cache with exceptional URL support

    Examples:
        >>> # Auto-discover exceptions
        >>> cache = graze_cache('~/graze')  # doctest: +SKIP

        >>> # Explicit exceptions
        >>> cache = graze_cache('~/graze', exceptions={'http://example.com/data': '/local.txt'})  # doctest: +SKIP

        >>> # Wrap existing cache
        >>> from dol import Files  # doctest: +SKIP
        >>> cache = graze_cache(Files('~/graze'))  # doctest: +SKIP

        >>> # Custom cache (dict example)
        >>> my_cache = {'url1': b'data'}
        >>> exceptions = {'url2': '/path/to/file.txt'}
        >>> cache = graze_cache(my_cache, exceptions=exceptions)  # doctest: +SKIP
    """
    # Create cache from rootdir if string provided
    if isinstance(cache_or_rootdir, str):
        from dol import Files

        cache = Files(cache_or_rootdir)
    else:
        cache = cache_or_rootdir

    # Load exceptions
    if exceptions is None:
        # Auto-discover
        exceptions = _discover_exceptions(cache)
    elif isinstance(exceptions, str):
        # Load from file path
        exceptions = _load_exceptions_from_path(exceptions)
    # else: use dict as-is

    # Wrap if we have exceptions
    if exceptions:
        return _wrap_with_exceptions(cache, exceptions)

    return cache


def add_exception(
    cache_or_rootdir: Union[MutableMapping, str],
    url: str,
    filepath: str,
    *,
    exceptions_filename: str = '_exceptions.json',
):
    """
    Add an exceptional URL to the cache's exceptions file.

    Args:
        cache_or_rootdir: Cache or rootdir string
        url: URL to map
        filepath: Path to existing file
        exceptions_filename: Name of exceptions file in cache directory

    Examples:
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
        >>> exceptions['http://example.com/data'] == data_path
        True
        >>>
        >>> # Cleanup
        >>> os.unlink(exceptions_path)
        >>> os.unlink(data_path)
        >>> os.rmdir(cache_dir)
    """
    # Get rootdir
    if isinstance(cache_or_rootdir, str):
        rootdir = Path(cache_or_rootdir).expanduser().resolve()
    elif hasattr(cache_or_rootdir, '_rootdir'):
        rootdir = Path(cache_or_rootdir._rootdir)
    else:
        raise ValueError(
            "Cannot determine rootdir. Pass a string path or cache with _rootdir attribute."
        )

    # Validate file exists
    filepath = str(Path(filepath).expanduser().resolve())
    if not Path(filepath).exists():
        raise FileNotFoundError(f"File does not exist: {filepath}")

    # Load existing exceptions
    exceptions_path = rootdir / exceptions_filename
    if exceptions_path.exists():
        exceptions = json.loads(exceptions_path.read_text())
    else:
        exceptions = {}

    # Add new exception
    exceptions[url] = filepath

    # Save
    rootdir.mkdir(parents=True, exist_ok=True)
    exceptions_path.write_text(json.dumps(exceptions, indent=2, sort_keys=True))


def list_exceptions(
    cache_or_rootdir: Union[MutableMapping, str],
    *,
    exceptions_filename: str = '_exceptions.json',
    show_paths: bool = False,
):
    """
    List exceptional URLs in a cache.

    Args:
        cache_or_rootdir: Cache or rootdir string
        exceptions_filename: Name of exceptions file
        show_paths: If True, return (url, filepath) tuples

    Returns:
        List of URLs or list of (url, filepath) tuples

    Examples:
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
    """
    # Get rootdir
    if isinstance(cache_or_rootdir, str):
        rootdir = Path(cache_or_rootdir).expanduser().resolve()
    elif hasattr(cache_or_rootdir, '_rootdir'):
        rootdir = Path(cache_or_rootdir._rootdir)
    else:
        return [] if not show_paths else []

    # Load exceptions
    exceptions_path = rootdir / exceptions_filename
    if not exceptions_path.exists():
        return [] if not show_paths else []

    exceptions = json.loads(exceptions_path.read_text())

    if show_paths:
        return list(exceptions.items())
    return list(exceptions.keys())


__all__ = [
    'graze_cache',
    'add_exception',
    'list_exceptions',
]

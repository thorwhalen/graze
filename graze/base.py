"""Base functionality"""

from typing import Optional, Union, Any, Protocol, Iterator
from collections.abc import Callable, MutableMapping
import os
import time
from warnings import warn
from operator import attrgetter
from functools import partialmethod, partial

import requests

# from py2store.persisters.local_files import ensure_slash_suffix
from dol.filesys import ensure_slash_suffix

# from py2store import add_ipython_key_completions, wrap_kvs, LocalBinaryStore
from dol import add_ipython_key_completions, wrap_kvs, Files

# from py2store.stores.local_store import AutoMkDirsOnSetitemMixin
from dol import mk_dirs_if_missing

from graze.util import (
    handle_missing_dir,
    is_special_url,
    download_from_special_url,
    human_readable_bytes,
    get_content_size,
    inner_most_key,
)

Url = str
LocalPath = str
Contents = Union[bytes, str]


class Gettable(Protocol):
    """Protocol for objects with __getitem__ method."""

    def __getitem__(self, key: str) -> Contents: ...


# TODO: handle configuration and existence of root
pjoin = os.path.join
psep = os.path.sep

URL = str
DFLT_GRAZE_DIR = os.path.expanduser("~/graze")

# TODO: Make url-localpath conversion a plugin (with class or partials)
SUBDIR_SUFFIX = "_f"
SUBDIR_SUFFIX_IDX = -len(SUBDIR_SUFFIX)


def url_to_localpath(url: str) -> str:
    """
    >>> url_to_localpath('http://www.example.com/subdir1/subdir2/file.txt')
    'http/www.example.com_f/subdir1_f/subdir2_f/file.txt'
    >>> url_to_localpath('https://www.example.com/subdir1/subdir2/file.txt/')
    'https/www.example.com_f/subdir1_f/subdir2_f/file.txt'
    >>> url_to_localpath('www.example.com/subdir1/subdir2/file.txt')
    'www.example.com/subdir1_f/subdir2_f/file.txt'
    """
    path = url.replace("https://", "https/").replace("http://", "http/")
    path_subdirs = list(filter(None, path.split(psep)))
    path_subdirs[1:-1] = [x + SUBDIR_SUFFIX for x in path_subdirs[1:-1]]
    return pjoin(*path_subdirs)


def localpath_to_url(path: str) -> str:
    """
    >>> localpath_to_url('http/www.example.com_f/subdir1_f/subdir2_f/file.txt')
    'http://www.example.com/subdir1/subdir2/file.txt'
    >>> localpath_to_url('https://www.example.com_f/subdir1_f/subdir2_f/file.txt_f/')
    'https:/www.example.com/subdir1/subdir2/file.txt/'
    >>> localpath_to_url('www.example.com/subdir1_f/subdir2_f/file.txt')
    'www.example.com/subdir1/subdir2/file.txt'
    """
    path_subdirs = path.split(psep)
    path_subdirs[1:-1] = [x[:SUBDIR_SUFFIX_IDX] for x in path_subdirs[1:-1]]
    url = pjoin(*path_subdirs)
    return url.replace("https/", "https://").replace("http/", "http://")


_url_to_localpath = url_to_localpath  # backward compatibility
_localpath_to_url = localpath_to_url  # backward compatibility


# --------------------------------------------------------------------------------------
# Cache helpers for flexible caching backends


def _is_full_filepath(path: str) -> bool:
    """
    Check if path is a full filepath (platform-independent).

    >>> _is_full_filepath('/usr/local/data')
    True
    >>> _is_full_filepath('~/data')
    True
    >>> _is_full_filepath('relative/path')
    False
    >>> _is_full_filepath('C:\\\\Users\\\\data')  # doctest: +SKIP
    True
    """
    if path.startswith("~"):
        return True
    if os.path.isabs(path):
        return True
    # Check for Windows absolute paths on Windows
    if os.name == "nt" and len(path) > 1 and path[1] == ":":
        return True
    return False


def _resolve_cache_and_key(
    url: str,
    cache: Optional[Union[str, MutableMapping]],
    cache_key: Optional[Union[str, Callable]],
    rootdir: Optional[str] = None,
) -> tuple[Optional[Union[str, MutableMapping]], str, bool]:
    """
    Resolve cache and cache_key, handling conflicts and defaults.

    Returns:
        tuple: (resolved_cache, resolved_cache_key, is_explicit_filepath)
    """
    # Handle backwards compatibility: rootdir vs cache conflict
    if rootdir is not None and cache is not None:
        raise ValueError(
            "Cannot specify both 'rootdir' and 'cache'. "
            "'rootdir' is deprecated; use 'cache' instead."
        )

    # Use rootdir if cache not specified (backwards compatibility)
    if cache is None and rootdir is not None:
        cache = rootdir

    # Resolve cache_key
    if cache_key is None:
        resolved_cache_key = url_to_localpath(url)
    elif callable(cache_key):
        resolved_cache_key = cache_key(url)
    else:
        resolved_cache_key = cache_key

    # Check if cache_key is a full filepath
    is_explicit_filepath = _is_full_filepath(resolved_cache_key)

    if is_explicit_filepath and cache is not None:
        raise ValueError(
            f"cache_key appears to be a full filepath ({resolved_cache_key}), "
            f"but 'cache' was also provided ({cache}). This is ambiguous. "
            f"Either provide cache_key as a full filepath with cache=None, "
            f"or provide both cache and a relative cache_key."
        )

    return cache, resolved_cache_key, is_explicit_filepath


def _cache_contains(
    cache: Optional[Union[str, MutableMapping]],
    cache_key: str,
    is_explicit_filepath: bool,
) -> bool:
    """Check if cache contains the key."""
    if is_explicit_filepath:
        expanded_path = os.path.expanduser(cache_key)
        return os.path.exists(expanded_path)

    if cache is None:
        return False

    if isinstance(cache, str):
        # It's a folder path
        expanded_cache = os.path.expanduser(cache)
        full_path = os.path.join(expanded_cache, cache_key)
        return os.path.exists(full_path)

    # It's a MutableMapping
    try:
        return cache_key in cache
    except (TypeError, KeyError):
        return False


def _cache_get(
    cache: Optional[Union[str, MutableMapping]],
    cache_key: str,
    is_explicit_filepath: bool,
) -> Optional[Contents]:
    """Get contents from cache."""
    if is_explicit_filepath:
        expanded_path = os.path.expanduser(cache_key)
        if os.path.exists(expanded_path):
            with open(expanded_path, "rb") as f:
                return f.read()
        return None

    if cache is None:
        return None

    if isinstance(cache, str):
        # It's a folder path
        expanded_cache = os.path.expanduser(cache)
        full_path = os.path.join(expanded_cache, cache_key)
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                return f.read()
        return None

    # It's a MutableMapping
    try:
        return cache[cache_key]
    except (KeyError, TypeError):
        return None


def _cache_set(
    cache: Optional[Union[str, MutableMapping]],
    cache_key: str,
    contents: Contents,
    is_explicit_filepath: bool,
):
    """Store contents in cache."""
    if is_explicit_filepath:
        expanded_path = os.path.expanduser(cache_key)
        os.makedirs(os.path.dirname(expanded_path) or ".", exist_ok=True)
        with open(expanded_path, "wb") as f:
            f.write(contents)
        return

    if cache is None:
        return

    if isinstance(cache, str):
        # It's a folder path
        expanded_cache = os.path.expanduser(cache)
        full_path = os.path.join(expanded_cache, cache_key)
        os.makedirs(os.path.dirname(full_path) or expanded_cache, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(contents)
        return

    # It's a MutableMapping - need to ensure directories exist if it's file-based
    # Try to create dirs for the key (gracefully handle if cache doesn't support it)
    try:
        # For Files and similar stores, we need to ensure parent dirs exist
        if hasattr(cache, 'rootdir'):
            # It's likely a file-based store like Files
            full_path = os.path.join(cache.rootdir, cache_key)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
    except (AttributeError, OSError):
        # Not a file-based store, or dirs already exist, just continue
        pass

    cache[cache_key] = contents


def _should_refresh(
    refresh: Union[bool, Callable],
    cache: Optional[Union[str, MutableMapping]],
    cache_key: str,
    url: str,
    is_explicit_filepath: bool,
) -> bool:
    """Determine if content should be refreshed."""
    if isinstance(refresh, bool):
        return refresh

    if callable(refresh):
        return refresh(cache_key, url)

    raise ValueError(f"refresh must be bool or callable. Got: {type(refresh)}")


def _max_age_to_refresh_func(max_age: Union[int, float]) -> Callable:
    """Convert max_age to a refresh function."""

    def refresh_func(cache_key: str, url: str) -> bool:
        # For MutableMapping, we can't easily check file age
        # So we return False (don't refresh) - the old behavior with Graze
        # Note: This is a limitation, but maintains backwards compatibility
        # For file-based caches, check the modification time
        if _is_full_filepath(cache_key):
            filepath = os.path.expanduser(cache_key)
        else:
            # Assume it's in DFLT_GRAZE_DIR if we can't determine
            filepath = os.path.join(DFLT_GRAZE_DIR, cache_key)

        if not os.path.exists(filepath):
            return True  # File doesn't exist, so we need to fetch

        age = time.time() - os.stat(filepath).st_mtime
        return age > max_age

    return refresh_func


# End of cache helpers
# --------------------------------------------------------------------------------------


# CONTENT_FILENAME = 'grazed'
FOLDER_SUFFIX = SUBDIR_SUFFIX  # TODO: Check usage and delete if none
# CONTENT_PATH_SUFFIX = psep + CONTENT_FILENAME
# CONTENT_FILENAME_INDEX = -len(CONTENT_PATH_SUFFIX)

# def _url_to_localpath(url: str) -> str:
#     path = url.replace('https://', 'https/').replace('http://', 'http/')
#     return pjoin(path, CONTENT_FILENAME)
#
#
# def _localpath_to_url(path: str) -> str:
#     assert path.endswith(psep + CONTENT_FILENAME), f'Not a valid key: {path}'
#     # remove the /CONTENT_FILENAME part
#     path = path[:CONTENT_FILENAME_INDEX]
#     return path.replace('https/', 'https://').replace('http/', 'http://')


@mk_dirs_if_missing
class LocalFiles(Files):
    """Store to read/write/delete local files, creating directories on write."""

    def __init__(self, rootdir=DFLT_GRAZE_DIR):
        handle_missing_dir(rootdir)
        super().__init__(ensure_slash_suffix(rootdir))


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=localpath_to_url,
    id_of_key=url_to_localpath,
)
class LocalGrazed(LocalFiles):
    """LocalFiles using url as keys"""


class RequestFailure(RuntimeError):
    """To be used when the request to get the contents of a url failed"""


def _dflt_selenium_response_func(response_obj):
    page_src = response_obj.page_source
    if isinstance(page_src, str):
        return page_src.encode()
    return page_src


def selenium_url_to_contents(
    url: URL, response_func=_dflt_selenium_response_func, browser="Chrome"
):
    """Function to get contents from a url, using selenium.

    To work, selenium needs to be installed an setup (browser drivers (default is
    Chrome)).

    See: https://selenium-python.readthedocs.io/

    :param url: The url to fetch
    :param response_func: The function to call on browser object to return html.
        The default is attrgetter('page_source') which just returns the page_source
        attribute. But a custom function can be specified to check for status first,
        or wait a number of seconds, etc.
    :param browser: If a string, will use it as a `selenium.webdriver` attribute.
        It's the user's responsibility to have the necessary drivers for this to
        work. When using a string, a browser is made and closed once the page is
        fetched. This is inefficient if many pages need to be fetched.
        To reuse the same browser, or a browser with specific properties, one
        can specify a already made browser.

        ``
        b = selenium.webdriver.Chrome(...)
        my_selenium = functools.partial(url_to_contents.selenium, browser=b)
        ``

        When doing so, the browser is made/opened when ``b`` is made, and
        won't be closed by ``url_to_contents.selenium``.
        It's up to the user to close it (``b.close()``) when they don't need it
        anymore.


    """
    from selenium import webdriver  # See: https://selenium-python.readthedocs.io/

    if isinstance(browser, str):
        browser_name = browser
        mk_browser = getattr(webdriver, browser_name)
        browser = mk_browser()  # start web browser
        close_after_use = True
    else:
        close_after_use = False

    browser.get(url)
    html = response_func(browser)
    if close_after_use:
        browser.close()
    return html


class url_to_contents:
    """A place to contain url_to_contents functions. Not meant to be intantiated.
    The only reason for it's existence is to make it easier for a user to choose
    available url_to_contents functions using tab suggestions.

    The first argument of a url_to_contents function is a URL, and is the only
    argument that an Internet object, where these are used, will use.

    Any extra arguments in url_to_contents functions are meant to be used with
    their defaults or be set by currying (e.g. with `functools.partial`).

    For example, one can use a custom `response_func` to get the data in a particular
    way, and or wait for a page to load, etc.

    """

    def __init__(self):
        raise ValueError(
            "Not meant to be instantiated: Just to hold url_to_contents functions"
        )

    @staticmethod
    def requests_get(url: URL, response_func=attrgetter("content"), **request_kwargs):
        resp = requests.request("get", url=url, **request_kwargs)
        if resp.status_code == 200:
            return response_func(resp)
        else:
            raise RequestFailure(
                f"Response code was {resp.status_code}.\n"
                f"The first 500 characters of the content were: {resp.content[:500]}"
            )

    selenium_chrome = staticmethod(partial(selenium_url_to_contents, browser="Chrome"))
    selenium_safari = staticmethod(partial(selenium_url_to_contents, browser="Safari"))
    selenium_opera = staticmethod(partial(selenium_url_to_contents, browser="Opera"))
    selenium_firefox = staticmethod(
        partial(selenium_url_to_contents, browser="Firefox")
    )


DFLT_URL_TO_CONTENT = url_to_contents.requests_get

# Moved to util
# TODO: Should move more of this stuff below to util too
# def _ensure_dirs_of_file_exists(filepath: str):
#     """Recursively ensure all dirs necessary for filepath exist.
#     Return filepath (useful for pipelines)"""
#     dirpath = os.path.dirname(filepath)
#     os.makedirs(dirpath, exist_ok=True)  # TODO: REALLY don't like this here.
#     return filepath
from graze.util import _ensure_dirs_of_file_exists


def _write_to_file(contents, filepath, *, mode="wb"):
    with open(filepath, mode) as f:
        f.write(contents)
    return filepath


def _read_file(filepath, *, mode="rb"):
    with open(filepath, mode) as f:
        return f.read()


def return_contents(filepath, contents, url):
    return contents


def return_filepath(filepath, contents, url):
    return filepath


# Typical function to use as a key_ingress to Graze
def key_egress_print_downloading_message(url):
    print(f"The contents of {url} are being downloaded")
    return url


def key_egress_print_downloading_message_with_size(url):
    size = get_content_size(url)
    if size is None:
        size = " (size unknown)"
    else:
        size = f" ({human_readable_bytes(size)})"
    print(f"The contents {size} of {url} are being downloaded...")
    return url


# TODO: The function boils down a more abstract key-value caching pattern.
#   (src_key, targ_key, *, read_src_key, write_to_targ_key, src_key_to_targ_key, ...)
# TODO: This function is in line to become the most central function of the package.
#   -> Refactor the package to use it?
def url_to_file_download(
    url,
    filepath=None,
    *,
    url_to_contents: Callable[[Url], Contents] = DFLT_URL_TO_CONTENT,
    write_contents_to_file: Callable[[Contents, LocalPath], Any] = _write_to_file,
    url_to_path: Callable = url_to_localpath,
    overwrite: bool | Callable[[LocalPath, Url], bool] = True,
    url_egress: Callable[[Url], Url] | None = None,
    rootdir: LocalPath = DFLT_GRAZE_DIR,
    ensure_dirs: bool = True,
    read_contents_of_file: Callable[[LocalPath], Contents] = _read_file,
    return_func: Callable[[LocalPath, Contents, Url], Any] = return_contents,
):
    """Helper to make a url-to-file download functions (using partial).

    Args:
        url: The url to download from
        filepath: The local file path to download to. If None, will be derived from url
        url_to_contents: The function to get the contents from the url
        write_contents_to_file: The function to write the contents to a file
        url_to_path: The function to get the local file path from the url
        overwrite: Whether to overwrite the file if it exists.
            Can be a boolean, or a function that takes a LocalPath and Url and returns
            a boolean. For example, one can use this to only redownload and overwrite
            the data if the file hasn't been modified for X days (i.e. stale contents).
        url_egress: The function to call on the url before getting the contents from it.
            This can, for example, be used to notify the user that data is being
            downloaded, or to modify the url before fetching the contents (for example,
            replacing the dl=0 in a dropbox url with dl=1).
        rootdir: The root directory where the file will be stored
        ensure_dirs: Whether to ensure the directories of the file exist
        read_contents_of_file: The function to read the contents of a file
        return_func: The function that determines what to return.
            The default is to return the contents, but could be any function of
            filepath, contents and url.

    A few recipes:

    Download in chunks, and possibly to multiple files in a directory?
    You can make `url_to_contents` return the url itself, and `write_contents_to_file`
    do the work of opening url and filepath, and launch a get-chunk-write-chunk
    process.

    Need to decide how to download the url based on some characteristics of the url?
    For example, if it's a dropbox url with dl=0, change that to dl=1.
    Put this in the url_to_contents logic.

    """
    if filepath is None:
        filepath = os.path.join(rootdir, url_to_path(url))

    if os.path.exists(filepath) and not overwrite:
        # if file exists and we're not supposed to overwrite it, just get the contents
        contents = read_contents_of_file(filepath)
    else:
        # if not, get the contents of the url
        url = url if url_egress is None else url_egress(url)
        contents = url_to_contents(url)
        if ensure_dirs:
            _ensure_dirs_of_file_exists(filepath)
        write_contents_to_file(contents, filepath)

    return return_func(filepath, contents, url)


_url_to_file_download = url_to_file_download  # backcompatibility alias


# TODO: Think of a better way to handle the contents vs file download cases
#   For example, better if Internet is not aware at all of local files
class Internet:
    def __init__(
        self,
        url_to_contents=DFLT_URL_TO_CONTENT,
        url_to_file_download=None,  # TODO: Find a good explicit default
    ):
        """From the url, get content off the internet.

        :param url_to_contents: The function that gets you the contents from the url
        """
        self.url_to_contents = url_to_contents
        if url_to_file_download is None:
            url_to_file_download = partial(
                _url_to_file_download, url_to_contents=url_to_contents
            )
        self.url_to_file_download = url_to_file_download

    # TODO: implement the key-specific getitem mapping externally to make it open-closed
    def __getitem__(self, k):
        k = k.strip()
        if k.endswith("/"):
            # because it shouldn't matter as url (?) and having it leads to dirs (not
            # files) being created:
            k = k[:-1]

        if is_special_url(k):
            return download_from_special_url(k)
        else:
            return self._get_contents_of_url(k)

    def _get_contents_of_url(self, url, file=None):
        try:
            if file is None:
                return self.url_to_contents(url)
            else:
                return self.url_to_file_download(url, file)
        except RequestFailure as e:
            raise KeyError(str(e))

    def download_to_file(self, url, file=None):
        """Download the contents of the url to the given filepath"""
        url = url.strip()
        if url.endswith("/"):
            # because it shouldn't matter as url (?) and having it leads to dirs (not
            # files) being created:
            url = url[:-1]

        if is_special_url(url):
            return download_from_special_url(url, file)
        else:
            return self._get_contents_of_url(url, file)


# TODO: Use reususable caching decorator?
# TODO: Not seeing the right signature, but the LocalGrazed one!


# --------------------------------------------------------------------------------------
# Helper functions for GrazeBase
# --------------------------------------------------------------------------------------


def _iterate_cache(
    cache: Optional[Union[str, MutableMapping]],
    cache_key_to_url: Callable[[str], str] = localpath_to_url,
) -> Iterator[str]:
    """Iterate over URLs in cache.

    Args:
        cache: The cache (folder path, MutableMapping, or None)
        cache_key_to_url: Function to convert cache keys to URLs

    Yields:
        URLs (str)
    """
    if cache is None:
        return

    if isinstance(cache, str):
        # It's a folder path
        expanded_cache = os.path.expanduser(cache)
        if not os.path.exists(expanded_cache):
            return

        # Walk the directory and yield URLs
        for root, dirs, files in os.walk(expanded_cache):
            for filename in files:
                # Get relative path from cache root
                filepath = os.path.join(root, filename)
                relpath = os.path.relpath(filepath, expanded_cache)
                # Convert to URL
                yield cache_key_to_url(relpath)
    else:
        # It's a MutableMapping
        for key in cache:
            yield cache_key_to_url(key)


def _get_cache_size(cache: Optional[Union[str, MutableMapping]]) -> int:
    """Get the number of items in cache."""
    if cache is None:
        return 0

    if isinstance(cache, str):
        expanded_cache = os.path.expanduser(cache)
        if not os.path.exists(expanded_cache):
            return 0
        count = 0
        for root, dirs, files in os.walk(expanded_cache):
            count += len(files)
        return count
    else:
        return len(cache)


# --------------------------------------------------------------------------------------
# GrazeBase: The foundation class that uses graze() function
# --------------------------------------------------------------------------------------


class GrazeBase(MutableMapping):
    """Base class for Graze that wraps the graze() function.

    This class provides a MutableMapping interface (dict-like) where:
    - Keys are URLs
    - Values are the contents of those URLs (bytes)
    - Items are cached locally (in folder, Files, or dict)

    The key design principle: All actual work is delegated to the graze() function.
    This class just provides the Mapping interface and state management.

    Args:
        cache: Where to cache contents. Can be:
            - str: folder path for file-based caching
            - MutableMapping: custom cache (e.g., Files, dict)
            - None: uses DFLT_GRAZE_DIR
        source: Where to get contents if not cached. Defaults to Internet().
        key_ingress: Function to call on URL before downloading.
        url_to_cache_key: Function to convert URL to cache key.
            Defaults to url_to_localpath.
        cache_key_to_url: Function to convert cache key back to URL.
            Defaults to localpath_to_url.

    Examples:
        >>> # With folder cache (default)
        >>> g = GrazeBase(cache='~/my_cache')  # doctest: +SKIP
        >>> content = g['http://example.com/data.json']  # doctest: +SKIP

        >>> # With Files cache
        >>> from dol import Files
        >>> g = GrazeBase(cache=Files('~/cache'))  # doctest: +SKIP

        >>> # With dict cache (in-memory)
        >>> g = GrazeBase(cache={})  # doctest: +SKIP
    """

    def __init__(
        self,
        cache: Optional[Union[str, MutableMapping]] = None,
        *,
        source: Union[Callable, Gettable] = None,
        key_ingress: Callable | None = None,
        url_to_cache_key: Callable[[str], str] = url_to_localpath,
        cache_key_to_url: Callable[[str], str] = localpath_to_url,
        refresh: Union[bool, Callable] = False,
    ):
        # Set defaults
        if cache is None:
            cache = DFLT_GRAZE_DIR
        if source is None:
            source = Internet()

        # Store configuration
        self.cache = cache
        self.source = source
        self.key_ingress = key_ingress
        self.url_to_cache_key = url_to_cache_key
        self.cache_key_to_url = cache_key_to_url
        self.refresh = refresh

    def __getitem__(self, url: str) -> Contents:
        """Get contents for URL (downloads if not cached)."""
        cache_key = self.url_to_cache_key(url)
        return graze(
            url,
            cache=self.cache,
            cache_key=cache_key,
            source=self.source,
            key_ingress=self.key_ingress,
            refresh=self.refresh,
        )

    def __setitem__(self, url: str, contents: Contents):
        """Manually set contents for URL in cache."""
        cache_key = self.url_to_cache_key(url)
        _cache_set(self.cache, cache_key, contents, is_explicit_filepath=False)

    def __delitem__(self, url: str):
        """Delete cached contents for URL."""
        cache_key = self.url_to_cache_key(url)

        # Check if it exists first
        if not _cache_contains(self.cache, cache_key, is_explicit_filepath=False):
            raise KeyError(url)

        if isinstance(self.cache, str):
            # It's a folder path - delete the file
            expanded_cache = os.path.expanduser(self.cache)
            filepath = os.path.join(expanded_cache, cache_key)
            if os.path.isfile(filepath):
                os.remove(filepath)
            else:
                raise KeyError(url)
        else:
            # It's a MutableMapping
            del self.cache[cache_key]

    def __contains__(self, url: str) -> bool:
        """Check if URL is cached."""
        cache_key = self.url_to_cache_key(url)
        return _cache_contains(self.cache, cache_key, is_explicit_filepath=False)

    def __iter__(self) -> Iterator[str]:
        """Iterate over cached URLs."""
        return _iterate_cache(self.cache, self.cache_key_to_url)

    def __len__(self) -> int:
        """Return number of cached URLs."""
        return _get_cache_size(self.cache)

    def __repr__(self):
        cache_repr = (
            repr(self.cache) if not isinstance(self.cache, str) else f"'{self.cache}'"
        )
        return f"{self.__class__.__name__}(cache={cache_repr})"


# TODO: Use reususable caching decorator?
# TODO: Not seeing the right signature, but the LocalGrazed one!
class Graze(GrazeBase):
    """A data access object that will get data from the internet if it's not
    already stored locally.

    The interface of ``Graze`` instances is a ``typing.Mapping`` (i.e. ``dict``-like).
    When you list (or iterate over) keys, you'll get the urls
    whose contents are stored locally.
    When you get a value, you'll get the contents of the url (in bytes).
    ``Graze`` will first look if the contents are stored locally, and return that,
    if not it will get the contents from the internet and store it locally,
    then return those bytes.

    This class now extends GrazeBase and delegates most work to the graze() function.
    """

    def __init__(
        self,
        rootdir=DFLT_GRAZE_DIR,
        source=Internet(),
        *,
        key_ingress: Callable | None = None,
        return_filepaths: bool = False,
    ):
        """
        :param rootdir: Where to store the contents locally.
        :param source: Where to get the contents from if they're not already stored
            locally. By default, it's an ``Internet`` instance, but can be a custom
            object that has a ``__getitem__`` method that takes a url and returns
            its contents.
        :param key_ingress: A function to call on the key before getting the contents from
            ``source``. By default, this is used to notify the user that the contents
            are being downloaded.
        :param return_filepaths: If True, will return the path to the file where the
            contents are stored, instead of the contents themselves.


        """
        # Handle key_ingress=True shortcut
        if key_ingress is True:
            key_ingress = key_egress_print_downloading_message

        # Initialize GrazeBase with mapped parameters
        super().__init__(
            cache=rootdir,
            source=source,
            key_ingress=key_ingress,
        )

        # Store attributes for backwards compatibility
        self.rootdir = rootdir
        self.source = source
        self.key_ingress = key_ingress
        self.return_filepaths = return_filepaths

    def __getitem__(self, url: str) -> Union[Contents, str]:
        """Get contents for URL (or filepath if return_filepaths=True)."""
        if self.return_filepaths:
            # Return the filepath instead of contents
            cache_key = self.url_to_cache_key(url)
            return graze(
                url,
                cache=self.cache,
                cache_key=cache_key,
                source=self.source,
                key_ingress=self.key_ingress,
                refresh=self.refresh,
                return_key=True,
            )
        else:
            # Normal behavior - return contents
            return super().__getitem__(url)

    def filepath_of(self, url: str) -> str:
        """Get the filepath of where graze stored (or would store) the contents for a url locally."""
        cache_key = self.url_to_cache_key(url)
        if isinstance(self.cache, str):
            # It's a folder path
            expanded_cache = os.path.expanduser(self.cache)
            return os.path.join(expanded_cache, cache_key)
        else:
            # For MutableMapping, if it has a rootdir, use that
            if hasattr(self.cache, 'rootdir'):
                return os.path.join(self.cache.rootdir, cache_key)
            # Otherwise, just return the cache_key (which may not be a filepath)
            return cache_key

    def filepath_of_url_downloading_if_necessary(self, url):
        """Get the file path for the url, downloading contents before hand if necessary.

        Use case:

        Sometimes you need to specify a filepath as a resource for some python object.
        For example, some font definition file, or configuration file, or such.
        You can provide the file for the user, or can tell them where they can find
        such a file if needed...
        Use `filepath_of_url_downloading_if_necessary` to get that local filepath,
        ensuring that the data is there before hand.
        """
        if url not in self:
            _ = self[url]  # load to make sure we have it (getting it if not)
        return self.filepath_of(url)

    def __reduce__(self):
        return (Graze, (), {"rootdir": self.rootdir, "source": self.source})


# TODO: The following is to cope with https://github.com/i2mint/dol/issues/6
#  --> Remove when resolved
from inspect import signature

Graze.__signature__ = signature(Graze.__init__)


A_WEEK_IN_SECONDS = 7 * 24 * 60 * 60  # one week

GrazeReturningFilepaths = partial(Graze, return_filepaths=True)
GrazeReturningFilepaths.__doc__ = """
A Graze that returns filepaths instead of the contents of the url.

It will still do what graze does (i.e. download the data if it's not already there,
and use url keys (mapped to local filepaths). Only difference is it doesn't return
the contents of the url, but the filepath of the local file where the contents
are stored (once they are stored).

This is useful when you want to use the data in a way that doesn't require
loading the data in memory.

For example, let's say you're going to call a function that requires a filepath
as an input, and you want that function to use a specific url's contents as input.
Sure, you can write some docs telling the user to download the data and use the
filepath, but it's nicer if you can just give them the url, (or have the url even
be in the defaults) and let the function do the downloading if and when necessary.
"""

from typing import Literal


# TODO: Would be nicer to solve this with a reusable ttl caching decorator!
#       (or possibly, with a key_ingress enhancement)
class GrazeWithDataRefresh(Graze):
    def __init__(
        self,
        rootdir=DFLT_GRAZE_DIR,
        source=Internet(),
        *,
        key_ingress: Callable | None = None,
        time_to_live: int | float = 0,
        on_error: Literal[
            "warn", "raise", "ignore", "warn_and_return_local"
        ] = "ignore",
        return_filepaths: bool = False,
    ):
        """Like Graze, but where you can specify a time_to_live "freshness threshold"
        to trigger the re-download of data

        Note: The default is time_to_live=0, on_error='ignore'. This means that
        the data will be re-downloaded every time you ask for it, and if there's
        an error, the stale data will be returned.

        :param time_to_live: In seconds.
        :param on_error: What to do if there's an error when fetching the new data.
            'raise' raise an error (but keep the cached data)
            'warn' warn the user of the stale data (but return anyway)
            'ignore' ignore the error, and return the stale data
            'warn_and_return_local' warn the user of the stale data, but return the
            stale data anyway

        """
        # Store time_to_live and on_error before calling super().__init__
        self.time_to_live = time_to_live
        self.on_error = on_error

        # Create refresh function based on time_to_live
        refresh_func = self._make_refresh_func()

        # Initialize parent with refresh function
        # NOTE: We can't pass refresh to super().__init__ directly because
        # Graze.__init__ doesn't accept it. So we'll set it after.
        super().__init__(
            rootdir,
            source=source,
            key_ingress=key_ingress,
            return_filepaths=return_filepaths,
        )

        # Override the refresh attribute from GrazeBase
        self.refresh = refresh_func

    def _make_refresh_func(self) -> Callable:
        """Create a refresh function based on time_to_live."""
        time_to_live = self.time_to_live

        def should_refresh(cache_key: str, url: str) -> bool:
            """Check if cached data is stale based on time_to_live."""
            # Determine filepath
            if isinstance(self.cache, str):
                expanded_cache = os.path.expanduser(self.cache)
                filepath = os.path.join(expanded_cache, cache_key)
            else:
                # For MutableMapping with rootdir
                if hasattr(self.cache, 'rootdir'):
                    filepath = os.path.join(self.cache.rootdir, cache_key)
                else:
                    # Can't determine age for non-file-based caches
                    return False

            if not os.path.exists(filepath):
                return False  # File doesn't exist, so it's not a refresh situation

            age = time.time() - os.stat(filepath).st_mtime
            return age > time_to_live

        return should_refresh

    def __getitem__(self, url: str) -> Union[Contents, str]:
        """Get contents for URL with refresh logic and error handling."""
        url = url.strip()

        # Check if we need to refresh
        cache_key = self.url_to_cache_key(url)
        should_refresh = (
            self.refresh(cache_key, url) if callable(self.refresh) else self.refresh
        )

        if should_refresh and url in self:
            # Data exists but is stale - try to refresh, handle errors based on on_error setting
            try:
                # Use graze() function with refresh=True
                if self.return_filepaths:
                    return graze(
                        url,
                        cache=self.cache,
                        cache_key=cache_key,
                        source=self.source,
                        key_ingress=self.key_ingress,
                        refresh=True,
                        return_key=True,
                    )
                else:
                    return graze(
                        url,
                        cache=self.cache,
                        cache_key=cache_key,
                        source=self.source,
                        key_ingress=self.key_ingress,
                        refresh=True,
                    )
            except Exception as e:
                # Handle error based on on_error setting
                filepath = self.filepath_of(url)
                if os.path.exists(filepath):
                    age = time.time() - os.stat(filepath).st_mtime
                else:
                    age = None

                if self.on_error == "raise":
                    raise
                elif (
                    self.on_error == "warn" or self.on_error == "warn_and_return_local"
                ):
                    if age is not None:
                        warn(
                            f"There was an error getting a fresh copy of {url}, "
                            f"so I'll give you a copy that's {age:.1f} seconds old. "
                            f"The error was: {e}"
                        )
                    else:
                        warn(f"There was an error getting {url}: {e}")

                # For 'ignore' and after warning, return stale data directly
                # Read the file directly without triggering download
                if self.return_filepaths:
                    return filepath
                else:
                    with open(filepath, 'rb') as f:
                        return f.read()

        # Get data normally (from cache or download)
        return super().__getitem__(url)


def graze(
    url: str,
    cache: Optional[Union[str, MutableMapping]] = None,
    *,
    cache_key: Optional[Union[str, Callable]] = None,
    source: Union[Callable, Gettable] = None,
    key_ingress: Callable | None = None,
    refresh: Union[bool, Callable] = False,
    max_age: int | float | None = None,
    return_key: bool = False,
    # Deprecated parameters (kept for backwards compatibility)
    rootdir: Optional[str] = None,
    return_filepaths: Optional[bool] = None,
):
    """Get the contents of the url (persisting the results in a local file or cache,
    for next time you'll ask for it)

    :param url: The url to download from
    :param cache: Where to store the contents. Can be:
        - None: use DFLT_GRAZE_DIR as folder path (unless cache_key is full filepath)
        - str: folder path for file-based caching
        - MutableMapping: custom cache object (e.g., Files, dict)
    :param cache_key: The key to use in the cache. Can be:
        - None: auto-generate using url_to_localpath
        - str: explicit cache key (or full filepath if starts with / or ~)
        - Callable: function to generate cache key from url
    :param source: Where to get the contents from if not cached. Can be:
        - None: use default Internet() instance
        - Callable: function that takes url and returns contents
        - Gettable: object with __getitem__ method
    :param key_ingress: Function to call on the url before downloading.
        Typically used to notify user that download is happening.
    :param refresh: Whether to re-download even if cached. Can be:
        - bool: True to always refresh, False to use cache if available
        - Callable: function(cache_key, url) -> bool to decide dynamically
    :param max_age: If not None, number of seconds cached data is considered fresh.
        If cached data is older, it will be re-downloaded. Cannot be used with refresh.
    :param return_key: If True, return the cache_key instead of contents.
    :param rootdir: (DEPRECATED) Use 'cache' instead. Folder path for caching.
    :param return_filepaths: (DEPRECATED) Use 'return_key' instead.

    Examples:

    >>> # Basic usage - caches to default directory
    >>> content = graze('http://example.com/data.json')  # doctest: +SKIP

    >>> # Cache to specific folder
    >>> content = graze('http://example.com/data.json', cache='~/my_cache')  # doctest: +SKIP

    >>> # Cache to specific file (cache defaults to None automatically)
    >>> content = graze('http://example.com/data.json', cache_key='~/data/my_data.json')  # doctest: +SKIP

    >>> # Use custom cache object
    >>> from dol import Files
    >>> my_cache = Files('~/cache')
    >>> content = graze('http://example.com/data.json', cache=my_cache, cache_key='data.json')  # doctest: +SKIP

    >>> # Force refresh
    >>> content = graze('http://example.com/data.json', refresh=True)  # doctest: +SKIP

    >>> # Conditional refresh based on age
    >>> content = graze('http://example.com/data.json', max_age=3600)  # doctest: +SKIP
    """
    # Handle deprecated parameters
    if return_filepaths is not None:
        if return_key:
            raise ValueError("Cannot specify both 'return_key' and 'return_filepaths'")
        return_key = return_filepaths

    # Handle max_age and refresh conflict
    if max_age is not None and refresh != False:
        if callable(refresh) or refresh is True:
            raise ValueError(
                "Cannot specify both 'max_age' and 'refresh'. "
                "Use either max_age for time-based refresh, or refresh for custom logic."
            )

    # Convert max_age to refresh function if provided
    if max_age is not None:
        refresh = _max_age_to_refresh_func(max_age)

    # Check for rootdir/cache conflict FIRST (before any assignments)
    if rootdir is not None and cache is not None:
        raise ValueError(
            "Cannot specify both 'rootdir' and 'cache'. "
            "'rootdir' is deprecated; use 'cache' instead."
        )

    # Resolve cache_key first to know if it's a full filepath
    if cache_key is None:
        resolved_cache_key = url_to_localpath(url)
        is_explicit_filepath = False
    elif callable(cache_key):
        resolved_cache_key = cache_key(url)
        is_explicit_filepath = _is_full_filepath(resolved_cache_key)
    else:
        resolved_cache_key = cache_key
        is_explicit_filepath = _is_full_filepath(resolved_cache_key)

    # Handle backwards compatibility and defaults
    # Only set cache to default if not using explicit filepath
    if cache is None and rootdir is None and not is_explicit_filepath:
        cache = DFLT_GRAZE_DIR
    elif cache is None and rootdir is not None:
        cache = rootdir

    # Check for explicit filepath conflict (after cache may have been set to default)
    if is_explicit_filepath and cache is not None:
        raise ValueError(
            f"cache_key appears to be a full filepath ({resolved_cache_key}), "
            f"but 'cache' was also provided ({cache}). This is ambiguous. "
            f"Either provide cache_key as a full filepath with cache=None, "
            f"or provide both cache and a relative cache_key."
        )

    # Set source default
    if source is None:
        source = Internet()

    # Convert callable source to Gettable if needed
    if callable(source) and not hasattr(source, '__getitem__'):
        # Wrap callable in a simple class with __getitem__
        class _CallableWrapper:
            def __init__(self, func):
                self.func = func

            def __getitem__(self, key):
                return self.func(key)

        source = _CallableWrapper(source)

    # Determine if we should refresh
    should_download = _should_refresh(
        refresh, cache, resolved_cache_key, url, is_explicit_filepath
    )

    # Try to get from cache if not refreshing
    if not should_download and _cache_contains(
        cache, resolved_cache_key, is_explicit_filepath
    ):
        contents = _cache_get(cache, resolved_cache_key, is_explicit_filepath)
        if contents is not None:
            if return_key:
                if is_explicit_filepath:
                    return os.path.expanduser(resolved_cache_key)
                elif isinstance(cache, str):
                    return os.path.join(os.path.expanduser(cache), resolved_cache_key)
                else:
                    return resolved_cache_key
            return contents

    # Download fresh content
    if key_ingress is not None:
        url = key_ingress(url)

    contents = source[url]

    # Cache the contents
    _cache_set(cache, resolved_cache_key, contents, is_explicit_filepath)

    if return_key:
        if is_explicit_filepath:
            return os.path.expanduser(resolved_cache_key)
        elif isinstance(cache, str):
            return os.path.join(os.path.expanduser(cache), resolved_cache_key)
        else:
            return resolved_cache_key

    return contents


graze.key_ingress_print_downloading_message = key_egress_print_downloading_message
graze.key_ingress_print_downloading_message_with_size = (
    key_egress_print_downloading_message_with_size
)


def url_to_filepath(url: str, rootdir: str = DFLT_GRAZE_DIR, *, download=None):
    """Get the file path for the url.

    :param rootdir: Where to store the contents locally.
    :param download: Controls when to download the file.
        If None (default), will download only if "necessary"

    >>> filepath = url_to_filepath(url_of_resource) # doctest: +SKIP

    Use case:

    Sometimes you need to specify a filepath as a resource for some python object.
    For example, some font definition file, or configuration file, or such.
    You can provide the file for the user, or can tell them where they can find
    such a file if needed... or you can use the following for the best of both worlds.

    >>> filepath = url_to_filepath(url_of_resource, download=None) # doctest: +SKIP

    If you want to download the file whether it's there or not, use:

    >>> filepath = url_to_filepath(url_of_resource, download=True) # doctest: +SKIP

    """
    g = Graze(rootdir)
    filepath = g.filepath_of(url)  # gives us the target filepath via string formatting

    if download is True:
        b = url_to_contents(url)  # download it
        with open(filepath, "wb") as f:  # write it
            f.write(b)
    elif download is None:
        filepath = g.filepath_of_url_downloading_if_necessary(url)
    # else: download is False, or anything else, we won't download

    return filepath


# # TODO: Check this out. Is not correct/finished. MakeMissingDirsStoreMixin concernt
# #  should be handled differently (search dol for the right tool)
# def _mk_special_local_graze(local_to_url, url_to_localpath):
#     @add_ipython_key_completions
#     @wrap_kvs(
#         key_of_id=local_to_url, id_of_key=url_to_localpath,
#     )
#     class _LocalGrazed(MakeMissingDirsStoreMixin, Files):
#         def __init__(self, rootdir=DFLT_GRAZE_DIR):
#             handle_missing_dir(rootdir)
#             super().__init__(path_format=ensure_slash_suffix(rootdir))

#     return _LocalGrazed


# Old Graze, used mk_sourced_store
# from py2store.caching import mk_sourced_store
# _Graze = mk_sourced_store(
#     store=LocalGrazed,
#     source=Internet(),
#     return_source_data=True,
#     __name__='_Graze',
#     __module__=__name__
# )

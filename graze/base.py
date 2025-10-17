"""Base functionality"""

from typing import Optional, Union, Any
from collections.abc import Callable
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
class Graze(LocalGrazed):
    """A data access object that will get data from the internet if it's not
    already stored locally.

    The interface of ``Graze`` instances is a ``typing.Mapping`` (i.e. ``dict``-like).
    When you list (or iterate over) keys, you'll get the urls
    whose contents are stored locally.
    When you get a value, you'll get the contents of the url (in bytes).
    ``Graze`` will first look if the contents are stored locally, and return that,
    if not it will get the contents from the internet and store it locally,
    then return those bytes.
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
        super().__init__(rootdir)
        self.source = source
        self.rootdir = rootdir
        if key_ingress is True:
            key_ingress = key_egress_print_downloading_message
        self.key_ingress = key_ingress
        self.return_filepaths = return_filepaths

    # def __getitem__(self, k):
    #     if not super().__contains__(k):
    #         return self.filepath_of(k)
    #     return self.filepath_of(k)

    #     path = self.filepath_of(k)  # get the target filepath
    #     v = super().__getitem__(k)  # get the contents from the target filepath
    #     if self.return_filepaths:

    # TODO: Could be more RAM-efficient by not systematically loading the whole file
    #  in memory when it's not necessary.
    def __missing__(self, k):
        if self.key_ingress:
            k = self.key_ingress(k)

        path = self.filepath_of(k)  # get the target filepath
        self.source.download_to_file(k, file=path)  # download the contents to target
        if self.return_filepaths:
            return path  # if return_path, return the path
        else:
            return self[k]  # if not, retrieve contents from file and return them

        # PREVIOUS WAY (using stores -- only return_path=False case
        # # if you didn't have it "locally", ask src for it
        # v = self.source[k]  # ... get it from _src,
        # self[k] = v  # ... store it in self
        # return v  # ... and return it.

    filepath_of = partialmethod(inner_most_key)
    filepath_of.__doc__ = (
        "Get the filepath of where graze stored (or would store) "
        "the contents for a url locally"
    )

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
        super().__init__(
            rootdir,
            source=source,
            key_ingress=key_ingress,
            return_filepaths=return_filepaths,
        )
        self.time_to_live = time_to_live
        self.on_error = on_error

    def __getitem__(self, k):
        k = k.strip()
        v = None
        if k in self:
            # TODO: Use info store that is not necessarily a local files sys?
            filepath = inner_most_key(self, k)
            age = (
                time.time() - os.stat(filepath).st_mtime
            )  # Note: local file sys cache is assumed here!
            if age > self.time_to_live:
                # Need to refresh the data...
                try:
                    # TODO: perhaps do this with super()
                    v = Internet()[k]
                    with open(filepath, "wb") as f:
                        f.write(v)  # replace existing
                except Exception as e:
                    if self.on_error == "warn_and_return_local":
                        warn(
                            "There was an error getting a fresh copy of {k}, "
                            f"so I'll give you a copy that's {age} seconds old."
                        )
                    elif self.on_error == "raise":
                        raise
                    elif self.on_error == "warn":
                        warn(
                            f"There was an error getting a fresh copy of {k}, "
                            f"so I'll give you a copy that's {age} seconds old. "
                            f"The error was {e}"
                        )
        if v is None:
            v = super().__getitem__(k)  # retrieve the data normally
        return v


def graze(
    url: str,
    rootdir: str = DFLT_GRAZE_DIR,
    source=Internet(),
    *,
    key_ingress: Callable | None = None,
    max_age: int | float | None = None,
    return_filepaths: bool = False,
):
    """Get the contents of the url (persisting the results in a local file,
    for next time you'll ask for it)

    :param rootdir: Where to store the contents locally.
    :param source: Where to get the contents from if they're not already stored
        locally. By default, it's an ``Internet`` instance, but can be a custom
        object that has a ``__getitem__`` method that takes a url and returns
        its contents.
    :param key_ingress: A function to call on the key before getting the contents from
        ``source``. Typically, this is used to notify the user that the contents
        are being downloaded. For example, you could use
        ``key_ingress="The contents of {} are being downloaded".format``.
    :param max_age: If not None, should be a number specifying the number of
    seconds a the cached data is considered "fresh". If the cached data is older
    than this, then it will be re-downloaded from the source.
    :param on_error: What to do if there's an error when fetching the new data.
        'raise' raise an error (but keep the cached data)
        'warn' warn the user of the stale data (but return anyway)
        'ignore' ignore the error, and return the stale data
    """
    _kwargs = dict(
        rootdir=rootdir,
        source=source,
        key_ingress=key_ingress,
        return_filepaths=return_filepaths,
    )
    if max_age is None:
        g = Graze(**_kwargs)
    else:
        g = GrazeWithDataRefresh(**_kwargs)
    return g[url]


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

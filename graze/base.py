"""Base functionality"""

from typing import Optional, Callable, Union
import os
import time
from warnings import warn
from operator import attrgetter
from functools import partialmethod, partial

import requests

from py2store.dig import inner_most_key

# from py2store.persisters.local_files import ensure_slash_suffix
from dol.filesys import ensure_slash_suffix

# from py2store import add_ipython_key_completions, wrap_kvs, LocalBinaryStore
from dol import add_ipython_key_completions, wrap_kvs, Files

# from py2store.stores.local_store import AutoMkDirsOnSetitemMixin
from dol import MakeMissingDirsStoreMixin

from graze.util import handle_missing_dir, is_dropbox_url, bytes_from_dropbox

# TODO: handle configuration and existence of root
pjoin = os.path.join
psep = os.path.sep

URL = str
DFLT_GRAZE_DIR = os.path.expanduser('~/graze')


SUBDIR_SUFFIX = '_f'
SUBDIR_SUFFIX_IDX = -len(SUBDIR_SUFFIX)


def _url_to_localpath(url: str) -> str:
    """
    >>> _url_to_localpath('http://www.example.com/subdir1/subdir2/file.txt')
    'http/www.example.com_f/subdir1_f/subdir2_f/file.txt'
    >>> _url_to_localpath('https://www.example.com/subdir1/subdir2/file.txt/')
    'https/www.example.com_f/subdir1_f/subdir2_f/file.txt_f/'
    >>> _url_to_localpath('www.example.com/subdir1/subdir2/file.txt')
    'www.example.com/subdir1_f/subdir2_f/file.txt'
    """
    path = url.replace('https://', 'https/').replace('http://', 'http/')
    path_subdirs = path.split(psep)
    path_subdirs[1:-1] = [x + '_f' for x in path_subdirs[1:-1]]
    return pjoin(*path_subdirs)


def _localpath_to_url(path: str) -> str:
    """
    >>> _localpath_to_url('http/www.example.com_f/subdir1_f/subdir2_f/file.txt')
    'http://www.example.com/subdir1/subdir2/file.txt'
    >>> _localpath_to_url('https://www.example.com_f/subdir1_f/subdir2_f/file.txt_f/')
    'https:/www.example.com/subdir1/subdir2/file.txt/'
    >>> _localpath_to_url('www.example.com/subdir1_f/subdir2_f/file.txt')
    'www.example.com/subdir1/subdir2/file.txt'
    """
    path_subdirs = path.split(psep)
    path_subdirs[1:-1] = [x[:SUBDIR_SUFFIX_IDX] for x in path_subdirs[1:-1]]
    url = pjoin(*path_subdirs)
    return url.replace('https/', 'https://').replace('http/', 'http://')


# CONTENT_FILENAME = 'grazed'
FOLDER_SUFFIX = '_f'
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


class LocalFiles(MakeMissingDirsStoreMixin, Files):
    """Store to read/write/delete local files, creating directories on write."""

    def __init__(self, rootdir=DFLT_GRAZE_DIR):
        handle_missing_dir(rootdir)
        super().__init__(ensure_slash_suffix(rootdir))


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=_localpath_to_url, id_of_key=_url_to_localpath,
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
    url: URL, response_func=_dflt_selenium_response_func, browser='Chrome'
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
            'Not meant to be instantiated: Just to hold url_to_contents functions'
        )

    @staticmethod
    def requests_get(url: URL, response_func=attrgetter('content'), **request_kwargs):
        resp = requests.request('get', url=url, **request_kwargs)
        if resp.status_code == 200:
            return response_func(resp)
        else:
            raise RequestFailure(
                f'Response code was {resp.status_code}.\n'
                f'The first 500 characters of the content were: {resp.content}'
            )

    selenium_chrome = staticmethod(partial(selenium_url_to_contents, browser='Chrome'))
    selenium_safari = staticmethod(partial(selenium_url_to_contents, browser='Safari'))
    selenium_opera = staticmethod(partial(selenium_url_to_contents, browser='Opera'))
    selenium_firefox = staticmethod(
        partial(selenium_url_to_contents, browser='Firefox')
    )


DFLT_URL_TO_CONTENT = url_to_contents.requests_get


class Internet:
    def __init__(self, url_to_contents=DFLT_URL_TO_CONTENT):
        """From the url, get content off the internet.

        :param url_to_contents: The function that gets you the contents from the url
        """
        self.url_to_contents = url_to_contents

    # TODO: implement the key-specific getitem mapping externally to make it open-closed
    def __getitem__(self, k):
        if k.endswith('/'):
            # because it shouldn't matter as url (?) and having it leads to dirs (not
            # files) being created:
            k = k[:-1]

        if is_dropbox_url(k):
            return bytes_from_dropbox(k)
        else:
            return self._get_contents_of_url(k)

    def _get_contents_of_url(self, url):
        try:
            return self.url_to_contents(url)
        except RequestFailure as e:
            raise KeyError(e.args[0])


# TODO: Use reususable caching decorator?
# TODO: Not seeing the right signature, but the LocalGrazed one!
class Graze(LocalGrazed):
    def __init__(self, rootdir=DFLT_GRAZE_DIR, source=Internet()):
        super().__init__(rootdir)
        self.source = source
        self.rootdir = rootdir

    def __missing__(self, k):
        # if you didn't have it "locally", ask src for it
        v = self.source[k]  # ... get it from _src,
        self[k] = v  # ... store it in self
        return v  # ... and return it.

    filepath_of = partialmethod(inner_most_key)
    filepath_of.__doc__ = (
        'Get the filepath of where graze stored (or would store) '
        'the contents for a url locally'
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
        return (Graze, (), {'rootdir': self.rootdir, 'source': self.source})


# TODO: The following is to cope with https://github.com/i2mint/dol/issues/6
#  --> Remove when resolved
from inspect import signature

Graze.__signature__ = signature(Graze.__init__)


A_WEEK_IN_SECONDS = 7 * 24 * 60 * 60  # one week


# TODO: Would be nicer to solve this with a reusable ttl caching decorator!
class GrazeWithDataRefresh(Graze):
    def __init__(
        self,
        time_to_live: Union[int, float] = A_WEEK_IN_SECONDS,
        on_error: str = 'warn',
    ):
        """Like Graze, but where you can specify a time_to_live "freshness threshold" to trigger the re-download of data

        :param time_to_live: In seconds.
        :param on_error: What to do if there's an error when fetching the new data.
            'raise' raise an error (but keep the cached data)
            'warn' warn the user of the stale data (but return anyway)
            'ignore' ignore the error, and return the stale data
        """
        super().__init__()
        self.time_to_live = time_to_live
        self.on_error = on_error

    def __getitem__(self, k):
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
                    with open(filepath, 'wb') as f:
                        f.write(v)  # replace existing
                except Exception as e:
                    if self.on_error == 'raise':
                        raise
                    elif self.on_error == 'warn':
                        warn(
                            f'There was an error getting a fresh copy of {k}, '
                            f"so I'll give you a copy that's {age} seconds old. "
                            f'The error was {e}'
                        )
        if v is None:
            v = super().__getitem__(k)  # retrieve the data normally
        return v


def graze(
    url: str,
    rootdir: str = DFLT_GRAZE_DIR,
    source=Internet(),
    max_age: Optional[Union[int, float]] = None,
):
    """Get the contents of the url (persisting the results in a local file, for next time you'll ask for it)"""
    if max_age is None:
        return Graze(rootdir=rootdir, source=source)[url]
    else:
        return GrazeWithDataRefresh(time_to_live=max_age)[url]


def url_to_filepath(url: str, rootdir: str = DFLT_GRAZE_DIR):
    """Get the file path for the url, downloading contents before hand if necessary.

    Use case:

    Sometimes you need to specify a filepath as a resource for some python object.
    For example, some font definition file, or configuration file, or such.
    You can provide the file for the user, or can tell them where they can find
    such a file if needed... or you can use `url_to_filepath` for the
    best of both worlds.

    It works as such:

    >>> filepath = url_to_filepath(url_of_resource) # doctest: +SKIP

    """
    return Graze(rootdir).filepath_of_url_downloading_if_necessary(url)


def _mk_special_local_graze(local_to_url, url_to_localpath):
    @add_ipython_key_completions
    @wrap_kvs(
        key_of_id=local_to_url, id_of_key=url_to_localpath,
    )
    class _LocalGrazed(MakeMissingDirsStoreMixin, Files):
        def __init__(self, rootdir=DFLT_GRAZE_DIR):
            handle_missing_dir(rootdir)
            super().__init__(path_format=ensure_slash_suffix(rootdir))

    return _LocalGrazed


# Old Graze, used mk_sourced_store
# from py2store.caching import mk_sourced_store
# _Graze = mk_sourced_store(
#     store=LocalGrazed,
#     source=Internet(),
#     return_source_data=True,
#     __name__='_Graze',
#     __module__=__name__
# )

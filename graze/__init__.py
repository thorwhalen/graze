import time
import os
from warnings import warn
import requests
from typing import Union, Optional

from py2store import LocalBinaryStore
from py2store.persisters.local_files import ensure_slash_suffix
from py2store.caching import mk_sourced_store
from py2store.stores.local_store import AutoMkDirsOnSetitemMixin, LocalJsonStore
from py2store.trans import add_ipython_key_completions, wrap_kvs
from py2store.dig import inner_most_key

# TODO: handle configuration and existence of root
DFLT_GRAZE_DIR = os.path.expanduser('~/graze')


def clog(condition, *args):
    if condition:
        print(*args)


def handle_missing_dir(dirpath, prefix_msg='', ask_first=True, verbose=True):
    if not os.path.isdir(dirpath):
        if ask_first:
            clog(verbose, prefix_msg)
            clog(verbose, f"This directory doesn't exist: {dirpath}")
            answer = input("Should I make that directory for you? ([Y]/n)?") or 'Y'
            if next(iter(answer.strip().lower()), None) != 'y':
                return
        clog(verbose, f"Making {dirpath}...")
        os.mkdir(dirpath)


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=lambda _id: _id.replace('https/', 'https://').replace('http/', 'http://'),
    id_of_key=lambda k: k.replace('https://', 'https/').replace('http://', 'http/')
)
class LocalGrazed(AutoMkDirsOnSetitemMixin, LocalBinaryStore):
    def __init__(self, rootdir=DFLT_GRAZE_DIR):
        handle_missing_dir(rootdir)
        super().__init__(path_format=ensure_slash_suffix(rootdir))


class Internet:
    def __getitem__(self, k):
        if k.endswith('/'):
            k = k[:-1]  # because it shouldn't matter as url (?) and having it leads to dirs (not files) being created
        resp = requests.get(k)
        if resp.status_code == 200:
            return resp.content
        else:
            raise KeyError(f"Response code was {resp.status_code}")


Graze = mk_sourced_store(
    store=LocalGrazed,
    source=Internet,
    return_source_data=True,
    __name__='Graze',
    __module__=__name__
)

A_WEEK_IN_SECONDS = 7 * 24 * 60 * 60  # one week


class GrazeWithDataRefresh(Graze):
    def __init__(self,
                 time_to_live: Union[int, float] = A_WEEK_IN_SECONDS,
                 on_error: str = 'warn'):
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
            age = (time.time() - os.stat(filepath).st_mtime)  # Note: local file sys cache is assumed here!
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
                        warn(f"There was an error getting a fresh copy of {k}, "
                             f"so I'll give you a copy that's {age} seconds old. "
                             f"The error was {e}")
        if v is None:
            v = super().__getitem__(k)  # retrieve the data normally
        return v


def graze(url: str,
          max_age: Optional[Union[int, float]] = None):
    """Get the contents of the url (persisting the results in a local file, for next time you'll ask for it)"""
    if max_age is None:
        return Graze()[url]
    else:
        return GrazeWithDataRefresh(time_to_live=max_age)[url]

from typing import Optional, Callable, Union
import os
import time
from warnings import warn
from operator import attrgetter
from functools import partialmethod

import requests

from py2store.dig import inner_most_key
from py2store.persisters.local_files import ensure_slash_suffix
from py2store import add_ipython_key_completions, wrap_kvs, LocalBinaryStore
from py2store.stores.local_store import AutoMkDirsOnSetitemMixin

from graze.util import handle_missing_dir, is_dropbox_url, bytes_from_dropbox

# TODO: handle configuration and existence of root

DFLT_GRAZE_DIR = os.path.expanduser("~/graze")


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=lambda _id: _id.replace("https/", "https://").replace("http/", "http://"),
    id_of_key=lambda k: k.replace("https://", "https/").replace("http://", "http/"),
)
class LocalGrazed(AutoMkDirsOnSetitemMixin, LocalBinaryStore):
    def __init__(self, rootdir=DFLT_GRAZE_DIR):
        handle_missing_dir(rootdir)
        super().__init__(path_format=ensure_slash_suffix(rootdir))


class Internet:
    def __init__(
        self,
        method: str = "get",
        response_func: Callable = attrgetter("content"),
        **request_kwargs,
    ):
        self.method = method
        self.request_kwargs = request_kwargs
        self.response_func = response_func

    # TODO: implement the key-specific getitem mapping externally to make it open-closed
    def __getitem__(self, k):
        if k.endswith("/"):
            k = k[
                :-1
            ]  # because it shouldn't matter as url (?) and having it leads to dirs (not files) being created
        if is_dropbox_url(k):
            return bytes_from_dropbox(k)
        else:
            return self._get_contents_of_url(k)

    def _get_contents_of_url(self, url):
        resp = requests.request(method=self.method, url=url, **self.request_kwargs)
        if resp.status_code == 200:
            return self.response_func(resp)
        else:
            raise KeyError(f"Response code was {resp.status_code}")


# TODO: Use reususable caching decorator?
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
    filepath_of.__doc__ = "Get the filepath of where graze stored (or would store) the contents for a url locally"

    def __reduce__(self):
        return (Graze, (), {"rootdir": self.rootdir, "source": self.source})


A_WEEK_IN_SECONDS = 7 * 24 * 60 * 60  # one week


# TODO: Would be nicer to solve this with a reusable ttl caching decorator!
class GrazeWithDataRefresh(Graze):
    def __init__(
        self, time_to_live: Union[int, float] = A_WEEK_IN_SECONDS, on_error: str = "warn"
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
                    with open(filepath, "wb") as f:
                        f.write(v)  # replace existing
                except Exception as e:
                    if self.on_error == "raise":
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
    max_age: Optional[Union[int, float]] = None,
):
    """Get the contents of the url (persisting the results in a local file, for next time you'll ask for it)"""
    if max_age is None:
        return Graze(rootdir=rootdir, source=source)[url]
    else:
        return GrazeWithDataRefresh(time_to_live=max_age)[url]


# Old Graze, used mk_sourced_store
# from py2store.caching import mk_sourced_store
# _Graze = mk_sourced_store(
#     store=LocalGrazed,
#     source=Internet(),
#     return_source_data=True,
#     __name__='_Graze',
#     __module__=__name__
# )

from py2store import QuickBinaryStore, LocalBinaryStore
# from py2store.slib.s_zipfile import ZipFilesReaderAndBytesWriter
from py2store.persisters.local_files import ensure_slash_suffix
from py2store.caching import mk_sourced_store
# from py2store.filesys import mk_relative_path_store, LocalFileDeleteMixin
from py2store.stores.local_store import AutoMkDirsOnSetitemMixin, LocalJsonStore
from py2store.trans import add_ipython_key_completions, wrap_kvs
# from py2store.key_mappers.paths import str_template_key_trans
# from py2store.appendable import appendable
import os

import requests

DFLT_GRAZE_DIR = os.path.expanduser('~/graze')

#
# @mk_relative_path_store(prefix_attr='rootdir')
# class RelZipFiles(ZipFilesReaderAndBytesWriter, LocalFileDeleteMixin):
#     pass


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
        resp = requests.get(k)
        if resp.status_code == 200:
            return resp.content
        else:
            raise KeyError(f"Response code was {resp.status_code}")


# kaggle_remote_datasets_bytes = kv_wrap(remote_key_trans)(KaggleBytesDatasetReader)()

Graze = mk_sourced_store(
    store=LocalGrazed,
    source=Internet,
    return_source_data=True,
    __name__='Graze',
    __module__=__name__
)


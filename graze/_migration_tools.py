"""
Migration tools
"""

import os
from graze.base import (
    pjoin,
    wrap_kvs,
    LocalFiles,
    psep,
    add_ipython_key_completions,
    DFLT_GRAZE_DIR,
    Files,
    LocalGrazed,
)


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=lambda _id: _id.replace("https/", "https://").replace("http/", "http://"),
    id_of_key=lambda k: k.replace("https://", "https/").replace("http://", "http/"),
)
class LocalGrazedVersion01(LocalFiles):
    """LocalFiles using url as keys"""


class _KeyMapVersion02:
    CONTENT_FILENAME = "grazed"
    CONTENT_PATH_SUFFIX = psep + CONTENT_FILENAME
    CONTENT_FILENAME_INDEX = -len(CONTENT_PATH_SUFFIX)

    def url_to_localpath(url: str) -> str:
        path = url.replace("https://", "https/").replace("http://", "http/")
        return pjoin(path, _KeyMapVersion02.CONTENT_FILENAME)

    def localpath_to_url(path: str) -> str:
        assert path.endswith(
            psep + _KeyMapVersion02.CONTENT_FILENAME
        ), f"Not a valid key: {path}"
        # remove the /CONTENT_FILENAME part
        path = path[: _KeyMapVersion02.CONTENT_FILENAME_INDEX]
        return path.replace("https/", "https://").replace("http/", "http://")


@add_ipython_key_completions
@wrap_kvs(
    key_of_id=_KeyMapVersion02.localpath_to_url,
    id_of_key=_KeyMapVersion02.url_to_localpath,
)
class LocalGrazedVersion02(LocalFiles):
    """LocalFiles using url as keys"""


def _middle_folders(path):
    return path.split(psep)[1:-1]


def is_a_version_3_graze_folder(rootdir):
    from itertools import chain
    from dol import FilesReader

    return all(
        map(
            lambda x: x.endswith("_f"),
            chain.from_iterable(map(_middle_folders, FilesReader(rootdir))),
        )
    )


def _get_old_grazer(src_root=DFLT_GRAZE_DIR, old_grazer=None):
    if old_grazer is None:
        if all(path.endswith("grazed") for path in Files(src_root)):
            return LocalGrazedVersion02
        elif not is_a_version_3_graze_folder(src_root):
            return LocalGrazedVersion01
        else:
            raise RuntimeError(
                f"This folder seems to already using the newest version (3) of "
                f"url_to_filepath: {src_root}"
            )

    if isinstance(old_grazer, int):
        if old_grazer == 1:
            return LocalGrazedVersion01
        elif old_grazer == 2:
            return LocalGrazedVersion02
        else:
            raise ValueError(f"{old_grazer=}")


def _migrate_versions(src_root=DFLT_GRAZE_DIR, old_grazer=None):
    src = LocalFiles(src_root)
    old_grazer = _get_old_grazer(src_root, old_grazer)

    bak_root = src_root + "_bak"
    bak = LocalFiles(bak_root)

    print(f"backing up files from {src_root} to {bak_root}")
    bak.update(src)
    # for k, v in src.items():
    #     try:
    #         bak[k] = v
    #     except Exception as e:
    #         print(f'{k}: {e}')

    print(f"deleting and recreating original source directory: {src_root}")
    import shutil

    shutil.rmtree(src_root)
    os.mkdir(src_root)

    print(
        f"Copy backup files of {bak_root} to {src_root} using current url2path mapping"
    )
    new_grazed = LocalGrazed(src_root)
    old_grazed = old_grazer(bak_root)
    new_grazed.update(old_grazed)

    print(
        f"Done -- check if things work, and if they do, delete the backup folder: "
        f"{bak_root}"
    )


def change_files_to_new_url_to_filepath_format(
    src_root=DFLT_GRAZE_DIR, old_grazer=None
):
    """Util function to convert existing local files to new version of
    the url_to_localpath mapping.

    Relevant issue: https://github.com/thorwhalen/graze/issues/1

    """

    return _migrate_versions(src_root, old_grazer)

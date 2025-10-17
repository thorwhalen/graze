"""Utils"""

from typing import Union
from collections.abc import Callable
from functools import partial
import os
import urllib
import re
from io import BytesIO

Filepath = str


def last_element(iterable, *, default=None):
    """
    Returns the last element of an iterable, or a default if the iterable is empty.
    """
    x = default
    for x in iterable:
        pass
    return x


def store_trans_path(store, arg, method):
    f = getattr(store, method, None)
    if f is not None:
        trans_arg = f(arg)
        yield trans_arg
        if hasattr(store, "store"):
            yield from unravel_key(store.store, trans_arg)


unravel_key = partial(store_trans_path, method="_id_of_key")


def inner_most(store, arg, method):
    return last_element(store_trans_path(store, arg, method))


# The only raison d'être of everything above is to define inner_most_key:
# TODO: Write a standalone for inner_most_key? (Came originally from py2store.dig)
inner_most_key = partial(inner_most, method="_id_of_key")


# --------------------- General ---------------------


def _ensure_dirs_of_file_exists(filepath: str):
    """Recursively ensure all dirs necessary for filepath exist.
    Return filepath (useful for pipelines)"""
    dirpath = os.path.dirname(filepath)
    os.makedirs(dirpath, exist_ok=True)  # TODO: REALLY don't like this here.
    return filepath


def clog(condition: bool, *args, log_func: Callable = print, **kwargs):
    """Conditional log

    >>> clog(False, "logging this")
    >>> clog(True, "logging this")
    logging this

    One common usage is when there's a verbose flag that allows the user to specify
    whether they want to log or not. Instead of having to litter your code with
    `if verbose:` statements you can just do this:

    >>> verbose = True  # say versbose is True
    >>> _clog = clog(verbose)  # makes a clog with a fixed condition
    >>> _clog("logging this")
    logging this

    You can also choose a different log function:

    >>> _clog = clog(True, log_func=lambda x: print(f"hello {x}"))
    >>> _clog("logging this")
    hello logging this

    """
    if not args and not kwargs:
        import functools

        return functools.partial(clog, condition, log_func=log_func)
    if condition:
        return log_func(*args, **kwargs)


def handle_missing_dir(dirpath: str, prefix_msg="", ask_first=True, verbose=True):
    _clog = clog(verbose)
    if dirpath.startswith("~"):
        dirpath = os.path.expanduser(dirpath)
    if not os.path.isdir(dirpath):
        if ask_first:
            _clog(prefix_msg)
            _clog(f"This directory doesn't exist: {dirpath}")
            answer = input("Should I make that directory for you? ([Y]/n)?") or "Y"
            if next(iter(answer.strip().lower()), None) != "y":
                return
        _clog(f"Making {dirpath}...")
        os.mkdir(dirpath)


def get_content_size(url: str, *, default=None):
    """Get the content size of a url, if available, without downloading the content."""
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request) as response:
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            return int(content_length)
        else:
            return default


# Note: General util
# TODO: Consider moving general util (to lkj?)
def human_readable_bytes(
    num_of_bytes: int,
    *,
    approx_marker="~",
    n_digits=4,
    base=1000,
    units=("B", "KB", "MB", "GB", "TB", "PB"),
):
    """
    Convert a number of bytes into a human-readable format with units.

    Args:
        num_of_bytes (int): The number of bytes.
        approx_marker (str, optional): Marker indicating approximation. Defaults to "~".
        n_digits (int, optional): Number of significant digits in the output. Defaults to 4.
        base (int, optional): Conversion base, 1024 or 1000. Defaults to 1000.
        units (tuple, optional): Units for conversion. Defaults to ('B', 'KB', 'MB', 'GB', 'TB', 'PB').

    Returns:
        str: Human-readable string representing the number of bytes.

    Examples:
    >>> human_readable_bytes(123456)
    '~123.456KB'
    >>> human_readable_bytes(123456789)
    '~123.457MB'

    Using `base=1000` (default) is the International System of Units (SI) standard.
    But base=1024 is a common practice in computing.

    >>> human_readable_bytes(123456789, base=1024)
    '~117.738MB'

    >>> human_readable_bytes(1234567890123)
    '~1.235TB'

    Tip: Use `functools.partial` to customize the function to your needs.

    >>> from functools import partial
    >>> readable = partial(
    ...     human_readable_bytes,
    ...     approx_marker='approximately ',
    ...     units=(' bytes', ' kilobytes')
    ... )
    >>> readable(123456)
    'approximately 123.456 kilobytes'

    Note how the function starts using the scientific notation when it runs out of
    units.

    >>> readable(123456789)
    'approximately 1.235e+08 kilobytes'

    """
    factor = 1
    for unit in units:
        if num_of_bytes < factor * base:
            return f"{approx_marker}{num_of_bytes / factor:.{n_digits-1}f}{unit}"
        factor *= base
    return f"{approx_marker}{num_of_bytes:.{n_digits-1}e}{units[-1]}"


DFLT_USER_AGENT = "Wget/1.16 (linux-gnu)"
DFLT_CHK_SIZE = 1024


def _first_bytes(src, n_bytes=None):
    """Get the first n_bytes of a src, which can be a bytes object or a file path."""
    if isinstance(src, bytes):
        return src[slice(0, n_bytes)]
    elif isinstance(src, str):
        with open(src, "rb") as file:
            return file.read(n_bytes)
    else:  # assume it's a file-like object
        file.read(n_bytes)


def chks_of_url_contents(url, *, chk_size=DFLT_CHK_SIZE, user_agent=DFLT_USER_AGENT):
    """Yield chunks of a url's contents."""
    req = urllib.request.Request(url)
    req.add_header("user-agent", user_agent)
    with urllib.request.urlopen(req) as response:
        while True:
            chk = response.read(chk_size)
            if len(chk) > 0:
                yield chk
            else:
                break


def download_url_contents(
    url, file=None, *, chk_size=DFLT_CHK_SIZE, user_agent=DFLT_USER_AGENT
):
    """
    Download url contents into a `file` object, or return bytes if `file` is None.
    """

    def iter_content_and_copy_to(file):
        for chk in chks_of_url_contents(url, chk_size=chk_size, user_agent=user_agent):
            file.write(chk)

    if file is None:
        # TODO: Might there be a way to avoid the double buffering?
        #      (i.e. avoid the need to copy the bytes from the BytesIO to the file)
        #      (maybe using itertools.chain?)
        #      (maybe by using a memory-mapped file?)
        #      (or maybe by using a file-like object that can be seeked and read from?)
        # from itertools import chain
        # return bytes(chain.from_iterable(chks_of_url_contents(url)))
        with BytesIO() as file:
            iter_content_and_copy_to(file)
            file.seek(0)  # rewind
            return file.read()  # read bytes from the beginning
    elif isinstance(file, str):
        _ensure_dirs_of_file_exists(file)  # TODO: Make optional?
        with open(file, "wb") as _target_file:
            iter_content_and_copy_to(_target_file)
        return file
    else:
        iter_content_and_copy_to(file)
        return file


bytes_of_url_content = partial(download_url_contents, file=None)


# --------------------- Dropbox ---------------------

# Note to the developper: In Dropbox shared links, the query parameter dl controls how
# the link behaves:
# * dl=0: The link opens a preview page for the file on the Dropbox website.
#   It's used when you want to share a viewable link rather than a direct download link.
# * dl=1: The link becomes a direct download link. When someone clicks on this link,
#   the file starts downloading immediately, instead of opening a preview page.
# Changing the value of dl in a Dropbox link is a common way to control the user
# experience when accessing shared files.

drobox_url_re = re.compile(r"https?://www\.dropbox\.com/s/.+\?dl=(0|1)$")


def is_dropbox_url(url: str):
    return bool(drobox_url_re.match(url))


download_from_dropbox = download_url_contents  # backwards compatibility alias
bytes_from_dropbox = bytes_of_url_content  # backwards compatibility alias

# --------------------- Google Drive ---------------------

_google_drive_file_id_patterns = (
    r"drive\.google\.com/file/d/([\w-]+)",  # Standard file URL
    r"drive\.google\.com/uc\?export=download&id=([\w-]+)",  # Direct download link
    r"drive\.google\.com/open\?id=([\w-]+)",  # Open link format
    r"docs\.google\.com/spreadsheets/d/([\w-]+)",  # Google Sheets URL
    r"docs\.google\.com/document/d/([\w-]+)",  # Google Docs URL
    r"docs\.google\.com/presentation/d/([\w-]+)",  # Google Slides URL
    r"docs\.google\.com/forms/d/([\w-]+)",  # Google Forms URL
    r"drive\.google\.com/drive/folders/([\w-]+)",  # Google Drive folder URL
    r"drive\.google\.com/drive/u/\d/folders/([\w-]+)",  # Google Drive folder with user ID
    r"drive\.google\.com/file/d/([\w-]+)",  # Standard file link with variations
    r"drive\.google\.com/file/d/([\w-]+)/view",  # File view URL
    r"drive\.google\.com/file/d/([\w-]+)/edit",  # File edit URL
    r"drive\.google\.com/file/d/([\w-]+)/preview",  # File preview URL
)
_google_drive_file_id_pattern = re.compile("|".join(_google_drive_file_id_patterns))


def _google_drive_id(url: str) -> str:
    match = _google_drive_file_id_pattern.search(url)
    if match:
        # Return the first non-None group found in the match
        return next(g for g in match.groups() if g is not None)
    else:
        msg = "Only FILE Google Drive URLs are supported, "
        msg += "which have the format '...drive.google.com/file/d/{file_id}... "
        msg += f"This url is not supported: {url}"
        raise ValueError(msg)


def is_google_drive_url(url: str) -> bool:
    """
    Checks if the provided URL is a Google Drive URL.

    Args:
        url (str): The URL to check.

    Returns:
        bool: True if the URL is a Google Drive URL, False otherwise.

    >>> is_google_drive_url('https://drive.google.com/file/d/1Ul5mPePKAO11dG98GN/view')
    True
    >>> is_google_drive_url('http://drive.google.com/file/d/1Ul5mPePKAO11dG98GN/view')
    True
    >>> is_google_drive_url('https://example.com/file/d/1Ul5mPePKAO11dG98GN/view')
    False
    """
    try:
        _google_drive_id(url)
        return True
    except ValueError:
        return False


def google_drive_download_url(url):
    """Get the download url from a FILE Google Drive URL.

    Note: File URLs have the format: `...drive.google.com/file/d/{file_id}...`.
    Folder URLs as well as "special format" (google docs, sheets, etc.) URLs are not
    supported.
    """
    file_id = _google_drive_id(url)
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _is_html_doc(src: bytes | Filepath):
    """Check if the src is an html document."""
    html_prefix = b"<!DOCTYPE html>"
    first_bytes = _first_bytes(src, len(html_prefix))
    return first_bytes == html_prefix


def download_from_google_drive(
    url: str,
    file=None,
    *,
    chk_size=DFLT_CHK_SIZE,
    user_agent=DFLT_USER_AGENT,
    skip_virus_scan_confirmation_page=False,
):
    """
    Download a file from a Google Drive URL.
    Will write the downloaded contents bytes to `file`, which can be a local file path
    or file-like object.
    If `file=None`, returns the bytes of the contents of the url.

    Note: File URLs have the format: `...drive.google.com/file/d/{file_id}...`.
    Folder URLs as well as "special format" (google docs, sheets, etc.) URLs are not
    supported.
    """
    _download_kwargs = dict(chk_size=chk_size, user_agent=user_agent)
    download_url = google_drive_download_url(url)
    src = download_url_contents(download_url, file, **_download_kwargs)
    if skip_virus_scan_confirmation_page:
        html_prefix = b"<!DOCTYPE html>"
        first_bytes = _first_bytes(src, len(html_prefix))
        if first_bytes == html_prefix:
            html_content = src.decode("utf-8")
            url_with_token = url_with_virus_scan_confirmation_token(
                download_url, html_content
            )
            src = download_url_contents(url_with_token, file, **_download_kwargs)

    return src


def url_with_virus_scan_confirmation_token(url, page_html):
    # Use regular expressions to find the confirmation token
    confirm_token_match = re.search(r"confirm=([0-9A-Za-z_\-]+)&", page_html)
    if not confirm_token_match:
        raise ValueError(
            "Could not find the confirmation token for the virus scan page of url: "
            f" {url}."
        )

    confirmation_token = confirm_token_match.group(1)

    # Construct the URL with the confirmation token
    return url + "&confirm=" + confirmation_token


# --------------------- Special URLS ---------------------

# Note: Add/edit default special url routes here:
special_url_routes = {
    is_dropbox_url: download_url_contents,
    is_google_drive_url: download_from_google_drive,
}


def add_special_url_route(condition, url_download_func):
    """
    Add a special url route, i.e. a function that downloads a url's contents
    for a specific condition on the url.
    """
    special_url_routes.update({condition: url_download_func})


def is_special_url(url: str):
    """Check if a url is a special url, i.e. if it has a special url route."""
    for _is_special_url in special_url_routes:
        if _is_special_url(url):
            return True
    return False


def download_from_special_url(
    url: str, file=None, chk_size=DFLT_CHK_SIZE, user_agent=DFLT_USER_AGENT
):
    """Download a url's contents, using a special url route."""
    kwargs = dict(chk_size=chk_size, user_agent=user_agent)
    for is_special_url, download_func in special_url_routes.items():
        if is_special_url(url):
            return download_func(url, file, **kwargs)
    raise ValueError(f"Unsupported url: {url}")

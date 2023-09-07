"""Utils"""

import os
import urllib


def clog(condition, *args, log_func=print, **kwargs):
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

    >>> _clog = clog(verbose, log_func=lambda x: f"hello {x}"})
    >>> _clog("logging this")
    hello logging this

    """
    if not args and not kwargs:
        import functools
        return functools.partial(clog, condition)
    if condition:
        print(*args, **kwargs)



def handle_missing_dir(dirpath, prefix_msg="", ask_first=True, verbose=True):
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


DFLT_USER_AGENT = "Wget/1.16 (linux-gnu)"


def is_dropbox_url(url):
    return (
        url.startswith("https://www.dropbox.com")
        or url.startswith("http://www.dropbox.com")
        and (url.endswith("dl=0") or url.endswith("dl=1"))
    )


def download_from_dropbox(url, file, chk_size=1024, user_agent=DFLT_USER_AGENT):
    def iter_content_and_copy_to(file):
        req = urllib.request.Request(url)
        req.add_header("user-agent", user_agent)
        with urllib.request.urlopen(req) as response:
            while True:
                chk = response.read(chk_size)
                if len(chk) > 0:
                    file.write(chk)
                else:
                    break

    if not isinstance(file, str):
        iter_content_and_copy_to(file)
    else:
        with open(file, "wb") as _target_file:
            iter_content_and_copy_to(_target_file)


def bytes_from_dropbox(url, chk_size=1024, user_agent=DFLT_USER_AGENT):
    from io import BytesIO

    with BytesIO() as file:
        download_from_dropbox(url, file, chk_size=chk_size, user_agent=user_agent)
        file.seek(0)
        return file.read()

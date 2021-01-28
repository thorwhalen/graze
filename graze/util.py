import os
import urllib


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


DFLT_USER_AGENT = "Wget/1.16 (linux-gnu)"


def is_dropbox_url(url):
    return (
            url.startswith('https://www.dropbox.com') or url.startswith('http://www.dropbox.com')
            and (url.endswith('dl=0') or url.endswith('dl=1'))
    )


def download_from_dropbox(
        url, file, chk_size=1024, user_agent=DFLT_USER_AGENT
):
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
        download_from_dropbox(
            url, file, chk_size=chk_size, user_agent=user_agent
        )
        file.seek(0)
        return file.read()

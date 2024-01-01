"""Tests for graze """

from graze.util import download_url_contents, download_from_special_url


def test_download_url_contents():
    github_url = (
        'https://raw.githubusercontent.com/thorwhalen/test_repo/main/file_1_level_1'
    )
    b = download_url_contents(github_url)
    assert b == b'Contents of file_1_level_1\n'

    # Note here, the url prefix could bd dl=0 or dl=1
    drobox_url = 'https://www.dropbox.com/scl/fi/2hat8onob5jbafv5qgmbb/text_test.txt?rlkey=9ydsjvbrflolmksd97q55ejla&dl=0'
    bb = download_url_contents(drobox_url)
    assert bb == b'This is some text.'


def test_download_from_special_url():
    # Here, the url given is for a preview page, not the actual file.
    # The download_from_special_url function will make the actual direct download url
    google_drive_url = 'https://drive.google.com/file/d/1DkKI2tAQn34VAWD_mcwwtQzlpMPGIMnb/view?usp=sharing'
    bbb = download_from_special_url(google_drive_url)
    assert bbb == b'This is some text.'

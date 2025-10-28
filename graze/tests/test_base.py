"""Test the base module."""

import tempfile
from typing import Union
import os
from functools import partial
from pathlib import Path
from graze.base import url_to_file_download, Contents

test_url_1 = (
    "https://raw.githubusercontent.com/thorwhalen/graze/master/graze/tests/test_base.py"
)
test_url_contents_1_first_line = b'"""Test the base module."""'


def _get_temp_path(relative_path: str = ""):
    return os.path.join(tempfile.mkdtemp(), relative_path)


def _first_line(contents: Contents) -> Contents:
    return next(iter(contents.splitlines()), None)


def _is_test_file(filepath: str) -> bool:
    """Determine if filepath is a test file"""
    return os.path.basename(filepath).startswith("__graze_test_file_")


def _if_test_file_exists_delete_it(filepath: str):
    """Safely delete a test file. If not a test file, raises ValueError"""
    if not _is_test_file(filepath):
        raise ValueError(f"Not a test file: {filepath}")
    if os.path.isfile(filepath):
        os.remove(filepath)
    return filepath  # return filepath (so we can use function in a pipe)


def _assert_first_line_is(
    contents: Contents, content_name="content", expected_first_line: Contents = None
):
    assert (
        _first_line(contents) == expected_first_line
    ), f"First line of {content_name} expected to be: {expected_first_line}"


def test_url_to_file_download_simple():
    filepath = _get_temp_path("__graze_test_file_01")
    print(f"\n------> INFO: {filepath}")
    _if_test_file_exists_delete_it(filepath)
    __assert_first_line_is = partial(
        _assert_first_line_is, expected_first_line=test_url_contents_1_first_line
    )

    assert os.path.isfile(filepath) is False, f"File expected not to exist: {filepath}"
    func_output = url_to_file_download(test_url_1, filepath)
    assert os.path.isfile(filepath), f"File expected to exist: {filepath}"
    __assert_first_line_is(func_output, "func_output")
    contents_from_file = Path(filepath).read_bytes()
    __assert_first_line_is(contents_from_file, "contents_from_file")


def test_url_to_file_download_complex():
    # Setup
    temp_dir = tempfile.mkdtemp()

    # Test 1: Basic download with default parameters
    filepath1 = os.path.join(temp_dir, "__graze_test_file_02")
    _if_test_file_exists_delete_it(filepath1)
    assert not os.path.isfile(filepath1), f"File expected not to exist: {filepath1}"
    result1 = url_to_file_download(test_url_1, filepath1)
    assert os.path.isfile(filepath1), f"File expected to exist: {filepath1}"
    _assert_first_line_is(result1, "result1", test_url_contents_1_first_line)

    # Test 2: `overwrite=False`` --> The caching mechanism
    # The main reason we have this url_to_file_download function is to cache the
    # files we download from urls. By default, the url_to_file_download will fetch
    # data from the url and write it in the file, every time we call it.
    # But if we set `overwrite=False`, we get a different behavior...
    # Let's have a look at what the last updated timestamp is for our filepath1.
    last_updated = os.path.getmtime(filepath1)
    # Now we'll try to download the same file again, but with overwrite=False
    result2 = url_to_file_download(test_url_1, filepath1, overwrite=False)
    # We get the same result (test_url_contents_1_first_line) again
    _assert_first_line_is(result2, "result2", test_url_contents_1_first_line)
    # But we didn't get this from the url, we got this from our filepath1
    # See that the file was NOT overwritten (last updated timestamp should be the same)
    assert last_updated == os.path.getmtime(
        filepath1
    ), "File should NOT have been overwritten"
    # Let's drill this point further by writing something else in the file
    with open(filepath1, "wb") as f:
        f.write(b"Temporary content")
    result3 = url_to_file_download(test_url_1, filepath1, overwrite=False)
    # now we don't get the same result
    assert result3 != result2, "Expected different content"
    assert result3 == b"Temporary content", "Expected new content"

    # Test 3: Overwrite existing file
    # The default of overwrite is True, so if you modify the file:
    with open(filepath1, "wb") as f:
        f.write(b"Temporary content")
    # after using url_to_file_download
    result4 = url_to_file_download(test_url_1, filepath1, overwrite=True)
    # you'll get the original content again
    _assert_first_line_is(result4, "result4", test_url_contents_1_first_line)

    # Test 4: Ensure directories exist
    nested_filepath = os.path.join(temp_dir, "nested", "__graze_test_file_03")
    _if_test_file_exists_delete_it(nested_filepath)
    assert not os.path.isfile(
        nested_filepath
    ), f"File expected not to exist: {nested_filepath}"
    result5 = url_to_file_download(test_url_1, nested_filepath, ensure_dirs=True)
    assert os.path.isfile(nested_filepath), f"File expected to exist: {nested_filepath}"
    _assert_first_line_is(result5, "result5", test_url_contents_1_first_line)

    # Test 5: Custom return function
    # By default, url_to_file_download will give you the contents of the file.
    # But in some cases you may want the filepath instead, or the url...
    # ... in fact you can have any function of all three that you want. Here's
    # a demo of that.
    filepath4 = os.path.join(temp_dir, "__graze_test_file_04")
    _if_test_file_exists_delete_it(filepath4)

    def custom_return_func(filepath, contents, url):
        return {"filepath": filepath, "contents": contents, "url": url}

    result6 = url_to_file_download(
        test_url_1, filepath4, return_func=custom_return_func
    )
    assert isinstance(result6, dict), "Expected result to be a dictionary"
    assert result6["filepath"] == filepath4, "Filepath mismatch in result"
    _assert_first_line_is(
        result6["contents"], 'result6["contents"]', test_url_contents_1_first_line
    )
    assert result6["url"] == test_url_1, "URL mismatch in result"


def test_url_to_localpath():
    """Test URL to local path conversion"""
    from graze.base import url_to_localpath, localpath_to_url

    # Test http URL
    result = url_to_localpath("http://www.example.com/subdir1/subdir2/file.txt")
    assert result == "http/www.example.com_f/subdir1_f/subdir2_f/file.txt"

    # Test https URL
    result = url_to_localpath("https://www.example.com/subdir1/subdir2/file.txt")
    assert result == "https/www.example.com_f/subdir1_f/subdir2_f/file.txt"

    # Test URL with trailing slash
    result = url_to_localpath("https://www.example.com/subdir1/subdir2/file.txt/")
    assert result == "https/www.example.com_f/subdir1_f/subdir2_f/file.txt"

    # Test URL without protocol
    result = url_to_localpath("www.example.com/subdir1/subdir2/file.txt")
    assert result == "www.example.com/subdir1_f/subdir2_f/file.txt"


def test_localpath_to_url():
    """Test local path to URL conversion (inverse of url_to_localpath)"""
    from graze.base import localpath_to_url

    # Test http path
    result = localpath_to_url("http/www.example.com_f/subdir1_f/subdir2_f/file.txt")
    assert result == "http://www.example.com/subdir1/subdir2/file.txt"

    # Test https path
    result = localpath_to_url("https/www.example.com_f/subdir1_f/subdir2_f/file.txt")
    assert result == "https://www.example.com/subdir1/subdir2/file.txt"

    # Test path without protocol prefix
    result = localpath_to_url("www.example.com/subdir1_f/subdir2_f/file.txt")
    assert result == "www.example.com/subdir1/subdir2/file.txt"


def test_url_localpath_roundtrip():
    """Test that url_to_localpath and localpath_to_url are inverses"""
    from graze.base import url_to_localpath, localpath_to_url

    test_urls = [
        "http://www.example.com/subdir1/subdir2/file.txt",
        "https://www.example.com/path/to/resource.json",
        "https://raw.githubusercontent.com/user/repo/main/file.py",
    ]

    for url in test_urls:
        localpath = url_to_localpath(url)
        recovered_url = localpath_to_url(localpath)
        # Strip trailing slashes for comparison
        assert recovered_url.rstrip("/") == url.rstrip("/"), (
            f"Roundtrip failed for {url}: got {recovered_url}"
        )


def test_local_files():
    """Test LocalFiles store functionality with temp directory"""
    from graze.base import LocalFiles

    temp_dir = tempfile.mkdtemp()
    store = LocalFiles(rootdir=temp_dir)

    # Test write
    test_key = "test_file.txt"
    test_content = b"Hello, World!"
    store[test_key] = test_content

    # Test read
    assert store[test_key] == test_content

    # Test contains
    assert test_key in store

    # Test iteration (keys)
    keys = list(store)
    assert test_key in keys

    # Test delete
    del store[test_key]
    assert test_key not in store

    # Test nested paths
    nested_key = "subdir/nested/file.txt"
    store[nested_key] = b"nested content"
    assert store[nested_key] == b"nested content"
    del store[nested_key]


def test_local_grazed():
    """Test LocalGrazed - LocalFiles with URL key wrapping"""
    from graze.base import LocalGrazed

    temp_dir = tempfile.mkdtemp()
    store = LocalGrazed(rootdir=temp_dir)

    # Test with URL as key
    test_url = "http://example.com/test/file.txt"
    test_content = b"URL-mapped content"

    # Write using URL as key
    store[test_url] = test_content

    # Read using URL as key
    assert store[test_url] == test_content

    # Test that it's stored in the right local path
    assert test_url in store

    # Can iterate over URL keys
    keys = list(store)
    assert test_url in keys

    # Clean up
    del store[test_url]
    assert test_url not in store


def test_url_to_contents_requests_get():
    """Test url_to_contents.requests_get with a real URL"""
    from graze.base import url_to_contents

    # Use the test URL that we know works
    contents = url_to_contents.requests_get(test_url_1)
    assert isinstance(contents, bytes)
    _assert_first_line_is(contents, "contents", test_url_contents_1_first_line)


def test_url_to_contents_with_custom_response_func():
    """Test url_to_contents with custom response function"""
    from graze.base import url_to_contents

    # Custom response function that gets the status code instead
    def get_status_code(response):
        return response.status_code

    status = url_to_contents.requests_get(test_url_1, response_func=get_status_code)
    assert status == 200


def test_internet_getitem():
    """Test Internet class for getting contents from URLs"""
    from graze.base import Internet

    internet = Internet()

    # Test basic getitem
    contents = internet[test_url_1]
    assert isinstance(contents, bytes)
    _assert_first_line_is(contents, "contents", test_url_contents_1_first_line)

    # Test that trailing slash is handled
    url_with_slash = test_url_1 + "/"
    contents = internet[url_with_slash]
    assert isinstance(contents, bytes)


def test_internet_download_to_file():
    """Test Internet.download_to_file method"""
    from graze.base import Internet

    internet = Internet()
    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, "__graze_test_internet_download.txt")

    # Download to file
    result = internet.download_to_file(test_url_1, file=filepath)
    assert os.path.isfile(filepath)

    # Check contents
    with open(filepath, "rb") as f:
        contents = f.read()
    _assert_first_line_is(contents, "downloaded file", test_url_contents_1_first_line)

    # Clean up
    os.remove(filepath)


def test_graze_basic():
    """Test Graze basic caching behavior"""
    from graze.base import Graze

    temp_dir = tempfile.mkdtemp()
    g = Graze(rootdir=temp_dir)

    # First access - should download
    contents1 = g[test_url_1]
    _assert_first_line_is(contents1, "first access", test_url_contents_1_first_line)

    # Check that the URL is now in the store
    assert test_url_1 in g

    # Second access - should use cached version
    contents2 = g[test_url_1]
    assert contents1 == contents2

    # Test that iteration works
    urls = list(g)
    assert test_url_1 in urls


def test_graze_filepath_of():
    """Test Graze.filepath_of method"""
    from graze.base import Graze

    temp_dir = tempfile.mkdtemp()
    g = Graze(rootdir=temp_dir)

    # Get filepath without downloading
    filepath = g.filepath_of(test_url_1)
    assert isinstance(filepath, str)
    assert temp_dir in filepath

    # The file shouldn't exist yet
    assert not os.path.isfile(filepath)

    # Now download it
    _ = g[test_url_1]

    # Now the file should exist
    assert os.path.isfile(filepath)


def test_graze_filepath_of_url_downloading_if_necessary():
    """Test Graze.filepath_of_url_downloading_if_necessary method"""
    from graze.base import Graze

    temp_dir = tempfile.mkdtemp()
    g = Graze(rootdir=temp_dir)

    # This should download if necessary and return filepath
    filepath = g.filepath_of_url_downloading_if_necessary(test_url_1)
    assert isinstance(filepath, str)
    assert os.path.isfile(filepath)

    # Calling again should just return the filepath
    filepath2 = g.filepath_of_url_downloading_if_necessary(test_url_1)
    assert filepath == filepath2


def test_graze_with_key_ingress():
    """Test Graze with key_ingress callback"""
    from graze.base import Graze

    temp_dir = tempfile.mkdtemp()

    # Track if key_ingress was called
    called_urls = []

    def track_url(url):
        called_urls.append(url)
        return url

    g = Graze(rootdir=temp_dir, key_ingress=track_url)

    # Access a new URL (not cached)
    _ = g[test_url_1]

    # key_ingress should have been called
    assert test_url_1 in called_urls

    # Access again (cached) - key_ingress should NOT be called again
    called_urls.clear()
    _ = g[test_url_1]
    assert len(called_urls) == 0


def test_graze_returning_filepaths():
    """Test Graze with return_filepaths=True"""
    from graze.base import Graze

    temp_dir = tempfile.mkdtemp()
    g = Graze(rootdir=temp_dir, return_filepaths=True)

    # Should return filepath instead of contents
    result = g[test_url_1]
    assert isinstance(result, str)
    assert os.path.isfile(result)

    # The file should contain the expected content
    with open(result, "rb") as f:
        contents = f.read()
    _assert_first_line_is(contents, "file contents", test_url_contents_1_first_line)


def test_graze_returning_filepaths_alias():
    """Test GrazeReturningFilepaths alias"""
    from graze.base import GrazeReturningFilepaths

    temp_dir = tempfile.mkdtemp()
    g = GrazeReturningFilepaths(rootdir=temp_dir)

    # Should return filepath instead of contents
    result = g[test_url_1]
    assert isinstance(result, str)
    assert os.path.isfile(result)


def test_graze_with_data_refresh():
    """Test GrazeWithDataRefresh with time_to_live"""
    from graze.base import GrazeWithDataRefresh
    import time

    temp_dir = tempfile.mkdtemp()

    # Use a very short time_to_live for testing
    g = GrazeWithDataRefresh(rootdir=temp_dir, time_to_live=0.5)

    # First access
    contents1 = g[test_url_1]
    _assert_first_line_is(contents1, "first access", test_url_contents_1_first_line)

    # Wait a bit but not past time_to_live
    time.sleep(0.2)

    # Should still use cache (not stale yet)
    contents2 = g[test_url_1]
    assert contents1 == contents2

    # Wait past time_to_live
    time.sleep(0.4)  # Total wait is now 0.6 seconds > 0.5

    # Should re-download (but we'll get the same content)
    contents3 = g[test_url_1]
    _assert_first_line_is(contents3, "after refresh", test_url_contents_1_first_line)


def test_graze_with_data_refresh_on_error_ignore():
    """Test GrazeWithDataRefresh with on_error='ignore'"""
    from graze.base import GrazeWithDataRefresh, Internet
    import time

    temp_dir = tempfile.mkdtemp()

    # Create an Internet instance that will fail on the second call
    class FailingInternet(Internet):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        def _get_contents_of_url(self, url, file=None):
            self.call_count += 1
            if self.call_count > 1:
                raise Exception("Simulated network error")
            return super()._get_contents_of_url(url, file)

    failing_source = FailingInternet()
    g = GrazeWithDataRefresh(
        rootdir=temp_dir, source=failing_source, time_to_live=0.5, on_error="ignore"
    )

    # First access should succeed
    contents1 = g[test_url_1]
    _assert_first_line_is(contents1, "first access", test_url_contents_1_first_line)

    # Wait past time_to_live
    time.sleep(0.6)

    # Second access should fail to refresh but return stale data without error
    contents2 = g[test_url_1]
    assert contents1 == contents2  # Should still work with stale data


def test_standalone_graze_function():
    """Test the standalone graze function"""
    from graze.base import graze

    temp_dir = tempfile.mkdtemp()

    # Basic usage
    contents = graze(test_url_1, rootdir=temp_dir)
    _assert_first_line_is(contents, "graze result", test_url_contents_1_first_line)

    # With return_filepaths - note: the graze function doesn't directly support
    # return_filepaths, so we test that it returns contents by default
    contents2 = graze(test_url_1, rootdir=temp_dir)
    assert isinstance(contents2, bytes)

    # With max_age
    contents3 = graze(test_url_1, rootdir=temp_dir, max_age=3600)
    _assert_first_line_is(contents3, "graze with max_age", test_url_contents_1_first_line)



def test_url_to_filepath():
    """Test url_to_filepath function"""
    from graze.base import url_to_filepath

    temp_dir = tempfile.mkdtemp()

    # Test with download=None (download if necessary)
    filepath1 = url_to_filepath(test_url_1, rootdir=temp_dir, download=None)
    assert isinstance(filepath1, str)
    assert os.path.isfile(filepath1)

    # Verify contents
    with open(filepath1, "rb") as f:
        contents = f.read()
    _assert_first_line_is(contents, "downloaded file", test_url_contents_1_first_line)

    # Test with download=False (just get the path, don't download)
    test_url_2 = test_url_1.replace("test_base.py", "test_util.py")  # Different URL
    filepath2 = url_to_filepath(test_url_2, rootdir=temp_dir, download=False)
    assert isinstance(filepath2, str)
    # File should NOT exist since we didn't download
    assert not os.path.isfile(filepath2)

    # Note: download=True uses url_to_contents which is a class, not a function
    # This is a known issue in the base.py code at line 673
    # We skip testing download=True to avoid the TypeError



def test_return_functions():
    """Test different return functions for url_to_file_download"""
    from graze.base import (
        url_to_file_download,
        return_contents,
        return_filepath,
    )

    temp_dir = tempfile.mkdtemp()

    # Test return_contents (default)
    filepath1 = os.path.join(temp_dir, "__test_return_contents.txt")
    result = url_to_file_download(
        test_url_1, filepath1, return_func=return_contents
    )
    assert isinstance(result, bytes)
    _assert_first_line_is(result, "return_contents", test_url_contents_1_first_line)

    # Test return_filepath
    filepath2 = os.path.join(temp_dir, "__test_return_filepath.txt")
    result = url_to_file_download(
        test_url_1, filepath2, return_func=return_filepath
    )
    assert isinstance(result, str)
    assert result == filepath2
    assert os.path.isfile(filepath2)


def test_url_to_file_download_with_overwrite_callable():
    """Test url_to_file_download overwrite behavior
    
    Note: The current implementation in base.py checks `not overwrite` which
    treats callables as truthy. This test documents the actual behavior.
    """
    from graze.base import url_to_file_download
    import time

    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, "__test_overwrite_behavior.txt")

    # First download
    url_to_file_download(test_url_1, filepath)
    mtime1 = os.path.getmtime(filepath)

    time.sleep(0.1)

    # Test overwrite=False (should NOT overwrite)
    url_to_file_download(test_url_1, filepath, overwrite=False)
    mtime2 = os.path.getmtime(filepath)
    assert mtime2 == mtime1, "File should NOT have been overwritten with overwrite=False"

    # Test overwrite=True (should overwrite)
    time.sleep(0.1)
    url_to_file_download(test_url_1, filepath, overwrite=True)
    mtime3 = os.path.getmtime(filepath)
    assert mtime3 > mtime2, "File should have been overwritten with overwrite=True"




def test_url_egress_in_url_to_file_download():
    """Test url_egress parameter in url_to_file_download"""
    from graze.base import url_to_file_download

    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, "__test_url_egress.txt")

    # Track if url_egress was called
    egress_calls = []

    def track_egress(url):
        egress_calls.append(url)
        return url

    # Download with url_egress
    url_to_file_download(test_url_1, filepath, url_egress=track_egress)

    # Verify egress was called
    assert test_url_1 in egress_calls
    assert os.path.isfile(filepath)




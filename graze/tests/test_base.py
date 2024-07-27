"""Test the base module.

"""

import tempfile
from typing import Union
import os
from functools import partial
from pathlib import Path
from graze.base import url_to_file_download, Contents

test_url_1 = (
    'https://raw.githubusercontent.com/thorwhalen/graze/master/graze/tests/test_base.py'
)
test_url_contents_1_first_line = b'"""Test the base module.'


def _get_temp_path(relative_path: str = ''):
    return os.path.join(tempfile.mkdtemp(), relative_path)


def _first_line(contents: Contents) -> Contents:
    return next(iter(contents.splitlines()), None)


def _is_test_file(filepath: str) -> bool:
    """Determine if filepath is a test file"""
    return os.path.basename(filepath).startswith('__graze_test_file_')


def _if_test_file_exists_delete_it(filepath: str):
    """Safely delete a test file. If not a test file, raises ValueError"""
    if not _is_test_file(filepath):
        raise ValueError(f'Not a test file: {filepath}')
    if os.path.isfile(filepath):
        os.remove(filepath)
    return filepath  # return filepath (so we can use function in a pipe)


def _assert_first_line_is(
    contents: Contents, content_name='content', expected_first_line: Contents = None
):
    assert (
        _first_line(contents) == expected_first_line
    ), f"First line of {content_name} expected to be: {expected_first_line}"


def test_url_to_file_download_simple():
    filepath = _get_temp_path('__graze_test_file_01')
    print(f"\n------> INFO: {filepath}")
    _if_test_file_exists_delete_it(filepath)
    __assert_first_line_is = partial(
        _assert_first_line_is, expected_first_line=test_url_contents_1_first_line
    )

    assert os.path.isfile(filepath) is False, f"File expected not to exist: {filepath}"
    func_output = url_to_file_download(test_url_1, filepath)
    assert os.path.isfile(filepath), f"File expected to exist: {filepath}"
    __assert_first_line_is(func_output, 'func_output')
    contents_from_file = Path(filepath).read_bytes()
    __assert_first_line_is(contents_from_file, 'contents_from_file')


def test_url_to_file_download_complex():
    # Setup
    temp_dir = tempfile.mkdtemp()

    # Test 1: Basic download with default parameters
    filepath1 = os.path.join(temp_dir, '__graze_test_file_02')
    _if_test_file_exists_delete_it(filepath1)
    assert not os.path.isfile(filepath1), f"File expected not to exist: {filepath1}"
    result1 = url_to_file_download(test_url_1, filepath1)
    assert os.path.isfile(filepath1), f"File expected to exist: {filepath1}"
    _assert_first_line_is(result1, 'result1', test_url_contents_1_first_line)

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
    _assert_first_line_is(result2, 'result2', test_url_contents_1_first_line)
    # But we didn't get this from the url, we got this from our filepath1
    # See that the file was NOT overwritten (last updated timestamp should be the same)
    assert last_updated == os.path.getmtime(
        filepath1
    ), "File should NOT have been overwritten"
    # Let's drill this point further by writing something else in the file
    with open(filepath1, 'wb') as f:
        f.write(b'Temporary content')
    result3 = url_to_file_download(test_url_1, filepath1, overwrite=False)
    # now we don't get the same result
    assert result3 != result2, "Expected different content"
    assert result3 == b'Temporary content', "Expected new content"

    # Test 3: Overwrite existing file
    # The default of overwrite is True, so if you modify the file:
    with open(filepath1, 'wb') as f:
        f.write(b'Temporary content')
    # after using url_to_file_download
    result4 = url_to_file_download(test_url_1, filepath1, overwrite=True)
    # you'll get the original content again
    _assert_first_line_is(result4, 'result4', test_url_contents_1_first_line)

    # Test 4: Ensure directories exist
    nested_filepath = os.path.join(temp_dir, 'nested', '__graze_test_file_03')
    _if_test_file_exists_delete_it(nested_filepath)
    assert not os.path.isfile(
        nested_filepath
    ), f"File expected not to exist: {nested_filepath}"
    result5 = url_to_file_download(test_url_1, nested_filepath, ensure_dirs=True)
    assert os.path.isfile(nested_filepath), f"File expected to exist: {nested_filepath}"
    _assert_first_line_is(result5, 'result5', test_url_contents_1_first_line)

    # Test 5: Custom return function
    # By default, url_to_file_download will give you the contents of the file.
    # But in some cases you may want the filepath instead, or the url...
    # ... in fact you can have any function of all three that you want. Here's
    # a demo of that.
    filepath4 = os.path.join(temp_dir, '__graze_test_file_04')
    _if_test_file_exists_delete_it(filepath4)

    def custom_return_func(filepath, contents, url):
        return {"filepath": filepath, "contents": contents, "url": url}

    result6 = url_to_file_download(
        test_url_1, filepath4, return_func=custom_return_func
    )
    assert isinstance(result6, dict), "Expected result to be a dictionary"
    assert result6['filepath'] == filepath4, "Filepath mismatch in result"
    _assert_first_line_is(
        result6['contents'], 'result6["contents"]', test_url_contents_1_first_line
    )
    assert result6['url'] == test_url_1, "URL mismatch in result"

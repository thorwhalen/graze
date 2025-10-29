"""Tests for graze_exceptional module."""

import tempfile
import os
import json
from pathlib import Path
import pytest

from graze.graze_exceptional import (
    graze_cache,
    add_exception,
    list_exceptions,
    _load_exceptions_from_path,
    _discover_exceptions,
    _wrap_with_exceptions,
)


# --------------------------------------------------------------------------------------
# Tests for _load_exceptions_from_path
# --------------------------------------------------------------------------------------


def test_load_exceptions_from_path():
    """Test loading exceptions from a JSON file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(
                {
                    'http://example.com/data1': '/path/to/data1.txt',
                    'http://example.com/data2': '/path/to/data2.txt',
                },
                f,
            )

        exceptions = _load_exceptions_from_path(path)
        assert len(exceptions) == 2
        assert exceptions['http://example.com/data1'] == '/path/to/data1.txt'
        assert exceptions['http://example.com/data2'] == '/path/to/data2.txt'
    finally:
        os.unlink(path)


def test_load_exceptions_from_nonexistent_path():
    """Test loading exceptions from a file that doesn't exist."""
    exceptions = _load_exceptions_from_path('/nonexistent/path/file.json')
    assert exceptions == {}


def test_load_exceptions_from_empty_file():
    """Test loading exceptions from an empty JSON file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    try:
        os.close(fd)  # Close without writing anything
        exceptions = _load_exceptions_from_path(path)
        assert exceptions == {}
    finally:
        os.unlink(path)


# --------------------------------------------------------------------------------------
# Tests for _discover_exceptions
# --------------------------------------------------------------------------------------


def test_discover_exceptions_with_files_cache():
    """Test discovering exceptions from a Files cache."""
    from dol import Files

    cache_dir = tempfile.mkdtemp()
    try:
        # Create exceptions file
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        exceptions_file.write_text(
            json.dumps({'http://example.com/data': '/path/to/data.txt'})
        )

        # Create Files cache
        cache = Files(cache_dir)

        # Discover exceptions
        exceptions = _discover_exceptions(cache)
        assert len(exceptions) == 1
        assert exceptions['http://example.com/data'] == '/path/to/data.txt'
    finally:
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        os.rmdir(cache_dir)


def test_discover_exceptions_without_exceptions_file():
    """Test discovering exceptions when no _exceptions.json exists."""
    from dol import Files

    cache_dir = tempfile.mkdtemp()
    try:
        cache = Files(cache_dir)
        exceptions = _discover_exceptions(cache)
        assert exceptions == {}
    finally:
        os.rmdir(cache_dir)


def test_discover_exceptions_with_dict_cache():
    """Test that dict caches return empty exceptions."""
    cache = {'key': b'value'}
    exceptions = _discover_exceptions(cache)
    assert exceptions == {}


# --------------------------------------------------------------------------------------
# Tests for _wrap_with_exceptions
# --------------------------------------------------------------------------------------


def test_wrap_with_exceptions_basic():
    """Test wrapping a cache with exceptions."""
    cache = {'url1': b'cached data'}

    # Create a temp file for exception
    fd, filepath = tempfile.mkstemp()
    try:
        with os.fdopen(fd, 'w') as f:
            f.write('exceptional data')

        exceptions = {'url2': filepath}
        wrapped = _wrap_with_exceptions(cache, exceptions)

        # Test cached data
        assert wrapped['url1'] == b'cached data'

        # Test exceptional data
        assert wrapped['url2'] == b'exceptional data'
    finally:
        os.unlink(filepath)


def test_wrap_with_exceptions_preserves_cache_methods():
    """Test that wrapper preserves cache methods."""
    cache = {'url1': b'data1'}

    fd, filepath = tempfile.mkstemp()
    try:
        with os.fdopen(fd, 'w') as f:
            f.write('exceptional')

        exceptions = {'url2': filepath}
        wrapped = _wrap_with_exceptions(cache, exceptions)

        # Test __setitem__
        wrapped['url3'] = b'new data'
        assert 'url3' in cache
        assert cache['url3'] == b'new data'

        # Test __len__
        assert len(wrapped) == 2  # url1 and url3 (not url2, it's exceptional)

        # Test __iter__
        keys = list(wrapped)
        assert 'url1' in keys
        assert 'url3' in keys
    finally:
        os.unlink(filepath)


def test_wrap_with_exceptions_warns_on_missing_files():
    """Test that wrapper warns when exception files don't exist."""
    cache = {'url1': b'data'}
    exceptions = {'url2': '/nonexistent/file.txt', 'url3': '/another/missing.txt'}

    with pytest.warns(UserWarning, match="Excluded 2 exceptional URLs"):
        wrapped = _wrap_with_exceptions(cache, exceptions)

    # Should fall back to cache for missing exceptions
    with pytest.raises(KeyError):
        _ = wrapped['url2']


# --------------------------------------------------------------------------------------
# Tests for graze_cache with Files
# --------------------------------------------------------------------------------------


def test_graze_cache_with_string_rootdir():
    """Test graze_cache with string rootdir (creates Files cache)."""
    cache_dir = tempfile.mkdtemp()
    try:
        cache = graze_cache(cache_dir)

        # Should be a Files instance
        from dol import Files

        assert isinstance(cache, Files)
    finally:
        os.rmdir(cache_dir)


def test_graze_cache_auto_discovers_exceptions():
    """Test that graze_cache auto-discovers exceptions from _exceptions.json."""
    cache_dir = tempfile.mkdtemp()
    fd, data_file = tempfile.mkstemp()

    try:
        # Create data file
        with os.fdopen(fd, 'w') as f:
            f.write('pre-existing data')

        # Add exception
        add_exception(cache_dir, 'http://example.com/data', data_file)

        # Create cache (should auto-discover)
        from graze.base import url_to_localpath

        cache = graze_cache(cache_dir, url_to_cache_key=url_to_localpath)

        # Access via transformed key
        cache_key = url_to_localpath('http://example.com/data')
        result = cache[cache_key]
        assert result == b'pre-existing data'
    finally:
        os.unlink(data_file)
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        os.rmdir(cache_dir)


def test_graze_cache_with_explicit_exceptions_dict():
    """Test graze_cache with explicit exceptions dictionary."""
    cache_dir = tempfile.mkdtemp()
    fd, data_file = tempfile.mkstemp()

    try:
        with os.fdopen(fd, 'w') as f:
            f.write('explicit exception data')

        # Create cache with explicit exceptions
        exceptions = {'key1': data_file}
        cache = graze_cache(cache_dir, exceptions=exceptions)

        # Access exceptional data
        result = cache['key1']
        assert result == b'explicit exception data'
    finally:
        os.unlink(data_file)
        os.rmdir(cache_dir)


def test_graze_cache_with_exceptions_file_path():
    """Test graze_cache with exceptions loaded from a file path."""
    cache_dir = tempfile.mkdtemp()
    data_fd, data_file = tempfile.mkstemp()
    exc_fd, exc_file = tempfile.mkstemp(suffix='.json')

    try:
        # Create data file
        with os.fdopen(data_fd, 'w') as f:
            f.write('data from file path')

        # Create exceptions file
        with os.fdopen(exc_fd, 'w') as f:
            json.dump({'key1': data_file}, f)

        # Create cache with exceptions from file
        cache = graze_cache(cache_dir, exceptions=exc_file)

        result = cache['key1']
        assert result == b'data from file path'
    finally:
        os.unlink(data_file)
        os.unlink(exc_file)
        os.rmdir(cache_dir)


# --------------------------------------------------------------------------------------
# Tests for graze_cache with custom dict cache
# --------------------------------------------------------------------------------------


def test_graze_cache_with_dict_and_explicit_exceptions():
    """Test graze_cache with a dict cache and explicit exceptions."""
    cache = {'cached_key': b'cached value'}
    fd, exception_file = tempfile.mkstemp()

    try:
        with os.fdopen(fd, 'w') as f:
            f.write('exceptional value')

        exceptions = {'exception_key': exception_file}
        wrapped = graze_cache(cache, exceptions=exceptions)

        # Test cached data
        assert wrapped['cached_key'] == b'cached value'

        # Test exceptional data
        assert wrapped['exception_key'] == b'exceptional value'

        # Test setting new data
        wrapped['new_key'] = b'new value'
        assert cache['new_key'] == b'new value'
    finally:
        os.unlink(exception_file)


def test_graze_cache_dict_without_exceptions():
    """Test graze_cache with dict returns unwrapped dict if no exceptions."""
    cache = {'key': b'value'}
    wrapped = graze_cache(cache)

    # Should return the same dict
    assert wrapped is cache


def test_graze_cache_dict_with_url_to_cache_key_transform():
    """Test graze_cache with dict and url_to_cache_key transformation."""
    cache = {}
    fd, exception_file = tempfile.mkstemp()

    try:
        with os.fdopen(fd, 'w') as f:
            f.write('transformed data')

        # Exceptions use URLs
        exceptions = {'http://example.com/data': exception_file}

        # Transform function
        def simple_transform(url):
            return url.replace('http://', '').replace('/', '_')

        wrapped = graze_cache(
            cache, exceptions=exceptions, url_to_cache_key=simple_transform
        )

        # Access via transformed key
        transformed_key = simple_transform('http://example.com/data')
        result = wrapped[transformed_key]
        assert result == b'transformed data'
    finally:
        os.unlink(exception_file)


# --------------------------------------------------------------------------------------
# Tests for add_exception and list_exceptions
# --------------------------------------------------------------------------------------


def test_add_exception_basic():
    """Test adding an exception."""
    cache_dir = tempfile.mkdtemp()
    fd, data_file = tempfile.mkstemp()

    try:
        os.close(fd)

        # Add exception
        add_exception(cache_dir, 'http://example.com/data', data_file)

        # Verify exceptions file was created
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        assert exceptions_file.exists()

        # Verify content
        exceptions = json.loads(exceptions_file.read_text())
        assert 'http://example.com/data' in exceptions
        assert (
            Path(exceptions['http://example.com/data']).resolve()
            == Path(data_file).resolve()
        )
    finally:
        os.unlink(data_file)
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        os.rmdir(cache_dir)


def test_add_exception_multiple():
    """Test adding multiple exceptions."""
    cache_dir = tempfile.mkdtemp()
    files = []

    try:
        # Create multiple files
        for i in range(3):
            fd, filepath = tempfile.mkstemp()
            os.close(fd)
            files.append(filepath)
            add_exception(cache_dir, f'http://example.com/data{i}', filepath)

        # Verify all were added
        urls = list_exceptions(cache_dir)
        assert len(urls) == 3
        for i in range(3):
            assert f'http://example.com/data{i}' in urls
    finally:
        for filepath in files:
            os.unlink(filepath)
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        os.rmdir(cache_dir)


def test_add_exception_raises_on_missing_file():
    """Test that add_exception raises error if file doesn't exist."""
    cache_dir = tempfile.mkdtemp()

    try:
        with pytest.raises(FileNotFoundError, match="File does not exist"):
            add_exception(cache_dir, 'http://example.com/data', '/nonexistent/file.txt')
    finally:
        os.rmdir(cache_dir)


def test_list_exceptions_basic():
    """Test listing exceptions."""
    cache_dir = tempfile.mkdtemp()
    fd, data_file = tempfile.mkstemp()

    try:
        os.close(fd)
        add_exception(cache_dir, 'http://example.com/data', data_file)

        # List URLs only
        urls = list_exceptions(cache_dir)
        assert urls == ['http://example.com/data']

        # List URLs with paths
        urls_with_paths = list_exceptions(cache_dir, show_paths=True)
        assert len(urls_with_paths) == 1
        url, path = urls_with_paths[0]
        assert url == 'http://example.com/data'
        assert Path(path).resolve() == Path(data_file).resolve()
    finally:
        os.unlink(data_file)
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        os.rmdir(cache_dir)


def test_list_exceptions_empty():
    """Test listing exceptions when none exist."""
    cache_dir = tempfile.mkdtemp()

    try:
        urls = list_exceptions(cache_dir)
        assert urls == []

        urls_with_paths = list_exceptions(cache_dir, show_paths=True)
        assert urls_with_paths == []
    finally:
        os.rmdir(cache_dir)


# --------------------------------------------------------------------------------------
# Integration tests
# --------------------------------------------------------------------------------------


def test_end_to_end_with_files_cache():
    """Test complete workflow with Files cache."""
    from dol import Files
    from graze.base import url_to_localpath

    cache_dir = tempfile.mkdtemp()
    fd1, file1 = tempfile.mkstemp()
    fd2, file2 = tempfile.mkstemp()

    try:
        # Create data files
        with os.fdopen(fd1, 'w') as f:
            f.write('data 1')
        with os.fdopen(fd2, 'w') as f:
            f.write('data 2')

        # Add exceptions
        add_exception(cache_dir, 'http://example.com/data1', file1)
        add_exception(cache_dir, 'http://example.com/data2', file2)

        # Create wrapped cache
        cache = graze_cache(cache_dir, url_to_cache_key=url_to_localpath)

        # Access exceptional data
        key1 = url_to_localpath('http://example.com/data1')
        key2 = url_to_localpath('http://example.com/data2')

        assert cache[key1] == b'data 1'
        assert cache[key2] == b'data 2'

        # Write normal cached data (ensure directory exists for Files)
        key3 = url_to_localpath('http://example.com/data3')
        key3_path = Path(cache_dir) / key3
        os.makedirs(key3_path.parent, exist_ok=True)
        cache[key3] = b'data 3'

        # Verify it was written to the Files cache
        assert key3 in cache
        assert cache[key3] == b'data 3'
    finally:
        os.unlink(file1)
        os.unlink(file2)
        exceptions_file = Path(cache_dir) / '_exceptions.json'
        if exceptions_file.exists():
            os.unlink(exceptions_file)
        # Don't remove cache_dir as it may have files written to it


def test_end_to_end_with_dict_cache():
    """Test complete workflow with dict cache."""
    cache = {
        'normal_key1': b'normal data 1',
        'normal_key2': b'normal data 2',
    }

    fd1, file1 = tempfile.mkstemp()
    fd2, file2 = tempfile.mkstemp()

    try:
        with os.fdopen(fd1, 'w') as f:
            f.write('exceptional data 1')
        with os.fdopen(fd2, 'w') as f:
            f.write('exceptional data 2')

        exceptions = {
            'exception_key1': file1,
            'exception_key2': file2,
        }

        wrapped = graze_cache(cache, exceptions=exceptions)

        # Access normal cached data
        assert wrapped['normal_key1'] == b'normal data 1'
        assert wrapped['normal_key2'] == b'normal data 2'

        # Access exceptional data
        assert wrapped['exception_key1'] == b'exceptional data 1'
        assert wrapped['exception_key2'] == b'exceptional data 2'

        # Write new data
        wrapped['new_key'] = b'new data'
        assert cache['new_key'] == b'new data'

        # Verify iteration
        keys = set(wrapped)
        assert 'normal_key1' in keys
        assert 'normal_key2' in keys
        assert 'new_key' in keys

        # Verify length (doesn't include exceptional keys as they're not in underlying cache)
        assert len(wrapped) == 3
    finally:
        os.unlink(file1)
        os.unlink(file2)


def test_dict_cache_with_mixed_operations():
    """Test dict cache with mixed read/write/delete operations."""
    cache = {'key1': b'value1'}
    fd, exception_file = tempfile.mkstemp()

    try:
        with os.fdopen(fd, 'w') as f:
            f.write('exception value')

        exceptions = {'exception_key': exception_file}
        wrapped = graze_cache(cache, exceptions=exceptions)

        # Read
        assert wrapped['key1'] == b'value1'
        assert wrapped['exception_key'] == b'exception value'

        # Write
        wrapped['key2'] = b'value2'
        assert cache['key2'] == b'value2'

        # Update
        wrapped['key1'] = b'updated value1'
        assert cache['key1'] == b'updated value1'

        # Delete
        del wrapped['key1']
        assert 'key1' not in cache

        # Exception key should still work
        assert wrapped['exception_key'] == b'exception value'
    finally:
        os.unlink(exception_file)

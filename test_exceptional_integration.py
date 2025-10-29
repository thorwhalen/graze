"""
Integration test for exceptional URLs functionality with Graze.

This demonstrates the complete workflow of using exceptional URLs with Graze.
"""

import tempfile
import os
import json
from pathlib import Path


# Test that basic exceptional URL functionality works
def test_exceptional_urls_with_graze():
    """Test that Graze automatically discovers and uses exceptional URLs."""
    from graze.base import Graze
    from graze.graze_exceptional import add_exception

    # Create a temp directory for the cache
    cache_dir = tempfile.mkdtemp()
    print(f"\n✓ Created cache directory: {cache_dir}")

    # Create a temp file with some test data (simulating pre-existing data)
    test_data = b"This is pre-existing data that we don't want to re-download"
    fd, existing_file = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(test_data)
    print(f"✓ Created test file: {existing_file}")

    # Add an exception for a URL to point to our existing file
    test_url = "http://example.com/my-data.txt"
    add_exception(cache_dir, test_url, existing_file)
    print(f"✓ Added exception: {test_url} -> {existing_file}")

    # Verify the _exceptions.json file was created
    exceptions_file = Path(cache_dir) / "_exceptions.json"
    assert exceptions_file.exists(), "Exceptions file should exist"
    print(f"✓ Exceptions file created: {exceptions_file}")

    # Create a Graze instance - it should auto-discover the exceptions
    g = Graze(rootdir=cache_dir)
    print(f"✓ Created Graze instance (auto-discovers exceptions)")

    # Access the URL - should return the pre-existing data without downloading
    result = g[test_url]
    assert result == test_data, "Should get data from exceptional URL"
    print(f"✓ Got data from exceptional URL: {result[:50]}...")

    # Clean up
    os.unlink(existing_file)
    os.unlink(exceptions_file)
    os.rmdir(cache_dir)
    print(f"✓ Cleaned up test files")

    print("\n✅ All tests passed! Exceptional URLs work with Graze.")


def test_exceptional_urls_with_multiple_sources():
    """Test multiple exceptional URLs."""
    from graze.base import Graze
    from graze.graze_exceptional import add_exception, list_exceptions

    cache_dir = tempfile.mkdtemp()
    print(f"\n✓ Created cache directory: {cache_dir}")

    # Create multiple test files
    test_files = {}
    for i in range(3):
        data = f"Test data {i}".encode()
        fd, filepath = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        url = f"http://example.com/data-{i}.txt"
        test_files[url] = (filepath, data)
        add_exception(cache_dir, url, filepath)
        print(f"✓ Added exception {i+1}: {url} -> {filepath}")

    # List the exceptions
    urls = list_exceptions(cache_dir)
    assert len(urls) == 3, "Should have 3 exceptions"
    print(f"✓ Listed {len(urls)} exceptions")

    # Access all URLs through Graze
    g = Graze(rootdir=cache_dir)
    for url, (filepath, expected_data) in test_files.items():
        result = g[url]
        assert result == expected_data, f"Data mismatch for {url}"
        print(f"✓ Retrieved data for: {url}")

    # Clean up
    for url, (filepath, _) in test_files.items():
        os.unlink(filepath)
    os.unlink(Path(cache_dir) / "_exceptions.json")
    os.rmdir(cache_dir)
    print(f"✓ Cleaned up test files")

    print("\n✅ Multiple exceptional URLs test passed!")


def test_exceptional_urls_mixed_with_normal_downloads():
    """Test that exceptional URLs work alongside normal URL downloads."""
    from graze.base import Graze
    from graze.graze_exceptional import add_exception

    cache_dir = tempfile.mkdtemp()
    print(f"\n✓ Created cache directory: {cache_dir}")

    # Create an exceptional URL
    test_data = b"Exceptional data"
    fd, existing_file = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(test_data)
    exceptional_url = "http://example.com/exceptional.txt"
    add_exception(cache_dir, exceptional_url, existing_file)
    print(f"✓ Added exceptional URL: {exceptional_url}")

    # Create Graze instance
    g = Graze(rootdir=cache_dir)

    # Access the exceptional URL
    result1 = g[exceptional_url]
    assert result1 == test_data
    print(f"✓ Retrieved exceptional data: {result1}")

    # Access a real URL (this will actually download)
    real_url = "https://raw.githubusercontent.com/thorwhalen/graze/master/README.md"
    result2 = g[real_url]
    assert len(result2) > 0, "Should download real data"
    print(f"✓ Downloaded real URL: {real_url} ({len(result2)} bytes)")

    # Verify both are in the cache
    assert exceptional_url in g
    assert real_url in g
    print(f"✓ Both URLs are cached")

    # Clean up
    os.unlink(existing_file)
    os.unlink(Path(cache_dir) / "_exceptions.json")
    # Don't delete cache_dir as it has downloaded files
    print(f"✓ Cleaned up exceptional file")

    print("\n✅ Mixed exceptional and normal URLs test passed!")


if __name__ == "__main__":
    print("=" * 70)
    print("Testing Exceptional URLs Integration with Graze")
    print("=" * 70)

    test_exceptional_urls_with_graze()
    test_exceptional_urls_with_multiple_sources()
    test_exceptional_urls_mixed_with_normal_downloads()

    print("\n" + "=" * 70)
    print("🎉 All integration tests passed!")
    print("=" * 70)

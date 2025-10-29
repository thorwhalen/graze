#!/usr/bin/env python
"""
Quick Demo: Exceptional URLs with Graze

This script demonstrates how to use exceptional URLs to avoid re-downloading data.
"""

import tempfile
import os
from pathlib import Path


def demo_exceptional_urls():
    """Demonstrate the exceptional URLs feature."""

    print("=" * 70)
    print("Exceptional URLs Demo")
    print("=" * 70)
    print()

    # Step 1: Setup
    print("📁 Setting up demo environment...")
    cache_dir = tempfile.mkdtemp()
    print(f"   Cache directory: {cache_dir}")

    # Create a file with some "precious" data we don't want to re-download
    precious_data = b"This data took hours to download! Don't download it again!"
    fd, precious_file = tempfile.mkstemp(suffix='.dat')
    with os.fdopen(fd, 'wb') as f:
        f.write(precious_data)
    print(f"   Precious file: {precious_file}")
    print()

    # Step 2: Add an exception
    print("⚙️  Adding exception mapping...")
    from graze import add_exception

    fake_url = "http://bigdata.example.com/massive-dataset.dat"
    add_exception(cache_dir, fake_url, precious_file)
    print(f"   URL: {fake_url}")
    print(f"   → Maps to: {precious_file}")
    print()

    # Step 3: Show the exceptions file
    print("📋 Exceptions file created:")
    exceptions_file = Path(cache_dir) / '_exceptions.json'
    print(f"   {exceptions_file}")
    print(f"   Content: {exceptions_file.read_text()[:100]}...")
    print()

    # Step 4: Use Graze (it auto-discovers the exception)
    print("🔍 Creating Graze instance (auto-discovers exceptions)...")
    from graze import Graze

    g = Graze(rootdir=cache_dir)
    print("   ✓ Graze created")
    print()

    # Step 5: Access the URL (uses exceptional file, no download!)
    print("🎯 Accessing the 'remote' URL...")
    print(f"   Getting: {fake_url}")
    result = g[fake_url]
    print(f"   ✓ Got: {result}")
    print()

    # Step 6: Show that it really used the local file
    print("✨ Verification:")
    print(f"   Original file content: {precious_data}")
    print(f"   Retrieved content:     {result}")
    print(f"   Match: {result == precious_data}")
    print()

    # Step 7: Show it works alongside normal URLs
    print("🌐 Normal URLs still work as before...")
    real_url = "https://raw.githubusercontent.com/thorwhalen/graze/master/LICENSE"
    license_text = g[real_url]
    print(f"   Downloaded: {real_url}")
    print(f"   Size: {len(license_text)} bytes")
    print(f"   First line: {license_text.splitlines()[0]}")
    print()

    # Step 8: List all exceptions
    print("📜 Listing all exceptions:")
    from graze import list_exceptions

    urls = list_exceptions(cache_dir)
    for i, url in enumerate(urls, 1):
        print(f"   {i}. {url}")
    print()

    # Cleanup
    print("🧹 Cleaning up...")
    os.unlink(precious_file)
    os.unlink(exceptions_file)
    print()

    print("=" * 70)
    print("✅ Demo Complete!")
    print("=" * 70)
    print()
    print("Key Takeaways:")
    print("  • Exceptions are stored in _exceptions.json")
    print("  • Graze automatically discovers and uses them")
    print("  • No code changes needed to existing Graze usage")
    print("  • Mix exceptional and normal URLs freely")
    print()


if __name__ == "__main__":
    demo_exceptional_urls()

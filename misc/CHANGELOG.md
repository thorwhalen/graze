# Changelog

All notable changes to the graze project will be documented in this file.

### Changed - 2025-10-28

#### Major Refactoring: Made `graze()` Function the Single Source of Truth

Refactored the Graze classes architecture following TDD principles to eliminate code duplication and make the `graze()` function the central implementation for all caching and downloading operations.

**New Architecture:**
- Created `GrazeBase(MutableMapping)` - Foundation class that wraps `graze()` function
- Refactored `Graze` to extend `GrazeBase` instead of `LocalGrazed`
- Refactored `GrazeWithDataRefresh` to use refresh functions instead of custom `__getitem__` logic

**Key Improvements:**
- **Single Source of Truth**: All classes now delegate work to `graze()` function
- **Less Code Duplication**: Removed redundant `__missing__` and caching logic
- **More Flexible Cache Support**: Support for folder paths, `Files` objects, and any `MutableMapping` (e.g., dict)
- **100% Backwards Compatible**: All existing APIs and behavior maintained
- **Better Error Handling**: Improved error handling in `GrazeWithDataRefresh` with proper stale data return
- **More Robust**: Added comprehensive test coverage (71 tests, up from 55+)

**Technical Details:**
- Added helper functions: `_iterate_cache()`, `_get_cache_size()`, enhanced `_cache_set()`
- `GrazeBase` provides complete `MutableMapping` interface: `__getitem__`, `__setitem__`, `__delitem__`, `__iter__`, `__contains__`, `__len__`
- `Graze.filepath_of()` reimplemented without dependency on `LocalGrazed` internals
- `GrazeWithDataRefresh` now creates refresh functions based on `time_to_live` parameter
- Enhanced `_cache_set()` to automatically create directories for file-based `MutableMapping` stores

**Testing:**
- Added 7 new tests for `Graze` class behavior
- Added 5 new tests for `GrazeWithDataRefresh` class behavior
- Added 11 new tests for new `GrazeBase` class
- All 71 tests pass with full backwards compatibility

**Benefits:**
- Easier to maintain - changes only needed in `graze()` function
- Clearer separation of concerns - each class has well-defined responsibilities
- More extensible - easy to add new cache backends through `MutableMapping` interface
- Better tested - comprehensive test coverage ensures reliability

**Migration Notes:**
- No breaking changes - all existing code continues to work as before
- New `GrazeBase` class available for users who want the simpler foundation interface
- `cache` parameter in `graze()` function now supports any `MutableMapping`, not just folder paths



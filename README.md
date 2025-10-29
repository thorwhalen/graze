# graze

Cache (a tiny part of) the internet.

(For the technically inclined, `graze` is meant to ease the separation of the concerns of getting and caching/persisting data from the internet.)

## install

```pip install graze```


# Quick example

```python
from graze import Graze
import os
rootdir = os.path.expanduser('~/graze')
g = Graze(rootdir)
list(g)
```

If this is your first time, you got nothing:

```
[]
```

So get something. For no particular reason let's be self-referential and get myself:

```python
url = 'https://raw.githubusercontent.com/thorwhalen/graze/master/README.md'
content = g[url]
type(content), len(content)
```

Before I grew up, I had only 46 petty bytes (I have a lot more now):

```
(bytes, 46)
```

These were:

```python
print(content.decode())
```

```
# graze

Cache (a tiny part of) the internet.
```

But now, here's the deal. List your ``g`` keys now. Go ahead, don't be shy!

```python
list(g)
```
```
['https://raw.githubusercontent.com/thorwhalen/graze/master/README.md']
```

What does that mean? 

I means you have a local copy of these contents. 

The file path isn't really ``https://...``, it's `rootdir/https/...`, but you 
only have to care about that if you actually have to go get the file with
something else than graze. Because graze will give it to you.

How? Same way you got it in the first place:

```
content_2 = g[url]
assert content_2 == content
```

But this time, it didn't ask the internet. It just got it's local copy.

And if you want a fresh copy? 

No problem, just delete your local one. You guessed! 
The same way you would delete a key from a dict:

```python
del g[url]
```


# Understanding graze: Function and Class

Now that you've seen `graze` in action, let's dive deeper into how it works and what options you have to tailor it to your needs.

## The `graze()` function: Your core workhorse

At the heart of the package is the `graze()` function. It's simple: give it a URL, and it gives you back the contents as bytes. But here's the clever bit—it caches those bytes locally so the next time you ask for the same URL, you get instant access without hitting the network again.

```python
from graze import graze

# First call downloads and caches
content = graze('https://example.com/data.json')

# Second call uses cached version - blazing fast!
content_again = graze('https://example.com/data.json')
```

### Where does it cache?

By default, `graze()` stores files in `~/graze`, but you have full control over this through the `cache` parameter:

```python
# Cache to a specific folder
content = graze(url, cache='~/my_project/cache')

# Or use a specific filepath (cache defaults to None automatically)
content = graze(url, cache_key='~/data/specific_file.json')

# Or even use a dict for in-memory caching!
my_cache = {}
content = graze(url, cache=my_cache, cache_key='data.json')
```

The `cache` parameter accepts:
- `None` (default): Uses `~/graze` as the cache folder
- A string path: Any folder where you want files cached
- A `MutableMapping` (like dict or `dol.Files`): Custom storage backend

### Controlling the cache key

The `cache_key` parameter determines what key is used in your cache. By default, URLs are converted to safe filesystem paths, but you can customize this:

```python
# Auto-generated key (default)
content = graze('https://example.com/data.json')

# Explicit cache key
content = graze('https://example.com/data.json', cache_key='my_data.json')

# Use a function to generate keys
def url_to_key(url):
    return url.split('/')[-1]  # Just use filename
content = graze('https://example.com/data/file.json', cache_key=url_to_key)

# Or provide a full filepath (makes cache default to None)
content = graze('https://example.com/data.json', cache_key='~/my_data/important.json')
```

### Keeping data fresh

What if the data at your URL changes? `graze` offers two powerful refresh strategies:

**Time-based refresh with `max_age`:**

```python
# Re-download if cached data is older than 1 hour (3600 seconds)
content = graze(url, max_age=3600)

# Or for a whole day
content = graze(url, max_age=86400)
```

**Custom refresh logic with `refresh`:**

```python
# Always re-download
content = graze(url, refresh=True)

# Or use a function for complex logic
def should_refresh(cache_key, url):
    # Your custom logic here
    return some_condition

content = graze(url, refresh=should_refresh)
```

### Custom data sources

By default, `graze` uses `requests` to fetch URLs, but you can plug in any data source:

```python
from graze import graze, Internet

# Use a custom fetcher function
def my_fetcher(url):
    # Your custom logic (must return bytes)
    return response_bytes

content = graze(url, source=my_fetcher)

# Or use an object with __getitem__
content = graze(url, source=Internet(timeout=30))
```

### Getting notified of downloads

Want to know when `graze` is actually hitting the network?

```python
# Simple notification
content = graze(url, key_ingress=lambda k: print(f"Downloading {k}..."))

# Or get fancy with logging
import logging
logger = logging.getLogger(__name__)
content = graze(url, key_ingress=lambda k: logger.info(f"Fetching fresh data from {k}"))
```

### Other useful parameters

```python
# Get the cache key/filepath instead of contents
filepath = graze(url, return_key=True)
```

## The `Graze` class: Your dict-like cache interface

While the `graze()` function is great for one-off fetches, the `Graze` class gives you a convenient dict-like interface to browse and manage your cached data.

```python
from graze import Graze

# Create your cache interface
g = Graze('~/my_cache')

# It's a mapping - use it like a dict!
urls = list(g)  # See what you've cached
content = g[url]  # Get contents (downloads if not cached)
url in g  # Check if cached
len(g)  # Count cached items
del g[url]  # Remove from cache
```

The beauty of `Graze` is that it makes your cache feel like a dictionary where the keys are URLs and the values are the byte contents. Under the hood, it's using the `graze()` function for all the heavy lifting.

### Configuring your Graze instance

`Graze` accepts similar parameters to `graze()`, but they apply to all operations:

```python
from graze import Graze, Internet

g = Graze(
    rootdir='~/my_cache',  # Where to cache
    source=Internet(timeout=30),  # Custom source
    key_ingress=lambda k: print(f"Fetching {k}"),  # Download notifications
)

# Now all operations use these settings
content = g['https://example.com/data.json']
```

### Working with filepaths

Sometimes you need the actual filepath where data is cached:

```python
# Get filepaths instead of contents
g = Graze('~/cache', return_filepaths=True)
filepath = g[url]  # Returns path string instead of bytes

# Or get filepath on demand
g = Graze('~/cache')
filepath = g.filepath_of(url)
content = g[url]  # Still gets contents normally
```

### When you need TTL (time-to-live) caching

For data that changes periodically, use `GrazeWithDataRefresh`:

```python
from graze import GrazeWithDataRefresh

# Re-fetch if data is older than 1 hour
g = GrazeWithDataRefresh(
    rootdir='~/cache',
    time_to_live=3600,  # seconds
    on_error='ignore'  # Return stale data if refresh fails
)

content = g[url]  # Fresh data (or cached if recent enough)
```

The `on_error` parameter controls what happens when refresh fails:
- `'ignore'`: Silently return stale cached data
- `'warn'`: Warn but return stale data
- `'raise'`: Raise the error
- `'warn_and_return_local'`: Warn and return stale data

### Advanced cache backends

Want to cache to something other than files? Use any `MutableMapping`:

```python
from dol import Files

# Files gives you a dict-like interface to a filesystem
cache = Files('~/cache')
g = Graze(cache)  # Now using Files instead of plain folder

# Or use an in-memory dict for temporary caching
cache = {}
g = Graze(cache)
```

## Choosing between `graze()` and `Graze`

Use the **`graze()` function** when:
- You're fetching a single URL
- You want different settings per fetch
- You prefer a functional style

Use the **`Graze` class** when:
- You want a dict-like interface to your cache
- You're working with multiple URLs with consistent settings
- You need to browse, count, or manage cached items
- You want to check what's cached before fetching


# Q&A


## The pages I need to slurp need to be rendered, can I use selenium of other such engines?

Sure!

We understand that sometimes you might have special slurping needs -- such 
as needing to let the JS render the page fully, and/or extract something 
specific, in a specific way, from the page.

Selenium is a popular choice for these needs.

`graze` doesn't install selenium for you, but if you've done that, you just 
need to specify a different `Internet` object for `Graze` to source from, 
and to make an internet object, you just need to specify what a 
`url_to_contents` function that does exactly what it says. 

Note that the contents need to be returned in bytes for `Graze` to work.

If you want to use some of the default `selenium` `url_to_contents` functions 
to make an `Internet` (we got Chrome, Firefox, Safari, and Opera), 
you go ahead! here's an example using the default Chrome driver
(again, you need to have the driver installed already for this to work; 
see https://selenium-python.readthedocs.io/):

```python
from graze import Graze, url_to_contents, Internet

g = Graze(source=Internet(url_to_contents=url_to_contents.selenium_chrome))
```

And if you'll be using it often, just do:

```python
from graze import Graze, url_to_contents, Internet
from functools import partial
my_graze =  partial(
    Graze,
    rootdir='a_specific_root_dir_for_your_project',
    source=Internet(url_to_contents=url_to_contents.selenium_chrome)
)

# and then you can just do
g = my_graze()
# and get on with the fun...
```


## What if I want a fresh copy of the data?

Classic caching problem. 
You like the convenience of having a local copy, but then how do you keep in sync with the data source if it changes?

See the "Keeping data fresh" section above for comprehensive coverage of refresh strategies. In brief:

If you KNOW the source data changed and want to sync, it's easy. You delete the local copy 
(like deleting a key from a dict: `del g[url]`)
and you try to access it again. 
Since you don't have a local copy, it will get one from the `url` source. 

For automatic refresh, you have several options:

**Time-based (TTL) refresh:**
```python
from graze import graze

# Re-download if cached data is older than an hour
content_bytes = graze(url, max_age=3600)
```

**Or use `GrazeWithDataRefresh` for dict-like TTL caching:**
```python
from graze import GrazeWithDataRefresh

g = GrazeWithDataRefresh(time_to_live=3600, on_error='ignore')
content = g[url]
```

**Custom refresh logic:**
```python
# Always refresh
content = graze(url, refresh=True)

# Or use a custom function
def should_refresh(cache_key, url):
    return your_logic_here

content = graze(url, refresh=should_refresh)
```

## Can I make graze notify me when it gets a new copy of the data?

Sure! Just specify a `key_ingress` function when you make your `Graze` object, or 
call `graze`. This function will be called on the key (the url) just before contents 
are being downloaded from the internet. The typical function would be:

```python
key_ingress = lambda key: print(f"Getting {key} from the internet")
```

## Does graze work for dropbox links?

Yes it does, but you need to be aware that dropbox systematically send the data as a zip, **even if there's only one file in it**.

Here's some code that can help.

```python
def zip_store_of_dropbox_url(dropbox_url: str):
    """Get a key-value perspective of the (folder) contents 
    of the zip a dropbox url gets you"""
    from graze import graze
    from dol import FilesOfZip
    return FilesOfZip(graze(dropbox_url))
    
def filebytes_of_dropbox_url(dropbox_url: str, assert_only_one_file=True):
    """Get the bytes of the first file in a zip that a dropbox url gives you"""
    zip_store = zip_store_of_dropbox_url(dropbox_url)
    zip_filepaths = iter(zip_store)
    first_filepath = next(zip_filepaths)
    if assert_only_one_file:
        assert next(zip_filepaths, None) is None, f"More than one file in {dropbox_url}"
    return zip_store[first_filepath]
```


# Notes

## New url-to-path mapping 

`graze` used to have a more straightforward url-to-local_filepath mapping, 
but it ended up being problematic: In a nutshell, 
if you slurp `abc.com` and it goes to a file of that name, 
where is `abc.com/data.zip` supposed to go (`abc.com` needs to be a folder 
in that case).  
See [issue](https://github.com/thorwhalen/graze/issues/1).

It's with a heavy heart that I changed the mapping to one that was still 
straightforward, but has the disadvantage of mapping all files to the 
same file name, without extension. 

Hopefully a better solution will show up soon.

If you already have graze files from the old way, you can 
use the `change_files_to_new_url_to_filepath_format` function to change these 
to the new format. 




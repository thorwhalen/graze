# graze

Cache (a tiny part of) the internet.

## install

```pip install graze```

# Example

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

Before I grew up, I had only 46 petty bytes:
```
(bytes, 46)
```

These were:

```python
print(content.decode())
```

```

# graze

Cache (a tiny part of) the internet
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


# Q&A

## What if I want a fresh copy of the data?

Classic caching problem. 
You like the convenience of having a local copy, but then how do you keep in sync with the data source if it changes?

If you KNOW the source data changed and want to sync, it's easy. You delete the local copy 
(like deleting a key from a dict: `del Graze()[url]`)
and you try to access it again. 
Since you don't have a local copy, it will get one from the `url` source. 

What if you want this to happen automatically? 

Well, there's several ways to do that. 

If you have a way to know if the source and local are different (through modified dates, or hashes, etc.), 
then you can write a little function to keep things in sync. 
But that's context dependent; `graze` doesn't offer you any default way to do it. 

Another way to do this is sometimes known as a `TTL Cache` (time-to-live cache). 
You get such functionality with the `graze.GrazeWithDataRefresh` store, or for most cases, 
simply getting your data through the `graze` function
specifying a `max_age` value (in seconds):

```
from graze import graze

content_bytes = graze(url, max_age=in_seconds)
```

## Does it work for dropbox links?

Yes it does, but you need to be aware that dropbox systematically send the data as a zip, **even if there's only one file in it**.

Here's some code that can help.

```python
def zip_store_of_gropbox_url(dropbox_url: str):
    """Get a key-value perspective of the (folder) contents 
    of the zip a dropbox url gets you"""
    from graze import graze
    from py2store import FilesOfZip
    return FilesOfZip(graze(dropbox_url))
    
def filebytes_of_dropbox_url(dropbox_url: str, assert_only_one_file=True):
    """Get the bytes of the first file in a zip that a dropbox url gives you"""
    zip_store = zip_store_of_gropbox_url(dropbox_url)
    zip_filepaths = iter(zip_store)
    first_filepath = next(zip_filepaths)
    if assert_only_one_file:
        assert next(zip_filepaths, None) is None, f"More than one file in {dropbox_url}"
    return zip_store[first_filepath]
```




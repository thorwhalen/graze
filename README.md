# graze

Cache (a tiny part of) the internet.

(For the technically inclined, graze is meant to enable the separation of the concerns 
of getting and caching data from the internet.)

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

## Can I make graze notify me when it gets a new copy of the data?

Sure! Just specify a `preget` function when you make your `Graze` object, or 
call `graze`. This function will be called on the key (the url) just before contents 
are being downloaded from the internet. The typical function would be:

```python
preget = lambda key: print(f"Getting {key} from the internet")
```


## Does graze work for dropbox links?

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




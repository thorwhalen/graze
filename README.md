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


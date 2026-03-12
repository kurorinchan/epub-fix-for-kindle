# What is this?
Some `epub` files do not "just work" transfering them to Kindle. Whether it is done via
send-to-kindle webpage by Amazon or using Calibre and sending them over USB.

Kindle freezes up and most books fail to open until it is rebooted.

This problem could be avoided by removing `<svg>` elements from problematic books.
You can check whether the `epub` file contains `svg` in Calibre by trying to edit the book. Its
cover page and first few pages of images (common in Light novels), have `svg` elements surrounding
`image` elements.
This script tries to "fix" it by replacing them with `p` and `img` elements.

# Prerequisite
`ebook-convert` (bundled with the Calibre app) is in the PATH so that the script can reference it.
You probably want to install Calibre anyway, so that you can transfer the resulting file to Kindle.

# Usage
```bash
python3 convert.py -i input.epub -o output.epub
```


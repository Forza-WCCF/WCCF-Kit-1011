# python\ - Python, so players install nothing

Python 3.13 (python.org's "embeddable" build) with Pillow 11.3 (pictures) in `Lib\site-packages`. Everything in
`code\` runs with this Python. The files here are Python's own - do not edit them, with one exception:

| File | What it does |
|---|---|
| `python313._pth` | THE KIT'S FILE: the only place this Python learns where the kit's code is (`..\code`). Rename `code\` and this must change too - `source\test_imports.py` fails if it does not |
| `python.exe`, `pythonw.exe` | Python itself (with and without a console window) |
| `python313.zip` | Python's standard library |
| `LICENSE.txt` | Python's licence |
| the `.dll` and `.pyd` files | the parts of Python and its standard library that are compiled |

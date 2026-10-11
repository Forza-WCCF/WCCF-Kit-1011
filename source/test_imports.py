# -*- coding: utf-8 -*-
"""test_imports.py - every file in code\\ (every folder) imports the way the launchers run the kit: through
python\\python313._pth alone - nothing is added to the path here.  2026-10-11: a folder renamed without the _pth, and a
file moved one folder deeper, both passed every other test (they add code\\ to the path themselves).  check.ps1 runs it
with the kit's Python.
    python\\python.exe -I source\\test_imports.py"""
import importlib
import os
import sys

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


try:
    import kit_common as K
except ImportError as ex:
    print("FAILED: kit_common is not found through python313._pth (%s)" % ex)
    sys.exit(1)
code = K.SCRIPTS
check(os.path.basename(code) == "code", "kit_common comes from code\\ (got %s)" % code)

names = []
for root, dirs, files in os.walk(code):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    rel = os.path.relpath(root, code)
    for f in sorted(files):
        if f.endswith(".py"):
            names.append(f[:-3] if rel == "." else "%s.%s" % (rel.replace(os.sep, "."), f[:-3]))
for name in names:
    try:
        importlib.import_module(name)
    except Exception as ex:  # noqa: BLE001 - any failure to import is the finding
        check(False, "import %s: %s: %s" % (name, type(ex).__name__, ex))

# imports inside functions (run only when that feature is used - SEND LOGS imports online.send_logs on a click):
# every import line in every file must name something Python can find
import ast  # noqa: E402
import importlib.util  # noqa: E402
for root, dirs, files in os.walk(code):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        for node in ast.walk(ast.parse(open(path, "rb").read(), path)):
            wanted = []
            if isinstance(node, ast.Import):
                wanted = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                wanted = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names
                                          if os.path.isdir(os.path.join(code, node.module))]
            for w in wanted:
                try:
                    found = importlib.util.find_spec(w) is not None
                except (ImportError, ValueError):
                    found = False
                check(found, "%s line %d: import %s - not found" % (os.path.relpath(path, code), node.lineno, w))

# a file one folder deeper must not take "two folders up" for the kit
from online import send_logs  # noqa: E402
check(os.path.normcase(send_logs.KIT) == os.path.normcase(K.KIT), "send_logs.KIT is the kit (%s)" % send_logs.KIT)

print("imports: %d files in code\\ import through python313._pth, %d failed" % (len(names), len(fails)))
sys.exit(1 if fails else 0)

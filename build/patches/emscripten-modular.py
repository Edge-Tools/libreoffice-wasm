#!/usr/bin/env python3
"""
Patch LibreOffice's EMSCRIPTEN_INTEL_GCC.mk to produce an ES6-modular soffice
with callMain, FS, and ENV unconditionally exported.

Without this patch:
  - callMain/FS are only exported when ENABLE_QT6 is set (Qt GUI builds)
  - main() fires automatically (INVOKE_RUN default)
  - the output is a non-modular global-Module script

We intentionally do NOT change gb_Executable_EXT.  Changing it (e.g. .js →
.mjs) breaks the install rules for other emscripten executables (uri-encode,
unoidl-read) because the GBuild auxiliary-target rules feed the renamed file
back into em++ as an object-file input, which em++ rejects.  Instead we keep
the .js extension and rename soffice.js → soffice.mjs in the Dockerfile.
"""
import re, sys

path = sys.argv[1]
c = open(path).read()

marker = "-s EXIT_RUNTIME=0"
assert marker in c, f"emscripten-modular: '{marker}' not found in {path}"
assert "MODULARIZE=1" not in c, f"emscripten-modular: {path} already patched"
c = c.replace(
    marker,
    marker + " -s MODULARIZE=1 -s EXPORT_ES6=1 -s INVOKE_RUN=0",
    1,
)

c, n = re.subn(
    r'\$\(if \$\(ENABLE_QT6\),.*?\]',
    ',"callMain","FS","ENV"]',
    c,
)
assert n >= 1, f"emscripten-modular: ENABLE_QT6 export block not found in {path}"

open(path, "w").write(c)
print(f"Patched {path} ({n} export block(s) rewritten)")

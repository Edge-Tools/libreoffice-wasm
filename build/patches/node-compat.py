#!/usr/bin/env python3
"""
Post-process soffice.mjs for Node.js compatibility.

LibreOffice's emscripten output targets browsers/browser-workers. Three
constructs break when the module is driven from Node.js:

1. runUnoScriptUrls — calls importScripts() which does not exist in Node.js
   ES-module workers. The urls array passed at runtime is always empty for
   the headless CLI build, so the call is a safe no-op we can skip.

2. LOWA-channel postMessage — the main thread transfers a MessagePort via
   the transfer list: postMessage({cmd:"LOWA-channel"}, [port]).
   Browsers expose transferred ports as event.ports[0]; Node.js worker_threads
   does not surface them there. Include the port in the data object so the
   worker can find it.

3. setupMainChannel receiver — reads e.ports[0] (always undefined in Node.js).
   Fall back to e.data.port which is set by patch 2.
"""
import sys

path = sys.argv[1]
c = open(path).read()

old1 = (
    'function runUnoScriptUrls(handle)'
    '{globalThis.Module=globalThis.Module||Module;'
    'importScripts.apply(self,Emval.toValue(handle))}'
)
new1 = (
    'function runUnoScriptUrls(handle)'
    '{globalThis.Module=globalThis.Module||Module;'
    'const urls=Emval.toValue(handle);'
    'if(urls.length&&typeof importScripts!=="undefined")'
    '{importScripts.apply(self,urls)}}'
)
assert old1 in c, f"patch 1 pattern not found in {path}"
c = c.replace(old1, new1, 1)

old2 = 'sofficeMain.postMessage({cmd:"LOWA-channel"},[channel.port2])'
new2 = 'sofficeMain.postMessage({cmd:"LOWA-channel",port:channel.port2},[channel.port2])'
assert old2 in c, f"patch 2 pattern not found in {path}"
c = c.replace(old2, new2, 1)

old3 = 'Module.uno_mainPort=e.ports[0]'
new3 = 'Module.uno_mainPort=(e.ports&&e.ports[0])||e.data.port'
assert old3 in c, f"patch 3 pattern not found in {path}"
c = c.replace(old3, new3, 1)

open(path, "w").write(c)
print(f"Patched {path}")

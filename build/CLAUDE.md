# libreoffice-wasm

Headless LibreOffice compiled to WebAssembly for server-side document-to-PDF
conversion. Follows the same project conventions as the sibling tools at
`edge-tools/wasm/{ghostscript,jq,php,python}` but has several important
differences documented below.

GitLab remote: `git@gitlab.com:edge-tools/wasm/libreoffice.git`

---

## Artifacts

The build produces **three** files (not two like other tools):

| File | Size (approx) | Purpose |
|---|---|---|
| `dist/soffice.mjs` | ~1 MB | ES6 module — the entry point for consumers |
| `dist/soffice.js` | ~1 MB | Same file; required by emscripten pthread workers at runtime |
| `dist/soffice.wasm` | ~80–150 MB | Compiled LibreOffice binary |
| `dist/soffice.data` | ~100–500 MB | Emscripten preloaded FS image — fonts, templates, filters |
| `dist/soffice.data.js.metadata` | ~few KB | Chunk manifest for the data loader (required in emscripten 3.x) |

All five files are **essential** and must be co-located. `soffice.js` and
`soffice.mjs` are identical copies — workers load `soffice.js` by that hardcoded
name, while consumers `import Module from './dist/soffice.mjs'`.

The `.js` extension is kept in the emscripten platform makefile (not changed to
`.mjs`) to avoid breaking install rules for other build tools (`uri-encode`,
`unoidl-read`) that GBuild re-processes during the build.

---

## How the build works

Unlike jq/ghostscript/PHP, LibreOffice cannot be built with a simple
`emconfigure ./configure && emmake make`. It has its own cross-compilation
infrastructure:

- Base image is **`ubuntu:22.04`** (not `emscripten/emsdk`) because LO needs
  many more apt packages than the emsdk image provides.
- emsdk **3.1.71** is installed manually (consistent with other tools in this
  repo). Emscripten 3.1.30 was the originally documented version for headless
  WASM; 3.1.71 is a compatible upgrade.
- Source is the official Document Foundation release tarball, verified against
  a pinned SHA-256 (`SOURCE_SHA256` in the Dockerfile) before unpacking:
  `https://download.documentfoundation.org/libreoffice/src/<X.Y.Z>/libreoffice-VERSION.tar.xz`
  (a stable hash, unlike GitHub's auto-generated archives).
- Configure is plain `./autogen.sh` (no `emconfigure` wrapper) — LO detects
  emscripten from `PATH` automatically when `--host=wasm32-local-emscripten` is
  given.
- Build is plain `make -j$(nproc)`. LO downloads and cross-compiles its own
  external dependencies (boost, icu, libxml2, etc.) during this step.
- **Expected build time: 2–6 hours** on a fast machine (32+ cores). The link
  step can require up to 64 GB of RAM.

### Configure flags used

```
--disable-debug
--enable-sal-log
--disable-crashdump
--host=wasm32-local-emscripten
--disable-gui
--with-wasm-module="writer calc impress"   ← Writer, Calc and Impress/Draw
--without-java
```

`--with-wasm-module="writer calc impress"` builds all three application
sub-modules, so docx/odt/rtf, xlsx/ods/csv and pptx/odp/odg documents can all
be converted. Draw shares the `sd` module with Impress, so `impress` covers
drawings too. Restricting it to `writer` produces a smaller binary but only
loads word-processor documents — anything else fails with "source file could
not be loaded". The default in 26.x is `calc writer`.

Note: the flag was renamed across versions — `--with-wasm-module` (original and
26.x+), `--with-main-module` (24.x only). `--with-package-format=emscripten` is
not a valid option in any recent version; the data file is produced automatically
by the Emscripten `file_packager` tool during `make`.

---

## The emscripten platform patch

LibreOffice's `solenv/gbuild/platform/EMSCRIPTEN_INTEL_GCC.mk` defaults to:
- Output extension `.js` (non-modular CommonJS-style global Module)
- `callMain` and `FS` only exported when building with Qt6 GUI

`patches/emscripten-modular.py` patches this file immediately after the source
is extracted in the Dockerfile. It makes two changes:

1. Appends `-s MODULARIZE=1 -s EXPORT_ES6=1 -s INVOKE_RUN=0` after
   `-s EXIT_RUNTIME=0`
2. Replaces the Qt6-conditional export list with an unconditional set:
   `callMain, FS, ENV`

To verify the patch still applies cleanly after a LO version bump, run:

```bash
# Download the makefile for the new version and dry-run the patch
gh api 'repos/LibreOffice/core/contents/solenv/gbuild/platform/EMSCRIPTEN_INTEL_GCC.mk' \
    --jq '.content' | base64 -d > /tmp/test.mk
python3 patches/emscripten-modular.py /tmp/test.mk
grep -E "MODULARIZE|INVOKE_RUN|callMain" /tmp/test.mk
```

### Node.js compatibility patch

`patches/node-compat.py` post-processes `dist/soffice.mjs` after the build
(and syncs it to `dist/soffice.js`). It fixes three browser-only constructs:

1. **`runUnoScriptUrls`** — LO calls `importScripts()` (browser Worker API) to
   load UNO scripts. The URL list is always empty for the headless CLI build, so
   the fix guards on `urls.length` and `typeof importScripts !== "undefined"`.

2. **LOWA-channel sender** (ASM_CONSTS) — the main thread transfers a
   `MessagePort` via `postMessage({cmd:"LOWA-channel"}, [port])`. Browsers
   expose it as `event.ports[0]`; Node.js worker_threads does not. The fix
   includes the port in the data object: `{cmd:"LOWA-channel", port:port}`.

3. **`setupMainChannel` receiver** — reads `e.ports[0]` (always `undefined` in
   Node.js). The fix falls back to `e.data.port` which is set by fix 2.

Additionally, the **JavaScript API** consumer (test or app code) must polyfill
`globalThis.location` before loading the module — LO's UNO layer reads
`globalThis.location.href` to resolve its base URL, which is `undefined` in
Node.js:

```js
import { pathToFileURL } from 'node:url';
if (!globalThis.location) {
  globalThis.location = { href: pathToFileURL('/path/to/dist/soffice.mjs').href };
}
import Module from './dist/soffice.mjs';
```

After verifying conversion success, call `process.exit(0)` — `EXIT_RUNTIME=0`
keeps Worker threads alive, so the Node.js process never drains its event loop
on its own.

---

## JavaScript API

```js
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

// Must be set before loading the module — LO's UNO layer reads location.href.
if (!globalThis.location) {
  globalThis.location = { href: pathToFileURL(path.resolve('dist/soffice.mjs')).href };
}

import Module from './dist/soffice.mjs';

const mod = await Module({
  wasmBinary: fs.readFileSync('dist/soffice.wasm'),
  locateFile: (name) => path.join('dist', name),   // auto-loads soffice.data
  noInitialRun: true,
  print:    (line) => console.log(line),
  printErr: (line) => console.error(line),
  preRun: [(m) => {
    m.FS.mkdir('/lo-home');
    m.ENV['HOME'] = '/lo-home';          // writable user-profile directory
    m.FS.writeFile('/input.docx', new Uint8Array(inputBytes));
    m.FS.mkdir('/output');
  }],
});

// With PROXY_TO_PTHREAD, callMain returns immediately while main() runs on a
// Worker thread. Poll MEMFS until the output file appears (FS ops from the
// worker are proxied to the main thread and become visible on each await).
mod.callMain([
  '--headless',
  '--norestore',
  '--convert-to', 'pdf',
  '--outdir', '/output',
  '/input.docx',
]);

const deadline = Date.now() + 120_000;
while (!mod.FS.analyzePath('/output/input.pdf').exists) {
  if (Date.now() > deadline) throw new Error('timeout waiting for PDF');
  await new Promise(r => setTimeout(r, 500));
}

// Output is at /output/input.pdf (same basename as input)
const pdfBytes = mod.FS.readFile('/output/input.pdf');

// EXIT_RUNTIME=0 keeps Worker threads alive; call process.exit() when done.
process.exit(0);
```

`callMain` proxies `main()` to a pthread Worker and returns 0 immediately — the
conversion happens asynchronously. Poll MEMFS for the output file to detect
completion. Because `EXIT_RUNTIME=0` is set, the Node.js process will not exit
on its own; call `process.exit(0)` when finished.

Do not call `callMain` a second time on the same module instance — LO's UNO
runtime is torn down after the first exit.

---

## Version bump

Three places need updating:

1. `Dockerfile` — `ARG VERSION=...`
2. `Dockerfile` — `ENV SOURCE_SHA256=...` (the new tarball's hash)
3. `.gitlab-ci.yml` — `LO_VERSION: "..."`

Available versions are listed under
`https://download.documentfoundation.org/libreoffice/src/`. Fetch the matching
hash from the tarball's `.sha256` companion file, e.g.:
```bash
curl -fsSL https://download.documentfoundation.org/libreoffice/src/26.2.2/libreoffice-26.2.2.2.tar.xz.sha256
```

After bumping, re-verify the emscripten patch (see above) before triggering CI.

---

## CI requirements

The pipeline is `build → test → publish`, using the standard DinD pattern from
other tools in this repo. Critical differences:

- `timeout: 6h` on the build job — LO takes 2–4 hours even on fast runners.
- **Self-hosted runner required.** GitLab SaaS shared runners will time out and
  may not have enough RAM (linking needs up to 64 GB).
- The `test` job runs `test/test.mjs` against the freshly built module and
  gates `publish` — a build that dropped a sub-module fails here.
- `publish` is idempotent: it deletes the package for `LO_VERSION` before
  uploading, so re-running a pipeline for the same version does not fail on a
  duplicate.
- All four artifacts (`soffice.wasm`, `soffice.mjs`, `soffice.data`,
  `soffice.data.js.metadata`) are uploaded to the GitLab package registry
  under `libreoffice-wasm/<LO_VERSION>/`.

---

## Local build

```bash
./run-local.sh          # builds and extracts dist/ (~2–6 hours)
node test/test.mjs      # runs the smoke test (requires dist/ to be populated)

# Or both in one shot:
./run-tests.sh
```

Pass a different version: `VERSION=25.2.6.1 ./run-local.sh`

---

## Known limitations / next steps

- **Module scope**: the build includes Writer, Calc and Impress/Draw
  (`--with-wasm-module="writer calc impress"`). Dropping a module shrinks the
  binary but makes that document class fail with "source file could not be
  loaded".
- **Single use per instance**: `callMain` can only be called once. For a
  multi-document service, spawn a fresh `Module(...)` per conversion.
- **soffice.data size**: Hundreds of MB. Consider serving it separately via CDN
  (see `edge-tools/wasm/cdn`) rather than bundling it with each consumer.
- **Emscripten compatibility**: If a newer LO version requires emscripten 4.x,
  change `3.1.71` in the Dockerfile to `4.0.10` (the version LO's GUI builds
  target as of early 2025) and re-verify the platform patch.

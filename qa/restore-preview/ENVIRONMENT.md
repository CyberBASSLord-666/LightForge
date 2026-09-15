# Completed-project preview startup repair

The Android job `104250112441` in run `34926066282` completed and saved the
background show. Reopening reached the full vehicle's first draw: the two
PMREM `sigmaRadians` warnings at 04:24:17 establish that model loading and rig
assembly had already finished. The last `modelReady=false` probe was stale.
The graphics queue then stalled before a frame committed; the existing
45-second startup watchdog retired the renderer at 04:24:55.

The four fixed studio lighting cards and background are now convolved once
by the pinned Three.js r180 generator. The resulting complete 768 × 1024
CubeUV atlas retains all roughness levels and every RGBA half-float word.
Its 6,291,456 bytes compress losslessly to 575,287 bytes. The source scene,
generator, lockfile hash, texture metadata and both asset hashes are retained.
The app uploads these values directly; context recovery uploads the same
values again. It no longer creates dozens of lighting-convolution render
passes on Android before the first frame.

The model, lighting values/intensities, shadow maps, material response, bloom,
output pass and selected raster quality remain the same. The original
first-frame, native visual-commit and completed-job acknowledgement checks
are unchanged. A missing, corrupt, truncated or oversized atlas fails model
readiness. There is no fallback to the blocking convolution.

## Reproduce

Install the project's pinned development dependencies with `npm ci`. Install
the pinned graphics package/lockfile under `../toolchain/graphics`, as described
by `tools/build_preview.mjs`; alternatively set `LF_GRAPHICS_NODE_MODULES` to
that graphics installation. Both tools use Playwright's installed Chromium;
`PLAYWRIGHT_EXECUTABLE_PATH` can select an installed browser explicitly.

```sh
node tools/bake_preview_environment.cjs --check
node qa/restore-preview/environment.cjs
node --test tests/preview-environment.test.cjs tests/preview-startup.test.cjs tests/preview-lifecycle.test.cjs tests/completed-restore-preview-start.test.cjs
```

Omit `--check` only when intentionally regenerating the asset and its metadata.
The bake check compares all raw half-float bytes. It can detect GPU/compiler
rounding differences on a different rendering stack; review those differences
and the complete rendered comparisons before replacing the committed asset.
Rebuild the offline preview bundle with `node tools/build_preview.mjs` after
editing its source.

The retained `environment-result/verification.json` is a desktop Chromium
153.0.8010.0 SwiftShader check. The complete vehicle produced zero differing
RGBA components against the original live PMREM for studio/front/high,
night/rear/high, studio/cabin/balanced and night/driver/battery. It also records
an actual WebGL context-loss/recovery cycle and the first recovered full frame.
This is visual-equivalence evidence, not Android or release qualification.
The complete Android lifecycle workflow must still pass on the candidate.

The subsequent PR and main Android runs still exceeded startup deadlines. On
main, the application did render and acknowledge the completed show, but too
late for the instrumentation's additional hardware-frame callback. Six fixed
`preview-startup` diagnostic markers now separate graphics initialization,
GLTF loading, atlas decoding, rig assembly and the first full compositor's
start/end. `elapsedMs` uses the preview's monotonic creation time; `durationMs`
measures the indicated operation (GLTF and atlas both begin with model loading).
The compositor duration measures synchronous submission, independently of the
later native hardware-frame callback. Only numeric timings and fixed phase
names are logged, once per preview lifetime. These observations add no timing
allowance and do not alter loading, drawing, quality or acknowledgement checks.

The decoder/provenance regression is part of `tools/verify_v2.py`; the asset and
metadata are also included in the browser evidence's source inventory.

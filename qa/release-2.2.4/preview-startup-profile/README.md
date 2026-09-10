# Preview startup timing investigation

This evidence investigates scheduling during a completed-project reopen. It is a desktop Chromium SwiftShader profile and a separate CPU-only rig audit, not an Android benchmark, release timing gate, or justification for changing an Android deadline. Production code, model assets, settings, and quality presets are unchanged.

## Retained observations

`timing-original.json` is the original raw browser result, preserved byte-for-byte. `profile-preview-startup-original.cjs` is the scratch script that produced it. In its 4× CPU-throttled run:

- GLB fetch/parse took 875.44 ms and synchronous rig construction took 229.94 ms.
- The first preview draw took 980.82 ms to submit; its enclosing main-thread long task lasted 2,953 ms.
- The actual restore worker emitted first progress and its final result 53.69 ms apart. The result reached the main thread 3,242.38 ms after emission. The interval excludes worker startup/imports before first progress.
- Both browser runs restored the expected frame hash `16d1afe9543aba85cc19fbffdda019d68b395288fa3fa129bb3bb8d5f5749351`.

The result demonstrates that `composing=true` can remain visible while a completed worker result awaits UI delivery. It does not establish the cause or duration of the Android stall. The Android probe's last `modelReady=false` response can also be stale while later graphics work is running.

`rig-build-count-audit-original.json` and its original script preserve the separate Node audit. The builder processed 684 source meshes, transformed/cloned 600 static geometries, merged them into 11 groups, and produced 105 final meshes. Its measured build time was 118.50 ms. Texture decoding is explicitly stubbed in this audit; it measures geometry work and operation counts, not visual rendering or shader compilation. Identity transforms still normalize normals, so these counts do not establish that transforms can safely be removed.

## Reproduce

Install the repository's pinned development dependencies with `npm ci`. Install the graphics dependencies using the pinned `web/preview/src/package.json` and lockfile, following `tools/build_preview.mjs`; the default graphics directory is `../toolchain/graphics/node_modules` relative to the repository. `LF_GRAPHICS_NODE_MODULES` may point to an equivalent installation of those pinned dependencies.

Run the portable browser probe from any working directory:

```sh
node /path/to/LightForge/qa/release-2.2.4/preview-startup-profile/profile-preview-startup.cjs /path/to/new-output-directory
```

It uses Playwright's installed Chromium. Set `PLAYWRIGHT_EXECUTABLE_PATH` if the pinned local browser is installed elsewhere. It runs one unthrottled and one 4× CPU-throttled observation, preserves source/model/settings behavior, and asserts the final frame hash and one worker result. The 60-second local wait bounds this investigation; it is not a replacement for the Android readiness test. Timing-only wrappers record method entry/exit and add an emission timestamp to actual worker messages. A temporary bundle is built outside production output. Omitting the output argument creates a new temporary directory.

Run the portable rig audit similarly:

```sh
node /path/to/LightForge/qa/release-2.2.4/preview-startup-profile/rig-build-count-audit.mjs /path/to/new-output-directory
```

The `*-portability.json` files contain separate validation runs of the portable scripts. Their timings are not substituted into the original observations. `manifest.json` binds retained evidence and the current relevant sources by SHA-256; original raw results were not retroactively rewritten to add metadata.

The useful next Android measurements are GLB fetch/parse completion, rig start/end, assignment of `loaded`, first draw start/end, and worker-result emission versus main-thread delivery. These observations alone do not justify a production rendering rewrite, lowered quality, or a relaxed test predicate.

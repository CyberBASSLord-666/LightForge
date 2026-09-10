# Preview startup verification

`verification.json` binds the current source, renderer bundle, unchanged model,
saved-show fixture, comparison script, and previous renderer extracted from the
pre-change signed 2.2.4 APK. The previous bundle SHA-256 is
`1129ac95eedbb49b2a0688566276dce897e8f59d26704c115a92ec7bf3ca3034`.

Run from the project root:

```sh
node qa/release-2.2.4/compare-preview-startup.cjs
```

Set `PLAYWRIGHT_EXECUTABLE_PATH` only when using an externally installed Chromium.
The test holds the actual GLB request while the actual saved show is restored.
The previous renderer generates its lighting texture and submits empty frames;
the new renderer performs neither operation until the model is loaded and visible.

After releasing the request, both renderers use the same front camera and show
position (24.137 seconds). Studio and Night, selected before loading completes,
produce identical canvas PNG bytes, output snapshots, graphic settings, and
compiled-show checksums. Both pairs of images are retained.

This proves removal of redundant startup work and unchanged final output on these
two cases. It is not an Android performance benchmark or evidence that the Android
readiness timeout has been resolved.

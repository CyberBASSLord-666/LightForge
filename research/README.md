# Reproducing the music engine and its checks

The shipped mobile runtime is entirely under `../web/analysis`. Nothing in this
research directory is required on the phone. Curated original model code, weights,
filterbank implementation and licenses are under `upstream/`, so the ONNX export
can be reproduced without refetching upstream repositories.

Build dependencies: Python 3 with CPU PyTorch, NumPy, SciPy, ONNX and ONNX Runtime.
Test dependencies also include soundfile, Node 20+, and the original corrected stereo
44100 Hz `lightshow.wav`. No paid service is used.

```sh
python3 export_beatnet.py
python3 test_analysis_reference.py /absolute/path/to/lightshow.wav
node test_dsp.cjs
node test_ort_wasm.cjs
node test_worker_node.cjs
```

The first reference test writes temporary audio/feature fixtures here. The worker test
serves the WAV with actual HTTP Range requests and exercises the production worker,
feature extraction, trained model, beat decoder, sections and result interface using
the packaged WebAssembly runtime. Node requires one test-only remapping of the WASM
module URL to a filesystem path. This test does not claim to replace the separate
Android WebView loading and end-user UI smoke checks.

Verified on the supplied 238.04-second Glass Castle music:

- JavaScript feature maximum absolute difference from Python: 8.20e-8.
- Packaged WASM probability difference from CPU ONNX: 1.49e-7 over 80 reference frames.
- 93.08 BPM; 368 beats; 92 downbeats; meter estimate 4; heuristic confidence 0.9404.
- 12 contiguous sections covering the entire track; 6250 sensitive band onset markers.
- 26 HTTP Range requests; largest audio read 442,940 bytes.
- Full analysis: 25.3 seconds on this workspace CPU. Phone performance varies.
- Invalid audio rejects with an actionable message; silence returns no invented beat.

Machine-readable result: `analysis_verification.json`. The full analyzed music object
is `glass_castle_analysis.json`, useful for generator regression checks. These are
measurements from actual inference, not synthetic or song-specific beat fixtures.

`upstream/BeatNet` is from commit 81cedd4beeb7235262db80969a0c9ce9a48a0ed4;
`upstream/madmom` is from 27f032e8947204902c675e5e341a3faf5dc86dae.
Upstream links and the explanation of modifications are in
`../web/analysis/README.md`. Runtime files come from the npm package
`onnxruntime-web@1.20.1` (`dist/ort.wasm.min.js`,
`dist/ort-wasm-simd-threaded.mjs`, `dist/ort-wasm-simd-threaded.wasm`).

Real browser verification also passed on Chromium 131.0.6778.204 with the production
Worker, same-origin scripts and a restrictive CSP. It analyzed the complete track,
kept the main thread responsive, delivered monotonic progress, supported immediate
cancellation, rejected invalid audio and handled silence. No page errors occurred.
The full suite completed in 23.1 seconds. See `browser_verification.json`.

```sh
node test_browser_worker.cjs /absolute/path/to/chrome-headless-shell
```

Temporary `test_audio22050.*` files contain resampled copies of the supplied song and
can be excluded from a source archive; regenerate them with the reference test above.

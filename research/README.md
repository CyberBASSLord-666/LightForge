# Research sources and historical BeatNet checks

Use [BUILD.md](../BUILD.md) for current model reproduction and verification,
[ASSETS.md](../ASSETS.md) for pinned sources and distribution terms, and
[VALIDATION.md](../VALIDATION.md) for evidence that applies to a named release.
The shipped analysis runtime is under [web/analysis](../web/analysis/).
This directory retains model sources, conversion inputs, licenses and research
records; it is not an additional APK payload.

## Historical BeatNet experiment

The commands and measurements below describe the original BeatNet-based
experiment, before the current Beat This! rhythm path and the later separation,
vocal and choreography stages. They do not reproduce or qualify the current
complete analysis pipeline. Retained receipts and failed investigations remain
historical evidence with their original scope.

Curated BeatNet code, weights and the madmom filterbank implementation remain
under `upstream/`. Run the historical exporter only in an isolated checkout:
it writes fixed model paths under `web/analysis/models/`, and the reference test
writes temporary fixtures under `research/`.

Build dependencies: Python 3 with CPU PyTorch, NumPy, SciPy, ONNX and ONNX Runtime.
Test dependencies also include soundfile, Node 20+, and the original corrected
stereo 44100 Hz `lightshow.wav`. Supply its actual local path to the reference
test; the script's old default workspace path is not a bundled fixture.

```sh
python3 export_beatnet.py
python3 test_analysis_reference.py /absolute/path/to/lightshow.wav
node test_dsp.cjs
node test_ort_wasm.cjs
node test_worker_node.cjs
```

The first reference test writes temporary audio/feature fixtures here. The historical
worker test serves the WAV with actual HTTP Range requests and exercises the worker,
feature extraction, trained model, beat decoder, sections and result interface using
the packaged WebAssembly runtime. Node requires one test-only remapping of the WASM
module URL to a filesystem path. This test does not claim to replace the separate
Android WebView loading and end-user UI smoke checks.

The retained [analysis receipt](analysis_verification.json) records these
observations on the supplied 238.04-second Glass Castle music:

- JavaScript feature maximum absolute difference from Python: 8.20e-8.
- Packaged WASM probability difference from CPU ONNX: 1.49e-7 over 80 reference frames.
- 93.08 BPM; 368 beats; 92 downbeats; meter estimate 4; heuristic confidence 0.9404.
- 12 contiguous sections covering the entire track; 6250 sensitive band onset markers.
- 26 HTTP Range requests; largest audio read 442,940 bytes.
- Historical BeatNet worker analysis: 25.3 seconds on the experiment's workspace CPU.
- Invalid audio rejects with an actionable message; silence returns no invented beat.

The full historical analyzed music object is
[glass_castle_analysis.json](glass_castle_analysis.json). These records are
retained measurements of that experiment, not current release receipts or
comparative musical-quality evidence.

`upstream/BeatNet` is from commit 81cedd4beeb7235262db80969a0c9ce9a48a0ed4;
`upstream/madmom` is from 27f032e8947204902c675e5e341a3faf5dc86dae.
Upstream links and the explanation of modifications are in
[web/analysis/README.md](../web/analysis/README.md). Runtime files came from the npm package
`onnxruntime-web@1.20.1` (`dist/ort.wasm.min.js`,
`dist/ort-wasm-simd-threaded.mjs`, `dist/ort-wasm-simd-threaded.wasm`).

The retained [browser receipt](browser_verification.json) records a pass on
Chromium 131.0.6778.204 with the then-production worker, same-origin scripts and a
restrictive CSP. It analyzed the complete track,
kept the main thread responsive, delivered monotonic progress, supported immediate
cancellation, rejected invalid audio and handled silence. No page errors occurred.
The receipt records 20.683 seconds for that browser suite. It does not establish
current browser, Android-device or whole-analysis performance.

```sh
node test_browser_worker.cjs /absolute/path/to/chrome-headless-shell
```

Temporary `test_audio22050.*` files contain resampled copies of the supplied song and
can be excluded from a source archive; regenerate them with the reference test above.

# Analysis version 2 verification — LightForge 1.3.0

The production analyzer retains the bundled BeatNet model and its exact feature geometry. The new interpretation adds local tempo, explicit bar positions, a true manual-tempo grid, nearby PCM attack alignment, fast energy, activity ranges, phrases and prominent impacts. It does not retrain the model or add a network dependency.

## Evidence

- Twelve deterministic decoder tests pass: fractional tempo, triple-meter pickup, quiet rest/restart, tempo change and acceleration, silence, exact manual BPM, sample-clock continuity across worker chunks, preserved silent intro/outro, uncertain meter, adversarial neural activations over silence, bounded timing corrections, and attack suppression spacing.
- Production worker/ONNX inference succeeds on the 64-second demo and valid 238.04-second resampled Sample.wav. All seven original neural/spectral descriptors match the frozen 1.2.0 results exactly. Beats remain 99 and 369 respectively. The new outputs include 7/27 phrases and 24/75 impact candidates, with the original audio clock preserved.
- An independently generated, annotated 47.1-second percussion/chord WAV passes through actual BeatNet inference. Both versions retain all 96 annotated beats. The new decoder estimates 124.49 BPM for 124.5 BPM audio. Median beat-time error improves from 10.71 ms to 1.98 ms; the 95th percentile improves from 19.87 ms to 4.20 ms.
- The same synthetic arrangement exposes a retained model limitation: its inferred downbeats are half a bar away from the authored chord-cycle phase. The result identifies 4/4 but does not guarantee the correct bar phase. Meter confidence is a heuristic strength score, not a calibrated accuracy probability.

The smaller controlled decoder fixtures use deliberately constructed neural activations and known PCM-envelope transients. They isolate the decoder's behavior. The separate percussion/chord fixture uses the actual trained model. Real music has no expert beat annotations here, so its checks establish pipeline behavior and numerical parity, not an independently measured timing-accuracy score.

No phone audio-output latency, Tesla lamp response, motor travel or physical show synchronization was measured. The 5 ms envelope is an analysis resolution; the exported frame interval and vehicle behavior impose additional limits.

## Reproduce

From `app/lightforge`, with the existing toolchain and valid Sample.wav converted to `/tmp/lightforge-1.2.0-baseline/sample.wav`:

```sh
python3 qa/music-1.3.0/make-audio-fixture.py
node qa/music-1.3.0/test-analysis.cjs
node qa/music-1.3.0/capture-analysis.cjs demo sample synthetic
node qa/music-1.3.0/verify-real-analysis.cjs
```

The final command merges the checks into `analysis-verification.json`, including exact production source/model hashes. Baseline and current feature captures are retained for reproducible comparison. The capture harness only instruments its served worker response to return test features; it does not modify the packaged worker.

## Primary references

- BeatNet authors' source and documented model scope: https://github.com/mjhydri/BeatNet
- Ellis, *Beat Tracking by Dynamic Programming*: https://www.ee.columbia.edu/~dpwe/pubs/Ellis07-beattrack.pdf

These support the algorithm families. The adaptive decoder, PCM refinement and phrase/impact implementation are LightForge-specific changes, not claims of implementing the original BeatNet particle filter or its published benchmark performance.

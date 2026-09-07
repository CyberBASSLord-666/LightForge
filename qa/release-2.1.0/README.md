# 2.1 evidence and reproduction

These files distinguish model quality, conversion parity, musical-role behavior,
public-worker integration, UI behavior and physical-device limits. No reference
vocal stem is supplied to the production separator. No note result is represented
as human-annotated note accuracy.

Use the model-build Python environment from `BUILD.md`, with
`onnxruntime==1.24.3` and `soundfile==0.14.0` for reference evaluation. Prepare the
licensed MUSDB18 seven-second excerpts using the pinned archive and commands in
`.github/workflows/verify-v2.yml`. The archive and individual track attribution
are recorded in `musdb-fixture-provenance.json`.

With `EVIDENCE` set to a temporary output directory and `CHECKPOINT` pointing to
the verified official Deux checkpoint, the numeric path is:

```bash
python qa/release-2.1.0/evaluate-separation.py --checkpoint "$CHECKPOINT" --output "$EVIDENCE"
python qa/release-2.1.0/verify-conversion.py --checkpoint "$CHECKPOINT" --output "$EVIDENCE"
node qa/release-2.1.0/probe-separator.cjs "$EVIDENCE"
node qa/release-2.1.0/evaluate-roles.cjs "$EVIDENCE"
node qa/release-2.1.0/test-source-clock.cjs
python qa/release-2.1.0/verify-analysis.py --evidence-dir "$EVIDENCE"
```

The original evidence was gathered before paths were adapted into the portable
probes; `reference-evaluation-capture.txt` and `wasm-evaluation-capture.txt` retain
those exact executed scripts. Every original staged graph was compared byte for
byte with the published model manifest. The actual public worker is tested
independently using `node qa/release-2.1.0/analysis-browser.cjs` in Chromium.

The first role pass ran GAME inference on all 18 estimated vocal sources. One
controlled short singing passage exposed weak general classifier scores. The
final implementation can use independent GAME/source-pitch agreement while
retaining the existing prominence, duration and speech gates. The classifier,
source detail and final fusion were then rerun on all 18 estimates. Unchanged
GAME predictions were reused with exact input and model/adapter hashes; the
`transcriptionReused` flag makes this explicit. No thresholds were selected per
song, and no reference annotation enters this decision.

All six natural-mixture SI-SDR values improved. The controlled-remix leakage
metric is worse than historical MDX (0.237% vs 0.059% mean outside-window vocal
energy), while source SI-SDR/envelope tracking improved. This tradeoff is retained
in `analysis-verification.json` and `VALIDATION.md`.

The source-clock probe uses neutral masks and fake sessions to isolate actual
STFT/scatter/ISTFT and overlap scheduling. Its four-window round trip is not a
neural-model benchmark. UI screenshots use the real app, WebGL and workers with
a simulated Android bridge. Phone installation, long-track thermals/memory,
Android provider behavior and actual Tesla lamp/motor timing remain unmeasured.

# Offline music intelligence, LightForge 1.6.0

`MusicAnalyzer.analyze(audioUrl, options, onProgress, signal)` returns analysis version 5.
All models, frontend coefficients and ONNX Runtime WebAssembly are bundled in the APK.
No account, API key, remote inference, runtime model downloads or subscriptions are used.

## Actual neural models

The rhythm pipeline uses **Beat This!**, the
transformer beat/downbeat tracker by Francesco Foscarin, Jan Schlüter and Gerhard
Widmer, published at ISMIR 2024. Its full and compact pretrained models are available
without configuration:

| Setting | Checkpoint | ONNX bytes | Behavior |
| --- | --- | ---: | --- |
| `precision` (default) | `final0` | 83,162,650 | Full transformer, more processing and memory |
| `balanced` | `small1` | 10,555,592 | Compact transformer, less processing and memory |
| Shared frontend | Log-mel graph | 270,742 | 128 Slaney mel bands; 22050 Hz; 1024 FFT; 441 hop; magnitude/32; log1p(1000*x) |

Both are real pretrained networks; they are not names for DSP presets. The APK includes
both. The browser uses one model at a time, up to four isolated WASM threads and bounded overlapping
30-second context windows. Six frames at each prediction edge are discarded, following
the upstream inference layout. Earlier overlap predictions are retained. PCM is read
with an additional STFT halo, so chunks do not introduce false spectrogram boundaries.
The two-second digital-silence regression skips model loading and produces no beats.

- Original implementation and model license: https://github.com/CPJKU/beat_this (MIT).
- Paper: https://arxiv.org/abs/2407.21658 . Its published benchmark is research evidence,
  not a benchmark of LightForge or a guarantee for every piece of music.
- ONNX conversion distribution: https://github.com/danigb/beat-this-rs . Small model
  and frontend pinned to commit `089b509247e6fdcec666511c0dcf0d5f39c21e73`.
- Full model: `model-large` release, SHA256 verified against the publisher's sidecar.
- All three packaged hashes and model IDs: `models/model-manifest.json`.
- Original and conversion copyright notices are retained in `models/BeatThis-LICENSE.txt`
  and `models/BeatThis-ONNX-Port-LICENSE.txt`.
- ONNX Runtime Web 1.20.1: MIT, unchanged bundled WASM/runtime/glue.
- Older BeatNet assets and sources remain for historical regression/conversion evidence;
  the production worker does not run BeatNet.

## Separated voice and accompaniment, analysis version 5

The full/compact rhythm choice stays independent. After rhythm/structure extraction,
release its two sessions and read the **original stereo 44.1 kHz** soundtrack.
The mono analysis proxy must never be fed to the stereo separator.

**UVR MDX-Net Voc FT** is an unchanged 66,762,490-byte pretrained ONNX model,
SHA-256 `534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111`.
It receives complex spectra from the exact trained 7,680-point FFT, 1,024-sample
hop, 3,072 frequency bins and 256 time frames. A mixed-radix transform is checked
against the original PyTorch geometry. Both polarity predictions are combined,
then inverse STFT, compensation 1.021 and complementary 50% segment crossfades
produce a continuous voice estimate. Accompaniment is the input minus voice.
No latency shift, time stretch or beat snapping is applied.

- Primary implementation/license: https://github.com/Anjok07/ultimatevocalremovergui
- Weights: https://github.com/TRvlvr/model_repo/releases/tag/all_public_uvr_models
- Parameters: https://github.com/TRvlvr/application_data/blob/main/mdx_model_data/model_data.json
- Credit UVR developers Anjok07 and aufr33; MDX-Net architecture by KUIELab.
- Exact weights, configuration, references and notices: `models/separator-mdx-model.json`.

Stereo estimates are averaged for vocal detail and audition and streamed through
a centered 63-tap low-pass filter into mono 22.05 kHz Float32 WAV caches in OPFS.
This preserves quiet detail without quantizing stems to PCM16. The private cache
uses contiguous validated writes, exact sample counts and atomic completion
metadata. It is replaceable and excluded from project backups. The original
stereo PCM16 soundtrack always remains the export audio. Evicted caches do not
invalidate saved frames or prevent exports; only isolated-layer audition needs
re-analysis.

Release the separator session before the singing/speech classifier.
**PretrainedSED Frame-MN10** supplies 40 ms singing and speech evidence over
10-second overlapping contexts on the isolated voice. Its original checkpoint,
MIT notice, class selection and exact frontend remain bundled. Primary source:
https://github.com/fschmid56/PretrainedSED . Raw singing and speech timelines are
transient; projects retain only compact musical detail and provenance.

`vocal-detail.js` consumes contiguous bounded voice/accompaniment chunks. It
measures local energy, source contrast, periodicity, articulation and estimated
pitch, using learned evidence to distinguish voice from remaining instrument
bleed. It returns phrases, articulation accents, estimated notes/holds, a 20 ms
envelope and a 40 ms pitch contour. Speech does not create sung pitch notes.
Quiet passages use local scaling with source/evidence guards, not whole-song
normalization alone. Confidence remains relative evidence, not a calibrated
probability. Lead/backing voices remain combined, and no lyric or word
transcription is claimed.

`bass-notes.js` follows low harmonic notes in the separated accompaniment.
Drums and other instruments remain present, so this is not isolated bass-source
identification. Its documented synthetic 40 ms ordinary onset / 50 ms offset
bounds and looser 80 ms closest overlapping-kick case are test-fixture results,
not guarantees for real songs.

`roleAnalysis.sourceSeparated` and `vocals.sourceSeparated` describe the actual
pipeline. `separation` records graph hash, overlap, polarity setting, source
clock and limitations. The 1.6 composer applies manual Voice/Instrumental guides
as an editing overlay without rewriting the model output or inventing pitch.

## Verification and scope

Current receipts, reference-fixture provenance and reproducible evaluation code
are in `qa/release-1.6.0/`. The selected separator is compared with official
MUSDB18 short multitrack excerpts, original vocal stems and known instrumental
or voice-window remixes. Timing, silence, nearby percussion, chunk boundaries,
cache playback, save/reload, migration and legal exported commands have separate
tests. Original source-stem component tests are clearly distinguished from
estimated-stem end-to-end tests.

The APK bundles all runtime assets and models and has no internet permission.
Model/frontend parity verifies implementation; it cannot establish universal
vocal or lyric accuracy. Dense/processed singing can remain ambiguous. Desktop
WASM and host JVM tests do not measure a physical phone or Tesla.

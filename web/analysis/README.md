# LightForge 2.1 offline music intelligence

`MusicAnalyzer.analyze(audioUrl, options, onProgress, signal)` returns analysis version 8.
Every runtime graph is bundled in the APK. Audio never leaves the device, and
there are no runtime downloads, keys, subscriptions or remote services.

| Stage | Studio (`precision`, default) | Balanced |
| --- | --- | --- |
| Rhythm and bar accents | Beat This! full | Beat This! compact |
| Stereo source separation | Mel-Band RoFormer Deux | UVR MDX-Net Voc FT |
| Singing/speech evidence | PretrainedSED Frame-MN10 | Same |
| Sung-note transcription | GAME Large 1.0.3 | Same |
| Bass notes | Harmonic tracking in vocal-separated accompaniment mixture (not a bass stem) | Same |

## Separation and original audio clock

Deux runs the author's full 13-second context, original checkpoint values as
Float32, 2,048-point centered STFT, 441-sample hop and both trained source heads.
The model is split into sequential ONNX sessions to bound working memory.
Attention query tiles retain the complete key/value context; there is no reduced
context, discarded layer or weight quantization. Ten-second owned regions retain
1.5 seconds of context on each side and overlap by five seconds with complementary
crossfades. Output sample counts equal the original 44.1 kHz source exactly.

Balanced mode retains the verified MDX pipeline: original stereo spectra,
7,680-point FFT, 1,024-sample hop, two polarity predictions, compensation 1.021,
normalized inverse STFT and complementary crossfades. Its accompaniment is the
original mix minus estimated voice. Neither mode applies reference-derived
latency correction, gain fitting, time stretching or beat snapping.

Both modes stream mono Float32 voice and accompaniment into private OPFS WAVs
at 22.05 kHz through the existing centered anti-aliasing filter. A separate
44.1 kHz Float32 voice WAV preserves the original source clock for GAME. This
cache needs approximately 21.2 MB per minute, is replaceable, and is omitted from
backups. Original stereo PCM16 audio remains the exported soundtrack. Aborted
jobs remove incomplete caches; missing caches do not invalidate saved shows.

## Neural singing and measured expression

Frame-MN10 supplies singing/speech evidence. The detail extractor measures
energy, source contrast and articulation on the actual estimated vocal waveform.
GAME Large predicts sung-note boundaries and pitch from that full-resolution
voice, with the author's eight diffusion steps and 0.2 thresholds. A supplied
seeded uniform-noise input replaces the graph's internal random operation;
original weights are unchanged. Twelve-second owned regions retain two seconds
of neighboring context. Carry-in notes are joined without inventing seam attacks.

GAME notes must overlap a supported non-speech phrase. A prominent separated source with weak general event-classifier scores can retain uncertain phrasing when GAME notes agree with independently measured periodic pitch; existing source-energy, duration and speech guards still apply. Classifier scores are never inflated. Speech and unsupported
regions cannot acquire sung-note gestures. Neural pitch and boundaries replace
acoustic note estimates; measured expressive energy and independent unvoiced
articulations remain. Confidence describes relative singing evidence, not a
calibrated GAME probability. Lead and backing singers remain combined. This is
singing-note transcription, not lyrics, exact word alignment or singer separation.

Bass tracking uses low-register harmonics in a vocal-separated accompaniment mixture.
The input has been separated from lead vocals, but it is not an isolated bass stem:
drums and other instruments remain, and real-song onset estimates can be ambiguous.
The semantic timeline records this as separated accompaniment context, never as
an isolated bass source.

## Rhythm, memory and cancellation

Beat This! retains the full/compact author models, exact log-mel frontend,
overlapping 30-second contexts and original-clock feature extraction. Frame
edges follow the upstream context policy. Earlier BeatNet assets remain only
for historical reproducibility. ONNX Runtime Web 1.20.1 is unchanged.

Sessions are released between stages. WASM may retain its peak allocation until
the disposable worker terminates. Studio processing can take much longer than
the soundtrack and needs several GB of working memory. Balanced is explicitly
selected by the user; failures do not silently switch models or fabricate results.
Keep the app open while analyzing. Abort terminates the worker and retries cache
cleanup while WebView releases its writable handles.

## Reproduction, licenses and evidence

`tools/prepare_deux.py` and `tools/prepare_game.py` verify pinned official source
archives/checkpoints and reproduce the graphs. `ASSET_MANIFEST.json` binds every
runtime file, graph, model manifest and notice. Builds reject missing, unexpected
or modified analysis assets. See `BUILD.md` at the repository root.

- Deux: [becruily](https://huggingface.co/becruily/mel-band-roformer-deux), weights
  CC BY-NC 4.0; architecture code from ZFTurbo/lucidrains and contributors, MIT.
- GAME: [openvpi](https://github.com/openvpi/GAME), original and modified models
  CC BY-NC-SA 4.0. Attribution and modification notice accompany the graphs.
- Beat This!: [CPJKU](https://github.com/CPJKU/beat_this), MIT; ONNX distribution
  [danigb/beat-this-rs](https://github.com/danigb/beat-this-rs), MIT.
- Frame-MN10: [PretrainedSED](https://github.com/fschmid56/PretrainedSED), MIT.
- MDX: [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui),
  notices, model parameters and checkpoint provenance remain bundled.
- ONNX Runtime: Microsoft and contributors, MIT.

Current runtime, parity and small reference-set results are in
`qa/release-2.1.0/`. Original vocal stems are scoring references, not production
separator inputs. Component tests using an original stem are labeled separately.
The six short MUSDB excerpts are not representative or verified held-out data;
training overlap is possible. Desktop WASM, parity and source-clock sample counts
do not establish human note accuracy or physical Android/Tesla performance.

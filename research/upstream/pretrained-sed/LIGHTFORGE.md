# Frame-MN10 singing analysis in LightForge 1.5

The app uses Florian Schmid and collaborators’ **PretrainedSED Frame-MN10 strong_1** checkpoint: a small convolutional sound-event model distilled from stronger models and trained using AudioSet’s timed event labels. This is a genuine pretrained neural model; no training or model service runs in the app. The core and original checkpoint are MIT-licensed. The exact repository commit and individual source hashes are in `source-receipt.json`.

Sources: [PretrainedSED authors’ repository](https://github.com/fschmid56/PretrainedSED), [published model release](https://github.com/fschmid56/PretrainedSED/releases/tag/v0.0.1). `export_lightforge.py` exports only the original strong head with sigmoid; training weights and label order are unchanged. The unused weak head is omitted by export. Rebuild with Python, PyTorch, torchvision, torchaudio, NumPy, ONNX and ONNX Runtime, then run the exporter from this directory. The exact locally verified package versions are recorded in the reference receipt; mobile uses bundled ONNX Runtime Web 1.20.1.

The frontend follows the author’s FrameMNWrapper: 16 kHz mono, preemphasis `[-0.97, 1]`, nonperiodic 400-sample Hann, centered 512-point FFT, 160-sample hop, 128 Kaldi mel bands from 0 to 7 kHz, power spectrum, log floor `1e-7`, normalization `(log_mel + 4.5) / 5`. Literal filter/window coefficients are exported from the reference. The browser’s bounded 64-tap resampler preserves global sample positions across chunks. ONNX input is fixed `[1,1,128,1000]`; output is `[1,447,250]` on 40 ms bins. Ten-second context overlaps by at least four seconds, with weighted averaging at seams and a tail window anchored to the audio’s last 40 ms bin. Only small current chunks and aggregated singing scores stay in memory.

The selected event classes cover generic, male, female and child singing, choir, chant, humming, mantra, yodeling, synthetic singing and rapping. Speech categories do not drive singing cues. Thresholds use raw model evidence (0.30 entrance, 0.16 continuation, at least 0.35 peak). The displayed confidence is an explicit relative evidence score, **not a calibrated probability of correctness**. Short score gaps may be grouped into one estimated region; these regions are not musical measures or individual sung notes.

Singing envelopes use the actual singing-event score, with supporting dynamics from the original mixture. Accent estimates additionally require a rising singing score, so a bass or drum transient alone cannot invent a vocal accent. Zero PCM has a separate gate and produces a zero envelope. The resulting 20 ms envelope does **not** imply 20 ms detection accuracy; the model has 40 ms output bins, substantial musical context, and unmeasured real-world boundary error. It does not separate stems, transcribe lyrics, track words or identify each sung pitch.

## Selection and verification

Google YAMNet was implemented and numerically checked first, then rejected for this feature because the real mixed folk singing fixture reached only 0.071 raw Singing score. EfficientAT mn10_as was independently evaluated and also performed poorly on short windows. Lowering arbitrary thresholds would have risked inventing vocals from accompaniment. Frame-MN10’s timed labels and specific singing categories provide materially better evidence on the checked recordings.

The production WASM model detects eight singing regions in the 60-second Karissa Hobbs mixed folk recording. Separate 60-second instrumental jazz, 14.84-second spoken narration, 30-second snare percussion and ten-second silence fixtures produce no singing regions. These are targeted regression examples, not a broad accuracy benchmark. The supplied Sample track is 238.04 seconds. The uploaded Glass Castle WAV is truncated; its separately decoded recoverable prefix is 121.749 seconds, which is the only portion evaluated. Neither file has hand-annotated singing boundaries, so observed detections are not claimed as ground-truth accuracy.

`qa/release-1.5.0/vocal-reference-verification.json` records ONNX agreement to original PyTorch (maximum absolute score error approximately `1.01e-6`). The production JS frontend agrees with the PyTorch frontend within `8.99e-5` absolute log-mel units. `vocal-inference-verification.json` records actual browser WASM runs. The independent timing/resampler audit checks chunk seams, output coverage, zeros, delay and short tails. Desktop run times do not establish Android performance, and physical Tesla execution has not been tested.

## Current retained source scope and recovery

The retained tree contains the Frame-MN10 exporter, local numerical evaluator,
architecture, frontend, literal class order, original checkpoint, notices and
source receipt. It is not a complete upstream training/demo checkout. Five
optional upstream inputs are omitted from current source:

| Relative path | Bytes | Upstream use |
| --- | ---: | --- |
| `hf_dataset_gen/metadata/audioset_train_strong.csv` | 36,221,392 | AudioSet training-dataset reconstruction |
| `hf_dataset_gen/metadata/audioset_eval_strong.csv` | 5,372,919 | AudioSet evaluation-dataset reconstruction |
| `resources/eval_durations.csv` | 315,018 | Upstream training/evaluation script |
| `test_files/752547__iscence__milan_metro_coming_in_station.wav` | 6,614,796 | Optional inference example |
| `images/downstream_task_results.png` | 75,144 | Upstream README illustration |

These 48,599,269 bytes are not consumed by the LightForge exporter or evaluator:
the exporter creates seeded reference PCM, while the evaluator uses separately
prepared LightForge QA vocal fixtures. Both small label maps and the example's Freesound
attribution remain. The upstream README and source receipt stay unchanged;
their optional training, evaluation and default-demo instructions describe a
full upstream checkout. Supply an explicit existing `--audio_file` to the
upstream inference script, or recover the original inputs with their matching
source in a separate historical checkout (fetch this revision first in a shallow
clone):

```bash
git worktree add --detach ../lightforge-upstream-history e434d3880c47ebe0e951f01aba366181fd091f96
```

This reduces current checkout data, not model computation or APK runtime work.
Historical numerical receipts and model hashes are unchanged.

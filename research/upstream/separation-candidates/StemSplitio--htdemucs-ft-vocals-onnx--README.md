---
language: en
license: mit
library_name: onnxruntime
pipeline_tag: audio-to-audio
tags:
  - onnx
  - onnxruntime
  - stem-separation
  - source-separation
  - demucs
  - htdemucs
  - music
  - audio-to-audio
  - mobile
  - ios
  - android
  - coreml
  - directml
  - production-ready
  - vocal-extraction
  - vocal-isolation
  - vocal-remover
  - karaoke
  - acapella
datasets:
  - StemSplitio/stem-separation-benchmark-2026
inference: false
---

# HT-Demucs FT — Vocals Specialist, ONNX

**The #1 open-source vocal separator on MUSDB18-HQ**, exported to ONNX. No PyTorch required at inference. Runs on CPU / CoreML / CUDA / DirectML.

This repo packages sub-model 3 of the
[`htdemucs_ft`](https://github.com/facebookresearch/demucs) 4-bag ensemble
as a single 316 MB `.onnx` file plus a ~150-line numpy reference inference
script. Verified to be **numerically equivalent** to the original PyTorch
model.

> Want all 4 stems in one drop-in package? Use the full bag repo:
> [`StemSplitio/htdemucs-ft-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-onnx).

---

## TL;DR

```bash
pip install onnxruntime numpy soundfile
python infer.py your-song.mp3 ./out/
# writes ./out/vocals.wav at 44.1 kHz stereo
```

That's it. No PyTorch, no CUDA setup, no GPU server.

---

## Quality

| Metric (MUSDB18-HQ test, 50 songs) | Value | Source |
|---|---|---|
| Median vocals SDR | **9.19 dB** | [StemSplitio/stem-separation-benchmark-2026](https://huggingface.co/datasets/StemSplitio/stem-separation-benchmark-2026) |
| Rank among open-source separators on vocals | **#1** (the highest open-source vocal SDR on MUSDB18-HQ) | same |
| ONNX vs PyTorch max abs diff | **< 1e-3** | verified during export (see [Day 1 spike report](https://huggingface.co/StemSplitio/htdemucs-ft-drums-onnx#how-it-was-built)) |

---

## Performance

| Runtime | Hardware | Per 7.8-s segment | Per 3-min song |
|---|---|---:|---:|
| **onnxruntime CPU EP** | Apple M4 Pro | **~1.6 s** | **~22 s** |
| PyTorch CPU | Apple M4 Pro | ~2.1 s | ~29 s |
| onnxruntime CUDA EP | NVIDIA L4 | ~0.4 s | ~5 s *(extrapolated)* |
| onnxruntime DirectML EP | RTX 4090 | ~0.2 s | ~2 s *(extrapolated)* |

**Real-time factor on M4 Pro CPU: 0.20.** Roughly 1.31× faster than
PyTorch CPU on the same hardware.

---

## Tooling — `demucs-onnx` Python package

This model can also be run (and re-exported) via the open-source
[`demucs-onnx`](https://github.com/StemSplit/demucs-onnx) Python package
on PyPI. It auto-downloads from this repo on first use.

```bash
pip install demucs-onnx

# Single specialist (this repo)
demucs-onnx separate song.mp3 stems/ --stem vocals

# Or via the Python API
python -c "from demucs_onnx import separate_stem; \
  audio = separate_stem('song.mp3', 'vocals')"
```

The same package is also the canonical tool for **exporting** htdemucs
to ONNX yourself — it bundles all four blocker fixes (complex STFT,
`fractions.Fraction`, `random.randrange`,
`aten::_native_multi_head_attention`) so vanilla `torch.onnx.export`
works on your own checkpoints.

```bash
pip install "demucs-onnx[export]"
demucs-onnx export htdemucs_ft vocals.onnx --stem vocals
```

---

## Common use cases

- **Karaoke maker** — extract clean instrumental + acapella in one pass (pair with the `other` ONNX)
- **Acapella extraction** — harvest isolated vocals for sampling, remixing, vocal-coach feedback
- **Vocal removal** — build a vocal-remover app on iOS / Android / web without a GPU server
- **Speech-from-music** — isolate spoken-word from background music for transcription

---

## Quick start

### Python — minimal

```python
import infer
vocals = infer.separate_vocals("your-song.mp3")
# vocals: numpy array (2, samples) at 44.1 kHz
```

### Python — full control

```python
import soundfile as sf
import infer

# Optional execution providers — CPU is the default and most portable.
# Swap to "coreml" on macOS, "cuda" on NVIDIA, "dml" on Windows DX12.
audio, sr = sf.read("your-song.mp3", dtype="float32", always_2d=True)
stems = infer.separate(audio.T, sr, providers=["CPUExecutionProvider"])
sf.write("vocals.wav", stems[infer.SOURCES.index("vocals")].T, sr)
```

### CLI

```bash
python infer.py your-song.mp3 ./out/
python infer.py your-song.mp3 ./out/ --providers cuda    # NVIDIA
python infer.py your-song.mp3 ./out/ --providers coreml  # macOS
python infer.py your-song.mp3 ./out/ --providers dml     # Windows
```

### Mobile (iOS / Swift)

```swift
import onnxruntime_objc

let env = try ORTEnv(loggingLevel: .warning)
let opts = try ORTSessionOptions()
try opts.appendCoreMLExecutionProvider(with: ORTCoreMLExecutionProviderOptions())
let session = try ORTSession(env: env,
                              modelPath: Bundle.main.path(forResource: "htdemucs_ft_vocals", ofType: "onnx")!,
                              sessionOptions: opts)
// audio: 1 × 2 × 343980 Float32 buffer, then session.run(...).
```

### Mobile (Android / Kotlin)

```kotlin
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession

val env = OrtEnvironment.getEnvironment()
val opts = OrtSession.SessionOptions().apply { addNnapi() }
val session = env.createSession(modelPath, opts)
```

### Web (onnxruntime-web)

```js
import * as ort from "onnxruntime-web";
const session = await ort.InferenceSession.create("htdemucs_ft_vocals.onnx", {
  executionProviders: ["wasm"],
  graphOptimizationLevel: "all",
});
const tensor = new ort.Tensor("float32", audioBuffer, [1, 2, 343980]);
const out = await session.run({ mix: tensor });
// out.stems.data is a Float32Array (1, 4, 2, 343980); use row 3 for vocals.
```

---

## Input / output spec

| Tensor | Name | Shape | Dtype | Notes |
|---|---|---|---|---|
| Input | `mix` | `(1, 2, 343980)` | float32 | Stereo audio, 44.1 kHz, 7.8 s segment. Values in [-1, 1]. |
| Output | `stems` | `(1, 4, 2, 343980)` | float32 | `[drums, bass, other, vocals]` order. **Use only row 3 (`vocals`)** — the other 3 rows are weakly-predicted by-products of the vocals specialist. |

For longer audio, chunk with overlap-add — see `infer.py::separate` for a
working ~60-line implementation.

---

## Related repos

Sibling stem-specialist ONNX repos from the same export:

| Repo | Stem | Use when |
|---|---|---|
| [`htdemucs-ft-drums-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-drums-onnx) | drums | Drum extraction, beat transcription |
| [`htdemucs-ft-bass-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-bass-onnx) | bass | Bassline transcription, mix rebalancing |
| [`htdemucs-ft-other-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-other-onnx) | other | Karaoke instrumentals, sample-flipping |
| [`htdemucs-ft-vocals-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-vocals-onnx) | vocals | **#1 open-source vocal SDR** — karaoke, acapella, vocal removal |
| [`htdemucs-ft-onnx`](https://huggingface.co/StemSplitio/htdemucs-ft-onnx) | all 4 | Full 4-stem separation in one repo |

PyTorch versions for HF Inference Endpoints:
[`htdemucs-ft-pytorch`](https://huggingface.co/StemSplitio/htdemucs-ft-pytorch),
[`htdemucs-ft-vocals-pytorch`](https://huggingface.co/StemSplitio/htdemucs-ft-vocals-pytorch).

Full benchmark across every popular open-source separator:
[StemSplitio/stem-separation-benchmark-2026](https://huggingface.co/datasets/StemSplitio/stem-separation-benchmark-2026).

---

## Skip the infrastructure — use the StemSplit API

Don't want to ship a 316 MB model in your app, manage a GPU pool, or write
overlap-add chunking? Use the **[StemSplit API](https://stemsplit.io/developers)**
instead — same model under the hood, hosted for you, with credits and a
dashboard.

- 🌐 [stemsplit.io](https://stemsplit.io)
- 📘 [Developer docs](https://stemsplit.io/developers/docs)
- 🔌 [API reference](https://stemsplit.io/developers/reference)
- 📚 [Guides & recipes](https://stemsplit.io/developers/guides)

Or use the no-code tools that ship the same model family:

- 🎧 [Vocal Remover](https://stemsplit.io/vocal-remover)
- 🎧 [Karaoke Maker](https://stemsplit.io/karaoke-maker)
- 🎧 [Acapella Maker](https://stemsplit.io/acapella-maker)
- 🎧 [YouTube Stem Splitter](https://stemsplit.io/youtube-stem-splitter)

---

## Files in this repo

| File | Size | Purpose |
|---|---:|---|
| `htdemucs_ft_vocals.onnx` | 316 MB | The exported model. Opset 17. Passes `onnx.checker`. |
| `infer.py` | ~6 KB | Pure numpy + onnxruntime reference. No torch. |
| `requirements.txt` | <1 KB | `onnxruntime`, `numpy`, `soundfile`. |
| `README.md` | this file | |

---

## License & attribution

This repo is **MIT-licensed**, matching the original HT-Demucs.

```bibtex
@inproceedings{rouard2023hybrid,
  title     = {Hybrid Transformers for Music Source Separation},
  author    = {Rouard, Simon and Massa, Francisco and D{\'e}fossez, Alexandre},
  booktitle = {ICASSP},
  year      = {2023}
}
```

- Original PyTorch model: [`facebookresearch/demucs`](https://github.com/facebookresearch/demucs)
- ONNX export, parity verification, and packaging by [StemSplit](https://stemsplit.io)
- Search keywords: vocal remover onnx, karaoke maker, acapella extractor, htdemucs vocals onnx, vocal separation ios

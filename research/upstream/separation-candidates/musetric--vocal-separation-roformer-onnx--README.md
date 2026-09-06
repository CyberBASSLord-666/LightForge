---
license: mit
library_name: onnxruntime
pipeline_tag: audio-to-audio
tags:
  - audio
  - source-separation
  - vocals
  - music
  - mel-band-roformer
  - onnx
  - webgpu
---

# Vocal Separation Core (Mel-Band RoFormer) — ONNX / fp16 / WebGPU

ONNX export of a **Mel-Band RoFormer** vocal source-separation core, packaged for
the [`musetric`](https://github.com/popelenkow/musetric) `packages/ai` runtime
(`onnxruntime-web` on **WebGPU**).

The graph is the **neural network core**: it takes a precomputed STFT
representation and returns per-bin complex masks. The mel-band gather/average
tables are baked into the ONNX graph, so the host does not need sidecar
`/tables/*` assets. STFT, iSTFT, chunking and complex packing run **host-side**
(browser WGSL + FFT). This is not a drop-in PyTorch checkpoint.

## Intended uses & limitations

**Intended:**
- Vocals / instrumental separation as the first stage of an audio pipeline.
- Client/edge inference via WebGPU through `onnxruntime-web`, on desktop and on
  mobile GPUs alike.

**Out of scope:**
- Standalone use without a host that computes the STFT input, applies the
  per-bin `masks`, and runs iSTFT (see `musetric` `packages/ai`).
- Use in other training frameworks — this is an inference-only export.

**Limitations:**
- One static time window, **T = 1100** (~11 s), the model's full reference
  context, rounded down to a multiple of four. See the window note below.
- Training-data provenance of the upstream weights is undocumented.

## How to use

The session runs the core; the host supplies `stft_repr` and consumes `masks`.

```ts
import * as ort from 'onnxruntime-web/webgpu';

// .onnx and .onnx.data must sit in the same directory; .data loads automatically.
const session = await ort.InferenceSession.create('syhft_core_t1100.onnx', {
  executionProviders: [{ name: 'webgpu', storageBufferCacheMode: 'simple' }],
});

// stftRepr: Float32Array of shape [1, 2050, 1100, 2], produced host-side from one
// ~11 s audio chunk (n_fft=2048, hop=441, 44.1 kHz, stereo).
const input = new ort.Tensor('float32', stftRepr, [1, 2050, 1100, 2]);
const { masks } = await session.run({ stft_repr: input });
// masks: float32 [1, 2050, 1100, 2] -> apply to STFT, then iSTFT host-side.
```

See the `musetric` `packages/ai` host code for the full STFT/iSTFT and
chunk-recombination pipeline.

## Files

One graph. Keep the `.onnx` next to its `.onnx.data`.

| File | Size | SHA256 |
|---|---|---|
| `syhft_core_t1100.onnx` | 7,041,719 B | `8b624200ac9bfc76c38fbcc9dcde3901f307acd6ee7e95b5b0a6cb3022585758` |
| `syhft_core_t1100.onnx.data` | 741,190,540 B | `06b41c5798b3c44d514e74feca715a002031c26fa390fcea913ad01844fb7221` |

**Signature** — opset `ai.onnx` 23, IR 10, no `com.microsoft` import. fp16
weights, fp32 graph I/O, `T` = 1100:

| Tensor | Type | Shape | Meaning |
|---|---|---|---|
| `stft_repr` (in) | float32 | `[1, 2050, T, 2]` | batch, freq*2, time, complex |
| `masks` (out) | float32 | `[1, 2050, T, 2]` | per-bin complex masks, already gathered/averaged from mel bands |

## How these graphs are written

**Attention is split along the query axis into 64-row blocks.** Written in one
shot, each layer's score tensor is `[60, 8, T, T]` fp16 — 1110 MiB at this
window — and a mobile storage-buffer binding stops working past 256 MiB whatever
limit the adapter declares, silently returning zeros. Softmax normalizes each
query row over the full key axis on its own, so splitting the *queries* is
exact: same values, same work, no context given up. The peak score tensor
becomes `[60, 8, 64, T]`, 64.5 MiB.

**RMSNorm is the fused `ai.onnx::RMSNormalization`, in fp16, with
`epsilon = 1e-9`.** Its WebGPU kernel accumulates the sum of squares in `f32`
inside the shader, which is what makes fp16 safe here; an fp32 island instead
costs 387 MiB of activations at this window. The epsilon is not the `1e-12` an fp32
RMSNorm would carry: the kernel normalizes by the reciprocal
`1/sqrt(mean(x^2) + epsilon)` and casts it to the tensor dtype, so on an fp16
node any row whose `mean(x^2) + epsilon` falls below `1/65504^2 = 2.33e-10` gets
`+inf`, then `0 * inf = NaN`, and one NaN row takes the whole output out through
the next attention softmax. Rows that small are ordinary — padded STFT edges,
silent frames, dead band-split features, 0.089 % of rows on a real chunk.

**Wide `Concat`/`Split` are re-treed to <=8-wide** so every shader stays at <=9
storage buffers, under the strictest shipping cap (Dawn/Metal on macOS reports
`maxStorageBuffersPerShaderStage = 10`).

All three rewrites are compatibility and footprint measures. None of them
touches a weight.

## Why the window is 1100 and not 1101

On an Adreno 750, `onnxruntime-web` computes an fp16 `MatMul` with visibly less
precision whenever the reduction length `K` or the output width `N` is not a
multiple of four. Measured on that adapter against the CPU execution provider,
`M = 4096`, both operands dynamic:

| K | N | desktop | Adreno 750 |
|---|---|---|---|
| 1101 | 64 | 46.6 dB | 20.1 dB |
| 1100 | 64 | 46.4 dB | 46.3 dB |
| 1104 | 64 | 46.4 dB | 46.3 dB |
| 1102 | 64 | 46.5 dB | 20.9 dB |
| 384 | 1101 | 50.8 dB | 35.4 dB |
| 384 | 1100 | 50.8 dB | 50.7 dB |

A multiple of two is not enough. Both attention matmuls carry the window in
exactly that position — `q @ kᵀ` has `N = T` and `attn @ v` has `K = T` — so a
window of 1101 put every attention in every layer on the bad path, while the
projections (`K = 384`, `N = 512` or `1536`) stayed exact. End to end that cost
15 dB on that adapter and nothing anywhere else.

Rounding the window down to 1100 removes it: 26.9 dB becomes 41.7 dB on the
Adreno 750, desktop is unchanged, and the price is one frame of context, 11.00 s
instead of 11.01 s. Any future window should stay a multiple of four.

## Validation

Against the PyTorch first-stage reference at the same window, which
isolates conversion and execution-provider error:

| Metric | Value |
|---|---|
| SNR (vocals) | ~46–49 dB |
| correlation | ~0.999 |
| NaN / silent gaps | 0 |

The `1e-9` epsilon costs nothing measurable against `1e-12`: 45.68 dB versus
45.70 dB on a real chunk, and 45.07 dB with a fifth of the frames zeroed, where
`1e-12` returns NaN.


Against the earlier non-blocked export of the same weights, on a desktop NVIDIA
GPU through the shipping host, one 30 s track: **52.7 dB on the vocals stem and
55.8 dB on the instrumental** — the two graphs sit closer to each other than
either sits to torch, which is what an exact rewrite plus fp16 rounding looks
like. Two A/B pairs put the cost at 3 % and 7 % more wall clock at the same peak
GPU memory, so the blocking is not a desktop optimization; it is what lets one
graph serve every target.

One real 11 s chunk, identical input bytes, Chrome 151 on both phones,
measured against this graph on the CPU execution provider:

| runtime | SNR vs CPU | run |
|---|---|---|
| desktop NVIDIA, WebGPU | 44.0 dB | 2.9 s |
| Galaxy S24 Ultra, Adreno 750 | 41.7 dB | 15.9 s |
| OnePlus 9RT, Adreno 660 | 41.7 dB | 42.6 s |

All three are ordinary fp16 execution error, and the two phones agree to the
digit.

Re-run the parity gate on the exact published bytes before relying on it.

## Source & lineage

Code license and weight license are separate; ONNX conversion does not change the
weight license. Documented only as far as it is verifiable.

- Architecture: **Mel-Band RoFormer** ([arXiv:2310.01809](https://arxiv.org/abs/2310.01809)).
- Reference implementation: [`lucidrains/BS-RoFormer`](https://github.com/lucidrains/BS-RoFormer).
- Training framework / config: ZFTurbo [`Music-Source-Separation-Training`](https://github.com/ZFTurbo/Music-Source-Separation-Training).
- Direct weight source: [`SYH99999/MelBandRoformerBigSYHFTV1Fast`](https://huggingface.co/SYH99999/MelBandRoformerBigSYHFTV1Fast)
  @ `96f4ae8e3f690e51ef26b3bef84531c944f5341b`, **MIT**.
- Export tooling: `scripts/onnx/roformer` in
  [musetric-toolkit](https://github.com/popelenkow/musetric-toolkit).

The base checkpoint the upstream fine-tuned from is **not documented upstream**;
we do not assert a chain we cannot verify. This export preserves the upstream
**MIT** license; we do not claim authorship of the original weights.

## License & citation

MIT, inherited from the upstream weights.

```bibtex
@article{wang2023melbandroformer,
  title={Mel-Band RoFormer for Music Source Separation},
  author={Wang, Ju-Chiang and Lu, Wei-Tsung and Won, Minz},
  journal={arXiv preprint arXiv:2310.01809},
  year={2023}
}
```

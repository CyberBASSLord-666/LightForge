# Exact vocal frontend reuse

The Frame-MN10 frontend now computes its fixed FFT twiddle coefficients once
and reuses already-computed interior log-mel frames where successive ten-second
analysis windows overlap. It keeps the original pre-emphasis, reflection,
400-sample window, 512-point FFT, mel weights, arithmetic order, Float32 model
input, neural windows, and model calls. The separated-vocal summarizer also
reuses its existing singing/speech interpolation arrays instead of computing
them twice.

Reuse requires integer absolute PCM coordinates and bit-identical Float32
samples across the complete supporting window. Reflected edge frames are always
recomputed. Changed input or a nonaligned clock disables reuse; Float64 and
ordinary arrays use the original frontend without caching. The cache owns
snapshots of one ten-second window and its features, retaining 1,152,000 bytes
of arrays. This is an explicit cache budget, not a peak application memory
measurement. The original audio and model clocks remain unchanged.

The [recorded host benchmark](../qa/release-2.4.0/performance/vocal-frontend-reviewed.json)
processes all ten original windows of the complete public 64-second demo. Two
warmups and seven measured rounds per variant use rotating execution order.
Every trial compares all 1,280,000 Float32 feature values byte for byte against
the frozen 2.3.2 frontend. All comparisons passed. Of 10,000 frames, 3,573 reused
verified interior features; 6,427 were computed normally.

| Frontend | Median host wall time |
| --- | ---: |
| Released 2.3.2 | 421.2 ms |
| Fixed FFT coefficients | 298.2 ms |
| Fixed coefficients and verified overlap reuse | 308.4 ms |

The combined change reduced this host frontend median by **26.8%**. Individual
trial ranges remain in the receipt because this shared host has timing
variation. Fixed coefficients alone had a slightly lower median in this run;
the recorded timings do not establish an additional speed gain from overlap
reuse by itself. This measures only log-mel extraction from prepared PCM. It excludes
resampling, audio IO, neural inference, and the rest of analysis; it does not
establish Android speed, a 75% complete-analysis reduction, or general musical
quality. Byte-identical model inputs establish that this frontend optimization
does not approximate or discard the exercised input features.

Reproduce in a new output file:

```sh
node --expose-gc tools/benchmark_vocal_frontend.cjs --output /tmp/vocal-frontend-new.json
node --test tests/vocal-frontend-reuse.test.cjs
```

The receipt binds source, oracle, model frontend configuration, WAV fixture,
runtime, window coordinates, and every timing sample. The reference is the
project's own 2.3.2 implementation and is used only by verification. This
provenance statement does not grant a license to the LightForge application.
No xLights code or new dependency is involved in this DSP change.

Native GAME/Deux session retention remains unchanged. The separate PR43 host
experiment demonstrates selected numerical equivalence, but its retained
session candidate is host-only and does not qualify Android cancellation,
resource ownership, or whole-job speed. Its CPU traces also show Deux dominated
by graph execution, so removing constructor work alone cannot justify the
75% objective.

# Source separation frontend measurements

The [observations](separation-frontends.json) compare the released 2.4.3 MDX frontend with this change using the bundled 64-second Glass Castle demo. One warmup and five measured pairs alternated order on Node 24.22.3. The measurements cover memory-backed audio reads and host DSP.

Studio's native passage preflight classified the same 12 windows as active and read 98,304 bytes instead of 26,812,800. In an imported 16-bit WAV any nonzero sample exceeds the existing silence threshold. The probe checks the remaining bytes after a quiet prefix, and generic encodings retain float decoding. The original native graphs still process the same complete passages. [PCM format reference](https://learn.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatex)

The Balanced frontend computes the final FFT sums consumed by its trained model and the real time-domain samples used for synthesis. The median for one full stereo encode/decode round-trip fell from 1,046.95 to 582.82 ms. The released runs ranged from 826 to 1,322 ms. Complete spectral and decoded buffers matched byte for byte. A separate check ran both polarities of the original MDX model on the first passage and compared all 253,440 samples in each emitted stem. Both stem digests matched. [FFT output pruning](https://fftw.org/pruned.html)

End-to-end phone processing time, thermal behavior and whole-song inference remain unmeasured. Reproduce from a checkout containing the 2.4.3 release and its pinned assets:

```sh
git show v2.4.3:web/analysis/separator-mdx.js > /tmp/lightforge-released-mdx.cjs
node tools/benchmark_separation_frontends.cjs /tmp/lightforge-released-mdx.cjs --verify-model
```

## Complete five-second Balanced analysis

The [eight cold runs](balanced-clip-analysis.json) processed seconds 16–21 of Glass Castle through the normal production analyzer in headless desktop Chromium. Each run started with fresh browser storage. Rhythm, both MDX polarity passes, isolated-voice classification, GAME transcription and bass tracking all ran. The two CPU conditions used separate counterbalanced comparisons.

| Host CPU condition | Order | Released 2.4.3 | Candidate |
| --- | --- | ---: | ---: |
| Default affinity, concurrent repository work | Released first | 45.709 s | 53.277 s |
| Default affinity, concurrent repository work | Candidate first | 45.440 s | 52.044 s |
| CPUs 5–8, two WASM workers | Released first | 64.047 s | 64.427 s |
| CPUs 5–8, two WASM workers | Candidate first | 66.234 s | 65.559 s |

Both unrestricted runs were slower on the candidate. In the fixed-affinity pairs the candidate took 0.380 seconds longer once and 0.675 seconds less once. Timing for the unchanged neural graph calls varied between runs. These trials leave a dependable end-to-end speedup unestablished.

All three stem files, 8 beats, 16 vocal notes and 5 bass notes matched. Each CPU condition produced identical musical analysis across versions after removing the recorded execution metadata and temporary cache identities. Rhythm confidence differed slightly between CPU conditions even on the released code. Across all eight analyses the fixed 2.4.3 compiler produced byte-identical FSEQ exports for all three styles at both frame rates. Studio-native inference, longer tracks and physical phones require separate measurements.

# Source separation frontend measurements

The [observations](separation-frontends.json) compare the released 2.4.3 MDX frontend with this change using the bundled 64-second Glass Castle demo. One warmup and five measured pairs alternated order on Node 24.22.3. The measurements cover memory-backed audio reads and host DSP.

Studio's native passage preflight classified the same 12 windows as active and read 98,304 bytes instead of 26,812,800. In an imported 16-bit WAV any nonzero sample exceeds the existing silence threshold. The probe checks the remaining bytes after a quiet prefix, and generic encodings retain float decoding. The original native graphs still process the same complete passages. [PCM format reference](https://learn.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatex)

The Balanced frontend computes the final FFT sums consumed by its trained model and the real time-domain samples used for synthesis. The median for one full stereo encode/decode round-trip fell from 1,046.95 to 582.82 ms. The released runs ranged from 826 to 1,322 ms. Complete spectral and decoded buffers matched byte for byte. A separate check ran both polarities of the original MDX model on the first passage and compared all 253,440 samples in each emitted stem. Both stem digests matched. [FFT output pruning](https://fftw.org/pruned.html)

End-to-end phone processing time, thermal behavior and whole-song inference remain unmeasured. Reproduce from a checkout containing the 2.4.3 release and its pinned assets:

```sh
git show v2.4.3:web/analysis/separator-mdx.js > /tmp/lightforge-released-mdx.cjs
node tools/benchmark_separation_frontends.cjs /tmp/lightforge-released-mdx.cjs --verify-model
```

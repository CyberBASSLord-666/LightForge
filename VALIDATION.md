# LightForge 2.1.0 validation

Version 2.1.0 / code 20100 upgrades the models and studio interface while retaining the original signing identity and saved-arrangement integrity. Current receipts are in `qa/release-2.1.0/`. Historical measurements below keep their original release scope.

| Current gate | What it establishes |
| --- | --- |
| Node and Python regressions | Musical boundaries, voice/bass offsets, final FSEQ attacks, hardware routing, silence, deterministic composition, stem/WAV components, neural-note fusion, backup handling, legacy frame migration and real app DOM editing |
| Actual Chromium UI | WebGL, workers, cue form, Undo/Redo, exact-byte streamed export, save/reload, four keyboard-accessible workspaces and 320/393/768/1440 px layouts |
| Actual Chromium analysis | Public MusicAnalyzer with real Deux, GAME, Beat This and Frame-MN10; OPFS full-resolution voice retrieval and incomplete-cache cleanup after cancellation |
| Source separation | Six original mixtures, six instrument-only negatives and six controlled voice-window remixes, scored against original reference stems; references are never separator inputs |
| Model conversion/runtime | Staged Float32 graphs reproduce the original model within measured floating-point error; the production JS adapter executes on the unchanged ONNX Runtime Web 1.20.1 WASM backend |
| Native JVM | Production Java compiles; storage recovery, WAV conversion, bridge ranges, previews and 16 independent FSEQ/hardware cases |
| Signed APK | Version, alignment, original certificate, ZIP CRCs and exact packaged-asset hashes; all current gate receipts must match the source |

`tools/package_v2.py` refuses missing, failed or stale regression/UI/native/analysis receipts. The build checks all 60 bundled analysis files before packaging. CI reproduces GAME and Deux from pinned official checkpoints and verifies the resulting hashes; no large new checkpoint is silently omitted from a fresh checkout.

## Current separator comparison

| Mixture | Previous MDX vocal SI-SDR | Deux vocal SI-SDR |
| --- | ---: | ---: |
| Night Owl | 6.878 | 7.504 |
| Stella | 17.054 | 18.791 |
| Meaxic | 16.060 | 16.558 |
| Grunge | 9.887 | 10.790 |
| Falcon | 3.058 | 7.044 |
| SDRNR | 7.315 | 8.162 |
| Mean | 10.042 | 11.475 |

Units are dB. Deux uses the exact production 13-second context and 1.5-second left halo in the original PyTorch reference. The historical MDX scores use the same declared mixtures and scorer. The six short excerpts are neither representative nor verified held-out data; training overlap is possible. SI-SDR includes its conventional scale projection; plain SDR, envelope correlation, sample counts and instrumental/control leakage are also retained. No reference-derived timing shift, separator mask or per-song tuning is used.

Actual production JS/WASM on Falcon returns exactly 300,032 samples. Compared with the original model's vocal waveform at the same context/crop, maximum absolute error is 0.000468 and RMS error is 0.0000244 (rounded upward). Zero envelope lag was measured on the excerpt's 5 ms diagnostic grid. This does not establish sub-frame perceptual precision or vehicle latency. Both source heads are checked separately in the original ONNX parity probe.

The role component evaluation uses estimated vocals/accompaniment and the production Float32 resampler, classifier, detail extractor and GAME adapter. Original vocal stems are reserved for scoring. Weak general event scores may use independent GAME/source-pitch agreement while retaining existing prominence, duration and speech guards. Classifier scores remain unchanged. Its event counts establish the declared positive/negative behavior, not note-boundary or pitch accuracy against human annotations. The full public browser pipeline is an independent integration gate.

Synchronization review compares selected voice/bass targets with final exported lamp commands after manual output edits. A matching command proves frame placement, not whether an automatic musical target was detected correctly. Bass remains a harmonic estimate from combined accompaniment. There are no lyrics, word timestamps or individually synchronized Tesla Dance strokes.

Desktop WASM, Chromium and host JVM checks do not execute Android Activities, document providers, phone codecs or a physical Tesla. The larger models need several GB of working memory; WASM can retain peak allocation until the disposable worker terminates. Actual phone installation, sustained analysis, thermals and vehicle timing remain physical validation work.

## Historical 1.6.0 model choice and measured quality

The selected UVR MDX-Net Voc FT model was compared with Spleeter, HTDemucs FT's vocal specialist, four deterministic Demucs shifts, and a fixed equal MDX/Demucs waveform blend. The official MUSDB18 short excerpts provide six original reference mixtures and vocal stems, six accompaniment-only negatives, and six controlled voice-window remixes. There was no reference-derived mask, gain fitting, latency correction or per-song ensemble selection.

| Candidate | Mean vocal SI-SDR | Vocal RMS-envelope correlation |
| --- | ---: | ---: |
| Spleeter | 5.923 dB | 0.8669 |
| MDX with polarity refinement | **10.042 dB** | 0.9204 |
| HTDemucs FT, four shifts | 8.687 dB | 0.9227 |
| Fixed equal MDX/Demucs blend | 9.976 dB | **0.9330** |

MDX improved separation fidelity over Spleeter on every tested mixture. The blend helped the most difficult Falcon excerpt but reduced four other SI-SDR results; it was not a consistent overall winner. Its additional working memory and upstream weight-use uncertainty are recorded in the candidate evidence. MDX was the selected 1.6.0 quality-first model; this does not establish superiority on every song or over every available model.

On the six controlled remixes, MDX's mean estimated voice energy outside the exact voice windows was 0.059%, versus 0.801% for Spleeter; envelope correlation was approximately 0.9898 versus 0.9514. No envelope timing lag was measured in the six natural mixture excerpts. These are acoustic source-estimate metrics, not word-boundary annotations or a subjective choreography score. Original stems contain production effects and codec artifacts; the small set is neither statistically representative nor a verified held-out benchmark.

The final application envelope tracked original vocal dynamics more closely: mean correlation rose from 0.4445 to 0.8331 on the six natural mixtures and from 0.7202 to 0.9652 on the controlled remixes. All 12 positive reference variants retain voice and all six instrumental variants produce zero vocal events. These results concern the declared small reference set.

The complete production pipeline is tested separately from those raw separator outputs. It includes Float32 cache conversion, trained singing/speech evidence, measured vocal detail, bass tracking, composition and export. Component tests using original reference vocals demonstrate detail extraction and command translation only; they are not represented as separator accuracy.

## 3. Retained analysis timing and uncertainty

The separator uses the exact trained 7,680-point FFT geometry. JavaScript spectra and reconstructed waveform are checked against PyTorch reference transforms. Centered filtering and overlap-add remain on the original audio clock. The cache's 63-tap resampler has zero added impulse delay in the independent test; chunked and whole-buffer outputs match. Odd source sample counts produce only the required final half-rate sample, without cumulative drift.

Frame-MN10 produces 40 ms singing/speech evidence. The detail extractor follows separated waveform energy, source contrast, periodicity and local pitch on finer grids. Its phrases, syllabic accents and estimated notes are acoustic estimates. Lead and backing singers are combined; speech does not invent sung notes. There is no lyric transcription or word-by-word forced alignment. Dense, breathy, quiet or heavily processed singing can still be uncertain, and source separation can retain instruments. User Voice/Instrumental guides are reversible editing overlays, not fabricated model confidence.

Bass is estimated from combined accompaniment, not an isolated bass stem. Synthetic ordinary/nearby-kick fixtures use 40 ms onset and 50 ms offset bounds; the closest 50 ms overlapping-kick fixture has a separately disclosed 80 ms onset bound. These do not certify real-song precision. A 5 ms analysis grid and 15/20 ms export frame interval do not guarantee equivalent perceptual or physical accuracy.

The original supplied Sample WAV is complete at 238.04 seconds. Glass Castle declares that duration but physically contains only about 121.749 seconds; only its available prefix is recoverable. Original uploads are unchanged. Neither supplied song has independent vocal or bass-note annotations.

## 4. Reliability and compatibility / limits

Original 1.4, 1.5, 1.6 and previously migrated compiled arrangements are checked against their original settings before only explicitly recognized empty or zero defaults are bound. The 2.0 defaults are an empty musical cue list and zero voice/bass timing offsets; prior guide/focus migrations remain supported. Changes to music, previous settings, nondefault new settings or nonempty guides cannot bypass the check. Accepted upgrades preserve exact original frame and compressed payload bytes; the export header identifies the current producer. Current projects with actual guides follow ordinary full-input integrity checks.

Audio decoding, project revisions, transactional imports, backup/recovery and native FSEQ/ZIP validation execute against production Java on the host JVM. Actual browser workers exercise compression, checksums, corruption rejection, Undo/Redo and IndexedDB reopening. Separate real OPFS tests cover streaming writes, corruption, metadata, cancellation, stored samples and browser audio playback. Missing audition caches do not rewrite saved analysis or prevent original-audio export.

Neural sessions are released between stages so their allocations can be reused. WebAssembly linear memory can retain its peak size until the disposable analysis worker terminates; release does not promise an immediate resident-memory drop. PCM reads and cache writes are bounded, and the original full-quality soundtrack remains the export audio. Processing time depends on track and device and can substantially exceed song duration.

The retained 1.6.0 preview gate loaded 105 meshes and 180,081 triangles in actual WebGL2, and checks command/pose parity across quality modes, seeking, hidden views and graphics-context recovery. Visual lamp optics, lens subdivisions, motor travel and Tesla-controlled Dance cadence remain estimates requiring physical comparison.

No physical Android phone or Tesla was tested in this workspace. APK alignment, signature and ZIP checks establish package integrity; desktop Chromium and host JVM checks do not establish phone memory/performance, Android codec-provider behavior or physical lamp/motor timing. Full four-hour neural analysis has not been timed on a phone.

## Related docs

- [`BUILD.md`](BUILD.md)
- [`ASSETS.md`](ASSETS.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`INSTALL_OVER_1.5_to_1.6_CHECKLIST.md`](INSTALL_OVER_1.5_to_1.6_CHECKLIST.md)

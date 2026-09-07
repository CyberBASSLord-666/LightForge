# LightForge 2.2.1 validation

Version 2.2.1 / code 20201 changes Studio execution and recovery while retaining analysis v6, learned model weights, original soundtrack timing, existing musical semantics and saved-arrangement integrity. Current evidence is under `qa/release-2.2.1/`. Final release-candidate CI, the complete Android cancellation/resume gate and signed publication are still pending; historical measurements below retain their original scope.

| Current check | Status and scope |
| --- | --- |
| Node/Python regressions | **Passed against the current sources: 145 Node checks and 39 Python checks.** Engine/role boundaries, deterministic FSEQ, migration, actual-app DOM editing, checkpoint corruption/reuse, native transport, resource sequencing and APK transfer/package contracts. This is not browser rendering or Android execution. |
| Native host compilation/storage | **Passed against the current Activity teardown sources: 21 host verification checks.** Production Java compilation, storage/audio/format checks, stronger final-checkpoint validation and compatibility with three real 1.6 music-analysis fixtures. |
| Deux runtime equivalence | **Passed on the development host.** Bounded WASM matches the declared original Float32 output; production Java native CPU matches the separate, identical PCM16 WASM input within measured Float32 error. |
| Vocal/bass role regression | **Passed: 18 cases.** Fresh downstream neural inference on fixed original-model source estimates retains voice in 12 positive cases and produces zero vocal events in six instrumental cases. These are not 18 newly separated native-runtime mixtures. |
| Source-clock reconstruction | **Passed.** Production transform/scheduler tests exercise overlapping joins and an odd final sample count with neutral masks; model timing and perceptual accuracy are separate questions. |
| Chromium UI and complete public analysis | **Passed against unchanged web sources.** Real UI/WebGL, responsive layouts, workers, OPFS, cancellation, persistence and export, including elapsed/passage/reuse progress. The final release-candidate CI rerun remains pending. |
| Android native Studio lifecycle | **Complete gate pending.** An initial real native Studio fixture completed and reopened its saved show with the Activity destroyed, screen off and Doze active. A later probe cancelled with one durable passage but hit an Android focus-event ANR during resume. The Activity teardown fix still requires a complete current run. |
| Signed update APK and publication | **Pending final release gates.** Version, alignment, original certificate, ZIP CRCs and exact web/model/native-library inventories must match current source-bound receipts. |
| Physical phone and Tesla | **Unverified.** No sustained-phone, thermal, manufacturer battery-policy or physical lamp/motor timing certification. |

All 73 declared bundled analysis assets have been restored and verified against their pinned manifests. The bounded APK staging check streamed 111 files totaling 1,524,917,198 bytes and verified their exact source hashes; six staging regression tests pass. This establishes staging integrity, not a complete signed release. `tools/package_v2.py` refuses missing, failed or stale required receipts. Build and package verification check every declared model and native-runtime asset against pinned hashes. Native libraries do not enter the APK merely because a host test passes; dependency, ABI, ZIP and signing checks remain separate gates.

## Measured native execution on one development excerpt

The exact comparison uses the same **300,032-sample, approximately 6.803-second stereo PCM16 Falcon excerpt**, the same learned model weights and four inference threads on a Linux x86_64 development machine. See [`DEUX_RUNTIME.md`](qa/release-2.2.1/DEUX_RUNTIME.md), [`deux-native-java.json`](qa/release-2.2.1/deux-native-java.json) and its pinned [`PCM16 WASM reference`](qa/release-2.2.1/deux-bounded-pcm16-wasm.json).

| Measure | Bounded WASM | Production Java native CPU |
| --- | ---: | ---: |
| Processing time | 127.25 s | 61.11 s |
| Peak process resident memory | 1,920.96 MiB | 720.56 MiB |

Native execution was **2.08× faster** in this comparison, with approximately **62.49% less peak process RSS**. These are whole-process host measurements on one short excerpt, not an isolated tensor-allocation budget, full-song result or phone prediction. Even the faster result takes much longer than this excerpt's playback duration. Sustained performance, thermals and successful completion on the user's phone remain unverified.

Native output retains both 300,032-sample crops with no non-finite values. Maximum absolute error against the identical PCM16 WASM reference is approximately **3.21 × 10⁻⁷** for vocals and **2.99 × 10⁻⁷** for accompaniment; RMS error is below **4.51 × 10⁻⁸**. The full model input remains 13 seconds, including source context. Context crop offsets are not a measured output delay.

A separate Float32-input WASM comparison to the historical combined-graph output is bit-identical for both stems. Its input differs from the PCM16 native comparison and must not be substituted for that oracle. The current [`analysis-verification.json`](qa/release-2.2.1/analysis-verification.json) binds these results to exact sources and states their limits. Preserving learned weights does not by itself prove execution equivalence; native transforms, graph partitioning and source-clock handling require the fresh numerical checks above.

## Recovery, cancellation and lifecycle scope

Host transactions now reject incomplete overall music checkpoints, wrong source duration, unsupported versions, malformed arrays, missing role/model fields and changed checkpoint bytes. Repeated attempts after damaged checkpoints return to analysis rather than reusing the same invalid result. Complete legacy v5 analysis remains eligible; existing compiled projects still reopen through their unchanged checksum/migration path. Changing audio, analysis settings, app version or execution namespace prevents stale work reuse; rename and choreography-only edits preserve matching work.

Checkpoint/component tests cover committed passage reuse, failed writes, corrupted or swapped records, stage invalidation when stems are missing, cancellation and exact source sample counts. A fresh worker per rhythm/separation/voice/bass stage frees its prior WASM heap. Native resources are released after separation before voice/GAME; cancellation reaches the active native run, and a process-wide gate serializes heavy native allocations across rapid cancel/resume. Host/DOM tests verify these contracts; the Android lifecycle test must independently confirm runtime behavior.

The implemented Android 15 test runs Studio native CPU separation and full neural choreography after destroying the Activity and turning the display off under forced Doze and a user-equivalent battery exemption. It then cancels during the second passage of a 12-second fixture, immediately starts Resume, checks old native-executor cleanup, and requires at least one restored passage, two final source passages and a compiled show on the same clock. It also observes native-model release during voice/GAME and exercises the media-processing timeout callback. The earlier [native probe](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34166156881) completed its first background fixture and reopened the saved show, then failed while establishing Doze for the second fixture. The next [probe](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34168136295) passed the repeated Doze setup, saved one passage and cancelled native work, but hit an Android focus-event ANR during the resume sequence. It did not verify complete Resume. `MainActivity` now detaches the preview WebView before destruction; the instrumentation asserts actual Activity destruction and WebView detachment. A two-second diagnostic watchdog captures stacks while preserving Android’s normal ANR threshold. **The current lifecycle fix needs a new complete production run and signed build.** Earlier fixture passes and [CI on the previous app source](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34168172741) cannot validate that fix.

The 18 current role cases use fixed original-PyTorch separation estimates followed by fresh production resampling, singing/speech evidence, vocal detail, GAME and bass processing. They demonstrate the declared positive/negative behavior on that small set, not fresh native separation quality across 18 songs or human-annotated note/word timing. Historical 2.1 separation scores follow below; they remain historical and are not relabeled as a new native benchmark.

## Historical 2.1 separator comparison

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

A separate neutral-mask transform test crosses four overlapping windows with 932,143 nonzero source samples, including seam impulses and an odd final count. Maximum round-trip error is below 0.000000023. This checks the real STFT/scatter/ISTFT and scheduler with fake graph sessions; it is not neural-model accuracy.

On controlled remixes, Deux mean vocal SI-SDR is 11.991 dB and envelope correlation is 0.9935. Residual estimated-voice energy outside the exact voice windows is **0.237%**, versus the historical MDX **0.059%**. This is a measured tradeoff: improved mixture fidelity does not make Deux uniformly better at rejecting every tail or artifact. The role gate separately checks that all six instrument-only cases create zero vocal events.

Actual production JS/WASM on Falcon returns exactly 300,032 samples. Compared with the original model's vocal waveform at the same context/crop, maximum absolute error is 0.000468 and RMS error is 0.0000244 (rounded upward). Zero envelope lag was measured on the excerpt's 5 ms diagnostic grid. This does not establish sub-frame perceptual precision or vehicle latency. Both source heads are checked separately in the original ONNX parity probe.

The role component evaluation uses estimated vocals/accompaniment and the production Float32 resampler, classifier, detail extractor and GAME adapter. Original vocal stems are reserved for scoring. Weak general event scores may use independent GAME/source-pitch agreement while retaining existing prominence, duration and speech guards. Classifier scores remain unchanged. Its event counts establish the declared positive/negative behavior, not note-boundary or pitch accuracy against human annotations. The full public browser pipeline is an independent integration gate.

Synchronization review compares selected voice/bass targets with final exported lamp commands after manual output edits. A matching command proves frame placement, not whether an automatic musical target was detected correctly. Bass remains a harmonic estimate from combined accompaniment. There are no lyrics, word timestamps or individually synchronized Tesla Dance strokes.

Those historical desktop WASM, Chromium and host JVM checks do not execute Android Activities, document providers, phone codecs or a physical Tesla. Their original WASM memory needs are not a measurement of the new native execution path. Current host memory/runtime results and pending device scope are recorded above.

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

In 2.2.1, a separate worker is terminated after each major model stage so its WebAssembly heap is not carried into the next stage; releasing an individual session alone still does not promise an immediate resident-memory drop. Native separation buffers are separately released before voice/GAME. PCM reads and checkpoint writes are bounded, and the original full-quality soundtrack remains the export audio. Runtime and remaining storage/memory requirements depend on the track and device and can substantially exceed song duration.

The retained 1.6.0 preview gate loaded 105 meshes and 180,081 triangles in actual WebGL2, and checks command/pose parity across quality modes, seeking, hidden views and graphics-context recovery. Visual lamp optics, lens subdivisions, motor travel and Tesla-controlled Dance cadence remain estimates requiring physical comparison.

No physical Android phone or Tesla was tested in this workspace. APK alignment, signature and ZIP checks establish package integrity; desktop Chromium and host JVM checks do not establish phone memory/performance, Android codec-provider behavior or physical lamp/motor timing. Full four-hour neural analysis has not been timed on a phone.

## Related docs

- [`BUILD.md`](BUILD.md)
- [`ASSETS.md`](ASSETS.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`INSTALL_OVER_1.5_to_1.6_CHECKLIST.md`](INSTALL_OVER_1.5_to_1.6_CHECKLIST.md)

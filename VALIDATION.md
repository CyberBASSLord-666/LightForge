# LightForge 2.0.0 validation

Related: [`BUILD.md`](BUILD.md) · [`ASSETS.md`](ASSETS.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`INSTALL_OVER_1.5_to_1.6_CHECKLIST.md`](INSTALL_OVER_1.5_to_1.6_CHECKLIST.md)

Version 2.0.0 / code 20000 retains the original update certificate and the offline analysis pipeline. New evidence lives in `qa/release-2.0.0/`. The 1.6.0 model measurements below are historical; the current regression gate verifies that every analysis asset remains byte-identical.

## 1. Current release verification

Run `npm ci --ignore-scripts`, `npm test`, `node qa/release-2.0.0/browser.cjs` with Chromium installed, and `python3 tests/verify_native_release.py --release 2.0.0`. See [`BUILD.md`](BUILD.md) for toolchain, signing and packaging commands. The GitHub Actions workflow runs these gates on the actual development source.

| Gate | What it establishes |
| --- | --- |
| 103 Node checks | Musical cue boundaries, independent part offsets, final FSEQ attacks, lamp fallback, bass retriggers, disabled outputs, section crossings, silence, deterministic composition, engine format and preview contracts, audio/model components, backup integrity, and actual app DOM Undo/Redo/save/new-song isolation |
| 11 Python checks | Bounded-memory archive operations, checksum and file inventory checks, source/signature validation, and package failure handling |
| Legacy worker migration | Real archived 1.6 worker output plus 1.4 and rebound 1.5 snapshots reopen without changing frame bytes; altered inputs and corrupt payloads fail |
| Actual Chromium app | Production workers, WebCrypto, gzip, cue form, final-byte export hash, Undo/Redo, saved-project reload and export of its timing report; four responsive layouts at 320, 393, 768 and 1440 px |
| Native JVM | Production Android Java compiles; project storage, recovery, streaming bridge, WAV handling, FSEQ/hardware limits and preview transport tests pass against host Android stubs |
| Analysis asset manifest | All 32 files under the existing analysis manifest retain their exact 1.6.0 sizes and SHA-256 values; this is an integrity check, not a new model-quality measurement |
| Signed package | APK version, alignment, original certificate, ZIP CRC and every packaged web asset match the current source; release receipts are bound to exact source hashes |

`tools/package_v2.py` refuses missing, failed or stale regression/browser/native receipts, a changed APK, an incompatible signing identity, or differing packaged web assets. CI deliberately uses an ephemeral key for build verification. The distributable is built separately with the original private signing identity; it never enters Git or CI.

Synchronization review compares selected voice/bass targets against commands in the final FSEQ after output edits. A matching attack proves command placement at the exported frame interval. It does not prove that an automatic musical target was detected correctly, that a human hears the same onset, or that the vehicle responded at that instant. Suppressed targets and holds without distinct attacks remain visible for review. Explicit user cues, timing corrections and original detections are kept separate.

The browser bridge is simulated. Desktop Chromium, host JVM tests and APK integrity checks do not establish physical Android installation, codec-provider behavior, memory/performance, or Tesla lamp/motor timing. Neither a phone nor a vehicle was tested for this release.

## 2. Retained 1.6.0 model choice and measured quality

The selected UVR MDX-Net Voc FT model was compared with Spleeter, HTDemucs FT's vocal specialist, four deterministic Demucs shifts, and a fixed equal MDX/Demucs waveform blend. The official MUSDB18 short excerpts provide six original reference mixtures and vocal stems, six accompaniment-only negatives, and six controlled voice-window remixes. There was no reference-derived mask, gain fitting, latency correction or per-song ensemble selection.

| Candidate | Mean vocal SI-SDR | Vocal RMS-envelope correlation |
| --- | ---: | ---: |
| Spleeter | 5.923 dB | 0.8669 |
| MDX with polarity refinement | **10.042 dB** | 0.9204 |
| HTDemucs FT, four shifts | 8.687 dB | 0.9227 |
| Fixed equal MDX/Demucs blend | 9.976 dB | **0.9330** |

MDX improved separation fidelity over Spleeter on every tested mixture. The blend helped the most difficult Falcon excerpt but reduced four other SI-SDR results; it was not a consistent overall winner. Its additional working memory and upstream weight-use uncertainty are recorded in the candidate evidence. MDX is the selected quality-first model; this does not establish superiority on every song or over every available model.

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

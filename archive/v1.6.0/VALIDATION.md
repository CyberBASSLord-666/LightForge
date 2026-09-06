# LightForge 1.6.0 validation

Version 1.6.0 / code 10600 uses the existing private update certificate for the North American 2025 Model 3 Long Range RWD. `release-verification.json` binds the built APK, packaged sources and current tests to exact hashes. Historical releases remain separate evidence.

## Current verification

Current scripts, receipts, fixture provenance and screenshots are under `qa/release-1.6.0/`. `tools/package_release.py` refuses missing or failed required receipts, source changes after verification, mismatched model hashes/sizes, incorrect APK signing identity, invalid ZIP CRCs or differing packaged web assets.

| Area | Evidence |
| --- | --- |
| Real complete audio pipeline | `analysis-verification.json`, production worker captures and reference-quality reports |
| Stereo source separation | `separator-mdx-frontend-verification.json`, `separator-mdx-inference-verification.json`, `separator-quality-comparison.json` |
| Vocal expression | `vocal-detail-verification.json`, source-stem component results explicitly distinguished from estimated-stem pipeline results |
| Singing/speech classifier transport | `vocal-resampling-audit.json`; exact unchanged model linked to original Torch conversion evidence |
| Bass notes | `bass-verification.json`; independent harmonic-note and nearby-kick tests plus supplied-audio execution |
| Private audio caches | `stem-cache-verification.json`, `public-analysis-cancel-verification.json` |
| Actual layer playback and editing | `audition-verification.json`, `studio16-verification.json` |
| Choreography and supported commands | `composer-verification.json`, `role-composer-verification.json`, `light-verification.json`, `movement-verification.json` |
| Saved-project migration and recovery | `migration-verification.json`, `runtime-verification.json` |
| Native import/storage/export | `native-verification.json`, `native-isolation-verification.json` |
| Detailed 3D preview | `preview-verification.json` |
| Complete app / checked show export | `integration-verification.json` |

## Model choice and measured quality

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

## Timing and uncertainty

The separator uses the exact trained 7,680-point FFT geometry. JavaScript spectra and reconstructed waveform are checked against PyTorch reference transforms. Centered filtering and overlap-add remain on the original audio clock. The cache's 63-tap resampler has zero added impulse delay in the independent test; chunked and whole-buffer outputs match. Odd source sample counts produce only the required final half-rate sample, without cumulative drift.

Frame-MN10 produces 40 ms singing/speech evidence. The detail extractor follows separated waveform energy, source contrast, periodicity and local pitch on finer grids. Its phrases, syllabic accents and estimated notes are acoustic estimates. Lead and backing singers are combined; speech does not invent sung notes. There is no lyric transcription or word-by-word forced alignment. Dense, breathy, quiet or heavily processed singing can still be uncertain, and source separation can retain instruments. User Voice/Instrumental guides are reversible editing overlays, not fabricated model confidence.

Bass is estimated from combined accompaniment, not an isolated bass stem. Synthetic ordinary/nearby-kick fixtures use 40 ms onset and 50 ms offset bounds; the closest 50 ms overlapping-kick fixture has a separately disclosed 80 ms onset bound. These do not certify real-song precision. A 5 ms analysis grid and 15/20 ms export frame interval do not guarantee equivalent perceptual or physical accuracy.

The original supplied Sample WAV is complete at 238.04 seconds. Glass Castle declares that duration but physically contains only about 121.749 seconds; only its available prefix is recoverable. Original uploads are unchanged. Neither supplied song has independent vocal or bass-note annotations.

## Reliability and compatibility

Original 1.4, 1.5 and previously migrated 1.4 compiled arrangements are checked against their original settings before only the new empty voice-guide default is bound. Changes to music, previous settings, nondefault new settings or nonempty guides cannot bypass the check. Accepted upgrades preserve exact original frame and compressed payload bytes; the export header identifies the current producer. Current projects with actual guides follow ordinary full-input integrity checks.

Audio decoding, project revisions, transactional imports, backup/recovery and native FSEQ/ZIP validation execute against production Java on the host JVM. Actual browser workers exercise compression, checksums, corruption rejection, Undo/Redo and IndexedDB reopening. Separate real OPFS tests cover streaming writes, corruption, metadata, cancellation, stored samples and browser audio playback. Missing audition caches do not rewrite saved analysis or prevent original-audio export.

Neural sessions are released between stages so their allocations can be reused. WebAssembly linear memory can retain its peak size until the disposable analysis worker terminates; release does not promise an immediate resident-memory drop. PCM reads and cache writes are bounded, and the original full-quality soundtrack remains the export audio. Processing time depends on track and device and can substantially exceed song duration.

The preview gate loads 105 meshes and 180,081 triangles in actual WebGL2, and checks command/pose parity across quality modes, seeking, hidden views and graphics-context recovery. Visual lamp optics, lens subdivisions, motor travel and Tesla-controlled Dance cadence remain estimates requiring physical comparison.

No physical Android phone or Tesla was tested in this workspace. APK alignment, signature and ZIP checks establish package integrity; desktop Chromium and host JVM checks do not establish phone memory/performance, Android codec-provider behavior or physical lamp/motor timing. Full four-hour neural analysis has not been timed on a phone.

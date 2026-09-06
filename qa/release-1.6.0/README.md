# LightForge 1.6 release evidence

The release gates bind the source files they executed through SHA-256. `analysis-verification.json` contains the active model identities, independent quality comparison, exact clock checks and explicit limitations. `integration-verification.json` covers actual browser imports, final analysis/compiler, preview and export. Neither is a physical phone or Tesla validation.

The first 18 public-worker outputs are retained as `quality-studio-*.json`; several were created before the final weak-vocal fallback. Final `detail-candidate-*.json` outputs replay actual MDX estimates through the final production downsampler, actual isolated-source classifier and final vocal detail. No original studio source is injected into production. The previously missed controlled NightOwl case is additionally rerun through the complete final public worker, matching the final detail replay exactly. This distinction is retained in `musical-detail-comparison.json` and the aggregate.

`separator-quality-comparison.json` scores actual Spleeter, MDX and Demucs candidate outputs against licensed original reference stems. Spleeter/Demucs are research candidates, not shipped model choices. Their capture scripts may need the corresponding archived research assets restored to the documented model paths before reproducing historical comparisons. Downloaded reference audio, raw model-output audio, archives containing those recordings, and discarded model weights are excluded from the app and private source ZIP. Their preparation scripts, hashes and provenance remain.

`public-analysis-cancel-verification.json` tests the real public worker after it owns a writable OPFS cache and has entered MDX separation. A cleanup race was reproduced and fixed; final trials verify abort plus eventual namespace removal. The app integration also cancels re-analysis and deliberately blocks one model read, checking that original saved frame/audio hashes and export readiness survive without an automatic full-song retry.

The 64-second user-audio fixture is the first 64 seconds of the physically available recovered Glass Castle prefix. It is not represented as the original full 238-second attachment. Details are in `user-glass-fixture-provenance.json`.

Full method, model tradeoffs, quantitative results and limits: `research/evaluation-1.6/README.md`.

The initial integration server served CSS with the wrong MIME type. This was a test-harness issue; the final styled replay loads the actual stylesheet, imports identical normalized audio, recompiles the preserved actual analysis, verifies preview navigation at a 393-pixel viewport, and verifies identical audio/FSEQ exports for all three projects. It does not repeat unchanged model inference. Its screenshots depict restored projects without restored OPFS audition samples; trained-source listening controls are verified separately by the studio/audition suites.

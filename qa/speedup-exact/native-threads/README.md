# Native Studio thread candidate — held from release

The eight-thread candidate is **not shipping in 2.2.5**. Production `NativeDeux.java`, its existing regression test and native release gate were restored byte-for-byte to their published 2.2.4 sources. The shipping budget remains `max(1, min(4, availableProcessors))`; MDX is unchanged.

The candidate passed two complete x86_64 host comparisons, but target Android/ARM64 optimized kernels and dispatch were not qualified. The pinned ORT source review found generic arithmetic-order risks, while the inspected Deux blocks avoid those specific paths. **No Deux-specific output divergence was demonstrated.** The release decision preserves the user's exact-output requirement without treating host evidence as an ARM64 guarantee.

| Full 13-second context | Original 4 threads | Candidate 8 threads | Less elapsed time | Complete output |
|---|---:|---:|---:|---|
| Glass Castle start | 53.51 s | 44.51 s | 16.82% | Byte-identical |
| Independent Falcon mixture | 54.57 s | 43.19 s | 20.84% | Byte-identical |

Each prediction contains two 573,300-sample stems: 4,586,400 bytes and 1,146,600 float32 values, all finite and exactly equal. The candidate's normal available-core policy selected eight threads on the host; its source was not patched to force the value. The Falcon float32 fixture was deterministically prepared as the same PCM16 input for both classes, preserving the existing native input contract. These timings do not establish whole-analysis throughput, physical-phone speed or memory savings.

`release-decision.json` is the current release decision and source inventory. It maps the original receipt's candidate bindings to snapshots in `candidate/`, records the restored production hashes and binds the architecture review. `verification.json`, `independent-review.json` and all four inference logs remain unchanged historical evidence. Their original references to production paths describe the tested candidate at that time, **not the restored production tree**.

`candidate/` preserves the tested native source, its policy test, the native release gate with the proposed policy assertion, and the exact benchmark harness. `reference/` contains the original predictor and test. `architecture-review/` contains the bounded primary-source assessment, official v1.25.1 source URLs/hashes and actual graph operator/shape inventories. Its scalar grouping counterexample is explicitly illustrative, not Deux or ARM execution.

Do not run the historical `verify.py` in the restored production tree: it expects the candidate policy and would overwrite the historical receipt. Reproduction requires an isolated copy with the archived candidate snapshots restored to their original paths, unchanged model/runtime/fixture pins and an uncontended host exposing at least eight Java processors. Reproduction is an experiment, not a release gate.

Earlier experiments also rejected larger independent batches as slower and concurrent Deux instances as poor memory tradeoffs: two two-thread instances gained only about 6.2% throughput while adding approximately 653 MB peak RSS. Neither is a production change.

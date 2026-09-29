# Owner-interrupt correction

The targeted host JNI reproduction failed before the correction and passed afterward for both temporal and frequency execution. These artifacts establish cancellation propagation and resource retirement. They do not establish complete-output recovery, performance improvement, physical-device behavior, or release qualification.

The original owner thread observed its interrupt and threw `InterruptedIOException`. Retirement then terminated the shared native RunOptions without publishing the runner's shared cancellation flag. The worker threads were not interrupted, so their native termination errors remained raw `OrtException` instances. The strict cancellation classifier correctly rejected that exception tree.

[The exact failed JVM log](before/owner-interrupt.log) retains the owner's original exception and four suppressed native termination errors. The assertion was changed to retain that exception as its cause before reproducing the failure.

The correction gives retirement separate callbacks for native termination and owner cancellation. An owner interrupt observed on entry, during executor retirement, or while draining Futures invokes the cancellation callback, which publishes shared cancellation before terminating native execution. Optional probe termination continues to use only the termination callback. The cancellation classifier was not weakened, and all original causes and cleanup failures remain retained.

[The targeted correction receipt](after/targeted-owner-interrupt.json) records seven observed concurrent JNI workers for temporal interruption and five for frequency interruption in `block-00-frequency`. Both tests verified worker and RunOptions retirement, preserved the owner interrupt flag, held the process gate until native workers retired, released the gate afterward, and left no committed or temporary output. The exact JVM outputs are [temporal](after/owner-interrupt-only.log) and [frequency](after/frequency-owner-interrupt-only.log).

The before and after directories preserve their original `receipt.json`, `compile.log`, and complete `source-snapshots/` bytes. Each compile receipt binds 14 input files, 51 compiled class identities, and the pinned JSON, Android API, and ONNX Runtime 1.25.1 JAR identities. The generated no-op host `AppDiagnostics.java` adapter is also archived. Compiled binaries are excluded; their hashes were checked against the retained receipt during archival.

The original `receipt.json` files are **compile-only receipts**. Their `inferencePerformed=false` and `passed=false` fields remain unchanged and describe that workflow. The separately invoked targeted JVM tests are evidenced by the original failure log and the after-run targeted receipt. There is no manufactured passing receipt for the failed run.

The harness modes are `owner-interrupt-only` and `frequency-owner-interrupt-only`, supplied after the model directory, demo WAV, and a new output directory when invoking `com.cyberbasslord.lightforge.NativeDeuxCalibrationTest`. Both use source sample 661500, eight allowed host CPUs, `-Xmx1g`, and `-XX:MaxDirectMemorySize=512m`. The full integration and performance runs remain separate evidence.

[archive.json](archive.json) describes the archival checks. [inventory.json](inventory.json) hashes every other archived file without changing any original receipt or log.

# Failed actual combined frequency integration attempt 01

This archive preserves the failed JNI integration attempt from the frozen
combined temporal B1/frequency B16 source. It is failure evidence, not a passed
integration or performance qualification.

The JVM reported `Native cancellation contained an unclassified cleanup failure`
at `NativeDeuxCalibrationTest.main:353`, the owner-thread interruption check.
The preceding reference, unknown-work, short-work, automatic first-passage, and
forced four-worker runs produced complete outputs. The preceding caller-cancel
check returned; the later frequency cancellation and eight-worker recovery
checks were not reached.

All five surviving PCM files were independently checked at archive time: each
contained 4,586,400 bytes, all finite Float32 samples, and the original complete
demo SHA-256 `d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`.
Their filenames and verification results are in `archive.json`. PCM is omitted.

`receipt.original.json` is copied byte-for-byte, including the misleading
`inferencePerformed=false`. The frozen wrapper sets that field to true only
after the JNI invocation succeeds and validates, so the field does not describe
this failed execution accurately. Actual inference occurred, as shown by the
JVM log and complete surviving outputs. The original record is deliberately not
rewritten. The wrapper and JVM logs are retained verbatim.

`source-snapshots.json` contains the complete frozen source text, including the
host diagnostics stub. The original receipt retains all compiled-class and
dependency hashes; source bindings and the surviving class files were checked
against them at archive time. No inference was rerun to create this archive.
Subsequent corrections and their validation require separate evidence.

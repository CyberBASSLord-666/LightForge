# Owner-interrupt fix: current compile and portable checks

Both Android-first and host-JSON-first compilations passed after the owner-interrupt propagation fix: the same eleven production/test Java sources produced 61 classes in each order with no compiler diagnostics. All source hashes remained unchanged during compilation. The adjacent compile receipt is an unchanged copy of the successful scratch receipt.

The separately archived current portable suite passed 642 tests: 571 repository-defined current Python/JVM tests and 71 tests in the five explicit quality-tool scripts. Its source hashes remained unchanged before and after execution. The two historical source-hash suites remain excluded exactly as defined by the existing production portable gate; all older evidence is retained unchanged.

This snapshot includes the validation-wrapper receipt correction. Subprocess attempts are checkpointed before launch; exit codes, timeouts and launch failures remain distinct from verified neural work. Unverified execution reports `inferencePerformed: null`, compile-only execution remains false, and validated inference becomes true. A prior verified run is retained if a later attempt fails. The wrapper does not set `passed` until every gate succeeds. Five small subprocess regressions cover these distinctions without model inference.

These are compile and portable checks, not actual-JNI or device-performance qualification. Original failed integration receipts and the earlier 637-test snapshot are preserved.

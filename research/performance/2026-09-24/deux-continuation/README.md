# Prepared Deux continuation

`deux_retry.py` reuses the verified Colab assets and toolchain after GAME has
stopped. It pins source `8590ac4a67de4340857a96ffe38bae53d7d902b8`, verifies
the original public APK and demo, extracts and checks all 27 Deux graphs,
and runs the unchanged readiness and accelerator harness into a new evidence
directory. All original notebook globals and evidence stay intact.

The original harness runs eight diagnostic passes and retains numerical
differences without admitting timing. If all exact-output checks pass, its
existing repeated-timing path remains unchanged. The script never turns a
nonzero diagnostic exit into quality approval. Use `export_deux.py` after
completion or interruption to retain complete outputs, traces and receipts.

This is a prepared procedure, not an executed result. The subsequent existing
`tools/compare_deux_downstream.cjs` requires fresh CPU/CUDA waveform captures,
unchanged original assets, Node >=22 and the exact expected upstream evidence.
It examines only the first committed five-second separated-vocal excerpt.

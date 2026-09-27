# Deux downstream sensitivity — September 24, 2026

The unchanged paired consumer check returned **`EXCERPT_SENSITIVITY_PASS`** on the first committed five seconds of the public demo. Both CPU/ALL and CUDA/BASIC separation outputs produced exactly matching final transcriptions and fused vocal results: 25 raw notes, 25 fused notes, 4.72 seconds of fused-note coverage and one non-speech phrase. All existing sensitivity and coverage rules passed without modification.

Frame-MN10's largest singing-score difference was `6.556510925292969e-7`; its largest speech-score difference was `1.043081283569336e-6`. Raw GAME checkpoints were **not** byte-identical. This is evidence about downstream sensitivity to the captured separation differences; it does not resolve the upstream `NUMERICAL_EQUIVALENCE_UNPROVEN` gate or admit speed ratios.

The run used original GAME Large with all eight steps, Frame-MN10 and the original ONNX Runtime Web 1.20.1 assets, recovered from the verified public APK. Each arm recorded all six expected models and the declared graph-call counts. The source snapshot is pinned to commit `8590ac4a67de4340857a96ffe38bae53d7d902b8`, tree `c841bf18f91d3d04dd6daf7e886e2aa473ab8c70`. The existing source checkout and comparator were unchanged. Research Node 22.19.0 was verified against its official archive checksum before execution.

The independent audit checked the ZIP's 49 members and CRCs, all 48 recorded artifact hashes, 25 frozen source files, 21 strict JSON files, parent process/setup bindings, and all four captured/profiled waveforms. It independently replayed the original separator consumer and reproduced all four resampled WAVs byte-for-byte, then recomputed the complete original sensitivity comparison from the stored outputs. It did not repeat model inference. Model and Node binary hashes are runtime records; those binaries are excluded from this archive. Full upstream CUDA/native-library verification belongs to the separately retained Deux accelerator archive.

Archive: `20260924T022132Z-deux-downstream-6d762cd1.zip`, **17,147,976 bytes**, SHA256 `310cc5697489fd89fe2a34afa7bb50678e515001add74784604eb1aaa3b4b06f`.

See [verification-report.json](verification-report.json), [verify_evidence.py](verify_evidence.py), and the unchanged compressed comparator receipt. The auditor requires the exact ZIP, this repository's frozen Git objects, and the original `web/demo/glass-castle.wav`; it writes only to a new output directory.

This five-second bounded excerpt does not test a second measured overlap, complete-song context, a representative quality corpus, CUDA vocal inference, transfer overhead, Android or physical devices. **Quality, benchmark timing, release and 75% target approval remain false.**

# Balanced native MDX qualification

The three-passage decoded-output qualification and paired real-model singing-note comparison have passed. The internal-spectrum diagnostic remains failed. The production model, ONNX Runtime 1.25.1, ALL graph optimization, four-thread maximum, trained FFT geometry, polarity ensemble and decoder are unchanged by this validation work.

## Protocol history

The first comparator applied an absolute limit of 0.0001 to unnormalized complex FFT coefficients. It failed, despite very small normalized audio differences. The next protocol used a fixed per-coefficient allowance of `0.0001 + 0.00001 * abs(reference)` and retained RMS limits. That also failed on a few coefficients. These were actual failures; the original comparator and failed receipt remain in `initial-mdx-absolute-only/`, and the first revised attempt remains in `revised-mdx-first-run/`.

Changing native graph optimization passed the coefficient check on one passage but failed it on a second. Single-thread execution did not remove the discrepancy. Those experiments therefore did not justify changing production execution options.

## Revised release boundary

The release contract was revised **after those failures**, following independent review. Downstream singing and note models consume the normalized decoded waveform, not the internal complex spectrum. Qualification therefore requires the following on three fixed inputs: the bundled demo's first context, a non-overlapping context starting at sample 878160, and the independent licensed Falcon mixture's first context.

- Exact model hashes, dimensions, sample counts, timing and both polarity passes; finite spectra and waveforms throughout.
- Normalized decoded audio maximum absolute error at most `1e-6`, RMS error at most `1e-7`, and relative RMS error at most `1e-4`.
- A separate paired run of actual production resampling, vocal evidence and eight-step GAME transcription. It must contain meaningful sung-note coverage and meet fixed categorical, pitch, timing and feature checks.
- Source hashes must remain unchanged during execution and match the final candidate.

The waveform peak limit is less than one thirtieth of a normalized signed 16-bit PCM step. This is a numeric compatibility bound; it does not establish perceptual accuracy or guarantee equivalent predictions on every song.

The unchanged coefficient thresholds remain diagnostic. Their failed results must stay visible as failed spectral checks even if decoded-output qualification passes. No receipt may claim bit-identical spectra or that every numeric comparison passed. Publication still requires the separate Android background, cancellation, recovery, diagnostic-export and original-signature package gates.

The three audio comparisons had worst normalized peak error `2.5332e-7` and worst relative RMS error `2.4580e-7`. Both downstream runs produced 16 GAME notes and 16 fused sung notes with 5.02 seconds of sung-note coverage, and passed the fixed timing, pitch, classifier and feature limits.

Three reference passages and one paired downstream test are bounded development evidence. They are not a corpus benchmark, a held-out-training claim, physical ARM/Samsung validation, a long-song performance guarantee or Tesla timing certification.

# Spleeter evaluation baseline

These assets are an evaluated comparison, not the production LightForge 1.6 separator. The production UVR MDX-Net Voc FT model achieved higher SI-SDR on all six short development excerpts. Results and limitations are recorded in `qa/release-1.6.0/separator-quality-comparison.json`.

The source archive retains baseline code, pinned model metadata, licenses and this download helper. The unused Spleeter model binaries are excluded from the APK and source package to avoid duplicating 79 MB of evaluation weights.

To reproduce the baseline, run from the project root:

```sh
python3 research/evaluation-1.6/download-models.py
node qa/release-1.6.0/test-separator.cjs
```

The helper verifies both exact size and SHA-256 before publishing downloaded files. It downloads the original converted graphs pinned to their provider's commit, without any inference API or credentials. Fixture audio is obtained through the separate MUSDB fixture preparation workflow and has its own attribution terms.

Historical Spleeter inference receipts were recorded before the comparison files moved out of `web/analysis`. Their hashes still identify these identical bytes; path relocation does not claim a new inference run.

## Measured final results

The selected MDX model uses two polarity passes and 50% overlapping source windows. The comparison also ran the Spleeter baseline, the HTDemucs FT vocal specialist, four deterministic Demucs shifts, and a fixed equal MDX/Demucs waveform blend. Blend weights were declared before scoring; there was no reference-fitted weight or timing correction.

| Separator | Mean vocal SI-SDR, six mixtures | Mean vocal-envelope correlation | Worst backing-only vocal energy relative to mix |
| --- | ---: | ---: | ---: |
| Spleeter two stems | 5.92 dB | 0.8669 | −25.44 dB |
| HTDemucs FT, center padded | 8.62 dB | 0.9230 | Not captured for this variant |
| HTDemucs FT, four deterministic shifts | 8.69 dB | 0.9227 | −36.33 dB |
| MDX Voc FT, polarity ensemble | **10.04 dB** | 0.9204 | −33.98 dB |
| Fixed equal MDX / four-shift Demucs blend | 9.98 dB | **0.9330** | −40.00 dB |

MDX improved SI-SDR over Spleeter on each of the six natural mixtures. The blend helped the difficult Falcon excerpt but reduced four other positive SI-SDRs, including worse SDRNR dynamics. The selected MDX path has the strongest overall separation-fidelity result on this limited set; it is not a universal best-model claim. No processing-speed criterion decided the winner.

The final app's vocal envelope is measured separately from raw separated waveform quality. It includes confidence gating, local expression normalization and articulation decisions:

| Final detail behavior | Natural mixtures | Controlled vocal remixes |
| --- | ---: | ---: |
| 1.5 tracks with voice cues | 5 / 6 | 5 / 6 |
| 1.6 tracks with voice cues | 6 / 6 | 6 / 6 |
| 1.5 mean envelope / original-vocal RMS correlation | 0.4445 | 0.7202 |
| 1.6 mean envelope / original-vocal RMS correlation | 0.8331 | 0.9652 |
| 1.5 total articulation markers | 9 | 12 |
| 1.6 total articulation markers | 116 | 69 |

All six no-vocal backing remixes produce zero final voice phrases, articulations and notes. More articulation markers alone would not prove better choreography; the envelope agreement and no-vocal regressions provide independent context. NightOwl remains *uncertain singing*, even when its actual separated voice now produces useful conservative cues. It is not mislabeled as certain singing to improve a headline count.

A 41.531-second clock fixture puts four real source excerpts at non-grid positions with known silence between them. Actual MDX processing produces exactly 1,831,517 samples across 14 contiguous chunks / 28 model passes. Each source-window envelope has zero measured lag at the 5 ms measurement spacing. The overall source-envelope correlation is 0.99694. Small waveform residuals remain in silence; no claim of perfect separation or universal 5 ms perceptual accuracy follows from this regression.

## Evidence scopes and release binding

- `quality-studio-*.json` is the first complete 18-case **public worker** pass. Early cases predate the final weak-voice fallback and are preserved unchanged.
- `detail-candidate-*.json` is the **final production detail replay** for all 18 cases: actual recorded MDX estimates → production float downsampler → actual Frame-MN10 classifier → final detail. Original studio vocals are never substituted as input. The final comparison table above uses this replay.
- `quality-final-nightowl-controlled.json` reruns the previously missed case through the complete final public worker. Its two uncertain voice phrases, seven articulations, no invented pitch notes, and complete envelope/contour arrays match the final replay exactly.
- `public-analysis-cancel-verification.json` contains three actual analyzer cancellations while MDX owns an incomplete writable OPFS cache. An observed cleanup race was fixed; all three retries remove the new namespace within approximately 3.5 seconds.
- `analysis-verification.json` verifies the final processing sources and five active bundled model graphs by SHA-256. Historical Spleeter and Demucs candidate evidence is separate from active app models.
- `integration-verification.json` separately records actual app file import, inference, compilation, WebGL preview, save/reload and ZIP export, including an original-user-audio prefix. It also verifies preservation of the prior show on cancellation and a deliberately failed model read. This is desktop browser evidence, not physical Android/Tesla execution.

The first-pass and final-replay distinction is intentional and visible. Recomputing unchanged heavy separator outputs adds no evidence about a later threshold fix; the final public-worker regression and actual app flows cover the integration boundary.

# Dense estimator memory stress

The fresh 4-GiB parallel GAME admission budget is insufficient for the maximum observed estimator dimension.

The unchanged five production GAME models ran on 705,600 float32 samples (16 seconds at 44,100 Hz), including all eight diffusion steps. Only the final bd2dur and estimator boundary inputs were replaced with a boundary at each of the 1,600 frame positions. This yielded 1,601 estimator slots. All five model hashes match the bundled manifest.

| Measurement | Bytes | GiB |
| --- | ---: | ---: |
| Normal 16-second fixture, 43 retained notes | 1,636,130,816 | 1.524 |
| Dense synthetic boundary stress, 1,601 estimator slots | 2,429,222,912 | 2.262 |
| Two dense peaks plus 512-MiB reserve | 5,395,316,736 | 5.025 |
| Proposed fresh available-memory threshold | 6,442,450,944 | 6.000 |

Fresh available memory of at least 6 GiB leaves about 1.475 GiB beyond the two measured dense peaks. Keep the existing 64-bit, core-count, total-memory, low-memory, single-thread, and durable interruption guards. Root owns the final admission decision; production was not changed by this probe.

This is an artificial allocation stress on a synthetic 16-second tiling of an actual separated vocal excerpt. It is not an analysis output, a quality comparison, or Android WebView memory qualification. It measures one passage; device allocator behavior and repeated inference remain separate limits.

The process finished successfully in 96.75 seconds and reported its own peak RSS through process.resourceUsage().maxRSS. An attempted external /proc RSS guard read the wrong PID because the process namespace differed from the mounted /proc view. Its reading is explicitly invalidated in the receipt; no enforcement is claimed for this run. The corrected watchdog uses an independent Node worker thread and process.memoryUsage().rss, and successfully killed a disposable process under a deliberately low limit. The model stress was not rerun merely to repair this auxiliary monitor.

# Four-Worker complete-passage host evidence at `9435489`

This fresh run uses the original 27 graphs, pinned ONNX Runtime 1.25.1,
original demo passage, fresh JVMs, and seven observed child CPUs with one
quota CPU reserved. It excludes a warmup pair and measures three alternating
AB/BA/AB baseline/candidate pairs. No release-gate receipt was changed.

A previous preliminary local run was lost in a scratch reset; its full receipt, logs and profiles were not retained and are not evidence for this archive.

All eight outputs are finite and byte-identical (SHA-256 `d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`). Baseline uses 335 calls; four-worker uses 1,727 calls with full 27-graph coverage.
Measured wall reductions: **31.1723%, 40.3602%, 45.1970%**. Median passage wall: **91.648495195 → 51.682151079 seconds**, **43.6083%** reduction. Median process CPU: 239.21 → 174.33 seconds. Median peak RSS: 843,960,320 → 984,776,704 bytes. Maximum throttle/wall ratio: 0.0201%. No OOM: True; no memory-limit event: True; no direct reclaim: True. Host thresholds met: True.

`receipt.json` is the unchanged run receipt. The archive contains the exact
logs, profiles, frozen source snapshots and a bounded SHA-256 file inventory.
It omits output PCM, model graphs, compiled classes, audio and scratch partials.
Any partials observed later in scratch are recorded by size/hash only; the
workspace overlay may rehydrate old snapshots after JVM exit.

This is fixed host execution geometry, not physical-phone admission,
sustained policy, qualification payback or whole-analysis speed evidence.

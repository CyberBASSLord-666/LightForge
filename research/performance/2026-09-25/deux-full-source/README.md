# Complete public-source Deux CPU diagnostic

This isolated research driver collects the original twelve Deux contexts for
the complete public 64-second `glass-castle.wav`, once plain and once with ORT
profiling. Both fresh JVMs keep one original `NativeDeux` object for their full
source. The unchanged engine still retires its 27 sessions after every passage;
the original object already amortizes model verification and runtime startup.
All 27 original Float32 graphs, 335 graph calls per passage, clocks and overlap
geometry remain unchanged. There is no production application edit.

The collector must finish all 24 predictions and prove all twelve plain/profiled
outputs byte-identical. The next stage feeds those actual captures through the
unchanged production separator, binary checkpoint and stem-cache modules. It
checks interrupted and checkpoint-only reconstruction and reopens the three
saved public-derived WAVs. The in-memory file adapter establishes consumer
correctness only; it does not establish Android storage or lifecycle behavior.

Cold single-passage timing must not be multiplied by twelve or used to predict
a 75% complete-analysis reduction. In the prior CUDA passage diagnostic, the
5.719-second model-init total included 3.290 seconds in the first front-session
constructor and 2.410 seconds across the remaining 26 sessions. Runtime and
cache initialization are already amortized by the original same-object sequence.
The actual complete-source control is required before interpreting any proposed
bounded session-retention experiment. Instrumented or concurrently collected
wall time remains diagnostic, with no admitted speed ratio.

## Frozen execution

Prepare original model and runtime assets separately. `restore_deux_assets.py`
extracts manifest-bound original graphs from the hash-verified public v2.3.1 APK
and binds its receipt to the existing host preparation receipt. It performs no
inference. The driver requires those original receipts and the exact public WAV;
models, APKs and runtime binaries are never included in the evidence archive.

Commit the driver, collector and all bound helpers before running. Use the full
new commit and corresponding tree, a fresh output directory, and these existing
asset paths:

```sh
python3 research/performance/2026-09-25/deux-full-source/run_local.py \
  --source-commit COMMIT --source-tree TREE \
  --toolchain /workspace/scratch/b9f08ad0c73c/lightforge-host-research-toolchain \
  --models /workspace/scratch/b9f08ad0c73c/lightforge-host-assets/deux \
  --public-wav /workspace/scratch/b9f08ad0c73c/lightforge-host-assets/glass-castle.wav \
  --output /workspace/scratch/b9f08ad0c73c/new-deux-full-source-run
```

The driver verifies exact Git blobs before execution and rechecks all source
copies, 27 graphs and manifest, CPU ORT/SDK/JSON dependencies, complete installed
JDK file/link inventory, pinned JDK archive, observed Node binary, original WAV,
provenance and both preparation receipts after production replay. The complete
child workflow has one shared 90-minute deadline with owned descendant cleanup;
interruption or failure retains a rejected driver receipt. Input preparation
failure may happen before the runtime inventory is complete and cannot be
exported as a fully bound archive.

```sh
python3 research/performance/2026-09-25/deux-full-source/export_evidence.py \
  --run /workspace/scratch/b9f08ad0c73c/new-deux-full-source-run \
  --output /workspace/scratch/b9f08ad0c73c/new-deux-full-source-evidence.zip
python3 -m unittest discover -s tests -p test_deux_local_driver.py -v
```

The exporter admits only exact copied execution sources, reviewed collector
paths, original public input, three derived consumer WAVs, receipts and logs.
It rejects links and unknown paths, hashes every member, checks file/count/total
bounds, verifies ZIP CRCs and prints the archive SHA-256. All quality, timing,
75%, Android, full-vocal-stage and release claims remain false. Full vocal
classification, GAME on the newly separated voice, fusion, bass, show generation
and complete-analysis timing are later stages and are not performed here.

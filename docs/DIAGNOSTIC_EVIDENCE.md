# Local diagnostic evidence

Published 2.4.1 diagnostic receipts and host performance evidence remain
historical. The [unreleased device-regression correction](../research/inference-device-regression-20260928/README.md)
adds complete-passage policy evidence and mixed scheduling counts. Its observed
phone regression is documented separately from uncontrolled device conditions;
these records do not establish a new device speedup or thermal explanation.

`tools/diagnostic_evidence.py` extracts observations from the UTF-8 Android diagnostic export without uploading it. Python's standard library is sufficient:

```sh
python tools/diagnostic_evidence.py --report /private/report.txt --output /private/observations.json
python -m unittest discover -s tests -p 'test_diagnostic_evidence.py'
```

The output must not already exist. Keep original reports and generated observations outside the repository. No raw logs, filenames, absolute timestamps, job/passage identifiers, stack traces, project names or arbitrary field values are copied into the output. Source line numbers and relative event offsets support local inspection. The current environment is a separate technical snapshot; it does not establish the version used by older events.

The JSON contains:

- Separate attempts with explicit/missing start boundaries and observed terminal states. `fresh` means an explicitly started attempt with zero-restored-stage observations; **cold caches are never assumed**. Any observed restoration marks the attempt `resumed`. A rotated earlier window remains `historical_partial` unless restoration is observed; its missing start remains explicit.
- Inclusive stage intervals, individual native/vocal passages, restored versus executed vocal work, and native profile aggregates. Completed profile bundles, incomplete bundles, non-completed outcomes and orphan detail records remain separate. A complete bundle means its declared detail counts were retained without dropped or duplicate records; missing numeric metrics still remain unavailable.
- Interruption-to-next-attempt gaps, renderer failure events and completed-preview frame intervals. A chronological next attempt is not verified parent/resume lineage. Interruption gaps are excluded from compute totals.
- A separate current-job snapshot. Its elapsed time is never substituted for original full-song analysis time.

`observed` includes a genuine reported zero. `partial` contains an `observed_subtotal` and a null complete `value`. `unavailable` keeps missing, invalid and explicitly unavailable values distinct. An unfinished passage records only its observed partial interval. Profile metric summaries include observed/population counts, missing/unavailable/invalid counts, minimum, maximum and mean. Stage and passage duration keys use milliseconds. Native field suffixes preserve their units; passage-policy `*Nanos` values retain exact integer nanoseconds.

Native bundles accept the optional `engine-init` stage emitted during engine initialization. A producer's `cpuTelemetry=partial` remains a distinct telemetry observation; unavailable CPU totals are not filled from wall time or assumed to be zero.

Stage, passage and native profile intervals overlap: do not add them together. These diagnostics cannot establish a controlled baseline, complete job lineage, a 75% speedup, or unchanged musical quality. Full-song runtime remains unavailable until those observations are collected separately. The tool intentionally does not change release policy or qualify a release.

## Compact Android job summaries

New diagnostic exports include `DURABLE ANALYSIS SUMMARIES`, independent of the
1 MiB rotating event trace. A fixed-schema, checksum-checked atomic file retains
the latest three jobs. Only a hashed job reference, fixed state/stage/route enums,
creation/observation times, duration, analysis quality, restoration counts,
numeric measurements and bounded allowlisted policy evidence are stored.
The current-job header uses the same hashed
reference; no media name, audio, transcript, path, VIN or raw job ID enters this
store.

Stage boundaries bypass ordinary progress throttling. Durations accumulate from
observed monotonic intervals; a process restart increments `recoveryGaps` and
excludes the unobserved interval from stage timing. `lifecycleElapsedMs` separately
uses the job wall clock, includes final project saving and interruptions, and
freezes at the first terminal observation. It can differ from summed stage time.
Active progress is checkpointed at most every 30 seconds apart from stage
changes and finalized native receipts. A crash can therefore lose the latest
uncommitted progress interval or unfinished passage; this is not an exact record
of an unobserved termination time.

Native totals distinguish Deux and GAME, completed/cancelled/other outcomes,
model/session preparation, production inference calls, and scheduler calibration
cost. Every metric includes its measured-passage count. A subtotal with fewer
measurements than attempted passages is partial, never a complete total or a
synthetic zero. Retries and failed attempts remain included as work. Thread CPU
means the calling thread; process CPU covers all app threads.

The correction's `diagnostic-job-summary-v2` preserves the latest complete
controller snapshot: raw qualification/recheck pairs, complete output digest,
finite/exact/geometry checks, decision reasons, extra-work cost and lease state.
`projectedAccruedSavingsNanos` is a conservative payback projection labeled
`projected-not-measured`, never a measured whole-job saving. Mixed baseline,
four-worker, eight-worker and unobserved temporal session counts describe
initialization attempts; the last configuration alone cannot describe a mixed
passage. Candidate probe costs remain separate from production graph totals.
The binary reader accepts the previous summary format and upgrades it atomically
without inventing missing historical counts. The three-job, 32 KiB storage bound
and privacy restrictions remain unchanged.

The offline extractor supports both summary versions as `durable_job_summaries`,
removes job references and absolute timestamps, and retains only a boolean
association to the current job. It accepts readable and encoded policy snapshots
without counting them as additional passages. Failed-pair flags remain observations;
the extractor does not qualify a schedule. Duplicate, inconsistent, truncated or
unsafe records cannot become valid evidence, and orphan records after trace
rotation are not assigned to an invented passage. Missing mixed-session metrics
remain unavailable or partial. The current snapshot and trace measurements stay
separate; a compact receipt is observational evidence, not a controlled
performance or quality qualification.

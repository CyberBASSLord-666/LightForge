# Local diagnostic evidence

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

`observed` includes a genuine reported zero. `partial` contains an `observed_subtotal` and a null complete `value`. `unavailable` keeps missing, invalid and explicitly unavailable values distinct. An unfinished passage records only its observed partial interval. Profile metric summaries include observed/population counts, missing/unavailable/invalid counts, minimum, maximum and mean. All duration keys are milliseconds; native field suffixes preserve their original units.

Native bundles accept the optional `engine-init` stage emitted during engine initialization. A producer's `cpuTelemetry=partial` remains a distinct telemetry observation; unavailable CPU totals are not filled from wall time or assumed to be zero.

Stage, passage and native profile intervals overlap: do not add them together. These diagnostics cannot establish a controlled baseline, complete job lineage, a 75% speedup, or unchanged musical quality. Full-song runtime remains unavailable until those observations are collected separately. The tool intentionally does not change release policy or qualify a release.

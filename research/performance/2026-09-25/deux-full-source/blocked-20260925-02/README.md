# Retained blocked Deux CPU retry — September 25, 2026

Status: **BLOCKED_OR_REJECTED**. All twelve plain predictions returned and
wrote passage receipts, but the collector rejected unexpected temporary files
before admitting the plain arm. Its accepted `runs` list is empty. **No profiled
arm or production stem replay ran.** This is not a complete qualified diagnostic.

The execution source was commit
`925fc91ecb198141901ef62eb55feb7d7e43c3a0`, tree
`8d2160d126bf0adb5698a94471c44cd09b8df36b`. The exact failure was
`ValueError: Unexpected passage output member.` Eleven `.native-deux-*.partial`
files are retained: one empty file in passage 000, and one 2,293,200-byte file
in each of passages 002–011. Every nonempty partial is byte-identical to the
first, vocal half of that passage's 4,586,400-byte final stem output. This
observation does not authorize deleting the files or accepting the run. Their
origin or recreation mechanism remains unknown.

The failed directory was not changed. [preserve_blocked.py](preserve_blocked.py)
requires this exact rejected commit/tree, checks all 22 execution source copies
against Git, validates the exact public fixture and original output pins, and
uses the unchanged frozen exporter against a new scratch snapshot. It checks
all original files again afterward. The exporter already permits the explicit
partial-file pattern for preservation; the complete-output gate remains strict.
The ZIP contains all 181 original raw files plus its archival inventory.

| Preserved item | Binding |
| --- | --- |
| Archive | `deux-full-source-cpu-20260925-02-blocked.zip` |
| Bytes | `81825943` |
| SHA-256 | `26562c5287f83f252c7cb5f4139ba9bd87c006fccf632a4d662324dab3e635cd` |
| Archive members | `182`; every CRC and inventory hash checked |
| Parts | `110`; 109 parts of 750,000 bytes and one of 75,943 bytes |
| Completed passage receipts | Plain: `12`; profiled: `0`; accepted collector runs: `0` |
| Integrity report | [verification.json](verification.json), `VERIFIED_INTEGRITY_BLOCKED` |
| Original partial metadata | [partial-file-observations.json](partial-file-observations.json) |
| Part inventory | [raw/manifest.json](raw/manifest.json) |

Reconstruct into a new path:

```sh
python3 reconstruct_archive.py /path/to/new-deux-retry02-blocked.zip
```

The reconstructor pins the manifest, every part, and the complete ZIP. The
`modelInferenceExecuted: false` fields in the inspection reports describe the
preservation operations; the archived run itself performed CPU inference.
No accepted timing ratio, 75% reduction, musical quality, CUDA, Android,
full-vocal-stage or release approval follows from this archive.

# Retained blocked Deux CPU experiment — September 25, 2026

Status: **BLOCKED_OR_REJECTED**. The archive is intact; the complete diagnostic
was not qualified. No accepted speed ratio, 75% reduction, musical-quality,
CUDA, Android, full-vocal-stage or release approval follows from this evidence.

The frozen execution source was commit
`85bca325b65f93790a17bfd9142dad80162384b2`, tree
`b703f823fb7da8f36eb4461c4f139ddda0df2038`. The run used the original models
and public 64-second source. It retained **12 completed plain passage receipts
and 4 completed profiled passage receipts**. During profiled passage index 4
(the fifth passage), the collector rejected 54 active trace files where it
required exactly 27. Of these files, 27 were byte-identical copies of the
already-retained passage-003 traces; 27 belonged to the current passage.
The actor or mechanism that recreated the prior trace files is **not established**.

The original failed run and ZIP were not repaired or edited. Collection stopped
before complete plain/profiled qualification and production stem replay. These
partial receipts must not be substituted for the missing complete diagnostic.
The `modelInferenceExecuted: false` fields in the adjacent verification and
diagnosis JSON describe those read-only inspection operations; the archived
experiment itself did execute CPU inference.

| Preserved item | Binding |
| --- | --- |
| Original archive | `deux-full-source-cpu-20260925-01-blocked.zip` |
| Bytes | `132558003` |
| SHA-256 | `41d0ca6a25ddfa80a325ae71d5ad9930cf6d9a78480d6c63461c6abe3a14f624` |
| Archive members | `383`; member CRCs, inventory pins and 21 exact Git source files checked |
| Parts | `177`; 176 parts of 750,000 bytes and one of 558,003 bytes |
| Integrity result | [verification.json](verification.json), `VERIFIED_INTEGRITY_BLOCKED` |
| Trace observation | [trace-failure-diagnosis.json](trace-failure-diagnosis.json) |
| Part inventory | [raw/manifest.json](raw/manifest.json) |

Reconstruct into a new path:

```sh
python3 reconstruct_archive.py /path/to/new-deux-blocked-evidence.zip
```

The reconstructor pins the manifest bytes, every part, and the complete original
archive. It refuses an existing output. Reconstruction establishes identity,
not successful model qualification. The adjacent [integrity verifier](../verify_blocked_archive.py)
can repeat the archive inspection without executing models.

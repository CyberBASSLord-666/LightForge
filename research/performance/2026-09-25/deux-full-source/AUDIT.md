# Independent complete-source CPU audit

`verify_evidence.py` accepts a completed run directory or a digest-pinned ZIP.
It performs no model inference and writes only to a fresh audit directory.

```sh
python3 research/performance/2026-09-25/deux-full-source/verify_evidence.py \
  --source-commit 85bca325b65f93790a17bfd9142dad80162384b2 \
  --run-directory /path/to/completed-deux-run \
  --output-dir /path/to/new-audit
```

For an archive, replace `--run-directory` with `--zip`, `--expected-size` and
`--expected-sha256`. The expected commit and archive digest must come from the
preserved execution checkpoint, not be silently accepted from the archive itself.

The audit checks exact Git source bytes before importing archived helpers,
original model and public WAV identities, recorded runtime/preparation bindings,
generated Java/class inventories, all 24 passage receipts, twelve raw Float32
observer comparisons and all 324 profiled graph sessions containing 4,020 graph
calls. It independently recomputes provider placement from the raw traces.
Unrecognized paths, symlinks, duplicate JSON/ZIP entries, nonfinite JSON and
oversized inventories are rejected.

It then runs the exact archived production consumer with inference disabled,
reproduces all three saved WAVs and compares the entire fresh receipt with the
original receipt. No receipt fields are ignored. This repeats source decoding,
overlap, binary-checkpoint interrupted recovery, checkpoint-only recovery and
verified stem-cache readers. Complete input inventories are hashed again after
the audit.

Runtime and model binaries are intentionally absent from the archive. Their
recorded identities and preparation relationships are audited, but the auditor
does not independently execute or recompile those binaries. Compiled classes
are hash-checked, not executed. The independent replay records its own observed
Node binary and does not reinterpret the original collection's timing.

Application source is compared with research baseline
`efd95eb04068a7470490e34d729020f81efcab56`. That baseline already enabled the CPU
arena and memory-pattern settings in `NativeDeux`; those settings differ from
the public v2.3.1 APK's source tag. The 27 model graphs and public WAV are original
to that APK. The audit makes no claim that the research application source is
identical to the released APK's application source.

Successful verification remains a CPU diagnostic. Quality, GPU performance,
Android integration, a complete vocal stage, the 75% target and publication are
not approved by it.

```sh
python3 -m unittest discover -s tests -p test_deux_evidence_auditor.py -v
```

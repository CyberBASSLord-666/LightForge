# Device regression correction — unreleased

The supplied 2.4.1 phone run did not reproduce the earlier host speedup. This
work does not establish a physical-device or whole-analysis improvement yet.
The production version and release artifacts remain unchanged. The existing
source-bound release prerequisite must continue to reject these changed sources
until new evidence supports the next release.

## Observed regression

The retained 2.4.0 and 2.4.1 diagnostics describe the same phone model, Android
version, precision mode and 176.513492-second input duration. They do not prove
identical audio bytes or controlled phone conditions.

| Observation | 2.4.0 | 2.4.1 |
| --- | ---: | ---: |
| Complete job lifecycle | 3,086,737 ms | 3,844,483 ms |
| Matching retained passages 17–35, total | 1,489,929 ms | 1,907,049 ms |
| Matching retained passages, median | 77,816 ms | 104,268 ms |

The complete job took 24.55% longer; matched retained passage time increased
28.00%. The new separation stage consumed 3,321,384 ms (86.39% of the job).
Scheduler probes accounted for 69,256 ms, so probe overhead alone cannot explain
the regression. The summaries reported an eight-worker final configuration but
did not retain the deciding measurements or mixed-configuration counts.

The frequency graphs also slowed despite an unchanged configuration. CPU
availability, contention and thermal effects are possible contributors; the
logs do not establish which caused the change. Export-time resource snapshots
cannot describe conditions during the earlier inference. Overlapping worker
call durations must not be summed as elapsed passage time.

## Corrective implementation

- A cold, complete 60-band graph may nominate four or eight workers. It cannot
  authorize the production fast path. Warm graph-only admission is removed.
- Three alternating complete-passage comparisons are spread over useful passage
  ordinals 0, 4 and 8. Both arms use fresh original sessions, identical observer
  settings, Float32 outputs and full 27-graph geometry. Baseline output remains
  the useful output of a paired passage. Complete finite outputs must hash
  identically; every pair must improve by at least 5%, and the median by 15%.
- Extra work, including screening, comparison and interrupted probes, consumes
  a 360-second budget. Checks occur at existing safe native boundaries, so an
  in-flight native call can overrun a time checkpoint. A conservative payback
  projection includes future checks and a 10% margin. It is labeled projected,
  not measured whole-job savings.
- A qualified schedule earns an eight-passage lease, then twelve-passage leases
  after renewed comparisons. Sustained slowdown triggers an earlier recheck.
  Failed, unaffordable, mismatched or memory-constrained execution latches the
  original baseline for the job. Cached evidence requires a fresh full pair.
- The JS separator supplies a bounded count of checked, uncached, non-silent
  useful passages. Unknown and short jobs cannot finance qualification.
- Durable diagnostics retain raw qualification/recheck pairs, explicit extra
  cost, decision reasons and actual temporal session configuration counts.
  Probe observations remain separate from production graph totals.
- Cancellation preserves native retirement: every worker and session stops
  before its run options, crash lease and process gate are released. Only a
  specifically identified optional Run rejection can use the fallback path;
  construction, retirement and other failures keep their normal error path.

No graph, trained weight, precision, attention context, band/frame coverage,
sample clock or output length is reduced. Historical 2.4.1 proof files remain
historical and are not rewritten as evidence for this correction.

## Validation status

Production Java compilation and the current portable checks passed: 702
JavaScript tests and 599 Python/quality-tool tests. The repository's existing
exclusions for immutable 2.2.2/2.2.3 historical receipts were not changed;
unrestricted discovery still rejects their old source hashes. The Python
commands, counts and logs are retained alongside this document.

`host-parallel-qualification.json` binds the corrected production sources to
eight complete original-model executions. All outputs are byte-identical and
finite. The three measured baseline/candidate pairs reduced median passage
time from 52.734780 to 35.551003 seconds, **32.585282%**. This is a controlled
host result for the execution geometry, not an Android, sustained-policy or
whole-analysis speedup claim.

The original-model integration JVM passed all six complete-output checks,
unknown/short-work admission, legacy-cache rejection, a real first automatic
pair, cancellation and owner interruption during concurrent native Run calls,
worker retirement, recovery, and final temporary-file cleanup. Two earlier
workspace-filesystem runs failed the final cleanup assertion with stale files;
the unchanged JVM passed on a separate tmpfs filesystem. A deleted legacy
policy file also reappeared in one failed directory. Isolated baseline and
pure Python/Java file-lifecycle controls passed. The underlying environmental
cause is not established, and no cleanup assertion was removed or relaxed.
The original passing JVM output and subsequent wrapper-verifier correction
are retained separately so the wrapper's initial rejection is not hidden.

The separate diagnostic companion has been built and structurally verified;
it has **not been installed or run on the phone**. `device-probe-build.json`
and `device-probe-sources.json` bind its APK and every compiled source. Its
separate application ID and development signer do not replace LightForge.
See `qa/inference-device-probe/README.md` for its 35-passage fixture, conditions
and limits. Automated artifact download was blocked by authentication, so a
normal authenticated download and installation are still required.

No new production release has been built. Physical-device output, sustained
admission, net qualification cost and noticeable end-to-end improvement remain
unproven. A successful companion run alone does not qualify the production
service, full-song pipeline, musicality or vehicle preview for release.

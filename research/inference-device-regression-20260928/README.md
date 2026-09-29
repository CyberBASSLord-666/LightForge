# Device regression correction — unreleased

The supplied 2.4.1 phone run did not reproduce the earlier host speedup. This
work does not establish sustained physical-device or whole-analysis improvement.
The production version and release artifacts remain unchanged. The existing
source-bound release prerequisite must continue to reject these changed sources
until new evidence supports the next release.

## September 29 follow-up

The [version 2 phone attempts](device-probe-v2-phone-20260929/README.md) have not
established acceleration. Run01 stopped at the severe-thermal guard before a
complete passage. Run02's terminal UI reported six completed passages and clean
native retirement; captured profiles show baseline execution after a
memory-pressure screening abort. Only 400 of its 1,115 exported lines were
retrieved before the phone connector failed, so its final cancellation reason
remains unknown. Both attempts ran the source snapshot at `6a91949a`.

The subsequent screening correction removes an unnecessary 79,933,440-byte
activation copy, reconstructing the original front output into the existing
buffer before each temporal trial. It also skips an ineligible larger screening
option without discarding a measured smaller option that passes a fresh memory
check. Runtime, budget, cancellation and retirement failures discard nominations.
Memory thresholds, original graphs, precision, context and complete-passage
qualification remain unchanged. This correction requires its own validation;
the installed version 2 companion does not contain it.

Fresh [original-model integration](nomination-integration-20260929/README.md)
passes seven complete, finite outputs identical to the original reference and
four observed native cancellation modes with recovery. The
[focused screening checks](nomination-memory-host-20260929/README.md) pass seven
real-JNI scenarios. Historical-source negative controls demonstrate an exact
79,933,440-byte reduction in screening's measured direct-buffer growth. Synthetic
headroom and disclosed timing delays test selection and abort behavior; they
provide no speedup evidence. The [focused regression receipt](nomination-focused-tests-20260929/receipt.json)
records 42 passing Python/JVM tests and seven passing bridge tests; four historical
frozen-build checks skip because their original build directories are unavailable.
The separate retained-APK verification tests pass. Production release remains held.

The [fresh four-worker host comparison](host-four-worker-9435489/README.md)
binds integrated source `9435489` after the scheduler nomination and source
classification corrections. Eight complete original-model outputs are finite
and byte-identical. Three alternating measured pairs reduce median passage
wall time from **91.648495195 to 51.682151079 seconds, 43.6083%**. Each pair
improves by 31.1723%, 40.3602%, and 45.1970%. The prior preliminary local
four-worker run was lost in a scratch reset; its full receipt and logs were not
retained and are not cited as evidence. This fresh result is fixed host geometry
only. It does not establish physical-phone memory eligibility or admission,
sustained scheduler policy, net qualification payback, or whole-analysis speed.

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
- The combined candidate also processes independent frequency frames in batches
  of 16, using the same worker count and buffers. All 1,301 frames remain,
  including the final five-frame batch; baseline B128 is unchanged. This gives
  1,727 actual calls versus the baseline's 335. The
  [frequency investigation](frequency-screen/README.md) retains exact-output
  graph experiments and an exploratory complete-passage check. Device and
  current complete-engine performance still require separate measurements.
- Model-file extraction and verification occur in common preflight before either
  arm's timer. This cost remains in whole-passage/job time and is not attributed
  only to the first baseline. Fresh sessions do not imply cold filesystem caches.
- Three alternating complete-passage comparisons use consecutive useful passage
  ordinals 0, 1 and 2. Both arms use fresh original sessions, identical observer
  settings, Float32 outputs and full 27-graph geometry. Baseline output remains
  the useful output of a paired passage. Complete finite outputs must hash
  identically; every pair must improve by at least 5%, and the median by 15%.
- Extra work, including screening, comparison and interrupted probes, consumes
  a 360-second budget. Checks occur at existing safe native boundaries, so an
  in-flight native call can overrun a time checkpoint. A conservative payback
  projection includes future checks and a 10% margin. It is labeled projected,
  not measured whole-job savings.
- A qualified schedule earns an eight-passage lease, then may earn twelve-passage
  leases after a useful baseline control, without replaying a candidate. This
  unmatched-input timing guard is not another same-input comparison. Sustained
  slowdown triggers an earlier control. A timing-accepted control can still fail
  the updated payback check; the controller state determines admission.
  Failed, unaffordable, mismatched or memory-constrained execution latches the
  original baseline for the job. Cached evidence requires a fresh full pair;
  cache schema 2 rejects historical 0/4/8 qualification records.
- The JS separator supplies a bounded count of checked, uncached, non-silent
  useful passages. Unknown and short jobs cannot finance qualification.
- Durable diagnostics retain raw qualification/fresh-check pairs, the latest
  distinct unmatched-input control, explicit extra cost, decision reasons and
  actual temporal and frequency session configuration counts.
  Probe observations remain separate from production graph totals.
- Cancellation preserves native retirement: every worker and session stops
  before its run options, crash lease and process gate are released. Only a
  specifically identified optional Run rejection can use the fallback path;
  construction, retirement and other failures keep their normal error path.

No graph, trained weight, precision, attention context, band/frame coverage,
sample clock or output length is reduced. Historical 2.4.1 proof files remain
historical and are not rewritten as evidence for this correction.

## Prior validation at `6a91949a`, before the screening correction

That owner-interrupt snapshot passes both Android-first and
host-JSON-first Java compilation: 61 classes from the same eleven source files,
with no compiler diagnostics. The [compile receipt](native-profile-json-portability.owner-interrupt.json)
binds that snapshot. Its [portable suite](portable-python-owner-interrupt-tests.json)
passes **642 tests**: 571 current Python/JVM tests plus 71 explicit quality-tool
tests, with all 894 source hashes unchanged before and after execution. Exact
logs are retained in `portable-python-owner-interrupt-logs/`. The existing
exclusions for immutable 2.2.2/2.2.3 historical receipts remain unchanged.

The [original-model integration attempt 02](../frequency-integration-attempt-02-passed/README.md)
passed both JNI processes and all seven complete-output checks. Four- and
eight-worker candidates execute all 27 graphs with 1,727 calls; baseline paths
retain 335. Every finite output is byte-identical to the original demo
reference. The suite observes an actual first automatic pair without admitting
an unqualified cache, unknown/short-work baseline behavior, temporal caller
cancellation, owner interruption with its flag preserved, frequency caller
cancellation, and synchronous baseline cancellation followed by exact recovery.
Native retirement, gate ownership/release and temporary-output cleanup pass.
The preceding failed attempt is retained separately; its owner-interrupt
failure is not rewritten as a success.

The [independent Falcon and Stella fixture checks](../inference-frequency-fixtures-20260928/README.md)
also pass on that snapshot's four- and eight-worker candidates. All four complete
outputs match their committed original hashes, with full B16/tail coverage.
The archive retains exact receipts, profiles, logs and source snapshots, plus
archive-time source/class/input/output hash checks. These and integration02
are host correctness and cancellation evidence; they do not establish a phone
or sustained whole-job speedup.

Earlier snapshots remain explicitly historical: 702 JavaScript tests,
599 Python/quality-tool tests, the later 637-test snapshot, and their associated
compile receipts are preserved. Each result binds its own source snapshot.

That combined temporal B1 / frequency B16 snapshot passed the
[controlled host qualification](frequency-complete-host-qualification.json).
All eight complete original-model outputs were finite and byte-identical.
Three measured AB/BA/AB pairs reduced median passage wall time from
**47.838871175 to 22.687393368 seconds, 52.575400%**. Each measured pair improved
by 57.394480%, 51.380026%, and 51.638839%, respectively. Independent archive-time
recomputation matched every timing and resource result. Equal seven-CPU child
affinity reserved one CPU of host quota; observed throttle, OOM, memory-limit
and direct-reclaim counter increases were zero. Median process CPU fell from
144.70 to 123.47 seconds. Median whole-process peak RSS increased from
854,720,512 to 1,079,443,456 bytes; existing memory guards remain unchanged.
The original 15% median / 5% each-pair / 5% throttle admission criteria passed.
[Exact profiles, logs, frozen sources and independent checks](frequency-complete-host-evidence/README.md)
are retained. This is fixed-configuration host evidence: physical-phone
admission, sustained adaptive policy, net benefit after qualification cost and
whole-analysis improvement are still unproven. The source-bound production gate
still reports `Release held: measured inference source changed` for NativeDeux;
version 2.4.1 / 20401 is unchanged and no production release has been built.

`host-parallel-qualification.json` binds the historical `091fda7` source revision to
eight complete original-model executions. All outputs are byte-identical and
finite. The three measured baseline/candidate pairs reduced median passage
time from 52.734780 to 35.551003 seconds, **32.585282%**. This is a controlled
host result for the execution geometry, not an Android, sustained-policy or
whole-analysis speedup claim. Current production sources have since changed;
this historical result does not validate those changes.

The historical original-model integration JVM passed all six complete-output checks,
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

The separate diagnostic companion was installed and run on the phone. The
[first run's finding note](device-probe-4a25e06032a3-run01.md) links its exact raw
receipt and historical-binding analysis. Four of 35 passages completed before
operator cancellation during passage five. One baseline-first full-passage
pair measured 64.104899455 s baseline and 48.358257794 s candidate, a **24.56%**
wall-time reduction with finite, identical full-output hashes. That difference is
cache-confounded: baseline graph records include 6,807 ms preparing model files
that the subsequent candidate could reuse. It is not an isolated scheduling gain.
The frozen policy
immediately latched baseline with `payback-unavailable`; ordinary acceleration,
repeat-start consistency and sustained qualification were not established.

The cancelled run conservatively reported native cleanup unconfirmed and retained
its temporary cache despite the inference coordinator and engine close returning.
The note records these flags and their limits without rewriting the observation
after subsequent source fixes. `device-probe-build.json` and
`device-probe-sources.json` still bind the historical companion, whose separate
application ID and development signer do not replace LightForge. Frozen artifact
verification passes; current-source binding fails for the changed implementation.
See `qa/inference-device-probe/README.md` for the fixture and protocol limits.

No new production release has been built. Sustained physical-device admission,
net benefit after qualification cost and noticeable end-to-end improvement remain
unproven. The phone run's four completed fixture outputs and single matching pair do not
qualify the production service, full-song pipeline, musicality or vehicle preview
for release.

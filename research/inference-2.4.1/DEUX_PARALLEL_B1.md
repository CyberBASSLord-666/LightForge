# Independent one-band parallel execution: host prototype

Eight independent temporal bands run concurrently through one original shared
session, with one intra-op thread per run. Every band retains all 1,301 context
frames. Frequency graphs, both output heads, model bytes, weights and Float32
precision are unchanged. All 60 bands run in each of the 12 temporal graphs.
Consequently the full passage has 875 calls instead of 335; this is the same
model work in smaller independent batches.

The formal host experiment used a warmup pair and three alternating measured
pairs. Every process executed a complete 13-second, two-stem passage through all
27 graphs. All eight outputs were finite and byte-identical over 1,146,600
Float32 values. Warmup is excluded below.

| Pair | Original | Eight one-band workers | Wall reduction |
| --- | ---: | ---: | ---: |
| 1 | 43.21 s | 37.60 s | 13.0% |
| 2 (reverse order) | 49.32 s | 40.44 s | 18.0% |
| 3 | 63.90 s | 38.06 s | 40.4% |

The ratio of median latencies is **22.8% lower** (49.32 to 38.06 seconds).
The median paired reduction is 18.0%; the baseline variability is material and
its remaining cause is unknown. Median process CPU increased 16.7%, from 134.73
to 157.25 seconds. Median peak RSS increased 19.7%, from 831.3 to 994.9 MiB.
There were no new memory-limit, OOM or direct-reclaim events. Measured candidate
CPU-quota throttling was 0.071–0.115 seconds per run, below 0.3% of passage wall
time. These observations do not establish battery, physical-phone, or complete
analysis speed improvements.

The criteria require at least 15% lower median full-passage latency and 5% lower
latency in every measured pair. They were agreed while the experiment was in
progress; by persistence, the first measured pair was complete. The timestamped
criteria receipt discloses that progress and metrics. This is not claimed as a
preregistration before all measured work.

The earlier two-pair screen had 26.0% lower median wall time and 18.6% higher
peak RSS. A separate eight-worker four-band screen had a larger apparent gain
but 56.8% more peak RSS. The one-band geometry was selected for its lower memory
cost. Neither screening result substitutes for production-source qualification.

Evidence:

- `deux-parallel-b1-eight-paired-screen.json`: immutable exploratory receipt.
- `deux-parallel-b1-eight-paired-qualification.json`: immutable formal prototype receipt.
- `deux-parallel-b1-eight-admission-criteria.json`: declaration timing and thresholds.
- `deux-parallel-b1-eight-provenance.json`: original receipt hashes and frozen source snapshots.
- `separator-scheduler-paired.json`: bound original baseline/common Java snapshots.

The host-only prototype passes these performance criteria. A release still
requires the actual production runner to reproduce the gain, broader-input
parity, safe cancellation/native retirement, bounded device memory admission,
and the existing production/Android gates. No APK was built for this experiment.

## First production attempt: not admitted

The unchanged production runner subsequently produced byte-identical finite
outputs in all eight runs. Measured reductions were 25.8%, **1.17%**, and 27.5%,
with a 23.3% reduction in median passage latency. The middle pair failed the
predeclared 5% minimum. The performance gate correctly retained a failing result
and did not create a canonical passing receipt.

The slow candidate's temporal stage took 21.584 seconds, versus 16.421 and
15.996 seconds in the other measured candidate runs. Summed worker run durations
divided by eight give optimistic lower bounds of 14.151, 12.950 and 12.751
seconds, respectively. This exposes lower effective worker utilization in the
slow run and motivates testing continuous reassignment of completed workers.
It does not prove that every second of the gap is recoverable or establish the
cause of the remaining host variability. No memory-limit, OOM or direct-reclaim
events occurred.

`production-parallel-wave-attempt.json` preserves the entire failing experiment.
`production-parallel-wave-attempt-provenance.json` preserves the exact production
source snapshots, original profiles and derived stage diagnostics. A rerun
without a concrete change cannot erase that failed repeatability observation.

## Continuous reassignment and CPU-budget control screens

All ten subsequent exploratory observations are preserved in
`temporal-refill-screen.json`, together with exact source snapshots, profiles,
logs and raw counters. Every complete output matched the original reference
bytes. These screens do not qualify production performance.

The first five runs inherited nine allowed CPUs under an eight-CPU quota. They
were, in execution order: refill 44.97 s, original serial 52.54 s, wave 39.04 s,
wave 40.54 s, refill 37.82 s. The first refill run's cgroup throttled-counter
delta divided by passage wall time was 5.44%, exceeding the resource guard.
That ratio is not a measurement of the exact wall time lost to throttling.

The follow-up restricted every Java child to the same eight CPUs within that
quota, observing eight available processors in each child. The parent process,
other processes, cgroup quota and Android implementation were unchanged.

| Controlled pair | Wave passage | Refill passage | Wave temporal interval | Refill temporal interval |
| --- | ---: | ---: | ---: | ---: |
| 1 | 37.23 s | 34.26 s | 15.627 s | 12.760 s |
| 2 (reverse order) | 36.96 s | 40.62 s | 15.099 s | 14.685 s |

Refill improved temporal utilization in both controlled pairs, but whole-passage
results were mixed: approximately 8.0% faster and 9.9% slower than waves. The
second refill's unchanged frequency graphs took 17.83 seconds versus 13.00
seconds for the adjacent wave run. The cause of that variation is not established.
A final controlled original-serial screen took 54.40 seconds; it is not a full
paired release comparison.

The refill temporal interval includes coordinator dispatch, packing and scatter
while workers remain active. The wave interval excludes packing and scatter.
Those intervals and overlapping worker durations must not be added together or
treated as identical scopes. Affinity groups must not be pooled into one timing
qualification. No overall refill-over-wave speedup is claimed from these screens.

The subsequent formal comparison used the final production implementation,
the same observed eight-CPU control for every child, an excluded warmup pair,
and three alternating pairs. Its failed result is retained below.

## First production refill qualification: resource guard failed

The complete eight-run production comparison on 2026-09-28 retained the same
original graphs, full context and output geometry. All eight complete outputs
were finite and byte-identical. All Java children observed CPUs 0–7 and eight
processors under the unchanged eight-CPU cgroup quota.

| Measured pair | Original | Production refill | Wall reduction | Candidate throttle-counter/wall ratio |
| --- | ---: | ---: | ---: | ---: |
| 1 | 55.883 s | 50.151 s | 10.26% | 5.3614% |
| 2 (reverse order) | 53.186 s | 36.902 s | 30.62% | 1.3661% |
| 3 | 54.233 s | 35.590 s | 34.38% | 1.3831% |

The ratio of median wall times improved by 31.96%, and each pair exceeded the
5% wall-reduction floor. Nevertheless, the predeclared maximum 5% resource
counter ratio failed. No passing release qualification was emitted. Every
baseline throttle-counter delta was zero; the candidate warmup ratio was
3.9881%. There were no added OOM, memory-limit or direct-reclaim events. Median
peak RSS rose from 815.0 to 1039.4 MiB and median process CPU from 147.69 to
158.31 seconds. This is host evidence, not a measured phone or whole-song gain.

The slower first measured candidate had both a longer temporal pipeline
(16.978 seconds versus 13.514/13.422 in later candidates) and longer unchanged
frequency inference (24.061 seconds versus 15.106/12.543). Its process CPU was
202.55 seconds, versus 158.31/150.17. These observations do not establish the
cause of the variation. The cgroup throttle ratio is not the fraction of wall
time lost to throttling. The complete failed receipt and all source/profile
snapshots are retained in `production-parallel-refill-attempt.json` and
`production-parallel-refill-attempt-provenance.json`.

## Declared host control for the next qualification

Before any further timed runs, protocol v3 reserves at least one CPU of the
unchanged cgroup quota for platform processes. Every baseline and candidate
Java child receives the same first seven allowed CPUs and must honestly report
seven available processors. The eight-worker candidate is an explicit host
fixture using the unchanged production runner; processor counts are never
spoofed. Android admission is tested separately and still requires eight
reported cores to select eight workers. Production source remains unchanged.

This is a concrete correction to shared quota headroom, not a retry of the
same control or a relaxation of the failed resource criterion. The next
comparison retains the excluded warmup, three alternating measured pairs,
15% median wall reduction, 5% minimum reduction for every pair, maximum 5%
throttle-counter/wall ratio, and exact full-output/source/coverage checks.
It must be considered separately from all previous affinity groups.

## Final source-bound host qualification passed

The v3 comparison on 2026-09-28 passed with the unchanged production refill
runner and all predeclared criteria. The same seven-CPU child control applied
to all eight fresh JVMs. The excluded warmup was 54.792 seconds for the original
path and 44.979 seconds for the forced eight-worker candidate.

| Measured pair | Original | Production refill | Wall reduction | Candidate throttle-counter/wall ratio |
| --- | ---: | ---: | ---: | ---: |
| 1 | 61.188 s | 44.010 s | 28.07% | 0% |
| 2 (reverse order) | 65.277 s | 46.472 s | 28.81% | 0.0868% |
| 3 | 67.129 s | 42.853 s | 36.16% | 0% |

The ratio of variant medians improved by **32.58%**, from 65.277 to 44.010
seconds. The median paired reduction was 28.81%. Every measured pair passed
the 5% floor; the ratio of medians passed the 15% criterion. The maximum
throttle-counter/wall ratio was 0.0868%, with zero added counter time in all
other runs, and no added OOM, memory-limit or direct-reclaim events.

The median peak RSS increased from 817.35 to 1032.00 MiB (+26.26%), and median
process CPU from 171.39 to 181.14 seconds (+5.69%). Parallelism reduces elapsed
time while using more memory and somewhat more total CPU; it does not reduce
the model's work or change its quality. All eight full outputs were finite and
byte-identical over 1,146,600 floats. All 27 original graphs, 60 bands, 1301
frames and two complete output stems were retained, with 335 original calls
versus 875 one-band calls. The pinned runtime was ONNX Runtime 1.25.1.

`production-parallel-qualification.json` records all raw observations, exact
source/class/model/runtime/input/output hashes, observed CPU controls and
resource deltas. `production-parallel-qualification-provenance.json` preserves
the eight source snapshots and eight full profiles. The independent release
gate recomputed and accepted the result from the receipt. Prior failed and
mixed experiments remain retained separately and were not pooled or discarded.

This establishes a repeatable improvement for the tested host passage and
forced production configuration. It does not establish a physical Android
speedup, complete-song analysis speedup, or the aspirational 75% goal. Actual
Android worker admission, memory headroom, correctness and cancellation are
separately tested; the host fixture's seven reported CPUs do not bypass the
production requirement for eight reported cores before selecting eight workers.

The same qualified class files also passed four independent full-output checks:
both Falcon and Stella, each with forced four- and eight-worker production
paths, were byte-identical to their source-bound original canonical outputs.
Each retained all 875 calls and 1,146,600 finite output floats. The receipt
`production-parallel-independent-inputs.json` binds the original references,
inputs, runtime, models, classes, source and complete output hashes; its
provenance companion preserves the quality helper and four complete profiles.
These are numerical quality checks, and their times are not performance claims.

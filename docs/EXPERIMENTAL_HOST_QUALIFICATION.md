# Experimental portable host qualification

## Scope and admission

`portable-four-worker-three-cpu-v1` compares the unchanged production four-worker
runner, explicitly forced by the benchmark, against the unchanged production
baseline with three intra-op threads. Both children use exactly the same three
actual CPUs, with at least one additional effective CPU of observed capacity
reserved. This is **not ordinary production scheduler admission**: that policy
would reject four workers at three available processors. No processor count is
spoofed, and production scheduling is not modified.

This experiment establishes no eight-worker, device-admission, Android,
full-song, or release claim. Its receipts use
`lightforge.experimental-portable-parallel-qualification.v1` and explicitly set
`releaseAdmissible: false`. The default production verifier rejects experimental
receipts; a passing experimental replay cannot satisfy the production release
gate or waive another requirement.

## Read-only eligibility diagnostic

From the repository root:

```sh
python3 tools/portable_inference_host.py
```

The command emits bounded JSON (at most one MiB) using
`lightforge.experimental-portable-runner-diagnostic.v1`, exiting **0** for
eligible and **2** for ineligible. It runs no inference and writes no host
settings: no affinity, cgroup, namespace, mount, or quota changes. Eligibility
never proves performance or release qualification; this projected diagnostic
is not replayable benchmark evidence.

Eligibility requires Linux x86_64, the initial/global cgroup namespace, a
complete visible cgroup-v2 hierarchy, and a non-root measured process. Every
ancestor's applicable limits, identities, and counters must be observable and
consistent. Effective capacity must be at least four CPUs after affinity and
all finite ancestor quotas are considered. An observed `cpu.max` value of
`max` means unlimited quota, not missing evidence. Structurally inapplicable
global-root limits/counters are explicitly marked not applicable, never
invented as zero. Missing, hidden, ambiguous, or changing evidence blocks the
lane; do not alter host controls to conceal that failure.

The available executor's diagnostic on 2026-10-23 exited 2 because its cgroup
namespace hides ancestry. GitHub-hosted eligibility remains unestablished until
the diagnostic actually runs there; a runner label or advertised CPU count is
not proof.

## Prospective measurement and replay

Select the lane explicitly before observing benchmark results:

```sh
python3 tools/benchmark_deux_parallel.py --protocol portable-four-worker-three-cpu-v1 --output /path/to/fresh-attempt
python3 tools/verify_inference_improvement.py --experimental-portable-receipt /path/to/fresh-attempt/receipt.json
```

The output directory must not already exist. The benchmark writes `protocol.json`
before inference, binding the declared lane, thresholds, host controls, sources,
and compiled classes. Do not retrospectively relabel legacy observations or use
`--receipt` to publish portable evidence into the production prerequisite.

Both variants retain the same complete original Float32 model and context:
27 graphs, 15 stages, 60 bands, 1,301 frames, and 573,300 samples per stem,
using the same audio passage and pinned ONNX Runtime 1.25.1. One warmup pair
precedes three measured pairs in baseline/candidate, candidate/baseline,
baseline/candidate order, each execution in a fresh JVM. Acceptance requires
at least 15% lower median wall time and at least 5% improvement in every
measured pair, plus byte-identical complete finite outputs across all eight runs.

Replay also requires unchanged source/class/model/runtime bindings, full work
profiles, actual child affinity and processor-count observations, matching child
resource identities, and before/after full-ancestry resource proof. No OOM,
memory-limit/high events, direct reclaim, or memory-pressure increases are
allowed. CPU pressure is observed; throttling must stay within 5% of wall time
both per ancestor and cumulatively.

Preserve every failed attempt, raw log, process record, counter snapshot, output,
profile, declaration, source snapshot, and compiled artifact. Keep retries in
fresh directories; never overwrite failures or select only passing pairs or
attempts to manufacture a qualifying result.

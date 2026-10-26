# Host qualification: experimental evidence and bounded campaign

## Distinct protocols, no relabeling

The existing `production-v3` protocol remains distinct, with its eight-worker
candidate, seven observed child CPUs and finite quota of at least eight CPUs.
Its CLI and resource requirements are unchanged. It is not a fallback when the
bounded campaign is missing or fails.

The old `portable-four-worker-three-cpu-v1` protocol and
`lightforge.experimental-portable-parallel-qualification.v1` receipts remain
experimental, explicitly `releaseAdmissible: false`. They cannot be relabeled,
registered retroactively or consumed as bounded production host admission.

The new prospective `bounded-four-worker-three-cpu-v1` protocol writes
`lightforge.bounded-host-parallel-qualification.v1` receipts. It compares the
unchanged production four-worker runner, explicitly forced by the benchmark,
against the unchanged production reference using three intra-op threads. Both
children use exactly the same three actual CPUs, with at least one additional
effective CPU of observed capacity reserved. No processor count is spoofed and
production scheduling is not changed. Normal production scheduler admission
would reject four workers with only three available processors.

A passing bounded receipt alone is not release authority. Only the exact
policy-owned, prospectively registered, terminal producer proof can be replayed
into a fresh candidate-specific admission. This establishes no eight-worker,
device-admission, Android or full-song speed claim and waives no other gate.

## Read-only resource eligibility

Select the bounded resource lane explicitly:

```sh
python3 tools/inference_qualification_preflight.py \
  --protocol bounded-four-worker-three-cpu-v1
```

The legacy preflight still defaults to `production-v3`; a failed legacy check
never silently chooses the bounded lane. `python3 tools/portable_inference_host.py`
remains a standalone read-only diagnostic, not a qualifying receipt.

Eligibility requires Linux x86_64, the initial/global cgroup namespace, a
complete visible cgroup-v2 hierarchy and a non-root measured process cgroup.
Every ancestor's applicable limits, identities and counters must be observable
and consistent. Effective capacity must be at least four CPUs after affinity
and all finite ancestor quotas are considered. An observed `cpu.max` value of
`max` means unlimited quota, not missing evidence. Structurally inapplicable
global-root limits/counters are explicitly marked not applicable, never
invented as zero. Missing, hidden, ambiguous or changing evidence blocks the
lane. Do not alter host controls to conceal a failure.

The diagnostic runs no inference and changes no affinity, cgroup, namespace,
mount, quota or host setting. It is not campaign authorization. Only subsequent
benchmark children are pinned to the prospectively declared CPUs; the parent
and production Android implementation are not repinned. Ordinary build replay
does not require the consumer to qualify as a new timing host.

The available executor's diagnostic on 2026-10-23 exited 2 because its cgroup
namespace hides ancestry. The bounded producer's prospectively selected pool
is fixed to `ubuntu-latest`; repository variables and dispatch inputs cannot
select another producer pool. Every actual allocated machine must pass the
full strict preflight. Any prior diagnostic proves only the sampled machine's
observations, not blanket eligibility for the pool. A runner label or advertised
CPU count is not evidence, and no bounded campaign timing or performance pass
is asserted. Ordinary consumer and production-v3 routing remain unchanged.

## Prospective declaration, registration and single execution

The initial policy owns one campaign,
`lightforge-2.4.2-neural-four-worker-host-001`. Source publication of
`tools/host-inference-campaigns/<campaignId>.request.json` requests its single
producer in `.github/workflows/verify-v2.yml`. The request contains only schema
`lightforge.host-inference-request.v1`, the campaign ID and the current policy
SHA-256. Its first and only protected-main creation commit allocates the run;
no request means no producer. The request and registration are control-plane
files outside measured source identity, with their immutable history checked
directly against protected main. Registration and later source/cosmetic pushes
cannot allocate another attempt. A lightweight read-only routing job chooses
the producer, original-terminal replay on a rerun, or ordinary proof consumer.
Manual dispatch is only a diagnostic consumer and cannot allocate a duplicate.
The implementation does not create or publish a request itself.

Request-creation precondition: ensure no older main verification run is ahead
of the request. Wait until the designated `host-campaign` job is running before
publishing registration or unrelated pushes. `cancel-in-progress: false`
preserves an already-running producer, not a queued request run. GitHub's
default single pending slot can replace a queued run when another main push
arrives. A replaced/missing designated run holds; no replacement timing attempt
is allocated and no queue setting is changed.

1. In the allocated main-push attempt, reviewed fixed bootstrap/model paths prepare the original dependencies and
   model. Declaration-only preparation compiles and fingerprints all measured
   inputs and the execution closure before any warmup or timing:

   ```sh
   python3 tools/benchmark_deux_parallel.py \
     --protocol bounded-four-worker-three-cpu-v1 --phase prepare \
     --output /path/to/fresh-attempt
   ```

   The new directory contains `declaration.json`, the unmeasured initial receipt,
   frozen source snapshots and compiled classes. It cannot overwrite a previous
   directory. The declaration alone is uploaded with an immutable artifact ID
   and server digest. No timing may precede that upload.

2. The exact declaration is reviewed and registered through normal authorized
   source publication at `tools/host-inference-campaigns/<campaignId>.json` on
   protected main. Registration must identify the designated run ID and
   attempt, actual input commit/tree, declaration artifact ID/server digest and
   reviewed execution closure. A mutable branch or PR ref is not an identity.
   This initial implementation accepts only the designated protected-main
   request-creation push producer; PR/main verification consumers may replay its
   exact-identity proof.

3. The same still-running designated producer polls registration read-only for
   a bounded interval. Only an exact admitted registration allows execution:

   ```sh
   python3 tools/benchmark_deux_parallel.py \
     --protocol bounded-four-worker-three-cpu-v1 --phase execute \
     --output /path/to/the-same-attempt
   ```

   The execution path rechecks live registration and frozen identities before
   the first warmup. It cannot start with a replacement declaration, work
   directory, run or attempt. Campaign concurrency preserves this already-running
   producer when its registration is published, subject to the request-creation
   precondition above. No new persistent credential, service,
   repository setting or approval infrastructure is introduced.

4. The original terminal proof retains raw observations, outputs, profiles,
   process records, counters, declaration, source snapshots and compiled
   artifacts. Success and failure are not overwritten. A producer rerun must
   replay the original terminal result, never prepare or measure again.

There are no automatic timing retries, selected passing subsets or replacement
attempts. Missing, deleted, cancelled, unknown or incomplete attempts hold.
Registration absence can be awaited only by the designated initial preparation
attempt; timeout holds rather than beginning measurement. A failed terminal
result stays failed. Artifact expiry also holds and must not cause remeasurement.
Any new attempt or changed measured identity needs an explicit reviewed policy
change, not an inferred exception.

These commands document the implementation, not permission to run them now.
Independent review, integrated 2.4.2 source, a source freeze and authorized source
publication must all precede actual warmups or timing.

## Unchanged full-work and resource acceptance

Both variants retain the complete original Float32 model and context: 27 graphs,
15 stages, 60 bands, 1,301 frames and 573,300 samples per stem, using the same
original audio passage and pinned ONNX Runtime 1.25.1. One warmup pair precedes
three measured pairs in baseline/candidate, candidate/baseline,
baseline/candidate order, each execution in a fresh JVM. Acceptance requires
at least 15% lower median wall time and at least 5% improvement in every
measured pair, plus byte-identical complete finite outputs across all eight runs.

Replay also requires unchanged source/class/policy/model/runtime/audio bindings,
full work profiles, actual child affinity and processor-count observations,
matching child resource identities and before/after full-ancestry resource
proof. No OOM, memory-limit/high events, direct reclaim or memory-pressure
increases are allowed. CPU pressure is observed; throttling must stay within
5% of wall time both per ancestor and cumulatively. Fresh compilation validates
the current class identity without executing inference.

## Fresh per-build admission, not fresh timing

### 2.4.3 metadata migration

The current `tools/replay_inference_proof.py` consumer preserves the original
2.4.2 campaign and verifies its original source view with the unchanged
authority and numerical verifiers. Its reviewed policy permits only
`version.json` and the pinned current verification workflow to differ from
the original 27-file closure. The remaining 25 files, original model/runtime
identities and complete freshly compiled Java class inventory must still
match exactly. The original QA 2.4.2 verifier remains unchanged; fresh app
receipts come from the current QA 2.4.3 protocol and current asset inventory.

The new prerequisite records both the original measurement identity and the
current source projection, explicitly stating that no new measurement ran.
The canonical admission retains the original producer and artifact identities
while binding the new candidate commit/tree and session. Publication
independently retrieves and replays the original proof again. Missing or
expired proof, changed numerical inputs/classes, an unreviewed workflow,
wrong metadata, or stale candidate/session binding still holds the release.
No numerical performance threshold, signing requirement or current automated
Android/app gate is removed by this migration.

Normal verification clears any checked-in/current prerequisite and first
establishes the exact registered terminal proof before expensive preparation.
After preparing the current inputs, it independently replays the full immutable
bundle and issues a fresh admission bound to the current candidate commit/tree
and evidence session. All measured identities must still match exactly. A
copied admission from another build or a stale receipt is not accepted.

This deliberately replaces the former per-build remeasurement requirement with
immutable exact-identity replay. The original timing remains the original timing;
only the candidate-specific admission is new. No performance claim is made for
changed inputs, another host configuration, a device or a whole song. The proof
is retained as an immutable artifact with finite retention; expiry, digest
mismatch, removal or unavailable provenance causes a release hold.

The normal current-release regression, source-clock, browser, actual-model,
native, Android and signing suites remain unchanged and produce their existing
same-session evidence. The campaign producer never packages a candidate or
becomes publication authority. Release publication still requires successful protected-
main verification, exact candidate/source/evidence bindings and the original
signing identity.

### Frozen consumer checkout-layout compatibility

The registered consumer workflow invokes replay with `--root .`. Its immutable
bounded verifier retains that relative root, so its `ROOT.parent / 'toolchain'`
lookup selects `checkout/toolchain`, whereas the immutable bootstrap installs
into the sibling `checkout-parent/toolchain`. This is a consumer lookup defect,
not a failed timing experiment or an unavailable pinned JDK.

`npm test` explicitly runs `tools/prepare_consumer_toolchain_layout.py` before
`tools/verify_v2.py`. Outside GitHub Actions the preparation is a no-op, preserving
local test setups and custom toolchain locations. In GitHub Actions it checks the
canonical `GITHUB_WORKSPACE` and Git root, rejects tracked-path collisions and
project toolchain overrides, and exclusively creates the relative symlink
`checkout/toolchain -> ../toolchain`. Existing entries are accepted only when they
are this exact alias. It never replaces directories/files/other links, installs
dependencies, clears environment variables, or changes command resolution.
Descriptor-relative creation prevents writes through a replaced checkout parent.

This step reports **layout-ready**, always with `runtimeValidated: false`.
Bootstrap runs later, so the target may legitimately be absent at preparation.
An existing target is not evidence of valid installation. Generic hosted-runner
`JAVA_HOME`/Android SDK discovery settings are not redirected or cleared: the
frozen bounded lookup uses explicit paths, and its runtime environment guard
remains authoritative.

The later unchanged admission still replays every retained observation, validates
the complete JDK/internal-link and dependency inventories, recompiles the current
measured sources, and requires exact class hashes. Candidate commit/tree/session
bindings and dirty-source rejection are unchanged. The preparation helper,
package command, tests, and this document are covered by the existing regression
source-hash inventory. No registered execution-closure file, runtime bytes, or
original proof is changed or relabeled. This is compatibility for the current
frozen consumer workflow, not a general fix for arbitrary relative CLI roots.

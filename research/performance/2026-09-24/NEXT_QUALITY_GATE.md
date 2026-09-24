# Next GAME CUDA quality gate

Passing all twelve exact observer/source/runtime/placement checks validates the
diagnostic. CPU/CUDA tensor or unrounded-note differences still produce
`NUMERICAL_EQUIVALENCE_UNPROVEN`. They are neither proof of musical degradation
nor quality approval. No GAME CUDA tensor tolerance is approved by this note.
The existing [acceleration plan](../../../docs/75_PERCENT_ACCELERATION_PLAN.md)
requires comparison rules to be fixed before qualification evidence is collected.

## Executable next steps

From the repository root, independently verify preserved complete captures with
the existing comparator. Use a new output path; exit 2 means a numerical or shape
difference, not permission to apply a new tolerance:

```sh
python3 tools/game_benchmark/compare.py \
  "$EVIDENCE/cpu_all_captured/output" \
  "$EVIDENCE/cuda_basic_captured/output" \
  --output "$NEW_COMPARISON_JSON"
```

The accelerator harness already performs that comparison. Repeating it verifies
the retained evidence; it does not create musical-quality qualification.

The next strict qualification prerequisite is a real approved corpus/policy
bundle. Once available through its authorized store, validate it before new
collection; these commands validate supplied evidence and do not change policy:

```sh
python3 tools/locked_benchmark_runner.py validate-manifest \
  --manifest "$QUALITY_DIR/locked-corpus-manifest.json"
python3 tools/release_policy_setup.py validate \
  --policy "$QUALITY_DIR/performance-gate-policy.json" \
  --manifest "$QUALITY_DIR/locked-corpus-manifest.json" \
  --attestation "$QUALITY_DIR/release-policy-attestation.json"
```

Collect complete source-bound baseline/candidate diagnostics under the existing
paired protocol, then use `tools/locked_benchmark_runner.py validate-reports`
and `aggregate`, followed by `tools/performance_quality_gate.py`. Exact arguments,
controlled runtime/cache conditions, review inputs and protected execution are in
[the runner contract](../../../docs/LOCKED_BENCHMARK_RUNNER.md) and
[the gate contract](../../../docs/PERFORMANCE_QUALITY_GATE.md). Existing requirements
include at least five pairs per track, 99% confidence, and a 75% total-time
reduction lower bound for every required track, alongside all critical quality,
resource and review gates. A model-call or passage timing cannot replace this.

## Existing assets and missing prerequisites

The checkout contains only `qa/locked-corpus-manifest.template.json` and the
template-mode `qa/performance-gate-policy.json`, whose required track is
`__configure_locked_corpus__`. The manifest has synthetic identities/goldens and
is not release-ready. Validation without `--allow-template` returns exit 2:
`template manifest is not a locked release corpus`.

No real approved locked manifest, complete annotation bundle or current
ten-category golden bundle was found in the checkout. The authorized private
store was not inspected. Strict qualification needs at least sixteen distinct
licensed tracks with the fixed coverage requirements, genuine applicable
annotations, frozen goldens, the exact approved policy and detached
policy/corpus attestation. Baseline runs must reproduce those goldens; candidate
outputs must be deterministic across repeated runs. Authenticated blinded review
and complete measured diagnostics are additional requirements, not supplied by
the bundle alone. See [setup requirements](../../../docs/RELEASE_QUALITY_SETUP.md).

Recoverable public development inputs include the demo, original models and
toolchain pinned by `research/performance/2026-09-21/public-assets-recovery.json`;
six short licensed MUSDB excerpts described by
`qa/release-1.6.0/prepare-musdb-fixtures.py` and its retained provenance; and
synthetic beat, vocal and source-clock fixtures. These are not the locked corpus.
The short-excerpt records disclose possible training overlap and do not provide
human singing/word annotations. Historical small goldens are not the current
ten-category release goldens. A lost capture cannot be recovered from its digest;
rerunning produces new evidence.

## Two distinct differentials

`tools/differential_analysis.py` accepts strict baseline/candidate semantic-event,
choreography, collision and FSEQ-timing artifacts and produces a review report:

```sh
python3 tools/differential_analysis.py \
  --baseline "$BASELINE_DIFFERENTIAL_JSON" \
  --candidate "$CANDIDATE_DIFFERENTIAL_JSON" \
  --output "$NEW_DIFFERENTIAL_REPORT_JSON"
```

It does not decide quality equivalence or generate the gate's separate
`candidate_output_differential`. That canonical hash differential is required
only when candidate golden-artifact hashes change. It must list every changed
artifact, baseline/candidate hash and rationale hash, bound to candidate identity
and corpus. The gate rejects an unexpected differential when outputs are
unchanged. The mandatory external blinded-review signature covers the complete
benchmark evidence, including any required hash differential.

## What public-fixture sensitivity can decide

A predeclared source-bound experiment can show whether observed changes affect
the exercised notes, production stitching, vocal fusion or downstream events.
It can expose failures and justify further research. Matching rounded notes,
exact downstream outputs, or a sensitivity pass on these fixtures cannot approve
general musical quality, resolve the locked-corpus gate, admit benchmark ratios
or prove the 75% production target.

`tools/game_benchmark/benchmark_native_process.py` currently supports native CPU
versus WASM, not the CUDA candidate. `tools/game_benchmark/process_capture.cjs`
exports production replay helpers, but its existing CLI binds historical
CPU/WASM schemas. A GAME CUDA consumer experiment needs a reviewed source-bound
wrapper and complete original passage coverage; one captured first passage
cannot be relabeled as a complete-source result. For stage isolation, both arms
must consume the same exact vocal PCM. Existing Deux excerpt sensitivity rules
are not a GAME CUDA tensor tolerance or publication authority.

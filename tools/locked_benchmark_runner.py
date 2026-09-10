#!/usr/bin/env python3
"""Fail-closed locked-corpus benchmark report validator and aggregator.

This is intentionally a host-side tool: the production pipeline emits one
``analysis_benchmark_contract`` diagnostic per analysis attempt, and this tool
turns an explicitly locked, comparable set of those diagnostics into the raw
``runs`` document consumed by ``performance_quality_gate.py``.  It never
decodes audio, invokes a model, or changes a show output.

The aggregate is deterministic: input discovery, run ordering, summaries, and
JSON serialization are all stable.  It contains no source paths or audio data.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_TOOLS_DIRECTORY = Path(__file__).resolve().parent
if str(_TOOLS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIRECTORY))

import analysis_benchmark_contract as contract
import performance_quality_gate as quality_gate


_OPAQUE_ID = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


class LockedBenchmarkError(ValueError):
    """Raised when a diagnostic set cannot support a release comparison."""


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LockedBenchmarkError(f"cannot read {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise LockedBenchmarkError(f"{path.name} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise LockedBenchmarkError(f"{path.name} must contain a JSON object")
    return value


def _validate_runner_manifest(manifest: Mapping[str, Any], *, allow_template: bool) -> None:
    """Apply runner-only release safeguards after the shared schema validates."""
    contract.validate_corpus_manifest(manifest)
    template = manifest.get("template", False)
    release_ready = manifest.get("release_ready", False)
    if not isinstance(template, bool):
        raise LockedBenchmarkError("manifest.template must be a boolean when present")
    if not isinstance(release_ready, bool):
        raise LockedBenchmarkError("manifest.release_ready must be a boolean when present")
    if template and release_ready:
        raise LockedBenchmarkError("a template manifest cannot be marked release_ready")
    if template and not allow_template:
        raise LockedBenchmarkError("template manifest is not a locked release corpus")
    if not template and not release_ready:
        raise LockedBenchmarkError("locked corpus must explicitly set release_ready to true")

    # A locked corpus should not accidentally count the same audio twice under
    # different labels.  The shared contract deliberately permits this for
    # broader cache use cases, while this release runner does not.
    audio_ids: dict[str, str] = {}
    for track in manifest["tracks"]:
        audio_sha = track["audio"]["content_sha256"]
        previous = audio_ids.setdefault(audio_sha, track["track_id"])
        if previous != track["track_id"]:
            raise LockedBenchmarkError(
                "locked corpus has duplicate audio identities: "
                f"{previous!r} and {track['track_id']!r}"
            )


def load_manifest(path: Path | str, *, allow_template: bool = False) -> dict[str, Any]:
    """Load and validate a redacted locked-corpus manifest."""
    manifest = dict(_load_json(Path(path)))
    _validate_runner_manifest(manifest, allow_template=allow_template)
    return manifest


def discover_diagnostic_paths(inputs: Iterable[Path | str]) -> list[Path]:
    """Resolve JSON files deterministically without embedding paths in output."""
    discovered: set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() != ".json":
                raise LockedBenchmarkError(f"diagnostic input {path.name} is not a JSON file")
            discovered.add(path.resolve())
        elif path.is_dir():
            children = [child.resolve() for child in path.rglob("*.json") if child.is_file()]
            if not children:
                raise LockedBenchmarkError(f"diagnostic directory {path.name} contains no JSON reports")
            discovered.update(children)
        else:
            raise LockedBenchmarkError(f"diagnostic input {path.name} does not exist")
    if not discovered:
        raise LockedBenchmarkError("at least one diagnostic report is required")
    return sorted(discovered, key=lambda item: str(item))


def gate_environment(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Make a readable aggregate of the authoritative per-run provenance.

    The paired quality gate compares the per-run provenance directly.  This
    projection is retained for human diagnostics and provides deterministic
    model/configuration digests without duplicating those full objects.
    """
    provenance = diagnostic["provenance"]
    environment = provenance["environment"]
    implementation = provenance["implementation"]
    workload = provenance["workload"]
    return {
        "hardware": {"fingerprint": environment["hardware_fingerprint"]},
        "runtime": {
            "backend": environment["runtime_backend"],
            "version": environment["runtime_version"],
            "accelerator": environment["accelerator"],
        },
        "pipeline": {
            # Source version is intentionally *not* named by the default gate
            # policy, because baseline and candidate normally differ there.
            "source_version": implementation["pipeline_version"],
            "preprocessing_version": implementation["preprocessing_version"],
            "model_manifest": "sha256:" + contract.digest_json(implementation["model_versions"]),
            "configuration_hash": "sha256:" + contract.digest_json(workload["analysis_configuration"]),
        },
        "benchmark": {
            "random_seed": environment["random_seed"],
            "thermal_profile": environment["thermal_profile"],
        },
    }


def _opaque_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise LockedBenchmarkError(f"{field} must be a stable opaque identifier")
    return value


def _opaque_reference(value: Any, field: str) -> str:
    """Accept contract IDs such as UUIDs without allowing control characters."""
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise LockedBenchmarkError(f"{field} must be a non-empty opaque reference")
    return value


def load_gate_policy(path: Path | str) -> dict[str, Any]:
    """Load the committed gate policy and validate it with the real gate."""
    policy = dict(_load_json(Path(path)))
    try:
        quality_gate._validate_policy(policy)
    except ValueError as exc:
        raise LockedBenchmarkError(f"invalid performance quality policy: {exc}") from exc
    return policy


def load_pairing(path: Path | str) -> dict[tuple[str, str], str]:
    """Read an optional explicit mapping from diagnostic run IDs to pair IDs.

    The default pairing is the diagnostic ``run_id``.  Use a sidecar only when
    an external harness cannot assign the same stable run ID to baseline and
    candidate attempts.  The mapping intentionally contains opaque IDs only.
    """
    value = _load_json(Path(path))
    if value.get("schema_version") != 1:
        raise LockedBenchmarkError("pairing.schema_version must equal 1")
    pairs = value.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise LockedBenchmarkError("pairing.pairs must be a non-empty array")
    mapping: dict[tuple[str, str], str] = {}
    for index, row in enumerate(pairs):
        if not isinstance(row, Mapping) or set(row) != {"track_id", "run_id", "pair_id"}:
            raise LockedBenchmarkError(f"pairing.pairs[{index}] must contain only track_id, run_id, and pair_id")
        key = (
            _opaque_reference(row["track_id"], f"pairing.pairs[{index}].track_id"),
            _opaque_reference(row["run_id"], f"pairing.pairs[{index}].run_id"),
        )
        if key in mapping:
            raise LockedBenchmarkError(f"pairing has duplicate mapping for track {key[0]!r} and run {key[1]!r}")
        mapping[key] = _opaque_reference(row["pair_id"], f"pairing.pairs[{index}].pair_id")
    return mapping


def _resolve_pair_ids(
    diagnostics: Sequence[Mapping[str, Any]], pairing: Mapping[tuple[str, str], str] | None
) -> dict[tuple[str, str], str]:
    expected = {(diagnostic["track_id"], diagnostic["run_id"]) for diagnostic in diagnostics}
    if pairing is None:
        resolved = {key: _opaque_reference(key[1], "diagnostic run_id") for key in expected}
    else:
        extras = sorted(set(pairing) - expected)
        missing = sorted(expected - set(pairing))
        if extras or missing:
            raise LockedBenchmarkError("pairing must map every and only the supplied diagnostic run identities")
        resolved = dict(pairing)
    seen: set[tuple[str, str]] = set()
    for (track_id, run_id), pair_id in resolved.items():
        _opaque_reference(track_id, "pairing track_id")
        _opaque_reference(run_id, "pairing run_id")
        _opaque_reference(pair_id, "pairing pair_id")
        identity = (track_id, pair_id)
        if identity in seen:
            raise LockedBenchmarkError(f"pairing maps multiple diagnostics to pair {pair_id!r} for track {track_id!r}")
        seen.add(identity)
    return resolved


def _validate_common_environment(diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not diagnostics:
        raise LockedBenchmarkError("at least one diagnostic report is required")
    common = gate_environment(diagnostics[0])
    encoded_common = contract.canonical_json(common)
    for diagnostic in diagnostics[1:]:
        candidate = gate_environment(diagnostic)
        if contract.canonical_json(candidate) != encoded_common:
            raise LockedBenchmarkError(
                "diagnostics do not share one controlled benchmark environment, "
                "model manifest, preprocessing version, configuration, seed, and thermal profile"
            )
    return common


def load_diagnostics(
    manifest: Mapping[str, Any],
    inputs: Iterable[Path | str],
    *,
    require_complete_corpus: bool = True,
) -> list[dict[str, Any]]:
    """Load strict contract diagnostics and bind every one to the manifest."""
    _validate_runner_manifest(manifest, allow_template=False)
    diagnostics: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    run_ids: set[str] = set()
    diagnostic_hashes: set[str] = set()
    for path in discover_diagnostic_paths(inputs):
        diagnostic = dict(_load_json(path))
        contract.validate_against_corpus(diagnostic, manifest)
        identity = (diagnostic["track_id"], diagnostic["run_id"])
        if identity in identities:
            raise LockedBenchmarkError(
                f"duplicate diagnostic run identity for track {identity[0]!r} and run {identity[1]!r}"
            )
        if diagnostic["run_id"] in run_ids:
            raise LockedBenchmarkError("duplicate diagnostic run_id across the aggregate")
        digest = contract.digest_json(diagnostic)
        if digest in diagnostic_hashes:
            raise LockedBenchmarkError("identical diagnostic content was supplied more than once")
        identities.add(identity)
        run_ids.add(diagnostic["run_id"])
        diagnostic_hashes.add(digest)
        diagnostics.append(diagnostic)

    diagnostics.sort(key=lambda item: (item["track_id"], item["run_id"], contract.digest_json(item)))
    _validate_common_environment(diagnostics)
    if require_complete_corpus:
        expected = {track["track_id"] for track in manifest["tracks"]}
        observed = {diagnostic["track_id"] for diagnostic in diagnostics}
        missing = sorted(expected - observed)
        if missing:
            raise LockedBenchmarkError(
                "diagnostics are missing locked corpus tracks: " + ", ".join(missing)
            )
    return diagnostics


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _summary(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("cannot summarize an empty sequence")
    numbers = [float(value) for value in values]
    return {
        "count": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "p90": _percentile(numbers, 0.90),
        "p95": _percentile(numbers, 0.95),
        "p99": _percentile(numbers, 0.99),
        "min": min(numbers),
        "max": max(numbers),
    }


def _diagnostic_statistics(diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize host-measured timings without conflating tracks or stages."""
    by_track: dict[str, dict[str, Any]] = {}
    for diagnostic in diagnostics:
        track_id = diagnostic["track_id"]
        state = by_track.setdefault(
            track_id,
            {
                "execution": defaultdict(list),
                "stage_timings": defaultdict(lambda: defaultdict(list)),
                "cache_status_counts": defaultdict(Counter),
            },
        )
        for field, value in diagnostic["execution"].items():
            state["execution"][field].append(float(value))
        for stage in diagnostic["stages"]:
            stage_id = stage["stage_id"]
            for field, value in stage["timings"].items():
                state["stage_timings"][stage_id][field].append(float(value))
            state["cache_status_counts"][stage_id][stage["cache"]["status"]] += 1

    result: dict[str, Any] = {"by_track": {}}
    for track_id in sorted(by_track):
        state = by_track[track_id]
        result["by_track"][track_id] = {
            "run_count": len(state["execution"]["wall_clock_seconds"]),
            "execution": {
                field: _summary(values) for field, values in sorted(state["execution"].items())
            },
            "stage_timings": {
                stage_id: {
                    field: _summary(values) for field, values in sorted(timings.items())
                }
                for stage_id, timings in sorted(state["stage_timings"].items())
            },
            "cache_status_counts": {
                stage_id: dict(sorted(counts.items()))
                for stage_id, counts in sorted(state["cache_status_counts"].items())
            },
        }
    return result


def validation_summary(diagnostics: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    counts = Counter(diagnostic["track_id"] for diagnostic in diagnostics)
    return {
        "schema_version": 1,
        "format": "lightforge.locked-benchmark-validation.v1",
        "valid": True,
        "corpus": {
            "corpus_id": manifest["corpus_id"],
            "manifest_sha256": contract.corpus_manifest_sha256(manifest),
            "complete": {track["track_id"] for track in manifest["tracks"]} == set(counts),
        },
        "environment": _validate_common_environment(diagnostics),
        "run_counts": dict(sorted(counts.items())),
    }


def aggregate_diagnostics(
    manifest: Mapping[str, Any],
    inputs: Iterable[Path | str],
    *,
    policy: Mapping[str, Any],
    protocol_id: str,
    cache_mode: str,
    pairing: Mapping[tuple[str, str], str] | None = None,
    minimum_runs_per_track: int | None = None,
    report_side: str | None = None,
    change: Mapping[str, Any] | None = None,
    human_perceptual_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic, performance-gate-compatible benchmark input."""
    try:
        policy_metrics, policy_tracks, policy_minimum_pairs, _, _, policy_profile = quality_gate._validate_policy(dict(policy))
    except ValueError as exc:
        raise LockedBenchmarkError(f"invalid performance quality policy: {exc}") from exc
    protocol_id = _opaque_id(protocol_id, "protocol_id")
    cache_mode = _opaque_id(cache_mode, "cache_mode")
    if minimum_runs_per_track is None:
        minimum_runs_per_track = policy_minimum_pairs
    if not isinstance(minimum_runs_per_track, int) or isinstance(minimum_runs_per_track, bool):
        raise LockedBenchmarkError("minimum_runs_per_track must be a positive integer")
    if minimum_runs_per_track < 1:
        raise LockedBenchmarkError("minimum_runs_per_track must be a positive integer")
    if minimum_runs_per_track < policy_minimum_pairs:
        raise LockedBenchmarkError(
            "minimum_runs_per_track cannot be lower than policy.minimum_pairs_per_track"
        )
    manifest_tracks = {track["track_id"] for track in manifest["tracks"]}
    if manifest_tracks != policy_tracks:
        raise LockedBenchmarkError(
            "policy.required_tracks must exactly match the locked corpus track IDs before aggregation"
        )
    release_corpus_contract = None
    if policy_profile["mode"] == "release":
        expected = policy_profile["locked_corpus"]
        actual = {
            "corpus_id": manifest.get("corpus_id"),
            "manifest_sha256": contract.corpus_manifest_sha256(manifest),
        }
        if actual != expected:
            raise LockedBenchmarkError(
                "release policy locked_corpus does not exactly match the aggregation manifest"
            )
        try:
            release_corpus_contract = quality_gate.validate_locked_corpus_manifest(manifest, dict(policy))
        except ValueError as exc:
            raise LockedBenchmarkError(f"release corpus contract is invalid: {exc}") from exc
        if report_side not in {"baseline", "candidate"}:
            raise LockedBenchmarkError("release aggregation requires report_side baseline or candidate")
    elif report_side is not None and report_side not in {"baseline", "candidate"}:
        raise LockedBenchmarkError("report_side must be baseline or candidate when supplied")
    diagnostics = load_diagnostics(manifest, inputs, require_complete_corpus=True)
    counts = Counter(diagnostic["track_id"] for diagnostic in diagnostics)
    too_few = {
        track_id: counts[track_id]
        for track_id in sorted(track["track_id"] for track in manifest["tracks"])
        if counts[track_id] < minimum_runs_per_track
    }
    if too_few:
        rendered = ", ".join(f"{track_id}={count}" for track_id, count in too_few.items())
        raise LockedBenchmarkError(
            f"locked corpus requires at least {minimum_runs_per_track} runs per track; got {rendered}"
        )

    environment = _validate_common_environment(diagnostics)
    pair_ids = _resolve_pair_ids(diagnostics, pairing)
    runs = []
    for diagnostic in diagnostics:
        run = contract.benchmark_run(diagnostic)
        run["pair_id"] = pair_ids[(diagnostic["track_id"], diagnostic["run_id"])]
        run["condition"] = {"cache_mode": cache_mode}
        runs.append(run)
    aggregate = {
        "schema_version": quality_gate.SCHEMA_VERSION,
        "format": "lightforge.locked-benchmark-runs.v2",
        "suite": {
            "corpus_id": manifest["corpus_id"],
            "corpus_manifest_sha256": contract.corpus_manifest_sha256(manifest),
            "protocol_id": protocol_id,
            "policy_sha256": quality_gate.policy_sha256(dict(policy)),
        },
        "corpus": {"track_ids": sorted(track["track_id"] for track in manifest["tracks"]), "complete": True},
        # This top-level shape is deliberately compatible with the existing
        # performance_quality_gate.py paired-report schema.  ``environment``
        # remains a readable aggregate summary; the gate compares authoritative
        # per-run provenance and condition fields.
        "environment": environment,
        "runs": runs,
        "run_counts": dict(sorted(counts.items())),
        "minimum_pairs_per_track": minimum_runs_per_track,
        "diagnostic_statistics": _diagnostic_statistics(diagnostics),
    }
    if release_corpus_contract is not None:
        # This immutable projection makes it clear which corpus coverage and
        # golden-artifact contract was used to create the gate input, without
        # adding audio, paths, titles, or annotation content to diagnostics.
        aggregate["release_corpus_contract"] = release_corpus_contract
    if policy_profile["mode"] == "release" and report_side == "candidate":
        pipeline_versions = {item["provenance"]["implementation"].get("pipeline_version") for item in diagnostics}
        source_hashes = {item["provenance"]["implementation"].get("source_sha256") for item in diagnostics}
        if len(pipeline_versions) != 1 or len(source_hashes) != 1:
            raise LockedBenchmarkError("release candidate diagnostics must share one source and pipeline identity")
        pipeline_version = next(iter(pipeline_versions))
        source_sha256 = next(iter(source_hashes))
        try:
            quality_gate._require_string(pipeline_version, "release candidate pipeline_version")
            quality_gate._require_sha256(source_sha256, "release candidate source_sha256", reject_placeholder=True)
        except ValueError as exc:
            raise LockedBenchmarkError(f"release candidate identity is invalid: {exc}") from exc
        aggregate["candidate_identity"] = {
            "source_sha256": source_sha256,
            "pipeline_version": pipeline_version,
        }
    if change is not None:
        if not isinstance(change, Mapping):
            raise LockedBenchmarkError("change must be a JSON object")
        aggregate["change"] = json.loads(contract.canonical_json(dict(change)))
    if human_perceptual_review is not None:
        if not isinstance(human_perceptual_review, Mapping):
            raise LockedBenchmarkError("human_perceptual_review must be a JSON object")
        if change is None:
            raise LockedBenchmarkError("human_perceptual_review requires an explicit candidate change classification")
        aggregate["human_perceptual_review"] = json.loads(
            contract.canonical_json(dict(human_perceptual_review))
        )
    if policy_profile["mode"] == "release":
        if report_side == "candidate" and (change is None or human_perceptual_review is None):
            raise LockedBenchmarkError(
                "release candidate aggregation requires change classification and externally attested blinded review"
            )
        if report_side == "baseline" and (change is not None or human_perceptual_review is not None):
            raise LockedBenchmarkError("release baseline aggregation cannot carry candidate review evidence")
    try:
        _, _, issues = quality_gate._index_report(
            aggregate, policy_metrics, quality_gate.policy_sha256(dict(policy))
        )
    except ValueError as exc:
        raise LockedBenchmarkError(f"aggregate is not accepted by the performance quality gate: {exc}") from exc
    if issues:
        reasons = ", ".join(sorted({str(issue.get("reason", "invalid_run")) for issue in issues}))
        raise LockedBenchmarkError(f"aggregate is not gate-ready: {reasons}")
    return aggregate


def _write_or_print(value: Mapping[str, Any], output: str | None) -> None:
    if output:
        contract.atomic_write_json(output, value)
        print(f"wrote {Path(output).name}")
    else:
        print(contract.canonical_json(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("validate-manifest", help="validate a locked corpus manifest")
    manifest.add_argument("--manifest", required=True)
    manifest.add_argument(
        "--allow-template",
        action="store_true",
        help="validate the checked-in redacted template without treating it as release-ready",
    )
    manifest.add_argument("--output", help="optional JSON summary output")

    reports = commands.add_parser("validate-reports", help="validate diagnostics against a locked corpus")
    reports.add_argument("--manifest", required=True)
    reports.add_argument("--reports", required=True, nargs="+", help="diagnostic JSON files or directories")
    reports.add_argument(
        "--allow-incomplete-corpus",
        action="store_true",
        help="permit validation during bring-up; aggregate always requires complete coverage",
    )
    reports.add_argument("--output", help="optional JSON summary output")

    aggregate = commands.add_parser("aggregate", help="create a quality-gate input from validated diagnostics")
    aggregate.add_argument("--manifest", required=True)
    aggregate.add_argument("--reports", required=True, nargs="+", help="diagnostic JSON files or directories")
    aggregate.add_argument("--policy", required=True, help="committed performance quality gate policy")
    aggregate.add_argument("--protocol-id", required=True, help="opaque benchmark protocol identifier shared by baseline and candidate")
    aggregate.add_argument("--cache-mode", required=True, help="controlled cache condition, for example cold or warm")
    aggregate.add_argument(
        "--pairing",
        help="optional JSON mapping of diagnostic (track_id, run_id) values to stable cross-side pair IDs",
    )
    aggregate.add_argument(
        "--minimum-runs-per-track",
        type=int,
        help="override the policy minimum only for a stricter local preflight; defaults to policy.minimum_pairs_per_track",
    )
    aggregate.add_argument(
        "--report-side",
        choices=("baseline", "candidate"),
        help="required for a release policy so candidate review evidence cannot be omitted by ambiguity",
    )
    aggregate.add_argument(
        "--change-classification",
        choices=("minor", "major"),
        help="candidate change classification; release policy requires it before comparison",
    )
    aggregate.add_argument(
        "--change-id",
        help="opaque ID bound to --change-classification, for example semantic-pipeline-rework",
    )
    aggregate.add_argument(
        "--human-perceptual-review",
        help="structured blinded A/B review JSON for a major candidate change; validated by the gate",
    )
    aggregate.add_argument("--output", required=True, help="gate-compatible benchmark JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-manifest":
            manifest = load_manifest(args.manifest, allow_template=args.allow_template)
            _write_or_print(
                {
                    "schema_version": 1,
                    "format": "lightforge.locked-benchmark-manifest-validation.v1",
                    "valid": True,
                    "corpus_id": manifest["corpus_id"],
                    "manifest_sha256": contract.corpus_manifest_sha256(manifest),
                    "track_count": len(manifest["tracks"]),
                    "release_ready": bool(manifest.get("release_ready", False)),
                },
                args.output,
            )
            return 0
        manifest = load_manifest(args.manifest)
        if args.command == "validate-reports":
            diagnostics = load_diagnostics(
                manifest,
                args.reports,
                require_complete_corpus=not args.allow_incomplete_corpus,
            )
            _write_or_print(validation_summary(diagnostics, manifest), args.output)
            return 0
        if args.command == "aggregate":
            policy = load_gate_policy(args.policy)
            pairing = load_pairing(args.pairing) if args.pairing else None
            if bool(args.change_classification) != bool(args.change_id):
                raise LockedBenchmarkError("--change-classification and --change-id must be supplied together")
            change = None
            if args.change_classification:
                change = {
                    "classification": args.change_classification,
                    "change_id": _opaque_reference(args.change_id, "change_id"),
                }
            review = _load_json(Path(args.human_perceptual_review)) if args.human_perceptual_review else None
            _write_or_print(
                aggregate_diagnostics(
                    manifest,
                    args.reports,
                    policy=policy,
                    protocol_id=args.protocol_id,
                    cache_mode=args.cache_mode,
                    pairing=pairing,
                    minimum_runs_per_track=args.minimum_runs_per_track,
                    report_side=args.report_side,
                    change=change,
                    human_perceptual_review=review,
                ),
                args.output,
            )
            return 0
        parser.error("unknown command")
    except (LockedBenchmarkError, contract.ContractValidationError, OSError, ValueError) as exc:
        print(f"locked-benchmark-runner: {exc}", file=sys.stderr)
        return 2
    return 2  # pragma: no cover - argparse command selection is exhaustive.


if __name__ == "__main__":
    raise SystemExit(main())

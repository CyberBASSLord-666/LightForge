#!/usr/bin/env python3
"""Fail-closed, paired performance and music-quality release gate.

The gate has deliberately no numerical dependencies. It validates the evidence
before comparing it: an optimization cannot pass merely because a median hides
one bad vocal, bass, rhythm, or structure run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path


SCHEMA_VERSION = 3
COMPARABILITY_PATHS = (
    "provenance.workload.corpus_id",
    "provenance.workload.corpus_manifest_sha256",
    "provenance.workload.audio.content_sha256",
    "provenance.workload.analysis_configuration",
    "provenance.implementation.preprocessing_version",
    "provenance.implementation.model_versions",
    "provenance.environment.hardware_fingerprint",
    "provenance.environment.runtime_backend",
    "provenance.environment.runtime_version",
    "provenance.environment.accelerator",
    "provenance.environment.random_seed",
    "provenance.environment.thermal_profile",
    "condition.cache_mode",
)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def policy_sha256(policy):
    """Hash the committed policy before benchmark reports are collected."""
    return hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()


def percentile(values, q):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    position = (len(values) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (position - lower)


def summary(values):
    values = [float(value) for value in values]
    if not values:
        raise ValueError("cannot summarize an empty series")
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "min": min(values),
        "max": max(values),
    }


def _get(value, path):
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _flatten_metrics(prefix, value, output):
    if isinstance(value, dict):
        if not value:
            raise ValueError(f"{prefix or 'metrics'} must not be empty")
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("metric keys must be non-empty strings")
            _flatten_metrics(f"{prefix}.{key}" if prefix else key, child, output)
    elif _is_finite_number(value):
        output[prefix] = float(value)
    else:
        raise ValueError(f"{prefix or 'metric'} must be a finite numeric leaf")


def _require_string(value, path):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _validate_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    metrics = policy.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("policy.metrics must be a non-empty object")
    tracks = policy.get("required_tracks")
    if not isinstance(tracks, list) or not tracks or not all(isinstance(track, str) and track for track in tracks):
        raise ValueError("policy.required_tracks must be a non-empty string array")
    if len(set(tracks)) != len(tracks):
        raise ValueError("policy.required_tracks must not contain duplicates")
    minimum_pairs = policy.get("minimum_pairs_per_track", 5)
    if not isinstance(minimum_pairs, int) or isinstance(minimum_pairs, bool) or minimum_pairs < 3:
        raise ValueError("policy.minimum_pairs_per_track must be at least three")
    bootstrap = policy.get("bootstrap", {})
    if not isinstance(bootstrap, dict):
        raise ValueError("policy.bootstrap must be an object")
    if bootstrap.get("method", "paired-percentile-v1") != "paired-percentile-v1":
        raise ValueError("policy.bootstrap.method is unsupported")
    confidence = bootstrap.get("confidence", 0.99)
    resamples = bootstrap.get("resamples", 20000)
    _require_string(bootstrap.get("seed", "lightforge-performance-quality-v3"), "policy.bootstrap.seed")
    if not _is_finite_number(confidence) or not 0.5 < float(confidence) < 1.0:
        raise ValueError("policy.bootstrap.confidence must be between 0.5 and 1")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 256:
        raise ValueError("policy.bootstrap.resamples must be at least 256")
    for name, rule in metrics.items():
        if not isinstance(name, str) or not name or not isinstance(rule, dict):
            raise ValueError("every policy metric requires a non-empty name and object rule")
        if rule.get("direction", "higher") not in {"higher", "lower"}:
            raise ValueError(f"metric {name} has an invalid direction")
        tolerance = rule.get("equivalence_tolerance", 0)
        hard = rule.get("pair_hard_regression", tolerance)
        if not _is_finite_number(tolerance) or float(tolerance) < 0:
            raise ValueError(f"metric {name} has an invalid equivalence_tolerance")
        if not _is_finite_number(hard) or float(hard) < 0:
            raise ValueError(f"metric {name} has an invalid pair_hard_regression")
        bounds = rule.get("bounds")
        if bounds is not None:
            if not isinstance(bounds, list) or len(bounds) != 2 or not all(_is_finite_number(value) for value in bounds) or float(bounds[0]) > float(bounds[1]):
                raise ValueError(f"metric {name} has invalid bounds")
    runtime = policy.get("runtime_target")
    if not isinstance(runtime, dict):
        raise ValueError("policy.runtime_target must be an object")
    metric = runtime.get("metric")
    if not isinstance(metric, str) or metric not in metrics:
        raise ValueError("runtime_target.metric must be a declared policy metric")
    reduction = runtime.get("target_reduction_percent", 75)
    if not _is_finite_number(reduction) or float(reduction) < 0 or float(reduction) > 100:
        raise ValueError("runtime target reduction must be within 0..100")
    if runtime.get("scope", "each_required_track") != "each_required_track":
        raise ValueError("only each_required_track runtime scope is supported")
    return metrics, set(tracks), minimum_pairs, bootstrap, runtime


def _validate_suite(report, expected_policy_sha):
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"report.schema_version must equal {SCHEMA_VERSION}")
    suite = report.get("suite")
    if not isinstance(suite, dict):
        raise ValueError("report.suite must be an object")
    for path in ("corpus_id", "corpus_manifest_sha256", "protocol_id", "policy_sha256"):
        _require_string(suite.get(path), f"report.suite.{path}")
    if suite["policy_sha256"] != expected_policy_sha:
        raise ValueError("report suite policy_sha256 does not match the supplied policy")
    return suite


def _index_report(report, policy_metrics, expected_policy_sha):
    suite = _validate_suite(report, expected_policy_sha)
    runs = report.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("report.runs must be a non-empty array")
    indexed, run_ids, issues = {}, set(), []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise ValueError("every run must be an object")
        track_id = _require_string(run.get("track_id"), f"runs[{index}].track_id")
        pair_id = _require_string(run.get("pair_id"), f"runs[{index}].pair_id")
        run_id = _require_string(run.get("run_id"), f"runs[{index}].run_id")
        if run_id in run_ids:
            issues.append({"run_id": run_id, "reason": "duplicate_run_id"})
        run_ids.add(run_id)
        key = (track_id, pair_id)
        if key in indexed:
            issues.append({"track": track_id, "pair_id": pair_id, "reason": "duplicate_track_pair"})
        metrics = run.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"runs[{index}].metrics must be an object")
        flattened = {}
        _flatten_metrics("", metrics, flattened)
        for name, rule in policy_metrics.items():
            if rule.get("required", True) and name not in flattened:
                issues.append({"track": track_id, "pair_id": pair_id, "metric": name, "reason": "missing_metric"})
            if name in flattened and rule.get("bounds") is not None:
                lower, upper = map(float, rule["bounds"])
                if not lower <= flattened[name] <= upper:
                    issues.append({"track": track_id, "pair_id": pair_id, "metric": name, "reason": "metric_out_of_bounds", "value": flattened[name], "bounds": [lower, upper]})
        provenance = run.get("provenance")
        condition = run.get("condition")
        if not isinstance(provenance, dict):
            raise ValueError(f"runs[{index}].provenance must be an object")
        if not isinstance(condition, dict):
            raise ValueError(f"runs[{index}].condition must be an object")
        _require_string(condition.get("cache_mode"), f"runs[{index}].condition.cache_mode")
        indexed[key] = {"run": run, "metrics": flattened}
    return suite, indexed, issues


def _stable_bootstrap(values, *, seed, confidence, resamples):
    values = [float(value) for value in values]
    if not values:
        return None, None
    if len(values) == 1 or min(values) == max(values):
        return values[0], values[0]
    digest = hashlib.sha256((seed + "|" + canonical_json(values)).encode("utf-8")).digest()
    state = int.from_bytes(digest[:8], "big") or 1
    mask = (1 << 64) - 1
    draws = []
    for _ in range(resamples):
        total = 0.0
        for _ in values:
            state ^= state >> 12
            state ^= (state << 25) & mask
            state ^= state >> 27
            state = (state * 2685821657736338717) & mask
            total += values[state % len(values)]
        draws.append(total / len(values))
    alpha = (1.0 - confidence) / 2.0
    return percentile(draws, alpha), percentile(draws, 1.0 - alpha)


def _compare_pair_provenance(baseline, candidate):
    differences = []
    for path in COMPARABILITY_PATHS:
        before, after = _get(baseline, path), _get(candidate, path)
        if before is None or after is None or canonical_json(before) != canonical_json(after):
            differences.append({"field": path, "baseline": before, "candidate": after})
    return differences


def _classify_effect(deltas, tolerance, hard_floor, bootstrap, seed):
    lower, upper = _stable_bootstrap(
        deltas,
        seed=seed,
        confidence=float(bootstrap.get("confidence", 0.99)),
        resamples=int(bootstrap.get("resamples", 20000)),
    )
    if any(delta < -hard_floor for delta in deltas) or upper < -tolerance:
        classification = "regressed"
    elif lower > 0:
        classification = "improved"
    elif lower >= -tolerance and upper <= tolerance:
        classification = "statistically_equivalent"
    else:
        classification = "inconclusive"
    return classification, lower, upper


def compare(baseline, candidate, policy):
    policy_metrics, required_tracks, minimum_pairs, bootstrap, runtime_target = _validate_policy(policy)
    expected_policy_sha = policy_sha256(policy)
    baseline_suite, baseline_runs, baseline_issues = _index_report(baseline, policy_metrics, expected_policy_sha)
    candidate_suite, candidate_runs, candidate_issues = _index_report(candidate, policy_metrics, expected_policy_sha)
    blockers = [*baseline_issues, *candidate_issues]
    if canonical_json(baseline_suite) != canonical_json(candidate_suite):
        blockers.append({"reason": "incomparable_suite", "baseline": baseline_suite, "candidate": candidate_suite})
    if "__configure_locked_corpus__" in required_tracks:
        blockers.append({"reason": "unconfigured_locked_corpus"})
    baseline_tracks = {track for track, _ in baseline_runs}
    candidate_tracks = {track for track, _ in candidate_runs}
    missing_tracks = sorted(required_tracks - (baseline_tracks & candidate_tracks))
    for track in sorted((baseline_tracks | candidate_tracks) - required_tracks):
        blockers.append({"track": track, "reason": "unexpected_track"})
    for track in sorted(baseline_tracks ^ candidate_tracks):
        blockers.append({"track": track, "reason": "track_not_present_in_both_reports"})
    baseline_keys, candidate_keys = set(baseline_runs), set(candidate_runs)
    for track, pair_id in sorted(baseline_keys ^ candidate_keys):
        blockers.append({"track": track, "pair_id": pair_id, "reason": "unpaired_run"})
    paired = sorted(baseline_keys & candidate_keys)
    pairs_by_track = {track: [] for track in required_tracks}
    for key in paired:
        pairs_by_track.setdefault(key[0], []).append(key)
        for difference in _compare_pair_provenance(baseline_runs[key]["run"], candidate_runs[key]["run"]):
            blockers.append({"track": key[0], "pair_id": key[1], "reason": "incomparable_pair_provenance", **difference})
    for track in sorted(required_tracks):
        actual = len(pairs_by_track.get(track, []))
        if actual < minimum_pairs:
            blockers.append({"track": track, "reason": "insufficient_paired_runs", "actual": actual, "minimum": minimum_pairs})
    comparisons, runtime = [], []
    for track in sorted(required_tracks & baseline_tracks & candidate_tracks):
        keys = pairs_by_track.get(track, [])
        for metric, rule in sorted(policy_metrics.items()):
            deltas, rows = [], []
            for key in keys:
                before = baseline_runs[key]["metrics"].get(metric)
                after = candidate_runs[key]["metrics"].get(metric)
                if before is None or after is None:
                    continue
                # Positive always means candidate improved regardless of metric direction.
                delta = after - before if rule.get("direction", "higher") == "higher" else before - after
                deltas.append(delta)
                rows.append({"pair_id": key[1], "baseline": before, "candidate": after, "effect": delta})
            if len(deltas) != len(keys):
                continue  # Missing metrics already produced a release blocker.
            tolerance = float(rule.get("equivalence_tolerance", 0))
            hard_floor = float(rule.get("pair_hard_regression", tolerance))
            classification, lower, upper = _classify_effect(deltas, tolerance, hard_floor, bootstrap, f"{bootstrap.get('seed')}|{track}|{metric}")
            row = {
                "track": track,
                "metric": metric,
                "critical": bool(rule.get("critical", False)),
                "classification": classification,
                "equivalence_tolerance": tolerance,
                "pair_hard_regression": hard_floor,
                "paired_effect": summary(deltas),
                "paired_mean_effect_ci": [lower, upper],
                "pairs": rows,
            }
            comparisons.append(row)
            if row["critical"] and classification in {"regressed", "inconclusive"}:
                blockers.append({"reason": f"critical_{classification}", "track": track, "metric": metric, "paired_mean_effect_ci": [lower, upper]})
        runtime_metric = runtime_target["metric"]
        reductions = []
        for key in keys:
            before = baseline_runs[key]["metrics"].get(runtime_metric)
            after = candidate_runs[key]["metrics"].get(runtime_metric)
            if before is None or after is None:
                continue
            if before <= 0:
                blockers.append({"track": track, "pair_id": key[1], "metric": runtime_metric, "reason": "non_positive_baseline_runtime"})
            else:
                reductions.append(100.0 * (before - after) / before)
        if len(reductions) == len(keys) and reductions:
            lower, upper = _stable_bootstrap(reductions, seed=f"{bootstrap.get('seed')}|{track}|runtime", confidence=float(bootstrap.get("confidence", 0.99)), resamples=int(bootstrap.get("resamples", 20000)))
            runtime.append({"track": track, "paired_reduction_percent": summary(reductions), "paired_mean_reduction_ci": [lower, upper], "target_reduction_percent": float(runtime_target["target_reduction_percent"]), "target_met": lower >= float(runtime_target["target_reduction_percent"])})
    target_met = bool(runtime) and len(runtime) == len(required_tracks) and all(row["target_met"] for row in runtime)
    status = "FAIL" if missing_tracks or blockers else ("PASS_TARGET" if target_met else "PASS_PARTIAL")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "production_ready": status == "PASS_TARGET",
        "quality_regressions_detected": any(row["classification"] == "regressed" for row in comparisons),
        "missing_required_tracks": missing_tracks,
        "blockers": blockers,
        "comparisons": comparisons,
        "runtime": runtime,
        "suite": baseline_suite,
        "policy_sha256": expected_policy_sha,
        "bootstrap": bootstrap,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    with Path(args.baseline).open(encoding="utf-8") as stream:
        baseline = json.load(stream)
    with Path(args.candidate).open(encoding="utf-8") as stream:
        candidate = json.load(stream)
    with Path(args.policy).open(encoding="utf-8") as stream:
        policy = json.load(stream)
    result = compare(baseline, candidate, policy)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"quality-gate={result['status']} target-tracks={sum(row['target_met'] for row in result['runtime'])}/{len(result['runtime'])}")
    return 0 if result["status"] == "PASS_TARGET" or (args.allow_partial and result["status"] == "PASS_PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Deterministic baseline-vs-candidate performance and quality release gate."""
from __future__ import annotations

import argparse, json, math, statistics, sys
from pathlib import Path


def percentile(values, q):
    values = sorted(float(v) for v in values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] if lo == hi else values[lo] + (values[hi] - values[lo]) * (pos - lo)


def summary(values):
    values = [float(v) for v in values]
    return {"count": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
            "p90": percentile(values, .90), "p95": percentile(values, .95), "p99": percentile(values, .99),
            "min": min(values), "max": max(values)}


def load(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def flatten(prefix, value, out):
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(f"{prefix}.{key}" if prefix else key, child, out)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix] = float(value)


def aggregate(report):
    runs = report.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("report.runs must be a non-empty array")
    tracks = {}
    for run in runs:
        track = run.get("track_id")
        if not isinstance(track, str) or not track:
            raise ValueError("every run requires track_id")
        numeric = {}; flatten("", run.get("metrics", {}), numeric)
        for name, value in numeric.items():
            tracks.setdefault(track, {}).setdefault(name, []).append(value)
    return {track: {name: summary(vals) for name, vals in metrics.items()} for track, metrics in tracks.items()}


def compare(baseline, candidate, policy):
    b, c = aggregate(baseline), aggregate(candidate)
    required_tracks = set(policy.get("required_tracks", []))
    missing = sorted(required_tracks - (set(b) & set(c)))
    results, blockers = [], []
    metric_policy = policy.get("metrics", {})
    for track in sorted(set(b) & set(c)):
        for name, rule in sorted(metric_policy.items()):
            if name not in b[track] or name not in c[track]:
                if rule.get("required", True): blockers.append({"track":track,"metric":name,"reason":"missing_metric"})
                continue
            stat = rule.get("stat", "median")
            bv, cv = b[track][name][stat], c[track][name][stat]
            direction = rule.get("direction", "higher")
            abs_tol = float(rule.get("absolute_tolerance", 0))
            rel_tol = float(rule.get("relative_tolerance", 0))
            tolerance = max(abs_tol, abs(bv) * rel_tol)
            delta = cv - bv
            regressed = delta < -tolerance if direction == "higher" else delta > tolerance
            classification = "regressed" if regressed else ("improved" if (delta > tolerance if direction == "higher" else delta < -tolerance) else "statistically_equivalent")
            row = {"track":track,"metric":name,"stat":stat,"baseline":bv,"candidate":cv,"delta":delta,
                   "percent_change":None if bv == 0 else 100*delta/bv,"classification":classification,
                   "critical":bool(rule.get("critical", False)),"tolerance":tolerance}
            results.append(row)
            if regressed and row["critical"]: blockers.append({**row,"reason":"critical_regression"})
    perf = [r for r in results if r["metric"] == policy.get("runtime_metric", "performance.total_wall_clock_seconds")]
    reductions = [-r["percent_change"] for r in perf if r["percent_change"] is not None]
    reduction = statistics.median(reductions) if reductions else None
    target = float(policy.get("target_reduction_percent", 75))
    status = "FAIL" if missing or blockers else ("PASS_TARGET" if reduction is not None and reduction >= target else "PASS_PARTIAL")
    return {"schema_version":1,"status":status,"production_ready":status=="PASS_TARGET","target_reduction_percent":target,
            "median_runtime_reduction_percent":reduction,"missing_required_tracks":missing,"blockers":blockers,
            "comparisons":results,"baseline_summary":b,"candidate_summary":c}


def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--baseline",required=True); p.add_argument("--candidate",required=True)
    p.add_argument("--policy",required=True); p.add_argument("--output",required=True); p.add_argument("--allow-partial",action="store_true")
    a=p.parse_args(argv)
    result=compare(load(a.baseline),load(a.candidate),load(a.policy))
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"quality-gate={result['status']} runtime-reduction={result['median_runtime_reduction_percent']}")
    return 0 if result["status"]=="PASS_TARGET" or (a.allow_partial and result["status"]=="PASS_PARTIAL") else 1


if __name__ == "__main__": sys.exit(main())

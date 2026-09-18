#!/usr/bin/env python3
"""Fail-closed admission gate for LightForge inference-placement candidates.

This gate does not run models and cannot qualify a release by itself. It accepts
only an already-completed performance/quality report, then applies the product
constraints that are easy to lose when comparing local, hybrid, and remote
execution: full-pipeline latency, failure recovery, privacy, cost, and result
provenance. The output is deterministic and contains no audio or credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "lightforge.execution-candidate.v1"
REPORT_SCHEMA = "lightforge.execution-admission.v1"
PLACEMENTS = {"device", "hybrid", "remote"}
HEX_256 = set("0123456789abcdef")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def benchmark_evidence_sha256(report: dict[str, Any]) -> str:
    """Match performance_quality_gate's circular-signature projection."""
    projection = dict(report)
    review = projection.get("human_perceptual_review")
    if isinstance(review, dict):
        projection["human_perceptual_review"] = {
            key: value for key, value in review.items() if key != "attestation"
        }
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
    return sha256(encoded)


def finite_number(value: Any, name: str, minimum: float = 0) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
            name + " must be a finite number >= " + str(minimum))
    return float(value)


def digest(value: Any, name: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX_256,
            name + " must be a lower-case SHA-256 digest")
    return value


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    require(isinstance(value, dict), path.name + " must contain a JSON object")
    return value, sha256(raw)


def validate_candidate(value: dict[str, Any]) -> dict[str, Any]:
    require(value.get("schema") == SCHEMA, "Unsupported candidate schema")
    candidate_id = value.get("candidateId")
    require(isinstance(candidate_id, str) and 1 <= len(candidate_id) <= 120 and
            all(c.isalnum() or c in "._-" for c in candidate_id), "Invalid candidateId")
    placement = value.get("placement")
    require(placement in PLACEMENTS, "placement must be device, hybrid, or remote")
    source = value.get("source", {})
    require(isinstance(source, dict), "source binding is required")
    source_binding = {
        "implementationSha256": digest(source.get("implementationSha256"),
                                        "source.implementationSha256"),
        "modelSetSha256": digest(source.get("modelSetSha256"), "source.modelSetSha256"),
        "pipelineVersion": source.get("pipelineVersion"),
    }
    require(isinstance(source_binding["pipelineVersion"], str) and
            1 <= len(source_binding["pipelineVersion"]) <= 160,
            "source.pipelineVersion is required")
    result_contract = value.get("resultContract")
    require(result_contract == "lightforge-analysis-v8",
            "Candidate must return the complete LightForge analysis v8 contract")
    fallback = value.get("fallback", {})
    require(isinstance(fallback, dict) and fallback.get("preservesCompletedWork") is True and
            fallback.get("devicePathAvailable") is True,
            "A resumable device fallback is required")
    privacy = value.get("privacy", {})
    require(isinstance(privacy, dict), "privacy declaration is required")
    leaves = privacy.get("sourceAudioLeavesDevice")
    require(type(leaves) is bool, "privacy.sourceAudioLeavesDevice must be boolean")
    if leaves:
        require(placement in {"hybrid", "remote"}, "Device placement cannot upload source audio")
        require(privacy.get("explicitPerAnalysisConsent") is True,
                "Remote audio requires explicit per-analysis consent")
        require(privacy.get("transport") == "tls-1.3",
                "Remote audio requires declared TLS 1.3 transport")
        retention = finite_number(privacy.get("maximumRetentionHours"),
                                  "privacy.maximumRetentionHours")
        require(retention <= 24, "Remote source audio retention must not exceed 24 hours")
        require(privacy.get("trainingUse") is False,
                "User audio must not be used for training")
        require(privacy.get("credentialLocation") in {"android-keystore", "server"},
                "Credentials must not be embedded in the app payload")
    else:
        require(placement != "remote", "Remote placement must declare its audio transfer")
    operations = value.get("operations", {})
    require(isinstance(operations, dict), "operations declaration is required")
    max_cost = finite_number(operations.get("maximumCostUsdPerTrack"),
                             "operations.maximumCostUsdPerTrack")
    require(operations.get("boundedRequestBytes") is True,
            "Every request body must have an enforced size bound")
    require(operations.get("idempotentRetry") is True,
            "Candidate retries must be idempotent")
    return {"candidateId": candidate_id, "placement": placement, "source": source_binding,
            "resultContract": result_contract, "sourceAudioLeavesDevice": leaves,
            "maximumCostUsdPerTrack": max_cost}


def validate_candidate_benchmark(value: dict[str, Any], candidate: dict[str, Any]) -> None:
    require(value.get("schema_version") == 4 and isinstance(value.get("runs"), list) and
            value["runs"], "Candidate benchmark schema 4 with runs is required")
    for index, run in enumerate(value["runs"]):
        implementation = run.get("provenance", {}).get("implementation", {})
        require(implementation.get("source_sha256") == candidate["source"]["implementationSha256"],
                f"Candidate benchmark run {index} does not bind the implementation source")
        require(implementation.get("pipeline_version") == candidate["source"]["pipelineVersion"],
                f"Candidate benchmark run {index} does not bind the pipeline version")
        models = implementation.get("model_versions")
        require(isinstance(models, dict) and models,
                f"Candidate benchmark run {index} has no model identity")
        require(sha256(canonical(models)) == candidate["source"]["modelSetSha256"],
                f"Candidate benchmark run {index} does not bind the model set")


def validate_quality_report(value: dict[str, Any], candidate_benchmark_sha: str) -> dict[str, Any]:
    # This deliberately accepts only the strict gate's production result. A
    # candidate-authored "quality passed" boolean is not a trust boundary.
    require(value.get("schema_version") == 4, "Performance/quality report schema 4 is required")
    require(value.get("status") == "PASS_TARGET" and value.get("production_ready") is True,
            "Strict performance/quality gate has not admitted this candidate")
    review = value.get("human_perceptual_review", {})
    require(review.get("externally_attested") is True and
            review.get("candidate_benchmark_sha256") == candidate_benchmark_sha,
            "Quality report does not bind the exact candidate benchmark")
    runtime = value.get("runtime")
    require(isinstance(runtime, list) and runtime, "Per-track runtime results are missing")
    reductions = []
    for row in runtime:
        require(row.get("target_met") is True and row.get("target_reduction_percent") == 75,
                "Candidate has not demonstrated the 75% wall-clock target on every track")
        summary = row.get("paired_reduction_percent", {})
        reductions.append(finite_number(summary.get("median"), "paired median reduction"))
    require(min(reductions) >= 75,
            "Candidate has not demonstrated the 75% wall-clock reduction target")
    return {"trackCount": len(runtime), "minimumMedianReductionPercent": min(reductions),
            "maximumMedianReductionPercent": max(reductions)}


def evaluate(candidate_path: Path, benchmark_path: Path, quality_path: Path) -> dict[str, Any]:
    candidate_raw, candidate_file_sha = read_json(candidate_path)
    benchmark_raw, benchmark_file_sha = read_json(benchmark_path)
    quality_raw, quality_file_sha = read_json(quality_path)
    candidate = validate_candidate(candidate_raw)
    validate_candidate_benchmark(benchmark_raw, candidate)
    benchmark_evidence_sha = benchmark_evidence_sha256(benchmark_raw)
    performance = validate_quality_report(quality_raw, benchmark_evidence_sha)
    report = {"schema": REPORT_SCHEMA, "status": "ADMIT", "candidate": candidate,
              "performance": performance,
              "bindings": {"candidateFileSha256": candidate_file_sha,
                           "candidateBenchmarkFileSha256": benchmark_file_sha,
                           "candidateBenchmarkEvidenceSha256": benchmark_evidence_sha,
                           "qualityReportFileSha256": quality_file_sha,
                           "candidateCanonicalSha256": sha256(canonical(candidate_raw)),
                           "qualityReportCanonicalSha256": sha256(canonical(quality_raw))}}
    report["reportSha256"] = sha256(canonical(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-benchmark", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite an existing admission report")
    try:
        report = evaluate(args.candidate, args.candidate_benchmark, args.quality_report)
    except Exception as error:
        report = {"schema": REPORT_SCHEMA, "status": "REJECT", "reason": str(error)[:512]}
        args.output.write_bytes(canonical(report))
        raise SystemExit(str(error))
    args.output.write_bytes(canonical(report))
    print(json.dumps({"status": report["status"], "candidate": report["candidate"]["candidateId"],
                      "minimumMedianReductionPercent": round(report["performance"]["minimumMedianReductionPercent"], 4),
                      "reportSha256": report["reportSha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()

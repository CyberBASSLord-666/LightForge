#!/usr/bin/env python3
"""Development-only consistency lint for inference-placement declarations.

The historical filename does not make this a release gate. Inputs are untrusted
caller-supplied declarations, including any performance, consent or attestation
claims. Matching hashes establish internal consistency, not authenticity. This
tool does not execute models, recompute quality, verify signatures, authorize
audio transfer, approve spending, or qualify a release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "lightforge.execution-candidate.v1"
REPORT_SCHEMA = "lightforge.execution-evidence-lint.v1"
PLACEMENTS = {"device", "hybrid", "remote"}
HEX_256 = set("0123456789abcdef")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


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


def finite_number(value: Any, name: str, minimum: float | None = 0) -> float:
    require(type(value) in (int, float), name + " must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite and (minimum is None or value >= minimum),
            name + " must be a finite number" +
            (" >= " + str(minimum) if minimum is not None else ""))
    return float(value)


def digest(value: Any, name: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX_256,
            name + " must be a lower-case SHA-256 digest")
    return value


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in result, "Duplicate JSON object key")
            result[key] = item
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("Non-finite JSON numbers are not permitted")

    value = json.loads(raw, object_pairs_hook=unique_object,
                       parse_constant=reject_constant)
    require(isinstance(value, dict), path.name + " must contain a JSON object")
    # Also reject finite-looking exponent literals such as 1e999, which the
    # standard parser turns into infinity, anywhere (including unknown fields).
    canonical(value)
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
    require(isinstance(fallback, dict), "fallback declaration must be an object")
    for field in ("preservesCompletedWork", "devicePathAvailable"):
        if field in fallback:
            require(type(fallback[field]) is bool, "fallback." + field + " must be boolean")
    privacy = value.get("privacy", {})
    require(isinstance(privacy, dict), "privacy declaration is required")
    leaves = privacy.get("sourceAudioLeavesDevice")
    require(type(leaves) is bool, "privacy.sourceAudioLeavesDevice must be boolean")
    if leaves:
        require(placement in {"hybrid", "remote"}, "Device placement cannot upload source audio")
    for field in ("explicitPerAnalysisConsent", "trainingUse"):
        if field in privacy:
            require(type(privacy[field]) is bool, "privacy." + field + " must be boolean")
    for field in ("transport", "credentialLocation"):
        if field in privacy:
            require(isinstance(privacy[field], str) and privacy[field],
                    "privacy." + field + " must be a non-empty string")
    if "maximumRetentionHours" in privacy:
        finite_number(privacy["maximumRetentionHours"], "privacy.maximumRetentionHours")
    operations = value.get("operations", {})
    require(isinstance(operations, dict), "operations declaration is required")
    max_cost = finite_number(operations.get("maximumCostUsdPerTrack"),
                             "operations.maximumCostUsdPerTrack")
    for field in ("boundedRequestBytes", "idempotentRetry"):
        require(type(operations.get(field)) is bool, "operations." + field + " must be boolean")
    return {"candidateId": candidate_id, "placement": placement, "source": source_binding,
            "resultContract": result_contract, "sourceAudioLeavesDevice": leaves,
            "maximumCostUsdPerTrack": max_cost}


def validate_candidate_benchmark(value: dict[str, Any], candidate: dict[str, Any]) -> None:
    require(value.get("schema_version") == 4 and isinstance(value.get("runs"), list) and
            value["runs"], "Candidate benchmark schema 4 with runs is required")
    for index, run in enumerate(value["runs"]):
        require(isinstance(run, dict), f"Candidate benchmark run {index} must be an object")
        provenance = run.get("provenance")
        require(isinstance(provenance, dict), f"Candidate benchmark run {index} has no provenance")
        implementation = provenance.get("implementation")
        require(isinstance(implementation, dict),
                f"Candidate benchmark run {index} has no implementation identity")
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
    """Check declarations only; do not infer trust from a reported gate result."""
    require(value.get("schema_version") == 4, "Performance/quality report schema 4 is required")
    require(isinstance(value.get("status"), str) and value["status"],
            "Performance/quality report status is required")
    require(type(value.get("production_ready")) is bool,
            "Performance/quality report production_ready must be boolean")
    review = value.get("human_perceptual_review", {})
    require(isinstance(review, dict) and
            review.get("candidate_benchmark_sha256") == candidate_benchmark_sha,
            "Quality report does not bind the exact candidate benchmark")
    runtime = value.get("runtime")
    require(isinstance(runtime, list), "Per-track runtime declarations must be a list")
    reductions = []
    for row in runtime:
        require(isinstance(row, dict), "Per-track runtime declaration must be an object")
        summary = row.get("paired_reduction_percent")
        if summary is None:
            continue
        require(isinstance(summary, dict), "Paired reduction summary must be an object or null")
        reductions.append(finite_number(summary.get("median"), "Declared paired median reduction",
                                        minimum=None))
    return {"declaredStatus": value["status"],
            "declaredProductionReady": value["production_ready"],
            "declaredTrackCount": len(runtime), "declaredMeasuredTrackCount": len(reductions),
            "declaredMinimumMedianReductionPercent": min(reductions) if reductions else None,
            "declaredMaximumMedianReductionPercent": max(reductions) if reductions else None}


def evaluate(candidate_path: Path, benchmark_path: Path, quality_path: Path) -> dict[str, Any]:
    candidate_raw, candidate_file_sha = read_json(candidate_path)
    benchmark_raw, benchmark_file_sha = read_json(benchmark_path)
    quality_raw, quality_file_sha = read_json(quality_path)
    candidate = validate_candidate(candidate_raw)
    validate_candidate_benchmark(benchmark_raw, candidate)
    benchmark_evidence_sha = benchmark_evidence_sha256(benchmark_raw)
    performance = validate_quality_report(quality_raw, benchmark_evidence_sha)
    report = {"schema": REPORT_SCHEMA, "status": "LINT_PASS", "candidate": candidate,
              "releaseAuthorized": False, "authorityVerified": False,
              "evidenceTrust": "caller-supplied-unverified",
              "performanceDeclarations": performance,
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
    require(not args.output.exists(), "Refusing to overwrite an existing lint report")
    try:
        report = evaluate(args.candidate, args.candidate_benchmark, args.quality_report)
    except Exception as error:
        report = {"schema": REPORT_SCHEMA, "status": "LINT_FAIL", "releaseAuthorized": False,
                  "authorityVerified": False, "evidenceTrust": "caller-supplied-unverified",
                  "reason": str(error)[:512]}
        with args.output.open("xb") as output:
            output.write(canonical(report))
        raise SystemExit(str(error))
    with args.output.open("xb") as output:
        output.write(canonical(report))
    print(json.dumps({"status": report["status"], "candidate": report["candidate"]["candidateId"],
                      "releaseAuthorized": False, "authorityVerified": False,
                      "reportSha256": report["reportSha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()

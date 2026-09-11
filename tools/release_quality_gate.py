#!/usr/bin/env python3
"""Bind an authoritative quality-gate result to a publishable LightForge release.

The performance-quality gate already decides whether a benchmark candidate is
fit for release.  This module closes the handoff to the APK publisher: it
records the exact benchmark artifacts, successful Actions runs, candidate
commit/tree and release version, then rejects a release when any part changes.
It intentionally has no network or credential logic; GitHub API data is
collected by the protected workflow and rechecked by the publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
REPOSITORY = "CyberBASSLord-666/LightForge"
QUALITY_WORKFLOW = ".github/workflows/performance-quality-gate.yml"
RELEASE_WORKFLOW = ".github/workflows/verify-v2.yml"
QUALITY_ARTIFACT = "performance-quality-gate-report"

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha1(value: Any, label: str) -> str:
    _require(isinstance(value, str) and _SHA1.fullmatch(value) is not None, label + " must be a 40-character lowercase Git SHA")
    return value


def _sha256(value: Any, label: str) -> str:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None, label + " must be a 64-character lowercase SHA-256")
    return value


def _positive_int(value: Any, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and value > 0, label + " must be a positive integer")
    return value


def _artifact(value: Any, label: str) -> str:
    _require(isinstance(value, str) and _ARTIFACT.fullmatch(value) is not None, label + " is not a safe Actions artifact name")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_file(path: Path | str) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    _require(isinstance(value, dict), str(path) + " must contain a JSON object")
    return value


def validate_version(version: Mapping[str, Any]) -> dict[str, Any]:
    _require(set(version) == {"name", "code"}, "release version must contain exactly name and code")
    name, code = version.get("name"), version.get("code")
    _require(isinstance(name, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", name) is not None, "release version name must be dotted numeric")
    _positive_int(code, "release version code")
    return {"name": name, "code": code}


def validate_report(report: Mapping[str, Any]) -> None:
    _require(report.get("status") == "PASS_TARGET", "quality-gate report is not PASS_TARGET")
    _require(report.get("production_ready") is True, "quality-gate report is not production_ready")
    _require(report.get("quality_regressions_detected") is False, "quality-gate report detected a quality regression")
    _require(report.get("blockers") == [], "quality-gate report contains release blockers")
    profile = report.get("release_profile")
    _require(isinstance(profile, dict) and profile.get("mode") == "release", "quality-gate report was not evaluated under the release profile")
    authority = report.get("release_policy_authority")
    _require(isinstance(authority, dict) and authority.get("verified") is True, "quality-gate report has no verified release-policy authority")


def _run_identity(run: Mapping[str, Any], commit: Mapping[str, Any], label: str) -> dict[str, Any]:
    run_id = _positive_int(run.get("id"), label + " run id")
    _require(run.get("status") == "completed" and run.get("conclusion") == "success", label + " Actions run did not succeed")
    _require(isinstance(run.get("head_repository"), dict) and run["head_repository"].get("full_name") == REPOSITORY, label + " Actions run is not from the canonical repository")
    source_commit = _sha1(run.get("head_sha"), label + " source commit")
    tree = commit.get("tree") if isinstance(commit, Mapping) else None
    _require(isinstance(tree, Mapping), label + " Git commit metadata is missing its tree")
    source_tree = _sha1(tree.get("sha"), label + " source tree")
    path = run.get("path")
    _require(isinstance(path, str) and path.startswith(".github/workflows/"), label + " Actions run has an unexpected workflow path")
    return {"run_id": run_id, "artifact": None, "source_commit": source_commit, "source_tree_sha": source_tree, "workflow_path": path}


def _benchmark_identity(run: Mapping[str, Any], commit: Mapping[str, Any], artifact: str, benchmark: Path | str, label: str) -> dict[str, Any]:
    result = _run_identity(run, commit, label)
    result["artifact"] = _artifact(artifact, label + " artifact")
    result["benchmark_sha256"] = sha256_file(benchmark)
    return result


def build_provenance(
    *,
    report: Mapping[str, Any],
    report_sha256: str,
    version: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    ref: str,
    ref_protected: bool,
    quality_run_id: int,
    baseline_run: Mapping[str, Any],
    baseline_commit: Mapping[str, Any],
    baseline_artifact: str,
    baseline_benchmark: Path | str,
    candidate_run: Mapping[str, Any],
    candidate_commit: Mapping[str, Any],
    candidate_artifact: str,
    candidate_benchmark: Path | str,
) -> dict[str, Any]:
    """Create the deterministic protected-workflow receipt for a PASS_TARGET run."""
    validate_report(report)
    report_sha256 = _sha256(report_sha256, "quality-gate report digest")
    version = validate_version(version)
    source_commit = _sha1(source_commit, "quality-gate source commit")
    source_tree_sha = _sha1(source_tree_sha, "quality-gate source tree")
    _require(ref == "refs/heads/main" and ref_protected is True, "quality gate must run on protected main")
    quality_run_id = _positive_int(quality_run_id, "quality-gate workflow run id")
    baseline = _benchmark_identity(baseline_run, baseline_commit, baseline_artifact, baseline_benchmark, "baseline")
    candidate = _benchmark_identity(candidate_run, candidate_commit, candidate_artifact, candidate_benchmark, "candidate")
    _require(candidate["source_commit"] == source_commit, "candidate benchmark run is not for the quality-gate source commit")
    _require(candidate["source_tree_sha"] == source_tree_sha, "candidate benchmark run is not for the quality-gate source tree")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "lightforge-release-quality-provenance",
        "repository": REPOSITORY,
        "quality_gate": {
            "workflow": QUALITY_WORKFLOW,
            "workflow_run_id": quality_run_id,
            "source_commit": source_commit,
            "source_tree_sha": source_tree_sha,
            "ref": ref,
            "ref_protected": True,
            "event": "workflow_dispatch",
        },
        "release": version,
        "baseline": baseline,
        "candidate": candidate,
        "report": {
            "sha256": report_sha256,
            "status": "PASS_TARGET",
            "production_ready": True,
            "quality_regressions_detected": False,
        },
    }


def validate_release_policy(policy: Mapping[str, Any], *, version: Mapping[str, Any], source_commit: str, source_tree_sha: str) -> dict[str, Any]:
    """Validate the source-pinned opt-in or explicit non-performance waiver."""
    expected = {"schema_version", "release", "source_commit", "source_tree_sha", "requirement", "classification", "reason"}
    _require(set(policy) == expected, "release quality policy has unexpected or missing fields")
    _require(policy.get("schema_version") == SCHEMA_VERSION, "release quality policy schema is unsupported")
    _require(validate_version(policy.get("release")) == validate_version(version), "release quality policy belongs to another version")
    _require(_sha1(policy.get("source_commit"), "release quality policy source commit") == _sha1(source_commit, "release source commit"), "release quality policy is not pinned to the candidate source commit")
    _require(_sha1(policy.get("source_tree_sha"), "release quality policy source tree") == _sha1(source_tree_sha, "release source tree"), "release quality policy is not pinned to the candidate source tree")
    requirement = policy.get("requirement")
    classification = policy.get("classification")
    _require(requirement in {"performance_quality_gate", "not_required"}, "release quality policy has an invalid requirement")
    _require(
        (requirement == "performance_quality_gate" and classification == "performance")
        or (requirement == "not_required" and classification == "non-performance"),
        "release quality policy requirement and classification disagree",
    )
    reason = policy.get("reason")
    _require(isinstance(reason, str) and 12 <= len(reason) <= 1000 and "\n" not in reason, "release quality policy reason must be a concise explicit justification")
    return dict(policy)


def validate_publication_evidence(
    report: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    version: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    quality_run: Mapping[str, Any],
    quality_commit: Mapping[str, Any],
    release_candidate_run: Mapping[str, Any],
    release_candidate_commit: Mapping[str, Any],
    report_sha256: str,
) -> dict[str, Any]:
    """Fail closed unless report, protected run and release candidate all agree."""
    validate_report(report)
    version = validate_version(version)
    source_commit = _sha1(source_commit, "release source commit")
    source_tree_sha = _sha1(source_tree_sha, "release source tree")
    required = {"schema_version", "kind", "repository", "quality_gate", "release", "baseline", "candidate", "report"}
    _require(set(provenance) == required, "quality-gate provenance has unexpected or missing fields")
    _require(provenance.get("schema_version") == SCHEMA_VERSION and provenance.get("kind") == "lightforge-release-quality-provenance", "quality-gate provenance schema is unsupported")
    _require(provenance.get("repository") == REPOSITORY, "quality-gate provenance repository mismatch")
    _require(validate_version(provenance.get("release")) == version, "quality-gate provenance release version mismatch")
    report_receipt = provenance.get("report")
    _require(isinstance(report_receipt, dict) and set(report_receipt) == {"sha256", "status", "production_ready", "quality_regressions_detected"}, "quality-gate provenance report receipt is invalid")
    report_sha256 = _sha256(report_sha256, "quality-gate report digest")
    _require(_sha256(report_receipt.get("sha256"), "quality-gate report digest") == report_sha256, "quality-gate report digest differs from its provenance")
    _require(report_receipt == {"sha256": report_sha256, "status": "PASS_TARGET", "production_ready": True, "quality_regressions_detected": False}, "quality-gate provenance weakens its report result")
    gate = provenance.get("quality_gate")
    _require(isinstance(gate, dict) and set(gate) == {"workflow", "workflow_run_id", "source_commit", "source_tree_sha", "ref", "ref_protected", "event"}, "quality-gate provenance gate identity is invalid")
    _require(gate.get("workflow") == QUALITY_WORKFLOW and gate.get("ref") == "refs/heads/main" and gate.get("ref_protected") is True and gate.get("event") == "workflow_dispatch", "quality-gate provenance is not a protected manual quality run")
    _require(_sha1(gate.get("source_commit"), "quality-gate provenance source commit") == source_commit, "quality-gate provenance commit differs from release candidate")
    _require(_sha1(gate.get("source_tree_sha"), "quality-gate provenance source tree") == source_tree_sha, "quality-gate provenance tree differs from release candidate")
    quality_identity = _run_identity(quality_run, quality_commit, "quality-gate")
    _require(quality_identity["run_id"] == _positive_int(gate.get("workflow_run_id"), "quality-gate provenance run id"), "quality-gate Actions run differs from its provenance")
    _require(quality_identity["workflow_path"] == QUALITY_WORKFLOW and quality_run.get("event") == "workflow_dispatch", "quality-gate Actions run used an unexpected workflow or event")
    _require(quality_identity["source_commit"] == source_commit and quality_identity["source_tree_sha"] == source_tree_sha, "quality-gate Actions run is not on the release source")
    release_identity = _run_identity(release_candidate_run, release_candidate_commit, "release candidate")
    _require(release_identity["workflow_path"] == RELEASE_WORKFLOW, "release candidate did not use production verification")
    _require(release_identity["source_commit"] == source_commit and release_identity["source_tree_sha"] == source_tree_sha, "release candidate CI differs from the quality-gate source")
    candidate = provenance.get("candidate")
    baseline = provenance.get("baseline")
    for label, item in (("candidate", candidate), ("baseline", baseline)):
        _require(isinstance(item, dict) and set(item) == {"run_id", "artifact", "source_commit", "source_tree_sha", "workflow_path", "benchmark_sha256"}, label + " benchmark provenance is invalid")
        _positive_int(item.get("run_id"), label + " benchmark run id")
        _artifact(item.get("artifact"), label + " benchmark artifact")
        _sha1(item.get("source_commit"), label + " benchmark source commit")
        _sha1(item.get("source_tree_sha"), label + " benchmark source tree")
        _sha256(item.get("benchmark_sha256"), label + " benchmark digest")
        _require(isinstance(item.get("workflow_path"), str) and item["workflow_path"].startswith(".github/workflows/"), label + " benchmark workflow path is invalid")
    _require(candidate["source_commit"] == source_commit and candidate["source_tree_sha"] == source_tree_sha, "candidate benchmark evidence is not for the release source")
    return {"quality_gate_run_id": quality_identity["run_id"], "candidate_benchmark_run_id": candidate["run_id"], "candidate_benchmark_artifact": candidate["artifact"], "report_sha256": report_receipt["sha256"]}


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-provenance")
    create.add_argument("--report", required=True, type=Path)
    create.add_argument("--version-json", required=True, type=Path)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--source-tree-sha", required=True)
    create.add_argument("--ref", required=True)
    create.add_argument("--ref-protected", required=True, choices=["true"])
    create.add_argument("--quality-run-id", required=True, type=int)
    for side in ("baseline", "candidate"):
        create.add_argument("--" + side + "-run-json", required=True, type=Path)
        create.add_argument("--" + side + "-commit-json", required=True, type=Path)
        create.add_argument("--" + side + "-artifact", required=True)
        create.add_argument("--" + side + "-benchmark", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = load_json(args.report)
    value = build_provenance(
        report=report,
        report_sha256=sha256_file(args.report),
        version=load_json(args.version_json),
        source_commit=args.source_commit,
        source_tree_sha=args.source_tree_sha,
        ref=args.ref,
        ref_protected=args.ref_protected == "true",
        quality_run_id=args.quality_run_id,
        baseline_run=load_json(args.baseline_run_json),
        baseline_commit=load_json(args.baseline_commit_json),
        baseline_artifact=args.baseline_artifact,
        baseline_benchmark=args.baseline_benchmark,
        candidate_run=load_json(args.candidate_run_json),
        candidate_commit=load_json(args.candidate_commit_json),
        candidate_artifact=args.candidate_artifact,
        candidate_benchmark=args.candidate_benchmark,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"quality_gate_run_id": value["quality_gate"]["workflow_run_id"], "candidate_benchmark_sha256": value["candidate"]["benchmark_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

#!/usr/bin/env python3
"""Bind an authoritative quality-gate result to a publishable LightForge release.

The performance-quality gate decides whether a benchmark candidate meets its
qualification policy. This module closes the handoff to the APK publisher: it
records the exact benchmark artifacts, successful Actions runs, candidate
commit/tree, release version, and the candidate's explicit release
declaration.  A declaration deliberately contains no commit/tree value: a
file cannot contain the hash of the tree that contains itself.  Its canonical
digest is instead bound by the later immutable release request and, for a
performance-qualified release, this protected-workflow provenance receipt.
The explicitly authorized automated-only publication policies retain
all APK verification requirements and report comparative qualification as
unverified; they cannot produce performance-quality PASS_TARGET provenance.

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
# Benchmark aggregates are accepted only from the protected manual producer
# implemented by the canonical performance-quality workflow.  The workflow's
# benchmark job invokes locked_benchmark_runner.py with the release corpus and
# policy held by its protected environment; arbitrary successful Actions runs
# are not interchangeable evidence.
BENCHMARK_WORKFLOW = QUALITY_WORKFLOW
RELEASE_SCOPE_SCHEMA_VERSION = 1
# The owner removed external qualification inputs for 2.2.5 and subsequently
# authorized publishing the musical-intelligence/inference release when ready
# without user-supplied measurements. Keep explicit version/code pairs: this
# publication policy never generates PASS_TARGET or a measured quality claim.
AUTOMATED_VERIFICATION_ONLY_RELEASES = frozenset({
    ("2.2.5", 20205),
    ("2.3.0", 20300),
    ("2.3.1", 20301),
    ("2.3.2", 20302),
})

# A waiver is deliberately much narrower than "does not look like a model
# change".  It is only for a release whose delta is demonstrably limited to
# prose, release identity and the source-pinned declaration.  Everything that
# can change a shipped bit, its verification, or the release authority falls
# through to the protected performance-quality gate.
NONPERFORMANCE_ROOT_DOCUMENTS = frozenset({
    "ARCHITECTURE.md",
    "ASSETS.md",
    "BUILD.md",
    "CHANGELOG.md",
    "INSTALL_OVER_1.5_to_1.6_CHECKLIST.md",
    "README.md",
    "RELEASE_NOTES.md",
    "REPOSITORY.md",
    "RESOURCES_MAP.md",
    "VALIDATION.md",
    "VERSIONING.md",
})
_REGULAR_FILE_MODE = "100644"
_ABSENT_MODE = "000000"

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


def sha256_canonical_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def version_key(version: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return a strict sortable semantic-version key for a release object."""
    normalized = validate_version(version)
    return tuple(int(part) for part in normalized["name"].split("."))


def parse_raw_tree_diff(raw: bytes | str) -> list[dict[str, str]]:
    """Parse complete ``git diff --raw -z --no-renames`` output.

    ``-z`` is essential: paths may contain whitespace, and a line-oriented
    parser can silently misclassify a path.  Rename detection is disabled so a
    runtime file moved under a documentation directory is still represented by
    its forbidden deletion.  Modes are retained to reject symlink, executable,
    submodule and type changes even when their path is otherwise allowlisted.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Git tree diff contains a non-UTF-8 path") from error
    else:
        _require(isinstance(raw, str), "Git tree diff must be bytes or text")
        text = raw
    tokens = text.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    _require(len(tokens) % 2 == 0, "Git tree diff is not a complete NUL-delimited name-status stream")
    changes: list[dict[str, str]] = []
    for index in range(0, len(tokens), 2):
        header, path = tokens[index], tokens[index + 1]
        parts = header.split(" ")
        _require(len(parts) == 5 and parts[0].startswith(":"), "Git tree diff has an invalid raw header")
        old_mode, new_mode = parts[0][1:], parts[1]
        old_sha, new_sha, status = parts[2:]
        _require(re.fullmatch(r"(?:000000|[0-7]{6})", old_mode) is not None, "Git tree diff has an invalid old mode")
        _require(re.fullmatch(r"(?:000000|[0-7]{6})", new_mode) is not None, "Git tree diff has an invalid new mode")
        _require(re.fullmatch(r"[0-9a-f]{40}", old_sha) is not None, "Git tree diff has an invalid old object")
        _require(re.fullmatch(r"[0-9a-f]{40}", new_sha) is not None, "Git tree diff has an invalid new object")
        _require(status in {"A", "D", "M", "T"}, "Git tree diff has an unsupported status")
        _require(
            isinstance(path, str)
            and path
            and not path.startswith("/")
            and "\\" not in path
            and all(part not in {"", ".", ".."} for part in path.split("/")),
            "Git tree diff has an unsafe repository path",
        )
        changes.append({
            "status": status,
            "path": path,
            "old_mode": old_mode,
            "new_mode": new_mode,
        })
    _require(len({item["path"] for item in changes}) == len(changes), "Git tree diff reports a path more than once")
    return sorted(changes, key=lambda item: item["path"])


def _regular_change(change: Mapping[str, str]) -> bool:
    """Return whether a change is an ordinary 0644 file add/modify/delete."""
    status = change.get("status")
    old_mode, new_mode = change.get("old_mode"), change.get("new_mode")
    return (
        (status == "A" and old_mode == _ABSENT_MODE and new_mode == _REGULAR_FILE_MODE)
        or (status == "M" and old_mode == _REGULAR_FILE_MODE and new_mode == _REGULAR_FILE_MODE)
        or (status == "D" and old_mode == _REGULAR_FILE_MODE and new_mode == _ABSENT_MODE)
    )


def _nonperformance_path_allowed(change: Mapping[str, str], version: Mapping[str, Any]) -> bool:
    """Whether one raw tree change is harmless enough for a waiver.

    This deliberately makes false positives safe: an allowlist miss requires a
    PASS_TARGET run, rather than allowing an unreviewed performance change.
    """
    if not _regular_change(change):
        return False
    path = change["path"]
    release = validate_version(version)
    declaration = "releases/v" + release["name"] + "/quality-gate-declaration.json"
    if path == declaration:
        return change["status"] == "A"
    if path == "version.json":
        return change["status"] == "M"
    if path == "web/version.js":
        return change["status"] == "M"
    return (
        path in NONPERFORMANCE_ROOT_DOCUMENTS
        or (path.startswith("docs/") and path.endswith(".md"))
    )


def derive_release_scope(
    *,
    base_release: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    version: Mapping[str, Any],
    raw_tree_diff: bytes | str,
    generated_web_version_valid: bool,
) -> dict[str, Any]:
    """Derive the only classification a source declaration may request.

    ``base_release`` is supplied by the publisher after it has recovered the
    previous published release's source-bound candidate record.  The candidate
    declaration never selects this baseline and cannot turn a disallowed path
    into a waiver.  The caller must independently prove source ancestry before
    invoking this function.
    """
    expected_base = {
        "tag",
        "target_commit",
        "source_commit",
        "source_tree_sha",
        "version",
    }
    _require(set(base_release) == expected_base, "release scope baseline has unexpected or missing fields")
    tag = base_release.get("tag")
    _require(isinstance(tag, str) and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is not None, "release scope baseline tag is invalid")
    base_version = validate_version(base_release.get("version"))
    _require(tag == "v" + base_version["name"], "release scope baseline tag and version disagree")
    release = validate_version(version)
    _require(version_key(base_version) < version_key(release), "release scope baseline is not older than the candidate release")
    _require(base_version["code"] < release["code"], "release scope baseline code is not lower than the candidate release")
    target_commit = _sha1(base_release.get("target_commit"), "release scope baseline target commit")
    baseline_commit = _sha1(base_release.get("source_commit"), "release scope baseline source commit")
    baseline_tree = _sha1(base_release.get("source_tree_sha"), "release scope baseline source tree")
    candidate_commit = _sha1(source_commit, "release scope candidate source commit")
    candidate_tree = _sha1(source_tree_sha, "release scope candidate source tree")
    _require(candidate_commit != baseline_commit and candidate_tree != baseline_tree, "release scope candidate is identical to the published baseline")
    changes = parse_raw_tree_diff(raw_tree_diff)
    _require(changes, "release scope candidate has no tree changes from the published baseline")
    declaration = "releases/v" + release["name"] + "/quality-gate-declaration.json"
    allowed = all(_nonperformance_path_allowed(change, release) for change in changes)
    declaration_added = any(change["path"] == declaration and change["status"] == "A" for change in changes)
    version_changed = any(change["path"] == "version.json" and change["status"] == "M" for change in changes)
    web_version_changed = any(change["path"] == "web/version.js" and change["status"] == "M" for change in changes)
    if not declaration_added or not version_changed or not web_version_changed or not generated_web_version_valid:
        allowed = False
    scope = {
        "schema_version": RELEASE_SCOPE_SCHEMA_VERSION,
        "kind": "lightforge-release-scope",
        "base_release": {
            "tag": tag,
            "target_commit": target_commit,
            "source_commit": baseline_commit,
            "source_tree_sha": baseline_tree,
            "version": base_version,
        },
        "source": {"commit": candidate_commit, "tree_sha": candidate_tree},
        "release": release,
        "changes": changes,
        "classification": "non-performance" if allowed else "performance",
    }
    scope["sha256"] = sha256_canonical_json(scope)
    return scope


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


def _artifact_identity(
    artifact_record: Mapping[str, Any],
    *,
    run_identity: Mapping[str, Any],
    artifact_name: str,
    label: str,
) -> dict[str, Any]:
    """Validate immutable Actions metadata before it becomes release evidence.

    The workflow resolves an artifact by exact ID before download.  Recording
    its server-provided digest here prevents a later same-name artifact (or a
    caller-supplied name from another run) from being treated as the reviewed
    benchmark.  The publisher repeats this validation against the live API.
    """
    _require(isinstance(artifact_record, Mapping), label + " artifact metadata is invalid")
    artifact_id = _positive_int(artifact_record.get("id"), label + " artifact id")
    _require(artifact_record.get("name") == artifact_name, label + " artifact name differs from the selected artifact")
    _require(artifact_record.get("expired") is False, label + " artifact has expired")
    size = _positive_int(artifact_record.get("size_in_bytes"), label + " artifact size")
    digest = artifact_record.get("digest")
    _require(isinstance(digest, str) and digest.startswith("sha256:"), label + " artifact digest is invalid")
    digest = _sha256(digest.removeprefix("sha256:"), label + " artifact digest")
    workflow = artifact_record.get("workflow_run")
    _require(isinstance(workflow, Mapping), label + " artifact workflow provenance is invalid")
    _require(
        workflow.get("id") == run_identity["run_id"]
        and workflow.get("head_sha") == run_identity["source_commit"]
        and workflow.get("head_branch") == "main",
        label + " artifact does not belong to the protected benchmark run",
    )
    return {
        "artifact": artifact_name,
        "artifact_id": artifact_id,
        "artifact_digest": digest,
        "artifact_size_bytes": size,
    }


def _benchmark_identity(
    run: Mapping[str, Any],
    commit: Mapping[str, Any],
    artifact: str,
    artifact_record: Mapping[str, Any],
    benchmark: Path | str | None,
    label: str,
) -> dict[str, Any]:
    result = _run_identity(run, commit, label)
    _require(
        result["workflow_path"] == BENCHMARK_WORKFLOW
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main",
        label + " benchmark did not use the canonical locked benchmark workflow",
    )
    result.update(
        _artifact_identity(
            artifact_record,
            run_identity=result,
            artifact_name=_artifact(artifact, label + " artifact"),
            label=label,
        )
    )
    if benchmark is not None:
        result["benchmark_sha256"] = sha256_file(benchmark)
    return result


def build_provenance(
    *,
    report: Mapping[str, Any],
    report_sha256: str,
    version: Mapping[str, Any],
    release_declaration: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    ref: str,
    ref_protected: bool,
    quality_run_id: int,
    baseline_run: Mapping[str, Any],
    baseline_commit: Mapping[str, Any],
    baseline_artifact: str,
    baseline_artifact_record: Mapping[str, Any],
    baseline_benchmark: Path | str,
    candidate_run: Mapping[str, Any],
    candidate_commit: Mapping[str, Any],
    candidate_artifact: str,
    candidate_artifact_record: Mapping[str, Any],
    candidate_benchmark: Path | str,
    release_candidate_run: Mapping[str, Any],
    release_candidate_commit: Mapping[str, Any],
    release_candidate_artifact: str,
) -> dict[str, Any]:
    """Create the deterministic protected-workflow receipt for a PASS_TARGET run."""
    validate_report(report)
    report_sha256 = _sha256(report_sha256, "quality-gate report digest")
    version = validate_version(version)
    release_declaration = validate_release_declaration(release_declaration, version=version)
    _require(
        release_declaration["requirement"] == "performance_quality_gate",
        "PASS_TARGET provenance requires a performance quality-gate declaration",
    )
    source_commit = _sha1(source_commit, "quality-gate source commit")
    source_tree_sha = _sha1(source_tree_sha, "quality-gate source tree")
    _require(ref == "refs/heads/main" and ref_protected is True, "quality gate must run on protected main")
    quality_run_id = _positive_int(quality_run_id, "quality-gate workflow run id")
    baseline = _benchmark_identity(
        baseline_run, baseline_commit, baseline_artifact, baseline_artifact_record, baseline_benchmark, "baseline"
    )
    candidate = _benchmark_identity(
        candidate_run, candidate_commit, candidate_artifact, candidate_artifact_record, candidate_benchmark, "candidate"
    )
    _require(candidate["source_commit"] == source_commit, "candidate benchmark run is not for the quality-gate source commit")
    _require(candidate["source_tree_sha"] == source_tree_sha, "candidate benchmark run is not for the quality-gate source tree")
    release_candidate = _run_identity(release_candidate_run, release_candidate_commit, "release candidate")
    _require(release_candidate["workflow_path"] == RELEASE_WORKFLOW, "release candidate did not use production verification")
    _require(release_candidate["source_commit"] == source_commit, "release candidate CI is not for the quality-gate source commit")
    _require(release_candidate["source_tree_sha"] == source_tree_sha, "release candidate CI is not for the quality-gate source tree")
    release_candidate["artifact"] = _artifact(release_candidate_artifact, "release candidate artifact")
    _require(
        release_candidate["artifact"] == "lightforge-" + version["name"] + "-ci-candidate",
        "release candidate artifact does not name the current release",
    )
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
        "release_declaration": {
            "sha256": sha256_canonical_json(release_declaration),
            "requirement": "performance_quality_gate",
            "classification": "performance",
        },
        "baseline": baseline,
        "candidate": candidate,
        "release_candidate": release_candidate,
        "report": {
            "sha256": report_sha256,
            "status": "PASS_TARGET",
            "production_ready": True,
            "quality_regressions_detected": False,
        },
    }


def validate_release_declaration(declaration: Mapping[str, Any], *, version: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the source-bound qualification or publication policy.

    The declaration is stored in the candidate tree, so it must not claim its
    own commit or tree hash.  ``validate_declaration_receipt`` binds it to
    those values after the candidate commit exists.
    """
    expected = {"schema_version", "release", "requirement", "classification", "reason"}
    _require(set(declaration) == expected, "release quality declaration has unexpected or missing fields")
    _require(type(declaration.get("schema_version")) is int and declaration["schema_version"] == SCHEMA_VERSION, "release quality declaration schema is unsupported")
    _require(validate_version(declaration.get("release")) == validate_version(version), "release quality declaration belongs to another version")
    requirement = declaration.get("requirement")
    classification = declaration.get("classification")
    _require(requirement in {"performance_quality_gate", "not_required", "automated_verification_only"}, "release quality declaration has an invalid requirement")
    _require(
        (requirement == "performance_quality_gate" and classification == "performance")
        or (requirement == "not_required" and classification == "non-performance")
        or (requirement == "automated_verification_only" and classification == "performance"),
        "release quality declaration requirement and classification disagree",
    )
    if requirement == "automated_verification_only":
        _require(
            (validate_version(version)["name"], validate_version(version)["code"])
            in AUTOMATED_VERIFICATION_ONLY_RELEASES,
            "automated-verification-only publication is authorized only for explicitly listed release/version-code pairs",
        )
    reason = declaration.get("reason")
    _require(isinstance(reason, str) and 12 <= len(reason) <= 1000 and "\n" not in reason, "release quality declaration reason must be a concise explicit justification")
    return dict(declaration)


def validate_declaration_receipt(
    receipt: Mapping[str, Any],
    *,
    version: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the post-CI release-request binding for a source declaration."""
    expected = {"schema_version", "source_commit", "source_tree_sha", "declaration_sha256"}
    _require(set(receipt) == expected, "release quality declaration receipt has unexpected or missing fields")
    _require(type(receipt.get("schema_version")) is int and receipt["schema_version"] == SCHEMA_VERSION, "release quality declaration receipt schema is unsupported")
    validate_release_declaration(declaration, version=version)
    _require(
        _sha1(receipt.get("source_commit"), "release quality declaration receipt source commit")
        == _sha1(source_commit, "release source commit"),
        "release quality declaration receipt is not pinned to the candidate source commit",
    )
    _require(
        _sha1(receipt.get("source_tree_sha"), "release quality declaration receipt source tree")
        == _sha1(source_tree_sha, "release source tree"),
        "release quality declaration receipt is not pinned to the candidate source tree",
    )
    expected_digest = sha256_canonical_json(declaration)
    _require(
        _sha256(receipt.get("declaration_sha256"), "release quality declaration digest") == expected_digest,
        "release quality declaration digest differs from the candidate source declaration",
    )
    return dict(receipt)


def validate_publication_evidence(
    report: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    version: Mapping[str, Any],
    source_declaration: Mapping[str, Any],
    source_commit: str,
    source_tree_sha: str,
    quality_run: Mapping[str, Any],
    quality_commit: Mapping[str, Any],
    baseline_run: Mapping[str, Any],
    baseline_commit: Mapping[str, Any],
    baseline_artifact_record: Mapping[str, Any],
    candidate_run: Mapping[str, Any],
    candidate_commit: Mapping[str, Any],
    candidate_artifact_record: Mapping[str, Any],
    release_candidate_run: Mapping[str, Any],
    release_candidate_commit: Mapping[str, Any],
    report_sha256: str,
) -> dict[str, Any]:
    """Fail closed unless report, protected run and release candidate all agree."""
    validate_report(report)
    version = validate_version(version)
    source_declaration = validate_release_declaration(source_declaration, version=version)
    _require(
        source_declaration["requirement"] == "performance_quality_gate",
        "performance quality provenance cannot authorize a declaration that does not require that gate",
    )
    source_commit = _sha1(source_commit, "release source commit")
    source_tree_sha = _sha1(source_tree_sha, "release source tree")
    required = {"schema_version", "kind", "repository", "quality_gate", "release", "release_declaration", "baseline", "candidate", "release_candidate", "report"}
    _require(set(provenance) == required, "quality-gate provenance has unexpected or missing fields")
    _require(provenance.get("schema_version") == SCHEMA_VERSION and provenance.get("kind") == "lightforge-release-quality-provenance", "quality-gate provenance schema is unsupported")
    _require(provenance.get("repository") == REPOSITORY, "quality-gate provenance repository mismatch")
    _require(validate_version(provenance.get("release")) == version, "quality-gate provenance release version mismatch")
    declaration_receipt = provenance.get("release_declaration")
    _require(
        isinstance(declaration_receipt, dict)
        and declaration_receipt
        == {
            "sha256": sha256_canonical_json(source_declaration),
            "requirement": "performance_quality_gate",
            "classification": "performance",
        },
        "quality-gate provenance declaration differs from the release candidate",
    )
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
    release_candidate_receipt = provenance.get("release_candidate")
    _require(
        isinstance(release_candidate_receipt, dict)
        and release_candidate_receipt
        == {
            "run_id": release_identity["run_id"],
            "artifact": "lightforge-" + version["name"] + "-ci-candidate",
            "source_commit": source_commit,
            "source_tree_sha": source_tree_sha,
            "workflow_path": RELEASE_WORKFLOW,
        },
        "quality-gate provenance release candidate differs from the artifact being published",
    )
    candidate = provenance.get("candidate")
    baseline = provenance.get("baseline")
    benchmark_fields = {
        "run_id",
        "artifact",
        "artifact_id",
        "artifact_digest",
        "artifact_size_bytes",
        "source_commit",
        "source_tree_sha",
        "workflow_path",
        "benchmark_sha256",
    }
    for label, item, live_run, live_commit, live_artifact in (
        ("candidate", candidate, candidate_run, candidate_commit, candidate_artifact_record),
        ("baseline", baseline, baseline_run, baseline_commit, baseline_artifact_record),
    ):
        _require(isinstance(item, dict) and set(item) == benchmark_fields, label + " benchmark provenance is invalid")
        live_identity = _benchmark_identity(
            live_run,
            live_commit,
            _artifact(item.get("artifact"), label + " benchmark artifact"),
            live_artifact,
            None,
            label,
        )
        expected = dict(live_identity)
        expected["benchmark_sha256"] = _sha256(item.get("benchmark_sha256"), label + " benchmark digest")
        _require(item == expected, label + " benchmark provenance differs from the live artifact identity")
    _require(candidate["source_commit"] == source_commit and candidate["source_tree_sha"] == source_tree_sha, "candidate benchmark evidence is not for the release source")
    return {
        "quality_gate_run_id": quality_identity["run_id"],
        "candidate_benchmark_run_id": candidate["run_id"],
        "candidate_benchmark_artifact": candidate["artifact"],
        "candidate_benchmark_artifact_id": candidate["artifact_id"],
        "candidate_benchmark_artifact_digest": candidate["artifact_digest"],
        "release_candidate_run_id": release_identity["run_id"],
        "release_candidate_artifact": release_candidate_receipt["artifact"],
        "report_sha256": report_receipt["sha256"],
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-provenance")
    create.add_argument("--report", required=True, type=Path)
    create.add_argument("--version-json", required=True, type=Path)
    create.add_argument("--release-declaration-json", required=True, type=Path)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--source-tree-sha", required=True)
    create.add_argument("--ref", required=True)
    create.add_argument("--ref-protected", required=True, choices=["true"])
    create.add_argument("--quality-run-id", required=True, type=int)
    for side in ("baseline", "candidate"):
        create.add_argument("--" + side + "-run-json", required=True, type=Path)
        create.add_argument("--" + side + "-commit-json", required=True, type=Path)
        create.add_argument("--" + side + "-artifact", required=True)
        create.add_argument("--" + side + "-artifact-json", required=True, type=Path)
        create.add_argument("--" + side + "-benchmark", required=True, type=Path)
    create.add_argument("--release-candidate-run-json", required=True, type=Path)
    create.add_argument("--release-candidate-commit-json", required=True, type=Path)
    create.add_argument("--release-candidate-artifact", required=True)
    create.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = load_json(args.report)
    value = build_provenance(
        report=report,
        report_sha256=sha256_file(args.report),
        version=load_json(args.version_json),
        release_declaration=load_json(args.release_declaration_json),
        source_commit=args.source_commit,
        source_tree_sha=args.source_tree_sha,
        ref=args.ref,
        ref_protected=args.ref_protected == "true",
        quality_run_id=args.quality_run_id,
        baseline_run=load_json(args.baseline_run_json),
        baseline_commit=load_json(args.baseline_commit_json),
        baseline_artifact=args.baseline_artifact,
        baseline_artifact_record=load_json(args.baseline_artifact_json),
        baseline_benchmark=args.baseline_benchmark,
        candidate_run=load_json(args.candidate_run_json),
        candidate_commit=load_json(args.candidate_commit_json),
        candidate_artifact=args.candidate_artifact,
        candidate_artifact_record=load_json(args.candidate_artifact_json),
        candidate_benchmark=args.candidate_benchmark,
        release_candidate_run=load_json(args.release_candidate_run_json),
        release_candidate_commit=load_json(args.release_candidate_commit_json),
        release_candidate_artifact=args.release_candidate_artifact,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"quality_gate_run_id": value["quality_gate"]["workflow_run_id"], "candidate_benchmark_sha256": value["candidate"]["benchmark_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

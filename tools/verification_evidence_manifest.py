#!/usr/bin/env python3
"""Seal success-only non-Android verify-v2 receipts for release publication.

The broad ``lightforge-<version>-verification`` Actions artifact is retained
for diagnostics and deliberately uploads under ``if: always()``.  It is never
release authority.  This module creates a separate, exact evidence content
artifact only after the verify job has completed all of its ordinary steps,
then a tiny wrapper artifact after Actions has assigned the content artifact an
immutable ID and digest.  The wrapper makes the otherwise self-referential
artifact identity auditable without trusting a checkout receipt or an artifact
name glob.

The candidate artifact is the common provenance root shared with Android
instrumentation evidence.  A failed-job-only rerun may have a newer
``GITHUB_RUN_ATTEMPT`` than the original verify/candidate job; consequently all
names and bindings are derived from the candidate manifest's pipeline identity,
not from a later retry attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping


# Candidate manifests are consumed by the Android handoff as well as this
# evidence chain. Keep that stable schema at 1; the content and wrapper schemas
# independently advance when their sealed receipt records evolve.
CANDIDATE_SCHEMA_VERSION = 1
CONTENT_SCHEMA_VERSION = 2
WRAPPER_SCHEMA_VERSION = 2
REPOSITORY = "CyberBASSLord-666/LightForge"
WORKFLOW = ".github/workflows/verify-v2.yml"
CANDIDATE_KIND = "lightforge-ci-candidate"
CONTENT_KIND = "lightforge-verify-v2-nonandroid-evidence"
WRAPPER_KIND = "lightforge-verify-v2-nonandroid-evidence-manifest"
CONTENT_MANIFEST = "verification-evidence-content.json"
WRAPPER_MANIFEST = "verification-evidence-manifest.json"

RECEIPTS = {
    "regression-verification.json": "receipts/regression-verification.json",
    "browser-verification.json": "receipts/browser-verification.json",
    "background-ui-verification.json": "receipts/background-ui-verification.json",
    "restore-preview-verification.json": "receipts/restore-preview-verification.json",
    "native-verification.json": "receipts/native-verification.json",
    "analysis-browser-verification.json": "receipts/analysis-browser-verification.json",
    "analysis-verification.json": "receipts/analysis-verification.json",
}
CAMELCASE_SESSION_RECEIPTS = frozenset({
    "browser-verification.json",
    "background-ui-verification.json",
    "restore-preview-verification.json",
    "analysis-browser-verification.json",
})
ANALYSIS_SESSION_RECEIPT = "analysis-verification.json"
EVIDENCE_SESSION_SCHEMA = "lightforge.evidence-session.v1"

# These are deliberately narrow.  A receipt source that is not the exact byte
# from the candidate tree must be one of these reviewed CI-only materials; a
# new path fails sealing until its provenance policy is explicitly reviewed.
DEUX_RECONSTRUCTED_MATERIALS = (
    "block-00-frequency.onnx",
    "block-00-time.onnx",
    "block-01-frequency.onnx",
    "block-01-time.onnx",
    "block-02-frequency.onnx",
    "block-02-time.onnx",
    "block-03-frequency.onnx",
    "block-03-time.onnx",
    "block-04-frequency.onnx",
    "block-04-time.onnx",
    "block-05-frequency.onnx",
    "block-05-time.onnx",
    "block-06-frequency.onnx",
    "block-06-time.onnx",
    "block-07-frequency.onnx",
    "block-07-time.onnx",
    "block-08-frequency.onnx",
    "block-08-time.onnx",
    "block-09-frequency.onnx",
    "block-09-time.onnx",
    "block-10-frequency.onnx",
    "block-10-time.onnx",
    "block-11-frequency.onnx",
    "block-11-time.onnx",
    "front.onnx",
    "head-0.onnx",
    "head-1.onnx",
)

RECONSTRUCTED_MATERIAL_PROVENANCE = {
    "qa/release-1.6.0/fixtures/falcon-mix.wav": "qa/release-1.6.0/musdb-fixture-provenance.json",
    "web/analysis/models/game/bd2dur.onnx": "web/analysis/models/game/manifest.json",
    "web/analysis/models/game/dur2bd.onnx": "web/analysis/models/game/manifest.json",
    "web/analysis/models/game/encoder.onnx": "web/analysis/models/game/manifest.json",
    "web/analysis/models/game/estimator.onnx": "web/analysis/models/game/manifest.json",
    "web/analysis/models/game/segmenter.onnx": "web/analysis/models/game/manifest.json",
    **{
        "web/analysis/models/deux/" + name: "web/analysis/models/deux/manifest.json"
        for name in DEUX_RECONSTRUCTED_MATERIALS
    },
}
MAX_RUNTIME_MATERIAL_BYTES = 128 * 1024 * 1024
MAX_RUNTIME_MATERIAL_TOTAL_BYTES = 512 * 1024 * 1024

_HEX64 = re.compile(r"[0-9a-f]{64}")
_SHA40 = re.compile(r"[0-9a-f]{40}")
_RELEASE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sha(value: Any, message: str) -> str:
    require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, message)
    return value


def _artifact_sha(value: Any, message: str) -> str:
    require(isinstance(value, str), message)
    return _sha(value.removeprefix("sha256:"), message)


def _integer(value: Any, message: str) -> int:
    require(type(value) is int and value > 0, message)
    return value


def _commit(value: Any, message: str) -> str:
    require(isinstance(value, str) and _SHA40.fullmatch(value) is not None, message)
    return value


def _session(value: Any, message: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, message)
    return value


def _release(value: Any, message: str) -> str:
    require(isinstance(value, str) and _RELEASE.fullmatch(value) is not None, message)
    return value


def _relative(value: Any, message: str) -> PurePosixPath:
    """Validate a repository/archive path before it reaches filesystem or Git."""
    require(isinstance(value, str) and value and "\x00" not in value and "\\" not in value and ":" not in value, message)
    relative = PurePosixPath(value)
    require(
        relative.as_posix() == value
        and not relative.is_absolute()
        and all(part not in {"", ".", ".."} for part in relative.parts),
        message,
    )
    return relative


def _regular(root: Path | str, relative: str, message: str) -> Path:
    root_path = Path(root).resolve()
    path = root_path / _relative(relative, message)
    require(path.is_file() and not path.is_symlink(), message)
    resolved = path.resolve()
    require(resolved.is_relative_to(root_path), message)
    return resolved


def _load(path: Path | str, message: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(message) from error
    require(isinstance(value, dict), message)
    return value


def _atomic_json(path: Path | str, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _fresh_directory(path: Path | str) -> Path:
    result = Path(path)
    require(not result.exists(), "Evidence output directory must be fresh: " + str(result))
    result.mkdir(parents=True, mode=0o700)
    return result


def _inventory(root: Path | str, expected: set[str], label: str) -> dict[str, dict[str, Any]]:
    root_path = Path(root).resolve()
    actual = {
        entry.relative_to(root_path).as_posix()
        for entry in root_path.rglob("*")
        if entry.is_file() or entry.is_symlink()
    }
    require(actual == expected, label + " contains an unexpected or missing file")
    expected_directories = {
        str(PurePosixPath(name).parent)
        for name in expected
        if str(PurePosixPath(name).parent) != "."
    }
    actual_directories = {
        entry.relative_to(root_path).as_posix()
        for entry in root_path.rglob("*")
        if entry.is_dir() and not entry.is_symlink()
    }
    require(actual_directories == expected_directories, label + " contains an unexpected directory")
    result: dict[str, dict[str, Any]] = {}
    for name in expected:
        path = _regular(root_path, name, label + " contains a non-regular file: " + name)
        result[name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return result


def _source_hashes(value: Any, message: str) -> dict[str, str]:
    require(isinstance(value, dict) and value, message)
    result: dict[str, str] = {}
    for relative, checksum in value.items():
        result[_relative(relative, message).as_posix()] = _sha(checksum, message)
    require(len(result) == len(value), message)
    return result


def validate_source_hashes(source_hashes: Any, source_root: Path | str) -> dict[str, str]:
    """Verify a freshly emitted receipt against the exact verifier checkout.

    This runs while the ordinary verify job is still operating on ``GITHUB_SHA``
    and after the workflow has removed any checked-in receipt files.  The later
    publisher validates candidate-tree bytes from immutable Git, regenerated
    materials from their exact source-controlled recipes, and fresh runtime
    outputs from this sealed artifact rather than a release-request checkout.
    """
    hashes = _source_hashes(source_hashes, "Verification receipt source hashes are invalid")
    for relative, checksum in hashes.items():
        path = _regular(source_root, relative, "Verification receipt source path is invalid: " + relative)
        require(sha256_file(path) == checksum, "Verification receipt source hash differs from the verifier checkout: " + relative)
    return hashes


def _runtime_evidence_materials(release: str) -> frozenset[str]:
    """Fresh results which are inputs to the final analysis receipt.

    The files are generated after the checkout and therefore cannot be read
    from the candidate Git tree or from a later release-request checkout.  They
    are copied into the sealed content artifact instead.
    """
    root = "qa/release-" + _release(release, "Evidence release is invalid") + "/"
    names = {
        "analysis-browser-verification.json",
        "background-ui-verification.json",
        "browser-verification.json",
        "restore-preview-verification.json",
        "native-inference-profile-equivalence.json",
        "native-mdx-comparison-verification.json",
        "native-mdx-downstream-native.json",
        "native-mdx-downstream-verification.json",
        "native-mdx-downstream-wasm.json",
        "source-clock-verification.json",
    }
    if release == "2.3.2":
        names.update({"native-game-verification.json", "native-game-demo-output.json",
                      "native-game-falcon-output.json"})
    return frozenset(root + name for name in names)


def _material_path(relative: str) -> str:
    _relative(relative, "Verification material path is invalid")
    return "materials/" + hashlib.sha256(relative.encode("utf-8")).hexdigest()


def _reconstructed_provenance_path(relative: str) -> str:
    try:
        return RECONSTRUCTED_MATERIAL_PROVENANCE[relative]
    except KeyError as error:
        raise ValueError("Evidence reconstructed material is not approved: " + relative) from error


def validate_reconstructed_material_provenance(relative: str, checksum: str, size: int,
                                                provenance_bytes: bytes) -> None:
    """Validate an exact source-controlled recipe for a rebuilt material."""
    checksum = _sha(checksum, "Evidence reconstructed material hash is invalid: " + relative)
    require(type(size) is int and size > 0, "Evidence reconstructed material size is invalid: " + relative)
    try:
        provenance = json.loads(provenance_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Evidence reconstructed material provenance is invalid: " + relative) from error
    if relative == "qa/release-1.6.0/fixtures/falcon-mix.wav":
        tracks = provenance.get("tracks") if isinstance(provenance, dict) else None
        falcon = next((track for track in tracks if isinstance(track, dict) and track.get("id") == "falcon"), None) if isinstance(tracks, list) else None
        require(isinstance(falcon, dict) and falcon.get("pcmSHA256", {}).get("falcon-mix.wav") == checksum,
                "Evidence fixture provenance differs from sealed material")
        return
    name = PurePosixPath(relative).name
    files = provenance.get("files") if isinstance(provenance, dict) else None
    record = files.get(name) if isinstance(files, dict) else None
    require(isinstance(record, dict) and record == {"bytes": size, "sha256": checksum},
            "Evidence model manifest differs from sealed material: " + relative)


def _candidate_tree_bytes(source_root: Path | str, commit: str, relative: str) -> bytes | None:
    """Read a candidate-tree path without trusting the mutable worktree."""
    commit = _commit(commit, "Candidate source commit is invalid")
    relative = _relative(relative, "Verification receipt source path is invalid").as_posix()
    try:
        return subprocess.check_output(
            ("git", "-C", str(Path(source_root).resolve()), "show", commit + ":" + relative),
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_hash_union(receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for name, receipt in receipts.items():
        require(name in RECEIPTS and isinstance(receipt, Mapping), "Verification receipt record is invalid")
        for relative, checksum in _source_hashes(receipt.get("source_hashes"), "Verification receipt source hashes are invalid: " + name).items():
            previous = expected.setdefault(relative, checksum)
            require(previous == checksum, "Verification receipts disagree on source hash: " + relative)
    return expected


def _source_bindings(value: Any, *, expected: Mapping[str, str], release: str,
                     root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Validate complete source provenance, including CI-only material origins."""
    require(isinstance(value, dict) and set(value) == set(expected), "Evidence source binding inventory is invalid")
    result: dict[str, dict[str, Any]] = {}
    runtime = _runtime_evidence_materials(release)
    runtime_total = 0
    for relative, checksum in expected.items():
        record = value.get(relative)
        require(isinstance(record, dict), "Evidence source binding is invalid: " + relative)
        checksum = _sha(checksum, "Evidence source hash is invalid: " + relative)
        origin = record.get("origin")
        if origin == "candidate_tree":
            require(record == {"origin": "candidate_tree", "sha256": checksum}, "Evidence candidate-tree binding differs: " + relative)
            result[relative] = {"origin": "candidate_tree", "sha256": checksum}
            continue
        if origin == "reconstructed_material":
            provenance_path = _reconstructed_provenance_path(relative)
            require(record == {"origin": "reconstructed_material", "bytes": record.get("bytes"), "sha256": checksum,
                               "provenance_path": provenance_path, "provenance_sha256": record.get("provenance_sha256")}
                    and type(record.get("bytes")) is int and record["bytes"] > 0,
                    "Evidence reconstructed-material binding differs: " + relative)
            result[relative] = {"origin": "reconstructed_material", "bytes": record["bytes"], "sha256": checksum,
                                "provenance_path": provenance_path,
                                "provenance_sha256": _sha(record["provenance_sha256"], "Evidence reconstructed provenance digest is invalid: " + relative)}
            continue
        if origin == "sealed_runtime_material":
            require(relative in runtime, "Evidence runtime material is not approved: " + relative)
            expected_path = _material_path(relative)
            require(record == {"origin": "sealed_runtime_material", "path": expected_path,
                               "bytes": record.get("bytes"), "sha256": checksum}
                    and type(record.get("bytes")) is int and 0 < record["bytes"] <= MAX_RUNTIME_MATERIAL_BYTES,
                    "Evidence sealed-runtime-material binding differs: " + relative)
            runtime_total += record["bytes"]
            require(runtime_total <= MAX_RUNTIME_MATERIAL_TOTAL_BYTES, "Evidence runtime material total exceeds the safe limit")
            if root is not None:
                path = _regular(root, expected_path, "Evidence runtime material is missing: " + relative)
                require(path.stat().st_size == record["bytes"] and sha256_file(path) == checksum,
                        "Evidence runtime material differs: " + relative)
            result[relative] = {"origin": "sealed_runtime_material", "path": expected_path,
                                "bytes": record["bytes"], "sha256": checksum}
            continue
        raise ValueError("Evidence source binding origin is invalid: " + relative)
    return result


def _seal_source_bindings(receipts: Mapping[str, Mapping[str, Any]], *, source_root: Path | str,
                          source_commit: str, release: str, output: Path) -> dict[str, dict[str, Any]]:
    """Classify every receipt hash as tree, reconstructed, or sealed runtime data."""
    expected = _source_hash_union(receipts)
    runtime = _runtime_evidence_materials(release)
    bindings: dict[str, dict[str, Any]] = {}
    for relative, checksum in expected.items():
        path = _regular(source_root, relative, "Verification receipt source path is invalid: " + relative)
        require(sha256_file(path) == checksum,
                "Verification receipt source hash differs from the verifier checkout: " + relative)
        candidate_bytes = _candidate_tree_bytes(source_root, source_commit, relative)
        if candidate_bytes is not None and hashlib.sha256(candidate_bytes).hexdigest() == checksum:
            bindings[relative] = {"origin": "candidate_tree", "sha256": checksum}
        elif relative in RECONSTRUCTED_MATERIAL_PROVENANCE:
            provenance_path = _reconstructed_provenance_path(relative)
            provenance_bytes = _candidate_tree_bytes(source_root, source_commit, provenance_path)
            require(provenance_bytes is not None, "Evidence reconstructed material provenance is absent from the candidate tree: " + relative)
            validate_reconstructed_material_provenance(relative, checksum, path.stat().st_size, provenance_bytes)
            bindings[relative] = {
                "origin": "reconstructed_material", "bytes": path.stat().st_size, "sha256": checksum,
                "provenance_path": provenance_path, "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
            }
        elif relative in runtime:
            archive_path = _material_path(relative)
            destination = output / archive_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            require(0 < destination.stat().st_size <= MAX_RUNTIME_MATERIAL_BYTES,
                    "Evidence runtime material exceeds the safe per-file limit: " + relative)
            bindings[relative] = {"origin": "sealed_runtime_material", "path": archive_path,
                                  "bytes": destination.stat().st_size, "sha256": sha256_file(destination)}
            require(bindings[relative]["sha256"] == checksum, "Evidence runtime material copy differs: " + relative)
        else:
            raise ValueError("Verification receipt source is not an exact candidate-tree byte or approved CI material: " + relative)
    return _source_bindings(bindings, expected=expected, release=release, root=output)


def candidate_artifact_name(release: str) -> str:
    return "lightforge-" + _release(release, "Candidate release is invalid") + "-ci-candidate"


def content_artifact_name(release: str, pipeline: Mapping[str, Any]) -> str:
    parsed = _pipeline(pipeline, "Evidence artifact pipeline is invalid")
    return "lightforge-" + _release(release, "Evidence release is invalid") + "-verification-evidence-" + str(parsed["run_id"]) + "-" + str(parsed["run_attempt"])


def wrapper_artifact_name(release: str, pipeline: Mapping[str, Any]) -> str:
    parsed = _pipeline(pipeline, "Evidence wrapper pipeline is invalid")
    return "lightforge-" + _release(release, "Evidence release is invalid") + "-verification-evidence-manifest-" + str(parsed["run_id"]) + "-" + str(parsed["run_attempt"])


def _candidate_files(release: str) -> tuple[str, ...]:
    apk = "LightForge-" + release + ".apk"
    return (apk, "background-tests.apk", "diagnostics-tests.apk", apk + ".json", apk + ".sha256")


def _pipeline(value: Any, message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"workflow", "run_id", "run_attempt", "head_sha", "tree_sha", "evidence_session"}, message)
    require(value.get("workflow") == WORKFLOW, message)
    return {
        "workflow": WORKFLOW,
        "run_id": _integer(value.get("run_id"), message),
        "run_attempt": _integer(value.get("run_attempt"), message),
        "head_sha": _commit(value.get("head_sha"), message),
        "tree_sha": _commit(value.get("tree_sha"), message),
        "evidence_session": _session(value.get("evidence_session"), message),
    }


def _candidate_pipeline(value: Any, message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"run_id", "run_attempt", "evidence_session"}, message)
    return {
        "run_id": _integer(value.get("run_id"), message),
        "run_attempt": _integer(value.get("run_attempt"), message),
        "evidence_session": _session(value.get("evidence_session"), message),
    }


def _candidate_record(value: Any, release: str, message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {
        "artifact_id", "artifact_digest", "identity_sha256", "source", "pipeline", "source_hashes", "files"
    }, message)
    source = value.get("source")
    require(isinstance(source, dict) and set(source) == {"commit", "tree_sha"}, message)
    candidate = {
        "artifact_id": _integer(value.get("artifact_id"), message),
        "artifact_digest": _artifact_sha(value.get("artifact_digest"), message),
        "identity_sha256": _sha(value.get("identity_sha256"), message),
        "source": {
            "commit": _commit(source.get("commit"), message),
            "tree_sha": _commit(source.get("tree_sha"), message),
        },
        "pipeline": _candidate_pipeline(value.get("pipeline"), message),
        "source_hashes": _source_hashes(value.get("source_hashes"), message),
    }
    files = value.get("files")
    expected = set(_candidate_files(release))
    require(isinstance(files, dict) and set(files) == expected, message)
    candidate["files"] = {}
    for name in sorted(expected):
        record = files[name]
        require(isinstance(record, dict) and set(record) == {"bytes", "sha256"}, message)
        candidate["files"][name] = {
            "bytes": _integer(record.get("bytes"), message),
            "sha256": _sha(record.get("sha256"), message),
        }
    return candidate


def candidate_binding(
    candidate_manifest: Path | str,
    *,
    release: str,
    artifact_id: int,
    artifact_digest: str,
    identity_sha256: str,
    pipeline: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert the common candidate manifest into its artifact-bound record."""
    release = _release(release, "Candidate release is invalid")
    expected_pipeline = _pipeline(pipeline, "Expected candidate pipeline is invalid")
    raw = _load(candidate_manifest, "Candidate manifest is invalid")
    require(set(raw) == {"schema_version", "kind", "release", "source", "pipeline", "source_hashes", "files"}, "Candidate manifest fields are invalid")
    require(raw.get("schema_version") == CANDIDATE_SCHEMA_VERSION and raw.get("kind") == CANDIDATE_KIND, "Candidate manifest schema is invalid")
    require(raw.get("release") == release, "Candidate manifest release differs")
    source = raw.get("source")
    require(isinstance(source, dict) and set(source) == {"commit", "tree_sha"}, "Candidate manifest source is invalid")
    candidate_source = {
        "commit": _commit(source.get("commit"), "Candidate manifest source is invalid"),
        "tree_sha": _commit(source.get("tree_sha"), "Candidate manifest source is invalid"),
    }
    require(candidate_source == {"commit": expected_pipeline["head_sha"], "tree_sha": expected_pipeline["tree_sha"]}, "Candidate manifest source differs from verification source")
    candidate_pipeline = _candidate_pipeline(raw.get("pipeline"), "Candidate manifest pipeline is invalid")
    require(candidate_pipeline == {
        "run_id": expected_pipeline["run_id"],
        "run_attempt": expected_pipeline["run_attempt"],
        "evidence_session": expected_pipeline["evidence_session"],
    }, "Candidate manifest pipeline differs from verification")
    source_hashes = _source_hashes(raw.get("source_hashes"), "Candidate manifest source hashes are invalid")
    files = raw.get("files")
    expected_files = set(_candidate_files(release))
    require(isinstance(files, dict) and set(files) == expected_files, "Candidate manifest file inventory is invalid")
    normalized_files: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_files):
        record = files[name]
        require(isinstance(record, dict) and set(record) == {"bytes", "sha256"}, "Candidate manifest file record is invalid")
        normalized_files[name] = {"bytes": _integer(record.get("bytes"), "Candidate manifest file size is invalid"),
                                  "sha256": _sha(record.get("sha256"), "Candidate manifest file digest is invalid")}
    actual_identity = sha256_file(candidate_manifest)
    require(actual_identity == _sha(identity_sha256, "Candidate manifest identity is invalid"), "Candidate manifest identity differs from Actions output")
    return {
        "artifact_id": _integer(artifact_id, "Candidate artifact id is invalid"),
        "artifact_digest": _artifact_sha(artifact_digest, "Candidate artifact digest is invalid"),
        "identity_sha256": actual_identity,
        "source": candidate_source,
        "pipeline": candidate_pipeline,
        "source_hashes": source_hashes,
        "files": normalized_files,
    }


def validate_candidate_record(value: Any, *, release: str, pipeline: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _candidate_record(value, _release(release, "Evidence release is invalid"), "Evidence candidate binding is invalid")
    expected = _pipeline(pipeline, "Evidence pipeline is invalid")
    require(candidate["source"] == {"commit": expected["head_sha"], "tree_sha": expected["tree_sha"]}, "Evidence candidate source differs")
    require(candidate["pipeline"] == {
        "run_id": expected["run_id"],
        "run_attempt": expected["run_attempt"],
        "evidence_session": expected["evidence_session"],
    }, "Evidence candidate pipeline differs")
    return candidate


def _session_evidence_record(value: Any, name: str, expected_session: str,
                             message: str) -> dict[str, str]:
    """Validate and retain the exact session fields observed in one receipt."""
    expected_session = _session(expected_session, message)
    if name in CAMELCASE_SESSION_RECEIPTS:
        expected = {
            "evidenceSessionSchema": EVIDENCE_SESSION_SCHEMA,
            "evidenceSession": expected_session,
        }
        require(value == expected, message)
        return expected
    if name == ANALYSIS_SESSION_RECEIPT:
        expected = {"evidence_session": expected_session}
        require(value == expected, message)
        return expected
    require(value == {}, message)
    return {}


def _receipt_session_evidence(value: Mapping[str, Any], name: str,
                              expected_session: str) -> dict[str, str]:
    if name in CAMELCASE_SESSION_RECEIPTS:
        return _session_evidence_record(
            {
                "evidenceSessionSchema": value.get("evidenceSessionSchema"),
                "evidenceSession": value.get("evidenceSession"),
            },
            name,
            expected_session,
            "Verification receipt evidence session differs: " + name,
        )
    if name == ANALYSIS_SESSION_RECEIPT:
        return _session_evidence_record(
            {"evidence_session": value.get("evidence_session")},
            name,
            expected_session,
            "Verification receipt evidence session differs: " + name,
        )
    require(
        "evidenceSessionSchema" not in value
        and "evidenceSession" not in value
        and "evidence_session" not in value,
        "Verification receipt is unexpectedly session-bound: " + name,
    )
    return {}


def _receipt(value: Any, name: str, release: str, evidence_session: str,
             source_root: Path | str | None = None) -> dict[str, Any]:
    require(isinstance(value, dict), "Verification receipt is invalid: " + name)
    require(value.get("passed") is True and value.get("errors") == [], "Verification receipt did not pass: " + name)
    require(value.get("release") == release, "Verification receipt release differs: " + name)
    source_hashes = _source_hashes(value.get("source_hashes"), "Verification receipt source hashes are invalid: " + name)
    if source_root is not None:
        validate_source_hashes(source_hashes, source_root)
    return {
        "passed": True,
        "release": release,
        "source_hashes": source_hashes,
        "source_hashes_sha256": canonical_sha256(source_hashes),
        # Keep the raw producer spelling in both artifacts. The final analysis
        # receipt intentionally uses snake case while browser producers use
        # camel case, and a wrapper must not erase that binding.
        "session_evidence": _receipt_session_evidence(value, name, evidence_session),
    }


def _receipt_record(value: Any, name: str, release: str, pipeline: Mapping[str, Any],
                    root: Path) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {
        "path", "bytes", "sha256", "passed", "release", "source_hashes",
        "source_hashes_sha256", "session_evidence",
    }, "Evidence receipt record is invalid: " + name)
    require(value.get("path") == RECEIPTS[name], "Evidence receipt path differs: " + name)
    path = _regular(root, value["path"], "Evidence receipt is missing: " + name)
    require(value.get("bytes") == path.stat().st_size and _sha(value.get("sha256"), "Evidence receipt digest is invalid: " + name) == sha256_file(path),
            "Evidence receipt digest differs: " + name)
    actual = _receipt(
        _load(path, "Evidence receipt is invalid: " + name),
        name,
        release,
        _pipeline(pipeline, "Evidence receipt pipeline is invalid")["evidence_session"],
    )
    expected = {
        "path": RECEIPTS[name],
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        **actual,
    }
    require(value == expected, "Evidence receipt metadata differs: " + name)
    return expected

def _content_manifest(value: Any, *, release: str, pipeline: Mapping[str, Any], root: Path,
                      expected_candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {
        "schema_version", "kind", "repository", "release", "pipeline", "candidate", "receipts", "source_bindings"
    }, "Evidence content manifest fields are invalid")
    require(value.get("schema_version") == CONTENT_SCHEMA_VERSION and value.get("kind") == CONTENT_KIND, "Evidence content manifest schema is invalid")
    require(value.get("repository") == REPOSITORY and value.get("release") == release, "Evidence content manifest identity differs")
    parsed_pipeline = _pipeline(value.get("pipeline"), "Evidence content pipeline is invalid")
    require(parsed_pipeline == _pipeline(pipeline, "Expected evidence pipeline is invalid"), "Evidence content pipeline differs")
    candidate = validate_candidate_record(value.get("candidate"), release=release, pipeline=parsed_pipeline)
    if expected_candidate is not None:
        require(candidate == _candidate_record(expected_candidate, release, "Expected evidence candidate is invalid"), "Evidence content candidate differs")
    receipts = value.get("receipts")
    require(isinstance(receipts, dict) and set(receipts) == set(RECEIPTS), "Evidence receipt inventory is invalid")
    normalized = {
        name: _receipt_record(receipts[name], name, release, parsed_pipeline, root)
        for name in RECEIPTS
    }
    bindings = _source_bindings(value.get("source_bindings"), expected=_source_hash_union(normalized), release=release, root=root)
    return {
        "schema_version": CONTENT_SCHEMA_VERSION,
        "kind": CONTENT_KIND,
        "repository": REPOSITORY,
        "release": release,
        "pipeline": parsed_pipeline,
        "candidate": candidate,
        "receipts": normalized,
        "source_bindings": bindings,
    }


def verify_content(artifact_dir: Path | str, *, release: str, pipeline: Mapping[str, Any],
                   expected_candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    manifest_path = _regular(root, CONTENT_MANIFEST, "Evidence content manifest is missing")
    parsed = _content_manifest(_load(manifest_path, "Evidence content manifest is invalid"), release=_release(release, "Evidence release is invalid"), pipeline=pipeline, root=root, expected_candidate=expected_candidate)
    material_paths = {record["path"] for record in parsed["source_bindings"].values()
                      if record["origin"] == "sealed_runtime_material"}
    _inventory(root, {CONTENT_MANIFEST, *RECEIPTS.values(), *material_paths}, "Verification evidence artifact")
    require(parsed == _load(manifest_path, "Evidence content manifest is invalid"), "Evidence content manifest is not canonical")
    return parsed


def write_content(args: argparse.Namespace) -> dict[str, Any]:
    pipeline = {
        "workflow": WORKFLOW,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "head_sha": args.head_sha,
        "tree_sha": args.tree_sha,
        "evidence_session": args.evidence_session,
    }
    pipeline = _pipeline(pipeline, "Evidence pipeline is invalid")
    release = _release(args.release, "Evidence release is invalid")
    candidate = candidate_binding(
        args.candidate_manifest,
        release=release,
        artifact_id=args.candidate_artifact_id,
        artifact_digest=args.candidate_artifact_digest,
        identity_sha256=args.candidate_identity_sha256,
        pipeline=pipeline,
    )
    source = Path(args.receipt_dir).resolve()
    output = _fresh_directory(args.output_dir)
    try:
        records: dict[str, dict[str, Any]] = {}
        for name, relative in RECEIPTS.items():
            origin = _regular(source, name, "Verification receipt is missing: " + name)
            summary = _receipt(
                _load(origin, "Verification receipt is invalid: " + name),
                name,
                release,
                pipeline["evidence_session"],
                args.source_root,
            )
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, destination)
            records[name] = {
                "path": relative,
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                **summary,
            }
        bindings = _seal_source_bindings(
            records,
            source_root=args.source_root,
            source_commit=pipeline["head_sha"],
            release=release,
            output=output,
        )
        manifest = {
            "schema_version": CONTENT_SCHEMA_VERSION,
            "kind": CONTENT_KIND,
            "repository": REPOSITORY,
            "release": release,
            "pipeline": pipeline,
            "candidate": candidate,
            "receipts": records,
            "source_bindings": bindings,
        }
        _atomic_json(output / CONTENT_MANIFEST, manifest)
        verify_content(output, release=release, pipeline=pipeline, expected_candidate=candidate)
        return manifest
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise


def _artifact_reference(value: Any, release: str, pipeline: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"id", "digest", "name", "content_manifest_sha256"}, "Evidence artifact reference is invalid")
    parsed_pipeline = _pipeline(pipeline, "Evidence pipeline is invalid")
    return {
        "id": _integer(value.get("id"), "Evidence artifact id is invalid"),
        "digest": _artifact_sha(value.get("digest"), "Evidence artifact digest is invalid"),
        "name": content_artifact_name(release, parsed_pipeline),
        "content_manifest_sha256": _sha(value.get("content_manifest_sha256"), "Evidence content manifest digest is invalid"),
    }


def _wrapper_manifest(value: Any, *, release: str, pipeline: Mapping[str, Any], root: Path,
                      expected_candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {
        "schema_version", "kind", "repository", "release", "pipeline", "candidate", "evidence_artifact", "receipts", "source_bindings"
    }, "Evidence wrapper manifest fields are invalid")
    require(value.get("schema_version") == WRAPPER_SCHEMA_VERSION and value.get("kind") == WRAPPER_KIND, "Evidence wrapper manifest schema is invalid")
    require(value.get("repository") == REPOSITORY and value.get("release") == release, "Evidence wrapper manifest identity differs")
    parsed_pipeline = _pipeline(value.get("pipeline"), "Evidence wrapper pipeline is invalid")
    require(parsed_pipeline == _pipeline(pipeline, "Expected evidence pipeline is invalid"), "Evidence wrapper pipeline differs")
    candidate = validate_candidate_record(value.get("candidate"), release=release, pipeline=parsed_pipeline)
    if expected_candidate is not None:
        require(candidate == _candidate_record(expected_candidate, release, "Expected evidence candidate is invalid"), "Evidence wrapper candidate differs")
    artifact = _artifact_reference(value.get("evidence_artifact"), release, parsed_pipeline)
    require(value["evidence_artifact"].get("name") == artifact["name"], "Evidence artifact name differs")
    receipts = value.get("receipts")
    require(isinstance(receipts, dict) and set(receipts) == set(RECEIPTS), "Evidence wrapper receipt inventory is invalid")
    # The wrapper repeats these records so that source-hash bindings are sealed
    # before the referenced content archive is even downloaded.
    normalized: dict[str, dict[str, Any]] = {}
    for name, record in receipts.items():
        require(isinstance(record, dict) and set(record) == {
            "path", "bytes", "sha256", "passed", "release", "source_hashes",
            "source_hashes_sha256", "session_evidence",
        }, "Evidence wrapper receipt record is invalid: " + name)
        require(record.get("path") == RECEIPTS[name] and type(record.get("bytes")) is int and record["bytes"] >= 0
                and _sha(record.get("sha256"), "Evidence wrapper receipt digest is invalid: " + name), "Evidence wrapper receipt fields are invalid: " + name)
        summary = {
            "passed": record.get("passed"),
            "release": record.get("release"),
            "source_hashes": _source_hashes(record.get("source_hashes"), "Evidence wrapper source hashes are invalid: " + name),
            "source_hashes_sha256": record.get("source_hashes_sha256"),
            "session_evidence": _session_evidence_record(
                record.get("session_evidence"),
                name,
                parsed_pipeline["evidence_session"],
                "Evidence wrapper receipt session differs: " + name,
            ),
        }
        require(summary["passed"] is True and summary["release"] == release
                and _sha(summary["source_hashes_sha256"], "Evidence wrapper source-hash digest is invalid: " + name)
                == canonical_sha256(summary["source_hashes"]), "Evidence wrapper receipt summary differs: " + name)
        normalized[name] = {
            "path": RECEIPTS[name], "bytes": record["bytes"], "sha256": record["sha256"], **summary,
        }
    bindings = _source_bindings(value.get("source_bindings"), expected=_source_hash_union(normalized), release=release)
    return {
        "schema_version": WRAPPER_SCHEMA_VERSION,
        "kind": WRAPPER_KIND,
        "repository": REPOSITORY,
        "release": release,
        "pipeline": parsed_pipeline,
        "candidate": candidate,
        "evidence_artifact": artifact,
        "receipts": normalized,
        "source_bindings": bindings,
    }


def verify_wrapper(artifact_dir: Path | str, *, release: str, pipeline: Mapping[str, Any],
                   expected_candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    _inventory(root, {WRAPPER_MANIFEST}, "Verification evidence wrapper")
    path = _regular(root, WRAPPER_MANIFEST, "Evidence wrapper manifest is missing")
    parsed = _wrapper_manifest(_load(path, "Evidence wrapper manifest is invalid"), release=_release(release, "Evidence release is invalid"), pipeline=pipeline, root=root, expected_candidate=expected_candidate)
    require(parsed == _load(path, "Evidence wrapper manifest is invalid"), "Evidence wrapper manifest is not canonical")
    return parsed


def write_wrapper(args: argparse.Namespace) -> dict[str, Any]:
    content_path = Path(args.content_dir).resolve() / CONTENT_MANIFEST
    raw_content = _load(content_path, "Evidence content manifest is invalid")
    release = _release(args.release, "Evidence release is invalid")
    pipeline = _pipeline(args.pipeline, "Evidence pipeline is invalid")
    content = verify_content(args.content_dir, release=release, pipeline=pipeline)
    require(content == raw_content, "Evidence content manifest differs")
    output = _fresh_directory(args.output_dir)
    try:
        wrapper = {
            "schema_version": WRAPPER_SCHEMA_VERSION,
            "kind": WRAPPER_KIND,
            "repository": REPOSITORY,
            "release": release,
            "pipeline": pipeline,
            "candidate": content["candidate"],
            "evidence_artifact": {
                "id": _integer(args.evidence_artifact_id, "Evidence artifact id is invalid"),
                "digest": _artifact_sha(args.evidence_artifact_digest, "Evidence artifact digest is invalid"),
                "name": content_artifact_name(release, pipeline),
                "content_manifest_sha256": sha256_file(content_path),
            },
            "receipts": content["receipts"],
            "source_bindings": content["source_bindings"],
        }
        _atomic_json(output / WRAPPER_MANIFEST, wrapper)
        verify_wrapper(output, release=release, pipeline=pipeline, expected_candidate=content["candidate"])
        return wrapper
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    content = commands.add_parser("write-content")
    content.add_argument("--output-dir", type=Path, required=True)
    content.add_argument("--receipt-dir", type=Path, required=True)
    content.add_argument("--source-root", type=Path, required=True)
    content.add_argument("--candidate-manifest", type=Path, required=True)
    content.add_argument("--candidate-artifact-id", type=int, required=True)
    content.add_argument("--candidate-artifact-digest", required=True)
    content.add_argument("--candidate-identity-sha256", required=True)
    content.add_argument("--release", required=True)
    content.add_argument("--run-id", type=int, required=True)
    content.add_argument("--run-attempt", type=int, required=True)
    content.add_argument("--head-sha", required=True)
    content.add_argument("--tree-sha", required=True)
    content.add_argument("--evidence-session", required=True)
    wrapper = commands.add_parser("write-wrapper")
    wrapper.add_argument("--output-dir", type=Path, required=True)
    wrapper.add_argument("--content-dir", type=Path, required=True)
    wrapper.add_argument("--evidence-artifact-id", type=int, required=True)
    wrapper.add_argument("--evidence-artifact-digest", required=True)
    wrapper.add_argument("--release", required=True)
    wrapper.add_argument("--run-id", type=int, required=True)
    wrapper.add_argument("--run-attempt", type=int, required=True)
    wrapper.add_argument("--head-sha", required=True)
    wrapper.add_argument("--tree-sha", required=True)
    wrapper.add_argument("--evidence-session", required=True)
    verify_content_parser = commands.add_parser("verify-content")
    verify_content_parser.add_argument("--artifact-dir", type=Path, required=True)
    verify_content_parser.add_argument("--release", required=True)
    verify_content_parser.add_argument("--pipeline", required=True, type=json.loads)
    verify_wrapper_parser = commands.add_parser("verify-wrapper")
    verify_wrapper_parser.add_argument("--artifact-dir", type=Path, required=True)
    verify_wrapper_parser.add_argument("--release", required=True)
    verify_wrapper_parser.add_argument("--pipeline", required=True, type=json.loads)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "write-content":
        result = write_content(args)
    elif args.command == "write-wrapper":
        args.pipeline = {
            "workflow": WORKFLOW,
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
            "head_sha": args.head_sha,
            "tree_sha": args.tree_sha,
            "evidence_session": args.evidence_session,
        }
        result = write_wrapper(args)
    elif args.command == "verify-content":
        result = verify_content(args.artifact_dir, release=args.release, pipeline=args.pipeline)
    else:
        result = verify_wrapper(args.artifact_dir, release=args.release, pipeline=args.pipeline)
    print(json.dumps({"manifest_sha256": canonical_sha256(result)}, sort_keys=True))


if __name__ == "__main__":
    main()

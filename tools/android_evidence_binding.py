#!/usr/bin/env python3
"""Bind Android test artifacts to the exact checkout that produced them.

The emulator receipt is meaningful only when the downloaded APKs and the source
tree checked by that emulator job agree.  This helper creates the immutable
build-side manifest and fails closed when the consumer-side checkout or any APK
does not match it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
MANIFEST_NAME = "android-evidence-provenance.json"
SOURCE_ROOTS = ("android", "web")
EXPLICIT_SOURCES = (
    ".github/workflows/verify-v2.yml",
    "build.sh",
    "tests/android/BackgroundInstrumentation.java",
    "tests/android/DiagnosticsInstrumentation.java",
    "tools/android_evidence_binding.py",
    "tools/build_android_tests.py",
    "tools/build_diagnostics_tests.py",
    "tools/run_android_background_tests.py",
    "tools/run_android_diagnostics_tests.py",
    "version.json",
)


class EvidenceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release(root: Path) -> str:
    value = json.loads((root / "version.json").read_text(encoding="utf-8")).get("name")
    if not isinstance(value, str) or len(value.split(".")) != 3 or not all(part.isdigit() for part in value.split(".")):
        raise EvidenceError("Invalid release version.")
    return value


def default_source_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for relative_root in SOURCE_ROOTS:
        folder = root / relative_root
        if not folder.is_dir():
            raise EvidenceError("Missing bound source directory: " + relative_root)
        for path in folder.rglob("*"):
            if path.is_file():
                # Bind every packaged asset as well as source. The APK digest
                # protects the artifact; this prevents a newer checkout from
                # using an APK built from an older binary asset.
                paths.add(path)
    for relative in EXPLICIT_SOURCES:
        path = root / relative
        if not path.is_file():
            raise EvidenceError("Missing bound source: " + relative)
        paths.add(path)
    return sorted(paths, key=lambda path: str(path.relative_to(root)))


def source_hashes(root: Path = ROOT, source_paths: list[Path] | None = None) -> dict[str, str]:
    paths = default_source_paths(root) if source_paths is None else sorted(source_paths, key=lambda path: str(path.relative_to(root)))
    if not paths:
        raise EvidenceError("No Android evidence sources were selected.")
    result: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise EvidenceError("Missing bound source: " + str(path))
        relative = str(path.relative_to(root))
        if relative in result:
            raise EvidenceError("Duplicate bound source: " + relative)
        result[relative] = sha256(path)
    return result


def artifact_names(version: str) -> tuple[str, str, str]:
    return ("LightForge-" + version + ".apk", "background-tests.apk", "diagnostics-tests.apk")


def artifact_manifest(candidate_dir: Path, version: str) -> dict[str, dict[str, int | str]]:
    result: dict[str, dict[str, int | str]] = {}
    for name in artifact_names(version):
        path = candidate_dir / name
        if not path.is_file():
            raise EvidenceError("Missing Android candidate artifact: " + name)
        result[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    metadata_path = candidate_dir / ("LightForge-" + version + ".apk.json")
    if not metadata_path.is_file():
        raise EvidenceError("Missing production APK metadata receipt.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    app = result["LightForge-" + version + ".apk"]
    if metadata.get("sha256") != app["sha256"] or metadata.get("bytes") != app["bytes"]:
        raise EvidenceError("Production APK metadata does not match the candidate APK.")
    return result


def write_provenance(root: Path = ROOT, candidate_dir: Path | None = None, output: Path | None = None,
                     source_paths: list[Path] | None = None, commit: str | None = None) -> dict:
    candidate_dir = candidate_dir or root / "dist"
    version = release(root)
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "release": version,
        "commit": commit if commit is not None else os.environ.get("GITHUB_SHA", "local"),
        "sourceHashes": source_hashes(root, source_paths),
        "artifacts": artifact_manifest(candidate_dir, version),
    }
    if not isinstance(evidence["commit"], str) or not evidence["commit"]:
        raise EvidenceError("Missing candidate commit identity.")
    output = output or candidate_dir / MANIFEST_NAME
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return evidence


def verify_provenance(root: Path = ROOT, candidate_dir: Path | None = None,
                      source_paths: list[Path] | None = None, expected_commit: str | None = None) -> dict:
    candidate_dir = candidate_dir or root / "candidate"
    manifest_path = candidate_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise EvidenceError("Missing Android candidate provenance manifest.")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = release(root)
    if value.get("schemaVersion") != SCHEMA_VERSION or value.get("release") != version:
        raise EvidenceError("Android candidate provenance has the wrong schema or release.")
    commit = expected_commit if expected_commit is not None else os.environ.get("GITHUB_SHA")
    if commit and value.get("commit") != commit:
        raise EvidenceError("Android candidate provenance is from a different commit.")
    expected_sources = source_hashes(root, source_paths)
    if value.get("sourceHashes") != expected_sources:
        raise EvidenceError("Android candidate provenance does not match this source checkout.")
    if value.get("artifacts") != artifact_manifest(candidate_dir, version):
        raise EvidenceError("Android candidate artifact digest does not match its provenance.")
    return {
        "schemaVersion": value["schemaVersion"],
        "release": value["release"],
        "commit": value["commit"],
        "provenanceSha256": sha256(manifest_path),
        "artifactNames": sorted(value["artifacts"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("write", "verify"):
        child = commands.add_parser(command)
        child.add_argument("--candidate-dir", type=Path, default=ROOT / ("dist" if command == "write" else "candidate"))
    write = commands.choices["write"]
    write.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "write":
        result = write_provenance(candidate_dir=args.candidate_dir, output=args.output)
    else:
        result = verify_provenance(candidate_dir=args.candidate_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

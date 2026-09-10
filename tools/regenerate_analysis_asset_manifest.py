#!/usr/bin/env python3
"""Deterministically rebuild or verify the checked-in analysis asset manifest.

The manifest is an integrity boundary: it records the exact installed byte
content, including reproduced model graphs.  This tool deliberately does not
download, convert, resample, or otherwise transform any asset.  Run model
reproduction first, then use ``--write`` to make the single canonical JSON
representation; CI uses ``--check`` to reject stale or hand-edited entries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "ASSET_MANIFEST.json"


class ManifestStaleError(ValueError):
    """Carries a machine-readable diff while preserving the hard failure."""

    def __init__(self, report: dict[str, object]):
        differences = report["differences"]
        summary = ("Analysis asset manifest is stale; expected_sha256="
                   + report["generatedManifestSha256"] + "; actual_sha256="
                   + str(report["actualManifestSha256"]) + "; added="
                   + ",".join(differences["added"]) + "; removed="
                   + ",".join(differences["removed"]) + "; changed="
                   + ",".join(differences["changed"]))
        super().__init__(summary + ". Reproduce assets and run "
                         "tools/regenerate_analysis_asset_manifest.py --write")
        self.report = report


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def analysis_root(root: Path) -> Path:
    base = (root / "web" / "analysis").resolve()
    if not base.is_dir():
        raise ValueError("Missing analysis asset directory: " + str(base))
    return base


def included(path: Path, base: Path) -> bool:
    relative = path.relative_to(base)
    return (path.is_file() and path.name != MANIFEST_NAME and not path.is_symlink()
            and not any(part.startswith(".") or part == "__pycache__" for part in relative.parts))


def build_manifest(root: Path) -> dict[str, dict[str, object]]:
    base = analysis_root(root)
    rows: list[tuple[str, Path]] = []
    for candidate in base.rglob("*"):
        resolved = candidate.resolve()
        if not resolved.is_relative_to(base):
            raise ValueError("Analysis asset escapes its root: " + str(candidate))
        if included(candidate, base):
            rows.append((candidate.relative_to(base).as_posix(), candidate))
    return {
        relative: {"bytes": path.stat().st_size, "sha256": digest(path)}
        for relative, path in sorted(rows)
    }


def canonical_bytes(manifest: dict[str, dict[str, object]]) -> bytes:
    return (json.dumps(manifest, indent=2) + "\n").encode("utf-8")


def write_atomic(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def inspect(root: Path) -> tuple[Path, bytes, dict[str, object]]:
    base = analysis_root(root)
    path = base / MANIFEST_NAME
    manifest = build_manifest(root)
    content = canonical_bytes(manifest)
    raw = path.read_bytes() if path.is_file() else b""
    try:
        committed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        committed = {}
    expected_names, committed_names = set(manifest), set(committed)
    changed = sorted(name for name in expected_names & committed_names
                     if manifest[name] != committed[name])
    differences = {
        "added": sorted(expected_names - committed_names),
        "removed": sorted(committed_names - expected_names),
        "changed": changed,
        "serializationMismatch": bool(raw) and raw != content and not (changed or expected_names ^ committed_names),
    }
    report = {
        "schema": "lightforge.analysis-asset-manifest.v1",
        "assetCount": len(manifest),
        "actualAssetCount": len(committed),
        "manifestPath": path.relative_to(root).as_posix(),
        "generatedManifestSha256": hashlib.sha256(content).hexdigest(),
        "actualManifestSha256": hashlib.sha256(raw).hexdigest() if raw else None,
        "upToDate": raw == content,
        "differences": differences,
    }
    return path, content, report


def execute(root: Path, write: bool) -> dict[str, object]:
    path, content, report = inspect(root)
    if write:
        write_atomic(path, content)
        report["actualManifestSha256"] = report["generatedManifestSha256"]
        report["upToDate"] = True
        report["differences"] = {"added": [], "removed": [], "changed": [], "serializationMismatch": False}
    elif not report["upToDate"]:
        raise ManifestStaleError(report)
    report["mode"] = "write" if write else "check"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="atomically replace the canonical manifest")
    mode.add_argument("--check", action="store_true", help="fail if the canonical manifest is stale")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root (defaults to this script's repository)")
    parser.add_argument("--receipt", type=Path,
                        help="write the generated-versus-committed manifest report before returning")
    args = parser.parse_args(argv)
    try:
        report = execute(args.root.resolve(), args.write)
    except ManifestStaleError as error:
        report = error.report
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(args.receipt, (json.dumps(report, indent=2) + "\n").encode("utf-8"))
        print(json.dumps(report, indent=2))
        raise
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(args.receipt, (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

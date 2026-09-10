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
DEUX_ROOT_ASSETS = {
    "separator-deux.js",
    "dsp.js",
    "wav-reader.js",
    "vendor/ONNX-Runtime-LICENSE.txt",
    "vendor/ort-wasm-simd-threaded.mjs",
    "vendor/ort-wasm-simd-threaded.wasm",
    "vendor/ort.wasm.min.js",
}


class ManifestStaleError(ValueError):
    """Carries a machine-readable diff while preserving the hard failure."""

    def __init__(self, report: dict[str, object]):
        differences = report["differences"]
        summary = ("Analysis asset manifest is stale; expected_sha256="
                   + report["generatedManifestSha256"] + "; actual_sha256="
                   + str(report["actualManifestSha256"]) + "; added="
                   + ",".join(differences["added"]) + "; removed="
                   + ",".join(differences["removed"]) + "; changed="
                   + ",".join(differences["changed"]) + "; graphInventory="
                   + str(report["graphInventory"]["matches"]))
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


def assets_under(base: Path) -> dict[str, Path]:
    rows: list[tuple[str, Path]] = []
    for candidate in base.rglob("*"):
        resolved = candidate.resolve()
        if not resolved.is_relative_to(base):
            raise ValueError("Analysis asset escapes its root: " + str(candidate))
        if included(candidate, base):
            rows.append((candidate.relative_to(base).as_posix(), candidate))
    return dict(sorted(rows))


def metadata(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def build_manifest(root: Path) -> dict[str, dict[str, object]]:
    base = analysis_root(root)
    return {relative: metadata(path) for relative, path in assets_under(base).items()}


def deux_asset_names(assets: dict[str, Path], committed: dict[str, object]) -> set[str]:
    """Return the exact diagnostic allow-list, not a global asset shortcut."""
    actual = set(assets)
    declared = {name for name in committed if name.startswith("models/deux/")}
    return DEUX_ROOT_ASSETS | {name for name in actual if name.startswith("models/deux/")} | declared


def deux_graph_inventory(base: Path, assets: dict[str, Path], committed: dict[str, object]) -> dict[str, object]:
    manifest_path = base / "models" / "deux" / "manifest.json"
    declared_graphs: set[str] = set()
    try:
        registry = json.loads(manifest_path.read_text())
        files = registry.get("files") if isinstance(registry, dict) else None
        if isinstance(files, dict):
            declared_graphs = {"models/deux/" + name for name in files if name.endswith(".onnx")}
    except (OSError, json.JSONDecodeError):
        pass
    actual_graphs = {name for name in assets if name.startswith("models/deux/") and name.endswith(".onnx")}
    bound_graphs = {name for name in committed if name.startswith("models/deux/") and name.endswith(".onnx")}
    matches = (len(declared_graphs) == 27 and declared_graphs == actual_graphs == bound_graphs)
    return {
        "requiredGraphCount": 27,
        "manifestGraphCount": len(declared_graphs),
        "actualGraphCount": len(actual_graphs),
        "boundGraphCount": len(bound_graphs),
        "missingFromDisk": sorted(declared_graphs - actual_graphs),
        "unexpectedOnDisk": sorted(actual_graphs - declared_graphs),
        "missingFromOuterManifest": sorted(declared_graphs - bound_graphs),
        "unexpectedInOuterManifest": sorted(bound_graphs - declared_graphs),
        "matches": matches,
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


def inspect(root: Path, scope: str = "all") -> tuple[Path, bytes, dict[str, object]]:
    base = analysis_root(root)
    path = base / MANIFEST_NAME
    raw = path.read_bytes() if path.is_file() else b""
    try:
        committed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        committed = {}
    if not isinstance(committed, dict):
        committed = {}
    if scope == "all":
        manifest = build_manifest(root)
        content = canonical_bytes(manifest)
        expected_names, committed_names = set(manifest), set(committed)
        declared = committed
        graph_inventory = {"requiredGraphCount": None, "matches": True}
        omitted_prefixes: list[str] = []
    elif scope == "deux":
        # The actual-model job reproduces Deux, not GAME.  It must still check
        # every runtime/module/graph byte it can load, but must not pretend it
        # regenerated unrelated GAME assets.  Production CI retains --scope all.
        assets = assets_under(base)
        names = deux_asset_names(assets, committed)
        manifest = {name: metadata(assets[name]) for name in sorted(names) if name in assets}
        content = canonical_bytes(committed)
        expected_names, committed_names = set(manifest), names
        declared = {name: committed.get(name) for name in names if name in committed}
        graph_inventory = deux_graph_inventory(base, assets, committed)
        omitted_prefixes = ["models/game/"]
    else:
        raise ValueError("Unsupported analysis asset scope: " + scope)
    changed = sorted(name for name in expected_names & committed_names
                     if manifest[name] != declared.get(name))
    differences = {
        "added": sorted(expected_names - committed_names),
        "removed": sorted(committed_names - expected_names),
        "changed": changed,
        "serializationMismatch": bool(raw) and raw != content,
    }
    report = {
        "schema": "lightforge.analysis-asset-manifest.v1",
        "scope": scope,
        "allowedAssetPaths": sorted(committed_names),
        "omittedAssetPrefixes": omitted_prefixes,
        "omittedAssetCount": len(set(committed) - committed_names),
        "omittedAssetPaths": sorted(set(committed) - committed_names),
        "assetCount": len(manifest),
        "actualAssetCount": len(committed),
        "manifestPath": path.relative_to(root).as_posix(),
        "generatedManifestSha256": hashlib.sha256(content).hexdigest(),
        "actualManifestSha256": hashlib.sha256(raw).hexdigest() if raw else None,
        "upToDate": raw == content and not any(differences[key] for key in ("added", "removed", "changed"))
                    and not differences["serializationMismatch"] and graph_inventory["matches"],
        "differences": differences,
        "graphInventory": graph_inventory,
    }
    return path, content, report


def execute(root: Path, write: bool, scope: str = "all") -> dict[str, object]:
    if write and scope != "all":
        raise ValueError("--write requires --scope all")
    path, content, report = inspect(root, scope)
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
    parser.add_argument("--scope", choices=("all", "deux"), default="all",
                        help="asset subset to attest; --scope deux is only for the Deux model diagnostic")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root (defaults to this script's repository)")
    parser.add_argument("--receipt", type=Path,
                        help="write the generated-versus-committed manifest report before returning")
    args = parser.parse_args(argv)
    try:
        report = execute(args.root.resolve(), args.write, args.scope)
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

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


def execute(root: Path, write: bool) -> dict[str, object]:
    base = analysis_root(root)
    path = base / MANIFEST_NAME
    manifest = build_manifest(root)
    content = canonical_bytes(manifest)
    if write:
        write_atomic(path, content)
    elif not path.is_file() or path.read_bytes() != content:
        raise ValueError("Analysis asset manifest is stale; reproduce assets and run "
                         "tools/regenerate_analysis_asset_manifest.py --write")
    return {
        "assetCount": len(manifest),
        "manifestPath": path.relative_to(root).as_posix(),
        "manifestSha256": hashlib.sha256(content).hexdigest(),
        "mode": "write" if write else "check",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="atomically replace the canonical manifest")
    mode.add_argument("--check", action="store_true", help="fail if the canonical manifest is stale")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root (defaults to this script's repository)")
    args = parser.parse_args(argv)
    print(json.dumps(execute(args.root.resolve(), args.write), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

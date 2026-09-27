#!/usr/bin/env python3
"""Verify and reconstruct the retained public research evidence archive."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent / "raw"
manifest = json.loads((root / "manifest.json").read_text())
assert len(sys.argv) == 2, "Supply one new output ZIP path"
output = Path(sys.argv[1])
assert not output.exists(), "Refusing an existing output"
parts = []
for index, row in enumerate(manifest["parts"]):
    assert row["file"] == f"evidence.zip.part{index:03d}"
    path = root / row["file"]
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    assert len(data) == row["bytes"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"]
    parts.append(data)
data = b"".join(parts)
assert len(data) == manifest["archiveBytes"]
assert hashlib.sha256(data).hexdigest() == manifest["archiveSha256"]
with output.open("xb") as stream:
    stream.write(data)
print(f"Verified {len(data)} bytes: {manifest['archiveSha256']}")

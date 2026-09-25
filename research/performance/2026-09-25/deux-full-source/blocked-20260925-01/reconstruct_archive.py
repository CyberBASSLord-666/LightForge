#!/usr/bin/env python3
"""Reconstruct the exact blocked public research archive; never qualify its run."""
import hashlib
import json
import re
import sys
from pathlib import Path

MANIFEST_SHA256 = 'ad41797062a19afc172eba9e017311cb1cd11c2265f37e89ecc2ebf9d19bc8a3'
ARCHIVE_BYTES = 132558003
ARCHIVE_SHA256 = "41d0ca6a25ddfa80a325ae71d5ad9930cf6d9a78480d6c63461c6abe3a14f624"
PART_BYTES = 750000
PART_COUNT = 177

def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    require(len(sys.argv) == 2, "Supply one new output ZIP path")
    root = Path(__file__).resolve().parent / "raw"
    manifest_path = root / "manifest.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "Unsafe manifest")
    manifest_bytes = manifest_path.read_bytes()
    require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256, "Manifest checksum mismatch")
    manifest = json.loads(manifest_bytes)
    require(manifest["archiveBytes"] == ARCHIVE_BYTES and manifest["archiveSha256"] == ARCHIVE_SHA256, "Archive identity mismatch")
    require(manifest["status"] == "BLOCKED_OR_REJECTED" and manifest["completeDiagnosticVerified"] is False, "Rejected status must be preserved")
    require(len(manifest["parts"]) == PART_COUNT, "Unexpected part count")
    paths = []
    for index, row in enumerate(manifest["parts"]):
        require(row["file"] == f"evidence.zip.part{index:03d}", "Unexpected part name")
        expected_bytes = min(PART_BYTES, ARCHIVE_BYTES - index * PART_BYTES)
        require(row["bytes"] == expected_bytes and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), "Invalid part binding")
        path = root / row["file"]
        require(path.is_file() and not path.is_symlink(), "Unsafe part")
        require(path.stat().st_size == expected_bytes, "Part size mismatch")
        with path.open("rb") as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"], "Part checksum mismatch")
        paths.append(path)
    output = Path(sys.argv[1])
    digest = hashlib.sha256()
    total = 0
    with output.open("xb") as stream:
        try:
            for path, row in zip(paths, manifest["parts"]):
                data = path.read_bytes()
                require(len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"], "Part changed during reconstruction")
                stream.write(data)
                digest.update(data)
                total += len(data)
            require(total == ARCHIVE_BYTES and digest.hexdigest() == ARCHIVE_SHA256, "Reconstructed archive mismatch")
        except BaseException:
            stream.close()
            output.unlink()
            raise
    print(f"Verified {total} bytes: {digest.hexdigest()} (BLOCKED_OR_REJECTED)")

if __name__ == "__main__":
    main()

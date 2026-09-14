#!/usr/bin/env python3
"""Move only candidate-bound reconstructed data between isolated release jobs.

The receiving job never executes archive contents.  Expected hashes come from
the immutable candidate Git tree, not producer-supplied metadata.  Run this
reviewed helper with ``python3 -E -S`` on the fresh publisher checkout.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

from verification_evidence_manifest import (
    RECONSTRUCTED_MATERIAL_PROVENANCE,
    canonical_json,
    validate_reconstructed_material_provenance,
)


MANIFEST_NAME = "release-materials-manifest.json"
KIND = "lightforge-release-materials"
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
CHUNK_BYTES = 1024 * 1024
MATERIAL_PATHS = frozenset(RECONSTRUCTED_MATERIAL_PROVENANCE)
MATERIAL_DIRS = tuple(sorted({str(PurePosixPath(path).parent) for path in MATERIAL_PATHS}))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field: " + key)
        result[key] = value
    return result


def _json(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=_json_pairs)


def _git(root, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], stderr=subprocess.PIPE,
    )


def _source_root(source_root, source_commit):
    require(isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit),
            "Source commit must be a full lowercase Git SHA")
    raw_root = Path(source_root).absolute()
    require(not raw_root.is_symlink() and raw_root.is_dir(), "Source root must be a real directory")
    root = raw_root.resolve(strict=True)
    require(_git(root, "rev-parse", "HEAD").decode().strip() == source_commit,
            "Source checkout HEAD differs from source commit")
    return root


def _safe_path(root, relative, *, parents=False):
    parts = PurePosixPath(relative).parts
    require(parts and not PurePosixPath(relative).is_absolute()
            and all(part not in ("", ".", "..") for part in parts)
            and "\\" not in relative, "Material path is not canonical")
    current = root
    for part in parts[:-1]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if parents:
                current.mkdir(mode=0o700)
                mode = current.lstat().st_mode
            else:
                continue
        require(stat.S_ISDIR(mode) and not stat.S_ISLNK(mode),
                "Material ancestor must be a real directory: " + relative)
    target = root.joinpath(*parts)
    require(not target.is_symlink(), "Material must not be a symlink: " + relative)
    return target


def _provenance(root, source_commit):
    result = {}
    for relative in sorted(set(RECONSTRUCTED_MATERIAL_PROVENANCE.values())):
        data = _git(root, "show", source_commit + ":" + relative)
        require(0 < len(data) <= MAX_MANIFEST_BYTES, "Source provenance is oversized or empty")
        # Parse strictly even though the shared validator also parses the bytes.
        _json(data)
        result[relative] = data
    return result


def _validate_record(relative, record, provenance):
    require(isinstance(record, dict) and set(record) == {"bytes", "sha256"},
            "Material record fields are invalid: " + relative)
    require(type(record["bytes"]) is int and 0 < record["bytes"] <= MAX_TOTAL_BYTES,
            "Material size is invalid: " + relative)
    require(isinstance(record["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]),
            "Material digest is invalid: " + relative)
    validate_reconstructed_material_provenance(
        relative, record["sha256"], record["bytes"],
        provenance[RECONSTRUCTED_MATERIAL_PROVENANCE[relative]],
    )


def _hash_stream(stream, expected_size=None, destination=None, max_bytes=None):
    checksum = hashlib.sha256()
    size = 0
    limit = (MAX_TOTAL_BYTES if max_bytes is None else max_bytes) if expected_size is None else expected_size
    while True:
        chunk = stream.read(min(CHUNK_BYTES, limit - size + 1))
        if not chunk:
            break
        size += len(chunk)
        require(size <= limit, "Material exceeds its permitted size")
        checksum.update(chunk)
        if destination is not None:
            destination.write(chunk)
    require(size > 0 and (expected_size is None or size == expected_size),
            "Material size differs from manifest")
    return {"bytes": size, "sha256": checksum.hexdigest()}


def _open_material(root, relative):
    path = _safe_path(root, relative)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode), "Material must be a regular file: " + relative)
        require(0 < info.st_size <= MAX_TOTAL_BYTES, "Material file size is invalid: " + relative)
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _generated_inventory(root):
    result = set()
    for options in (("--others", "--exclude-standard"),
                    ("--others", "--ignored", "--exclude-standard")):
        paths = _git(root, "ls-files", "-z", *options, "--", *MATERIAL_DIRS)
        result.update(path.decode("utf-8") for path in paths.split(b"\0") if path)
    return result


def _record_inventory(root, provenance, *, reject_extras=True):
    if reject_extras:
        require(_generated_inventory(root) == MATERIAL_PATHS,
                "Generated material inventory differs from exact allowlist")
    records = {}
    total = 0
    for relative in sorted(MATERIAL_PATHS):
        with _open_material(root, relative) as stream:
            record = _hash_stream(stream, max_bytes=MAX_TOTAL_BYTES - total)
        _validate_record(relative, record, provenance)
        total += record["bytes"]
        require(total <= MAX_TOTAL_BYTES, "Material total size exceeds limit")
        records[relative] = record
    return records


def _manifest(source_commit, records):
    return {"schema_version": 1, "kind": KIND, "source_commit": source_commit, "files": records}


def _zip_info(name):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def write_handoff(source_root, source_commit, output):
    root = _source_root(source_root, source_commit)
    provenance = _provenance(root, source_commit)
    # The reconstruction runner may contain model caches and fixture stems.
    # They are never selected for transfer; only the fresh consumer is required
    # to have an otherwise empty generated-material inventory.
    records = _record_inventory(root, provenance, reject_extras=False)
    document = _manifest(source_commit, records)
    payload = (canonical_json(document) + "\n").encode("utf-8")
    require(len(payload) <= MAX_MANIFEST_BYTES, "Handoff manifest exceeds limit")
    # Exclusive creation refuses an existing file or symlink, including failed
    # output from a previous attempt.  The workflow uploads only on success.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(_zip_info(MANIFEST_NAME), payload)
            for relative, expected in records.items():
                with _open_material(root, relative) as source:
                    with archive.open(_zip_info(relative), "w", force_zip64=True) as member:
                        actual = _hash_stream(source, expected["bytes"], member)
                require(actual == expected, "Material changed while writing handoff: " + relative)
    return document


def _read_manifest(archive, source_commit, provenance):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    require(len(names) == len(set(names)) and set(names) == MATERIAL_PATHS | {MANIFEST_NAME},
            "Handoff archive inventory differs from exact allowlist")
    total = 0
    for entry in entries:
        require(entry.orig_filename == entry.filename and "\0" not in entry.filename,
                "Archive path is not canonical")
        require(not entry.is_dir() and stat.S_ISREG(entry.external_attr >> 16),
                "Archive members must be regular files")
        require(entry.flag_bits & ~0x808 == 0, "Archive encryption or unsupported flags are forbidden")
        require(entry.compress_type == zipfile.ZIP_STORED and entry.compress_size == entry.file_size,
                "Archive compression is forbidden")
        limit = MAX_MANIFEST_BYTES if entry.filename == MANIFEST_NAME else MAX_TOTAL_BYTES
        require(0 < entry.file_size <= limit, "Archive member size exceeds limit")
        total += entry.file_size
    require(total <= MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES, "Archive total size exceeds limit")
    payload = archive.read(MANIFEST_NAME)
    document = _json(payload)
    require(isinstance(document, dict)
            and set(document) == {"schema_version", "kind", "source_commit", "files"},
            "Handoff manifest fields are invalid")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1
            and document["kind"] == KIND, "Handoff manifest schema is invalid")
    require(document["source_commit"] == source_commit, "Handoff source commit differs")
    records = document["files"]
    require(isinstance(records, dict) and set(records) == MATERIAL_PATHS,
            "Handoff manifest inventory differs from exact allowlist")
    require(payload == (canonical_json(document) + "\n").encode("utf-8"),
            "Handoff manifest is not canonical")
    for relative, record in records.items():
        _validate_record(relative, record, provenance)
        require(archive.getinfo(relative).file_size == record["bytes"],
                "Archive size differs from handoff manifest: " + relative)
    require(sum(record["bytes"] for record in records.values()) <= MAX_TOTAL_BYTES,
            "Material total size exceeds limit")
    return document


def install_handoff(source_root, source_commit, archive_path):
    root = _source_root(source_root, source_commit)
    provenance = _provenance(root, source_commit)
    require(not _generated_inventory(root), "Install requires an empty generated material inventory")
    for relative in MATERIAL_PATHS:
        target = _safe_path(root, relative)
        require(not target.exists(), "Install will not overwrite an existing material: " + relative)
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode), "Handoff archive must be a regular file")
        require(0 < info.st_size <= MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + 1024 * 1024,
                "Handoff archive file size exceeds limit")
        with zipfile.ZipFile(source, "r") as archive:
            document = _read_manifest(archive, source_commit, provenance)
            # Validate every byte before modifying the fresh candidate checkout.
            for relative, expected in document["files"].items():
                with archive.open(relative) as member:
                    require(_hash_stream(member, expected["bytes"]) == expected,
                            "Archive material digest differs: " + relative)
            for relative, expected in document["files"].items():
                target = _safe_path(root, relative, parents=True)
                output_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(output_fd, "wb") as output:
                    with archive.open(relative) as member:
                        require(_hash_stream(member, expected["bytes"], output) == expected,
                                "Archive material changed during install: " + relative)
    require(verify_installed(root, source_commit) == document, "Installed material inventory differs")
    return document


def verify_installed(source_root, source_commit):
    root = _source_root(source_root, source_commit)
    return _manifest(source_commit, _record_inventory(root, _provenance(root, source_commit)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "install", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--source-root", type=Path, required=True)
        command.add_argument("--source-commit", required=True)
        if name == "write":
            command.add_argument("--output", type=Path, required=True)
        elif name == "install":
            command.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "write":
            result = write_handoff(args.source_root, args.source_commit, args.output)
        elif args.command == "install":
            result = install_handoff(args.source_root, args.source_commit, args.input)
        else:
            result = verify_installed(args.source_root, args.source_commit)
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, RuntimeError) as error:
        parser.exit(1, "Release material handoff failed: " + str(error) + "\n")
    print(canonical_json({"source_commit": result["source_commit"], "materials": len(result["files"])}))


if __name__ == "__main__":
    main()

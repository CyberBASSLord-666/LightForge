#!/usr/bin/env python3
"""Reject post-candidate source drift before privileged release preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any


_COMMIT = re.compile(r"[0-9a-f]{40}")
_RELEASE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def _git_bytes(checkout: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ("git", "-C", str(checkout), *args),
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("Release source preflight Git command failed: " + " ".join(args)) from error


def _git_run(checkout: Path, *args: str) -> None:
    _git_bytes(checkout, *args)


def _show(checkout: Path, revision: str, relative: str) -> bytes:
    return _git_bytes(checkout, "show", revision + ":" + relative)


def _json(value: bytes, message: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(message) from error
    require(isinstance(parsed, dict), message)
    return parsed


def _version(value: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = value.get("name")
    code = value.get("code")
    require(isinstance(name, str) and _RELEASE.fullmatch(name) is not None,
            "Release source preflight version is invalid")
    require(type(code) is int and code > 0,
            "Release source preflight version code is invalid")
    return name, value


def _request_path(release: str) -> str:
    return "releases/v" + release + "/request.json"


def _allowed_release_artifacts(release: str) -> frozenset[str]:
    root = "releases/v" + release + "/"
    return frozenset({
        "RELEASE_NOTES.md",
        "release-verification.json",
        root + "prepare.json",
        root + "request.json",
        root + "signed-apk.delta.json",
        root + "publication.json",
    })


def _changed_paths(checkout: Path, source_commit: str, head: str) -> frozenset[str]:
    data = _git_bytes(checkout, "diff", "--no-renames", "--name-only", "-z", source_commit, head)
    result: set[str] = set()
    for raw in data.split(b"\0"):
        if not raw:
            continue
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Release source preflight diff path is invalid") from error
        path = PurePosixPath(relative)
        require(not path.is_absolute() and ".." not in path.parts and str(path) not in {"", "."},
                "Release source preflight diff path is invalid")
        result.add(relative)
    return frozenset(result)


def validate_release_source(checkout: Path | str, source_commit: str, *, head: str = "HEAD") -> dict[str, Any]:
    """Require that post-candidate commits contain only inert release artifacts."""
    root = Path(checkout).resolve()
    require(root.is_dir(), "Release source preflight checkout is invalid")
    require(isinstance(source_commit, str) and _COMMIT.fullmatch(source_commit) is not None,
            "Release source preflight source commit is invalid")
    version = _json(_show(root, head, "version.json"), "Release source preflight version JSON is invalid")
    release, exact_version = _version(version)
    request_path = _request_path(release)
    request = _json(_show(root, head, request_path), "Release source preflight request JSON is invalid")
    require(request.get("version") == exact_version,
            "Release source preflight request version differs from checkout")
    require(request.get("source_commit") == source_commit,
            "Release source preflight request source commit differs")
    require(type(request.get("run_id")) is int and request["run_id"] > 0,
            "Release source preflight request run is invalid")
    _git_run(root, "cat-file", "-e", source_commit + "^{commit}")
    _git_run(root, "merge-base", "--is-ancestor", source_commit, head)
    changed = _changed_paths(root, source_commit, head)
    unexpected = sorted(changed - _allowed_release_artifacts(release))
    require(not unexpected,
            "Post-candidate release request changes an unapproved source path: " + ", ".join(unexpected))
    return {
        "release": release,
        "request_path": request_path,
        "source_commit": source_commit,
        "changed_paths": sorted(changed),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    print(json.dumps(
        validate_release_source(args.checkout, args.source_commit, head=args.head),
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()

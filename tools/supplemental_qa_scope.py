#!/usr/bin/env python3
"""Skip supplemental browser work only for a complete, inert PR diff.

The workflow and its status check always run. This is not a production or
release-evidence decision. Missing, oversized or unrecognized inputs request
the full browser suite; manual dispatch and push events always do so too.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Mapping


MAX_BYTES = 2 * 1024 * 1024
MAX_PATHS = 10000
COMMIT = re.compile(r"[0-9a-f]{40}")
RELEASE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ROOT_DOCS = frozenset({
    "ARCHITECTURE.md", "ASSETS.md", "BUILD.md", "CHANGELOG.md", "README.md",
    "RELEASE_NOTES.md", "REPOSITORY.md", "VALIDATION.md", "VERSIONING.md",
})


def git(root: Path, *args: str) -> bytes:
    """Read complete Git output, with a time and result-size bound."""
    # Do not accumulate an unexpectedly large repository diff in memory.
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            ["git", "-C", str(root), *args], stdout=output,
            stderr=subprocess.DEVNULL, timeout=30, check=True,
        )
        output.seek(0)
        data = output.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Git result exceeds scope bound")
    return data


def full(reason: str) -> dict:
    return {"run_browser": True, "reason": reason}


def inert(path: str, release: str) -> bool:
    if path in ROOT_DOCS or re.fullmatch(r"docs/[A-Za-z0-9_-]+\.md", path):
        return True
    return path in {
        "release-verification.json",
        *(f"releases/v{release}/{name}.json" for name in
          ("prepare", "request", "signed-apk.delta", "publication")),
    }


def paths(data: bytes) -> set[str]:
    """A partial, malformed or unexpected inventory can never suppress QA."""
    if not data or len(data) > MAX_BYTES or not data.endswith(b"\0"):
        raise ValueError("Incomplete changed-path inventory")
    raw = data[:-1].split(b"\0")
    if not 0 < len(raw) <= MAX_PATHS or any(not name for name in raw):
        raise ValueError("Invalid changed-path count")
    names = {name.decode("utf-8", errors="strict") for name in raw}
    if any(name.startswith("/") or "\\" in name or
           any(part in ("", ".", "..") for part in name.split("/"))
           for name in names):
        raise ValueError("Unexpected changed-path syntax")
    return names


def current_release(root: Path, revision: str) -> str:
    value = json.loads(git(root, "show", revision + ":version.json"))
    name = value.get("name") if isinstance(value, dict) else None
    if not isinstance(name, str) or RELEASE.fullmatch(name) is None:
        raise ValueError("Unknown release version")
    return name


def classify(root: Path, event: Mapping, environment: Mapping[str, str]) -> dict:
    if environment.get("GITHUB_EVENT_NAME") != "pull_request":
        return full("Push and manual events always run supplemental browser QA")
    try:
        pull = event["pull_request"]
        base = pull["base"]["sha"]
        head = pull["head"]["sha"]
        checkout = environment.get("GITHUB_SHA", "")
        if any(not isinstance(value, str) or COMMIT.fullmatch(value) is None
               for value in (base, head, checkout)):
            raise ValueError("Invalid immutable PR revisions")
        if git(root, "rev-parse", "HEAD").decode().strip() != checkout:
            raise ValueError("Checkout does not match the event revision")
        # A shallow PR checkout may omit one or both immutable parents. Fetch
        # only those exact objects; do not request arbitrary branches or history.
        missing = []
        for revision in (base, head):
            try:
                git(root, "cat-file", "-e", revision + "^{commit}")
            except subprocess.CalledProcessError:
                missing.append(revision)
        if missing:
            git(root, "fetch", "--no-tags", "--depth=1", "origin", *missing)
        release = current_release(root, base)
        if any(current_release(root, revision) != release for revision in (head, checkout)):
            return full("Version changes require supplemental browser QA")
        # Compare both immutable PR trees and the actual tested merge tree.
        # Two-tree comparisons can conservatively include unrelated base work;
        # that can only request more QA. Never trust a truncated API file list,
        # a newest-commit-only diff, rename detection, or user-provided text.
        changed = set()
        for revision in (head, checkout):
            changed.update(paths(git(root, "diff", "--no-ext-diff", "--no-textconv",
                                     "--no-renames", "--name-only", "-z", base, revision, "--")))
        if any(not inert(name, release) for name in changed):
            return full("Runtime, test, workflow or unknown paths require supplemental browser QA")
        return {"run_browser": False, "reason": "Complete PR diff contains only maintained docs or inert current-release metadata",
                "changed_path_count": len(changed), "base_sha": base, "head_sha": head,
                "checkout_sha": checkout}
    except (KeyError, TypeError, ValueError, UnicodeError, OSError, subprocess.SubprocessError):
        return full("PR scope could not be established completely; running supplemental browser QA")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
        with event_path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Event exceeds scope bound")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("Unknown event shape")
        result = classify(root, event, os.environ)
    except (ValueError, OSError):
        result = full("Event unavailable or malformed; running supplemental browser QA")
    print(json.dumps(result, sort_keys=True))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("run_browser=" + str(result["run_browser"]).lower() + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("Supplemental browser scope: " + result["reason"] + ".\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

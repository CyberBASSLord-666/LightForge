#!/usr/bin/env python3
"""Tests for the pre-execution release source integrity gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_source_preflight", ROOT / "tools/release_source_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

COMMIT = "a" * 40
VERSION = {"name": "2.2.5", "code": 20205}
REQUEST_PATH = "releases/v2.2.5/request.json"


class ReleaseSourcePreflightTest(unittest.TestCase):
    def validate(self, changed=(), request=None, version=None):
        exact_version = VERSION if version is None else version
        exact_request = {
            "version": exact_version,
            "source_commit": COMMIT,
            "run_id": 741,
        } if request is None else request

        def show(_checkout, _revision, relative):
            if relative == "version.json":
                return json.dumps(exact_version).encode()
            if relative == REQUEST_PATH:
                return json.dumps(exact_request).encode()
            self.fail("unexpected Git source path " + relative)

        with patch.object(preflight, "_show", side_effect=show),                 patch.object(preflight, "_git_run") as git_run,                 patch.object(preflight, "_changed_paths", return_value=frozenset(changed)):
            result = preflight.validate_release_source(ROOT, COMMIT)
        self.assertEqual(
            git_run.call_args_list[0].args[1:],
            ("cat-file", "-e", COMMIT + "^{commit}"),
        )
        self.assertEqual(
            git_run.call_args_list[1].args[1:],
            ("merge-base", "--is-ancestor", COMMIT, "HEAD"),
        )
        return result

    def test_allows_only_inert_current_release_artifacts(self):
        changed = {
            REQUEST_PATH,
            "releases/v2.2.5/prepare.json",
            "releases/v2.2.5/signed-apk.delta.json",
            "releases/v2.2.5/publication.json",
            "release-verification.json",
            "RELEASE_NOTES.md",
        }
        result = self.validate(changed)
        self.assertEqual(result["release"], "2.2.5")
        self.assertEqual(result["request_path"], REQUEST_PATH)
        self.assertEqual(result["changed_paths"], sorted(changed))

    def test_rejects_every_post_candidate_executable_or_source_change(self):
        for changed in (
            "tools/prepare_deux.py",
            "tools/model-requirements.txt",
            "research/upstream/deux/models.py",
            "qa/release-1.6.0/prepare-musdb-fixtures.py",
            "web/analysis/models/deux/manifest.json",
            "android/app/src/main/AndroidManifest.xml",
            ".github/workflows/publish-release.yml",
        ):
            with self.subTest(changed=changed),                     self.assertRaisesRegex(ValueError, "unapproved source path"):
                self.validate({REQUEST_PATH, changed})

    def test_rejects_malformed_or_unbound_request(self):
        invalid = [
            {"version": VERSION, "source_commit": "b" * 40, "run_id": 741},
            {"version": {"name": "2.2.4", "code": 20204}, "source_commit": COMMIT, "run_id": 741},
            {"version": VERSION, "source_commit": COMMIT, "run_id": 0},
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.validate({REQUEST_PATH}, request=request)

    def test_rejects_invalid_release_name_before_constructing_request_path(self):
        with self.assertRaisesRegex(ValueError, "version is invalid"):
            self.validate(version={"name": "../2.2.5", "code": 20205})


if __name__ == "__main__":
    unittest.main()

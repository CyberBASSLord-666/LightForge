"""A successful no-work browser check requires a complete inert PR diff."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import supplemental_qa_scope as scope


class SupplementalQaScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Scope test")
        self.git("config", "user.email", "scope@example.invalid")
        for name, data in {"version.json": '{"name":"2.4.2","code":20402}\n',
                           "README.md": "Read me\n", "docs/BUILD.md": "Build\n",
                           "web/app.js": "runtime\n",
                           "web/analysis/README.md": "Hashed model notice\n"}.items():
            self.write(name, data)
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "Scope fixture")
        return self.git("rev-parse", "HEAD")

    def result(self, head=None, event_name="pull_request", base=None):
        checkout = self.git("rev-parse", "HEAD")
        event = {"pull_request": {"base": {"sha": base or self.base}, "head": {"sha": head or checkout}}}
        return scope.classify(self.root, event, {"GITHUB_EVENT_NAME": event_name, "GITHUB_SHA": checkout})

    def test_complete_docs_and_current_release_metadata_skip_browser_only(self):
        for name in ("README.md", "docs/BUILD.md", "RELEASE_NOTES.md", "release-verification.json",
                     "releases/v2.4.2/request.json", "releases/v2.4.2/prepare.json",
                     "releases/v2.4.2/signed-apk.delta.json", "releases/v2.4.2/publication.json"):
            self.write(name, "changed\n")
        self.commit()
        result = self.result()
        self.assertFalse(result["run_browser"])
        self.assertEqual(result["changed_path_count"], 8)

    def test_runtime_or_hashed_model_notice_and_mixed_changes_run_full(self):
        for name in ("web/app.js", "web/analysis/README.md"):
            with self.subTest(name=name):
                self.git("reset", "--hard", self.base)
                self.write(name, "changed\n")
                self.write("README.md", "updated\n")
                self.commit()
                self.assertTrue(self.result()["run_browser"])

    def test_deleted_docs_skip_but_deleted_runtime_requires_full(self):
        (self.root / "docs/BUILD.md").unlink()
        self.commit()
        self.assertFalse(self.result()["run_browser"])
        (self.root / "web/app.js").unlink()
        self.commit()
        self.assertTrue(self.result()["run_browser"])

    def test_rename_is_evaluated_as_both_paths_without_rename_detection(self):
        (self.root / "README.md").rename(self.root / "entry.js")
        self.commit()
        self.assertTrue(self.result()["run_browser"])

    def test_only_last_commit_cannot_hide_earlier_runtime_change(self):
        self.write("web/app.js", "changed\n")
        self.commit()
        self.write("README.md", "later documentation\n")
        self.commit()
        self.assertTrue(self.result()["run_browser"])

    def test_merge_checkout_is_checked_as_well_as_the_pr_head(self):
        self.write("README.md", "inert head\n")
        head = self.commit()
        self.write("web/app.js", "merge-only runtime change\n")
        self.commit()
        self.assertTrue(self.result(head=head)["run_browser"])

    def test_unknown_workflow_tool_old_release_and_version_paths_run_full(self):
        for name in (".github/workflows/new.yml", "tools/new.py", "tests/new.py",
                     "docs/new.json", "unknown.md", "releases/v2.4.1/request.json", "version.json"):
            with self.subTest(name=name):
                self.git("reset", "--hard", self.base)
                self.write(name, '{"name":"2.4.3","code":20403}\n' if name == "version.json" else "change\n")
                self.commit()
                self.assertTrue(self.result()["run_browser"])

    def test_manual_and_push_always_run_full(self):
        self.write("README.md", "changed\n")
        self.commit()
        for event_name in ("workflow_dispatch", "push", "pull_request_target", ""):
            self.assertTrue(self.result(event_name=event_name)["run_browser"])

    def test_missing_invalid_or_mismatched_revisions_cannot_skip(self):
        self.write("README.md", "changed\n")
        self.commit()
        self.assertTrue(self.result(base="f" * 40)["run_browser"])
        self.assertTrue(self.result(base="main; arbitrary text")["run_browser"])
        self.assertTrue(scope.classify(self.root, {}, {"GITHUB_EVENT_NAME": "pull_request"})["run_browser"])
        with mock.patch.object(scope, "git", return_value=b"unexpected-checkout\n"):
            self.assertTrue(self.result()["run_browser"])

    def test_unknown_empty_malformed_or_oversized_diff_falls_back_to_full(self):
        self.assertTrue(self.result()["run_browser"])
        for raw in (b"README.md", b"README.md\0\0", b"\xff\0", b"../README.md\0",
                    b"/README.md\0", b"docs//README.md\0", b"README.md\0" * (scope.MAX_PATHS + 1),
                    b"x" * (scope.MAX_BYTES + 1)):
            with self.subTest(raw_prefix=raw[:30]), self.assertRaises((ValueError, UnicodeError)):
                scope.paths(raw)
        self.write("README.md", "changed\n")
        self.commit()
        original = scope.git
        for failure in (OSError("unavailable"), subprocess.TimeoutExpired("git", 30), ValueError("oversized")):
            def broken(root, *args):
                if args[0] == "diff":
                    raise failure
                return original(root, *args)
            with mock.patch.object(scope, "git", side_effect=broken):
                self.assertTrue(self.result()["run_browser"])

    def test_cli_missing_or_malformed_event_emits_full_workflow_output(self):
        event = self.root / "event.json"
        output = self.root / "output.txt"
        summary = self.root / "summary.txt"
        for raw in (None, b"not json", b"[]", b" " * (scope.MAX_BYTES + 1)):
            if raw is not None:
                event.write_bytes(raw)
            elif event.exists():
                event.unlink()
            with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event),
                                             "GITHUB_OUTPUT": str(output),
                                             "GITHUB_STEP_SUMMARY": str(summary)}, clear=True), \
                    mock.patch("builtins.print"):
                self.assertEqual(scope.main(), 0)
        self.assertEqual(output.read_text(), "run_browser=true\n" * 4)
        self.assertEqual(summary.read_text().count("running supplemental browser QA"), 4)

    def test_diff_is_complete_nul_delimited_and_uses_both_immutable_trees(self):
        self.write("README.md", "inert PR\n")
        head = self.commit()
        self.write("docs/BUILD.md", "merge docs\n")
        checkout = self.commit()
        with mock.patch.object(scope, "git", wraps=scope.git) as process:
            self.assertFalse(self.result(head=head)["run_browser"])
        commands = [call.args[1:] for call in process.call_args_list if call.args[1] == "diff"]
        self.assertEqual(len(commands), 2)
        for command, revision in zip(commands, (head, checkout)):
            self.assertEqual(command, ("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                                       "--name-only", "-z", self.base, revision, "--"))

    def test_shallow_checkout_fetches_only_the_missing_immutable_parent(self):
        self.write("README.md", "inert PR\n")
        head = self.commit()
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            subprocess.run(["git", "clone", "-q", "--depth=1", self.root.as_uri(), str(checkout)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            missing = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", self.base + "^{commit}"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertNotEqual(missing.returncode, 0)
            event = {"pull_request": {"base": {"sha": self.base}, "head": {"sha": head}}}
            with mock.patch.object(scope, "git", wraps=scope.git) as process:
                result = scope.classify(checkout, event, {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_SHA": head})
            self.assertFalse(result["run_browser"])
            fetches = [call.args[1:] for call in process.call_args_list if call.args[1] == "fetch"]
            self.assertEqual(fetches, [("fetch", "--no-tags", "--depth=1", "origin", self.base)])
            self.assertEqual(scope.git(checkout, "rev-parse", "HEAD").decode().strip(), head)


if __name__ == "__main__":
    unittest.main()

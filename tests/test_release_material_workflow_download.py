"""Exercise the privileged workflow's literal, isolated data downloader."""
import ast
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-release.yml"
MEMBER = "lightforge-release-materials.zip"


def downloader_code(*, limit=None):
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Download and verify exact material artifact before extraction\n", 1
    )[1].split("      - name:", 1)[0]
    match = re.search(r"          python3 -I -S - <<'PY'\n(.*?)\n          PY", step, re.S)
    if match is None:
        raise AssertionError("Workflow downloader is not an isolated Python heredoc")
    tree = ast.parse(textwrap.dedent(match.group(1)))
    if limit is not None:
        assignments = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "limit" for target in node.targets)
        ]
        if len(assignments) != 1:
            raise AssertionError("Expected one explicit download size bound")
        assignments[0].value = ast.Constant(limit)
        ast.fix_missing_locations(tree)
    return compile(tree, str(WORKFLOW), "exec")


def archive_bytes(members=((MEMBER, b"source-pinned-inner-archive"),), *, mode=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, value)
    return buffer.getvalue()


class FakeProcess:
    def __init__(self, payload, returncode=0):
        self.stdout = io.BytesIO(payload)
        self.returncode = returncode
        self.killed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stdout.close()

    def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


class ReleaseMaterialWorkflowDownloadTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "lightforge-release-materials" / MEMBER

    def execute(self, payload, *, checksum=None, artifact_id="42", returncode=0, limit=None):
        environment = {
            "RUNNER_TEMP": str(self.root),
            "GITHUB_REPOSITORY": "CyberBASSLord-666/LightForge",
            "MATERIAL_ARTIFACT_ID": artifact_id,
            "MATERIAL_ARTIFACT_DIGEST": checksum or hashlib.sha256(payload).hexdigest(),
        }
        process = FakeProcess(payload, returncode)
        with mock.patch.dict(os.environ, environment), mock.patch(
            "subprocess.Popen", return_value=process
        ) as popen:
            exec(downloader_code(limit=limit), {})
        popen.assert_called_once_with(
            ["gh", "api", "repos/CyberBASSLord-666/LightForge/actions/artifacts/42/zip"],
            stdout=-1,
        )
        return process

    def test_extracts_exact_regular_member_after_matching_download_digest(self):
        self.execute(archive_bytes())
        self.assertEqual(self.target.read_bytes(), b"source-pinned-inner-archive")
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_accepts_api_prefixed_digest(self):
        payload = archive_bytes()
        self.execute(payload, checksum="sha256:" + hashlib.sha256(payload).hexdigest())
        self.assertTrue(self.target.is_file())

    def test_wrong_digest_fails_before_archive_parsing_or_extraction(self):
        with mock.patch("zipfile.ZipFile", side_effect=AssertionError("Parsed before digest gate")):
            with self.assertRaisesRegex(SystemExit, "digest differs"):
                self.execute(b"not even a ZIP", checksum="0" * 64)
        self.assertFalse(self.target.exists())

    def test_extra_member_fails_before_extraction(self):
        with self.assertRaisesRegex(SystemExit, "exact flat inventory"):
            self.execute(archive_bytes(((MEMBER, b"data"), ("extra.py", b"bad"))))
        self.assertFalse(self.target.exists())

    def test_traversal_member_fails_before_extraction(self):
        with self.assertRaisesRegex(SystemExit, "exact flat inventory"):
            self.execute(archive_bytes((("../outside.py", b"bad"),)))
        self.assertFalse((self.root / "outside.py").exists())
        self.assertFalse(self.target.exists())

    def test_symlink_member_fails_before_extraction(self):
        with self.assertRaisesRegex(SystemExit, "unsafe member"):
            self.execute(archive_bytes(mode=stat.S_IFLNK | 0o777))
        self.assertFalse(self.target.exists())

    def test_special_member_fails_before_extraction(self):
        with self.assertRaisesRegex(SystemExit, "unsafe member"):
            self.execute(archive_bytes(mode=stat.S_IFIFO | 0o600))
        self.assertFalse(self.target.exists())

    def test_empty_member_fails_before_extraction(self):
        with self.assertRaisesRegex(SystemExit, "unsafe member"):
            self.execute(archive_bytes(((MEMBER, b""),)))
        self.assertFalse(self.target.exists())

    def test_download_size_is_bounded_before_archive_parse(self):
        with mock.patch("zipfile.ZipFile", side_effect=AssertionError("Parsed oversized download")):
            with self.assertRaisesRegex(ValueError, "download limit"):
                self.execute(b"x" * 2048, limit=1024)
        self.assertFalse(self.target.exists())

    def test_decompressed_member_size_is_bounded(self):
        payload = archive_bytes(((MEMBER, b"x" * 2048),))
        self.assertLess(len(payload), 1024)
        with self.assertRaisesRegex(SystemExit, "unsafe member"):
            self.execute(payload, limit=1024)
        self.assertFalse(self.target.exists())

    def test_download_command_failure_fails_before_extraction(self):
        with self.assertRaisesRegex(ValueError, "download failed"):
            self.execute(archive_bytes(), returncode=1)
        self.assertFalse(self.target.exists())

    def test_invalid_artifact_id_cannot_reach_command(self):
        with self.assertRaisesRegex(SystemExit, "Invalid material artifact identity"):
            self.execute(archive_bytes(), artifact_id="42/../../bad")
        self.assertFalse(self.target.parent.exists())


if __name__ == "__main__":
    unittest.main()

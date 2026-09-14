"""Test the exact-artifact transfer without GitHub credentials or release imports."""
import ast
import hashlib
import io
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'tools/publish_github_release.py').read_text(encoding='utf-8'))
FUNCTIONS = {'require', '_sha256', '_download_exact_artifact'}
BOUNDARY = ast.Module(body=[
    node for node in TREE.body
    if (isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS)
    or (isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == 'MAX_ARTIFACT_ARCHIVE_BYTES'
        for target in node.targets
    ))
], type_ignores=[])


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


NAMESPACE = dict(Path=Path, re=re, shutil=shutil, stat=stat,
                 subprocess=subprocess, zipfile=zipfile, digest=digest)
exec(compile(BOUNDARY, '<publisher-artifact-transfer>', 'exec'), NAMESPACE)


class PublisherArtifactDownloadTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / 'download'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('receipt.json', b'{"valid":true}\n')
        self.payload = stream.getvalue()
        self.artifact = {'id': 123, 'digest': 'sha256:' + hashlib.sha256(self.payload).hexdigest()}

    def process(self, payload=None, returncode=0):
        process = MagicMock()
        process.stdout = io.BytesIO(self.payload if payload is None else payload)
        process.wait.return_value = returncode
        process.__enter__.return_value = process
        process.__exit__.return_value = False
        return process

    def download(self):
        return NAMESPACE['_download_exact_artifact'](
            'owner/repository', self.artifact, self.destination, {'receipt.json'}
        )

    def assert_no_materials(self):
        self.assertFalse((self.destination / '.artifact.zip').exists())
        self.assertFalse((self.destination / 'receipt.json').exists())

    def test_api_stdout_is_streamed_without_unsupported_output_flag(self):
        process = self.process()
        with patch.object(subprocess, 'Popen', return_value=process) as popen:
            result = self.download()
        popen.assert_called_once_with(
            ['gh', 'api', 'repos/owner/repository/actions/artifacts/123/zip'],
            stdout=subprocess.PIPE,
        )
        self.assertEqual(result, self.destination)
        self.assertEqual((result / 'receipt.json').read_bytes(), b'{"valid":true}\n')
        self.assertFalse((result / '.artifact.zip').exists())
        process.kill.assert_not_called()

    def test_download_accepts_exact_limit(self):
        with patch.dict(NAMESPACE, MAX_ARTIFACT_ARCHIVE_BYTES=len(self.payload)), \
                patch.object(subprocess, 'Popen', return_value=self.process()):
            self.download()

    def test_oversize_stream_is_killed_before_any_zip_parse(self):
        process = self.process()
        with patch.dict(NAMESPACE, MAX_ARTIFACT_ARCHIVE_BYTES=len(self.payload) - 1), \
                patch.object(subprocess, 'Popen', return_value=process), \
                patch.object(zipfile, 'ZipFile') as parse:
            with self.assertRaisesRegex(ValueError, 'safe download limit'):
                self.download()
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with()
        parse.assert_not_called()
        self.assert_no_materials()

    def test_nonzero_api_exit_is_not_parsed_even_with_valid_zip_bytes(self):
        process = self.process(returncode=1)
        with patch.object(subprocess, 'Popen', return_value=process), \
                patch.object(zipfile, 'ZipFile') as parse:
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                self.download()
        self.assertEqual(raised.exception.returncode, 1)
        parse.assert_not_called()
        self.assert_no_materials()

    def test_digest_mismatch_is_rejected_before_any_zip_parse(self):
        self.artifact['digest'] = 'sha256:' + '0' * 64
        with patch.object(subprocess, 'Popen', return_value=self.process()), \
                patch.object(zipfile, 'ZipFile') as parse:
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                self.download()
        parse.assert_not_called()
        self.assert_no_materials()

    def test_spawn_failure_leaves_no_archive(self):
        with patch.object(subprocess, 'Popen', side_effect=FileNotFoundError('gh')):
            with self.assertRaises(FileNotFoundError):
                self.download()
        self.assert_no_materials()


if __name__ == '__main__':
    unittest.main()

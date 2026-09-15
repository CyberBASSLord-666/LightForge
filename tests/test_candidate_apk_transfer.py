import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('candidate_apk_transfer', ROOT / 'tools/candidate_apk_transfer.py')
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


class CandidateAPKTransferTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = bytes(range(256)) * 3
        self.apk = self.root / 'LightForge-2.2.5.apk'
        self.apk.write_bytes(self.payload)
        self.checksum = hashlib.sha256(self.payload).hexdigest()
        self.commit = 'b' * 40
        candidate = {
            'artifact_id': 73, 'artifact_digest': 'c' * 64, 'identity_sha256': 'd' * 64,
            'source': {'commit': self.commit, 'tree_sha': 'e' * 40},
            'pipeline': {'run_id': 321, 'run_attempt': 1, 'evidence_session': 'f' * 64},
            'source_hashes': {'version.json': 'a' * 64},
            'files': {self.apk.name: {'bytes': len(self.payload), 'sha256': self.checksum}},
        }
        self.manifest = transfer.split_apk(self.apk, '2.2.5', candidate,
            {'run_id': 432, 'run_attempt': 2}, self.root / 'transfer', part_bytes=200)
        self.parts = self.root / 'transfer/parts'
        self.output = self.root / 'reconstructed.apk'

    def assemble(self, manifest=None):
        return transfer.reassemble(manifest or self.manifest, self.parts, self.output,
            expected_source_commit=self.commit, expected_apk_sha256=self.checksum)

    def test_byte_exact_roundtrip_and_bounded_contiguous_parts(self):
        self.assertEqual([part['bytes'] for part in self.manifest['parts']], [200, 200, 200, 168])
        self.assertEqual([part['offset'] for part in self.manifest['parts']], [0, 200, 400, 600])
        self.assertEqual(self.manifest['parts'][0]['artifact'], 'lightforge-signing-432-2-part-01')
        self.assemble()
        self.assertEqual(self.output.read_bytes(), self.payload)
        self.assertLess(transfer.PART_BYTES + 1024**2, 512 * 1024**2)
        self.assertEqual((transfer.MAX_APK_BYTES + transfer.PART_BYTES - 1) // transfer.PART_BYTES, transfer.MAX_PARTS)

    def test_command_line_reassembles_the_same_candidate(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/candidate_apk_transfer.py'),
            str(self.root / 'transfer/transfer-manifest.json'), str(self.parts), str(self.output),
            '--expected-source-commit', self.commit, '--expected-apk-sha256', self.checksum],
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), self.payload)
        self.assertIs(json.loads(result.stdout)['release_signed'], False)

    def test_missing_and_unexpected_parts_rejected(self):
        first = self.parts / 'part-01.bin'
        first.rename(self.root / 'missing-part')
        with self.assertRaisesRegex(ValueError, 'part inventory'):
            self.assemble()
        (self.root / 'missing-part').rename(first)
        (self.parts / 'unexpected.bin').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'part inventory'):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_truncated_and_altered_parts_preserve_existing_output(self):
        self.output.write_bytes(b'previous verified file')
        first = self.parts / 'part-01.bin'
        original = first.read_bytes()
        first.write_bytes(original[:-1])
        with self.assertRaisesRegex(ValueError, 'truncated part'):
            self.assemble()
        first.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, 'Part digest'):
            self.assemble()
        self.assertEqual(self.output.read_bytes(), b'previous verified file')
        self.assertFalse(list(self.root.glob('.candidate-transfer-*')))

    def test_rehashed_altered_part_still_fails_final_apk_digest(self):
        first = self.parts / 'part-01.bin'
        first.write_bytes(b'x' * 200)
        manifest = copy.deepcopy(self.manifest)
        manifest['parts'][0]['sha256'] = transfer.digest(first)
        with self.assertRaisesRegex(ValueError, 'Reconstructed APK digest'):
            self.assemble(manifest)
        self.assertFalse(self.output.exists())

    def test_source_binding_and_part_order_cannot_change(self):
        for mutate, message in (
            (lambda m: m['candidate']['source'].update(commit='0' * 40), 'Candidate source'),
            (lambda m: m['parts'].reverse(), 'part identity or ordering'),
            (lambda m: m['parts'][0].update(name='../outside'), 'part identity or ordering'),
            (lambda m: m['parts'][0].update(offset=1), 'part range'),
            (lambda m: m['parts'].pop(), 'Incomplete part inventory'),
        ):
            with self.subTest(message=message):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaisesRegex(ValueError, message):
                    self.assemble(manifest)
        self.assertFalse(self.output.exists())

    def test_symlink_part_is_rejected(self):
        first = self.parts / 'part-01.bin'
        first.rename(self.root / 'real-part')
        first.symlink_to(self.root / 'real-part')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_source_identity_checked_before_splitting(self):
        candidate = copy.deepcopy(self.manifest['candidate'])
        candidate['files'][self.apk.name]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Candidate APK identity differs'):
            transfer.split_apk(self.apk, '2.2.5', candidate, self.manifest['preparation'], self.root / 'invalid')
        self.assertFalse((self.root / 'invalid').exists())

    def test_part_size_and_count_limits_are_enforced(self):
        for part_bytes in (0, transfer.PART_BYTES + 1, 100):
            with self.subTest(part_bytes=part_bytes):
                with self.assertRaisesRegex(ValueError, 'limits|part count'):
                    transfer.split_apk(self.apk, '2.2.5', self.manifest['candidate'],
                        self.manifest['preparation'], self.root / 'invalid', part_bytes=part_bytes)
                self.assertFalse((self.root / 'invalid').exists())

    def test_prepare_workflow_keeps_index_and_private_bounded_uploads(self):
        text = (ROOT / '.github/workflows/prepare-release.yml').read_text()
        self.assertIn("'releases/v*/prepare.json'", text)
        self.assertIn('contents: read\n  actions: read', text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('secrets.', text)
        self.assertIn("run['event'] == 'push' and run['head_branch'] == 'main'", text)
        self.assertIn("f\"repos/{repo}/actions/artifacts/{artifact['id']}/zip\"", text)
        self.assertIn("sha256_file(archive_path) == checksum.removeprefix('sha256:')", text)
        self.assertIn("if total > artifact['size_in_bytes']:", text)
        self.assertIn('process.kill()\n                  process.wait()', text)
        self.assertIn("'head_sha', 'run_attempt', 'event', 'head_branch'", text)
        self.assertIn('name: verified-candidate-index', text)
        self.assertIn('build/transfer/candidate-manifest.json', text)
        self.assertEqual(text.count('compression-level: 0'), transfer.MAX_PARTS)
        for number in range(1, transfer.MAX_PARTS + 1):
            self.assertIn('fromJSON(steps.transfer.outputs.part_count) >= ' + str(number), text)
            self.assertIn(f'path: build/transfer/parts/part-{number:02d}.bin', text)
        refs = re.findall(r'uses: [^@\s]+@([^\s]+)', text)
        self.assertTrue(refs)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}', revision) for revision in refs))


if __name__ == '__main__':
    unittest.main()

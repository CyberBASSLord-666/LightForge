import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import android_evidence_manifest as evidence


HEAD = 'a' * 40
TREE = 'b' * 40
SESSION = 'c' * 64
RELEASE = '2.2.4'


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AndroidEvidenceManifestTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input = self.root / 'dist'
        self.input.mkdir()
        self.apk = self.input / ('LightForge-' + RELEASE + '.apk')
        self.apk.write_bytes(b'candidate-apk')
        (self.input / 'background-tests.apk').write_bytes(b'background-test')
        (self.input / 'diagnostics-tests.apk').write_bytes(b'diagnostics-test')
        metadata = {'bytes': self.apk.stat().st_size, 'sha256': checksum(self.apk)}
        (self.input / (self.apk.name + '.json')).write_text(json.dumps(metadata))
        (self.input / (self.apk.name + '.sha256')).write_text(metadata['sha256'] + '  ' + self.apk.name + '\n')
        self.candidate = self.root / 'candidate'
        evidence.create_candidate(argparse.Namespace(
            input_dir=self.input, output_dir=self.candidate, release=RELEASE, run_id=44,
            run_attempt=3, head_sha=HEAD, tree_sha=TREE, evidence_session=SESSION,
        ))
        self.binding = evidence.candidate_binding(self.candidate, RELEASE, artifact_id=55,
                                                  artifact_digest='d' * 64, head_sha=HEAD)
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir()
        self.background = self.receipts / 'android-background-verification.json'
        self.diagnostics = self.receipts / 'android-diagnostics-verification.json'
        for path in (self.background, self.diagnostics):
            path.write_text(json.dumps({
                'release': RELEASE, 'passed': True, 'errors': [],
                'source_hashes': {'web/app.js': 'e' * 64},
                'ci': {'run_id': 44, 'run_attempt': 3, 'head_sha': HEAD, 'evidence_session': SESSION},
                'candidate': self.binding,
            }))

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, output):
        evidence.write_evidence(argparse.Namespace(
            output_dir=output, background_receipt=self.background,
            diagnostics_receipt=self.diagnostics, candidate_dir=self.candidate,
            candidate_artifact_id=55, candidate_artifact_digest='d' * 64, release=RELEASE,
            run_id=44, run_attempt=3, head_sha=HEAD, evidence_session=SESSION,
        ))

    def test_valid_sealed_artifact_has_only_exact_receipts(self):
        output = self.root / 'accepted'
        self.write(output)
        manifest = evidence.verify_evidence(output, release=RELEASE, run_id=44,
                                            run_attempt=3, head_sha=HEAD)
        self.assertEqual(set(manifest['receipts']), {
            'android-background-verification.json', 'android-diagnostics-verification.json'})
        self.assertEqual({path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file()}, {
            'android-evidence-manifest.json',
            'receipts/android-background-verification.json',
            'receipts/android-diagnostics-verification.json'})

    def test_rejects_stale_checkout_receipt_before_manifest_creation(self):
        stale = json.loads(self.background.read_text())
        stale['ci']['run_attempt'] = 2
        self.background.write_text(json.dumps(stale))
        with self.assertRaisesRegex(ValueError, 'CI binding differs'):
            self.write(self.root / 'accepted')
        self.assertFalse((self.root / 'accepted').exists())

    def test_rejects_partial_and_extra_artifacts(self):
        output = self.root / 'accepted'
        self.write(output)
        (output / 'receipts/android-diagnostics-verification.json').unlink()
        with self.assertRaisesRegex(ValueError, 'unexpected or missing'):
            evidence.verify_evidence(output, release=RELEASE, run_id=44, run_attempt=3, head_sha=HEAD)
        shutil.rmtree(output)
        self.write(output)
        (output / 'old-top-level-receipt.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unexpected or missing'):
            evidence.verify_evidence(output, release=RELEASE, run_id=44, run_attempt=3, head_sha=HEAD)

    def test_rejects_tampered_receipt_digest_and_candidate_binding(self):
        output = self.root / 'accepted'
        self.write(output)
        receipt = output / 'receipts/android-background-verification.json'
        altered = json.loads(receipt.read_text())
        altered['candidate']['artifact_id'] = 99
        receipt.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            evidence.verify_evidence(output, release=RELEASE, run_id=44, run_attempt=3, head_sha=HEAD)


if __name__ == '__main__':
    unittest.main()

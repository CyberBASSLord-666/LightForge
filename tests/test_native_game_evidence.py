"""Fail-closed native GAME evidence contracts; these are not model measurements."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'qa/release-2.3.2/native_game_evidence.py'
SPEC = importlib.util.spec_from_file_location('native_game_release_evidence', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SESSION = 'a' * 64


def encoded(text):
    return {'utf8': text, 'bytes': len(text.encode()),
            'sha256': hashlib.sha256(text.encode()).hexdigest()}


def retained():
    return {'schema': MODULE.RETAINED_SCHEMA, 'fixture': {}, 'files': {
        name: encoded('{}\n') for name in (
            'experiment.json', 'capture-input.json', 'summary.json',
            'production-process-comparison.json')}}


class NativeGameEvidenceTest(unittest.TestCase):
    def test_json_rejects_nonfinite_and_duplicate_keys(self):
        for text in ('{"passed":false,"passed":true}', '{"x":NaN}', '{"x":[Infinity]}', '{"x":1e999}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                MODULE.loads(text)

    def test_retained_json_preserves_exact_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = retained()
            artifact['files']['passage-0/native/receipt.json'] = encoded('{"notes": []}\n')
            MODULE.unpack_json(artifact, root)
            self.assertEqual((root / 'passage-0/native/receipt.json').read_bytes(), b'{"notes": []}\n')

    def test_retained_path_cannot_escape_or_overwrite_non_json(self):
        for name in ('../outside.json', '/tmp/outside.json', 'passage//result.json',
                     'passage/./result.json', 'passage\\result.json', 'audio.f32'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                artifact = retained()
                artifact['files'][name] = encoded('{}')
                with self.assertRaisesRegex(ValueError, 'Invalid retained GAME path'):
                    MODULE.unpack_json(artifact, Path(folder))

    def test_retained_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = retained()
            artifact['files']['experiment.json']['utf8'] = '{"changed":true}\n'
            with self.assertRaisesRegex(ValueError, 'integrity'):
                MODULE.unpack_json(artifact, Path(folder))

    def test_missing_required_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = retained()
            artifact['files']['not-summary.json'] = artifact['files'].pop('summary.json')
            with self.assertRaisesRegex(ValueError, 'Missing required'):
                MODULE.unpack_json(artifact, Path(folder))

    def receipt(self):
        return {'schema': MODULE.SCHEMA, 'release': MODULE.RELEASE,
                'passed': True, 'errors': [],
                'evidenceSessionSchema': 'lightforge.evidence-session.v1',
                'evidenceSession': SESSION,
                'source_hashes': {}, 'source_hashes_after': {},
                'analysis_asset_hashes': {}, 'analysis_asset_hashes_after': {}}

    def test_missing_failed_wrong_release_or_stale_session_never_passes(self):
        variants = [None, {}, self.receipt() | {'passed': False},
                    self.receipt() | {'release': '2.3.1'},
                    self.receipt() | {'errors': ['failure']},
                    self.receipt() | {'evidenceSession': 'b' * 64}]
        for receipt in variants:
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, 'missing, failed, or stale'):
                MODULE.verify_receipt(ROOT, receipt, SESSION, {})

    def test_no_fresh_session_is_rejected(self):
        receipt = self.receipt() | {'evidenceSession': None}
        with self.assertRaisesRegex(ValueError, 'fresh evidence session'):
            MODULE.verify_receipt(ROOT, receipt, None, {})

    def test_source_change_is_rejected_before_any_retained_replay(self):
        with patch.object(MODULE, 'hash_sources', return_value={'source.java': '1' * 64}), \
             patch.object(MODULE, 'hash_assets', return_value={}), \
             patch.object(MODULE, 'verify_retained') as replay:
            with self.assertRaisesRegex(ValueError, 'source bytes changed'):
                MODULE.verify_receipt(ROOT, self.receipt(), SESSION, {})
            replay.assert_not_called()

    def test_graph_change_is_rejected_before_any_retained_replay(self):
        with patch.object(MODULE, 'hash_sources', return_value={}), \
             patch.object(MODULE, 'hash_assets', return_value={'graph.onnx': '2' * 64}), \
             patch.object(MODULE, 'verify_retained') as replay:
            with self.assertRaisesRegex(ValueError, 'model/runtime assets changed'):
                MODULE.verify_receipt(ROOT, self.receipt(), SESSION, {})
            replay.assert_not_called()

    def test_receipt_cannot_omit_either_fixed_input(self):
        with patch.object(MODULE, 'hash_sources', return_value={}), \
             patch.object(MODULE, 'hash_assets', return_value={}):
            for runs in (None, [], [{}], [{}, {}, {}]):
                with self.subTest(runs=runs), self.assertRaisesRegex(ValueError, 'input coverage'):
                    MODULE.verify_receipt(ROOT, self.receipt() | {'runs': runs}, SESSION, {})

    def test_truncated_source_claim_fails_before_model_or_runtime_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'public.wav'
            source.write_bytes(b'fixed fixture bytes')
            fixture = {'id': 'demo', 'source': 'public.wav', 'sourceSha256': MODULE.digest(source),
                       'monoPcmSha256': '1' * 64, 'samples': 44100, 'sampleRate': 44100,
                       'channels': 2, 'monoDerivation': 'production-stereo44100-float32-mean-v1',
                       'separationApplied': False}
            artifact = retained() | {'fixture': fixture}
            complete_source = fixture | {'samples': 88200}
            with patch.object(MODULE.subprocess, 'check_output', return_value=json.dumps(complete_source)), \
                 self.assertRaisesRegex(ValueError, 'exact complete public source'):
                MODULE.verify_retained(root, artifact, {'id': 'demo', 'source': 'public.wav'})

    def test_workflow_runs_fresh_game_after_models_fixtures_and_before_analysis(self):
        text = (ROOT / '.github/workflows/verify-v2.yml').read_text()
        commands = [
            'python3 tools/prepare_game.py',
            'python3 qa/release-1.6.0/prepare-musdb-fixtures.py',
            'python3 tools/bootstrap_toolchain.py',
            'python3 tests/test_native_game_engine.py',
            'python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-native-game.py',
            'python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-analysis.py',
        ]
        positions = []
        for command in commands:
            self.assertEqual(text.count(command), 1, command)
            positions.append(text.index(command))
        self.assertEqual(positions, sorted(positions))
        self.assertIn('"$receipt_root/native-game-verification.json"', text)

    def test_current_analysis_gate_cannot_omit_native_game(self):
        text = (ROOT / 'qa/release-2.3.2/verify-analysis.py').read_text()
        self.assertIn('native_game = verify_native_game(root, hashes, evidence_session)', text)
        self.assertIn('verifier.verify_receipt(root, receipt, evidence_session, hashes)', text)
        self.assertIn("'fresh_native_game'", text)
        self.assertNotIn('verify_native_game(', (ROOT / 'qa/release-2.3.1/verify-analysis.py').read_text())


if __name__ == '__main__':
    unittest.main()

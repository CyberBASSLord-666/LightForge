"""Fail closed on incomplete Android GAME proof without rewriting old releases."""
import copy
from pathlib import Path
import unittest

from tools import android_evidence_manifest as evidence


BACKGROUND = 'android-background-verification.json'
HEAD, SESSION = 'a' * 40, 'b' * 64
SOURCES = {'android/src/com/cyberbasslord/lightforge/NativeGame.java': 'c' * 64}


def device():
    return {'nativeGame': {
        'sampleRate': 44100, 'samples': 705600, 'language': 0, 'seed': 2025,
        'steps': 8, 'completedPasses': 1, 'noteCount': 27,
        'model': 'game-large-1.0.3-lightforge-1',
        'fixture': 'bundled-demo-first16s-stereo16-mono-average',
        'pcmSHA256': '6724721e8c1c4ac9ce532d46697393f8fafe81e7935f88399f05bc341115cedd',
        'notesSHA256': 'd' * 64, 'cancelledState': 'cancelled', 'cancellationProgress': .18,
        'unroundedNotesObserved': True, 'completedRetired': True, 'ownershipChecks': True,
        'boundedUploadChecked': True, 'uploadCancelChecked': True,
        'liveNativeCancellationObserved': True, 'cancelledRetired': True, 'executorRetired': True,
        'scope': 'Android emulator: isolated real production NativeGameTask/JobBridge with bundled GAME JNI; '
                 'test-only service-owner attachment, not an OS service-start, comparative-quality, speedup or physical-device claim.',
    }}


def receipt(release='2.3.2'):
    return {'passed': True, 'errors': [], 'release': release, 'source_hashes': SOURCES.copy(),
            'ci': {'run_id': 55, 'run_attempt': 2, 'head_sha': HEAD, 'evidence_session': SESSION},
            'candidate': {'source_hashes': SOURCES.copy(), 'identity_sha256': 'e' * 64},
            'device': device()}


class NativeGameAndroidEvidenceTest(unittest.TestCase):
    def validate_receipt(self, value, name=BACKGROUND, release='2.3.2'):
        return evidence._receipt(value, name, release=release, run_id=55, run_attempt=2,
                                 head_sha=HEAD, session=SESSION, candidate=receipt()['candidate'])

    def test_complete_declared_fixture_is_accepted_without_mutation(self):
        value = device()
        before = copy.deepcopy(value)
        self.assertIs(evidence.validate_native_game_device(value), value['nativeGame'])
        self.assertEqual(value, before)
        self.assertTrue(self.validate_receipt(receipt())['passed'])

    def test_missing_or_wrong_device_shapes_fail_closed(self):
        for value in (None, [], True, '', {}, {'nativeGame': None}, {'nativeGame': []},
                      {'nativeGame': True}, {'nativeGame': 'passed'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence.validate_native_game_device(value)
        value = receipt()
        del value['device']
        with self.assertRaisesRegex(ValueError, 'device evidence is missing'):
            self.validate_receipt(value)

    def test_every_required_field_must_be_present(self):
        for field in device()['nativeGame']:
            value = device()
            del value['nativeGame'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.validate_native_game_device(value)

    def test_integer_identity_rejects_bools_floats_strings_and_mismatch(self):
        for field in ('sampleRate', 'samples', 'language', 'seed', 'steps', 'completedPasses'):
            expected = device()['nativeGame'][field]
            for invalid in (True, False, float(expected), str(expected), expected + 1, None):
                value = device()
                value['nativeGame'][field] = invalid
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    evidence.validate_native_game_device(value)

    def test_note_count_is_a_bounded_strict_integer(self):
        for count in (1, 1601):
            value = device()
            value['nativeGame']['noteCount'] = count
            evidence.validate_native_game_device(value)
        for count in (0, -1, 1602, True, False, 27.0, '27', float('nan'), float('inf')):
            value = device()
            value['nativeGame']['noteCount'] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                evidence.validate_native_game_device(value)

    def test_each_boolean_proof_requires_literal_true(self):
        flags = [key for key, value in device()['nativeGame'].items() if value is True]
        self.assertEqual(len(flags), 8)
        for field in flags:
            for invalid in (False, 1, 0, 'true', None, [], {}):
                value = device()
                value['nativeGame'][field] = invalid
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    evidence.validate_native_game_device(value)

    def test_cancellation_progress_is_finite_and_live(self):
        for progress in (.18, .26, .819999):
            value = device()
            value['nativeGame']['cancellationProgress'] = progress
            evidence.validate_native_game_device(value)
        for progress in (-1, 0, .179999, .82, 1, True, False, '.18', None,
                         float('nan'), float('inf'), -float('inf'), 10**400):
            value = device()
            value['nativeGame']['cancellationProgress'] = progress
            with self.subTest(progress=progress), self.assertRaises(ValueError):
                evidence.validate_native_game_device(value)

    def test_fixture_model_cancelled_state_and_scope_cannot_be_substituted(self):
        for field in ('fixture', 'model', 'cancelledState', 'scope'):
            for invalid in ('', 'other', None, True):
                value = device()
                value['nativeGame'][field] = invalid
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    evidence.validate_native_game_device(value)

    def test_digests_are_lowercase_sha256_and_pcm_is_exact(self):
        for field in ('pcmSHA256', 'notesSHA256'):
            for invalid in ('a' * 63, 'A' * 64, 'g' * 64, '', None, True, 'a' * 64 + '\n'):
                value = device()
                value['nativeGame'][field] = invalid
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    evidence.validate_native_game_device(value)
        value = device()
        value['nativeGame']['pcmSHA256'] = 'a' * 64
        with self.assertRaises(ValueError):
            evidence.validate_native_game_device(value)

    def test_background_receipt_enforces_each_required_field(self):
        for field in device()['nativeGame']:
            value = receipt()
            del value['device']['nativeGame'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate_receipt(value)

    def test_current_diagnostics_and_historical_receipts_are_unchanged(self):
        current_diagnostics = receipt()
        del current_diagnostics['device']
        self.assertTrue(self.validate_receipt(current_diagnostics, name='android-diagnostics-verification.json')['passed'])
        for release in ('2.2.4', '2.2.5', '2.3.0', '2.3.1'):
            value = receipt(release)
            del value['device']
            self.assertTrue(self.validate_receipt(value, release=release)['passed'])

    def test_native_game_proof_cannot_replace_candidate_source_or_ci_bindings(self):
        for mutate, reason in (
                (lambda value: value.update(passed=False), 'did not pass'),
                (lambda value: value.update(errors=['failure']), 'did not pass'),
                (lambda value: value.update(release='2.3.1'), 'release differs'),
                (lambda value: value.update(source_hashes={'web/old.js': 'f' * 64}), 'source binding differs'),
                (lambda value: value['ci'].update(run_attempt=1), 'CI binding differs'),
                (lambda value: value['candidate'].update(identity_sha256='f' * 64), 'candidate binding differs')):
            value = receipt()
            mutate(value)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.validate_receipt(value)

    def test_runtime_runner_reuses_validator_before_marking_success(self):
        source = (Path(__file__).resolve().parents[1] / 'tools/run_android_background_tests.py').read_text()
        self.assertIn('candidate_binding, validate_native_game_device', source)
        call = source.index("validate_native_game_device(receipt.get('device'))")
        self.assertGreater(call, source.index("Android Balanced native lifecycle evidence is incomplete"))
        self.assertLess(call, source.index("receipt['passed']=True"))


if __name__ == '__main__':
    unittest.main()

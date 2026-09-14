"""Fail-closed session binding tests for regenerated release evidence."""
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase, main
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location('lightforge_verify_analysis_session', ROOT / 'qa/release-2.2.4/verify-analysis.py')
VERIFY = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)

SESSION = 'a' * 64
OTHER_SESSION = 'b' * 64


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


class EvidenceSessionBindingTest(TestCase):
    def write_receipt(self, root, name, session=None, schema=VERIFY.EVIDENCE_SESSION_SCHEMA):
        path = root / 'qa' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {'passed': True}
        if session is not None:
            receipt.update({'evidenceSessionSchema': schema, 'evidenceSession': session})
        path.write_text(json.dumps(receipt))
        return path

    def write_fresh_receipt(self, root, name='fresh.json', session=SESSION, passed=True, errors=None):
        source_relative = 'web/source.js'
        source = root / source_relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('const verifiedSource = true;\n')
        receipt_path = root / 'qa' / name
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            'release': '2.2.4',
            'passed': passed,
            'errors': [] if errors is None else errors,
            'completedAt': '2026-09-10T00:00:00Z',
            'source_hashes': {source_relative: digest(source)},
        }
        if session is not None:
            receipt.update({'evidenceSessionSchema': VERIFY.EVIDENCE_SESSION_SCHEMA,
                            'evidenceSession': session})
        receipt_path.write_text(json.dumps(receipt))
        return receipt_path, source

    def write_fresh_producer_receipt(self, root, relative, sources):
        source_hashes = {}
        for source_relative in sources:
            source = root / source_relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(('bound source: ' + source_relative + '\n').encode())
            source_hashes[source_relative] = digest(source)
        receipt_path = root / relative
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps({
            'release': '2.2.4', 'passed': True, 'errors': [],
            'completedAt': '2026-09-10T00:00:00Z',
            'evidenceSessionSchema': VERIFY.EVIDENCE_SESSION_SCHEMA,
            'evidenceSession': SESSION, 'source_hashes': source_hashes,
        }))
        return receipt_path

    def test_no_session_requires_the_immutable_pin_and_rejects_session_bound_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_receipt(root, 'mdx.json')
            expected = digest(path)
            hashes = {}
            bound, receipt = VERIFY.bind_session_receipt(root, 'qa/mdx.json', expected, hashes, None, 'MDX')
            self.assertEqual(bound, path)
            self.assertEqual(receipt, {'passed': True})
            self.assertEqual(hashes, {'qa/mdx.json': expected})
            self.write_receipt(root, 'mdx.json', session=SESSION)
            with self.assertRaisesRegex(ValueError, 'session-bound'):
                VERIFY.bind_session_receipt(root, 'qa/mdx.json', expected, {}, None, 'MDX')
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                VERIFY.bind_session_receipt(root, 'qa/mdx.json', expected, {}, None, 'MDX')

    def test_session_mode_rejects_absent_and_wrong_or_stale_nonces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_receipt(root, 'downstream.json', session=SESSION)
            hashes = {}
            VERIFY.bind_session_receipt(root, 'qa/downstream.json', '0' * 64, hashes, SESSION, 'Downstream')
            self.assertEqual(hashes['qa/downstream.json'], digest(path))

            self.write_receipt(root, 'downstream.json', session=OTHER_SESSION)
            with self.assertRaisesRegex(ValueError, 'different evidence session'):
                VERIFY.bind_session_receipt(root, 'qa/downstream.json', '0' * 64, {}, SESSION, 'Downstream')

            self.write_receipt(root, 'downstream.json')
            with self.assertRaisesRegex(ValueError, 'stale, absent'):
                VERIFY.bind_session_receipt(root, 'qa/downstream.json', '0' * 64, {}, SESSION, 'Downstream')

    def test_fresh_receipts_fail_closed_for_replay_missing_mismatch_changed_source_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, source = self.write_fresh_receipt(root)
            hashes = {}
            result = VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', hashes, SESSION,
                                                 'Browser', {'web/source.js'})
            self.assertTrue(result['passed'])
            self.assertEqual(hashes['qa/fresh.json'], digest(receipt))
            self.assertEqual(hashes['web/source.js'], digest(source))

            self.write_fresh_receipt(root, session=OTHER_SESSION)
            with self.assertRaisesRegex(ValueError, 'different evidence session'):
                VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', {}, SESSION,
                                             'Browser', {'web/source.js'})

            self.write_fresh_receipt(root, session=None)
            with self.assertRaisesRegex(ValueError, 'stale, absent'):
                VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', {}, SESSION,
                                             'Browser', {'web/source.js'})

            self.write_fresh_receipt(root, passed=False)
            with self.assertRaisesRegex(ValueError, 'did not pass cleanly'):
                VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', {}, SESSION,
                                             'Browser', {'web/source.js'})

            self.write_fresh_receipt(root, errors=['producer failed'])
            with self.assertRaisesRegex(ValueError, 'did not pass cleanly'):
                VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', {}, SESSION,
                                             'Browser', {'web/source.js'})

            self.write_fresh_receipt(root)
            source.write_text('replayed source bytes\n')
            with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                VERIFY.verify_fresh_receipt(root, 'qa/fresh.json', {}, SESSION,
                                             'Browser', {'web/source.js'})

    def test_browser_and_analysis_browser_consumed_fixtures_are_session_bound(self):
        cases = [
            (VERIFY.OUT + 'browser-verification.json', VERIFY.BROWSER_SOURCES,
             'qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json',
             VERIFY.verify_browser_receipt),
            (VERIFY.OUT + 'analysis-browser-verification.json', VERIFY.ANALYSIS_BROWSER_SOURCES,
             'qa/release-1.6.0/fixtures/falcon-mix.wav',
             VERIFY.verify_analysis_browser_receipt),
        ]
        for receipt_relative, sources, fixture_relative, verify in cases:
            with self.subTest(receipt=receipt_relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.assertIn(fixture_relative, sources)
                receipt = self.write_fresh_producer_receipt(root, receipt_relative, sources)
                hashes = {}
                self.assertTrue(verify(root, hashes, SESSION)['passed'])
                self.assertEqual(hashes[receipt_relative], digest(receipt))
                fixture = root / fixture_relative
                fixture.write_bytes(b'mutated consumed fixture\n')
                with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                    verify(root, {}, SESSION)

    def test_source_clock_accepts_historical_no_session_and_requires_exact_session_when_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_hashes = {}
            for relative in VERIFY.CLOCK_SOURCES:
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(relative + '\n')
                source_hashes[relative] = digest(source)
            receipt_path = root / VERIFY.OUT / 'source-clock-verification.json'
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt = {
                'release': '2.2.4', 'passed': True, 'errors': [], 'source_hashes': source_hashes,
                'samples': 932143, 'chunks': 4, 'maxAbsError': 0.0,
                'contiguousSourceSamples': True, 'monotonicProgress': True,
                'completedAt': '2026-09-10T00:00:00Z',
            }
            receipt_path.write_text(json.dumps(receipt))
            self.assertEqual(VERIFY.verify_clock(root, {}, None)['samples'], 932143)

            receipt.update({'evidenceSessionSchema': VERIFY.EVIDENCE_SESSION_SCHEMA,
                            'evidenceSession': SESSION})
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'session-bound source-clock'):
                VERIFY.verify_clock(root, {}, None)
            hashes = {}
            self.assertEqual(VERIFY.verify_clock(root, hashes, SESSION)['chunks'], 4)
            self.assertEqual(hashes[VERIFY.OUT + 'source-clock-verification.json'], digest(receipt_path))

    def test_mixed_receipt_nonces_cannot_form_one_evidence_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mdx = self.write_receipt(root, 'mdx.json', session=SESSION)
            downstream = self.write_receipt(root, 'downstream.json', session=OTHER_SESSION)
            hashes = {}
            VERIFY.bind_session_receipt(root, mdx.relative_to(root).as_posix(), '0' * 64, hashes, SESSION, 'MDX')
            with self.assertRaisesRegex(ValueError, 'different evidence session'):
                VERIFY.bind_session_receipt(root, downstream.relative_to(root).as_posix(), '0' * 64,
                                            hashes, SESSION, 'Downstream')

    def test_downstream_session_receipt_binds_exact_upstream_mdx_digest_and_nonce(self):
        mdx_path = VERIFY.OUT + 'native-mdx-comparison-verification.json'
        hashes = {mdx_path: 'c' * 64}
        good = {'upstreamMdx': {
            'path': mdx_path,
            'sha256': 'c' * 64,
            'evidenceSession': SESSION,
        }}
        VERIFY.verify_downstream_upstream(good, hashes, SESSION)
        for field, value in [('sha256', 'd' * 64), ('evidenceSession', OTHER_SESSION)]:
            changed = {'upstreamMdx': {**good['upstreamMdx'], field: value}}
            with self.assertRaisesRegex(ValueError, 'current MDX receipt'):
                VERIFY.verify_downstream_upstream(changed, hashes, SESSION)
        with self.assertRaisesRegex(ValueError, 'session-bound'):
            VERIFY.verify_downstream_upstream(good, hashes, None)

    def test_environment_nonce_is_lower_hex_and_bounded(self):
        with patch.dict('os.environ', {'LIGHTFORGE_EVIDENCE_SESSION': SESSION}, clear=False):
            self.assertEqual(VERIFY.current_evidence_session(), SESSION)
        for invalid in ['bad session', 'a' * 31, 'A' * 64, 'g' * 64]:
            with patch.dict('os.environ', {'LIGHTFORGE_EVIDENCE_SESSION': invalid}, clear=False):
                with self.assertRaisesRegex(ValueError, 'Invalid LIGHTFORGE_EVIDENCE_SESSION'):
                    VERIFY.current_evidence_session()

    def test_new_producers_overwrite_a_stale_pass_before_invalid_setup(self):
        producers = {
            'qa/release-2.2.4/test-source-clock.cjs': 'source-clock-verification.json',
            'qa/release-2.2.4/browser.cjs': 'browser-verification.json',
            'qa/release-2.2.4/analysis-browser.cjs': 'analysis-browser-verification.json',
        }
        environment = {**os.environ, 'LIGHTFORGE_EVIDENCE_SESSION': 'invalid session'}
        for relative, name in producers.items():
            output = ROOT / VERIFY.OUT / name
            original = output.read_bytes() if output.exists() else None
            try:
                output.write_text(json.dumps({'passed': True, 'errors': []}))
                completed = subprocess.run(['node', relative], cwd=ROOT, env=environment,
                                           text=True, capture_output=True, check=False)
                self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                receipt = json.loads(output.read_text())
                self.assertIs(receipt['passed'], False)
                self.assertTrue(receipt['errors'])
                self.assertIn('Invalid LIGHTFORGE_EVIDENCE_SESSION', receipt['errors'][0])
                self.assertEqual(list(output.parent.glob(output.name + '.*.tmp')), [])
            finally:
                if original is None:
                    output.unlink(missing_ok=True)
                else:
                    output.write_bytes(original)

    def test_producers_publish_failure_receipts_atomically_and_verifier_binds_all_session_receipts(self):
        mdx = (ROOT / 'qa/release-2.2.4/compare-native-mdx.py').read_text()
        downstream = (ROOT / 'qa/release-2.2.4/verify-mdx-downstream.cjs').read_text()
        self.assertIn('def write_atomic(path,value):', mdx)
        self.assertIn('os.replace(temporary,path)', mdx)
        self.assertIn("write_atomic(gate,receipt)", mdx)
        self.assertIn('function writeJsonAtomic(file,value)', downstream)
        self.assertIn('fs.renameSync(temporary,file)', downstream)
        self.assertIn('receipt.upstreamMdx=', downstream)
        self.assertIn('Upstream MDX receipt belongs to a different evidence session', downstream)

        for relative in ['test-source-clock.cjs', 'browser.cjs', 'analysis-browser.cjs']:
            producer = (ROOT / 'qa/release-2.2.4' / relative).read_text()
            self.assertIn("const EVIDENCE_SESSION_SCHEMA='lightforge.evidence-session.v1'", producer)
            self.assertIn('process.env.LIGHTFORGE_EVIDENCE_SESSION', producer)
            self.assertIn('function writeJsonAtomic(file,value)', producer)
            self.assertIn('fs.renameSync(temporary,file)', producer)
            self.assertIn('writeJsonAtomic(output,receipt)', producer)
            self.assertIn("source_hashes:{}", producer)
        browser = (ROOT / 'qa/release-2.2.4/browser.cjs').read_text()
        analysis_browser = (ROOT / 'qa/release-2.2.4/analysis-browser.cjs').read_text()
        self.assertIn('qa/release-1.6.0/actual-music-user-glass-prefix64-analysis.json', browser)
        self.assertIn('qa/release-1.6.0/fixtures/falcon-mix.wav', analysis_browser)

        verifier = (ROOT / 'qa/release-2.2.4/verify-analysis.py').read_text()
        self.assertIn('def verify_fresh_receipt(root, relative, hashes, session, label, sources):', verifier)
        self.assertIn('browser = verify_browser_receipt(root, hashes, evidence_session)', verifier)
        self.assertIn('analysis_browser = verify_analysis_browser_receipt(root, hashes, evidence_session)', verifier)
        self.assertIn("receipt['session_evidence_receipts']", verifier)
        self.assertIn("'native_profile_equivalence'", verifier)
        self.assertIn("write_atomic(output, {'release': '2.2.4', 'passed': False, 'errors': []})", verifier)

    def test_workflow_orders_all_session_evidence_before_final_verifier(self):
        workflow = (ROOT / '.github/workflows/verify-v2.yml').read_text()
        source_clock = workflow.index('test-source-clock.cjs')
        browser = workflow.index('browser.cjs')
        analysis_browser = workflow.index('analysis-browser.cjs')
        native = workflow.index('name: Regenerate and verify same-session native evidence')
        end = workflow.index('      - name:', native + 1)
        block = workflow[native:end]
        self.assertIn('test -n "$LIGHTFORGE_EVIDENCE_SESSION"', block)
        self.assertLess(source_clock, browser)
        self.assertLess(browser, analysis_browser)
        self.assertLess(analysis_browser, native)
        self.assertLess(block.index('compare-native-mdx.py'), block.index('verify-mdx-downstream.cjs'))
        self.assertLess(block.index('verify-mdx-downstream.cjs'), block.index('verify-native-inference-profile.py'))
        self.assertLess(block.index('verify-native-inference-profile.py'), block.index('verify-analysis.py'))


if __name__ == '__main__':
    main()

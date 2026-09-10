"""Fail-closed session binding tests for regenerated MDX/downstream evidence."""
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch
import tempfile

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

    def test_producers_publish_failure_receipts_atomically_and_downstream_binds_upstream(self):
        mdx = (ROOT / 'qa/release-2.2.4/compare-native-mdx.py').read_text()
        downstream = (ROOT / 'qa/release-2.2.4/verify-mdx-downstream.cjs').read_text()
        self.assertIn('def write_atomic(path,value):', mdx)
        self.assertIn('os.replace(temporary,path)', mdx)
        self.assertIn("write_atomic(gate,receipt)", mdx)
        self.assertIn('function writeJsonAtomic(file,value)', downstream)
        self.assertIn('fs.renameSync(temporary,file)', downstream)
        self.assertIn('receipt.upstreamMdx=', downstream)
        self.assertIn('Upstream MDX receipt belongs to a different evidence session', downstream)

    def test_workflow_generates_and_verifies_all_dynamic_receipts_in_one_nonce_bearing_step(self):
        workflow = (ROOT / '.github/workflows/verify-v2.yml').read_text()
        start = workflow.index('name: Regenerate and verify same-session native evidence')
        end = workflow.index('      - name:', start + 1)
        block = workflow[start:end]
        self.assertIn('test -n "$LIGHTFORGE_EVIDENCE_SESSION"', block)
        self.assertLess(block.index('compare-native-mdx.py'), block.index('verify-mdx-downstream.cjs'))
        self.assertLess(block.index('verify-mdx-downstream.cjs'), block.index('verify-native-inference-profile.py'))
        self.assertLess(block.index('verify-native-inference-profile.py'), block.index('verify-analysis.py'))


if __name__ == '__main__':
    main()

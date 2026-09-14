"""Release 2.2.5 source-only QA protocol guards."""
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location('lightforge_verify_analysis_2_2_5',
                               ROOT / 'qa/release-2.2.5/verify-analysis.py')
VERIFY = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)

SESSION = 'a' * 64
OTHER_SESSION = 'b' * 64


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


class Release225QaProtocolTest(TestCase):
    def write_receipt(self, root, relative, sources, session=SESSION):
        hashes = {}
        for source_relative in sources:
            source = root / source_relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('bound source: ' + source_relative + '\n')
            hashes[source_relative] = digest(source)
        receipt = root / relative
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            'release': '2.2.5', 'passed': True, 'errors': [],
            'completedAt': '2026-09-14T00:00:00Z',
            'evidenceSessionSchema': VERIFY.EVIDENCE_SESSION_SCHEMA,
            'evidenceSession': session, 'source_hashes': hashes,
        }))
        return receipt

    def test_background_and_restore_receipts_reject_stale_nonce_and_changed_source(self):
        cases = [
            (VERIFY.OUT + 'background-ui-verification.json', VERIFY.BACKGROUND_UI_SOURCES,
             VERIFY.verify_background_ui_receipt),
            (VERIFY.OUT + 'restore-preview-verification.json', VERIFY.RESTORE_PREVIEW_SOURCES,
             VERIFY.verify_restore_preview_receipt),
        ]
        for relative, sources, verify in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt = self.write_receipt(root, relative, sources)
                hashes = {}
                self.assertTrue(verify(root, hashes, SESSION)['passed'])
                self.assertEqual(hashes[relative], digest(receipt))

                self.write_receipt(root, relative, sources, OTHER_SESSION)
                with self.assertRaisesRegex(ValueError, 'different evidence session'):
                    verify(root, {}, SESSION)

                receipt = self.write_receipt(root, relative, sources)
                stale = json.loads(receipt.read_text())
                stale.pop('evidenceSessionSchema')
                stale.pop('evidenceSession')
                receipt.write_text(json.dumps(stale))
                with self.assertRaisesRegex(ValueError, 'stale, absent'):
                    verify(root, {}, SESSION)

                self.write_receipt(root, relative, sources)
                changed = root / next(iter(sources))
                changed.write_text('changed after receipt\n')
                with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                    verify(root, {}, SESSION)

    def test_background_and_restore_producers_publish_invalid_session_failure_first(self):
        producers = [
            (ROOT / 'qa/release-2.2.5/background-ui.cjs',
             'LIGHTFORGE_BACKGROUND_UI_OUTPUT'),
            (ROOT / 'qa/restore-preview/browser.cjs',
             'LIGHTFORGE_RESTORE_QA_OUTPUT'),
        ]
        for script, output_var in producers:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                env = {**os.environ, 'LIGHTFORGE_EVIDENCE_SESSION': 'invalid session',
                       output_var: temporary}
                completed = subprocess.run(['node', str(script)], cwd=ROOT, env=env,
                                           text=True, capture_output=True, check=False)
                self.assertNotEqual(completed.returncode, 0,
                                    completed.stdout + completed.stderr)
                receipt_name = ('background-ui-verification.json'
                                if 'background-ui' in script.name
                                else 'restore-preview-verification.json')
                receipt = json.loads((Path(temporary) / receipt_name).read_text())
                self.assertIs(receipt['passed'], False)
                self.assertTrue(receipt['errors'])
                self.assertIn('Invalid LIGHTFORGE_EVIDENCE_SESSION', receipt['errors'][0])

    def test_workflow_runs_restore_proof_in_fresh_current_release_order(self):
        workflow = (ROOT / '.github/workflows/verify-v2.yml').read_text(encoding='utf-8')
        source_clock = workflow.index('test-source-clock.cjs')
        browser = workflow.index('node qa/release-${{ env.LIGHTFORGE_RELEASE }}/browser.cjs')
        background = workflow.index('node qa/release-${{ env.LIGHTFORGE_RELEASE }}/background-ui.cjs')
        restore_output = workflow.index('LIGHTFORGE_RESTORE_QA_OUTPUT="qa/release-$LIGHTFORGE_RELEASE"')
        restore = workflow.index('node qa/restore-preview/browser.cjs', restore_output)
        analysis_browser = workflow.index('node qa/release-${{ env.LIGHTFORGE_RELEASE }}/analysis-browser.cjs')
        native = workflow.index('name: Regenerate and verify same-session native evidence')
        final_analysis = workflow.index('verify-analysis.py', native)
        self.assertLess(source_clock, browser)
        self.assertLess(browser, background)
        self.assertLess(background, restore_output)
        self.assertLess(restore_output, restore)
        self.assertLess(restore, analysis_browser)
        self.assertLess(analysis_browser, native)
        self.assertLess(native, final_analysis)

    def test_protocol_preserves_immutable_historical_anchor_and_has_no_tracked_outputs(self):
        hashes = {}
        historical = VERIFY.verify_historical_comparison(ROOT, hashes)
        self.assertEqual(historical['release'], '2.2.4')
        self.assertEqual(set(hashes), {
            VERIFY.HISTORICAL_OUT + 'native-runtime-comparison-verification.json',
        })
        expected = {
            'README.md', 'NativeMdxComparisonMain.java', 'analysis-browser.cjs',
            'analysis-performance.cjs', 'background-ui.cjs', 'browser.cjs',
            'compare-mdx-wasm.cjs', 'compare-native-mdx.py', 'mdx-downstream-compare.cjs',
            'mdx_numeric.py', 'test-source-clock.cjs', 'verify-analysis.py',
            'verify-mdx-downstream.cjs', 'verify-native-inference-profile.py',
        }
        tracked = set(subprocess.check_output(
            ['git', 'ls-files', '--', VERIFY.OUT], cwd=ROOT, text=True).splitlines())
        self.assertEqual(tracked, {VERIFY.OUT + name for name in expected})


if __name__ == '__main__':
    main()

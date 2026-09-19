"""Current-release source-only QA protocol guards."""
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
import re
import sys
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / 'version.json').read_text())
RELEASE = VERSION['name']
TOOLS = ROOT / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
PACKAGE_SPEC = spec_from_file_location('lightforge_package_v2', TOOLS / 'package_v2.py')
PACKAGE = module_from_spec(PACKAGE_SPEC)
assert PACKAGE_SPEC.loader is not None
PACKAGE_SPEC.loader.exec_module(PACKAGE)
from verification_evidence_manifest import RECEIPTS as VERIFICATION_RECEIPTS
SPEC = spec_from_file_location('lightforge_verify_analysis_current',
                               ROOT / f'qa/release-{RELEASE}/verify-analysis.py')
VERIFY = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)

SESSION = 'a' * 64
OTHER_SESSION = 'b' * 64


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


class CurrentReleaseQaProtocolTest(TestCase):
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
            'release': RELEASE, 'passed': True, 'errors': [],
            'completedAt': '2026-09-14T00:00:00Z',
            'evidenceSessionSchema': VERIFY.EVIDENCE_SESSION_SCHEMA,
            'evidenceSession': session, 'source_hashes': hashes,
        }))
        return receipt

    def test_background_and_restore_receipts_reject_stale_nonce_and_changed_source(self):
        VERIFY.ensure_browser_source_inventory()
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
            (ROOT / f'qa/release-{RELEASE}/background-ui.cjs',
             'LIGHTFORGE_BACKGROUND_UI_OUTPUT'),
            (ROOT / 'qa/restore-preview/browser.cjs',
             'LIGHTFORGE_RESTORE_QA_OUTPUT'),
        ]
        for script, output_var in producers:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                env = {**os.environ, 'LIGHTFORGE_EVIDENCE_SESSION': 'invalid session',
                       output_var: temporary}
                completed = subprocess.run(['node', str(script)], cwd=ROOT, env=env,
                                           text=True, capture_output=True, check=False, timeout=30)
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

    def test_restore_producer_uses_current_metadata_and_inventory_for_default_and_override_outputs(self):
        for release, code, override in ((RELEASE, VERSION['code'], False), ('9.8.7', 90807, True)):
            with self.subTest(release=release, override=override), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / 'qa/restore-preview/browser.cjs'
                script.parent.mkdir(parents=True)
                script.write_bytes((ROOT / 'qa/restore-preview/browser.cjs').read_bytes())
                (root / 'version.json').write_text(json.dumps({'name': release, 'code': code}))
                inventory_name = f'qa/release-{release}/browser-source-inventory.json'
                inventory_path = root / inventory_name
                inventory_path.parent.mkdir(parents=True)
                names = [inventory_name, 'version.json', 'qa/restore-preview/browser.cjs', 'source-marker.txt']
                inventory_path.write_text(json.dumps({
                    'schema': 'lightforge.browser-source-inventory.v1',
                    'common': [inventory_name], 'restore_preview': names[1:],
                }))
                (root / 'source-marker.txt').write_text('current release source\n')
                # An old inventory must never be selected just because it remains available.
                old_inventory = root / 'qa/release-2.2.5/browser-source-inventory.json'
                old_inventory.parent.mkdir(parents=True)
                old_inventory.write_text('{"schema":"stale inventory"}')
                playwright = root / 'node_modules/playwright/index.js'
                playwright.parent.mkdir(parents=True)
                playwright.write_text('throw new Error("fixture stop after source binding");\n')
                env = dict(os.environ, LIGHTFORGE_EVIDENCE_SESSION=SESSION)
                env.pop('LIGHTFORGE_RESTORE_QA_OUTPUT', None)
                output = root / 'override-output' if override else script.parent
                if override:
                    env['LIGHTFORGE_RESTORE_QA_OUTPUT'] = str(output)
                completed = subprocess.run(['node', str(script)], cwd=root, env=env,
                                           text=True, capture_output=True, check=False, timeout=30)
                self.assertNotEqual(completed.returncode, 0)
                receipt = json.loads((output / 'restore-preview-verification.json').read_text())
                self.assertEqual(receipt['release'], release)
                self.assertEqual(receipt['evidenceSession'], SESSION)
                self.assertEqual(receipt['evidenceSessionSchema'], VERIFY.EVIDENCE_SESSION_SCHEMA)
                self.assertEqual(receipt['source_hashes'], {name: digest(root / name) for name in names})
                self.assertIs(receipt['passed'], False)
                self.assertIn('fixture stop after source binding', receipt['errors'][0])
                for omitted in ('version.json', inventory_name):
                    with self.subTest(omitted=omitted):
                        inventory_path.write_text(json.dumps({
                            'schema': 'lightforge.browser-source-inventory.v1',
                            'common': [] if omitted == inventory_name else [inventory_name],
                            'restore_preview': [name for name in names[1:] if name != omitted],
                        }))
                        completed = subprocess.run(['node', str(script)], cwd=root, env=env,
                                                   text=True, capture_output=True, check=False, timeout=30)
                        self.assertNotEqual(completed.returncode, 0)
                        rejected = json.loads((output / 'restore-preview-verification.json').read_text())
                        self.assertIs(rejected['passed'], False)
                        self.assertEqual(rejected['source_hashes'], {})
                        self.assertIn('must bind its release metadata and inventory', rejected['errors'][0])

    def test_restore_producer_replaces_stale_pass_when_version_metadata_cannot_be_used(self):
        for document in (None, '{broken json', '{}', '{"name":"../../old-release"}'):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / 'qa/restore-preview/browser.cjs'
                script.parent.mkdir(parents=True)
                script.write_bytes((ROOT / 'qa/restore-preview/browser.cjs').read_bytes())
                if document is not None:
                    (root / 'version.json').write_text(document)
                receipt_path = script.parent / 'restore-preview-verification.json'
                receipt_path.write_text(json.dumps({'release': RELEASE, 'passed': True, 'errors': []}))
                env = dict(os.environ, LIGHTFORGE_EVIDENCE_SESSION=SESSION)
                env.pop('LIGHTFORGE_RESTORE_QA_OUTPUT', None)
                completed = subprocess.run(['node', str(script)], cwd=root, env=env,
                                           text=True, capture_output=True, check=False, timeout=30)
                self.assertNotEqual(completed.returncode, 0)
                receipt = json.loads(receipt_path.read_text())
                self.assertIs(receipt['passed'], False)
                self.assertIsNone(receipt['release'])
                self.assertTrue(receipt['errors'])
                self.assertEqual(receipt['source_hashes'], {})
                self.assertEqual(receipt['evidenceSession'], SESSION)

    def test_protocol_preserves_immutable_historical_anchor_and_has_no_tracked_outputs(self):
        hashes = {}
        historical = VERIFY.verify_historical_comparison(ROOT, hashes)
        self.assertEqual(historical['release'], '2.2.4')
        self.assertEqual(set(hashes), {
            VERIFY.HISTORICAL_OUT + 'native-runtime-comparison-verification.json',
        })
        expected = {
            'README.md', 'NativeMdxComparisonMain.java', 'analysis-browser.cjs',
            'analysis-performance.cjs', 'background-ui.cjs', 'browser.cjs', 'browser-source-inventory.json',
            'compare-mdx-wasm.cjs', 'compare-native-mdx.py', 'mdx-downstream-compare.cjs',
            'mdx_numeric.py', 'test-source-clock.cjs', 'verify-analysis.py',
            'verify-mdx-downstream.cjs', 'verify-native-inference-profile.py',
            'native_game_evidence.py', 'prepare-game-input.cjs', 'verify-native-game.py',
        }
        tracked = set(subprocess.check_output(
            ['git', 'ls-files', '--', VERIFY.OUT], cwd=ROOT, text=True).splitlines())
        self.assertEqual(tracked, {VERIFY.OUT + name for name in expected})

    def test_native_producers_publish_invalid_session_failure_first(self):
        cases = [
            ([sys.executable, str(ROOT / f'qa/release-{RELEASE}/compare-native-mdx.py')],
             ROOT / f'qa/release-{RELEASE}/native-mdx-comparison-verification.json'),
            (['node', str(ROOT / f'qa/release-{RELEASE}/verify-mdx-downstream.cjs')],
             ROOT / f'qa/release-{RELEASE}/native-mdx-downstream-verification.json'),
        ]
        for command, receipt_path in cases:
            with self.subTest(command=command[1]):
                prior = receipt_path.read_bytes() if receipt_path.exists() else None
                try:
                    receipt_path.write_text(json.dumps({'release': RELEASE, 'passed': True, 'errors': []}))
                    completed = subprocess.run(command, cwd=ROOT,
                                               env={**os.environ, 'LIGHTFORGE_EVIDENCE_SESSION': 'invalid session'},
                                               text=True, capture_output=True, check=False, timeout=30)
                    self.assertNotEqual(completed.returncode, 0,
                                        completed.stdout + completed.stderr)
                    receipt = json.loads(receipt_path.read_text())
                    self.assertIs(receipt['passed'], False)
                    self.assertTrue(receipt['errors'])
                    self.assertIn('Invalid LIGHTFORGE_EVIDENCE_SESSION', receipt['errors'][0])
                finally:
                    if prior is None:
                        receipt_path.unlink(missing_ok=True)
                    else:
                        receipt_path.write_bytes(prior)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'profile.json'
            output.write_text(json.dumps({'release': RELEASE, 'passed': True, 'errors': []}))
            completed = subprocess.run(
                [sys.executable, str(ROOT / f'qa/release-{RELEASE}/verify-native-inference-profile.py'),
                 '--output', str(output)],
                cwd=ROOT, env={**os.environ, 'LIGHTFORGE_EVIDENCE_SESSION': 'invalid session'},
                text=True, capture_output=True, check=False, timeout=30)
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            receipt = json.loads(output.read_text())
            self.assertIs(receipt['passed'], False)
            self.assertTrue(receipt['errors'])
            self.assertIn('LIGHTFORGE_EVIDENCE_SESSION is invalid.', receipt['errors'][0])

    def test_downstream_replaces_stale_pass_when_upstream_is_missing(self):
        downstream = ROOT / f'qa/release-{RELEASE}/native-mdx-downstream-verification.json'
        upstream = ROOT / f'qa/release-{RELEASE}/native-mdx-comparison-verification.json'
        previous_downstream = downstream.read_bytes() if downstream.exists() else None
        previous_upstream = upstream.read_bytes() if upstream.exists() else None
        try:
            downstream.write_text(json.dumps({'release': RELEASE, 'passed': True, 'errors': []}))
            upstream.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory() as temporary:
                pair = Path(temporary) / 'pair'
                pair.mkdir()
                for runtime in ('native', 'wasm'):
                    (pair / (runtime + '-waveform.float32le')).write_bytes(b'upstream-fixture')
                completed = subprocess.run(
                    ['node', str(ROOT / f'qa/release-{RELEASE}/verify-mdx-downstream.cjs')],
                    cwd=ROOT, env={
                        **os.environ,
                        'LIGHTFORGE_EVIDENCE_SESSION': SESSION,
                        'LIGHTFORGE_MDX_DOWNSTREAM_DIR': temporary,
                        'LIGHTFORGE_MDX_DOWNSTREAM_PAIR': str(pair),
                    }, text=True, capture_output=True, check=False, timeout=30)
            self.assertNotEqual(completed.returncode, 0,
                                completed.stdout + completed.stderr)
            receipt = json.loads(downstream.read_text())
            self.assertIs(receipt['passed'], False)
            self.assertTrue(receipt['errors'])
            self.assertIn('native-mdx-comparison-verification.json', receipt['errors'][0])
        finally:
            if previous_downstream is None:
                downstream.unlink(missing_ok=True)
            else:
                downstream.write_bytes(previous_downstream)
            if previous_upstream is None:
                upstream.unlink(missing_ok=True)
            else:
                upstream.write_bytes(previous_upstream)

    def test_browser_source_inventory_covers_loaded_runtime_closure(self):
        inventory = VERIFY.ensure_browser_source_inventory()
        common = set(inventory['common'])
        self.assertIn(VERIFY.BROWSER_SOURCE_INVENTORY_PATH, common)
        index = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        for reference in re.findall(r'<(?:script|link)\b[^>]+(?:src|href)=["\']([^"\']+)["\']', index):
            reference = reference.split('?', 1)[0]
            if reference.startswith(('http:', 'https:', '//', 'data:', '#')):
                continue
            self.assertIn((Path('web') / reference.lstrip('/')).as_posix(), common)
        styles = (ROOT / 'web/styles.css').read_text(encoding='utf-8')
        fonts = (ROOT / 'web/fonts/fonts.css').read_text(encoding='utf-8')
        self.assertIn('fonts/fonts.css', styles)
        self.assertIn('InterVariable.woff2', fonts)
        self.assertTrue({'web/fonts/fonts.css', 'web/fonts/InterVariable.woff2'} <= common)
        self.assertIn('web/engine/worker.js', common)
        for arguments in re.findall(r'importScripts\((.*?)\)', (ROOT / 'web/engine/worker.js').read_text(), flags=re.S):
            for name in re.findall(r'["\']([^"\']+)["\']', arguments):
                self.assertIn((ROOT / 'web/engine' / name).resolve().relative_to(ROOT.resolve()).as_posix(), common)
        analysis_covered = common | set(inventory['analysis_browser'])
        for arguments in re.findall(r'importScripts\((.*?)\)', (ROOT / 'web/analysis/worker.js').read_text(), flags=re.S):
            for name in re.findall(r'["\']([^"\']+)["\']', arguments):
                self.assertIn((ROOT / 'web/analysis' / name).resolve().relative_to(ROOT.resolve()).as_posix(), analysis_covered)
        preview = (ROOT / 'web/preview/vehicle-preview.js').read_text(encoding='utf-8')
        self.assertIn('preview/models/highland.glb', preview)
        self.assertIn('web/preview/models/highland.glb', common)
        for producer in [ROOT / f'qa/release-{RELEASE}/browser.cjs',
                         ROOT / f'qa/release-{RELEASE}/analysis-browser.cjs',
                         ROOT / f'qa/release-{RELEASE}/background-ui.cjs',
                         ROOT / 'qa/restore-preview/browser.cjs']:
            self.assertIn('browser-source-inventory.json', producer.read_text(encoding='utf-8'))

    def test_analysis_browser_observed_assets_are_manifest_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / 'web/analysis/models/example.onnx'
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b'bound asset')
            manifest = root / 'web/analysis/ASSET_MANIFEST.json'
            manifest.write_text(json.dumps({'models/example.onnx': {
                'bytes': asset.stat().st_size, 'sha256': digest(asset)}}))
            relative = 'web/analysis/models/example.onnx'
            observed = {'analysis_asset_hashes': {relative: digest(asset)}}
            hashes = {}
            VERIFY.verify_analysis_browser_assets(root, observed, hashes)
            self.assertEqual(hashes[relative], digest(asset))
            with self.assertRaisesRegex(ValueError, 'unapproved analysis asset'):
                VERIFY.verify_analysis_browser_assets(root, {
                    'analysis_asset_hashes': {'web/analysis/unlisted.bin': digest(asset)}}, {})
            asset.write_bytes(b'changed asset')
            with self.assertRaisesRegex(ValueError, 'Source differs from measured evidence'):
                VERIFY.verify_analysis_browser_assets(root, observed, {})

    def test_packager_requires_every_current_manifest_receipt(self):
        gates = PACKAGE.release_gate_names(VERSION)
        self.assertTrue(set(VERIFICATION_RECEIPTS) <= set(gates))
        self.assertIn('android-background-verification.json', gates)
        self.assertIn('android-diagnostics-verification.json', gates)

if __name__ == '__main__':
    main()

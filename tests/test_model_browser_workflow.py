"""Supplemental actual-model QA cannot become an unsigned release shortcut."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/model-browser-regression.yml').read_text()
PR_PATHS = re.findall(r"^      - '([^']+)'", WORKFLOW.split('  workflow_dispatch:', 1)[0], re.M)


def triggers_for(path):
    """Evaluate the ordered *, ** and negative patterns used by this workflow.

    This models a path in GitHub's cumulative PR diff, not the newest commit.
    The workflow intentionally does not claim per-commit run suppression.
    """
    included = False
    for rule in PR_PATHS:
        negative = rule.startswith('!')
        pattern = rule[1:] if negative else rule
        assert not any(token in pattern for token in '?[]+'), 'Unsupported test glob'
        expression = re.escape(pattern).replace(r'\*\*/', '(?:.*/)?').replace(r'\*\*', '.*').replace(r'\*', '[^/]*')
        if re.fullmatch(expression, path):
            included = not negative
    return included


def step(name):
    return WORKFLOW.split('      - name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]


def shell(name):
    return '\n'.join(line[10:] for line in step(name).split('        run: |\n', 1)[1].splitlines())


def python_block(marker):
    block = WORKFLOW.split("<<'" + marker + "'\n", 1)[1].split('\n          ' + marker, 1)[0]
    return '\n'.join(line[10:] for line in block.splitlines())


class ModelBrowserWorkflowTest(unittest.TestCase):
    def test_isolated_readonly_job_and_source_only_triggers(self):
        self.assertIn('permissions:\n  contents: read\n', WORKFLOW)
        self.assertEqual(WORKFLOW.count('runs-on:'), 1)
        self.assertIn('runs-on: ubuntu-latest', WORKFLOW)
        self.assertIn('timeout-minutes: 60', WORKFLOW)
        self.assertIn('group: model-browser-regression-${{ github.ref }}', WORKFLOW)
        self.assertIn('cancel-in-progress: true', WORKFLOW)
        triggers = WORKFLOW.split('permissions:', 1)[0]
        self.assertIn('  pull_request:\n', triggers)
        self.assertIn('    paths:', triggers)
        self.assertIn("- '!**/*.md'", triggers)
        self.assertNotIn("- 'docs/**'", triggers)
        for forbidden in ('pull_request_target', 'secrets.', 'self-hosted', 'build.sh',
                          'apksigner', 'candidate-manifest', 'verification_evidence_manifest',
                          'benchmark_deux_parallel.py', 'chmod', '/dev/kvm'):
            self.assertNotIn(forbidden, WORKFLOW)
        self.assertEqual(WORKFLOW.count('LIGHTFORGE_EVIDENCE_SESSION'), 1)
        self.assertIn('env -u LIGHTFORGE_EVIDENCE_SESSION node', WORKFLOW)

    def test_paths_cover_preparation_and_transitive_browser_inputs(self):
        required = (
            '.github/workflows/model-browser-regression.yml',
            '.github/workflows/verify-v2.yml',
            'tools/prepare_game.py', 'tools/prepare_deux.py',
            'tools/model_export_guard.py', 'tools/model-requirements.txt',
            'tools/verify_analysis_assets.py', 'tests/test_model_browser_workflow.py',
            'qa/release-1.6.0/prepare-musdb-fixtures.py',
            'qa/release-1.6.0/musdb-fixture-provenance.json',
            'research/evaluation-1.6/musdb-tracklist.csv',
            'research/upstream/deux/config.yaml',
            'research/upstream/deux/models/bs_roformer/attend.py',
            'research/upstream/deux/models/bs_roformer/mel_band_roformer.py',
            'package.json', 'package-lock.json', 'version.json',
            'web/analysis/models/deux/manifest.json', 'web/analysis/vendor/ort.wasm.min.js',
            'qa/release-9.9.9/analysis-browser.cjs',
            'qa/release-9.9.9/analysis-performance.cjs',
            'qa/release-9.9.9/browser-source-inventory.json',
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(triggers_for(path))
        # Read the actual current harness inventory rather than repeat only a
        # hand-maintained list. New source-bound inputs must get a trigger too.
        version = json.loads((ROOT / 'version.json').read_text())['name']
        inventory = json.loads((ROOT / f'qa/release-{version}/browser-source-inventory.json').read_text())
        for path in inventory['common'] + inventory['analysis_browser']:
            with self.subTest(inventory_path=path):
                self.assertTrue(triggers_for(path))
        assets = json.loads((ROOT / 'web/analysis/ASSET_MANIFEST.json').read_text())
        for name in assets:
            with self.subTest(asset=name):
                self.assertTrue(triggers_for('web/analysis/' + name))

    def test_unrelated_qa_verifier_tests_and_docs_do_not_match_paths(self):
        self.assertTrue(PR_PATHS)
        for broad in ('qa/**', 'tools/**', 'tests/**'):
            self.assertNotIn(broad, PR_PATHS)
        unrelated = (
            'tools/verify_inference_improvement.py', 'tools/benchmark_deux_parallel.py',
            'tools/verify_v2.py', 'tools/portable_inference_host.py',
            'tools/verify_preview_browser.cjs', 'tests/test_inference_improvement.py',
            'tests/test_portable_inference_qualification.py', 'tests/NativeDeuxParallelBenchmark.java',
            'tests/browser-diagnostic-capture.test.cjs',
            'qa/release-2.4.1/browser.cjs', 'qa/release-2.4.1/background-ui.cjs',
            'qa/restore-preview/browser.cjs', 'qa/release-2.4.1/browser-verification.json',
            'qa/release-2.4.1/analysis-browser-verification.json', 'qa/release-2.4.1/editor.png',
            '.github/workflows/restore-regression.yml', 'docs/ENGINEERING_COMPLETION_CHECKLIST.md',
            'web/README.md', 'research/upstream/deux/README.md', 'BUILD.md',
        )
        for path in unrelated:
            with self.subTest(path=path):
                self.assertFalse(triggers_for(path))
        self.assertIn('cumulative PR diff', WORKFLOW)

    def test_original_pins_and_integrity_are_reused_not_regenerated_baselines(self):
        for command in ('python-version: \'3.12.14\'', 'node-version: \'22\'',
                        'npm ci --ignore-scripts --no-audit --no-fund',
                        'python3 -m pip install pip==26.2.1 setuptools==83.0.0',
                        'python3 -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu',
                        'python3 -m pip install -r tools/model-requirements.txt',
                        'python3 tools/prepare_game.py', 'python3 tools/prepare_deux.py',
                        'python3 qa/release-1.6.0/prepare-musdb-fixtures.py',
                        '365f66acffc57282e474a4c24b32afec3678258c50b8d45646ac849b0a287df3'):
            self.assertIn(command, WORKFLOW)
            self.assertIn(command, (ROOT / '.github/workflows/verify-v2.yml').read_text())
        self.assertEqual(WORKFLOW.count('python3 tools/verify_analysis_assets.py'), 2)
        self.assertIn('id: model_assets', step('Reproduce unchanged original model assets'))
        self.assertIn("if: ${{ !cancelled() && steps.model_assets.outcome == 'success' }}",
                      step('Recheck unchanged model and source assets'))
        self.assertIn('git diff --exit-code -- web/analysis', WORKFLOW)
        self.assertIn('git diff --exit-code -- qa/release-1.6.0/musdb-fixture-provenance.json', WORKFLOW)
        self.assertLess(WORKFLOW.index('Invalidate any prior current diagnostic outputs'),
                        WORKFLOW.index('Reproduce unchanged original model assets'))
        self.assertNotIn('ASSET_MANIFEST.json\'', WORKFLOW)

    def test_external_deadline_and_bounded_upload_allowlist(self):
        run = step('Run unchanged actual-model browser harness with external deadline')
        self.assertIn('timeout-minutes: 32', run)
        self.assertIn('timeout --signal=TERM --kill-after=30s 30m', run)
        self.assertIn('tail -c 2097152', run)
        self.assertIn('set -o pipefail', run)
        self.assertIn('exit "$status"', run)
        upload = step('Retain supplemental model-browser diagnostics only')
        self.assertIn('if: always()', upload)
        paths = re.findall(r'^            (.+)$', upload, re.M)
        self.assertEqual(paths, ['${{ runner.temp }}/lightforge-model-browser/' + name for name in
            ('context.json', 'decoder-files.json', 'process.json', 'browser.log', 'analysis-browser-verification.json', 'actual-analysis-falcon.json')])
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', upload)
        self.assertIn('if: always()', step('Collect only bounded public-fixture diagnostics, including failures'))

    def test_decoder_setup_is_separately_bounded_without_changing_fixture(self):
        preflight = step('Check official decoder file identities before model setup')
        self.assertIn('set -o pipefail', preflight)
        self.assertIn('python3 tools/prepare_fixture_decoder.py --check-files', preflight)
        self.assertIn('tee "$RUNNER_TEMP/lightforge-model-browser/decoder-files.json"', preflight)
        self.assertNotIn('continue-on-error', preflight)
        self.assertLess(WORKFLOW.index('Check official decoder file identities before model setup'),
                        WORKFLOW.index('Reproduce unchanged original model assets'))
        decoder = step('Ensure official fixture decoder is available')
        self.assertIn('timeout-minutes: 15', decoder)
        self.assertIn('run: python3 tools/prepare_fixture_decoder.py', decoder)
        self.assertEqual(WORKFLOW.count('run: python3 tools/prepare_fixture_decoder.py\n'), 1)
        self.assertLess(WORKFLOW.index('Check official decoder file identities before model setup'),
                        WORKFLOW.index('Ensure official fixture decoder is available'))
        self.assertLess(WORKFLOW.index('Ensure official fixture decoder is available'),
                        WORKFLOW.index('Reproduce unchanged original model assets'))
        self.assertLess(WORKFLOW.index('Reproduce unchanged original model assets'),
                        WORKFLOW.index('Reproduce original licensed public reference fixture'))
        self.assertTrue(triggers_for('tools/prepare_fixture_decoder.py'))
        self.assertTrue(triggers_for('tests/test_fixture_decoder.py'))
        fixture = step('Reproduce original licensed public reference fixture')
        self.assertIn('timeout-minutes: 5', fixture)
        self.assertNotIn('apt-get', fixture)
        self.assertNotIn('continue-on-error', decoder + fixture)
        self.assertIn('curl -fL --retry 3 https://github.com/sigsep/sigsep-mus-db/releases/download/v0.4.0/MUSDB18-7-STEMS.zip', fixture)
        self.assertIn("echo '365f66acffc57282e474a4c24b32afec3678258c50b8d45646ac849b0a287df3  qa/release-1.6.0/fixtures/MUSDB18-7-STEMS.zip' | sha256sum -c", fixture)
        self.assertIn('python3 qa/release-1.6.0/prepare-musdb-fixtures.py', fixture)
        self.assertIn('git diff --exit-code -- qa/release-1.6.0/musdb-fixture-provenance.json', fixture)
        self.assertLess(WORKFLOW.index('Ensure official fixture decoder is available'),
                        WORKFLOW.index('Reproduce original licensed public reference fixture'))

    @unittest.skipUnless(shutil.which('bash'), 'The workflow requires bash')
    def test_file_identity_failure_is_retained_and_fails_the_early_step(self):
        with tempfile.TemporaryDirectory(prefix='decoder identity ') as directory:
            root = Path(directory)
            (root / 'lightforge-model-browser').mkdir()
            program = root / 'python3'
            program.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"scope":"synthetic","files":[]}\'\nexit 7\n')
            program.chmod(0o755)
            result = subprocess.run(['bash', '-c', shell('Check official decoder file identities before model setup')],
                env={**os.environ, 'RUNNER_TEMP': directory, 'PATH': str(root) + os.pathsep + os.environ['PATH']},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(json.loads((root / 'lightforge-model-browser/decoder-files.json').read_text()),
                             {'scope': 'synthetic', 'files': []})

    def inspect_capacity(self, cpu_count=4, memory_kib=12 * 1024**2, free_disk=12 * 1024**3):
        with tempfile.TemporaryDirectory() as directory:
            original = Path.read_text
            def read(path, *args, **kwargs):
                if str(path) == 'version.json':
                    return '{"name":"2.4.1"}'
                if str(path) == '/proc/meminfo':
                    return 'MemTotal: 16000000 kB\n' if memory_kib is None else f'MemAvailable: {memory_kib} kB\n'
                return original(path, *args, **kwargs)
            env = {'RUNNER_TEMP': directory, 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '2',
                   'GITHUB_ENV': str(Path(directory) / 'github-env')}
            with mock.patch.dict(os.environ, env), mock.patch.object(Path, 'read_text', read), \
                    mock.patch.object(os, 'sched_getaffinity', return_value=set(range(cpu_count)), create=True), \
                    mock.patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=free_disk)), \
                    mock.patch.object(subprocess, 'check_output', return_value='a' * 40 + '\n'), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    exec(compile(python_block('PYCONTEXT'), '<workflow-capacity>', 'exec'), {})
                except SystemExit:
                    pass
            return json.loads((Path(directory) / 'lightforge-model-browser/context.json').read_text())

    def test_actual_resource_observations_control_admission(self):
        record = self.inspect_capacity()
        self.assertTrue(record['eligible'])
        self.assertEqual(record['observations']['allowedCpuIds'], [0, 1, 2, 3])
        for values in ({'cpu_count': 1}, {'memory_kib': 1024}, {'free_disk': 1024}, {'memory_kib': None}):
            with self.subTest(values=values):
                record = self.inspect_capacity(**values)
                self.assertFalse(record['eligible'])
                self.assertTrue(record['errors'])
        self.assertNotIn('quota', python_block('PYCONTEXT').lower())

    def test_collection_preserves_failure_and_rejects_symlink_or_oversize(self):
        for mode in ('failed', 'symlink', 'oversize'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'qa/release-2.4.1/analysis-browser-verification.json'
                source.parent.mkdir(parents=True)
                if mode == 'symlink':
                    target = root / 'not-a-diagnostic'; target.write_text('must not upload')
                    source.symlink_to(target)
                elif mode == 'oversize':
                    with source.open('wb') as stream:
                        stream.truncate(8 * 1024**2 + 1)
                else:
                    source.write_text('{"passed":false,"errors":["incomplete"]}')
                env = {'RUNNER_TEMP': directory, 'LIGHTFORGE_RELEASE': '2.4.1'}
                with mock.patch.dict(os.environ, env), contextlib.chdir(root):
                    if mode == 'failed':
                        exec(compile(python_block('PYCOLLECT'), '<workflow-collect>', 'exec'), {})
                    else:
                        with self.assertRaises(SystemExit):
                            exec(compile(python_block('PYCOLLECT'), '<workflow-collect>', 'exec'), {})
                output = root / 'lightforge-model-browser' / source.name
                if mode == 'failed':
                    self.assertEqual(output.read_bytes(), source.read_bytes())
                else:
                    self.assertFalse(output.exists())
                self.assertTrue(source.exists())

    @unittest.skipUnless(shutil.which('bash') and shutil.which('timeout') and shutil.which('node'),
                         'The Linux workflow process tools are required')
    def test_external_timeout_and_failure_keep_false_receipt_and_capped_log(self):
        for mode in ('failure', 'timeout'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); qa = root / 'qa/release-2.4.1'; qa.mkdir(parents=True)
                diagnostics = root / 'lightforge-model-browser'; diagnostics.mkdir()
                program = "require('fs').writeFileSync(__dirname+'/analysis-browser-verification.json',JSON.stringify({passed:false}));"
                program += "process.stdout.write('x'.repeat(2200000),()=>process.exit(7));" if mode == 'failure' else "setInterval(()=>{},1000);"
                (qa / 'analysis-browser.cjs').write_text(program)
                script = shell('Run unchanged actual-model browser harness with external deadline')
                script = script.replace('--kill-after=30s 30m', '--kill-after=1s 0.5s' if mode == 'timeout' else '--kill-after=1s 10s')
                process = subprocess.run(['bash', '-c', script], cwd=root,
                    env={**os.environ, 'RUNNER_TEMP': directory, 'LIGHTFORGE_RELEASE': '2.4.1'},
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
                self.assertEqual(process.returncode, 124 if mode == 'timeout' else 7)
                record = json.loads((diagnostics / 'process.json').read_text())
                self.assertFalse(record['passed'])
                self.assertEqual(record['status'], 'timed-out' if mode == 'timeout' else 'failed')
                self.assertFalse(json.loads((qa / 'analysis-browser-verification.json').read_text())['passed'])
                self.assertLessEqual((diagnostics / 'browser.log').stat().st_size, 2097152)


if __name__ == '__main__':
    unittest.main()

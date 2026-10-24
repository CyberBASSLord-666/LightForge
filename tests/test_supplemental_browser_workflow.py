"""Desktop browser QA stays runnable without substituting for release evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/restore-regression.yml').read_text()


class SupplementalBrowserWorkflowTest(unittest.TestCase):
    def test_one_unprivileged_job_reuses_pinned_dependencies_and_browser(self):
        self.assertIn('runs-on: ubuntu-latest', WORKFLOW)
        self.assertIn('permissions:\n  contents: read', WORKFLOW)
        self.assertIn('    timeout-minutes: 25', WORKFLOW)
        self.assertEqual(WORKFLOW.count('runs-on:'), 1)
        self.assertEqual(WORKFLOW.count('run: npm ci --ignore-scripts'), 1)
        self.assertEqual(WORKFLOW.count('npx playwright install --with-deps chromium'), 1)
        self.assertNotIn('pull_request_target', WORKFLOW)
        self.assertNotIn('self-hosted', WORKFLOW)

    def test_current_version_is_read_before_browser_tests_and_artifacts(self):
        version_read = WORKFLOW.index('name: Read current release version')
        self.assertIn("version=json.load(open('version.json'))['name']", WORKFLOW)
        self.assertIn("assert len(version.split('.'))==3 and all(p.isdigit() for p in version.split('.'))", WORKFLOW)
        version = json.loads((ROOT / 'version.json').read_text())['name']
        for script in ('browser.cjs', 'background-ui.cjs'):
            command = 'node "qa/release-$LIGHTFORGE_RELEASE/' + script + '"'
            self.assertLess(version_read, WORKFLOW.index(command))
            self.assertTrue((ROOT / 'qa' / ('release-' + version) / script).is_file())
        self.assertNotIn('qa/release-2.4.1/', WORKFLOW)

    def test_all_four_suites_run_after_install_even_if_another_suite_fails(self):
        commands = (
            'node qa/restore-preview/browser.cjs',
            'node "qa/release-$LIGHTFORGE_RELEASE/browser.cjs"',
            'node "qa/release-$LIGHTFORGE_RELEASE/background-ui.cjs"',
            'node tools/verify_preview_browser.cjs',
        )
        for command in commands:
            with self.subTest(command=command):
                step = next(step for step in WORKFLOW.split('      - ') if 'run: ' + command in step)
                self.assertIn("if: ${{ !cancelled() && steps.chromium.outcome == 'success' }}", step)
                self.assertIn('timeout-minutes: 5', step)
                self.assertLess(WORKFLOW.index('id: chromium'), WORKFLOW.index(command))
        self.assertNotIn('continue-on-error', WORKFLOW)

    def test_generated_diagnostics_are_retained_without_sealing_production_evidence(self):
        artifact = WORKFLOW.split('name: Retain supplemental browser diagnostics', 1)[1].split('      - ', 1)[0]
        self.assertIn("if: ${{ always() && env.LIGHTFORGE_RELEASE != '' }}", artifact)
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', artifact)
        for filename in ('browser-verification.json', 'browser-export-project.json',
                         'background-ui-verification.json', 'preview-verification.json', '*.png'):
            self.assertIn('qa/release-${{ env.LIGHTFORGE_RELEASE }}/' + filename, artifact)
        self.assertIn('qa/restore-preview/*.json', WORKFLOW)
        self.assertIn('qa/restore-preview/*.png', WORKFLOW)
        self.assertIn('does not seal production evidence', WORKFLOW)
        for forbidden in ('LIGHTFORGE_EVIDENCE_SESSION', 'analysis-browser.cjs',
                          'benchmark_deux_parallel.py', 'seal_verification', 'build.sh'):
            self.assertNotIn(forbidden, WORKFLOW)

    def test_read_only_host_diagnostic_precedes_browser_work_and_retains_explicit_artifact(self):
        diagnostic = next(step for step in WORKFLOW.split('      - ') if 'id: host_diagnostic' in step)
        self.assertIn("subprocess.run(['python3', 'tools/portable_inference_host.py']", diagnostic)
        self.assertIn('timeout-minutes: 2', diagnostic)
        self.assertIn('check=False, timeout=30', diagnostic)
        self.assertIn("Path(os.environ['RUNNER_TEMP']) / 'lightforge-host-diagnostic'", diagnostic)
        self.assertLess(WORKFLOW.index('id: host_diagnostic'), WORKFLOW.index('run: npm ci'))
        self.assertLess(WORKFLOW.index('id: host_diagnostic'), WORKFLOW.index('id: chromium'))
        artifact = WORKFLOW.split('name: Retain read-only host diagnostic', 1)[1].split('      - ', 1)[0]
        self.assertIn("if: ${{ always() && steps.host_diagnostic.outcome != 'skipped' }}", artifact)
        self.assertIn('path: ${{ runner.temp }}/lightforge-host-diagnostic/runner-diagnostic.json', artifact)
        self.assertIn('name: lightforge-host-diagnostic-${{ github.run_id }}-${{ github.run_attempt }}', artifact)
        self.assertIn('if-no-files-found: error', artifact)
        for forbidden in ('sudo', 'chmod', 'cgcreate', 'taskset', 'sched_setaffinity',
                          'LIGHTFORGE_EVIDENCE_SESSION', 'continue-on-error'):
            self.assertNotIn(forbidden, diagnostic)

    @staticmethod
    def host_diagnostic_code():
        step = next(step for step in WORKFLOW.split('      - ') if 'id: host_diagnostic' in step)
        code = step.split("python3 - <<'PYHOST'\n", 1)[1].split('          PYHOST', 1)[0]
        return compile(textwrap.dedent(code), '<workflow-host-diagnostic>', 'exec')

    @staticmethod
    def diagnostic_record(eligible):
        return dict(schema='lightforge.experimental-portable-runner-diagnostic.v1', eligible=eligible,
                    qualificationEstablished=False, releaseAdmissible=False, fullQualificationEvidence=False,
                    reason='Eligible for observation only' if eligible else 'Observed host is ineligible')

    def exercise_diagnostic(self, raw, status, should_pass):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / 'summary.txt'
            def run(command, **options):
                self.assertEqual(command, ['python3', 'tools/portable_inference_host.py'])
                self.assertEqual(options['timeout'], 30)
                self.assertIs(options['check'], False)
                options['stdout'].write(raw)
                return SimpleNamespace(returncode=status)
            with mock.patch.dict(os.environ, RUNNER_TEMP=directory, GITHUB_STEP_SUMMARY=str(summary)), \
                    mock.patch.object(subprocess, 'run', side_effect=run) as process:
                if should_pass:
                    exec(self.host_diagnostic_code(), {'__name__': '__main__'})
                else:
                    with self.assertRaises((ValueError, SystemExit)):
                        exec(self.host_diagnostic_code(), {'__name__': '__main__'})
                process.assert_called_once()
            # A rejected/malformed diagnostic is not silently repaired or discarded.
            self.assertEqual((root / 'lightforge-host-diagnostic/runner-diagnostic.json').read_bytes(), raw)
            if should_pass:
                self.assertIn('INELIGIBLE' if status == 2 else 'ELIGIBLE', summary.read_text())
                self.assertIn('no inference, performance qualification, or release admission', summary.read_text())
            else:
                self.assertFalse(summary.exists())

    def test_host_diagnostic_accepts_only_actual_eligible_or_ineligible_status(self):
        for eligible in (False, True):
            with self.subTest(eligible=eligible):
                self.exercise_diagnostic(json.dumps(self.diagnostic_record(eligible)).encode(),
                                         0 if eligible else 2, True)

    def test_host_diagnostic_rejects_malformed_conflicting_or_admitted_observations(self):
        valid = self.diagnostic_record(False)
        cases = [(b'', 2), (b'not json', 2), (b'[]', 2), (b' ' * (1024 * 1024 + 1), 2),
                 (json.dumps(valid).encode(), 0), (json.dumps(valid).encode(), 1),
                 (json.dumps(valid).encode(), -9),
                 (json.dumps(valid).replace('"eligible": false', '"eligible": false, "eligible": true').encode(), 2),
                 (json.dumps(valid)[:-1].encode() + b', "unexpected": NaN}', 2)]
        for key, value in (('eligible', 0), ('eligible', 'false'), ('eligible', None),
                           ('qualificationEstablished', True), ('releaseAdmissible', True),
                           ('fullQualificationEvidence', True), ('releaseAdmissible', 0),
                           ('schema', 'unknown'), ('reason', ''), ('reason', None)):
            changed = copy.deepcopy(valid)
            changed[key] = value
            cases.append((json.dumps(changed).encode(), 2))
        for key in ('eligible', 'qualificationEstablished', 'releaseAdmissible', 'fullQualificationEvidence'):
            changed = copy.deepcopy(valid)
            del changed[key]
            cases.append((json.dumps(changed).encode(), 2))
        cases.append((json.dumps(self.diagnostic_record(True)).encode(), 2))
        for number, (raw, status) in enumerate(cases):
            with self.subTest(case=number, status=status):
                self.exercise_diagnostic(raw, status, False)

    def test_production_version_is_available_before_fail_closed_proof_replay(self):
        production = (ROOT / '.github/workflows/verify-v2.yml').read_text().split('\n  verify:', 1)[1].split('\n  android-background:', 1)[0]
        self.assertLess(production.index('name: Read current release version'),
                        production.index('name: Retrieve registered terminal proof'))
        self.assertLess(production.index('name: Retrieve registered terminal proof'),
                        production.index('run: npm ci'))


if __name__ == '__main__':
    unittest.main()

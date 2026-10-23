"""Desktop browser QA stays runnable without substituting for release evidence."""
import json
from pathlib import Path
import unittest


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

    def test_production_version_is_available_before_fail_closed_runner_preflight(self):
        production = (ROOT / '.github/workflows/verify-v2.yml').read_text().split('\n  android-background:', 1)[0]
        self.assertLess(production.index('name: Read current release version'),
                        production.index('name: Check controlled inference runner'))
        self.assertLess(production.index('name: Check controlled inference runner'),
                        production.index('run: npm ci'))


if __name__ == '__main__':
    unittest.main()

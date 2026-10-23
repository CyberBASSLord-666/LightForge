"""Fresh CI qualification and explicit fail-closed runner eligibility contracts."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'inference_preflight', ROOT / 'tools/inference_qualification_preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
WORKFLOW = (ROOT / '.github/workflows/verify-v2.yml').read_text()


class InferenceQualificationPreflightTest(unittest.TestCase):
    def setUp(self):
        self.controls = {'schema': 'test fixture; delegated CPU policy'}
        self.counters = {
            group: {name: 0 for name in names}
            for group, names in PREFLIGHT.REQUIRED_COUNTERS.items()
        }

    def inspect(self, counters=None, cpu_error=None, system='Linux', machine='x86_64'):
        with mock.patch.object(PREFLIGHT.platform, 'system', return_value=system), \
                mock.patch.object(PREFLIGHT.platform, 'machine', return_value=machine), \
                mock.patch.object(PREFLIGHT.benchmark, 'child_cpu_control',
                                  return_value=self.controls, side_effect=cpu_error) as control, \
                mock.patch.object(PREFLIGHT.benchmark.b, 'host_counters',
                                  return_value=self.counters if counters is None else counters), \
                mock.patch.object(PREFLIGHT.benchmark.os, 'sched_setaffinity') as set_affinity:
            record = PREFLIGHT.inspect_runner()
            set_affinity.assert_not_called()
            if system == 'Linux' and machine in {'x86_64', 'AMD64'}:
                control.assert_called_once_with()
            else:
                control.assert_not_called()
            return record

    def test_observed_runner_is_eligible_but_not_qualified(self):
        record = self.inspect()
        self.assertIs(record['eligible'], True)
        self.assertIs(record['qualificationEstablished'], False)
        self.assertEqual(record['hostControls'], self.controls)
        self.assertEqual(record['observedCounters'], self.counters)

    def test_missing_invalid_or_fabricated_zero_counters_are_rejected(self):
        for group, names in PREFLIGHT.REQUIRED_COUNTERS.items():
            for name in names:
                for value in (None, False, True, -1, '0', 0.0):
                    with self.subTest(group=group, name=name, value=value):
                        counters = copy.deepcopy(self.counters)
                        counters[group][name] = value
                        result = self.inspect(counters)
                        self.assertIs(result['eligible'], False)
                        self.assertIn(group + '.' + name, result['reason'])
                        self.assertIs(result['qualificationEstablished'], False)
            for value in (None, {}, [], 'unavailable'):
                with self.subTest(group=group, value=value):
                    counters = copy.deepcopy(self.counters)
                    counters[group] = value
                    self.assertIs(self.inspect(counters)['eligible'], False)

    def test_existing_cpu_policy_errors_are_not_reinterpreted(self):
        for error in (
                ValueError('Eight allowed CPUs are required to reserve platform headroom'),
                ValueError('A finite positive cgroup CPU quota is required'),
                ValueError('CPU quota does not permit seven child CPUs and one CPU of headroom'),
                FileNotFoundError('/sys/fs/cgroup/cpu.max')):
            with self.subTest(error=error):
                result = self.inspect(cpu_error=error)
                self.assertIs(result['eligible'], False)
                self.assertEqual(result['reason'], str(error))
                self.assertIn('Missing observations cannot be treated as zero', result['requiredRunner'])

    def test_unpinned_host_architecture_is_not_admitted(self):
        self.assertIs(self.inspect(system='Darwin')['eligible'], False)
        self.assertIs(self.inspect(machine='aarch64')['eligible'], False)


class InferenceQualificationWorkflowTest(unittest.TestCase):
    def test_custom_runner_selection_is_exactly_bounded(self):
        self.assertIn("runs-on: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' && github.ref_protected && vars.LIGHTFORGE_INFERENCE_RUNNER || github.event_name == 'workflow_dispatch' && inputs.inference_runner || 'ubuntu-latest' }}", WORKFLOW)
        self.assertIn('default: ubuntu-latest', WORKFLOW)
        self.assertNotIn('pull_request_target', WORKFLOW)
        self.assertEqual(WORKFLOW.count('vars.LIGHTFORGE_INFERENCE_RUNNER'), 1)

    def test_runner_expression_never_routes_untrusted_events_or_refs_to_configured_host(self):
        # Evaluate only the exactly asserted expression above, not arbitrary
        # repository input. GitHub's &&/|| choose the first truthy label.
        def select(event, ref, protected, configured='controlled-host', manual='manual-host'):
            return (event == 'push' and ref == 'refs/heads/main' and protected and configured
                    or event == 'workflow_dispatch' and manual or 'ubuntu-latest')

        for event in ('pull_request', 'pull_request_target', 'workflow_run', 'schedule'):
            for ref in ('refs/heads/main', 'refs/pull/56/merge', 'refs/heads/topic'):
                for protected in (True, False):
                    with self.subTest(event=event, ref=ref, protected=protected):
                        self.assertEqual(select(event, ref, protected), 'ubuntu-latest')
        for ref, protected in (('refs/heads/main', False), ('refs/heads/topic', True),
                               ('refs/heads/topic', False), ('refs/tags/main', True)):
            with self.subTest(ref=ref, protected=protected):
                self.assertEqual(select('push', ref, protected), 'ubuntu-latest')
        self.assertEqual(select('push', 'refs/heads/main', True), 'controlled-host')
        self.assertEqual(select('push', 'refs/heads/main', True, configured=''), 'ubuntu-latest')
        self.assertEqual(select('workflow_dispatch', 'refs/heads/topic', False), 'manual-host')

    def test_publisher_provenance_is_not_relaxed_for_manual_dispatch(self):
        prepare = (ROOT / '.github/workflows/prepare-release.yml').read_text()
        self.assertIn("run['event'] == 'push' and run['head_branch'] == 'main'", prepare)
        publish = (ROOT / '.github/workflows/publish-release.yml').read_text()
        self.assertEqual(publish.count('record.get("event") == "push"'), 2)
        self.assertEqual(publish.count('record.get("head_branch") == "main"'), 2)
        guide = (ROOT / 'BUILD.md').read_text()
        self.assertIn('**A manual run is not release-eligible**', guide)
        self.assertIn('No eligible configured runner has been verified', guide)

    def test_preflight_precedes_dependencies_and_does_not_allow_failure(self):
        preflight = WORKFLOW.index('name: Check controlled inference runner before expensive preparation')
        models = WORKFLOW.index('name: Reproduce bundled production models')
        self.assertLess(preflight, models)
        block = WORKFLOW[preflight:WORKFLOW.index('name: Retain runner preflight diagnostics')]
        self.assertIn('rm -f -- research/inference-current/production-parallel-qualification.json', block)
        self.assertIn('python3 tools/inference_qualification_preflight.py', block)
        self.assertNotIn('continue-on-error', block)
        self.assertNotIn('|| true', block)

    def test_fresh_qualification_runs_after_dependencies_before_build(self):
        qualification = WORKFLOW.index('name: Qualify fresh final-source full-passage inference before packaging')
        build = WORKFLOW.index('name: Build CI package with an ephemeral signing identity')
        block = WORKFLOW[qualification:WORKFLOW.index('name: Retain exact-source inference observations')]
        self.assertLess(WORKFLOW.index('python3 tools/bootstrap_testdeps.py'), qualification)
        self.assertLess(qualification, build)
        self.assertIn('python3 tools/inference_qualification_preflight.py', block)
        self.assertIn('python3 tools/benchmark_deux_parallel.py', block)
        self.assertIn('--output "$RUNNER_TEMP/lightforge-inference-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"', block)
        self.assertIn('--receipt research/inference-current/production-parallel-qualification.json', block)
        self.assertIn('python3 tools/verify_inference_improvement.py', block)
        self.assertLess(block.index('rm -f --'), block.index('python3 tools/benchmark_deux_parallel.py'))
        self.assertLess(block.index('python3 tools/benchmark_deux_parallel.py'), block.index('python3 tools/verify_inference_improvement.py'))
        self.assertNotIn('continue-on-error', block)
        self.assertNotIn('|| true', block)

    def test_failed_observations_are_retained_without_becoming_release_authority(self):
        start = WORKFLOW.index('name: Retain exact-source inference observations')
        block = WORKFLOW[start:WORKFLOW.index('name: Build CI package', start)]
        self.assertIn('if: always()', block)
        self.assertIn('not release evidence alone', block)
        self.assertIn('github.run_id', block)
        self.assertIn('github.run_attempt', block)
        self.assertIn('research/inference-current/production-parallel-qualification.json', block)
        self.assertNotIn('overwrite: true', block)
        self.assertNotIn('download-artifact', WORKFLOW[:start])


if __name__ == '__main__':
    unittest.main()

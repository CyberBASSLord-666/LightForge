"""Prospective host campaigns, exact proof replay and explicit runner lanes."""
import copy
import json
import os
import re
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
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
PRODUCER = WORKFLOW.split('\n  host-campaign:', 1)[1].split('\n  verify:', 1)[0]
CONSUMER = WORKFLOW.split('\n  verify:', 1)[1].split('\n  android-background:', 1)[0]
ROUTING = WORKFLOW.split('\n  host-routing:', 1)[1].split('\n  host-campaign:', 1)[0]


def step(text, name):
    return text.split('      - name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]


def assert_job_environment_contexts(text):
    # GitHub resolves job env before assigning a runner. Keep this targeted
    # context-availability guard independent of YAML's syntactic validity.
    # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
    allowed = {'github', 'needs', 'strategy', 'matrix', 'vars', 'secrets', 'inputs'}
    blocks = re.findall(r'(?ms)^    env:\n(.*?)(?=^ {0,4}\S|\Z)', text)
    for block in blocks:
        for expression in re.findall(r'\$\{\{(.*?)\}\}', block, flags=re.S):
            expression = re.sub(r"'(?:[^']|'')*'", "''", expression)
            contexts = set(re.findall(r'(?<![\w.])([A-Za-z_]\w*)\s*(?=[.\[])', expression))
            if contexts - allowed:
                raise AssertionError('Unavailable job-level environment context')


def inline_python(marker):
    block = WORKFLOW.split("<<'" + marker + "'\n", 1)[1].split('\n          ' + marker, 1)[0]
    return compile(textwrap.dedent(block), '<workflow-' + marker + '>', 'exec')



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


class BoundedInferenceQualificationPreflightTest(unittest.TestCase):
    def inspect(self, diagnostic):
        host = mock.Mock()
        host.diagnose.return_value = diagnostic
        with mock.patch.object(PREFLIGHT.benchmark, 'portable_host', return_value=host), \
                mock.patch.object(PREFLIGHT.benchmark, 'child_cpu_control') as legacy_control, \
                mock.patch.object(PREFLIGHT.benchmark.b, 'host_counters') as legacy_counters, \
                mock.patch.object(PREFLIGHT.benchmark.os, 'sched_setaffinity') as affinity_write:
            record = PREFLIGHT.inspect_runner(PREFLIGHT.BOUNDED_PROTOCOL)
            host.diagnose.assert_called_once_with()
            legacy_control.assert_not_called()
            legacy_counters.assert_not_called()
            affinity_write.assert_not_called()
        return record

    def test_explicit_bounded_lane_uses_full_ancestry_diagnostic_without_eight_cpu_gate(self):
        diagnostic = dict(eligible=True, qualificationEstablished=False,
                          releaseAdmissible=False, fullQualificationEvidence=False)
        record = self.inspect(diagnostic)
        self.assertTrue(record['eligible'])
        self.assertEqual(record['protocol'], 'bounded-four-worker-three-cpu-v1')
        self.assertFalse(record['qualificationEstablished'])
        self.assertFalse(record['releaseAdmissible'])
        self.assertEqual(record['hostDiagnostic'], diagnostic)

    def test_missing_or_hidden_ancestry_holds_without_fallback(self):
        diagnostic = dict(eligible=False, reason='Hidden ancestry cannot be qualified')
        record = self.inspect(diagnostic)
        self.assertFalse(record['eligible'])
        self.assertEqual(record['reason'], diagnostic['reason'])
        self.assertIn('three observed child CPUs', record['requiredRunner'])
        self.assertIn('Missing observations cannot be treated as zero', record['requiredRunner'])

    def test_unknown_and_old_experimental_lanes_do_not_silently_select_a_protocol(self):
        for lane in ('portable-four-worker-three-cpu-v1', '', None, 'auto'):
            with self.subTest(lane=lane), self.assertRaisesRegex(ValueError, 'Unknown inference'):
                PREFLIGHT.inspect_runner(lane)


class InferenceQualificationWorkflowTest(unittest.TestCase):
    def test_custom_runner_selection_is_exactly_bounded(self):
        self.assertIn("runs-on: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' && github.ref_protected && vars.LIGHTFORGE_INFERENCE_RUNNER || github.event_name == 'workflow_dispatch' && inputs.inference_runner || 'ubuntu-latest' }}", WORKFLOW)
        self.assertIn('default: ubuntu-latest', WORKFLOW)
        self.assertNotIn('pull_request_target', WORKFLOW)
        self.assertEqual(WORKFLOW.count('vars.LIGHTFORGE_INFERENCE_RUNNER'), 1)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main' && github.ref_protected", PRODUCER)

    def test_bounded_producer_pool_is_fixed_and_each_machine_still_requires_preflight(self):
        self.assertEqual(re.findall(r'^    runs-on: (.+)$', PRODUCER, re.M), ['ubuntu-latest'])
        self.assertNotIn('vars.', PRODUCER)
        self.assertNotIn('inputs.inference_runner', PRODUCER)
        preflight = step(PRODUCER, 'Check bounded campaign host before dependency preparation')
        self.assertIn('--protocol bounded-four-worker-three-cpu-v1', preflight)
        self.assertNotIn('continue-on-error', preflight)
        for path in ('BUILD.md', 'docs/EXPERIMENTAL_HOST_QUALIFICATION.md'):
            with self.subTest(path=path):
                guide = ' '.join((ROOT / path).read_text().split())
                self.assertIn('Every actual allocated machine must pass the full strict preflight.', guide)
                self.assertIn('not blanket eligibility for the pool', guide)

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
        self.assertIn('no passing campaign proof is asserted here', guide)

    def test_consumer_establishes_proof_before_dependencies_without_host_preflight(self):
        block = step(CONSUMER, 'Retrieve registered terminal proof before expensive preparation')
        self.assertLess(CONSUMER.index('Retrieve registered terminal proof'),
                        CONSUMER.index('Reproduce bundled production models'))
        self.assertIn('rm -f -- research/inference-current/production-parallel-qualification.json', block)
        self.assertIn('python3 tools/host_inference_campaign.py replay --root .', block)
        self.assertNotIn('inference_qualification_preflight.py', CONSUMER)
        self.assertNotIn('benchmark_deux_parallel.py', CONSUMER)
        self.assertNotIn('continue-on-error', block)
        self.assertNotIn('|| true', block)

    def test_fresh_candidate_admission_replays_after_dependencies_before_build(self):
        block = step(CONSUMER, 'Replay exact registered proof and seal fresh candidate host admission')
        start = CONSUMER.index('Replay exact registered proof and seal fresh candidate host admission')
        self.assertLess(CONSUMER.index('python3 tools/bootstrap_testdeps.py'), start)
        self.assertLess(start, CONSUMER.index('Build CI package with an ephemeral signing identity'))
        for option in ('--admission-output', '--prerequisite-output',
                       '--evidence-session "$LIGHTFORGE_EVIDENCE_SESSION"'):
            self.assertIn(option, block)
        self.assertIn('python3 tools/verify_inference_improvement.py', block)
        self.assertLess(block.index('rm -f --'), block.index('python3 tools/host_inference_campaign.py'))
        self.assertNotIn('continue-on-error', block)
        self.assertNotIn('|| true', block)

    def test_sealed_non_android_evidence_uses_the_exact_fresh_admission_output(self):
        replay = step(CONSUMER, 'Replay exact registered proof and seal fresh candidate host admission')
        seal = step(CONSUMER, 'Seal success-only non-Android verification evidence')
        generated = re.findall(r'--admission-output "([^"]+)"', replay)
        consumed = re.findall(r'--host-admission "([^"]+)"', seal)
        self.assertEqual(generated, ['$RUNNER_TEMP/lightforge-host-admission.json'])
        self.assertEqual(consumed, generated)
        self.assertIn('tools/verification_evidence_manifest.py write-content', seal)
        self.assertNotIn('if: always()', seal)

    def test_failed_observations_are_retained_without_becoming_release_authority(self):
        block = step(CONSUMER, 'Retain exact-source inference observations (not release evidence alone)')
        self.assertIn('if: always()', block)
        self.assertIn('github.run_id', block)
        self.assertIn('github.run_attempt', block)
        self.assertIn('research/inference-current/production-parallel-qualification.json', block)
        self.assertIn('lightforge-host-admission.json', block)
        self.assertNotIn('overwrite: true', block)

    def test_request_routing_is_readonly_and_preserves_already_running_producer(self):
        self.assertIn('host_inference_campaign.py route --root .', ROUTING)
        self.assertIn("('producer', 'producer-replay', 'consumer')", ROUTING)
        self.assertIn('cancel-in-progress: false', WORKFLOW)
        self.assertNotIn('cancel-in-progress: true', WORKFLOW)
        self.assertIn("needs.host-routing.outputs.mode == 'consumer'", CONSUMER)
        self.assertIn("needs.host-routing.outputs.mode == 'producer'", PRODUCER)
        self.assertIn("needs.host-routing.outputs.mode == 'producer-replay'", PRODUCER)
        for forbidden in ('benchmark_deux_parallel.py', 'git push', 'gh api', 'contents: write',
                          'actions: write', 'workflow_dispatch'):
            self.assertNotIn(forbidden, ROUTING)
        for forbidden in ('build.sh', 'npm test', 'prepare_game.py', 'android-background',
                          'LIGHTFORGE_EVIDENCE_SESSION', 'workflow_dispatch'):
            self.assertNotIn(forbidden, PRODUCER)

    def test_queued_request_replacement_caveat_is_documented_without_queue_changes(self):
        for path in ('BUILD.md', 'docs/EXPERIMENTAL_HOST_QUALIFICATION.md'):
            with self.subTest(path=path):
                guide = (ROOT / path).read_text()
                self.assertIn('no older main verification run', guide)
                self.assertIn('`host-campaign` job is running before', guide)
                self.assertIn('registration or unrelated pushes', guide)
                self.assertIn('single pending slot can replace a queued run', guide)
                self.assertIn('replaced/missing designated run', guide)
        self.assertIn('already-running producer, not a queued request run', WORKFLOW)
        self.assertNotIn('queue:', WORKFLOW)

    def test_campaign_preflight_compile_upload_registration_execute_are_strictly_ordered(self):
        names = (
            'Check bounded campaign host before dependency preparation',
            'Prepare only reviewed original campaign dependencies and model',
            'Compile and freeze declaration before zero warmups or timings',
            'Retain immutable prospective declaration only',
            'Wait read-only for exact prospective protected-main registration',
            'Execute the one registered original attempt without timing retries',
        )
        indices = [PRODUCER.index(name) for name in names]
        self.assertEqual(indices, sorted(indices))
        for name in names:
            block = step(PRODUCER, name)
            self.assertIn('if: ${{ github.run_attempt == 1 }}', block)
            self.assertNotIn('continue-on-error', block)
            self.assertNotIn('|| true', block)
        preflight = step(PRODUCER, names[0])
        self.assertIn('--protocol bounded-four-worker-three-cpu-v1', preflight)
        prepare = step(PRODUCER, names[2])
        execute = step(PRODUCER, names[5])
        self.assertIn('--phase prepare', prepare)
        self.assertNotIn('--phase execute', prepare)
        self.assertIn('--phase execute', execute)
        self.assertEqual(PRODUCER.count('tools/benchmark_deux_parallel.py'), 2)
        self.assertEqual(prepare.count('--output "$LIGHTFORGE_HOST_WORK"'), 1)
        self.assertEqual(execute.count('--output "$LIGHTFORGE_HOST_WORK"'), 1)
        self.assertNotIn('--retry', PRODUCER)

    def test_all_job_environment_expressions_use_available_contexts(self):
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            with self.subTest(workflow=path.name):
                assert_job_environment_contexts(path.read_text())
        for forbidden in ('runner.temp', "runner['temp']", 'steps.prepare.outputs.path',
                          'env.PATH', 'job.status'):
            with self.subTest(context=forbidden), self.assertRaises(AssertionError):
                assert_job_environment_contexts(
                    'jobs:\n  example:\n    env:\n      TEST: ${{ ' + forbidden + ' }}\n    steps: []\n')
        for allowed in ('github.run_id', 'needs.route.outputs.path', 'matrix.python',
                        'strategy.job-index', 'vars.MODE', 'secrets.TOKEN', 'inputs.name'):
            assert_job_environment_contexts(
                'jobs:\n  example:\n    env:\n      TEST: ${{ ' + allowed + ' }}\n    steps: []\n')

    def test_campaign_directory_is_initialized_on_runner_without_changing_namespace(self):
        initialize = step(PRODUCER, 'Initialize the original campaign attempt directory')
        self.assertIn('if: ${{ github.run_attempt == 1 }}', initialize)
        self.assertLess(PRODUCER.index('Initialize the original campaign attempt directory'),
                        PRODUCER.index('Check bounded campaign host before dependency preparation'))
        self.assertNotIn('LIGHTFORGE_HOST_WORK:', PRODUCER.split('    steps:', 1)[0])
        script = textwrap.dedent(initialize.split('        run: |\n', 1)[1])
        with tempfile.TemporaryDirectory(prefix='campaign path ') as directory:
            environment_file = Path(directory) / 'environment'
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], check=True,
                capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'RUNNER_TEMP': directory,
                    'GITHUB_RUN_ID': '123456', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ENV': str(environment_file)})
            self.assertEqual(environment_file.read_text(),
                'LIGHTFORGE_HOST_WORK=' + directory + '/lightforge-host-campaign-123456-1\n')
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ['environment'])

    def test_declaration_is_only_member_and_observations_never_overwrite(self):
        declaration = step(PRODUCER, 'Retain immutable prospective declaration only')
        proof = step(PRODUCER, 'Retain original campaign observations including failed attempts')
        self.assertIn('path: ${{ env.LIGHTFORGE_HOST_WORK }}/declaration.json', declaration)
        self.assertIn('host-inference-declaration-${{ env.LIGHTFORGE_HOST_CAMPAIGN }}-${{ github.run_id }}-${{ github.run_attempt }}', declaration)
        self.assertIn('host-inference-proof-${{ env.LIGHTFORGE_HOST_CAMPAIGN }}-${{ github.run_id }}-${{ github.run_attempt }}', proof)
        self.assertIn('always() && github.run_attempt == 1', proof)
        self.assertIn('path: ${{ env.LIGHTFORGE_HOST_WORK }}/', proof)
        self.assertNotIn('overwrite:', declaration + proof)
        self.assertEqual(declaration.count('retention-days: 90'), 1)
        self.assertEqual(proof.count('retention-days: 90'), 1)

    def test_rerun_retrieves_original_terminal_result_without_dependency_or_timing_steps(self):
        replay = step(PRODUCER, 'Reruns retrieve only the original terminal proof')
        self.assertIn('if: ${{ github.run_attempt != 1 }}', replay)
        self.assertIn('host_inference_campaign.py replay --root .', replay)
        self.assertNotIn('benchmark_deux_parallel.py', replay)
        self.assertNotIn('--admission-output', replay)
        self.assertLess(PRODUCER.index('Reruns retrieve only the original terminal proof'),
                        PRODUCER.index('Check bounded campaign host'))

    def exercise_registration_wait(self, results, clocks=(0, 1)):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'proof'
            work.mkdir()
            iterator = iter(results)
            def check(command, *, check, timeout):
                status, payload = next(iterator)
                self.assertEqual(command[:3], ['python3', 'tools/host_inference_campaign.py', 'check'])
                self.assertEqual(timeout, 300)
                self.assertFalse(check)
                Path(command[-1]).write_text(json.dumps(payload))
                return SimpleNamespace(returncode=status)
            with mock.patch.dict(os.environ, {'LIGHTFORGE_HOST_WORK': str(work), 'RUNNER_TEMP': directory}), \
                    mock.patch.object(subprocess, 'run', side_effect=check) as run, \
                    mock.patch('time.sleep') as sleep, \
                    mock.patch('time.monotonic', side_effect=clocks):
                error = None
                try:
                    exec(inline_python('PYREGISTRATION'), {})
                except SystemExit as caught:
                    error = caught
                return error, run.call_count, sleep.call_count

    def test_registration_wait_only_retries_explicit_absence(self):
        approved = (0, dict(measurementAuthorized=True, purpose='producer'))
        error, count, sleeps = self.exercise_registration_wait([approved])
        self.assertIsNone(error)
        self.assertEqual((count, sleeps), (1, 0))
        pending = (2, dict(status='awaiting-registration'))
        error, count, sleeps = self.exercise_registration_wait([pending, approved])
        self.assertIsNone(error)
        self.assertEqual((count, sleeps), (2, 1))
        for denied in ((2, dict(status='hold')), (3, dict(status='terminal-failure')),
                       (0, dict(measurementAuthorized=False, purpose='producer')),
                       (0, dict(measurementAuthorized=True, purpose='replay'))):
            with self.subTest(denied=denied):
                error, count, sleeps = self.exercise_registration_wait([denied])
                self.assertIsNotNone(error)
                self.assertEqual((count, sleeps), (1, 0))
        error, count, sleeps = self.exercise_registration_wait([pending], clocks=(0, 2701))
        self.assertIsNotNone(error)
        self.assertEqual((count, sleeps), (1, 0))

    def test_dynamic_current_release_and_existing_core_android_gates_remain(self):
        self.assertIn("version=json.load(open('version.json'))['name']", CONSUMER)
        for command in ('run: npm test', 'verify-native-inference-profile.py',
                        'analysis-browser.cjs', 'verify-native-game.py',
                        'tools/build_android_tests.py', 'tools/build_diagnostics_tests.py'):
            self.assertIn(command, CONSUMER)
        android = WORKFLOW.split('\n  android-background:', 1)[1]
        self.assertIn('needs: verify', android)
        self.assertIn('tools/run_android_background_tests.py', android)
        self.assertIn('tools/run_android_diagnostics_tests.py', android)


if __name__ == '__main__':
    unittest.main()

"""Full-source Deux collection retains the original clock and rejects invalid evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deux_source_cuda', ROOT / 'tools/benchmark_deux_source_cuda.py')
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


class DeuxSourceCudaTest(unittest.TestCase):
    def fixture(self, root, samples=44100, pcm=None):
        audio = root / 'public.wav'
        with wave.open(str(audio), 'wb') as stream:
            stream.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
            stream.writeframes(pcm if pcm is not None else struct.pack('<hh', 8192, -4096) * samples)
        provenance = dict(schema='lightforge.deux-source-input.v1', sampleRate=44100, sourceSamples=samples,
            audioSha256=source.sha(audio), sourceKind='synthetic', derivation='Synthetic source for collector validation only.')
        path = root / 'input.json'
        path.write_text(json.dumps(provenance))
        return audio, path, provenance

    def test_schedule_matches_production_clock_and_emission_boundaries(self):
        plan = source.passage_plan(64 * 44100)
        self.assertEqual(len(plan), 12)
        self.assertEqual([row['startSample'] for row in plan], [-66150 + 220500 * i for i in range(12)])
        self.assertEqual([row['emitSamples'] for row in plan], [220500] * 11 + [396900])
        self.assertEqual(sum(row['emitSamples'] for row in plan), 2822400)
        self.assertEqual(source.passage_plan(441000), [dict(index=0, startSample=-66150, outputOffset=0, emitSamples=441000)])
        self.assertEqual([row['emitSamples'] for row in source.passage_plan(441001)], [220500, 220501])
        self.assertEqual(source.passage_plan(1)[0]['emitSamples'], 1)
        for invalid in (0, True, 64 * 44100 + 1, 100.0):
            with self.assertRaises(ValueError):
                source.passage_plan(invalid)

    def test_stereo_reader_proof_preserves_channel_order_signed_pcm_and_padding(self):
        pcm = struct.pack('<hhhhhh', -32768, 32767, 0, -1, 8192, -4096)
        row = dict(startSample=-2)
        digest, peak = source.stereo_proof(pcm, row)
        left = [0, 0, -1, 0, .25]
        right = [0, 0, 32767 / 32768, -1 / 32768, -.125]
        expected = b''.join(struct.pack('<5f', *channel) + b'\0' * ((573300 - 5) * 4) for channel in (left, right))
        self.assertEqual(digest, hashlib.sha256(expected).hexdigest())
        self.assertEqual(peak, 1)
        cropped, _ = source.stereo_proof(pcm, dict(startSample=2))
        expected = b''.join(struct.pack('<f', value) + b'\0' * ((573300 - 1) * 4) for value in (.25, -.125))
        self.assertEqual(cropped, hashlib.sha256(expected).hexdigest())

    def test_complete_source_digest_and_last_passage_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio, path, provenance = self.fixture(root, 64 * 44100)
            _, original_plan = source.validate_input(audio, path)
            changed = bytearray(audio.read_bytes())
            changed[-2:] = struct.pack('<h', 16384)
            audio.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                source.validate_input(audio, path)
            path.write_text(json.dumps(dict(provenance, audioSha256=source.sha(audio))))
            _, changed_plan = source.validate_input(audio, path)
            self.assertEqual(original_plan[:-1], changed_plan[:-1])
            self.assertNotEqual(original_plan[-1]['inputStereoSha256'], changed_plan[-1]['inputStereoSha256'])

    def test_silence_private_source_wrong_clock_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio, path, provenance = self.fixture(root)
            for key, value in [('sourceSamples', 64 * 44100), ('sampleRate', True), ('sourceKind', 'private-audio'), ('derivation', '')]:
                path.write_text(json.dumps(dict(provenance, **{key: value})))
                with self.assertRaises(ValueError, msg=key):
                    source.validate_input(audio, path)
            path.write_text(json.dumps(provenance))
            alias = root / 'alias.wav'; alias.symlink_to(audio)
            with self.assertRaisesRegex(ValueError, 'regular'):
                source.validate_input(alias, path)
            audio, path, _ = self.fixture(root, 100, b'\0' * 400)
            with self.assertRaisesRegex(ValueError, 'Silent context'):
                source.validate_input(audio, path)

    def test_original_model_numeric_code_and_qualified_options_are_preserved(self):
        original = (source.accel.SOURCE / 'NativeDeux.java').read_text()
        self.assertEqual(source.source_snapshot(original, 'cpu_all', 'plain'), original)
        for variant in source.VARIANTS:
            qualified = source.accel.variant_source(original, variant)
            self.assertEqual(source.source_snapshot(original, variant, 'plain'), qualified)
            self.assertEqual(qualified.split('    private void run(', 1)[1], original.split('    private void run(', 1)[1])
            traces = Path('/tmp/deux-source-traces')
            maps = Path('/tmp/deux-source-maps') if variant == 'cuda_basic' else None
            expected = source.profiler.instrument_source(qualified, traces)
            if maps is not None:
                expected = source.accel.capture_library_maps(expected, maps)
            self.assertEqual(source.source_snapshot(original, variant, 'profiled', traces, maps), expected)
            self.assertNotIn('setDeterministicCompute', qualified)
        for args in [('cpu_all', 'profiled'), ('cuda_basic', 'profiled', Path('/tmp/traces')), ('cpu_all', 'plain', Path('/tmp/traces'))]:
            with self.assertRaises(ValueError):
                source.source_snapshot(original, *args)

    def test_observer_matrix_rejects_missing_duplicate_or_inexact_comparisons(self):
        plan = source.passage_plan(64 * 44100)
        rows = [dict(variant=variant, passageIndex=row['index'], byteIdentical=True)
                for variant in source.VARIANTS for row in plan]
        source.validate_observers(rows, plan)
        for invalid in (rows[:-1], rows[:-1] + [rows[0]]):
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                source.validate_observers(invalid, plan)
        for value in (False, None, 1):
            invalid = copy.deepcopy(rows); invalid[-1]['byteIdentical'] = value
            with self.assertRaises(source.accel.InvalidObserver):
                source.validate_observers(invalid, plan)

    def test_same_numeric_values_with_different_bits_still_fail_observer(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(source.benchmark, 'SAMPLES', 2):
            root = Path(directory)
            outputs = {'cpu_all': {}}
            for mode, value in [('plain', 0.0), ('profiled', -0.0)]:
                path = root / mode / 'passage-000'
                path.mkdir(parents=True)
                (path / 'stems.f32').write_bytes(struct.pack('<ff', value, 1))
                outputs['cpu_all'][mode] = path.parent
            rows = source.compare_observers(outputs, [dict(index=0)], ('cpu_all',))
            self.assertEqual(rows[0]['maximumAbsoluteError'], 0)
            self.assertFalse(rows[0]['byteIdentical'])
            self.assertFalse(rows[0]['qualityApproved'])
            self.assertIsNone(rows[0]['tolerance'])
            with self.assertRaises(source.accel.InvalidObserver):
                source.validate_observers(rows, [dict(index=0)], ('cpu_all',))

    def minimal_run(self, root):
        audio, _, provenance = self.fixture(root)
        plan = source.passage_plan(44100)
        plan[0]['inputStereoSha256'] = 'a' * 64
        output = root / 'run'; passage = output / 'passage-000'; passage.mkdir(parents=True)
        raw = passage / 'stems.f32'; raw.write_bytes(b'\0' * (2 * source.SAMPLES * 4))
        profile = passage / 'profile.txt'; profile.write_text('fixture checked separately')
        item = dict(schema='lightforge-deux-source-passage-1', **plan[0], sampleRate=44100, samplesPerStem=573300,
            sourceSamples=44100, sourceSha256=source.sha(audio), outputFile='passage-000/stems.f32',
            outputBytes=raw.stat().st_size, outputSha256=source.sha(raw), profileSha256=source.sha(profile),
            profiled=False, predictReturned=True, wallNanos=1, benchmarkTimingAdmitted=False)
        receipt = dict(schema='lightforge-deux-source-run-1', runtime='onnxruntime-java-1.25.1', sampleRate=44100,
            audioFrames=44100, audioSha256=source.sha(audio), modelFiles={}, profiled=False, engineObjects=1,
            engineCloseReturned=True, allPredictionsReturned=True, passageCount=1, wallNanos=1, passages=[item],
            qualityApproved=False, benchmarkTimingAdmitted=False, target75Proven=False, releaseAuthorized=False)
        return output, passage, provenance, plan, item, receipt

    def test_receipt_binds_raw_bytes_full_clock_and_completion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(source.benchmark, 'profile_fields'):
            output, passage, provenance, plan, item, receipt = self.minimal_run(Path(directory))
            def save():
                (passage / 'receipt.json').write_text(json.dumps(item))
                (output / 'receipt.json').write_text(json.dumps(receipt))
            save()
            source.validate_run(output, 'plain', provenance, plan, {'files': {}})
            for field, value in [('engineCloseReturned', False), ('audioFrames', 64 * 44100), ('passageCount', 12), ('qualityApproved', True)]:
                original = receipt[field]; receipt[field] = value; save()
                with self.assertRaises(ValueError, msg=field):
                    source.validate_run(output, 'plain', provenance, plan, {'files': {}})
                receipt[field] = original
            item['startSample'] = 0; save()
            with self.assertRaisesRegex(ValueError, 'source-bound'):
                source.validate_run(output, 'plain', provenance, plan, {'files': {}})
            item['startSample'] = -66150; save()
            raw = passage / 'stems.f32'
            with raw.open('r+b') as stream:
                stream.write(struct.pack('<f', 1))
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                source.validate_run(output, 'plain', provenance, plan, {'files': {}})

    def test_fresh_process_cleanup_occurs_after_success_timeout_and_interrupt(self):
        for failure in (None, subprocess.TimeoutExpired(['java'], 1), KeyboardInterrupt()):
            with tempfile.TemporaryDirectory() as directory, patch.object(source.subprocess, 'Popen') as popen, patch.object(source.os, 'killpg') as kill:
                process = popen.return_value
                process.pid = 1234
                process.wait.side_effect = [0 if failure is None else failure, 0]
                if failure is None:
                    source.run_process(['java'], Path(directory) / 'run.log', 1)
                else:
                    with self.assertRaises(type(failure)):
                        source.run_process(['java'], Path(directory) / 'run.log', 1)
                self.assertTrue(popen.call_args.kwargs['start_new_session'])
                kill.assert_called_once_with(1234, signal.SIGKILL)
                self.assertEqual(process.wait.call_count, 2)

    def test_observed_java_identity_binds_modules_and_rejects_other_major_version(self):
        with tempfile.TemporaryDirectory() as directory:
            jdk = Path(directory)
            for name in ('bin/java', 'bin/javac', 'bin/javap', 'lib/modules', 'lib/server/libjvm.so',
                         'lib/libjava.so', 'lib/libjli.so', 'release', 'conf/security/java.security'):
                path = jdk / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode())
            responses = [subprocess.CompletedProcess([], 0, text, '') for text in ('openjdk version "17.0.20.1"', 'javac 17.0.20.1', '17.0.20.1')]
            with patch.object(source.subprocess, 'run', side_effect=responses):
                identity, hashes = source.bind_java_identity(jdk / 'bin')
            self.assertEqual(len(hashes), 9)
            self.assertIn('lib/server/libjvm.so', identity['files'])
            source.verify_bound_files(hashes)
            (jdk / 'lib/modules').write_bytes(b'replaced compiler modules')
            with self.assertRaisesRegex(ValueError, 'changed'):
                source.verify_bound_files(hashes)
            with patch.object(source.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'openjdk version "21.0.1"', '')):
                with self.assertRaisesRegex(ValueError, 'Java 17'):
                    source.bind_java_identity(jdk / 'bin')

    def test_real_timeout_does_not_leave_a_live_child_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); child_path = root / 'child.pid'
            code = ('import pathlib,subprocess,sys,time; '
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]); '
                    'pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)')
            with self.assertRaises(subprocess.TimeoutExpired):
                source.run_process([sys.executable, '-c', code, str(child_path)], root / 'run.log', .4)
            self.assertTrue(child_path.is_file())
            child = Path('/proc') / child_path.read_text() / 'stat'
            # A killed descendant can briefly remain a zombie awaiting init's
            # reap. A live/sleeping process would reveal group-cleanup failure.
            if child.exists():
                self.assertEqual(child.read_text().split(') ', 1)[1][0], 'Z')

    def test_sigterm_writes_interrupted_receipt_and_retires_child_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = '''import importlib.util, pathlib, sys
spec=importlib.util.spec_from_file_location('collector',sys.argv[1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
root=pathlib.Path(sys.argv[2])
def exercise(args,receipt):
    child='import pathlib,os,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)'
    module.run_process([sys.executable,'-c',child,str(root/'child.pid')],root/'run.log',20)
module.execute=exercise
sys.argv=['collector','--models',str(root),'--audio',str(root/'unused.wav'),'--input-provenance',str(root/'unused.json'),'--output',str(root/'evidence')]
sys.exit(module.main())
'''
            with (root / 'outer.log').open('w') as log:
                outer = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'tools/benchmark_deux_source_cuda.py'), str(root)], stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while not (root / 'child.pid').exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue((root / 'child.pid').exists())
                    outer.terminate()
                    self.assertEqual(outer.wait(timeout=5), 130)
                    receipt = json.loads((root / 'evidence/receipt.json').read_text())
                    self.assertEqual(receipt['status'], 'BLOCKED_OR_REJECTED')
                    self.assertIn('KeyboardInterrupt', receipt['failure'])
                    child = Path('/proc') / (root / 'child.pid').read_text() / 'stat'
                    if child.exists():
                        self.assertEqual(child.read_text().split(') ', 1)[1][0], 'Z')
                finally:
                    if outer.poll() is None:
                        outer.kill(); outer.wait()


if __name__ == '__main__':
    unittest.main()

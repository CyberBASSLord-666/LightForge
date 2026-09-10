"""Fail-closed guards and report transport; no Android device or release key needed."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prepare_android_readiness_probe as pinned

# The runner intentionally owns its command-line/device session at module scope.
# Compile its actual pure guard/parser definitions without starting that session.
tree=ast.parse((ROOT/'tools/run_android_background_tests.py').read_text())
selected=[node for node in tree.body if isinstance(node,(ast.Import,ast.ImportFrom))
          or isinstance(node,(ast.FunctionDef,ast.ClassDef))
          and node.name in {'validate_observation_candidate','ReadinessObservationCapture'}]
namespace={}
exec(compile(ast.Module(body=selected,type_ignores=[]),str(ROOT/'tools/run_android_background_tests.py'),'exec'),namespace)
Capture=namespace['ReadinessObservationCapture']
validate=namespace['validate_observation_candidate']


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name)
        self.capture=Capture(self.folder)
        self.report=b'LIGHTFORGE DIAGNOSTIC REPORT\n'+('bounded trace \u2603\n'*5000).encode()+b'\nEND OF DIAGNOSTIC REPORT\n'

    def event(self,event):
        self.capture.observe('INSTRUMENTATION_STATUS: stream=LIGHTFORGE_NATIVE_REPORT '+json.dumps({'id':'readiness-failure',**event}))

    def chunks(self,data=None):
        data=self.report if data is None else data
        chunks=[data[i:i+32768] for i in range(0,len(data),32768)]
        for index,block in enumerate(chunks):
            self.event({'event':'chunk','index':index,'data':base64.b64encode(block).decode()})
        return len(chunks)

    def complete(self,data=None,**changes):
        data=self.report if data is None else data
        self.event({'event':'complete','bytes':len(data),'chunks':(len(data)+32767)//32768,
                    'sha256':hashlib.sha256(data).hexdigest(),'export':{'bytes':len(data)},**changes})

    def assert_rejected(self):
        summary=self.capture.finish()
        self.assertFalse(summary['nativeReport']['complete'])
        self.assertTrue(summary['errors'])
        self.assertFalse((self.folder/'android-readiness-native-report.txt').exists())

    def test_round_trip_and_failed_gate_remain_separate(self):
        failure={'passed':False,'limitSeconds':45,'error':'preview deadline'}
        observation={'diagnosticOnly':True,'originalGateFailed':True,'originalFailure':failure,'observedReady':True}
        self.capture.observe('LIGHTFORGE_READINESS_OBSERVATION '+json.dumps(observation))
        self.chunks();self.complete();summary=self.capture.finish()
        self.assertEqual((self.folder/'android-readiness-native-report.txt').read_bytes(),self.report)
        self.assertTrue(summary['nativeReport']['complete'])
        self.assertTrue(summary['originalGateFailed'])
        self.assertEqual(summary['originalFailure'],failure)
        self.assertFalse(summary['releaseEligible'])

    def test_incomplete_and_error_exports_never_publish(self):
        for error_event in [False,True]:
            with self.subTest(error=error_event):
                self.capture=Capture(self.folder);self.chunks()
                if error_event:self.event({'event':'error','error':'export deadline'})
                self.assert_rejected()

    def test_corrupt_completion_counts_hash_and_export_bytes(self):
        for changes in [{'bytes':3},{'chunks':0},{'sha256':'0'*64},{'export':{'bytes':1}}]:
            with self.subTest(changes=changes):
                self.capture=Capture(self.folder);self.chunks();self.complete(**changes);self.assert_rejected()

    def test_duplicate_missing_and_out_of_order_chunks(self):
        for index in [1,-1,True]:
            with self.subTest(index=index):
                self.capture=Capture(self.folder)
                self.event({'event':'chunk','index':index,'data':'eA=='})
                self.assert_rejected()
        self.capture=Capture(self.folder)
        for _ in range(2):self.event({'event':'chunk','index':0,'data':'eA=='})
        self.assert_rejected()

    def test_invalid_base64_and_size_limits(self):
        for encoded in ['%%%',base64.b64encode(b'x'*32769).decode()]:
            with self.subTest(length=len(encoded)):
                self.capture=Capture(self.folder)
                self.event({'event':'chunk','index':0,'data':encoded});self.assert_rejected()
        self.capture=Capture(self.folder)
        for index in range(65):self.event({'event':'chunk','index':index,'data':base64.b64encode(b'x'*32768).decode()})
        self.assert_rejected()

    def test_hash_valid_truncation_and_non_utf8_are_rejected(self):
        for data in [self.report[:-10],b'not a diagnostic report',
                     b'LIGHTFORGE DIAGNOSTIC REPORT\n\xff\nEND OF DIAGNOSTIC REPORT\n']:
            with self.subTest(length=len(data)):
                self.capture=Capture(self.folder);self.chunks(data);self.complete(data);self.assert_rejected()

    def test_post_completion_data_invalidates_report_and_old_files_are_removed(self):
        (self.folder/'android-readiness-native-report.txt').write_text('old report')
        self.capture=Capture(self.folder)
        self.assertFalse((self.folder/'android-readiness-native-report.txt').exists())
        self.chunks();self.complete();self.complete();self.assert_rejected()

    def test_original_failure_is_immutable(self):
        for message in ['original','changed']:
            self.capture.observe('LIGHTFORGE_READINESS_OBSERVATION '+json.dumps({
                'diagnosticOnly':True,'originalGateFailed':True,'originalFailure':{'error':message}}))
        self.assertEqual(self.capture.original_failure,{'error':'original'})
        self.assertTrue(self.capture.finish()['errors'])

    def test_observation_must_match_original_gate_marker_in_either_order(self):
        for gate_first in [True,False]:
            with self.subTest(gate_first=gate_first):
                self.capture=Capture(self.folder)
                if gate_first:self.capture.bind_gate_failure({'error':'original gate'})
                self.capture.observe('LIGHTFORGE_READINESS_OBSERVATION '+json.dumps({
                    'diagnosticOnly':True,'originalGateFailed':True,'originalFailure':{'error':'different'}}))
                if not gate_first:self.capture.bind_gate_failure({'error':'original gate'})
                self.assertTrue(self.capture.finish()['errors'])


class CandidateGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        for folder in ['candidate','diagnostic-input','tools']:(self.root/folder).mkdir()
        patches={}
        for name in pinned.PATCH_PATHS:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('reviewed '+name)
            patches[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest={'diagnostic_only':True,'base_head_sha':pinned.HEAD_SHA,
                  'base_apk_sha256':pinned.APK_SHA256,'reviewed_web_sha256':patches}
        text=json.dumps(manifest)
        (self.root/'tools/android-readiness-patch.json').write_text(text)
        (self.root/'diagnostic-input/reviewed-web-patch.json').write_text(text)
        self.apk=self.root/'candidate/LightForge-2.2.4.apk';self.apk.write_bytes(b'exact verified fixture bytes')
        self.metadata={'diagnostic_only':True,'release_eligible':False,'update_compatible':False,
            'input_ci_sha256':pinned.APK_SHA256,'input_ci_head_sha':pinned.HEAD_SHA,
            'patched_web_sha256':patches,'version_name':'2.2.4','version_code':20204,
            'signature':'verified','alignment':'passed','zip_integrity':'passed',
            'signing_certificate_sha256':'a'*64,'bytes':self.apk.stat().st_size,
            'sha256':hashlib.sha256(self.apk.read_bytes()).hexdigest()}
        self.provenance={'diagnostic_only':True,'release_eligible':False,'input_run_id':pinned.RUN_ID,
            'input_head_sha':pinned.HEAD_SHA,'input_job_id':pinned.JOB_ID,'input_job_conclusion':'success',
            'input_artifact_id':pinned.ARTIFACT_ID,'input_artifact_sha256':pinned.ARTIFACT_SHA256,
            'input_run_conclusion':'failure','signing_key_destroyed':True,
            'input_apk':{'sha256':pinned.APK_SHA256,'bytes':pinned.APK_BYTES,
                         'signing_certificate_sha256':pinned.CI_CERTIFICATE},
            'patched_web_sha256':patches,'patched_payload_entries':3,'unchanged_payload_entries':124,
            'reviewed_patch_manifest_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'diagnostic_apk':dict(self.metadata)}
        self.write()

    def write(self):
        self.apk.with_suffix('.apk.json').write_text(json.dumps(self.metadata))
        (self.root/'diagnostic-input/provenance.json').write_text(json.dumps(self.provenance))

    def test_exact_verified_diagnostic_is_accepted_despite_original_android_failure(self):
        self.assertTrue(validate(self.root,'2.2.4')['enabled'])

    def test_release_package_and_unverified_inputs_are_rejected(self):
        for key,value in [('diagnostic_only',False),('release_eligible',True)]:
            with self.subTest(key=key):
                original=self.metadata[key];self.metadata[key]=value;self.write()
                with self.assertRaises(RuntimeError):validate(self.root,'2.2.4')
                self.metadata[key]=original
        self.provenance['input_head_sha']='0'*40;self.write()
        with self.assertRaises(RuntimeError):validate(self.root,'2.2.4')

    def test_changed_apk_and_reviewed_sources_are_rejected(self):
        self.apk.write_bytes(b'changed candidate')
        with self.assertRaises(RuntimeError):validate(self.root,'2.2.4')
        self.apk.write_bytes(b'exact verified fixture bytes')
        (self.root/'web/app.js').write_text('unreviewed edit')
        with self.assertRaises(RuntimeError):validate(self.root,'2.2.4')


if __name__=='__main__':unittest.main()

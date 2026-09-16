"""Exercise local archive replay using genuine worker snapshots of synthetic music."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evaluate_show_archive', ROOT/'tools/evaluate_show_archive.py')
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def profile(stage, restored):
    return {'schemaVersion':1,'kind':'analysis-stage-profile','stage':stage,'totalWallClockMs':250 if restored else 1000,
            'timing':{'source':'performance.now','state':'available'},'attributes':{'performanceProbeVersion':1},
            'spanSummaryCoverage':{'namesComplete':True,'omittedSpanCount':0},
            'spanSummary':{'performance.model_inference':{'count':1,'totalMs':750,'maxMs':750}} if not restored else {},
            'cache':[{'domain':stage,'outcome':'restore' if restored else 'miss'}]}


@unittest.skipUnless(shutil.which('node'), 'Node is required to exercise the production compiler')
class EvaluateShowArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='lightforge-archive-test-')
        target = Path(cls.fixture.name)
        music = {'duration':4,'bpm':120,'beatConfidence':.95,'analysisVersion':5,
                 'beats':[index*.5 for index in range(8)],'downbeats':[0,2],'waveform':[.8],
                 'sections':[{'start':0,'end':4,'energy':.8}],
                 'vocals':{'available':True,'presence':'detected','confidence':.95,
                           'source':'separated-vocals','sourceSeparated':True,
                           'phrases':[{'start':1.113,'end':3,'confidence':.95,'strength':.8}],
                           'accents':[{'time':2.137,'confidence':.95,'strength':.8,'source':'separated-vocals'}]},
                 'bassNotes':[{'start':1.221,'end':2,'confidence':.95,'strength':.8,'midi':36}],
                 'bassAnalysis':{'confidence':.95},
                 'engine':{'analysisSeconds':2.5,'resourceDiagnostics':{'totalWallClockMs':2500},
                           'separationModel':{'analysisSeconds':90,'restoredPassages':0},
                           'stages':{name:{'restored':index<2,'seconds':0 if index<2 else 1,'profile':profile(name,index<2)}
                                     for index,name in enumerate(('rhythm','separation','voice','bass'))}}}
        (target/'music.json').write_text(json.dumps(music))
        script = r'''
const fs=require('node:fs'),path=require('node:path');
const run=require('./tests/worker-harness.cjs');
(async()=>{
 const output=process.argv[1],music=JSON.parse(fs.readFileSync(path.join(output,'music.json'))),settings={dance:'off',stepMs:15,seed:2025};
 const result=await run(path.resolve('web/engine'),{action:'generate',music,settings});
 fs.writeFileSync(path.join(output,'project.json'),JSON.stringify({version:1,name:'Synthetic fixture',music,settings,compiled:result.compiled}));
 fs.writeFileSync(path.join(output,'show.fseq'),Buffer.concat([Buffer.from(result.header),Buffer.from(result.show.frames)]));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node','-e',script,str(target)],cwd=ROOT,check=True,capture_output=True,text=True)
        audio = io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(44100)
            wav.writeframes(b'\x00'*(4*44100*4))
        fseq = (target/'show.fseq').read_bytes()
        cls.members = {TOOL.PROJECT:(target/'project.json').read_bytes(), TOOL.FSEQ:fseq, TOOL.AUDIO:audio.getvalue(),
                       TOOL.VALIDATION:json.dumps({'nativeChecks':{'sha256':hashlib.sha256(fseq).hexdigest()}}).encode()}

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lightforge-archive-case-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def make_archive(self, members=None, extras=(), compression=zipfile.ZIP_DEFLATED):
        archive = self.root/'input.zip'
        with zipfile.ZipFile(archive,'w',compression=compression) as output:
            for name,data in (self.members if members is None else members).items(): output.writestr(name,data)
            for name,data in extras: output.writestr(name,data)
        return archive

    def test_actual_worker_replay_is_exact_and_timings_do_not_claim_cold_speedup(self):
        archive = self.make_archive()
        original = archive.read_bytes()
        result = TOOL.evaluate_archive(archive)
        replay = result['projectEvaluation']['replay']
        self.assertTrue(result['integrityPassed']); self.assertTrue(replay['framesEqualSavedProject']); self.assertTrue(replay['fseqEqualArchive'])
        self.assertEqual(replay['changedFrameBytes'],0)
        self.assertEqual(result['audio']['samplesPerChannel'],176400)
        sync = result['projectEvaluation']['synchronization']['current']['report']
        self.assertGreater(sync['selected'],0)
        self.assertGreater(sync['roles']['vocals']['matched'],0)
        self.assertGreater(sync['roles']['bass']['matched'],0)
        self.assertLessEqual(sync['maxErrorMs'],7.5)
        self.assertFalse(result['evidenceBoundary']['audioGroundTruthAvailable'])
        self.assertFalse(result['evidenceBoundary']['freshModelInferencePerformed'])
        timing = result['savedAnalysisTiming']
        self.assertEqual(timing['executionClassification'],'restored-or-resumed')
        self.assertEqual(timing['reportedPipelineWallSeconds'],2.5)
        self.assertEqual(timing['separationModelHistoricalSeconds'],90)
        self.assertEqual(timing['stages']['rhythm']['observedWallSeconds'],.25)
        self.assertEqual(timing['stages']['rhythm']['declaredSeconds'],0)
        self.assertIsNone(timing['speedupPercent']); self.assertFalse(timing['coldStartVerified'])
        self.assertEqual(archive.read_bytes(),original)
        self.assertIn('web/engine/show-engine.js',result['projectEvaluation']['source']['fileSHA256'])

    def test_tampered_edits_are_rejected_by_real_snapshot_restore(self):
        members = dict(self.members); project = json.loads(members[TOOL.PROJECT]); project['settings']['seed'] = 666
        members[TOOL.PROJECT] = json.dumps(project).encode()
        with self.assertRaisesRegex(ValueError,'does not match its music and edits'):
            TOOL.evaluate_archive(self.make_archive(members))

    def test_changed_export_payload_cannot_pass_integrity(self):
        members = dict(self.members); fseq = bytearray(members[TOOL.FSEQ]); offset = struct.unpack_from('<H',fseq,4)[0]; fseq[offset] = 255
        members[TOOL.FSEQ] = bytes(fseq)
        result = TOOL.evaluate_archive(self.make_archive(members))
        self.assertFalse(result['integrityPassed'])
        self.assertFalse(result['projectEvaluation']['archive']['payloadMatchesSavedProject'])
        self.assertFalse(result['savedValidationFseqSHA256Matches'])

    def test_producer_header_difference_is_separate_from_frame_difference(self):
        members = dict(self.members); fseq = members[TOOL.FSEQ].replace(b'LightForge ',b'OtherForge ',1)
        members[TOOL.FSEQ] = fseq
        members[TOOL.VALIDATION] = json.dumps({'nativeChecks':{'sha256':hashlib.sha256(fseq).hexdigest()}}).encode()
        result = TOOL.evaluate_archive(self.make_archive(members))
        self.assertTrue(result['integrityPassed'])
        self.assertTrue(result['projectEvaluation']['replay']['framesEqualSavedProject'])
        self.assertFalse(result['projectEvaluation']['replay']['fseqEqualArchive'])

    def test_missing_audio_truncated_wav_and_duplicate_json_fail(self):
        cases = []
        missing = dict(self.members); del missing[TOOL.AUDIO]; cases.append(missing)
        short = dict(self.members); short[TOOL.AUDIO] = short[TOOL.AUDIO][:-1]; cases.append(short)
        duplicate = dict(self.members); duplicate[TOOL.PROJECT] = b'{"version":1,' + duplicate[TOOL.PROJECT][1:]; cases.append(duplicate)
        for members in cases:
            with self.subTest(kind=len(members.get(TOOL.AUDIO,b''))):
                with self.assertRaises((ValueError,wave.Error)):
                    TOOL.evaluate_archive(self.make_archive(members))

    def test_unsafe_paths_duplicate_entries_links_and_bombs_fail_before_staging(self):
        for name in ('../escape','/absolute','Review/../escape','Review\\escape','Review//escape','Review/C:drive'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,'Unsafe'):
                TOOL.evaluate_archive(self.make_archive(extras=[(name,b'bad')]))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            archive = self.make_archive(extras=[(TOOL.FSEQ,b'duplicate')])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            TOOL.evaluate_archive(archive)
        symlink = zipfile.ZipInfo('linked'); symlink.create_system = 3; symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError,'links or special'):
            TOOL.evaluate_archive(self.make_archive(extras=[(symlink,b'/tmp/target')]))
        archive = self.make_archive()
        with self.assertRaisesRegex(ValueError,'size limit'):
            TOOL.evaluate_archive(archive,max_total_bytes=archive.stat().st_size+4096)

    def test_crc_corruption_and_bad_fseq_header_fail(self):
        archive = self.make_archive(compression=zipfile.ZIP_STORED)
        corrupted = bytearray(archive.read_bytes()); offset = corrupted.index(b'RIFF'); corrupted[offset] ^= 1; archive.write_bytes(corrupted)
        with self.assertRaises(zipfile.BadZipFile): TOOL.evaluate_archive(archive)
        members = dict(self.members); fseq = bytearray(members[TOOL.FSEQ]); fseq[20] = 1; members[TOOL.FSEQ] = bytes(fseq)
        with self.assertRaisesRegex(ValueError,'Compressed, sparse or flagged'):
            TOOL.evaluate_archive(self.make_archive(members))

    def test_json_member_cap_is_case_insensitive_and_precedes_payload_reads(self):
        # Keep the test small while leaving all required JSON below the cap.
        cap = max(len(data) for name,data in self.members.items() if name.endswith('.json')) + 16
        for suffix in ('.json','.JSON','.JsOn'):
            with self.subTest(suffix=suffix):
                archive = self.make_archive(extras=[('Review/payload'+suffix,b'x'*(cap+1))])
                with mock.patch.object(TOOL,'MAX_JSON_BYTES',cap), \
                     mock.patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('Oversized JSON reached payload reads')):
                    with self.assertRaisesRegex(ValueError,'Archive member exceeds size limit'):
                        TOOL.evaluate_archive(archive)

    def test_high_bit_signature_and_metadata_codes_cannot_alias_valid_ascii(self):
        second_field = 32 + struct.unpack_from('<H',self.members[TOOL.FSEQ],32)[0]
        cases = [(offset,'Invalid FSEQ signature/header') for offset in range(4)]
        cases += [(offset,'Invalid FSEQ variable-header code')
                  for offset in (34,35,second_field+2,second_field+3)]
        for offset,message in cases:
            with self.subTest(offset=offset):
                members = dict(self.members)
                # No historical checksum is required by the format. Raw header
                # validation must reject corruption independently of that file.
                del members[TOOL.VALIDATION]
                fseq = bytearray(members[TOOL.FSEQ]); fseq[offset] |= 0x80
                members[TOOL.FSEQ] = bytes(fseq)
                with self.assertRaisesRegex(ValueError,message):
                    TOOL.evaluate_archive(self.make_archive(members))

    def test_source_bounds_and_special_files_fail_before_hashing(self):
        oversized = self.root/'oversized.bin'; oversized.write_bytes(b'x'*17)
        empty = self.root/'empty.bin'; empty.touch()
        directory = self.root/'directory'; directory.mkdir()
        cases = [(oversized,16),(empty,16),(directory,16)]
        if hasattr(os,'mkfifo'):
            fifo = self.root/'pipe'; os.mkfifo(fifo); cases.append((fifo,16))
        with mock.patch.object(TOOL,'digest_file',side_effect=AssertionError('Invalid source reached hashing')):
            for source,budget in cases:
                with self.subTest(source=source.name), self.assertRaisesRegex(ValueError,'size or type'):
                    TOOL.evaluate_archive(source,max_total_bytes=budget)

    def test_oversized_numeric_metadata_is_unavailable_or_cleanly_rejected(self):
        huge = 10**1000
        self.assertIsNone(TOOL.number(huge))
        self.assertIsNone(TOOL.number(-huge))
        model = {'analysisSeconds':huge,'resourceDiagnostics':{'totalWallClockMs':huge},
                 'separationModel':{'analysisSeconds':huge}}
        result = TOOL.saved_timings({'music':{'engine':model}})
        for field in ('reportedPipelineWallSeconds','declaredAnalysisSeconds','separationModelHistoricalSeconds'):
            self.assertIsNone(result[field])
        for field in ('wall','inference'):
            with self.subTest(field=field):
                measured = profile('voice',False)
                if field == 'wall': measured['totalWallClockMs'] = huge
                else: measured['spanSummary']['performance.model_inference']['totalMs'] = huge
                model['stages'] = {'voice':{'restored':False,'profile':measured}}
                with self.assertRaisesRegex(ValueError,'out-of-range number'):
                    TOOL.saved_timings({'music':{'engine':model}})

    def test_absent_timing_is_unavailable_not_zero_or_cold(self):
        result = TOOL.saved_timings({'music':{}})
        self.assertEqual(result['executionClassification'],'cache-state-unknown')
        self.assertIsNone(result['reportedPipelineWallSeconds'])
        self.assertIsNone(result['stages']['voice']['observedWallSeconds'])
        self.assertFalse(result['coldStartVerified'])

    def test_restore_count_requires_reported_positive_value(self):
        for complete_stages in (False,True):
            for count in (None,0,3):
                with self.subTest(complete_stages=complete_stages,count=count):
                    model = {'separationModel':{}}
                    if count is not None:
                        model['separationModel']['restoredPassages'] = count
                    if complete_stages:
                        model['stages'] = {name:{'restored':False,'profile':profile(name,False)}
                                           for name in ('rhythm','separation','voice','bass')}
                    result = TOOL.saved_timings({'music':{'engine':model}})
                    expected = 'restored-or-resumed' if count else 'no-stage-restores-reported' if complete_stages else 'cache-state-unknown'
                    self.assertEqual(result['executionClassification'],expected)
                    self.assertEqual(result['separationRestoredPassages'],count)
                    self.assertFalse(result['coldStartVerified'])
        # Independent stage evidence still establishes restoration with a zero
        # passage count; the two forms of cache evidence are not interchangeable.
        model = {'separationModel':{'restoredPassages':0},
                 'stages':{'rhythm':{'restored':True,'profile':profile('rhythm',True)}}}
        self.assertEqual(TOOL.saved_timings({'music':{'engine':model}})['executionClassification'],'restored-or-resumed')

    def test_cli_refuses_overwrite_and_repo_output(self):
        archive = self.make_archive(); output = self.root/'existing.json'; output.write_text('keep')
        for target in (output, ROOT/'private-user-evidence.json'):
            completed = subprocess.run(['python3',str(ROOT/'tools/evaluate_show_archive.py'),'--archive',str(archive),'--output',str(target)],capture_output=True,text=True)
            self.assertEqual(completed.returncode,1)
        self.assertEqual(output.read_text(),'keep')
        self.assertFalse((ROOT/'private-user-evidence.json').exists())


if __name__ == '__main__':
    unittest.main()

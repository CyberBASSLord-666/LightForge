#!/usr/bin/env python3
"""Install CI APKs and retain a source-bound Android background lifecycle receipt."""
import argparse,base64,datetime,hashlib,json,os,re,selectors,subprocess,time
from pathlib import Path

def validate_observation_candidate(root, release):
    """Enable extra observation only for the exact, verified diagnostic package."""
    from prepare_android_readiness_probe import (APK_BYTES, APK_SHA256, ARTIFACT_ID,
        ARTIFACT_SHA256, CI_CERTIFICATE, HEAD_SHA, JOB_ID, PATCH_PATHS, RUN_ID)
    from package_release import SIGNING_SHA256
    def require(value, message):
        if not value:raise RuntimeError('Readiness observation guard: '+message)
    def digest(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    apk=root/'candidate'/('LightForge-'+release+'.apk')
    metadata=json.loads(apk.with_suffix('.apk.json').read_text())
    provenance=json.loads((root/'diagnostic-input/provenance.json').read_text())
    manifest_path=root/'tools/android-readiness-patch.json'
    manifest=json.loads(manifest_path.read_text())
    require(release=='2.2.4' and metadata.get('diagnostic_only') is True
            and metadata.get('release_eligible') is False and metadata.get('update_compatible') is False,
            'candidate is not an explicitly ineligible diagnostic APK')
    require(provenance.get('diagnostic_only') is True and provenance.get('release_eligible') is False
            and provenance.get('input_run_id')==RUN_ID and provenance.get('input_head_sha')==HEAD_SHA
            and provenance.get('input_job_id')==JOB_ID and provenance.get('input_job_conclusion')=='success'
            and provenance.get('input_artifact_id')==ARTIFACT_ID
            and provenance.get('input_artifact_sha256')==ARTIFACT_SHA256
            and provenance.get('signing_key_destroyed') is True,
            'verified input provenance is missing or differs from the pinned build')
    original=provenance.get('input_apk',{})
    require(original.get('sha256')==APK_SHA256 and original.get('bytes')==APK_BYTES
            and original.get('signing_certificate_sha256')==CI_CERTIFICATE
            and metadata.get('input_ci_sha256')==APK_SHA256 and metadata.get('input_ci_head_sha')==HEAD_SHA,
            'base APK identity differs from the verified input')
    patches=manifest.get('reviewed_web_sha256',{})
    require(manifest.get('diagnostic_only') is True and manifest.get('base_head_sha')==HEAD_SHA
            and manifest.get('base_apk_sha256')==APK_SHA256 and set(patches)==PATCH_PATHS
            and patches==metadata.get('patched_web_sha256')==provenance.get('patched_web_sha256')
            and provenance.get('patched_payload_entries')==3
            and provenance.get('unchanged_payload_entries',0)>0
            and provenance.get('reviewed_patch_manifest_sha256')==digest(manifest_path)
            and digest(root/'diagnostic-input/reviewed-web-patch.json')==digest(manifest_path),
            'reviewed web patch provenance is incomplete')
    require(all(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value)
                and (root/name).is_file() and not (root/name).is_symlink()
                and digest(root/name)==value for name,value in patches.items()),
            'current web sources differ from the reviewed patches')
    require(provenance.get('diagnostic_apk')==metadata
            and metadata.get('version_name')==release and metadata.get('version_code')==20204
            and all(metadata.get(key)==value for key,value in
                    [('signature','verified'),('alignment','passed'),('zip_integrity','passed')])
            and re.fullmatch('[0-9a-f]{64}',metadata.get('signing_certificate_sha256',''))
            and metadata['signing_certificate_sha256'] not in (CI_CERTIFICATE,SIGNING_SHA256)
            and apk.stat().st_size==metadata.get('bytes') and digest(apk)==metadata.get('sha256'),
            'installed candidate bytes or metadata differ from the verified diagnostic APK')
    return {'enabled':True,'diagnosticOnly':True,'releaseEligible':False,
            'candidate':metadata,'provenanceSHA256':digest(root/'diagnostic-input/provenance.json')}


class ReadinessObservationCapture:
    """Keep post-failure evidence separate; reconstruct only a complete bounded report."""
    MAX_BYTES=2*1024*1024
    MAX_CHUNK=32768
    def __init__(self, directory):
        self.directory=directory
        self.original_gate_failed=False
        self.original_failure=None
        self.gate_failure=None
        self.events=[]
        self.errors=[]
        self.data=bytearray()
        self.chunks=0
        self.report_seen=False
        self.report_invalid=False
        self.report_complete=None
        self.finished=False
        # A previous invocation must never masquerade as this run's report.
        for name in ['android-readiness-native-report.txt','android-readiness-native-report.json',
                     'android-readiness-observation.json']:
            (directory/name).unlink(missing_ok=True)

    def error(self, message, report=False):
        if len(self.errors)<16:self.errors.append(str(message)[:1000])
        if report:
            self.report_invalid=True
            self.data.clear()
            (self.directory/'android-readiness-native-report.txt').unlink(missing_ok=True)

    def bind_gate_failure(self, failure):
        if self.gate_failure is not None and self.gate_failure!=failure:
            self.error('Original gate marker changed during observation')
            return
        self.gate_failure=failure
        if self.original_failure is not None and self.original_failure!=failure:
            self.error('Observation failure differs from the original gate marker')

    def observe(self, line):
        observation='LIGHTFORGE_READINESS_OBSERVATION '
        native='LIGHTFORGE_NATIVE_REPORT '
        marker=observation if observation in line else native if native in line else None
        if marker is None:return
        try:
            value=json.loads(line.split(marker,1)[1])
            if not isinstance(value,dict):raise ValueError('Diagnostic marker is not an object')
            if marker==observation:
                if value.get('diagnosticOnly') is not True or value.get('originalGateFailed') is not True:
                    raise ValueError('Observation did not retain the failed original gate')
                self.original_gate_failed=True
                failure=value.get('originalFailure')
                if not isinstance(failure,dict):raise ValueError('Original readiness failure is missing')
                if self.gate_failure is not None and failure!=self.gate_failure:
                    raise ValueError('Observation failure differs from the original gate marker')
                if self.original_failure is not None and failure!=self.original_failure:
                    raise ValueError('Original readiness failure changed during observation')
                self.original_failure=failure
                if len(self.events)>=128 or len(line)>65536:raise ValueError('Observation evidence exceeds its bound')
                self.events.append(value)
                self.save()
                return
            self.report_seen=True
            if self.report_invalid:return
            if value.get('id')!='readiness-failure':raise ValueError('Unexpected native report identity')
            if self.report_complete is not None:raise ValueError('Native report continued after completion')
            event=value.get('event')
            if event=='error':raise ValueError('Native report export failed: '+str(value.get('error',value.get('message','unspecified error'))))
            if event=='chunk':
                if type(value.get('index')) is not int or value['index']!=self.chunks:
                    raise ValueError('Native report chunk is missing, duplicate or out of order')
                encoded=value.get('data')
                if not isinstance(encoded,str) or len(encoded)>4*((self.MAX_CHUNK+2)//3):
                    raise ValueError('Native report chunk exceeds its bound')
                block=base64.b64decode(encoded,validate=True)
                if not 0<len(block)<=self.MAX_CHUNK or len(self.data)+len(block)>self.MAX_BYTES:
                    raise ValueError('Native report exceeds its byte bound')
                self.data.extend(block);self.chunks+=1
            elif event=='complete':
                exported=value.get('export',{})
                if (type(value.get('bytes')) is not int or type(value.get('chunks')) is not int
                        or value['bytes']!=len(self.data) or value['chunks']!=self.chunks or self.chunks==0
                        or not isinstance(exported,dict) or exported.get('bytes')!=len(self.data)
                        or value.get('sha256')!=hashlib.sha256(self.data).hexdigest()):
                    raise ValueError('Native report completion size, chunk count or SHA256 mismatch')
                self.data.decode('utf-8',errors='strict')
                if (not self.data.startswith(b'LIGHTFORGE DIAGNOSTIC REPORT\n')
                        or not self.data.endswith(b'\nEND OF DIAGNOSTIC REPORT\n')):
                    raise ValueError('Native report boundaries are incomplete')
                self.report_complete=value
            else:raise ValueError('Unknown native report event')
        except (ValueError,TypeError,KeyError) as error:
            self.error(error,report=marker==native)

    def summary(self):
        return {'diagnosticOnly':True,'releaseEligible':False,'originalGateFailed':self.original_gate_failed,
                'originalFailure':self.original_failure,'events':self.events,'errors':self.errors,
                'nativeReport':{'complete':self.report_complete is not None and not self.report_invalid,
                    'chunksReceived':self.chunks,'bytesReceived':len(self.data),
                    'exportReceipt':self.report_complete}}

    def save(self):
        (self.directory/'android-readiness-observation.json').write_text(json.dumps(self.summary(),indent=2)+'\n')

    def finish(self):
        if self.finished:return self.summary()
        self.finished=True
        if self.report_seen and self.report_complete is None and not self.report_invalid:
            self.error('Native report ended before its verified completion marker',report=True)
        if self.report_complete is not None and not self.report_invalid:
            (self.directory/'android-readiness-native-report.txt').write_bytes(self.data)
        self.save()
        if self.report_seen:
            (self.directory/'android-readiness-native-report.json').write_text(json.dumps(
                {'diagnosticOnly':True,'releaseEligible':False,**self.summary()['nativeReport'],'errors':self.errors},indent=2)+'\n')
        return self.summary()


ROOT=Path(__file__).resolve().parents[1];version=json.loads((ROOT/'version.json').read_text())['name'];out=ROOT/('qa/release-'+version);out.mkdir(exist_ok=True)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--diagnostic-readiness-observation',action='store_true',
                    help='Retain bounded post-failure evidence for a verified diagnostic-only APK.')
args=parser.parse_args()
observation_capture=None
sdk=Path(os.environ['ANDROID_HOME']);adb=sdk/'platform-tools/adb'
sources=[*sorted((ROOT/'android').rglob('*.java')),*sorted((ROOT/'android').rglob('*.xml')),*sorted((ROOT/'web/background').rglob('*')),*sorted((ROOT/'web/analysis').glob('*.js')),*sorted((ROOT/'web/engine').glob('*.js')),ROOT/'web/app.js',ROOT/'web/index.html',ROOT/'tests/android/BackgroundInstrumentation.java',ROOT/'tools/run_android_background_tests.py',ROOT/'tools/build_android_tests.py',ROOT/'android/native-runtime.json',ROOT/'web/analysis/ASSET_MANIFEST.json']
if args.diagnostic_readiness_observation:
    sources.extend(ROOT/name for name in ['tools/prepare_android_readiness_probe.py','tools/android-readiness-patch.json',
                    'web/preview/src/vehicle-preview.js','web/preview/vehicle-preview.js'])
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
receipt={'release':version,'passed':False,'checks':[],'errors':[],'source_hashes':hashes,'scope':'Android API 35 emulator lifecycle test using the production service, native CPU Studio and two-pass Balanced MDX separation, frozen-request routing, live model/tensor release before WebView/WASM voice/GAME, screen-off completion, live inference cancellation, verified passage resume and compilation. Not a physical phone or Tesla test.'}
def run(*args,timeout=120):
    return subprocess.run([str(adb),*args],text=True,capture_output=True,timeout=timeout,check=True).stdout
INSTRUMENT_TIMEOUT_SECONDS=3000

def run_instrumentation():
    """Tee status immediately and retain partial output if the global budget expires."""
    command=[str(adb),'shell','am','instrument','-w']
    if args.diagnostic_readiness_observation:command.extend(['-e','diagnosticReadinessObservation','true'])
    command.append('com.cyberbasslord.lightforge.tests/com.cyberbasslord.lightforge.BackgroundInstrumentation')
    log_path=out/'android-background.log'
    progress_path=out/'android-background-progress.json'
    pending=''
    def observe(text):
        nonlocal pending
        pending+=text
        while '\n' in pending:
            line,pending=pending.split('\n',1)
            gate_marker='LIGHTFORGE_READINESS_GATE_FAILED '
            if gate_marker in line:
                try:
                    failure=json.loads(line.split(gate_marker,1)[1])
                    if not isinstance(failure,dict) or failure.get('passed') is not False or failure.get('limitSeconds')!=45:
                        raise ValueError('Invalid original readiness gate marker')
                    if 'originalReadinessFailure' in receipt and receipt['originalReadinessFailure']!=failure:
                        raise ValueError('Original readiness failure changed')
                    receipt['originalReadinessFailure']=failure
                    if observation_capture is not None:observation_capture.bind_gate_failure(failure)
                except (ValueError,TypeError) as error:
                    receipt['errors'].append(str(error))
            if observation_capture is not None:observation_capture.observe(line)
            marker='LIGHTFORGE_PROGRESS '
            if marker not in line:continue
            try:
                snapshot=json.loads(line.split(marker,1)[1])
                if not isinstance(snapshot,dict) or not isinstance(snapshot.get('checks'),list):continue
                receipt['checks']=snapshot['checks']
                receipt['lastProgress']=snapshot
                progress_path.write_text(json.dumps(snapshot,indent=2)+'\n')
            except (ValueError,TypeError):pass
    with log_path.open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        selector=selectors.DefaultSelector()
        selector.register(process.stdout,selectors.EVENT_READ)
        deadline=time.monotonic()+INSTRUMENT_TIMEOUT_SECONDS
        timed_out=False
        try:
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0 and not timed_out:
                    timed_out=True
                    process.kill()
                ready=selector.select(1 if timed_out else min(1,max(0,remaining)))
                for selected,_ in ready:
                    block=os.read(selected.fileobj.fileno(),65536)
                    if not block:
                        selector.unregister(selected.fileobj)
                        continue
                    text=block.decode('utf-8',errors='replace')
                    log.write(text);log.flush()
                    print(text,end='',flush=True)
                    observe(text)
                if timed_out and not ready and process.poll() is not None:
                    # A terminated adb has no future writes. Keep everything already read.
                    break
            code=process.wait(timeout=10)
            if pending:observe('\n')
        finally:
            selector.close()
            if process.poll() is None:
                process.kill();process.wait(timeout=10)
            process.stdout.close()
    result=log_path.read_text(encoding='utf-8')
    if timed_out:
        raise subprocess.TimeoutExpired(command,INSTRUMENT_TIMEOUT_SECONDS,output=result)
    if code:
        raise subprocess.CalledProcessError(code,command,output=result)
    return result

try:
    if args.diagnostic_readiness_observation:
        receipt['readinessObservationGuard']=validate_observation_candidate(ROOT,version)
        observation_capture=ReadinessObservationCapture(out)
    until=time.monotonic()+180
    while time.monotonic()<until:
        log=ROOT/'emulator.log'
        if log.is_file():
            fatal=[line for line in log.read_text(errors='replace').splitlines() if 'FATAL' in line]
            if fatal:raise RuntimeError('Android emulator failed to start: '+fatal[-1])
        try:
            if run('get-state',timeout=10).strip()=='device':break
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):pass
        time.sleep(2)
    else:raise RuntimeError('Android emulator did not connect to adb; see emulator.log')
    until=time.monotonic()+300
    while time.monotonic()<until:
        if run('shell','getprop','sys.boot_completed').strip()=='1':break
        time.sleep(2)
    else:raise RuntimeError('Android emulator did not boot')
    for setting in ['window_animation_scale','transition_animation_scale','animator_duration_scale']:
        run('shell','settings','put','global',setting,'0')
        if run('shell','settings','get','global',setting).strip() not in {'0','0.0'}:
            raise RuntimeError('Android animation setting was not applied: '+setting)
    run('shell','input','keyevent','KEYCODE_WAKEUP');run('shell','wm','dismiss-keyguard')
    run('install','-r',str(ROOT/'candidate'/('LightForge-'+version+'.apk')),timeout=300)
    run('install','-r',str(ROOT/'candidate/background-tests.apk'))
    run('shell','pm','grant','com.cyberbasslord.lightforge','android.permission.POST_NOTIFICATIONS')
    run('shell','dumpsys','deviceidle','whitelist','+com.cyberbasslord.lightforge')
    result=run_instrumentation()
    if receipt['errors']:raise RuntimeError('Lifecycle failure evidence was invalid; see retained errors')
    if ('originalReadinessFailure' in receipt or
            observation_capture is not None and (observation_capture.original_gate_failed
                or observation_capture.report_seen or observation_capture.errors)):
        raise RuntimeError('Original 45-second preview readiness gate failed; later diagnostic observations do not change that result')
    if 'BACKGROUND_ANDROID_PASS' not in result:raise RuntimeError('Android lifecycle instrumentation failed; see android-background.log')
    final_report=False
    for line in result.splitlines():
        if line.startswith('{"passed":true') or ('"passed":true' in line and line.startswith('{')):
            detail=json.loads(line);receipt['checks']=detail['checks'];receipt['device']=detail;final_report=True
    if not final_report or not receipt['checks']:raise RuntimeError('Android lifecycle report missing')
    ui_readiness=receipt['device'].get('uiReadiness',[])
    if len(ui_readiness)<2 or not all(
            item.get('bootstrapInventoryReady') is True and item.get('projectRestoreIdle') is True
            and item.get('previewModelReady') is True
            and item.get('visualStateReady') is True and item.get('firstFrameCommitted') is True
            and item.get('hardwareAccelerated') is True and item.get('frameCommitMethod')=='hardware-frame-commit'
            and item.get('viewWidth',0)>0 and item.get('viewHeight',0)>0
            and (item.get('previewVisible') is not True or item.get('previewFrames',0)>0)
            for item in ui_readiness):
        raise RuntimeError('Android preview initialization and committed-frame evidence is incomplete')
    balanced=receipt['device'].get('balanced',{})
    if not (balanced.get('completedNativePasses')==2 and balanced.get('nativePassesBeforeVoice')==2
            and balanced.get('modelReleasedDuringVoice') is True and balanced.get('sourceSamples')==132300
            and balanced.get('stemSamples')==66150 and balanced.get('separation',{}).get('denoise') is True
            and balanced.get('separation',{}).get('modelPasses')==2 and balanced.get('separation',{}).get('chunks')==1):
        raise RuntimeError('Android Balanced native lifecycle evidence is incomplete')
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}, 'Android source changed during lifecycle verification.'
    receipt['passed']=True
except Exception as error:
    receipt['errors'].append(str(error));raise
finally:
    if observation_capture is not None:
        try:receipt['readinessObservation']=observation_capture.finish()
        except Exception as diagnostic_error:receipt['errors'].append('Readiness evidence retention: '+str(diagnostic_error))
    try:(out/'android-logcat.txt').write_text(run('logcat','-d','-v','threadtime',timeout=20))
    except Exception:pass
    if not receipt['passed']:
        for name,command in [
            ('android-last-anr.txt',('shell','dumpsys','activity','lastanr')),
            ('android-memory.txt',('shell','dumpsys','meminfo','com.cyberbasslord.lightforge')),
            ('android-power.txt',('shell','dumpsys','power')),
        ]:
            try:(out/name).write_text(run(*command,timeout=15))
            except Exception as diagnostic_error:(out/name).write_text(str(diagnostic_error)+'\n')
    receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (out/'android-background-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

#!/usr/bin/env python3
"""Install CI APKs and retain a source-bound Android background lifecycle receipt."""
import argparse,datetime,hashlib,json,os,selectors,subprocess,time
from pathlib import Path
from android_evidence_manifest import _atomic_json, candidate_binding
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate-dir',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--candidate-artifact-id',type=int,required=True)
parser.add_argument('--candidate-artifact-digest',required=True)
parser.add_argument('--candidate-run-id',type=int,required=True)
parser.add_argument('--candidate-run-attempt',type=int,required=True)
parser.add_argument('--candidate-evidence-session',required=True)
parser.add_argument('--candidate-identity-sha256',required=True)
parser.add_argument('--run-id',type=int,required=True)
parser.add_argument('--run-attempt',type=int,required=True)
parser.add_argument('--head-sha',required=True)
parser.add_argument('--evidence-session',required=True)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
version=json.loads((ROOT/'version.json').read_text())['name']
out=args.output_dir.resolve()
if out.exists():raise SystemExit('Android evidence output directory must be fresh: '+str(out))
out.mkdir(parents=True,mode=0o700)
candidate_dir=args.candidate_dir.resolve()
candidate=candidate_binding(candidate_dir,version,artifact_id=args.candidate_artifact_id,artifact_digest=args.candidate_artifact_digest,head_sha=args.head_sha,run_id=args.candidate_run_id,run_attempt=args.candidate_run_attempt,evidence_session=args.candidate_evidence_session,identity_sha256=args.candidate_identity_sha256)
ci={'run_id':args.run_id,'run_attempt':args.run_attempt,'head_sha':args.head_sha,'evidence_session':args.evidence_session}
sdk=Path(os.environ['ANDROID_HOME']);adb=sdk/'platform-tools/adb'
sources=[*sorted((ROOT/'android').rglob('*.java')),*sorted((ROOT/'android').rglob('*.xml')),*sorted((ROOT/'web/background').rglob('*')),*sorted((ROOT/'web/analysis').glob('*.js')),*sorted((ROOT/'web/engine').glob('*.js')),ROOT/'web/app.js',ROOT/'web/index.html',ROOT/'tests/android/BackgroundInstrumentation.java',ROOT/'tools/run_android_background_tests.py',ROOT/'tools/build_android_tests.py',ROOT/'android/native-runtime.json',ROOT/'web/analysis/ASSET_MANIFEST.json',ROOT/'tools/android_evidence_manifest.py']
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
receipt={'release':version,'passed':False,'checks':[],'errors':[],'source_hashes':hashes,'scope':'Android API 35 emulator lifecycle test using the production service, native CPU Studio and two-pass Balanced MDX separation, frozen-request routing, live model/tensor release before WebView/WASM voice/GAME, screen-off completion, live inference cancellation, verified passage resume and compilation. Not a physical phone or Tesla test.','ci':ci,'candidate':candidate}
def run(*args,timeout=120):
    return subprocess.run([str(adb),*args],text=True,capture_output=True,timeout=timeout,check=True).stdout
INSTRUMENT_TIMEOUT_SECONDS=3000

def run_instrumentation():
    """Tee status immediately and retain partial output if the global budget expires."""
    command=[str(adb),'shell','am','instrument','-w','com.cyberbasslord.lightforge.tests/com.cyberbasslord.lightforge.BackgroundInstrumentation']
    log_path=out/'android-background.log'
    progress_path=out/'android-background-progress.json'
    pending=''
    def observe(text):
        nonlocal pending
        pending+=text
        while '\n' in pending:
            line,pending=pending.split('\n',1)
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
    run('install','-r',str(candidate_dir/('LightForge-'+version+'.apk')),timeout=300)
    run('install','-r',str(candidate_dir/'background-tests.apk'))
    run('shell','pm','grant','com.cyberbasslord.lightforge','android.permission.POST_NOTIFICATIONS')
    run('shell','dumpsys','deviceidle','whitelist','+com.cyberbasslord.lightforge')
    result=run_instrumentation()
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
    _atomic_json(out/'android-background-verification.json',receipt);print(json.dumps(receipt,indent=2))

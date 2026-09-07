#!/usr/bin/env python3
"""Install CI APKs and retain a source-bound Android background lifecycle receipt."""
import datetime,hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];version=json.loads((ROOT/'version.json').read_text())['name'];out=ROOT/('qa/release-'+version);out.mkdir(exist_ok=True)
sdk=Path(os.environ['ANDROID_HOME']);adb=sdk/'platform-tools/adb'
sources=[*sorted((ROOT/'android').rglob('*.java')),*sorted((ROOT/'android').rglob('*.xml')),*sorted((ROOT/'web/background').rglob('*')),ROOT/'web/app.js',ROOT/'web/index.html',ROOT/'tests/android/BackgroundInstrumentation.java',ROOT/'tools/run_android_background_tests.py',ROOT/'tools/build_android_tests.py']
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
receipt={'release':version,'passed':False,'checks':[],'errors':[],'source_hashes':hashes,'scope':'Android API 35 emulator lifecycle test using real production service, actual balanced WASM analysis and compilation. Not a physical phone or Tesla test.'}
def run(*args,timeout=120):
    return subprocess.run([str(adb),*args],text=True,capture_output=True,timeout=timeout,check=True).stdout
try:
    run('wait-for-device');until=time.monotonic()+300
    while time.monotonic()<until:
        if run('shell','getprop','sys.boot_completed').strip()=='1':break
        time.sleep(2)
    else:raise RuntimeError('Android emulator did not boot')
    run('shell','settings','put','global','window_animation_scale','0');run('shell','settings','put','global','transition_animation_scale','0')
    run('shell','input','keyevent','KEYCODE_WAKEUP');run('shell','wm','dismiss-keyguard')
    run('install','-r',str(ROOT/'candidate'/('LightForge-'+version+'.apk')),timeout=300)
    run('install','-r',str(ROOT/'candidate/background-tests.apk'))
    run('shell','pm','grant','com.cyberbasslord.lightforge','android.permission.POST_NOTIFICATIONS')
    run('shell','dumpsys','deviceidle','whitelist','+com.cyberbasslord.lightforge')
    result=run('shell','am','instrument','-w','com.cyberbasslord.lightforge.tests/com.cyberbasslord.lightforge.BackgroundInstrumentation',timeout=1200)
    (out/'android-background.log').write_text(result)
    if 'BACKGROUND_ANDROID_PASS' not in result:raise RuntimeError('Android lifecycle instrumentation failed; see android-background.log')
    for line in result.splitlines():
        if line.startswith('{"passed":true') or ('"passed":true' in line and line.startswith('{')):
            detail=json.loads(line);receipt['checks']=detail['checks'];receipt['device']=detail
    if not receipt['checks']:raise RuntimeError('Android lifecycle report missing')
    receipt['passed']=True
except Exception as error:
    receipt['errors'].append(str(error));raise
finally:
    try:(out/'android-logcat.txt').write_text(run('logcat','-d','-v','threadtime',timeout=20))
    except Exception:pass
    receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (out/'android-background-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

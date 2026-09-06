#!/usr/bin/env python3
"""Compile production Android sources and run storage/format regressions on host JVM."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import datetime
import argparse

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--release', default=json.loads((ROOT / 'version.json').read_text())['name'])
args = parser.parse_args()
if not all(part.isdigit() for part in args.release.split('.')) or len(args.release.split('.')) != 3:
    parser.error('--release must be a dotted numeric release version')
OUT = ROOT / ('qa/release-' + args.release)
TOOLS = ROOT.parent / 'toolchain'
JAVA = TOOLS / 'jdk17/bin'
ANDROID = TOOLS / 'android-sdk/platforms/android-35/android.jar'
JSON = TOOLS / 'test-json.jar'
CLASSES = OUT / 'native-classes'
OUT.mkdir(parents=True, exist_ok=True)
CLASSES.mkdir(exist_ok=True)
sources = sorted((ROOT / 'android/src').rglob('*.java'))
names = ['NativeRecoveryTest', 'ProjectStoreTest', 'NativeHardwareTest', 'NativeAudioTest', 'WebViewTransportTest', 'ProjectPreviewTest']
tests = [ROOT / f'tests/{name}.java' for name in names + ['WebViewTransportServer']]
receipt = dict(release=args.release, passed=False, scope='Fresh production Java compilation and host JVM tests; no Android Activity/device/document-provider or physical Tesla execution.',
               source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, checks=[])

def run(name, *args):
    p = subprocess.run([str(JAVA / 'java'), '-cp', ':'.join(map(str, [CLASSES, JSON, ANDROID])),
                        'com.cyberbasslord.lightforge.' + name, *map(str, args)], cwd=ROOT, capture_output=True, text=True)
    (OUT / (name + '.txt')).write_text(p.stdout + p.stderr)
    p.check_returncode()
    return p.stdout

try:
    result = subprocess.run([str(JAVA / 'javac'), '-encoding', 'UTF-8', '--release', '8', '-classpath', str(ANDROID),
                             '-d', str(CLASSES), *map(str, sources), str(ROOT / 'build/generated/com/cyberbasslord/lightforge/R.java'), *map(str, tests)],
                            cwd=ROOT, capture_output=True, text=True)
    (OUT / 'native-compilation.txt').write_text(result.stdout + result.stderr)
    result.check_returncode()
    for folder in ['native-recovery-fixtures', 'native-project-fixtures', 'native-audio-fixtures', 'native-transport-fixtures']:
        where = OUT / folder
        if where.exists(): shutil.rmtree(where)
    recovery = json.loads(run('NativeRecoveryTest', OUT / 'native-recovery-fixtures'))
    assert recovery['passed']
    (OUT / 'native-recovery-results.json').write_text(json.dumps(recovery, indent=2) + '\n')
    receipt['checks'].extend(recovery['checks'])
    assert 'PASS:' in run('ProjectStoreTest', OUT / 'native-project-fixtures')
    receipt['checks'].append('Existing duplicate/rename/backup restore/CRC/traversal/cancellation and legacy rename-journal regression suite passed.')
    assert 'PASS: 16' in run('NativeHardwareTest', ROOT / 'qa/hardware-1.2.0/fixtures')
    receipt['checks'].append('All 16 independent native FSEQ hardware/closure validation cases passed.')
    assert 'PASS:' in run('NativeAudioTest', OUT / 'native-audio-fixtures')
    receipt['checks'].append('Native PCM conversion/resampling, supported WAV variants and incomplete-audio rejection regression suite passed.')
    assert 'PASS:' in run('WebViewTransportTest', ROOT / 'web/demo/glass-castle.wav', OUT / 'native-transport-fixtures')
    receipt['checks'].append('WebView byte-range transport regression suite passed on the actual demo audio.')
    receipt['checks'].append('Production COOP/COEP/CORP response policy is same-origin and independently instantiated across unknown, empty, partial and large responses; ranges and MIME protection remain intact without cross-origin grants.')
    run('ProjectPreviewTest')
    receipt['checks'].append('Playback proxy boundaries through the four-hour maximum passed.')
    main = (ROOT / 'android/src/com/cyberbasslord/lightforge/MainActivity.java').read_text()
    assert 'LightForge 1.0.1' not in main and '"version","1.0.1"' not in main
    assert 'getPackageInfo(getPackageName(),0)' in main
    assert 'session.projectState' in main and 'meta.optJSONObject("projectState")' in main
    assert 'window.pausePreview && window.pausePreview()' in main
    assert 'startupRecovery=worker.submit' in main
    assert 'WebViewFileTransport.responseHeaders(length,range)' in main
    receipt['checks'].append('Source wiring checks: package-derived version, frozen export projectState, native pause/save hook and background startup recovery are present (not device runtime tests).')
    assert receipt['source_hashes'] == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, 'Native sources changed during validation; rerun.'
    receipt['passed'] = True
except Exception as error:
    receipt['failure'] = repr(error)
    raise
finally:
    receipt['completed'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (OUT / 'native-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))

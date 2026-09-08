#!/usr/bin/env python3
"""Build focused diagnostic-export instrumentation with the ephemeral CI identity."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from package_release import SIGNING_SHA256

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    tool = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
    sdk, java = tool / 'android-sdk', tool / 'jdk17/bin'
    build, android = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    version = json.loads((ROOT / 'version.json').read_text())['name']
    native = ROOT / ('qa/release-' + version + '/native-classes')
    out = ROOT / 'build/diagnostics-tests'
    out.mkdir(parents=True, exist_ok=True)
    classes = out / 'classes'
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    env = dict(os.environ, JAVA_HOME=str(java.parent))

    def run(*command):
        return subprocess.check_output([str(part) for part in command], env=env, text=True)

    if not (native / 'com/cyberbasslord/lightforge/AppDiagnostics.class').is_file():
        raise SystemExit('Compile current production sources with tests/verify_native_release.py first.')
    run(java / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(android) + ':' + str(native) + ':' + str(tool / 'onnx/classes.jar'),
        '-d', classes, ROOT / 'tests/android/DiagnosticsInstrumentation.java')
    if args.compile_only:
        print('Diagnostics instrumentation compiled against the production Android classes.')
        return
    key = Path(os.environ['LIGHTFORGE_SIGNING_DIR'])
    certificate = run(java / 'keytool', '-list', '-v', '-keystore', key / 'lightforge-release.jks',
                      '-storepass:file', key / 'keystore-password.txt')
    if SIGNING_SHA256 in certificate.lower().replace(':', ''):
        raise SystemExit('Instrumentation must use an ephemeral CI key, never the private release identity.')
    manifest = out / 'AndroidManifest.xml'
    manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.cyberbasslord.lightforge.diagnostics.tests"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="LightForge diagnostic tests"/><instrumentation android:name="com.cyberbasslord.lightforge.DiagnosticsInstrumentation" android:targetPackage="com.cyberbasslord.lightforge" android:functionalTest="true"/></manifest>''')
    classpath = out / 'target-classes.jar'
    run(java / 'jar', 'cf', classpath, '-C', native, '.')
    dex = out / 'dex'
    if dex.exists():
        shutil.rmtree(dex)
    dex.mkdir()
    run(build / 'd8', '--lib', android, '--classpath', classpath,
        '--classpath', tool / 'onnx/classes.jar', '--min-api', '26', '--output', dex,
        *sorted(classes.rglob('*.class')))
    unsigned = out / 'unsigned.apk'
    run(build / 'aapt2', 'link', '-o', unsigned, '-I', android, '--manifest', manifest)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for path in sorted(dex.glob('*.dex')):
            archive.write(path, path.name, compress_type=zipfile.ZIP_STORED)
    aligned = out / 'aligned.apk'
    run(build / 'zipalign', '-f', '4', unsigned, aligned)
    target = ROOT / 'dist/diagnostics-tests.apk'
    target.parent.mkdir(exist_ok=True)
    run(build / 'apksigner', 'sign', '--ks', key / 'lightforge-release.jks',
        '--ks-key-alias', 'lightforge', '--ks-pass', 'file:' + str(key / 'keystore-password.txt'),
        '--out', target, aligned)
    run(build / 'apksigner', 'verify', target)
    print('Built ephemeral, same-signed diagnostics-tests.apk')


if __name__ == '__main__':
    main()

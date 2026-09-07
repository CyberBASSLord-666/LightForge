#!/usr/bin/env python3
"""Build a separate instrumentation APK using the ephemeral CI signing identity."""
import argparse, json, os, subprocess, zipfile
from pathlib import Path
from package_release import SIGNING_SHA256

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--compile-only',action='store_true');args=parser.parse_args()
tool=Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR',ROOT.parent/'toolchain'))
sdk=tool/'android-sdk';java=tool/'jdk17/bin';build=sdk/'build-tools/35.0.0';android=sdk/'platforms/android-35/android.jar'
version=json.loads((ROOT/'version.json').read_text())['name'];out=ROOT/'build/android-tests';out.mkdir(parents=True,exist_ok=True)
classes=out/'classes';classes.mkdir(exist_ok=True)
native=ROOT/('qa/release-'+version+'/native-classes')
env=dict(os.environ,JAVA_HOME=str(java.parent))
def run(*command):return subprocess.check_output([str(p) for p in command],env=env,text=True)
manifest=out/'AndroidManifest.xml'
manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.cyberbasslord.lightforge.tests"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="LightForge lifecycle tests"/><instrumentation android:name="com.cyberbasslord.lightforge.BackgroundInstrumentation" android:targetPackage="com.cyberbasslord.lightforge" android:functionalTest="true"/></manifest>''')
run(java/'javac','--release','8','-classpath',str(android)+':'+str(native),'-d',classes,ROOT/'tests/android/BackgroundInstrumentation.java')
if args.compile_only:
    print('Instrumentation compiled against the production Android classes.');raise SystemExit(0)
key=Path(os.environ['LIGHTFORGE_SIGNING_DIR'])
certificate=run(java/'keytool','-list','-v','-keystore',key/'lightforge-release.jks','-storepass:file',key/'keystore-password.txt')
if SIGNING_SHA256 in certificate.lower().replace(':',''):
    raise SystemExit('Instrumentation must never use the private release signing identity. Use the ephemeral CI identity.')
classpath=out/'target-classes.jar';run(java/'jar','cf',classpath,'-C',native,'.')
dex=out/'dex';dex.mkdir(exist_ok=True)
run(build/'d8','--lib',android,'--classpath',classpath,'--min-api','26','--output',dex,*classes.rglob('*.class'))
unsigned=out/'unsigned.apk';run(build/'aapt2','link','-o',unsigned,'-I',android,'--manifest',manifest)
with zipfile.ZipFile(unsigned,'a') as archive:
    for path in dex.glob('*.dex'):archive.write(path,path.name,compress_type=zipfile.ZIP_STORED)
aligned=out/'aligned.apk';run(build/'zipalign','-f','4',unsigned,aligned)
target=ROOT/'dist/background-tests.apk'
# The generated key uses the store password. apksigner consumes password-file
# lines, so specifying that same single-line file twice incorrectly reaches EOF.
run(build/'apksigner','sign','--ks',key/'lightforge-release.jks','--ks-key-alias','lightforge','--ks-pass','file:'+str(key/'keystore-password.txt'),'--out',target,aligned)
run(build/'apksigner','verify',target);print('Built ephemeral, same-signed background-tests.apk')

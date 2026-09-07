"""Prepare the exact locally built APK for isolated Android lifecycle testing."""
from pathlib import Path
import os,secrets,shutil,subprocess,sys
root=Path.cwd();sys.path.insert(0,str(root/'tools'))
from apk_delta import apply_delta
import json
patch=json.loads(''.join(p.read_text() for p in sorted(Path(__file__).parent.glob('delta.*'))))
target=root/'dist/LightForge-2.2.0.apk'
apply_delta(root/'base/LightForge-2.1.0.apk',patch,target)
tool=root.parent/'toolchain';sdk=tool/'android-sdk';build=sdk/'build-tools/35.0.0';java=tool/'jdk17/bin'
env=dict(os.environ,JAVA_HOME=str(java.parent))
def run(*args):subprocess.run([str(x) for x in args],env=env,check=True)
generated=root/'build/generated';generated.mkdir(parents=True,exist_ok=True)
run(build/'aapt2','compile','--dir',root/'android/res','-o',root/'build/probe-res.zip')
run(build/'aapt2','link','-o',root/'build/probe-res.apk','-I',sdk/'platforms/android-35/android.jar','--manifest',root/'android/AndroidManifest.xml','--java',generated,root/'build/probe-res.zip')
key=Path(os.environ['RUNNER_TEMP'])/'probe-signing';key.mkdir(mode=0o700,exist_ok=True)
password=key/'keystore-password.txt';password.write_text(secrets.token_urlsafe(36)+'\n');password.chmod(0o600)
run(java/'keytool','-genkeypair','-keystore',key/'lightforge-release.jks','-storetype','JKS','-alias','lightforge','-keyalg','RSA','-keysize','3072','-validity','2','-storepass:file',password,'-keypass:file',password,'-dname','CN=LightForge isolated lifecycle probe','-noprompt')
candidate=root/'candidate';candidate.mkdir(exist_ok=True)
run(build/'apksigner','sign','--ks',key/'lightforge-release.jks','--ks-key-alias','lightforge','--ks-pass','file:'+str(password),'--out',candidate/target.name,target)
run(build/'apksigner','verify',candidate/target.name)
# The emulator needs disk space more than it needs duplicate transfer APKs.
shutil.rmtree(root/'base');target.unlink()
print('Exact local APK reconstructed by hash and re-signed solely for isolated instrumentation. No release key is present.')

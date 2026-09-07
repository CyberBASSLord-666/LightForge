#!/usr/bin/env bash
# Build a personal, release-signed Android APK using the official SDK CLI tools.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOOLCHAIN="${LIGHTFORGE_TOOLCHAIN_DIR:-$ROOT/../toolchain}"
SDK="${ANDROID_SDK_ROOT:-$TOOLCHAIN/android-sdk}"
JAVA_HOME="${LIGHTFORGE_JAVA_HOME:-$TOOLCHAIN/jdk17}"
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
BUILD_TOOLS="$SDK/build-tools/35.0.0"
PLATFORM="$SDK/platforms/android-35/android.jar"
BUILD_ROOT="$ROOT/build"
DIST="$ROOT/dist"
KEY_DIR="${LIGHTFORGE_SIGNING_DIR:-$ROOT/signing}"
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["name"])' "$ROOT/version.json")"
VERSION_CODE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["code"])' "$ROOT/version.json")"
APK_NAME="LightForge-$VERSION.apk"
python3 "$ROOT/tools/sync_version.py" --check
python3 "$ROOT/tools/verify_analysis_assets.py"
for tool in "$JAVA_HOME/bin/javac" "$JAVA_HOME/bin/keytool" "$BUILD_TOOLS/aapt2" "$BUILD_TOOLS/d8" "$BUILD_TOOLS/zipalign" "$BUILD_TOOLS/apksigner"; do
    if [[ ! -x "$tool" ]]; then
        printf 'Missing build tool: %s\nRun python3 tools/bootstrap_toolchain.py first.\n' "$tool" >&2
        exit 1
    fi
done
[[ -f "$PLATFORM" ]] || { printf 'Missing Android 35 platform: %s\n' "$PLATFORM" >&2; exit 1; }
[[ -f "$ROOT/android/AndroidManifest.xml" ]] || { printf 'Missing AndroidManifest.xml\n' >&2; exit 1; }
[[ -f "$ROOT/web/index.html" ]] || { printf 'Missing bundled web/index.html\n' >&2; exit 1; }
mkdir -p "$BUILD_ROOT" "$DIST" "$KEY_DIR"
command -v flock >/dev/null || { printf 'Missing build lock tool: flock\n' >&2; exit 1; }
exec 9>"$BUILD_ROOT/.build.lock"
flock -n 9 || { printf 'Another LightForge build is already running.\n' >&2; exit 1; }
# Every SDK output starts at a fresh path. A failed prior link cannot be reused.
BUILD="$(mktemp -d "$BUILD_ROOT/.run-XXXXXXXX")"
cleanup_build() {
    local status=$?
    if [[ "$status" -eq 0 ]]; then
        # Cleanup must not turn a fully verified, published APK into a failed
        # build if the filesystem briefly retains an SDK temporary file.
        rm -rf -- "$BUILD" 2>/dev/null || rm -rf -- "$BUILD" 2>/dev/null ||
            printf 'Verified APK is ready; some temporary build files remain at %s\n' "$BUILD" >&2
    else
        printf 'Build failed; isolated intermediates retained at %s\n' "$BUILD" >&2
    fi
    return "$status"
}
trap cleanup_build EXIT
mkdir -p "$BUILD/classes" "$BUILD/dex" "$BUILD/generated" "$BUILD/assets"
if [[ ! -f "$KEY_DIR/lightforge-release.jks" ]]; then
    if [[ "${LIGHTFORGE_ALLOW_NEW_SIGNING:-0}" != "1" ]]; then
        printf 'The original update signing identity is required. Restore it and set LIGHTFORGE_SIGNING_DIR. For an isolated development install only, set LIGHTFORGE_ALLOW_NEW_SIGNING=1.\n' >&2
        exit 1
    fi
    if [[ -e "$KEY_DIR/keystore-password.txt" ]]; then
        printf 'Signing password exists but keystore is missing; restore the original keystore before rebuilding.\n' >&2
        exit 1
    fi
    python3 - "$KEY_DIR/keystore-password.txt" <<'PY'
import os,secrets,sys
p=sys.argv[1]
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    f.write(secrets.token_urlsafe(36)+'\n');f.flush();os.fsync(f.fileno())
PY
    "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KEY_DIR/lightforge-release.jks" \
        -storetype JKS -alias lightforge -keyalg RSA -keysize 3072 -validity 10001 \
        -storepass:file "$KEY_DIR/keystore-password.txt" -keypass:file "$KEY_DIR/keystore-password.txt" \
        -dname 'CN=LightForge Personal, OU=Private Android App, O=Personal Use, C=US' -noprompt
    chmod 600 "$KEY_DIR/lightforge-release.jks"
fi
[[ -f "$KEY_DIR/keystore-password.txt" ]] || { printf 'The release keystore password is missing.\n' >&2; exit 1; }
# Stage only distributable web assets; development dependencies never enter the APK.
python3 - "$ROOT/web" "$BUILD/assets" <<'PYASSETS'
from pathlib import Path
import shutil,sys
src,dst=map(Path,sys.argv[1:])
for f in src.rglob('*'):
    rel=f.relative_to(src)
    if not f.is_file() or any(v.startswith('.') or v in {'node_modules','__pycache__'} for v in rel.parts):continue
    target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
PYASSETS
printf 'Compiling Android resources and bundling offline assets…\n'
"$BUILD_TOOLS/aapt2" compile --dir "$ROOT/android/res" -o "$BUILD/compiled-res.zip"
"$BUILD_TOOLS/aapt2" link -o "$BUILD/resources.apk" \
    -I "$PLATFORM" --manifest "$ROOT/android/AndroidManifest.xml" \
    --java "$BUILD/generated" --min-sdk-version 26 --target-sdk-version 35 \
    --version-code "$VERSION_CODE" --version-name "$VERSION" --replace-version \
    -A "$BUILD/assets" "$BUILD/compiled-res.zip"
# aapt2's successful exit alone is insufficient: a truncated ZIP must stop here.
python3 "$ROOT/tools/apk_archive.py" validate "$BUILD/resources.apk" "$BUILD/assets"
printf 'Compiling Java and Android bytecode…\n'
python3 - "$ROOT/android/src" "$BUILD/generated" "$BUILD/java-sources.txt" <<'PY'
from pathlib import Path
import sys
files=sorted(p for folder in sys.argv[1:3] for p in Path(folder).rglob('*.java')
             if not any(part.startswith('.') for part in p.relative_to(Path(folder)).parts))
if not files:raise SystemExit('No Java sources were found.')
Path(sys.argv[3]).write_text('\n'.join('"'+str(p).replace('\\','\\\\').replace('"','\\"')+'"' for p in files)+'\n')
PY
"$JAVA_HOME/bin/javac" -encoding UTF-8 --release 8 \
    -classpath "$PLATFORM" \
    -d "$BUILD/classes" "@$BUILD/java-sources.txt"
"$JAVA_HOME/bin/jar" --create --file "$BUILD/classes.jar" -C "$BUILD/classes" .
"$BUILD_TOOLS/d8" --release --min-api 26 --lib "$PLATFORM" --output "$BUILD/dex" "$BUILD/classes.jar"
python3 "$ROOT/tools/apk_archive.py" assemble "$BUILD/resources.apk" "$BUILD/dex" "$BUILD/unsigned.apk" "$BUILD/assets"
rm -- "$BUILD/resources.apk"
printf 'Aligning and signing APK…\n'
"$BUILD_TOOLS/zipalign" -P 16 -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
rm -- "$BUILD/unsigned.apk"
"$BUILD_TOOLS/apksigner" sign --ks "$KEY_DIR/lightforge-release.jks" --ks-key-alias lightforge \
    --ks-pass "file:$KEY_DIR/keystore-password.txt" \
    --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
    --v4-signing-enabled false --out "$BUILD/signed.apk" "$BUILD/aligned.apk"
rm -- "$BUILD/aligned.apk"
"$BUILD_TOOLS/apksigner" verify --verbose --print-certs "$BUILD/signed.apk" > "$BUILD/signature-verification.txt"
"$BUILD_TOOLS/zipalign" -c -P 16 4 "$BUILD/signed.apk"
"$BUILD_TOOLS/aapt2" dump badging "$BUILD/signed.apk" > "$BUILD/apk-badging.txt"
python3 "$ROOT/tools/apk_archive.py" validate "$BUILD/signed.apk" "$BUILD/assets" --require-dex
python3 - "$BUILD/signed.apk" "$DIST/$APK_NAME" "$BUILD/apk-badging.txt" "$ROOT/version.json" "$BUILD/signature-verification.txt" <<'PY'
from pathlib import Path
import hashlib,json,os,re,shutil,sys,zipfile
src,dst,badging_path,version_path,signature_path=map(Path,sys.argv[1:])
certificate=re.search(r"certificate SHA-256 digest: ([0-9a-f]+)",signature_path.read_text()).group(1)
compatible=certificate=="7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b"
if not compatible and os.environ.get("LIGHTFORGE_ALLOW_NEW_SIGNING")!="1":raise SystemExit("Signing identity cannot update the original LightForge installation.")
version=json.loads(version_path.read_text())
badging=badging_path.read_text()
expected={"package: name='com.cyberbasslord.lightforge'", "versionCode='%s'"%version['code'], "versionName='%s'"%version['name'], "minSdkVersion:'26'", "targetSdkVersion:'35'", "launchable-activity: name='com.cyberbasslord.lightforge.MainActivity'"}
for marker in expected:
    if marker not in badging:raise SystemExit('APK manifest validation failed: missing '+marker)
with zipfile.ZipFile(src) as z:
    bad=z.testzip()
    if bad:raise SystemExit('APK ZIP integrity failure: '+bad)
    required={'AndroidManifest.xml','classes.dex','resources.arsc','assets/index.html'}
    missing=required-set(z.namelist())
    if missing:raise SystemExit('APK missing entries: '+str(missing))
    for name in z.namelist():
        if 'node_modules' in name.split('/'):raise SystemExit('Development dependency in APK: '+name)
        if name.endswith('.dex'):
            with z.open(name) as dex:
                if dex.read(4)!=b'dex\n':raise SystemExit('Invalid DEX '+name)
tmp=dst.with_suffix('.apk.tmp')
sha=hashlib.sha256()
with src.open('rb') as source,tmp.open('wb') as f:
    while chunk:=source.read(1024*1024):f.write(chunk);sha.update(chunk)
    f.flush();os.fsync(f.fileno())
os.replace(tmp,dst)
receipt={'apk':dst.name,'update_compatible':compatible,'signing_certificate_sha256':certificate,'bytes':dst.stat().st_size,'sha256':sha.hexdigest(),'zip_integrity':'passed','alignment':'passed','signature':'verified','min_sdk':26,'target_sdk':35,'compile_sdk':35,'version_name':version['name'],'version_code':version['code']}
dst.with_suffix('.apk.sha256').write_text(receipt['sha256']+'  '+dst.name+'\n')
dst.with_suffix('.apk.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
PY
# Preserve the established release and native-test paths only after verification.
cp "$BUILD/signature-verification.txt" "$BUILD_ROOT/signature-verification.txt"
cp "$BUILD/apk-badging.txt" "$BUILD_ROOT/apk-badging.txt"
rm -rf -- "$BUILD_ROOT/generated"
mv "$BUILD/generated" "$BUILD_ROOT/generated"
printf 'Ready: %s\n' "$DIST/$APK_NAME"

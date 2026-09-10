#!/usr/bin/env python3
"""Qualify production WASM threading on stock and pinned modern Android WebView."""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib

import bootstrap_androidx_runtime as androidx
from apk_archive import verify_java_resources
from package_release import SIGNING_SHA256
from prepare_android_readiness_probe import payloads, check, digest
from prepare_analysis_cpu_probe import (
    REPOSITORY, RUN_ID, JOB_ID, ARTIFACT_ID, HEAD_SHA, ARTIFACT_SHA256,
    APK_SHA256, APK_BYTES, CI_CERTIFICATE, APK_NAME,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/wasm-thread-probe'
EVIDENCE = ROOT / 'diagnostic-input/wasm-threads'
TOOL = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = TOOL / 'jdk17/bin'
BUILD = TOOL / 'android-sdk/build-tools/35.0.0'
ANDROID = TOOL / 'android-sdk/platforms/android-35/android.jar'
ENV = dict(os.environ, JAVA_HOME=str(JAVA.parent))
APP_APK = 'LightForge-wasm-threads.apk'
PROBE_APK = 'wasm-thread-probe.apk'
PACKAGE = 'com.cyberbasslord.lightforge'
PROBE_PACKAGE = PACKAGE + '.wasmthreadprobe'
HOST_RESERVE_BYTES = 1536 * 1024 * 1024
TIMEOUT_SECONDS = 24 * 60
FIXTURE_DIRECTORY = 'qa/speedup-exact/wasm-threads/fixtures'
FIXTURE_MANIFEST = FIXTURE_DIRECTORY + '/falcon-mdx-3s.json'
FIXTURE_TEXT = FIXTURE_DIRECTORY + '/falcon-mdx-3s.float32le.zlib.base64'
FIXTURE_BYTES = 529200
FIXTURE_SHA256 = '5cfb46f063a2263e56c54d176841e0f6b1cfb69feb894896ef6875c697e3de22'
FIXTURE_ASSET = 'falcon-mdx-3s.float32le'
PROVIDER_URL = 'https://storage.googleapis.com/chromium-browser-snapshots/AndroidDesktop_x64/1695130/chrome-android-desktop.zip'
PROVIDER_ARCHIVE_BYTES = 492496631
PROVIDER_ENTRY = 'chrome-android-desktop/apks/SystemWebView.apk'
PROVIDER_HEADER_OFFSET = 302310097
PROVIDER_DATA_OFFSET = 302310200
PROVIDER_COMPRESSED_BYTES = 185601487
PROVIDER_BYTES = 410508149
PROVIDER_CRC32 = 236444603
PROVIDER_SHA256 = 'aad3a2b8f07179abb1e619d33ffdc173a4d7b88553f796e9835bd81b3015b42b'
PROVIDER_CERTIFICATE = '32a2fc74d731105859e5a85df16d95f102d85b22099b8064c5d8915c61dad1e0'
PROVIDER_REVISION = '0517c5cd3d3ef9a57f28fc635bbfa7e0a34abe09'
PROVIDER_VERSION = '155.0.8051.0'
PROVIDER_VERSION_CODE = '805100007'
PROVIDER_PACKAGE = 'com.android.webview'
PROVIDER_APK = 'SystemWebView-' + PROVIDER_VERSION + '.apk'
WEB_PATCHES = frozenset({
    'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/analysis/worker.js',
    'web/analysis/analyzer.js', 'web/analysis/dsp.js', 'web/analysis/separator-deux.js',
    'web/analysis/separator-mdx.js', 'web/analysis/vocal.js', 'web/analysis/vocal-detail.js',
    'web/analysis/bass-notes.js', 'web/analysis/wav-reader.js', 'web/analysis/stem-cache.js',
    'web/analysis/work-store.js', 'web/background/runner.js', 'web/version.js',
    'web/analysis/ASSET_MANIFEST.json', 'web/index.html',
    'web/licenses/androidx-Apache-2.0-LICENSE.txt',
    'web/licenses/androidx-THIRD-PARTY-NOTICES.txt',
    'web/licenses/chromium-webkit-boundary-LICENSE.txt',
})
PROBE_FILES = (
    'tools/prepare_wasm_thread_probe.py', 'tools/prepare_analysis_cpu_probe.py',
    'tools/prepare_android_readiness_probe.py', 'tools/bootstrap_native_runtime.py',
    'tools/bootstrap_androidx_runtime.py', 'tools/bootstrap_toolchain.py',
    'tools/package_release.py', 'tools/apk_archive.py', 'tools/verify_wasm_thread_report.py', 'build.sh',
    'tests/android/WasmThreadProbe.java', 'tests/android/wasm-thread-probe.js',
    '.github/workflows/probe-wasm-threads.yml', FIXTURE_MANIFEST, FIXTURE_TEXT,
    'qa/release-2.2.4/native-mdx-comparison-verification.json',
    'qa/release-1.6.0/musdb-fixture-provenance.json',
)


def run(*command, **kwargs):
    return subprocess.check_output([str(part) for part in command], cwd=ROOT, env=ENV, text=True, **kwargs)

def host_memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        values[name] = int(value.split()[0]) * 1024
    swaps = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    return {'totalBytes': values['MemTotal'], 'availableBytes': values['MemAvailable'],
            'swapTotalBytes': values['SwapTotal'], 'swapFreeBytes': values['SwapFree'],
            'swapInPages': int(swaps['pswpin']), 'swapOutPages': int(swaps['pswpout'])}

def certificate(apk):
    found = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)',
                       run(BUILD / 'apksigner', 'verify', '--verbose', '--print-certs', apk))
    check(len(found) == 1, 'Expected exactly one verified APK signer')
    return found[0]

def clean_directory(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path

def current_version():
    version = json.loads((ROOT / 'version.json').read_text())
    check(version in ({'name': '2.2.4', 'code': 20204}, {'name': '2.2.5', 'code': 20205}),
          'Only the reviewed 2.2.4 to 2.2.5 metadata transition is permitted')
    generated = ('/* Generated by tools/sync_version.py from version.json. */\n'
                 '(function(root){const value=Object.freeze(' + json.dumps(version, separators=(',', ':')) +
                 ');root.LightForgeVersion=value;if(typeof module!=="undefined"&&module.exports)module.exports=value;}'
                 ')(typeof window!=="undefined"?window:globalThis);\n')
    check((ROOT / 'web/version.js').read_bytes() == generated.encode(), 'Runtime version metadata does not match the exact generator output')
    return version

def download_base():
    def api(path):
        return json.loads(run('gh', 'api', 'repos/' + REPOSITORY + '/actions/' + path))
    source_run, source_job, artifact = api('runs/' + str(RUN_ID)), api('jobs/' + str(JOB_ID)), api('artifacts/' + str(ARTIFACT_ID))
    check(source_run['head_sha'] == HEAD_SHA and source_run['head_repository']['full_name'] == REPOSITORY
          and source_run['path'] == '.github/workflows/verify-v2.yml'
          and source_run['status'] == 'completed' and source_run['conclusion'] == 'success', 'Pinned full CI identity or result differs')
    check(source_job['run_id'] == RUN_ID and source_job['head_sha'] == HEAD_SHA
          and source_job['name'] == 'verify' and source_job['conclusion'] == 'success', 'Pinned build job differs')
    check(artifact['name'] == 'lightforge-2.2.4-ci-candidate' and not artifact['expired']
          and artifact['workflow_run']['id'] == RUN_ID and artifact['workflow_run']['head_sha'] == HEAD_SHA
          and artifact['digest'] == 'sha256:' + ARTIFACT_SHA256, 'Pinned candidate artifact differs')
    archive_path = OUT / 'candidate.zip'
    with archive_path.open('wb') as output:
        subprocess.run(['gh', 'api', 'repos/' + REPOSITORY + '/actions/artifacts/' + str(ARTIFACT_ID) + '/zip'],
                       cwd=ROOT, env=ENV, stdout=output, check=True)
    check(digest(archive_path) == ARTIFACT_SHA256, 'Artifact ZIP digest mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        check(len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate artifact ZIP entries')
        for name in (APK_NAME, APK_NAME + '.json', APK_NAME + '.sha256'):
            destination = OUT / name if name == APK_NAME else EVIDENCE / name
            with archive.open(name) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    archive_path.unlink()
    source_apk = OUT / APK_NAME
    metadata = json.loads((EVIDENCE / (APK_NAME + '.json')).read_text())
    check(source_apk.stat().st_size == APK_BYTES == metadata['bytes']
          and digest(source_apk) == APK_SHA256 == metadata['sha256'], 'Pinned CI APK bytes differ')
    check(metadata['version_name'] == '2.2.4' and metadata['version_code'] == 20204
          and metadata['signing_certificate_sha256'] == CI_CERTIFICATE
          and metadata['update_compatible'] is False and metadata['signature'] == 'verified'
          and metadata['zip_integrity'] == 'passed' and metadata['alignment'] == 'passed', 'CI APK metadata differs')
    check((EVIDENCE / (APK_NAME + '.sha256')).read_text().split()[0] == APK_SHA256, 'CI checksum file differs')
    check(certificate(source_apk) == CI_CERTIFICATE != SIGNING_SHA256, 'Unexpected CI signer')
    return source_apk


def source_hashes():
    files = {*sorted((ROOT / 'android').rglob('*.java')),
             *sorted((ROOT / 'web/analysis').rglob('*.js')),
             *sorted((ROOT / 'web/background').rglob('*.js')),
             *(ROOT / path for path in WEB_PATCHES if (ROOT / path).is_file()),
             *(ROOT / path for path in PROBE_FILES), ROOT / 'version.json',
             ROOT / 'web/version.js', ROOT / 'web/analysis/ASSET_MANIFEST.json',
             ROOT / 'web/analysis/models/game/manifest.json',
             ROOT / 'web/analysis/vendor/ort-wasm-simd-threaded.mjs',
             ROOT / 'web/analysis/vendor/ort-wasm-simd-threaded.wasm',
             ROOT / 'android/AndroidManifest.xml', ROOT / 'android/native-runtime.json',
             ROOT / 'android/androidx-runtime.json'}
    files.update(path for path in (ROOT / 'android/res').rglob('*') if path.is_file())
    files.update(ROOT / item['path'] for item in json.loads((ROOT / 'android/androidx-runtime.json').read_text())['licenses'])
    for path in files:
        check(path.is_file() and not path.is_symlink(), 'Missing or symlinked source: ' + str(path))
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(files)}


def production_diff():
    run('git', 'fetch', '--no-tags', 'origin', HEAD_SHA)
    changed = sorted(filter(None, run('git', 'diff', '--name-only', '-z', '--no-renames',
                                    HEAD_SHA, 'HEAD', '--', 'android', 'web', 'version.json').split('\0')))
    allowed_android = {'android/AndroidManifest.xml', 'android/androidx-runtime.json'}
    for name in changed:
        java = bool(re.fullmatch(r'android/src/(?:[A-Za-z0-9_]+/)+[A-Za-z0-9_]+\.java', name))
        check(java or name in WEB_PATCHES or name in allowed_android or name == 'version.json',
              'Unreviewed production source change: ' + name)
        path = ROOT / name
        check(path.is_file() and not path.is_symlink(), 'Deleted or symlinked production source: ' + name)
    check('android/src/com/cyberbasslord/lightforge/WebViewIsolation.java' in changed,
          'Public provider-gated production isolation helper missing')
    baseline = ET.fromstring(run('git', 'show', HEAD_SHA + ':android/AndroidManifest.xml'))
    current = ET.fromstring((ROOT / 'android/AndroidManifest.xml').read_bytes())
    factory = '{http://schemas.android.com/apk/res/android}appComponentFactory'
    check(current.find('application').attrib.pop(factory, None) == 'androidx.core.app.CoreComponentFactory',
          'Required public AndroidX manifest factory missing')
    check(ET.tostring(current) == ET.tostring(baseline), 'Manifest changes exceed the public AndroidX component factory')
    manifest_path = 'web/analysis/ASSET_MANIFEST.json'
    previous_assets = json.loads(run('git', 'show', HEAD_SHA + ':' + manifest_path))
    current_assets = json.loads((ROOT / manifest_path).read_text())
    adapters = {name.removeprefix('web/analysis/') for name in changed
                if name.startswith('web/analysis/') and name.endswith('.js') and name in WEB_PATCHES}
    check(set(current_assets) == set(previous_assets) | adapters,
          'Analysis asset manifest changed the model/runtime asset inventory')
    for name, entry in current_assets.items():
        if name in adapters:
            path = ROOT / 'web/analysis' / name
            check(entry == {'bytes': path.stat().st_size, 'sha256': digest(path)}, 'Analysis adapter metadata differs: ' + name)
        else:
            check(entry == previous_assets[name], 'Unchanged model/runtime manifest entry differs: ' + name)
    version = current_version()
    expected_version_changes = {'version.json', 'web/version.js'} if version['name'] == '2.2.5' else set()
    check({'version.json', 'web/version.js'} & set(changed) == expected_version_changes, 'Unreviewed version transition')
    dependencies = json.loads((ROOT / 'android/androidx-runtime.json').read_text())
    check(dependencies['coordinate'] == 'androidx.webkit:webkit:1.18.0-alpha01'
          and dependencies['artifactCount'] == 12 and dependencies['runtimeJavaResourceCount'] == 22
          and dependencies['d8']['coordinate'] == 'com.android.tools:r8:8.6.17', 'Unreviewed AndroidX/runtime compiler closure')
    for item in dependencies['licenses']:
        path = ROOT / item['path']
        check(item['path'] in WEB_PATCHES and path.stat().st_size == item['bytes'] and digest(path) == item['sha256'],
              'Runtime license does not match its pin: ' + item['path'])
    run('git', 'diff', '--exit-code', 'HEAD', '--', 'android', 'web', 'version.json', *PROBE_FILES)
    check(not run('git', 'ls-files', '--others', '--exclude-standard', '--',
                  'android', 'web', 'version.json', *PROBE_FILES).strip(), 'Untracked production or diagnostic source found')
    return changed


def compile_current(with_dex=True):
    """Use build.sh's full AAR resource, final R, runtime-JAR and public D8 recipe."""
    version = current_version()
    run(sys.executable, ROOT / 'tools/bootstrap_native_runtime.py', '--check')
    manifest = androidx.prepare(check=True)
    generated = clean_directory(OUT / 'generated')
    native = clean_directory(OUT / 'target-classes')
    libraries = androidx.jar_paths()
    linked_dependencies = []
    for index, directory in enumerate(androidx.resource_dirs()):
        archive = OUT / ('androidx-res-' + str(index) + '.zip')
        run(BUILD / 'aapt2', 'compile', '--dir', directory, '-o', archive)
        linked_dependencies.append(archive)
    run(BUILD / 'aapt2', 'compile', '--dir', ROOT / 'android/res', '-o', OUT / 'compiled-res.zip')
    run(BUILD / 'aapt2', 'link', '-o', OUT / 'resources.apk', '-I', ANDROID,
        '--manifest', ROOT / 'android/AndroidManifest.xml', '--java', generated,
        '--min-sdk-version', '26', '--target-sdk-version', '35', '--version-code', version['code'],
        '--version-name', version['name'], '--replace-version', '--extra-packages',
        ':'.join(manifest['resourcePackages']), *linked_dependencies, OUT / 'compiled-res.zip')
    compile_classpath = os.pathsep.join(map(str, [ANDROID, TOOL / 'onnx/classes.jar', *libraries]))
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath', compile_classpath,
        '-d', native, *sorted((ROOT / 'android/src').rglob('*.java')), *sorted(generated.rglob('*.java')))
    classes = clean_directory(OUT / 'probe-classes')
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        compile_classpath + os.pathsep + str(native), '-d', classes, ROOT / 'tests/android/WasmThreadProbe.java')
    if not with_dex:
        return None, None, manifest
    classpath = OUT / 'target-classes.jar'
    run(JAVA / 'jar', 'cf', classpath, '-C', native, '.')
    dex = clean_directory(OUT / 'app-dex')
    compiler = (JAVA / 'java', '-cp', androidx.d8_jar(), 'com.android.tools.r8.D8')
    run(*compiler, '--release', '--min-api', '26', '--lib', ANDROID, '--output', dex,
        classpath, TOOL / 'onnx/classes.jar', *libraries)
    check((dex / 'classes.dex').is_file(), 'Fresh current-production DEX missing')
    probe_dex = clean_directory(OUT / 'probe-dex')
    probe_classpath = [argument for path in [classpath, TOOL / 'onnx/classes.jar', *libraries] for argument in ('--classpath', path)]
    run(*compiler, '--lib', ANDROID, *probe_classpath, '--min-api', '26', '--output', probe_dex,
        *sorted(classes.rglob('*.class')))
    return dex, probe_dex, manifest


def provider_range(first, last):
    request = urllib.request.Request(PROVIDER_URL, headers={
        'User-Agent': 'LightForge-WASM-diagnostic/1', 'Range': 'bytes=' + str(first) + '-' + str(last),
        'Accept-Encoding': 'identity',
    })
    response = urllib.request.urlopen(request, timeout=120)
    if (response.status != 206 or response.headers.get('Content-Range') != 'bytes ' + str(first) + '-' + str(last) + '/' + str(PROVIDER_ARCHIVE_BYTES)
            or int(response.headers.get('Content-Length', '-1')) != last - first + 1):
        response.close()
        raise RuntimeError('Official provider response did not preserve the exact pinned archive range')
    return response


def prepare_provider():
    """Extract only the fixed official ZIP entry and verify its complete APK bytes."""
    target = ROOT / 'candidate' / PROVIDER_APK
    target.parent.mkdir(exist_ok=True)
    provided = os.environ.get('LIGHTFORGE_PROBE_WEBVIEW_APK')
    if provided:
        local = Path(provided)
        check(local.is_file() and not local.is_symlink() and local.stat().st_size == PROVIDER_BYTES
              and digest(local) == PROVIDER_SHA256, 'Explicit local provider APK differs from the pin')
        shutil.copyfile(local, target)
    elif not (target.is_file() and target.stat().st_size == PROVIDER_BYTES and digest(target) == PROVIDER_SHA256):
        with provider_range(PROVIDER_HEADER_OFFSET, PROVIDER_DATA_OFFSET - 1) as response:
            header = response.read(PROVIDER_DATA_OFFSET - PROVIDER_HEADER_OFFSET + 1)
        check(len(header) == PROVIDER_DATA_OFFSET - PROVIDER_HEADER_OFFSET, 'Provider ZIP local header length differs')
        fields = struct.unpack_from('<4s5H3I2H', header)
        check(fields[0] == b'PK\x03\x04' and fields[3] == 8 and not fields[2] & 1,
              'Provider entry is not the expected unencrypted deflate stream')
        check(30 + fields[9] + fields[10] == len(header)
              and header[30:30 + fields[9]].decode() == PROVIDER_ENTRY, 'Provider ZIP entry identity differs')
        check(fields[6] in (0, PROVIDER_CRC32) and fields[7] in (0, PROVIDER_COMPRESSED_BYTES)
              and fields[8] in (0, PROVIDER_BYTES), 'Provider ZIP entry metadata differs')
        temporary = target.with_suffix('.apk.part')
        decompressor, total, compressed, crc = zlib.decompressobj(-15), 0, 0, 0
        sha = hashlib.sha256()
        try:
            with provider_range(PROVIDER_DATA_OFFSET, PROVIDER_DATA_OFFSET + PROVIDER_COMPRESSED_BYTES - 1) as response, temporary.open('wb') as output:
                while compressed < PROVIDER_COMPRESSED_BYTES:
                    block = response.read(min(1024 * 1024, PROVIDER_COMPRESSED_BYTES - compressed))
                    check(block, 'Official provider compressed entry was truncated')
                    compressed += len(block)
                    content = decompressor.decompress(block, PROVIDER_BYTES + 1 - total)
                    total += len(content)
                    check(total <= PROVIDER_BYTES and not decompressor.unconsumed_tail, 'Official provider entry exceeded its pinned size')
                    output.write(content)
                    sha.update(content)
                    crc = zlib.crc32(content, crc)
                check(not response.read(1), 'Official provider range had excess bytes')
                check(decompressor.eof and not decompressor.unused_data and total == PROVIDER_BYTES
                      and sha.hexdigest() == PROVIDER_SHA256 and crc == PROVIDER_CRC32,
                      'Official provider APK content/CRC/digest differs')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    check(target.stat().st_size == PROVIDER_BYTES and digest(target) == PROVIDER_SHA256,
          'Official provider APK failed final complete-byte verification')
    check(certificate(target) == PROVIDER_CERTIFICATE, 'Official provider APK signer differs')
    badging = run(BUILD / 'aapt2', 'dump', 'badging', target)
    for marker in ("package: name='" + PROVIDER_PACKAGE + "'", "versionName='" + PROVIDER_VERSION + "'",
                   "versionCode='" + PROVIDER_VERSION_CODE + "'", "minSdkVersion:'29'", "targetSdkVersion:'37'"):
        check(marker in badging, 'Official provider APK metadata differs: ' + marker)
    (EVIDENCE / 'provider-badging.txt').write_text(badging)
    receipt = dict(archive_url=PROVIDER_URL, archive_bytes=PROVIDER_ARCHIVE_BYTES, entry=PROVIDER_ENTRY,
                   source_revision=PROVIDER_REVISION, version=PROVIDER_VERSION, package=PROVIDER_PACKAGE,
                   apk_bytes=PROVIDER_BYTES, apk_sha256=PROVIDER_SHA256, certificate_sha256=PROVIDER_CERTIFICATE,
                   download_range=[PROVIDER_DATA_OFFSET, PROVIDER_DATA_OFFSET + PROVIDER_COMPRESSED_BYTES - 1],
                   official_chromium_snapshot=True, google_play_release_signed=False,
                   scope='Disposable userdebug emulator provider; capability qualification, not an app-distributed or recommended end-user update')
    (EVIDENCE / 'provider-provenance.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def decode_fixture():
    manifest = json.loads((ROOT / FIXTURE_MANIFEST).read_text())
    encoded = (ROOT / FIXTURE_TEXT).read_bytes()
    check(manifest['format'] == 'lightforge-diagnostic-pcm-v1' and manifest['diagnosticOnly'] is True
          and manifest['encoding'] == 'zlib+base64' and manifest['file'] == Path(FIXTURE_TEXT).name
          and manifest['assetName'] == FIXTURE_ASSET and manifest['bytes'] == FIXTURE_BYTES
          and manifest['sha256'] == FIXTURE_SHA256, 'Diagnostic fixture identity differs')
    check(len(encoded) == manifest['textBytes'] < 800000
          and hashlib.sha256(encoded).hexdigest() == manifest['textSha256'], 'Fixture text integrity differs')
    compressed = base64.b64decode(b''.join(encoded.splitlines()), validate=True)
    check(len(compressed) == manifest['compressedBytes']
          and hashlib.sha256(compressed).hexdigest() == manifest['compressedSha256'], 'Fixture compressed bytes differ')
    decoder = zlib.decompressobj()
    content = decoder.decompress(compressed, FIXTURE_BYTES + 1)
    check(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
          and len(content) == FIXTURE_BYTES and hashlib.sha256(content).hexdigest() == FIXTURE_SHA256,
          'Decoded separated PCM differs from exact three-second pin')
    check(manifest['samples'] == 132300 and manifest['sampleRate'] == 44100
          and manifest['sampleFormat'] == 'float32le' and manifest['seed'] == 2025 and manifest['language'] == 0,
          'Diagnostic fixture analysis settings changed')
    source = manifest['source']
    check(source['parentSha256'] == '3b928e6b749283788de5f27a0685754cbead48fe8b76752ca90b5354165c280b'
          and source['parentBytes'] == 1044480 and source['cropFirstSample'] == 3840
          and source['cropLastSample'] == 136140 and source['sampleBytesUnchanged'] is True,
          'Separated fixture source/crop binding changed')
    for value, path_key, hash_key in ((source, 'releaseProofPath', 'releaseProofSha256'),
                                      (manifest['attribution'], 'provenancePath', 'provenanceSha256')):
        check(value[path_key] in PROBE_FILES and digest(ROOT / value[path_key]) == value[hash_key], 'Original fixture proof/attribution changed')
    proof = json.loads((ROOT / source['releaseProofPath']).read_text())
    passages = [item for item in proof['passages'] if item.get('id') == 'falcon-start']
    check(len(passages) == 1 and passages[0]['source'] == source['mixturePath']
          and passages[0]['source_sha256'] == source['mixtureSha256']
          and passages[0]['output_hashes']['wasm-waveform.float32le']
          == {'bytes': source['parentBytes'], 'sha256': source['parentSha256']},
          'Original release proof does not bind this Falcon mixture and parent waveform')
    destination = OUT / FIXTURE_ASSET
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination, manifest


def prepare():
    check(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Diagnostic belongs to a different repository')
    check(os.environ.get('GITHUB_REF') == 'refs/heads/diagnostics/wasm-threads', 'Dedicated diagnostic branch required')
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    changed = production_diff()
    summary = dict(diagnostic_only=True, release_eligible=False, input_run_id=RUN_ID, input_head_sha=HEAD_SHA,
                   input_job_id=JOB_ID, input_run_conclusion='success', input_artifact_id=ARTIFACT_ID,
                   input_artifact_sha256=ARTIFACT_SHA256, input_apk_sha256=APK_SHA256,
                   probe_head_sha=run('git', 'rev-parse', 'HEAD').strip(), source_hashes=source_hashes(),
                   production_source_diff=changed, diagnostic_version=current_version(),
                   analysis_manifest_validation='Only approved adapter hashes differ; all models, ORT WASM and native JNI retain pinned 2.2.4 bytes')
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_apk = download_base()
    before = payloads(source_apk)
    (EVIDENCE / 'input-payloads.json').write_text(json.dumps(before, indent=2) + '\n')
    app_dex, probe_dex, dependency_manifest = compile_current()
    summary['androidx_runtime'] = dependency_manifest
    summary['compiler_sha256'] = digest(androidx.d8_jar())
    summary['runtime_jar_sha256'] = {str(path.relative_to(TOOL)): digest(path) for path in [TOOL / 'onnx/classes.jar', *androidx.jar_paths()]}
    replacements = {path.name: path for path in sorted(app_dex.glob('*.dex'))}
    old_dex = {name for name in before if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)}
    check(old_dex <= replacements.keys(), 'New dependency DEX layout would leave a stale removed DEX')
    check(any(digest(replacements[name]) != before[name]['sha256'] for name in old_dex), 'Current app DEX was not rebuilt')
    with zipfile.ZipFile(OUT / 'resources.apk') as archive:
        resources = set(archive.namelist())
        old_resources = {'AndroidManifest.xml', 'resources.arsc'} | {name for name in before if name.startswith('res/')}
        check(old_resources <= resources and all(name in ('AndroidManifest.xml', 'resources.arsc') or name.startswith('res/') for name in resources),
              'Linked AndroidX resources added an unexpected entry or removed an original resource')
        for name in sorted(resources):
            check('..' not in Path(name).parts and not Path(name).is_absolute(), 'Unsafe linked resource entry')
            target = OUT / 'linked-resource-payloads' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            replacements[name] = target
    java_resources = clean_directory(OUT / 'java-resources')
    androidx.prepare(check=True, stage_java_resources=java_resources)
    for item in dependency_manifest['javaResources']:
        replacements[item['path']] = java_resources / item['path']
    for name in changed:
        if name in WEB_PATCHES:
            replacements['assets/' + name.removeprefix('web/')] = ROOT / name
    new_entries = set(replacements) - before.keys()
    expected_added_assets = {'assets/analysis/game-worker.js'} | {
        'assets/' + item['path'].removeprefix('web/') for item in dependency_manifest['licenses']}
    expected_added = resources | {item['path'] for item in dependency_manifest['javaResources']} | expected_added_assets | {path.name for path in app_dex.glob('*.dex')}
    check(new_entries <= expected_added, 'Unreviewed new app payload entry')
    stage = clean_directory(OUT / 'patch-assets')
    expected = {}
    for entry, source in replacements.items():
        target = stage / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        expected[entry] = dict(sha256=digest(source), bytes=source.stat().st_size)
        check(digest(target) == expected[entry]['sha256'], 'Replacement changed during staging: ' + entry)
    patched, aligned = OUT / 'patched.apk', OUT / 'aligned-app.apk'
    shutil.copyfile(source_apk, patched)
    # Copy untouched compressed streams verbatim. Never repack any music model,
    # ORT WASM, native JNI, or unrelated app asset when adding this public API.
    subprocess.run(['zip', '-q', '-X', '-D', '-9', str(patched), *sorted(replacements)], cwd=stage, env=ENV, check=True)
    run(BUILD / 'zipalign', '-P', '16', '-f', '4', patched, aligned)
    patched.unlink()
    fixture, fixture_manifest = decode_fixture()
    (EVIDENCE / 'fixture-provenance.json').write_text(json.dumps(fixture_manifest, indent=2) + '\n')
    summary['fixture_sha256'] = digest(fixture)
    manifest = OUT / 'probe-manifest.xml'
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + PROBE_PACKAGE + '"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="LightForge WASM thread diagnostic"/><instrumentation android:name="' + PACKAGE + '.WasmThreadProbe" android:targetPackage="' + PACKAGE + '" android:functionalTest="true"/></manifest>')
    unsigned = OUT / 'unsigned-probe.apk'
    run(BUILD / 'aapt2', 'link', '-o', unsigned, '-I', ANDROID, '--manifest', manifest)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for path in sorted(probe_dex.glob('*.dex')):
            archive.write(path, path.name, compress_type=zipfile.ZIP_STORED)
        archive.write(ROOT / 'tests/android/wasm-thread-probe.js', 'assets/wasm-thread-probe.js', compress_type=zipfile.ZIP_DEFLATED)
        archive.write(fixture, 'assets/' + FIXTURE_ASSET, compress_type=zipfile.ZIP_DEFLATED)
    aligned_probe = OUT / 'aligned-probe.apk'
    run(BUILD / 'zipalign', '-f', '4', unsigned, aligned_probe)
    candidate = ROOT / 'candidate'
    candidate.mkdir(exist_ok=True)
    target, probe = candidate / APP_APK, candidate / PROBE_APK
    with tempfile.TemporaryDirectory(prefix='wasm-thread-ephemeral-', dir=os.environ['RUNNER_TEMP']) as temporary:
        key = Path(temporary)
        password = key / 'password.txt'
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(secrets.token_urlsafe(36) + '\n')
        keystore = key / 'probe.jks'
        run(JAVA / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'JKS',
            '-alias', 'lightforge', '-keyalg', 'RSA', '-keysize', '3072', '-validity', '2',
            '-storepass:file', password, '-keypass:file', password,
            '-dname', 'CN=LightForge WASM Thread Diagnostic, O=Ephemeral CI, C=US', '-noprompt')
        os.chmod(keystore, 0o600)
        for source, destination in ((aligned, target), (aligned_probe, probe)):
            run(BUILD / 'apksigner', 'sign', '--ks', keystore, '--ks-key-alias', 'lightforge',
                '--ks-pass', 'file:' + str(password), '--v1-signing-enabled', 'true',
                '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'false', '--alignment-preserved', 'true', '--out', destination, source)
        signer = certificate(target)
        check(signer not in (SIGNING_SHA256, CI_CERTIFICATE) and certificate(probe) == signer, 'Ephemeral app/instrumentation signing identities differ')
    run(BUILD / 'zipalign', '-c', '-P', '16', '4', target)
    with zipfile.ZipFile(target) as archive:
        verify_java_resources(archive, ROOT / 'android/androidx-runtime.json')
    after = payloads(target)
    check(after.keys() == before.keys() | new_entries, 'Unexpected added or removed app payload entry')
    for entry, details in after.items():
        if entry in expected:
            check(all(details[name] == value for name, value in expected[entry].items()), 'Generated payload differs: ' + entry)
        else:
            check(details == before[entry], 'Unreviewed payload bytes or metadata changed: ' + entry)
    badging = run(BUILD / 'aapt2', 'dump', 'badging', target)
    check("versionCode='" + str(summary['diagnostic_version']['code']) + "'" in badging
          and "versionName='" + summary['diagnostic_version']['name'] + "'" in badging, 'App manifest version differs')
    manifest_tree = run(BUILD / 'aapt2', 'dump', 'xmltree', target, '--file', 'AndroidManifest.xml')
    check('androidx.core.app.CoreComponentFactory' in manifest_tree, 'Public AndroidX factory missing from final APK')
    (EVIDENCE / 'diagnostic-payloads.json').write_text(json.dumps(after, indent=2) + '\n')
    summary.update(signing_key_destroyed=True, diagnostic_apk_sha256=digest(target), diagnostic_apk_bytes=target.stat().st_size,
                   diagnostic_certificate_sha256=signer, instrumentation_sha256=digest(probe), instrumentation_bytes=probe.stat().st_size,
                   replacement_entries=expected, unchanged_payload_entries=len(set(before) - replacements.keys()),
                   apk_source_hashes={'web/' + name.removeprefix('assets/'): item['sha256'] for name, item in after.items() if name.startswith('assets/')},
                   payload_comparison='Only complete current DEX, linked AndroidX resources, exact dependency Java resources/licenses and approved changed assets replaced; all other non-signature entry metadata and raw compressed/uncompressed bytes identical')
    summary['provider'] = prepare_provider()
    check(summary['source_hashes'] == source_hashes(), 'Source changed during preparation')
    summary['prepared'] = True
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_apk.unlink()
    aligned.unlink()
    print('Complete current-production diagnostic, exact separated fixture and pinned official provider prepared; no private signing key used.')


def validate_report(report, mode, provenance):
    from verify_wasm_thread_report import validate_phase
    expected_sources = {'web/analysis/' + name for name in (
        'worker.js', 'game.js', 'work-store.js', 'vendor/ort.wasm.min.js',
        'vendor/ort-wasm-simd-threaded.mjs', 'vendor/ort-wasm-simd-threaded.wasm',
        'models/game/manifest.json', 'models/game/encoder.onnx', 'models/game/dur2bd.onnx',
        'models/game/segmenter.onnx', 'models/game/bd2dur.onnx', 'models/game/estimator.onnx')}
    check(set(report.get('sourceHashes', {})) == expected_sources, 'Device engine/model/runtime bindings incomplete')
    for path in expected_sources:
        check(report['sourceHashes'][path] == provenance['apk_source_hashes'][path], 'Device loaded different app bytes: ' + path)
    check(report.get('fixtureSha256') == FIXTURE_SHA256
          and report.get('probeScriptSha256') == provenance['source_hashes']['tests/android/wasm-thread-probe.js'],
          'Device fixture or instrumentation script differs')
    return validate_phase(report, mode)


def host_preflight():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    value = host_memory()
    value.update(logicalCpus=os.cpu_count(), affinityCpus=len(os.sched_getaffinity(0)),
                 configuredGuestMemoryMiB=4096, configuredGuestCores=8, hostReserveBytes=HOST_RESERVE_BYTES,
                 scope='Eight guest CPUs exercise the production threshold; actual host CPUs/RAM are recorded independently. No physical-phone or throughput equivalence is implied.')
    value['passed'] = value['totalBytes'] >= 7 * 1024**3 and value['availableBytes'] >= 6 * 1024**3 and value['swapTotalBytes'] == 0
    (EVIDENCE / 'host-capacity.json').write_text(json.dumps(value, indent=2) + '\n')
    check(value['passed'], 'Runner needs six GiB of actual available RAM and swap disabled before launching the four-GiB guest')
    print(json.dumps(value))


def run_probe():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    receipt = dict(passed=False, diagnostic_only=True, phases={}, assertions={}, errors=[],
                   scope='Same app and retained default-profile data across stock124 fallback and official155 public isolation; bounded GAME exactness, not full-pipeline or physical-phone speed')
    adb = Path(os.environ['ANDROID_HOME']) / 'platform-tools/adb'
    stop = threading.Event()
    phase = {'name': 'boot'}
    sampler = host_watcher = None
    memory_counts = {'samples': 0, 'renderer_samples': 0, 'errors': 0}
    host_safety = {'samples': 0, 'minimumAvailableBytes': None, 'errors': [], 'reserveBytes': HOST_RESERVE_BYTES}

    def device(*arguments, timeout=30):
        command = [str(adb), *map(str, arguments)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            failure = {'phase': phase['name'], 'command': command, 'timeoutSeconds': timeout,
                       'stdout': error.stdout.decode(errors='replace') if isinstance(error.stdout, bytes) else error.stdout or '',
                       'stderr': error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else error.stderr or ''}
            with (EVIDENCE / 'adb-failures.jsonl').open('a') as output:
                output.write(json.dumps(failure) + '\n')
            print('ADB_FAILURE ' + json.dumps(failure), flush=True)
            raise
        if completed.returncode:
            failure = {'phase': phase['name'], 'command': command, 'returncode': completed.returncode,
                       'stdout': completed.stdout, 'stderr': completed.stderr}
            with (EVIDENCE / 'adb-failures.jsonl').open('a') as output:
                output.write(json.dumps(failure) + '\n')
            print('ADB_FAILURE ' + json.dumps(failure), flush=True)
            completed.check_returncode()
        return completed.stdout

    def watch_host():
        baseline = host_memory()
        last_write = 0
        with (EVIDENCE / 'host-memory-samples.jsonl').open('w', buffering=1) as output:
            while not stop.is_set():
                try:
                    sample = host_memory()
                    sample.update(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), phase=phase['name'])
                    host_safety['samples'] += 1
                    previous = host_safety['minimumAvailableBytes']
                    host_safety['minimumAvailableBytes'] = sample['availableBytes'] if previous is None else min(previous, sample['availableBytes'])
                    reason = None
                    if sample['availableBytes'] < HOST_RESERVE_BYTES:
                        reason = 'Actual host RAM fell below the reserved 1.5 GiB; diagnostic emulator stopped before host starvation'
                    if sample['swapInPages'] != baseline['swapInPages'] or sample['swapOutPages'] != baseline['swapOutPages']:
                        reason = 'Host swap activity appeared; swap-backed qualification is rejected'
                    if sample['swapTotalBytes'] != 0:
                        reason = 'Host swap was re-enabled after the required swap-free preflight'
                    now = time.monotonic()
                    if now - last_write >= 1 or reason:
                        output.write(json.dumps(sample) + '\n')
                        last_write = now
                    if reason:
                        host_safety['errors'].append(reason)
                        pid = int((ROOT / 'emulator.pid').read_text().strip())
                        command = Path('/proc') / str(pid) / 'cmdline'
                        check(pid > 1 and command.is_file() and b'LightForgeWasmThreads' in command.read_bytes(),
                              'Refusing to stop a process not identified as this diagnostic emulator')
                        os.kill(pid, signal.SIGTERM)
                        host_safety['emulatorStopped'] = True
                        return
                except Exception as error:
                    host_safety['errors'].append(str(error))
                    return
                stop.wait(.25)

    def sample_memory():
        with (EVIDENCE / 'memory-samples.jsonl').open('w', buffering=1) as output:
            while not stop.is_set():
                sample = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'phase': phase['name']}
                try:
                    sample['system_meminfo'] = device('shell', 'cat', '/proc/meminfo', timeout=10)
                    sample['processes'] = device('shell', 'ps', '-A', '-o', 'PID,PPID,RSS,NAME,ARGS', timeout=10)
                    sample['process_pss'] = device('shell', 'dumpsys', 'meminfo', '-c', timeout=15)
                    sample['renderer_processes'] = [line for line in sample['processes'].splitlines()
                                                   if 'sandboxed_process' in line.lower() or 'SandboxedProcessService' in line]
                    memory_counts['samples'] += 1
                    if sample['renderer_processes']:
                        memory_counts['renderer_samples'] += 1
                except Exception as error:
                    sample['error'] = str(error)
                    memory_counts['errors'] += 1
                output.write(json.dumps(sample) + '\n')
                stop.wait(10)

    def selected_provider(label):
        output = device('shell', 'dumpsys', 'webviewupdate')
        (EVIDENCE / ('webview-provider-' + label + '.txt')).write_text(output)
        found = re.search(r'Current WebView package \(name, version\):\s*\(([^,]+),\s*([^\)]+)\)', output)
        check(found is not None, 'Android did not identify a selected WebView provider')
        return {'package': found[1].strip(), 'version': found[2].strip()}

    try:
        provenance = json.loads((EVIDENCE / 'provenance.json').read_text())
        check(provenance.get('prepared') is True and provenance.get('source_hashes') == source_hashes(), 'Prepared source provenance missing or changed')
        receipt['provenance_sha256'] = digest(EVIDENCE / 'provenance.json')
        capacity = json.loads((EVIDENCE / 'host-capacity.json').read_text())
        check(capacity.get('passed') is True and capacity.get('configuredGuestMemoryMiB') == 4096
              and capacity.get('configuredGuestCores') == 8 and capacity.get('hostReserveBytes') == HOST_RESERVE_BYTES
              and capacity.get('swapTotalBytes') == 0, 'Required actual host-capacity preflight missing')
        receipt['hostCapacity'] = capacity
        host_watcher = threading.Thread(target=watch_host, name='wasm-thread-host-reserve', daemon=True)
        host_watcher.start()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                if device('shell', 'getprop', 'sys.boot_completed', timeout=10).strip() == '1':
                    break
            except (subprocess.SubprocessError, OSError):
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Android emulator did not boot')
        check(device('shell', 'getprop', 'ro.build.version.sdk').strip() == '35'
              and device('shell', 'getprop', 'ro.build.type').strip() == 'userdebug'
              and device('shell', 'getprop', 'ro.debuggable').strip() == '1', 'Official provider qualification requires the disposable API35 userdebug image')
        device('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
        device('shell', 'wm', 'dismiss-keyguard')
        for setting in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
            device('shell', 'settings', 'put', 'global', setting, '0')
        target, probe, provider = [ROOT / 'candidate' / name for name in (APP_APK, PROBE_APK, PROVIDER_APK)]
        check(digest(target) == provenance['diagnostic_apk_sha256'] and digest(probe) == provenance['instrumentation_sha256']
              and provider.stat().st_size == PROVIDER_BYTES and digest(provider) == PROVIDER_SHA256, 'Prepared APK bytes changed')
        stock_provider = selected_provider('stock-before-install')
        check(stock_provider['package'] == 'com.google.android.webview' and stock_provider['version'].startswith('124.'),
              'Stock fallback must run first on the actual WebView124 provider')
        device('install', '-r', target, timeout=300)
        device('install', '-r', probe, timeout=90)
        device('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
        (EVIDENCE / 'device-properties.txt').write_text(device('shell', 'getprop'))
        device('logcat', '-c')
        sampler = threading.Thread(target=sample_memory, name='wasm-thread-device-memory', daemon=True)
        sampler.start()
        started = time.monotonic()
        for mode in ('stock', 'modern'):
            phase['name'] = mode
            if mode == 'modern':
                phase['name'] = 'provider-switch'
                device('shell', 'am', 'force-stop', PACKAGE)
                (EVIDENCE / 'provider-adb-root.txt').write_text(device('root'))
                device('wait-for-device', timeout=30)
                check(device('shell', 'id', '-u').strip() == '0', 'Disposable userdebug adbd did not enter root mode')
                (EVIDENCE / 'provider-install.txt').write_text(device('install', '-r', provider, timeout=300))
                selection = device('shell', 'cmd', 'webviewupdate', 'set-webview-implementation', PROVIDER_PACKAGE)
                (EVIDENCE / 'provider-selection.txt').write_text(selection)
                check(selected_provider('modern-selected') == {'package': PROVIDER_PACKAGE, 'version': PROVIDER_VERSION},
                      'Official provider installation/selection did not take effect')
                phase['name'] = mode
            remaining = TIMEOUT_SECONDS - (time.monotonic() - started)
            check(remaining > 0 and not host_safety['errors'], 'Diagnostic time/host-memory budget expired')
            log = EVIDENCE / ('instrumentation-' + mode + '.log')
            with log.open('w') as output:
                completed = subprocess.run([str(adb), 'shell', 'am', 'instrument', '-w', '-e', 'mode', mode,
                                            PROBE_PACKAGE + '/' + PACKAGE + '.WasmThreadProbe'],
                                           stdout=output, stderr=subprocess.STDOUT, text=True,
                                           timeout=min(240 if mode == 'stock' else TIMEOUT_SECONDS, remaining))
            text = log.read_text()
            print(text, flush=True)
            check(completed.returncode == 0 and sum(line.strip() == 'WASM_THREAD_PASS' for line in text.splitlines()) == 1,
                  'Instrumentation failed during ' + mode + '; inspect retained phase log')
            reports = [json.loads(line.split('WASM_THREAD_RESULT ', 1)[1]) for line in text.splitlines() if 'WASM_THREAD_RESULT ' in line]
            check(len(reports) == 1, 'Exactly one device report is required per provider phase')
            report = reports[0]
            receipt['phases'][mode] = report
            (EVIDENCE / ('report-' + mode + '.json')).write_text(json.dumps(report, indent=2) + '\n')
            receipt['assertions'][mode] = validate_report(report, mode, provenance)
            (EVIDENCE / ('logcat-' + mode + '.txt')).write_text(device('logcat', '-d', '-v', 'threadtime'))
            check(selected_provider(mode + '-completed')['version'] == report['webViewVersion'], 'Provider changed within a qualification phase')
        check(receipt['phases']['stock']['storage']['opfs'] == receipt['phases']['modern']['storage']['opfs']
              and receipt['phases']['stock']['storage']['indexedDB'] == receipt['phases']['modern']['storage']['indexedDB'],
              'Provider switch did not retain the same default-profile app data')
        from verify_wasm_thread_report import validate_pair
        receipt['pair_assertions'] = validate_pair(receipt['phases']['stock'], receipt['phases']['modern'])
        check(digest(target) == provenance['diagnostic_apk_sha256'] and digest(probe) == provenance['instrumentation_sha256'],
              'App/instrumentation bytes changed between provider phases')
        receipt.update(passed=True, instrumentation_and_switch_seconds=time.monotonic() - started,
                       same_app_and_instrumentation=True, app_reinstalled_between_phases=False, app_data_cleared=False)
    except Exception as error:
        receipt['errors'].append(str(error))
        raise
    finally:
        stop.set()
        if host_watcher is not None:
            host_watcher.join(timeout=2)
        receipt['hostSafety'] = host_safety
        if host_safety['errors'] or host_safety['samples'] < 2:
            receipt['passed'] = False
            receipt['errors'].extend(host_safety['errors'] or ['Continuous host capacity observations missing'])
        if sampler is not None:
            sampler.join(timeout=40)
        receipt['memory'] = memory_counts
        try:
            (EVIDENCE / 'logcat-final.txt').write_text(device('logcat', '-d', '-v', 'threadtime'))
            (EVIDENCE / 'final-system-memory.txt').write_text(device('shell', 'dumpsys', 'meminfo', '-c'))
        except Exception as error:
            receipt['errors'].append('Final diagnostics: ' + str(error))
            receipt['passed'] = False
        if receipt['passed'] and (memory_counts['samples'] < 2 or memory_counts['renderer_samples'] < 1):
            receipt['passed'] = False
            receipt['errors'].append('Continuous system and renderer PSS observations incomplete')
        receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        try:
            device('shell', 'am', 'force-stop', PACKAGE)
        except Exception:
            pass
    check(receipt['passed'], 'WASM thread diagnostic did not pass all host checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--compile-only', action='store_true')
    mode.add_argument('--host-preflight', action='store_true')
    mode.add_argument('--decode-fixture', action='store_true')
    args = parser.parse_args()
    if args.compile_only:
        compile_current(with_dex=False)
        print('Complete current Java/AndroidX resources and independent instrumentation compiled; no DEX/model execution or signing.')
    elif args.run:
        run_probe()
    elif args.host_preflight:
        host_preflight()
    elif args.decode_fixture:
        path, _ = decode_fixture()
        print(json.dumps({'bytes': path.stat().st_size, 'sha256': digest(path)}))
    else:
        prepare()

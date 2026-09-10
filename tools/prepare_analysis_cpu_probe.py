#!/usr/bin/env python3
"""Prepare/run a tiny capability probe against a pinned, payload-identical CI APK."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile

from package_release import SIGNING_SHA256
from prepare_android_readiness_probe import payloads, check, digest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'CyberBASSLord-666/LightForge'
RUN_ID, JOB_ID, ARTIFACT_ID = 34424617050, 102707158334, 10132668921
HEAD_SHA = '57e6ee996bd8f9d135e89334585efe90d8667b68'
ARTIFACT_SHA256 = '54f9c3a4e21605b9dde666981636ef6d929d4ab2d82021f3f7c89486b538102e'
APK_SHA256 = '5620e784909b8fd14a4fb0e86c097f4acfe146f1b0a32681b1611015ef2c03d7'
APK_BYTES = 1204357470
CI_CERTIFICATE = '578bc5ba4969e3a4003811572085ebbfe45480abe659463ae2c3b3f993cc73d6'
APK_NAME = 'LightForge-2.2.4.apk'
PROBE_APK = 'analysis-cpu-probe.apk'
PROBE_FILES = ['tools/prepare_analysis_cpu_probe.py', 'tools/prepare_android_readiness_probe.py',
               'tests/android/AnalysisCpuProbe.java', 'tests/android/analysis-cpu-worker.js',
               '.github/workflows/probe-analysis-cpu.yml']
OUT = ROOT / 'build/analysis-cpu-probe'
EVIDENCE = ROOT / 'diagnostic-input/analysis-cpu'
TOOL = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = TOOL / 'jdk17/bin'
BUILD = TOOL / 'android-sdk/build-tools/35.0.0'
ANDROID = TOOL / 'android-sdk/platforms/android-35/android.jar'
ENV = dict(os.environ, JAVA_HOME=str(JAVA.parent))


def run(*command, **kwargs):
    return subprocess.check_output([str(part) for part in command], cwd=ROOT, env=ENV, text=True, **kwargs)


def source_hashes():
    files = [*sorted((ROOT / 'android').rglob('*.java')),
             ROOT / 'web/analysis/worker.js', ROOT / 'web/analysis/vendor/ort.wasm.min.js',
             ROOT / 'version.json', *(ROOT / path for path in PROBE_FILES)]
    return {str(path.relative_to(ROOT)): digest(path) for path in files}


def certificate(apk):
    found = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)',
                       run(BUILD / 'apksigner', 'verify', '--verbose', '--print-certs', apk))
    check(len(found) == 1, 'Expected exactly one verified APK signer')
    return found[0]


def compile_probe(native):
    classes = OUT / 'probe-classes'
    classes.mkdir(parents=True, exist_ok=True)
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(ANDROID) + ':' + str(native), '-d', classes,
        ROOT / 'tests/android/AnalysisCpuProbe.java')
    return classes


def prepare():
    check(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Diagnostic belongs to a different repository')
    check(os.environ.get('GITHUB_REF') == 'refs/heads/diagnostics/analysis-cpu', 'Dedicated diagnostic branch required')
    check(json.loads((ROOT / 'version.json').read_text()) == {'name': '2.2.4', 'code': 20204}, 'Unexpected app version')
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    def api(path):
        return json.loads(run('gh', 'api', 'repos/' + REPOSITORY + '/actions/' + path))

    source_run, source_job, artifact = api('runs/' + str(RUN_ID)), api('jobs/' + str(JOB_ID)), api('artifacts/' + str(ARTIFACT_ID))
    check(source_run['head_sha'] == HEAD_SHA and source_run['head_repository']['full_name'] == REPOSITORY
          and source_run['path'] == '.github/workflows/verify-v2.yml'
          and source_run['status'] == 'completed' and source_run['conclusion'] == 'success', 'Pinned full CI run did not pass or identity differs')
    check(source_job['run_id'] == RUN_ID and source_job['head_sha'] == HEAD_SHA
          and source_job['name'] == 'verify' and source_job['conclusion'] == 'success', 'Pinned build job differs')
    check(artifact['name'] == 'lightforge-2.2.4-ci-candidate' and not artifact['expired']
          and artifact['workflow_run']['id'] == RUN_ID and artifact['workflow_run']['head_sha'] == HEAD_SHA
          and artifact['digest'] == 'sha256:' + ARTIFACT_SHA256, 'Pinned candidate artifact differs')
    run('git', 'fetch', '--no-tags', 'origin', HEAD_SHA)
    run('git', 'diff', '--exit-code', HEAD_SHA, 'HEAD', '--', 'android', 'web', 'version.json')
    run('git', 'diff', '--exit-code', 'HEAD', '--', 'android', 'web', 'version.json')
    check(not run('git', 'ls-files', '--others', '--exclude-standard', '--', 'android', 'web', 'version.json').strip(), 'Untracked production source found')
    summary = dict(diagnostic_only=True, release_eligible=False, input_run_id=RUN_ID, input_head_sha=HEAD_SHA,
                   input_job_id=JOB_ID, input_run_conclusion='success', input_artifact_id=ARTIFACT_ID,
                   input_artifact_sha256=ARTIFACT_SHA256, input_apk_sha256=APK_SHA256,
                   probe_head_sha=run('git', 'rev-parse', 'HEAD').strip(), source_hashes=source_hashes(),
                   production_source_diff='none in android/, web/, version.json')
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
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
    before = payloads(source_apk)
    (EVIDENCE / 'input-payloads.json').write_text(json.dumps(before, indent=2) + '\n')

    # Compile only a classpath from the byte-identical production source. Its
    # dex is never written to the app; the original CI classes.dex survives.
    generated, native = OUT / 'generated', OUT / 'target-classes'
    generated.mkdir(exist_ok=True); native.mkdir(exist_ok=True)
    run(BUILD / 'aapt2', 'compile', '--dir', ROOT / 'android/res', '-o', OUT / 'compiled-res.zip')
    run(BUILD / 'aapt2', 'link', '-o', OUT / 'resources.apk', '-I', ANDROID,
        '--manifest', ROOT / 'android/AndroidManifest.xml', '--java', generated,
        '--min-sdk-version', '26', '--target-sdk-version', '35', '--version-code', '20204',
        '--version-name', '2.2.4', '--replace-version', OUT / 'compiled-res.zip')
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(ANDROID) + ':' + str(TOOL / 'onnx/classes.jar'), '-d', native,
        *sorted((ROOT / 'android/src').rglob('*.java')), *sorted(generated.rglob('*.java')))
    classes = compile_probe(native)
    classpath = OUT / 'target-classes.jar'
    run(JAVA / 'jar', 'cf', classpath, '-C', native, '.')
    dex = OUT / 'dex'; dex.mkdir(exist_ok=True)
    run(BUILD / 'd8', '--lib', ANDROID, '--classpath', classpath, '--min-api', '26', '--output', dex, *sorted(classes.rglob('*.class')))
    manifest = OUT / 'AndroidManifest.xml'
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.cyberbasslord.lightforge.cpuprobe"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="LightForge CPU capability diagnostic"/><instrumentation android:name="com.cyberbasslord.lightforge.AnalysisCpuProbe" android:targetPackage="com.cyberbasslord.lightforge" android:functionalTest="true"/></manifest>')
    unsigned = OUT / 'unsigned-probe.apk'
    run(BUILD / 'aapt2', 'link', '-o', unsigned, '-I', ANDROID, '--manifest', manifest)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for path in sorted(dex.glob('*.dex')): archive.write(path, path.name, compress_type=zipfile.ZIP_STORED)
        archive.write(ROOT / 'tests/android/analysis-cpu-worker.js', 'assets/analysis-cpu-worker.js', compress_type=zipfile.ZIP_DEFLATED)
    aligned = OUT / 'aligned-probe.apk'
    run(BUILD / 'zipalign', '-f', '4', unsigned, aligned)
    candidate = ROOT / 'candidate'; candidate.mkdir(exist_ok=True)
    target, probe = candidate / APK_NAME, candidate / PROBE_APK
    with tempfile.TemporaryDirectory(prefix='analysis-cpu-ephemeral-', dir=os.environ['RUNNER_TEMP']) as temporary:
        key = Path(temporary); password = key / 'password.txt'
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output: output.write(secrets.token_urlsafe(36) + '\n')
        keystore = key / 'probe.jks'
        run(JAVA / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'JKS',
            '-alias', 'lightforge', '-keyalg', 'RSA', '-keysize', '3072', '-validity', '2',
            '-storepass:file', password, '-keypass:file', password,
            '-dname', 'CN=LightForge CPU Diagnostic, O=Ephemeral CI, C=US', '-noprompt')
        os.chmod(keystore, 0o600)
        for source, destination in ((source_apk, target), (aligned, probe)):
            run(BUILD / 'apksigner', 'sign', '--ks', keystore, '--ks-key-alias', 'lightforge',
                '--ks-pass', 'file:' + str(password), '--v1-signing-enabled', 'true',
                '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'false', '--alignment-preserved', 'true', '--out', destination, source)
        signer = certificate(target)
        check(signer not in (SIGNING_SHA256, CI_CERTIFICATE) and certificate(probe) == signer, 'Ephemeral signing identities differ')
    run(BUILD / 'zipalign', '-c', '-P', '16', '4', target)
    after = payloads(target)
    check(before == after, 'App payload entry bytes or metadata changed; signatures are the only permitted difference')
    (EVIDENCE / 'diagnostic-payloads.json').write_text(json.dumps(after, indent=2) + '\n')
    summary.update(signing_key_destroyed=True, diagnostic_apk_sha256=digest(target), diagnostic_apk_bytes=target.stat().st_size,
                   diagnostic_certificate_sha256=signer, instrumentation_sha256=digest(probe),
                   instrumentation_bytes=probe.stat().st_size, payload_comparison='Every non-signature entry has identical metadata, compressed bytes, and uncompressed bytes',
                   unchanged_payload_entries=len(before), prepared=True)
    check(summary['source_hashes'] == source_hashes(), 'Source changed during preparation')
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_apk.unlink()
    print('Payload-identical diagnostic APK and independent, same-signed CPU instrumentation prepared.')


def run_probe():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    receipt = dict(passed=False, diagnostic_only=True, scope='CPU capability initialization on API 35 emulator; not a music-analysis benchmark or release gate', errors=[])
    adb = Path(os.environ['ANDROID_HOME']) / 'platform-tools/adb'

    def device(*arguments, timeout=30):
        return subprocess.run([str(adb), *map(str, arguments)], capture_output=True, text=True, timeout=timeout, check=True).stdout

    try:
        provenance = json.loads((EVIDENCE / 'provenance.json').read_text())
        check(provenance.get('prepared') is True and provenance.get('source_hashes') == source_hashes(), 'Prepared source provenance missing or changed')
        receipt['provenance_sha256'] = digest(EVIDENCE / 'provenance.json')
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                if device('shell', 'getprop', 'sys.boot_completed', timeout=10).strip() == '1': break
            except (subprocess.SubprocessError, OSError): pass
            time.sleep(2)
        else: raise RuntimeError('Android emulator did not boot')
        device('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'); device('shell', 'wm', 'dismiss-keyguard')
        for setting in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
            device('shell', 'settings', 'put', 'global', setting, '0')
        target, probe = ROOT / 'candidate' / APK_NAME, ROOT / 'candidate' / PROBE_APK
        check(digest(target) == provenance['diagnostic_apk_sha256'] and digest(probe) == provenance['instrumentation_sha256'], 'Prepared APK changed')
        device('install', '-r', target, timeout=300); device('install', '-r', probe, timeout=90)
        device('shell', 'pm', 'grant', 'com.cyberbasslord.lightforge', 'android.permission.POST_NOTIFICATIONS')
        completed = subprocess.run([str(adb), 'shell', 'am', 'instrument', '-w', 'com.cyberbasslord.lightforge.cpuprobe/com.cyberbasslord.lightforge.AnalysisCpuProbe'], capture_output=True, text=True, timeout=240)
        text = completed.stdout + completed.stderr
        (EVIDENCE / 'instrumentation.log').write_text(text)
        print(text)
        check(completed.returncode == 0 and 'ANALYSIS_CPU_PASS' in text, 'CPU instrumentation failed; inspect instrumentation.log')
        reports = [json.loads(line.split('ANALYSIS_CPU_RESULT ', 1)[1]) for line in text.splitlines() if 'ANALYSIS_CPU_RESULT ' in line]
        check(len(reports) == 1 and reports[0].get('passed') is True, 'Exactly one successful device report is required')
        report = reports[0]; worker = report.get('worker', {})
        for key, source in (('workerSourceSha256', 'web/analysis/worker.js'), ('ortSourceSha256', 'web/analysis/vendor/ort.wasm.min.js')):
            check(worker.get(key) == provenance['source_hashes'][source], 'Device loaded source differs from pinned production: ' + source)
        check(report.get('probeScriptSha256') == provenance['source_hashes']['tests/android/analysis-cpu-worker.js'], 'Device diagnostic script differs')
        check(worker.get('identityExact') is True and worker.get('checkpointRemoved') is True
              and type(worker.get('crossOriginIsolated')) is bool and type(worker.get('sharedArrayBuffer')) is bool
              and all(type(worker.get(name)) is int and worker[name] > 0 for name in ('hardwareConcurrency', 'configuredThreads', 'effectiveThreads')), 'Runtime capability evidence incomplete')
        receipt.update(passed=True, device=report)
    except Exception as error:
        if isinstance(error, subprocess.TimeoutExpired):
            (EVIDENCE / 'instrumentation-timeout.log').write_text(str(error.stdout or '') + str(error.stderr or ''))
        receipt['errors'].append(str(error))
        raise
    finally:
        try: (EVIDENCE / 'logcat.txt').write_text(device('logcat', '-d', '-v', 'threadtime'))
        except Exception: pass
        receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    if args.compile_only:
        compile_probe(ROOT / 'qa/release-2.2.4/native-classes')
        print('CPU instrumentation compiled against the existing published-version classpath; no app APK changed.')
    elif args.run: run_probe()
    else: prepare()

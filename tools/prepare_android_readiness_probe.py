#!/usr/bin/env python3
"""Prepare diagnostic-only APKs from one pinned CI build; never create a release."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile

from package_release import SIGNING_SHA256

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'CyberBASSLord-666/LightForge'
RUN_ID = 34417512894
HEAD_SHA = '222fe9956f91579b34d80b1cad2f993b52b5fbb4'
JOB_ID = 102685553522
ARTIFACT_ID = 10130198948
ARTIFACT_SHA256 = '925e3919c5b43dc81bcad46cc3fb5f84eaeb8c6db72edb89b421bd490bb5bcb0'
APK_SHA256 = 'cb8baf01ac9ba2422ceaa3f8cf0883d9cc2d61a4058d2acab2546fba669d23b6'
APK_BYTES = 1204357470
CI_CERTIFICATE = '0f3d49f3d436df33be3529c7cf7760c00d963561091507af2a9ec218c371e998'
APK_NAME = 'LightForge-2.2.4.apk'


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def payloads(path):
    """Bind every uncompressed ZIP entry except APK/JAR signature metadata."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist()]
        check(len(names) == len(set(names)), 'Duplicate APK ZIP entries')
        for item in archive.infolist():
            if item.filename in {'META-INF/MANIFEST.MF', 'META-INF/LIGHTFOR.SF', 'META-INF/LIGHTFOR.RSA'}:
                continue
            with archive.open(item) as stream:
                result[item.filename] = dict(bytes=item.file_size, compression=item.compress_type,
                                             sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    check({'AndroidManifest.xml', 'resources.arsc', 'classes.dex'} <= result.keys(), 'Required APK payload entries missing')
    return result


def main():
    check(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'This diagnostic input belongs to another repository')
    check(os.environ.get('GITHUB_REF') == 'refs/heads/diagnostics/2.2.4-readiness', 'Diagnostic branch required')
    check(json.loads((ROOT / 'version.json').read_text()) == {'name': '2.2.4', 'code': 20204}, 'Unexpected release version')
    provenance = ROOT / 'diagnostic-input'
    provenance.mkdir(exist_ok=True)
    tool = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
    java, build = tool / 'jdk17/bin', tool / 'android-sdk/build-tools/35.0.0'
    android = tool / 'android-sdk/platforms/android-35/android.jar'
    env = dict(os.environ, JAVA_HOME=str(java.parent))

    def run(*command):
        return subprocess.check_output([str(part) for part in command], cwd=ROOT, env=env, text=True)

    def api(path):
        return json.loads(run('gh', 'api', 'repos/' + REPOSITORY + '/actions/' + path))

    source_run = api('runs/' + str(RUN_ID))
    source_job = api('jobs/' + str(JOB_ID))
    artifact = api('artifacts/' + str(ARTIFACT_ID))
    check(source_run['head_sha'] == HEAD_SHA and source_run['head_repository']['full_name'] == REPOSITORY
          and source_run['path'] == '.github/workflows/verify-v2.yml', 'Input workflow/source mismatch')
    check(source_job['run_id'] == RUN_ID and source_job['head_sha'] == HEAD_SHA
          and source_job['name'] == 'verify' and source_job['status'] == 'completed'
          and source_job['conclusion'] == 'success', 'The pinned verification/build job did not succeed')
    check(artifact['name'] == 'lightforge-2.2.4-ci-candidate' and not artifact['expired']
          and artifact['workflow_run']['id'] == RUN_ID and artifact['workflow_run']['head_sha'] == HEAD_SHA
          and artifact['digest'] == 'sha256:' + ARTIFACT_SHA256, 'Candidate artifact identity mismatch')
    run('git', 'fetch', '--no-tags', 'origin', HEAD_SHA)
    run('git', 'diff', '--exit-code', HEAD_SHA, 'HEAD', '--', 'android', 'web', 'version.json')
    run('git', 'diff', '--exit-code', HEAD_SHA, '--', 'android', 'web', 'version.json')
    summary = dict(diagnostic_only=True, release_eligible=False, input_run_id=RUN_ID,
                   input_head_sha=HEAD_SHA, input_job_id=JOB_ID, input_job_conclusion='success',
                   input_run_conclusion=source_run['conclusion'], input_artifact_id=ARTIFACT_ID,
                   input_artifact_sha256=ARTIFACT_SHA256,
                   probe_head_sha=run('git', 'rev-parse', 'HEAD').strip(),
                   production_source_diff='empty for android/, web/, version.json')
    (provenance / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    archive_path = provenance / 'candidate.zip'
    with archive_path.open('wb') as output:
        subprocess.run(['gh', 'api', 'repos/' + REPOSITORY + '/actions/artifacts/' + str(ARTIFACT_ID) + '/zip'],
                       cwd=ROOT, env=env, stdout=output, check=True)
    check(digest(archive_path) == ARTIFACT_SHA256, 'Downloaded artifact ZIP digest mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        check(len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate candidate artifact entries')
        for name in (APK_NAME, APK_NAME + '.json', APK_NAME + '.sha256'):
            with archive.open(name) as source, (provenance / name).open('wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    archive_path.unlink()
    source_apk = provenance / APK_NAME
    metadata = json.loads((provenance / (APK_NAME + '.json')).read_text())
    check(source_apk.stat().st_size == APK_BYTES == metadata['bytes']
          and digest(source_apk) == APK_SHA256 == metadata['sha256'], 'CI APK does not match its pinned receipt')
    check(metadata['version_name'] == '2.2.4' and metadata['version_code'] == 20204
          and metadata['signing_certificate_sha256'] == CI_CERTIFICATE
          and metadata['update_compatible'] is False and metadata['zip_integrity'] == 'passed'
          and metadata['alignment'] == 'passed' and metadata['signature'] == 'verified', 'Unexpected CI build receipt identity')
    check((provenance / (APK_NAME + '.sha256')).read_text().split()[0] == APK_SHA256, 'CI checksum file mismatch')

    def certificate(apk):
        output = run(build / 'apksigner', 'verify', '--verbose', '--print-certs', apk)
        found = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)', output)
        check(len(found) == 1, 'Expected exactly one verified APK signer')
        return found[0]

    check(certificate(source_apk) == CI_CERTIFICATE != SIGNING_SHA256, 'Input is not the pinned ephemeral CI APK')
    before = payloads(source_apk)
    (provenance / 'input-payloads.json').write_text(json.dumps(before, indent=2) + '\n')
    out = ROOT / 'build/readiness-probe'
    out.mkdir(parents=True, exist_ok=True)
    generated = out / 'generated'
    generated.mkdir(exist_ok=True)
    native = ROOT / 'qa/release-2.2.4/native-classes'
    check(not native.exists(), 'Use a fresh checkout for diagnostic host classes')
    native.mkdir(parents=True)
    run(build / 'aapt2', 'compile', '--dir', ROOT / 'android/res', '-o', out / 'compiled-res.zip')
    run(build / 'aapt2', 'link', '-o', out / 'resources.apk', '-I', android,
        '--manifest', ROOT / 'android/AndroidManifest.xml', '--java', generated,
        '--min-sdk-version', '26', '--target-sdk-version', '35', '--version-code', '20204',
        '--version-name', '2.2.4', '--replace-version', out / 'compiled-res.zip')
    run(java / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(android) + ':' + str(tool / 'onnx/classes.jar'), '-d', native,
        *sorted((ROOT / 'android/src').rglob('*.java')), *sorted(generated.rglob('*.java')))
    candidate = ROOT / 'candidate'
    check(not candidate.exists(), 'Diagnostic output directory must be new')
    candidate.mkdir()
    (ROOT / 'dist').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='readiness-ephemeral-signing-', dir=os.environ['RUNNER_TEMP']) as temporary:
        key = Path(temporary)
        password = key / 'keystore-password.txt'
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(secrets.token_urlsafe(36) + '\n')
        run(java / 'keytool', '-genkeypair', '-keystore', key / 'lightforge-release.jks',
            '-storetype', 'JKS', '-alias', 'lightforge', '-keyalg', 'RSA', '-keysize', '3072',
            '-validity', '2', '-storepass:file', password, '-keypass:file', password,
            '-dname', 'CN=LightForge Readiness Diagnostic, O=Ephemeral CI, C=US', '-noprompt')
        os.chmod(key / 'lightforge-release.jks', 0o600)
        target = candidate / APK_NAME
        run(build / 'apksigner', 'sign', '--ks', key / 'lightforge-release.jks',
            '--ks-key-alias', 'lightforge', '--ks-pass', 'file:' + str(password),
            '--v1-signing-enabled', 'true', '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true',
            '--v4-signing-enabled', 'false', '--alignment-preserved', 'true', '--out', target, source_apk)
        new_certificate = certificate(target)
        check(new_certificate not in (SIGNING_SHA256, CI_CERTIFICATE), 'Fresh diagnostic signer was not created')
        run(build / 'zipalign', '-c', '-P', '16', '4', target)
        after = payloads(target)
        check(before == after, 'Re-signing changed a non-signature APK payload')
        for builder in ('build_android_tests.py', 'build_diagnostics_tests.py'):
            subprocess.run([sys.executable, str(ROOT / 'tools' / builder)], cwd=ROOT,
                           env={**env, 'LIGHTFORGE_SIGNING_DIR': str(key)}, check=True)
        for name in ('background-tests.apk', 'diagnostics-tests.apk'):
            source = ROOT / 'dist' / name
            check(certificate(source) == new_certificate, 'Instrumentation signing identity mismatch')
            shutil.copyfile(source, candidate / name)
    diagnostic_metadata = {**metadata, 'diagnostic_only': True, 'update_compatible': False,
                           'sha256': digest(target), 'bytes': target.stat().st_size,
                           'signing_certificate_sha256': new_certificate,
                           'input_ci_sha256': APK_SHA256, 'input_ci_head_sha': HEAD_SHA}
    (candidate / (APK_NAME + '.json')).write_text(json.dumps(diagnostic_metadata, indent=2) + '\n')
    summary.update(input_apk=metadata, diagnostic_apk=diagnostic_metadata,
                   unchanged_payload_entries=len(before), payload_comparison='all non-signature ZIP entries identical',
                   signing_key_destroyed=True)
    (provenance / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Diagnostic APKs ready: unchanged app payload; newly compiled instrumentation; fresh ephemeral signer.')


if __name__ == '__main__':
    main()

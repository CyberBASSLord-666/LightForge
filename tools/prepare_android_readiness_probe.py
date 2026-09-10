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
import struct
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
PATCH_PATHS = frozenset({'web/app.js', 'web/preview/src/vehicle-preview.js', 'web/preview/vehicle-preview.js'})
PATCH_MANIFEST = ROOT / 'tools/android-readiness-patch.json'


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def payloads(path):
    """Bind entry metadata and raw/uncompressed bytes, excluding only signatures.

    Header offsets and local alignment padding may change during zipalign.
    Central-directory metadata and compressed streams must otherwise survive.
    """
    result = {}
    with zipfile.ZipFile(path) as archive, path.open('rb') as raw:
        check(not archive.comment, 'Unexpected APK archive comment')
        names = [item.filename for item in archive.infolist()]
        check(len(names) == len(set(names)), 'Duplicate APK ZIP entries')
        for item in archive.infolist():
            if item.filename in {'META-INF/MANIFEST.MF', 'META-INF/LIGHTFOR.SF', 'META-INF/LIGHTFOR.RSA'}:
                continue
            raw.seek(item.header_offset)
            header = raw.read(30)
            check(len(header) == 30 and header[:4] == b'PK\x03\x04', 'Invalid local ZIP header')
            name_bytes, extra_bytes = struct.unpack_from('<HH', header, 26)
            raw.seek(name_bytes + extra_bytes, 1)
            compressed_hash, remaining = hashlib.sha256(), item.compress_size
            while remaining:
                block = raw.read(min(1024 * 1024, remaining))
                check(block, 'Truncated compressed APK entry')
                compressed_hash.update(block)
                remaining -= len(block)
            with archive.open(item) as stream:
                result[item.filename] = dict(bytes=item.file_size, compression=item.compress_type,
                                             sha256=hashlib.file_digest(stream, 'sha256').hexdigest(),
                                             compressed_bytes=item.compress_size, compressed_sha256=compressed_hash.hexdigest(),
                                             crc32=item.CRC, date_time=list(item.date_time), create_system=item.create_system,
                                             create_version=item.create_version, extract_version=item.extract_version,
                                             flag_bits=item.flag_bits, internal_attr=item.internal_attr,
                                             external_attr=item.external_attr, comment_hex=item.comment.hex(),
                                             extra_hex=item.extra.hex())
    check({'AndroidManifest.xml', 'resources.arsc', 'classes.dex'} <= result.keys(), 'Required APK payload entries missing')
    return result


def main():
    check(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'This diagnostic input belongs to another repository')
    check(os.environ.get('GITHUB_REF') == 'refs/heads/diagnostics/2.2.4-readiness', 'Diagnostic branch required')
    check(json.loads((ROOT / 'version.json').read_text()) == {'name': '2.2.4', 'code': 20204}, 'Unexpected release version')
    manifest = json.loads(PATCH_MANIFEST.read_text())
    patches = manifest.get('reviewed_web_sha256', {})
    check(manifest.get('diagnostic_only') is True and manifest.get('base_head_sha') == HEAD_SHA
          and manifest.get('base_apk_sha256') == APK_SHA256 and set(patches) == PATCH_PATHS,
          'Patch manifest must identify exactly the three reviewed web assets and pinned base')
    for name, expected in patches.items():
        check(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Reviewed patch SHA256 pin missing: ' + name)
        check((ROOT / name).is_file() and not (ROOT / name).is_symlink()
              and digest(ROOT / name) == expected, 'Reviewed patch source differs from its pin: ' + name)
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
    changed = set(filter(None, run('git', 'diff', '--name-only', '-z', HEAD_SHA, 'HEAD', '--', 'android', 'web', 'version.json').split('\0')))
    check(changed == PATCH_PATHS, 'Production source diff must be exactly the three reviewed web files')
    run('git', 'diff', '--exit-code', 'HEAD', '--', 'android', 'web', 'version.json')
    check(not run('git', 'ls-files', '--others', '--exclude-standard', '--', 'android', 'web', 'version.json').strip(),
          'Unexpected untracked production source')
    summary = dict(diagnostic_only=True, release_eligible=False, input_run_id=RUN_ID,
                   input_head_sha=HEAD_SHA, input_job_id=JOB_ID, input_job_conclusion='success',
                   input_run_conclusion=source_run['conclusion'], input_artifact_id=ARTIFACT_ID,
                   input_artifact_sha256=ARTIFACT_SHA256,
                   probe_head_sha=run('git', 'rev-parse', 'HEAD').strip(),
                   production_source_diff='exactly the three pinned web assets; all other android/, web/, version.json unchanged',
                   reviewed_patch_manifest_sha256=digest(PATCH_MANIFEST), patched_web_sha256=patches)
    (provenance / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    shutil.copyfile(PATCH_MANIFEST, provenance / 'reviewed-web-patch.json')
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
    entries = {'assets/' + name.removeprefix('web/'): name for name in PATCH_PATHS}
    check(set(entries) <= before.keys(), 'A reviewed replacement is absent from the base APK')
    stage = out / 'patch-assets'
    for entry, name in entries.items():
        destination = stage / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
        check(digest(destination) == patches[name], 'Patch changed while staging: ' + name)
    patched = out / 'patched.apk'
    shutil.copyfile(source_apk, patched)
    # Info-ZIP copies untouched compressed streams directly. Only these three
    # explicitly named small assets are compressed; no model is repacked.
    subprocess.run(['zip', '-q', '-X', '-D', '-9', str(patched), *sorted(entries)], cwd=stage, env=env, check=True)
    aligned = out / 'patched-aligned.apk'
    run(build / 'zipalign', '-P', '16', '-f', '4', patched, aligned)
    patched.unlink()
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
            '--v4-signing-enabled', 'false', '--alignment-preserved', 'true', '--out', target, aligned)
        new_certificate = certificate(target)
        check(new_certificate not in (SIGNING_SHA256, CI_CERTIFICATE), 'Fresh diagnostic signer was not created')
        run(build / 'zipalign', '-c', '-P', '16', '4', target)
        after = payloads(target)
        check(before.keys() == after.keys(), 'Diagnostic patch added or removed a non-signature APK entry')
        for entry, original in before.items():
            if entry in entries:
                name = entries[entry]
                check(after[entry]['sha256'] == patches[name] == digest(ROOT / name)
                      and after[entry]['bytes'] == (ROOT / name).stat().st_size,
                      'Patched APK entry differs from the exact reviewed source: ' + name)
            else:
                check(original == after[entry], 'Unreviewed APK entry bytes or metadata changed: ' + entry)
        (provenance / 'patched-payloads.json').write_text(json.dumps(after, indent=2) + '\n')
        aligned.unlink()
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
                           'input_ci_sha256': APK_SHA256, 'input_ci_head_sha': HEAD_SHA,
                           'patched_web_sha256': patches, 'release_eligible': False}
    (candidate / (APK_NAME + '.json')).write_text(json.dumps(diagnostic_metadata, indent=2) + '\n')
    summary.update(input_apk=metadata, diagnostic_apk=diagnostic_metadata,
                   unchanged_payload_entries=len(before) - len(entries), patched_payload_entries=len(entries),
                   payload_comparison='exactly three pinned web replacements; every other non-signature entry metadata and raw/uncompressed bytes identical',
                   signing_key_destroyed=True)
    (provenance / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Diagnostic APKs ready: exactly three reviewed web replacements; all other entry bytes/metadata unchanged; fresh ephemeral signer.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Build/run a diagnostic GAME pool APK with unchanged pinned model payloads."""
from __future__ import annotations

import argparse
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
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from package_release import SIGNING_SHA256
from prepare_android_readiness_probe import payloads, check, digest
from prepare_analysis_cpu_probe import (
    REPOSITORY, RUN_ID, JOB_ID, ARTIFACT_ID, HEAD_SHA, ARTIFACT_SHA256,
    APK_SHA256, APK_BYTES, CI_CERTIFICATE, APK_NAME,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/game-pool-probe'
EVIDENCE = ROOT / 'diagnostic-input/game-pool'
TOOL = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = TOOL / 'jdk17/bin'
BUILD = TOOL / 'android-sdk/build-tools/35.0.0'
ANDROID = TOOL / 'android-sdk/platforms/android-35/android.jar'
ENV = dict(os.environ, JAVA_HOME=str(JAVA.parent))
APP_APK = 'LightForge-game-pool.apk'
PROBE_APK = 'game-pool-probe.apk'
PACKAGE = 'com.cyberbasslord.lightforge'
PROBE_PACKAGE = PACKAGE + '.gamepoolprobe'
WEB_PATCHES = frozenset({
    'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/analysis/worker.js',
    'web/analysis/analyzer.js', 'web/analysis/dsp.js', 'web/analysis/separator-deux.js',
    'web/analysis/separator-mdx.js', 'web/analysis/vocal.js', 'web/analysis/vocal-detail.js',
    'web/analysis/bass-notes.js', 'web/analysis/wav-reader.js', 'web/analysis/stem-cache.js',
    'web/analysis/work-store.js', 'web/background/runner.js', 'web/version.js',
    'web/analysis/ASSET_MANIFEST.json',
})
PROBE_FILES = (
    'tools/prepare_game_pool_probe.py', 'tools/prepare_analysis_cpu_probe.py',
    'tools/prepare_android_readiness_probe.py', 'tools/bootstrap_native_runtime.py',
    'tools/bootstrap_toolchain.py', 'tools/package_release.py', 'tests/android/GamePoolProbe.java',
    'tests/android/game-pool-probe.js', '.github/workflows/probe-game-pool.yml',
)
TIMEOUT_SECONDS = 32 * 60
HOST_RESERVE_BYTES = 1536 * 1024 * 1024


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


def host_preflight():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    value = host_memory()
    value.update(logicalCpus=os.cpu_count(), affinityCpus=len(os.sched_getaffinity(0)),
                 configuredGuestMemoryMiB=8192, configuredGuestCores=4,
                 hostReserveBytes=HOST_RESERVE_BYTES,
                 scope='Host resources are measured separately from the advertised Android guest; no physical-phone equivalence or CPU speedup is implied.')
    value['passed'] = value['totalBytes'] >= 7 * 1024**3 and value['availableBytes'] >= 6 * 1024**3
    (EVIDENCE / 'host-capacity.json').write_text(json.dumps(value, indent=2) + '\n')
    check(value['passed'], 'Runner lacks six GiB of actual available host RAM before emulator launch; use a larger real runner')
    print(json.dumps(value))


def source_hashes():
    files = {*sorted((ROOT / 'android').rglob('*.java')),
             *sorted((ROOT / 'web/analysis').rglob('*.js')),
             *sorted((ROOT / 'web/background').rglob('*.js')),
             *(ROOT / path for path in PROBE_FILES), ROOT / 'version.json',
             ROOT / 'web/version.js', ROOT / 'web/demo/glass-castle.wav',
             ROOT / 'web/analysis/models/game/manifest.json',
             ROOT / 'web/analysis/ASSET_MANIFEST.json',
             ROOT / 'android/AndroidManifest.xml', ROOT / 'android/native-runtime.json',
             ROOT / 'web/analysis/vendor/ort.wasm.min.js'}
    files.update(path for path in (ROOT / 'android/res').rglob('*') if path.is_file())
    for path in files:
        check(path.is_file() and not path.is_symlink(), 'Missing or symlinked source: ' + str(path))
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(files)}


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


def compile_current(with_dex=True):
    """Compile the current app, including ORT, instead of retaining old app DEX."""
    version = current_version()
    run(sys.executable, ROOT / 'tools/bootstrap_native_runtime.py', '--check')
    OUT.mkdir(parents=True, exist_ok=True)
    generated = clean_directory(OUT / 'generated')
    native = clean_directory(OUT / 'target-classes')
    run(BUILD / 'aapt2', 'compile', '--dir', ROOT / 'android/res', '-o', OUT / 'compiled-res.zip')
    run(BUILD / 'aapt2', 'link', '-o', OUT / 'resources.apk', '-I', ANDROID,
        '--manifest', ROOT / 'android/AndroidManifest.xml', '--java', generated,
        '--min-sdk-version', '26', '--target-sdk-version', '35', '--version-code', str(version['code']),
        '--version-name', version['name'], '--replace-version', OUT / 'compiled-res.zip')
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(ANDROID) + ':' + str(TOOL / 'onnx/classes.jar'), '-d', native,
        *sorted((ROOT / 'android/src').rglob('*.java')), *sorted(generated.rglob('*.java')))
    classes = clean_directory(OUT / 'probe-classes')
    run(JAVA / 'javac', '-encoding', 'UTF-8', '--release', '8', '-classpath',
        str(ANDROID) + ':' + str(native) + ':' + str(TOOL / 'onnx/classes.jar'), '-d', classes,
        ROOT / 'tests/android/GamePoolProbe.java')
    if not with_dex:
        return None, None
    classpath = OUT / 'target-classes.jar'
    run(JAVA / 'jar', 'cf', classpath, '-C', native, '.')
    dex = clean_directory(OUT / 'app-dex')
    run(BUILD / 'd8', '--release', '--min-api', '26', '--lib', ANDROID,
        '--output', dex, classpath, TOOL / 'onnx/classes.jar')
    check((dex / 'classes.dex').is_file(), 'Current production DEX missing')
    probe_dex = clean_directory(OUT / 'probe-dex')
    run(BUILD / 'd8', '--lib', ANDROID, '--classpath', classpath,
        '--classpath', TOOL / 'onnx/classes.jar', '--min-api', '26', '--output', probe_dex,
        *sorted(classes.rglob('*.class')))
    return dex, probe_dex


def validate_analysis_manifest(current, baseline, changed):
    """Only changed adapter hashes and the new child may differ from 2.2.4."""
    check(isinstance(current, dict) and isinstance(baseline, dict), 'Analysis asset manifest must be an entry map')
    adapters = {name.removeprefix('web/analysis/') for name in changed
                if name.startswith('web/analysis/') and name.endswith('.js') and name in WEB_PATCHES}
    check(set(current) == set(baseline) | {'game-worker.js'}, 'Analysis manifest added or removed an unreviewed asset')
    check(adapters <= current.keys(), 'A changed analysis adapter is missing from its manifest')
    for name, entry in current.items():
        check(isinstance(entry, dict) and set(entry) == {'bytes', 'sha256'}
              and type(entry['bytes']) is int and entry['bytes'] >= 0
              and isinstance(entry['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', entry['sha256']),
              'Invalid analysis manifest entry: ' + name)
        if name in adapters:
            source = ROOT / 'web/analysis' / name
            check(source.is_file() and not source.is_symlink()
                  and entry == {'bytes': source.stat().st_size, 'sha256': digest(source)},
                  'Changed analysis adapter does not match its actual bytes: ' + name)
        else:
            check(name in baseline and entry == baseline[name],
                  'Unchanged model, runtime, or analysis asset manifest entry differs: ' + name)


def production_diff():
    run('git', 'fetch', '--no-tags', 'origin', HEAD_SHA)
    changed = sorted(filter(None, run('git', 'diff', '--name-only', '-z', '--no-renames',
                                    HEAD_SHA, 'HEAD', '--', 'android', 'web', 'version.json').split('\0')))
    for name in changed:
        java = bool(re.fullmatch(r'android/src/(?:[A-Za-z0-9_]+/)+[A-Za-z0-9_]+\.java', name))
        check(java or name in WEB_PATCHES or name == 'version.json', 'Unreviewed production change: ' + name)
        path = ROOT / name
        check(path.is_file() and not path.is_symlink(), 'Deleted or symlinked production input: ' + name)
    check('web/analysis/game.js' in changed and 'web/analysis/game-worker.js' in changed,
          'Diagnostic branch does not contain the GAME pool implementation')
    manifest_path = 'web/analysis/ASSET_MANIFEST.json'
    validate_analysis_manifest(json.loads((ROOT / manifest_path).read_text()),
                               json.loads(run('git', 'show', HEAD_SHA + ':' + manifest_path)), changed)
    version = current_version()
    expected_version_changes = {'version.json', 'web/version.js'} if version['name'] == '2.2.5' else set()
    check({'version.json', 'web/version.js'} & set(changed) == expected_version_changes,
          'Version source changes do not match the reviewed transition')
    run('git', 'diff', '--exit-code', 'HEAD', '--', 'android', 'web', 'version.json', *PROBE_FILES)
    check(not run('git', 'ls-files', '--others', '--exclude-standard', '--',
                  'android', 'web', 'version.json', *PROBE_FILES).strip(), 'Untracked probe or production source found')
    return changed


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


def prepare():
    check(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Diagnostic belongs to a different repository')
    check(os.environ.get('GITHUB_REF') == 'refs/heads/diagnostics/game-pool', 'Dedicated diagnostic branch required')
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    changed = production_diff()
    summary = dict(diagnostic_only=True, release_eligible=False, input_run_id=RUN_ID, input_head_sha=HEAD_SHA,
                   input_job_id=JOB_ID, input_run_conclusion='success', input_artifact_id=ARTIFACT_ID,
                   input_artifact_sha256=ARTIFACT_SHA256, input_apk_sha256=APK_SHA256,
                   probe_head_sha=run('git', 'rev-parse', 'HEAD').strip(), source_hashes=source_hashes(),
                   production_source_diff=changed, diagnostic_version=current_version(),
                   analysis_manifest_validation='Only reviewed changed adapter hashes and the new game-worker entry differ; all model/runtime and other entries match pinned source',
                   resource_sources_models_vendor_native_runtime='frozen to pinned source; only reviewed version metadata may change')
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_apk = download_base()
    before = payloads(source_apk)
    (EVIDENCE / 'input-payloads.json').write_text(json.dumps(before, indent=2) + '\n')
    app_dex, probe_dex = compile_current()
    replacements = {path.name: path for path in sorted(app_dex.glob('*.dex'))}
    # Keep the frozen resource IDs synchronized with new R classes. The sole
    # permitted resource difference is the reviewed package version transition.
    with zipfile.ZipFile(OUT / 'resources.apk') as archive:
        resource_entries = {'AndroidManifest.xml', 'resources.arsc'} | {name for name in before if name.startswith('res/')}
        check(set(archive.namelist()) == resource_entries, 'Generated resource entry set differs from pinned APK')
        for name in archive.namelist():
            content = archive.read(name)
            if summary['diagnostic_version']['name'] == '2.2.4':
                check(hashlib.sha256(content).hexdigest() == before[name]['sha256'], 'Recompiled resource differs from pinned APK: ' + name)
            else:
                resource = OUT / 'generated-resource-payloads' / name
                resource.parent.mkdir(parents=True, exist_ok=True)
                resource.write_bytes(content)
                replacements[name] = resource
    original_dex = {name for name in before if re.fullmatch(r'classes(?:[2-9][0-9]*)?\.dex', name)}
    check(original_dex == {path.name for path in app_dex.glob('*.dex')}, 'DEX entry layout changed; review before permitting added or deleted DEX')
    check(any(digest(app_dex / name) != before[name]['sha256'] for name in original_dex),
          'App DEX is unchanged; current production Java was not incorporated')
    for name in changed:
        if name in WEB_PATCHES:
            replacements['assets/' + name.removeprefix('web/')] = ROOT / name
    added = set(replacements) - before.keys()
    check(added <= {'assets/analysis/game-worker.js'}, 'Unexpected new app payload entry')
    stage = clean_directory(OUT / 'patch-assets')
    expected = {}
    for entry, source in replacements.items():
        destination = stage / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        expected[entry] = dict(sha256=digest(source), bytes=source.stat().st_size)
        check(digest(destination) == expected[entry]['sha256'], 'Staged replacement changed: ' + entry)
    patched, aligned = OUT / 'patched.apk', OUT / 'aligned-app.apk'
    shutil.copyfile(source_apk, patched)
    # Info-ZIP copies untouched compressed streams directly, including 1+ GiB
    # of model payloads. Only current DEX and the reviewed JS are replaced.
    subprocess.run(['zip', '-q', '-X', '-D', '-9', str(patched), *sorted(replacements)], cwd=stage, env=ENV, check=True)
    run(BUILD / 'zipalign', '-P', '16', '-f', '4', patched, aligned)
    patched.unlink()
    manifest = OUT / 'probe-manifest.xml'
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + PROBE_PACKAGE + '"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="LightForge GAME pool diagnostic"/><instrumentation android:name="' + PACKAGE + '.GamePoolProbe" android:targetPackage="' + PACKAGE + '" android:functionalTest="true"/></manifest>')
    unsigned = OUT / 'unsigned-probe.apk'
    run(BUILD / 'aapt2', 'link', '-o', unsigned, '-I', ANDROID, '--manifest', manifest)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for path in sorted(probe_dex.glob('*.dex')):
            archive.write(path, path.name, compress_type=zipfile.ZIP_STORED)
        archive.write(ROOT / 'tests/android/game-pool-probe.js', 'assets/game-pool-probe.js', compress_type=zipfile.ZIP_DEFLATED)
    aligned_probe = OUT / 'aligned-probe.apk'
    run(BUILD / 'zipalign', '-f', '4', unsigned, aligned_probe)
    candidate = ROOT / 'candidate'
    candidate.mkdir(exist_ok=True)
    target, probe = candidate / APP_APK, candidate / PROBE_APK
    with tempfile.TemporaryDirectory(prefix='game-pool-ephemeral-', dir=os.environ['RUNNER_TEMP']) as temporary:
        key = Path(temporary)
        password = key / 'password.txt'
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(secrets.token_urlsafe(36) + '\n')
        keystore = key / 'probe.jks'
        run(JAVA / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'JKS',
            '-alias', 'lightforge', '-keyalg', 'RSA', '-keysize', '3072', '-validity', '2',
            '-storepass:file', password, '-keypass:file', password,
            '-dname', 'CN=LightForge GAME Pool Diagnostic, O=Ephemeral CI, C=US', '-noprompt')
        os.chmod(keystore, 0o600)
        for source, destination in ((aligned, target), (aligned_probe, probe)):
            run(BUILD / 'apksigner', 'sign', '--ks', keystore, '--ks-key-alias', 'lightforge',
                '--ks-pass', 'file:' + str(password), '--v1-signing-enabled', 'true',
                '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'false', '--alignment-preserved', 'true', '--out', destination, source)
        signer = certificate(target)
        check(signer not in (SIGNING_SHA256, CI_CERTIFICATE) and certificate(probe) == signer, 'Ephemeral signing identities differ')
    run(BUILD / 'zipalign', '-c', '-P', '16', '4', target)
    badging = run(BUILD / 'aapt2', 'dump', 'badging', target)
    check("versionCode='" + str(summary['diagnostic_version']['code']) + "'" in badging
          and "versionName='" + summary['diagnostic_version']['name'] + "'" in badging,
          'Diagnostic manifest does not contain the reviewed version')
    after = payloads(target)
    check(after.keys() == before.keys() | added, 'Unexpected added or removed app payload')
    for entry, details in after.items():
        if entry in expected:
            check(all(details[key] == value for key, value in expected[entry].items()), 'Replacement payload differs: ' + entry)
        else:
            check(details == before[entry], 'Unreviewed payload bytes or metadata changed: ' + entry)
    (EVIDENCE / 'diagnostic-payloads.json').write_text(json.dumps(after, indent=2) + '\n')
    summary.update(signing_key_destroyed=True, diagnostic_apk_sha256=digest(target), diagnostic_apk_bytes=target.stat().st_size,
                   diagnostic_certificate_sha256=signer, instrumentation_sha256=digest(probe),
                   instrumentation_bytes=probe.stat().st_size, replacement_entries=expected,
                   payload_comparison='Only freshly compiled current Java/ORT DEX, approved changed JS and linked resources for the reviewed version transition replaced; every other non-signature entry has identical metadata and raw compressed/uncompressed bytes',
                   unchanged_payload_entries=len(set(before) - replacements.keys()), prepared=True)
    check(summary['source_hashes'] == source_hashes(), 'Source changed during preparation')
    (EVIDENCE / 'provenance.json').write_text(json.dumps(summary, indent=2) + '\n')
    source_apk.unlink()
    aligned.unlink()
    print('Current-production GAME pool diagnostic prepared with exact pinned models/runtime and independent temporary signing.')


def validate_report(report, provenance):
    for name in ('passed', 'exact', 'guardedRestartExact', 'childrenVerified', 'simulatedInterruptedLease'):
        check(report.get(name) is True, 'Missing successful device evidence: ' + name)
    expected_sources = {
        'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/analysis/wav-reader.js',
        'web/analysis/work-store.js', 'web/analysis/vendor/ort.wasm.min.js',
        'web/analysis/models/game/manifest.json', 'web/demo/glass-castle.wav',
    }
    check(set(report.get('sourceHashes', {})) == expected_sources, 'Device source bindings incomplete')
    for name in expected_sources:
        check(report['sourceHashes'][name] == provenance['source_hashes'][name], 'Device loaded different source: ' + name)
    check(report.get('probeScriptSha256') == provenance['source_hashes']['tests/android/game-pool-probe.js'], 'Device diagnostic script differs')
    serial, parallel, cancelled, restart = [report[name] for name in ('serial', 'parallel', 'cancel', 'restart')]
    for mode, value in (('serial', serial), ('parallel', parallel), ('cancel', cancelled), ('restart', restart)):
        check(value.get('passed') is True and value.get('mode') == mode
              and value.get('effectiveThreads') == 1 and value.get('checkpointNamespaceRemoved') is True,
              'Incomplete runtime/release evidence for ' + mode)
    check(len(serial['records']) == len(parallel['records']) == 24 and len(restart['records']) == 12,
          'Required raw graph-output records missing')
    check(re.fullmatch(r'[0-9a-f]{64}', serial['rawOutputsSha256'])
          and serial['rawOutputsSha256'] == parallel['rawOutputsSha256'], 'Serial/parallel raw output digest differs')

    def ordered(records):
        return sorted(records, key=lambda record: (record['pcm'], record['graph'], record['ordinal']))

    check(ordered(serial['records']) == ordered(parallel['records']), 'Raw graph-output records differ')
    expected_calls = [('bd2dur', 0), ('dur2bd', 0), ('encoder', 0), ('estimator', 0)] + [('segmenter', step) for step in range(8)]
    for mode, value in (('serial', serial), ('parallel', parallel)):
        check([(entry['first'], entry['count']) for entry in value['reads']] == [(0, 617400), (441000, 617400)],
              'Probe did not read both complete distinct fourteen-second contexts: ' + mode)
        pcm_ids = [entry['sha256'] for entry in value['reads']]
        check(len(set(pcm_ids)) == 2 and all(re.fullmatch(r'[0-9a-f]{64}', key) for key in pcm_ids), 'Distinct source PCM hashes missing')
        check({entry['pcm'] for entry in value['records']} == set(pcm_ids), 'Raw outputs refer to different source contexts')
        for key in pcm_ids:
            check(sorted((entry['graph'], entry['ordinal']) for entry in value['records'] if entry['pcm'] == key) == expected_calls,
                  'Per-passage graph coverage is incomplete: ' + mode)
    for mode, value in (('serial', serial), ('parallel', parallel)):
        executions = value.get('executions', [])
        check(len(executions) == 24, 'Actual graph execution intervals missing for ' + mode)
        check(sorted((entry['pcm'], entry['graph'], entry['ordinal']) for entry in executions)
              == sorted((entry['pcm'], entry['graph'], entry['ordinal']) for entry in value['records']),
              'Graph execution intervals do not cover every raw output for ' + mode)
        check(all(type(entry.get(name)) in (int, float) and math.isfinite(entry[name])
                  for entry in executions for name in ('startEpochMs', 'endEpochMs'))
              and all(entry['endEpochMs'] >= entry['startEpochMs'] > 0 for entry in executions),
              'Invalid actual graph execution intervals for ' + mode)
    check(all(entry.get('lane') == 'parent' for entry in serial['executions']), 'Serial graph calls used a child lane')
    parent_calls = [entry for entry in parallel['executions'] if entry.get('lane') == 'parent']
    child_calls = [entry for entry in parallel['executions'] if entry.get('lane') == 'child']
    check(len(parent_calls) == len(child_calls) == 12 and parallel.get('concurrentGraphCalls') is True,
          'Parallel graph calls did not execute in both lanes')
    check(any(min(first['endEpochMs'], second['endEpochMs']) > max(first['startEpochMs'], second['startEpochMs'])
              for first in parent_calls for second in child_calls), 'No actual parent/child graph-call overlap observed')
    check(serial['transcriptionJson'] == parallel['transcriptionJson'] and serial['reads'] == parallel['reads'],
          'Transcription bytes or source PCM reads differ')
    for value in (serial, parallel):
        check(set(value['checkpoints']) == {'game-0-0', 'game-0-1'}
              and sorted(value['writes']) == ['game-0-0', 'game-0-1'], 'Passages did not commit exactly once')
    for key in ('game-0-0', 'game-0-1'):
        first, second = serial['checkpoints'][key], parallel['checkpoints'][key]
        check(first['json'] == second['json'] and first['sha256'] == second['sha256']
              == hashlib.sha256(first['json'].encode()).hexdigest(), 'Unrounded checkpoint bytes differ: ' + key)
    check(len(serial['children']) == len(restart['children']) == 0 and len(parallel['children']) == 1,
          'Unexpected child-worker count')
    child = parallel['children'][0]
    check(child.get('inferRequests') == child.get('results') == 1 and child.get('terminated') is True,
          'Parallel child was not created, used, completed and terminated')
    check(cancelled.get('aborted') is True and cancelled.get('cancellation', {}).get('released') is True
          and len(cancelled['children']) == 1 and cancelled['children'][0].get('terminated') is True
          and cancelled['children'][0].get('inferRequests') == 1 and cancelled['writes'] == [],
          'Active cancellation left child work or committed passage data')
    check(len(restart['reads']) == 1, 'Guarded restart source evidence missing')
    first_pcm = restart['reads'][0]['sha256']
    check(ordered([record for record in serial['records'] if record['pcm'] == first_pcm]) == ordered(restart['records'])
          and serial['checkpoints']['game-0-0']['value']['notes'] == restart['restartedNotes'],
          'Guarded serial restart changed raw output records or notes')
    snapshots = report.get('memory', [])
    check(len(snapshots) >= 2 and all(sample.get('lowMemory') is False
          and type(sample.get('availableBytes')) is int and type(sample.get('totalBytes')) is int
          and 0 < sample['availableBytes'] <= sample['totalBytes'] for sample in snapshots),
          'Actual device memory snapshots incomplete or low-memory state observed')
    admissions = report.get('admissions', [])
    expected_admissions = {'initial-admission': 2, 'parallel-admission': 2, 'cancel-admission': 2,
                           'interrupted-lease-simulation': 2, 'guarded-restart-admission': 1}
    check(len(admissions) == len(expected_admissions)
          and {entry.get('phase'): entry.get('parallelism') for entry in admissions} == expected_admissions,
          'Fresh production admission/crash-guard evidence differs')
    check(all(entry.get('availableBytes', 0) >= 6 * 1024**3 and entry.get('totalBytes', 0) >= 7 * 1024**3
              and entry.get('cores', 0) >= 4 and entry.get('process64Bit') is True and entry.get('lowMemory') is False
              for entry in admissions), 'Admission bypassed the actual six-GiB available-memory policy')


def run_probe():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    receipt = dict(passed=False, diagnostic_only=True,
                   scope='Exact serial/parallel GAME output, child-worker lifecycle and memory on API 35 emulator; not a release gate or physical-phone speed claim', errors=[])
    adb = Path(os.environ['ANDROID_HOME']) / 'platform-tools/adb'
    stop = threading.Event()
    sampler = None
    host_watcher = None
    memory_counts = {'samples': 0, 'renderer_samples': 0, 'errors': 0}
    host_safety = {'samples': 0, 'minimumAvailableBytes': None, 'errors': [], 'reserveBytes': HOST_RESERVE_BYTES}

    def device(*arguments, timeout=30):
        return subprocess.run([str(adb), *map(str, arguments)], capture_output=True, text=True, timeout=timeout, check=True).stdout

    def watch_host():
        baseline = host_memory()
        last_write = 0
        with (EVIDENCE / 'host-memory-samples.jsonl').open('w', buffering=1) as output:
            while not stop.is_set():
                try:
                    sample = host_memory()
                    sample['at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    host_safety['samples'] += 1
                    previous = host_safety['minimumAvailableBytes']
                    host_safety['minimumAvailableBytes'] = sample['availableBytes'] if previous is None else min(previous, sample['availableBytes'])
                    reason = None
                    if sample['availableBytes'] < HOST_RESERVE_BYTES:
                        reason = 'Actual host RAM fell below the reserved 1.5 GiB; diagnostic emulator stopped before host starvation'
                    if sample['swapInPages'] != baseline['swapInPages'] or sample['swapOutPages'] != baseline['swapOutPages']:
                        reason = 'Host swap activity appeared during qualification; a swap-backed measurement is not accepted'
                    now = time.monotonic()
                    if now - last_write >= 1 or reason:
                        output.write(json.dumps(sample) + '\n'); last_write = now
                    if reason:
                        host_safety['errors'].append(reason)
                        pid = int((ROOT / 'emulator.pid').read_text().strip())
                        command = Path('/proc') / str(pid) / 'cmdline'
                        check(pid > 1 and command.is_file() and b'LightForgeGamePool' in command.read_bytes(), 'Refusing to stop a process not identified as this diagnostic emulator')
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
                sample = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'monotonic_seconds': time.monotonic()}
                try:
                    sample['system_meminfo'] = device('shell', 'cat', '/proc/meminfo', timeout=10)
                    sample['processes'] = device('shell', 'ps', '-A', '-o', 'PID,PPID,RSS,NAME,ARGS', timeout=10)
                    # Android's compact dump includes system totals and every
                    # renderer/process PSS, even when a renderer restarts.
                    sample['process_pss'] = device('shell', 'dumpsys', 'meminfo', '-c', timeout=15)
                    renderers = [line for line in sample['processes'].splitlines()
                                 if 'sandboxed_process' in line.lower() or 'SandboxedProcessService' in line]
                    sample['renderer_processes'] = renderers
                    memory_counts['samples'] += 1
                    if renderers:
                        memory_counts['renderer_samples'] += 1
                except Exception as error:
                    sample['error'] = str(error)
                    memory_counts['errors'] += 1
                output.write(json.dumps(sample) + '\n')
                stop.wait(10)

    try:
        provenance = json.loads((EVIDENCE / 'provenance.json').read_text())
        check(provenance.get('prepared') is True and provenance.get('source_hashes') == source_hashes(), 'Prepared source provenance missing or changed')
        receipt['provenance_sha256'] = digest(EVIDENCE / 'provenance.json')
        capacity = json.loads((EVIDENCE / 'host-capacity.json').read_text())
        check(capacity.get('passed') is True and capacity.get('configuredGuestMemoryMiB') == 8192
              and capacity.get('hostReserveBytes') == HOST_RESERVE_BYTES, 'Actual host capacity preflight is missing')
        receipt['hostCapacity'] = capacity
        host_watcher = threading.Thread(target=watch_host, name='game-pool-host-reserve', daemon=True)
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
        device('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
        device('shell', 'wm', 'dismiss-keyguard')
        for setting in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
            device('shell', 'settings', 'put', 'global', setting, '0')
        target, probe = ROOT / 'candidate' / APP_APK, ROOT / 'candidate' / PROBE_APK
        check(digest(target) == provenance['diagnostic_apk_sha256'] and digest(probe) == provenance['instrumentation_sha256'], 'Prepared APK changed')
        device('install', '-r', target, timeout=300)
        device('install', '-r', probe, timeout=90)
        device('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
        (EVIDENCE / 'device-properties.txt').write_text(device('shell', 'getprop'))
        device('logcat', '-c')
        sampler = threading.Thread(target=sample_memory, name='game-pool-memory', daemon=True)
        sampler.start()
        started = time.monotonic()
        with (EVIDENCE / 'instrumentation.log').open('w') as output:
            completed = subprocess.run([str(adb), 'shell', 'am', 'instrument', '-w',
                                        PROBE_PACKAGE + '/' + PACKAGE + '.GamePoolProbe'],
                                       stdout=output, stderr=subprocess.STDOUT, text=True, timeout=TIMEOUT_SECONDS)
        receipt['instrumentation_seconds'] = time.monotonic() - started
        text = (EVIDENCE / 'instrumentation.log').read_text()
        print(text)
        check(completed.returncode == 0 and sum(line.strip() == 'GAME_POOL_PASS' for line in text.splitlines()) == 1,
              'GAME pool instrumentation failed; inspect instrumentation.log')
        reports = [json.loads(line.split('GAME_POOL_RESULT ', 1)[1]) for line in text.splitlines() if 'GAME_POOL_RESULT ' in line]
        check(len(reports) == 1 and reports[0].get('passed') is True, 'Exactly one successful device report is required')
        report = reports[0]
        validate_report(report, provenance)
        receipt.update(passed=True, device=report)
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
            (EVIDENCE / 'logcat.txt').write_text(device('logcat', '-d', '-v', 'threadtime'))
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
    check(receipt['passed'], 'GAME pool diagnostic did not pass all host checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--compile-only', action='store_true')
    mode.add_argument('--host-preflight', action='store_true')
    args = parser.parse_args()
    if args.compile_only:
        compile_current(with_dex=False)
        print('Current app Java and independent GAME pool instrumentation compiled against pinned ORT. No DEX built, APK signed or model executed.')
    elif args.run:
        run_probe()
    elif args.host_preflight:
        host_preflight()
    else:
        prepare()

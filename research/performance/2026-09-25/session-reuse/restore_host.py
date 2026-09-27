#!/usr/bin/env python3
"""Restore pinned public CPU research inputs, without running model inference.

Only official public downloads and the public release APK are used. Every file
is checked before use; existing different files and receipts are never replaced.
This preparation does not qualify numerical behavior, performance or a release.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[4]
APK = dict(name='LightForge-2.3.1.apk', bytes=1205116958,
    sha256='af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f',
    url='https://github.com/CyberBASSLord-666/LightForge/releases/download/v2.3.1/LightForge-2.3.1.apk')
JDK = dict(name='jdk17.tar.gz', bytes=193252603,
    sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e',
    url='https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20.1_1.tar.gz')
ANDROID = dict(name='platform-35_r02.zip', bytes=64273788,
    sha256='0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0',
    url='https://dl.google.com/android/repository/platform-35_r02.zip')
JSON_JAR = dict(name='test-json.jar', bytes=90031,
    sha256='c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6',
    url='https://repo.maven.apache.org/maven2/org/json/json/20260719/json-20260719.jar')
ANDROID_JAR = dict(bytes=27092450, sha256='4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b')
MANIFEST_SHA = '51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97'
AUDIO_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'


def pin(path):
    assert path.is_file() and not path.is_symlink(), f'Missing or linked input: {path}'
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def checked(path, expected):
    actual = pin(path)
    assert all(actual[k] == expected[k] for k in actual if k in expected), f'Integrity failure: {path}'
    return actual


def fetch(destination, spec):
    if destination.exists():
        checked(destination, spec)
        print('Verified existing ' + destination.name, flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.download-part')
    print('Downloading ' + destination.name, flush=True)
    with partial.open('xb') as output:
        with urllib.request.urlopen(spec['url'], timeout=240) as response:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                assert total <= spec['bytes'], 'Download exceeds pinned size'
                output.write(block)
    checked(partial, spec)
    assert not destination.exists()
    partial.rename(destination)
    print('Verified download ' + destination.name, flush=True)
    return destination


def extract_member(archive, member, destination, expected):
    if destination.exists():
        return checked(destination, expected)
    info = archive.getinfo(member)
    assert not info.is_dir() and (info.external_attr >> 16) & 0o170000 != 0o120000
    if 'bytes' in expected:
        assert info.file_size == expected['bytes']
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source, destination.open('xb') as output:
        shutil.copyfileobj(source, output)
    return checked(destination, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    toolchain, assets = args.toolchain.resolve(), args.assets.resolve()
    receipt_path = toolchain / 'host-preparation-receipt.json'
    assert not receipt_path.exists(), 'Use a preparation directory without an existing receipt.'
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())['host']
    requests = [(assets / APK['name'], APK), (toolchain / 'downloads' / JDK['name'], JDK),
        (toolchain / 'downloads' / ANDROID['name'], ANDROID), (toolchain / JSON_JAR['name'], JSON_JAR),
        (toolchain / 'onnx' / runtime['name'], runtime)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda row: fetch(*row), requests))
    jdk = toolchain / 'jdk17'
    if not jdk.exists():
        with tempfile.TemporaryDirectory(dir=toolchain) as temp:
            with tarfile.open(toolchain / 'downloads' / JDK['name']) as archive:
                archive.extractall(temp, filter='data')
            shutil.move(str(Path(temp) / 'jdk-17.0.20.1+1'), str(jdk))
    # Compare every installed JDK regular file and link to the verified archive.
    with tarfile.open(toolchain / 'downloads' / JDK['name']) as archive:
        expected_files, expected_links = {}, {}
        for member in archive.getmembers():
            relative = Path(member.name).relative_to('jdk-17.0.20.1+1')
            target = jdk / relative
            if member.isfile():
                with archive.extractfile(member) as source:
                    expected = dict(bytes=member.size, sha256=hashlib.file_digest(source, 'sha256').hexdigest())
                expected_files[relative.as_posix()] = checked(target, expected)
            elif member.issym():
                assert target.is_symlink() and target.readlink().as_posix() == member.linkname
                assert target.resolve().is_relative_to(jdk.resolve()), 'JDK link leaves installation'
                expected_links[relative.as_posix()] = member.linkname
            else:
                assert member.isdir(), 'Unexpected JDK archive member type'
        actual_files = {p.relative_to(jdk).as_posix() for p in jdk.rglob('*') if p.is_file() and not p.is_symlink()}
        actual_links = {p.relative_to(jdk).as_posix() for p in jdk.rglob('*') if p.is_symlink()}
        assert actual_files == set(expected_files) and actual_links == set(expected_links)
    android_jar = toolchain / 'android-sdk/platforms/android-35/android.jar'
    with zipfile.ZipFile(toolchain / 'downloads' / ANDROID['name']) as archive:
        extract_member(archive, 'android-35/android.jar', android_jar, ANDROID_JAR)
    manifest_path = ROOT / 'web/analysis/models/game/manifest.json'
    checked(manifest_path, dict(sha256=MANIFEST_SHA))
    manifest = json.loads(manifest_path.read_text())
    models, audio = assets / 'game', assets / 'glass-castle.wav'
    with zipfile.ZipFile(assets / APK['name']) as archive:
        extract_member(archive, 'assets/analysis/models/game/manifest.json', models / 'manifest.json', pin(manifest_path))
        for name, expected in manifest['files'].items():
            assert Path(name).name == name
            extract_member(archive, 'assets/analysis/models/game/' + name, models / name, expected)
        extract_member(archive, 'assets/demo/glass-castle.wav', audio, dict(sha256=AUDIO_SHA))
        for member in archive.namelist():
            name = Path(member).name
            if member.startswith('assets/analysis/models/game/') and name not in manifest['files'] and name != 'manifest.json':
                if name.lower().startswith(('license', 'notice')):
                    extract_member(archive, member, models / name, dict(bytes=archive.getinfo(member).file_size))
    java_inputs = [jdk / 'bin/java', jdk / 'bin/javac', jdk / 'lib/modules',
        android_jar, toolchain / JSON_JAR['name'], toolchain / 'onnx' / runtime['name']]
    observations = {}
    for binary in ('java', 'javac', 'javap'):
        result = subprocess.run([jdk / 'bin' / binary, '-version'], check=True, text=True, capture_output=True)
        observations[binary] = result.stdout + result.stderr
        assert '17.0.20.1' in observations[binary]
    receipt = dict(schema='lightforge.host-game-research-preparation.v1',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        restoreScript=pin(Path(__file__)),
        archives=[dict(path=str(path), url=spec['url'], **pin(path)) for path, spec in requests],
        javaInputs=[dict(path=str(path), **pin(path)) for path in java_inputs],
        javaVersionObservations=observations,
        installedJdkMatchesPinnedArchive=True, jdkFiles=expected_files, jdkSymlinks=expected_links,
        modelManifestSha256=MANIFEST_SHA,
        models={name: pin(models / name) for name in ['manifest.json', *manifest['files']]},
        publicAudio=dict(path=str(audio), **pin(audio)),
        modelInferenceExecuted=False, cudaExecuted=False, qualityApproved=False,
        target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)
    with receipt_path.open('x') as output:
        json.dump(receipt, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps(dict(receipt=str(receipt_path), **pin(receipt_path),
        gameModelFiles=len(manifest['files']), jdkFiles=len(expected_files), jdkSymlinks=len(expected_links)), indent=2), flush=True)


if __name__ == '__main__':
    main()

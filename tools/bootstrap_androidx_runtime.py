#!/usr/bin/env python3
"""Prepare the pinned official AndroidX runtime and its compatible D8 compiler.

All runtime classes remain in the published JARs. AAR contents, including
resources, manifests, consumer rules, and notices, are extracted without
modification. Java resources retain their original APK-root paths; source-JAR
manifests are excluded explicitly because they are archive metadata.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'android/androidx-runtime.json'
DEST = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain')) / 'androidx'


def _relative(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or path.is_absolute()
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise RuntimeError('Unsafe dependency path: ' + value)
    return Path(*path.parts)


def _pin(item):
    if (not isinstance(item['bytes'], int) or item['bytes'] < 0
            or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
        raise RuntimeError('Invalid dependency integrity pin')


def _manifest():
    manifest = json.loads(MANIFEST.read_text())
    artifacts = manifest['artifacts']
    if manifest['version'] != 1 or len(artifacts) != manifest['artifactCount']:
        raise RuntimeError('Invalid AndroidX dependency manifest version or count')
    ids = set()
    for item in artifacts + [manifest['d8']]:
        _pin(item)
        if len(_relative(item['file']).parts) != 1:
            raise RuntimeError('Dependency archive must have a plain filename')
        if not item['url'].startswith(('https://dl.google.com/dl/android/maven2/',
                                       'https://repo.maven.apache.org/maven2/')):
            raise RuntimeError('Dependency URL must use its official Maven publisher')
    for item in artifacts:
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', item['id'])
                or item['id'] in ids or item['type'] not in ('aar', 'jar')):
            raise RuntimeError('Invalid or duplicate dependency artifact')
        ids.add(item['id'])
        for name, expected in item['extractedFiles'].items():
            _relative(name)
            _pin(expected)
    jars = set()
    for item in manifest['jarPaths'] + manifest['resourceDirs']:
        if item['artifactId'] not in ids:
            raise RuntimeError('Unknown dependency artifact reference')
        _relative(item['path'])
    for item in manifest['jarPaths']:
        key = (item['artifactId'], item['path'])
        if key in jars:
            raise RuntimeError('Duplicate dependency classpath entry')
        jars.add(key)
    paths = set()
    for item in manifest['javaResources']:
        _relative(item['path'])
        _pin(item)
        if ((item['artifactId'], item['jarPath']) not in jars
                or item['path'] in paths or item['path'].endswith('.class')
                or item['path'] == 'META-INF/MANIFEST.MF'):
            raise RuntimeError('Invalid Java resource provenance or path')
        paths.add(item['path'])
    if len(paths) != manifest['runtimeJavaResourceCount']:
        raise RuntimeError('Incorrect Java resource count')
    for item in manifest['licenses']:
        _relative(item['path'])
        _pin(item)
    return manifest


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RuntimeError('Dependency paths must not contain symlinks: ' + str(path))


def _matches(path, expected):
    _no_symlinks(path)
    if not path.is_file() or path.stat().st_size != expected['bytes']:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == expected['sha256']


def _bytes_match(data, expected):
    return len(data) == expected['bytes'] and hashlib.sha256(data).hexdigest() == expected['sha256']


def _write(path, data, expected):
    if not _bytes_match(data, expected):
        raise RuntimeError('Dependency content integrity failure: ' + str(path))
    _no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _archive(path, item, check):
    if _matches(path, item):
        return
    if check:
        raise RuntimeError('Missing or changed dependency archive: ' + str(path))
    _no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'LightForge-dependency-bootstrap/1'})
            with urllib.request.urlopen(request, timeout=120) as response:
                # Bound downloads to the exact published size, plus one byte to detect excess.
                remaining = item['bytes'] + 1
                while remaining:
                    chunk = response.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    stream.write(chunk)
                    remaining -= len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
            if not _matches(temporary, item):
                raise RuntimeError('Dependency download integrity failure: ' + item['file'])
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _zip_entries(archive):
    entries = {}
    for info in archive.infolist():
        name = info.filename.rstrip('/')
        _relative(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise RuntimeError('Dependency archive contains a symlink: ' + name)
        if info.is_dir():
            continue
        if name in entries:
            raise RuntimeError('Dependency archive contains a duplicate entry: ' + name)
        entries[name] = info
    return entries


def _tree_files(root):
    _no_symlinks(root)
    if not root.exists():
        return set()
    result = set()
    for path in root.rglob('*'):
        _no_symlinks(path)
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise RuntimeError('Unexpected dependency filesystem entry: ' + str(path))
    return result


def _extract_aar(path, item, check):
    root = path.parent / 'extracted'
    expected = item['extractedFiles']
    extras = _tree_files(root) - set(expected)
    if extras:
        raise RuntimeError('Unexpected extracted dependency files: ' + ', '.join(sorted(extras)))
    with zipfile.ZipFile(path) as archive:
        entries = _zip_entries(archive)
        if set(entries) != set(expected):
            raise RuntimeError('Published AAR inventory differs from pinned extraction inventory')
        for name, pin in expected.items():
            target = root / _relative(name)
            if _matches(target, pin):
                continue
            if check:
                raise RuntimeError('Missing or changed extracted dependency: ' + str(target))
            _write(target, archive.read(entries[name]), pin)


def _java_resources(manifest, check):
    by_jar = {}
    for item in manifest['javaResources']:
        by_jar.setdefault((item['artifactId'], item['jarPath']), {})[item['path']] = item
    root = DEST / 'java-resources'
    expected_paths = {item['path'] for item in manifest['javaResources']}
    if _tree_files(root) - expected_paths:
        raise RuntimeError('Unexpected files in staged dependency Java resources')
    # Inspect every runtime JAR, including those without retained resources, so
    # a changed closure cannot silently omit a new service, built-in, or notice.
    for jar in manifest['jarPaths']:
        expected = by_jar.get((jar['artifactId'], jar['path']), {})
        with zipfile.ZipFile(DEST / jar['artifactId'] / jar['path']) as archive:
            entries = _zip_entries(archive)
            actual = {name for name in entries if not name.endswith('.class')
                      and name not in manifest['excludedJavaResources']}
            if actual != set(expected):
                raise RuntimeError('Java resource inventory differs from pinned runtime JAR: ' + jar['artifactId'])
            for name, pin in expected.items():
                target = root / _relative(name)
                if _matches(target, pin):
                    continue
                if check:
                    raise RuntimeError('Missing or changed dependency Java resource: ' + name)
                _write(target, archive.read(entries[name]), pin)


def _stage(manifest, destination):
    destination = Path(destination)
    _no_symlinks(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RuntimeError('Java resource staging directory must be empty: ' + str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest['javaResources']:
        name = _relative(item['path'])
        _write(destination / name, (DEST / 'java-resources' / name).read_bytes(), item)
    if _tree_files(destination) != {item['path'] for item in manifest['javaResources']}:
        raise RuntimeError('Java resource staging inventory mismatch')


def _requirements(manifest):
    """Check the published AAR requirements as well as their locked bytes."""
    min_sdk = 1
    compile_sdk = 1
    for item in manifest['artifacts']:
        if item['type'] != 'aar':
            continue
        root = DEST / item['id'] / 'extracted'
        aar_manifest = ET.parse(root / 'AndroidManifest.xml').getroot()
        sdk = aar_manifest.find('uses-sdk')
        if sdk is not None:
            min_sdk = max(min_sdk, int(sdk.get('{http://schemas.android.com/apk/res/android}minSdkVersion', '1')))
        metadata = root / 'META-INF/com/android/build/gradle/aar-metadata.properties'
        if metadata.exists():
            properties = dict(line.split('=', 1) for line in metadata.read_text().splitlines()
                              if line.strip() and not line.lstrip().startswith('#'))
            compile_sdk = max(compile_sdk, int(properties.get('minCompileSdk', '1')))
            if (int(properties.get('minCompileSdkExtension', '0')) != 0
                    or properties.get('coreLibraryDesugaringEnabled', 'false') != 'false'):
                raise RuntimeError('Published AAR requires an unsupported SDK extension or core-library desugaring')
    requirements = manifest['buildRequirements']
    if (min_sdk != requirements['minSdk'] or compile_sdk != requirements['minCompileSdk']
            or min_sdk > requirements['testedMinSdk']
            or compile_sdk > requirements['testedCompileSdk']):
        raise RuntimeError('Published AAR requirements differ from the qualified build contract')


def prepare(check=False, stage_java_resources=None):
    """Verify or prepare all pinned artifacts; optionally stage APK Java resources."""
    manifest = _manifest()
    for item in manifest['licenses']:
        if not _matches(ROOT / _relative(item['path']), item):
            raise RuntimeError('Missing or changed dependency license or notice: ' + item['path'])
    _no_symlinks(DEST)
    if not check:
        DEST.mkdir(parents=True, exist_ok=True)
    for item in manifest['artifacts']:
        path = DEST / item['id'] / item['file']
        _archive(path, item, check)
        if item['type'] == 'aar':
            _extract_aar(path, item, check)
    _requirements(manifest)
    _archive(d8_jar(), manifest['d8'], check)
    _java_resources(manifest, check)
    if stage_java_resources is not None:
        _stage(manifest, stage_java_resources)
    return manifest


def jar_paths():
    """Return only runtime JARs in deterministic dependency order."""
    return [DEST / item['artifactId'] / item['path'] for item in _manifest()['jarPaths']]


def resource_dirs():
    """Return AAR resource directories for standard AAPT2 compilation/linking."""
    return [DEST / item['artifactId'] / item['path'] for item in _manifest()['resourceDirs']]


def classpath():
    return os.pathsep.join(str(path) for path in jar_paths())


def d8_jar():
    """Return the build-time compiler, which must never enter the runtime classpath."""
    return DEST / 'build-tools' / _manifest()['d8']['file']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--stage-java-resources', type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--classpath', action='store_true')
    output.add_argument('--resource-dirs', action='store_true')
    output.add_argument('--d8-jar', action='store_true')
    args = parser.parse_args()
    result = prepare(args.check, args.stage_java_resources)
    if args.classpath:
        print(classpath())
    elif args.resource_dirs:
        print('\n'.join(str(path) for path in resource_dirs()))
    elif args.d8_jar:
        print(d8_jar())
    else:
        print('Verified ' + str(result['artifactCount']) + ' official AndroidX runtime dependencies and '
              + str(result['runtimeJavaResourceCount']) + ' Java resources; D8 '
              + result['d8']['minimumVersion'] + '.')

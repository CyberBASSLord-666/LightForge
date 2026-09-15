#!/usr/bin/env python3
"""Private transport for one verified CI APK; never a release or signing authority."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

PART_BYTES = 400 * 1024**2
MAX_APK_BYTES = 2 * 1024**3
MAX_PARTS = 6
BLOCK = 1024**2


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)


def validate_manifest(manifest, expected_source_commit, expected_apk_sha256):
    require(isinstance(manifest, dict) and set(manifest) == {
        'schema_version', 'kind', 'release', 'candidate', 'preparation', 'apk', 'part_bytes', 'parts',
    }, 'Invalid transfer manifest fields')
    require(manifest['schema_version'] == 1 and manifest['kind'] == 'lightforge-private-apk-transfer',
            'Invalid transfer manifest schema')
    release = manifest['release']
    require(isinstance(release, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', release), 'Invalid release')
    require(isinstance(expected_source_commit, str) and re.fullmatch(r'[0-9a-f]{40}', expected_source_commit),
            'Invalid expected source commit')
    candidate = manifest['candidate']
    require(isinstance(candidate, dict) and isinstance(candidate.get('source'), dict)
            and candidate['source'].get('commit') == expected_source_commit, 'Candidate source differs')
    require(type(candidate.get('artifact_id')) is int and candidate['artifact_id'] > 0
            and _sha(candidate.get('artifact_digest')) and _sha(candidate.get('identity_sha256')),
            'Invalid authoritative candidate artifact binding')
    preparation = manifest['preparation']
    require(isinstance(preparation, dict) and set(preparation) == {'run_id', 'run_attempt'}
            and all(type(value) is int and value > 0 for value in preparation.values()), 'Invalid preparation identity')
    apk = manifest['apk']
    require(isinstance(apk, dict) and set(apk) == {'name', 'bytes', 'sha256'}
            and apk['name'] == 'LightForge-' + release + '.apk'
            and type(apk['bytes']) is int and 0 < apk['bytes'] < MAX_APK_BYTES
            and _sha(expected_apk_sha256) and apk['sha256'] == expected_apk_sha256, 'Invalid expected APK identity')
    require(candidate.get('files', {}).get(apk['name']) == {'bytes': apk['bytes'], 'sha256': apk['sha256']},
            'APK differs from sealed candidate file identity')
    part_bytes = manifest['part_bytes']
    require(type(part_bytes) is int and 0 < part_bytes <= PART_BYTES, 'Invalid part size limit')
    parts = manifest['parts']
    require(isinstance(parts, list) and 1 <= len(parts) <= MAX_PARTS, 'Invalid part count')
    position = 0
    prefix = 'lightforge-signing-' + str(preparation['run_id']) + '-' + str(preparation['run_attempt'])
    for number, part in enumerate(parts, 1):
        require(isinstance(part, dict) and set(part) == {'name', 'artifact', 'offset', 'bytes', 'sha256'},
                'Invalid part fields')
        require(part['name'] == f'part-{number:02d}.bin' and part['artifact'] == prefix + f'-part-{number:02d}',
                'Invalid part identity or ordering')
        require(type(part['offset']) is int and part['offset'] == position
                and type(part['bytes']) is int and part['bytes'] == min(part_bytes, apk['bytes'] - position)
                and part['bytes'] > 0 and _sha(part['sha256']), 'Invalid part range or digest')
        position += part['bytes']
    require(position == apk['bytes'], 'Incomplete part inventory')
    return manifest


def split_apk(apk, release, candidate, preparation, output, *, part_bytes=PART_BYTES):
    apk, output = Path(apk), Path(output)
    require(apk.is_file() and not apk.is_symlink(), 'Candidate APK must be regular')
    size = apk.stat().st_size
    require(0 < size < MAX_APK_BYTES and type(part_bytes) is int and 0 < part_bytes <= PART_BYTES,
            'APK or part size exceeds limits')
    require((size + part_bytes - 1) // part_bytes <= MAX_PARTS, 'APK exceeds part count limit')
    expected = candidate['files']['LightForge-' + release + '.apk']
    require(expected == {'bytes': size, 'sha256': digest(apk)}, 'Candidate APK identity differs')
    output.mkdir(parents=True, exist_ok=False)
    chunks = output / 'parts'
    chunks.mkdir()
    manifest = {'schema_version': 1, 'kind': 'lightforge-private-apk-transfer', 'release': release,
                'candidate': candidate, 'preparation': preparation,
                'apk': {'name': 'LightForge-' + release + '.apk', **expected},
                'part_bytes': part_bytes, 'parts': []}
    prefix = 'lightforge-signing-' + str(preparation['run_id']) + '-' + str(preparation['run_attempt'])
    with apk.open('rb') as source:
        offset = 0
        for number in range(1, (size + part_bytes - 1) // part_bytes + 1):
            name = f'part-{number:02d}.bin'
            remaining = min(part_bytes, size - offset)
            record = {'name': name, 'artifact': prefix + f'-part-{number:02d}', 'offset': offset, 'bytes': remaining}
            checksum = hashlib.sha256()
            with (chunks / name).open('xb') as destination:
                while remaining:
                    block = source.read(min(BLOCK, remaining))
                    require(block, 'Truncated candidate APK')
                    destination.write(block)
                    checksum.update(block)
                    remaining -= len(block)
            record['sha256'] = checksum.hexdigest()
            manifest['parts'].append(record)
            offset += record['bytes']
        require(not source.read(1), 'Candidate APK grew during transfer')
    validate_manifest(manifest, candidate['source']['commit'], expected['sha256'])
    require(digest(apk) == expected['sha256'], 'Candidate APK changed during transfer')
    (output / 'transfer-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


def reassemble(manifest, parts_root, output, *, expected_source_commit, expected_apk_sha256):
    validate_manifest(manifest, expected_source_commit, expected_apk_sha256)
    parts_root, output = Path(parts_root), Path(output)
    require({path.name for path in parts_root.iterdir()} == {part['name'] for part in manifest['parts']},
            'Unexpected or missing part inventory')
    for part in manifest['parts']:
        path = parts_root / part['name']
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == part['bytes'],
                'Missing, unsafe or truncated part: ' + part['name'])
        require(output.resolve() != path.resolve(), 'Output cannot overwrite a part')
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.candidate-transfer-', dir=output.parent)
    try:
        whole = hashlib.sha256()
        with os.fdopen(descriptor, 'wb') as destination:
            for part in manifest['parts']:
                checksum, count = hashlib.sha256(), 0
                with (parts_root / part['name']).open('rb') as source:
                    while block := source.read(BLOCK):
                        count += len(block)
                        require(count <= part['bytes'], 'Part grew during reconstruction')
                        checksum.update(block)
                        whole.update(block)
                        destination.write(block)
                require(count == part['bytes'] and checksum.hexdigest() == part['sha256'],
                        'Part digest or length differs: ' + part['name'])
            destination.flush()
            os.fsync(destination.fileno())
        require(whole.hexdigest() == expected_apk_sha256, 'Reconstructed APK digest differs')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('parts', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--expected-apk-sha256', required=True)
    args = parser.parse_args()
    reassemble(json.loads(args.manifest.read_text(encoding='utf-8')), args.parts, args.output,
               expected_source_commit=args.expected_source_commit, expected_apk_sha256=args.expected_apk_sha256)
    print(json.dumps({'candidate_apk': str(args.output), 'sha256': digest(args.output), 'release_signed': False}))

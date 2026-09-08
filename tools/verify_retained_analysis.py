#!/usr/bin/env python3
"""Retain numeric evidence only for identical measured sources.

An explicit archived version file permits a metadata-only release migration.
Its bytes must match the version hash in the original passing evidence. No
model, runtime or measured source is exempt from exact hash comparison.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def release_number(value):
    require(isinstance(value, str) and re.fullmatch(VERSION_PATTERN, value), 'Invalid release version')
    return tuple(map(int, value.split('.')))


def metadata(path):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and set(value) == {'name', 'code'}, 'Invalid version metadata schema')
    release_number(value['name'])
    require(type(value['code']) is int and 0 < value['code'] <= 2100000000, 'Invalid Android version code')
    return value


def inside(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'Invalid evidence path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), 'Missing or external evidence source: ' + relative)
    require(path.relative_to(root).as_posix() == relative, 'Noncanonical evidence path: ' + relative)
    return path


def retained_receipt(root, from_release, prior_version_file=None):
    root = Path(root).resolve()
    release_number(from_release)
    current_version_path = inside(root, 'version.json')
    current = metadata(current_version_path)
    require(release_number(current['name']) > release_number(from_release), 'Retained evidence requires a newer release')
    prior_relative = 'qa/release-' + from_release + '/analysis-verification.json'
    prior = inside(root, prior_relative)
    prior_hash = digest(prior)
    old = json.loads(prior.read_text())
    require(isinstance(old, dict) and old.get('passed') is True and not old.get('errors'), 'Prior numeric evidence did not pass')
    require(old.get('release') == from_release, 'Prior numeric evidence belongs to another release')
    old_hashes = old.get('source_hashes')
    require(isinstance(old_hashes, dict) and bool(old_hashes), 'Prior evidence has no measured source hashes')
    require(any(name != 'version.json' for name in old_hashes), 'Prior evidence has no measured sources')

    migrated = None
    archived = None
    if prior_version_file is not None:
        archived = inside(root, str(prior_version_file))
        expected = old_hashes.get('version.json')
        require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Prior evidence does not bind version metadata')
        require(digest(archived) == expected, 'Archived version does not match the prior evidence hash')
        previous = metadata(archived)
        require(previous['name'] == from_release, 'Archived version belongs to another release')
        require(current['code'] > previous['code'], 'Android version code must increase')
        migrated = {
            'path': 'version.json', 'classification': 'release metadata; not measured model or algorithm code',
            'prior_version_path': archived.relative_to(root).as_posix(),
            'prior_sha256': expected, 'current_sha256': digest(current_version_path),
            'prior': previous, 'current': current,
            'scope': 'Only the name/code release metadata changed. Every other source bound by prior numeric evidence is byte-identical.'
        }

    current_hashes = {}
    for relative, expected in old_hashes.items():
        require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Invalid measured source hash')
        path = inside(root, relative)
        actual = digest(path)
        if actual != expected:
            require(relative == 'version.json' and migrated is not None,
                    'Measured model/source changed: ' + relative)
        current_hashes[relative] = actual

    checks = ['Every measured model, runtime and analysis-source file bound by prior numeric evidence is byte-identical.',
              'Actual public model runtime and Android background execution require separate current release gates.']
    if migrated:
        checks.append('The explicit predecessor version file matches the original evidence hash; only validated name/code metadata advances monotonically.')
    current_hashes[prior_relative] = prior_hash
    current_hashes['tools/verify_retained_analysis.py'] = digest(inside(root, 'tools/verify_retained_analysis.py'))
    current_hashes['version.json'] = digest(current_version_path)
    if archived:
        current_hashes[archived.relative_to(root).as_posix()] = migrated['prior_sha256']
    for relative, expected in current_hashes.items():
        require(digest(inside(root, relative)) == expected, 'Source changed during evidence retention: ' + relative)
    return {
        'release': current['name'], 'passed': True, 'errors': [], 'checks': checks,
        'source_hashes': current_hashes,
        'retained_evidence': {'release': from_release, 'path': prior_relative, 'sha256': prior_hash},
        'metadata_migrations': [migrated] if migrated else [],
        'scope': 'Retained numeric evidence, not a fresh quality or performance benchmark. All measured model/runtime/source bytes are unchanged; any explicit release-metadata migration is recorded separately. Current browser/model and Android lifecycle checks remain mandatory.',
        'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-release', required=True)
    parser.add_argument('--prior-version-file', help='Repository-relative archived version.json whose exact hash is bound by the prior evidence')
    args = parser.parse_args()
    receipt = retained_receipt(ROOT, args.from_release, args.prior_version_file)
    output = ROOT / ('qa/release-' + receipt['release']) / 'analysis-verification.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=output.parent, prefix='.retained-analysis-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'passed': True, 'retained_release': args.from_release, 'release': receipt['release'],
                      'metadata_migrations': receipt['metadata_migrations']}))


if __name__ == '__main__':
    main()

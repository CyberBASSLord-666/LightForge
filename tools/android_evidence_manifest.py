#!/usr/bin/env python3
"""Create and validate the sealed Android instrumentation evidence artifact.

The Android emulator emits useful diagnostic files even when an instrumentation
suite fails.  Those files are deliberately *not* release evidence.  The only
release-consumable Android artifact is the small, exact file set produced by
this module after both suites have passed and their fresh CI/candidate bindings
have been checked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile


SCHEMA_VERSION = 1
KIND = 'lightforge-android-evidence'
CANDIDATE_KIND = 'lightforge-ci-candidate'
RECEIPTS = {
    'android-background-verification.json': 'receipts/android-background-verification.json',
    'android-diagnostics-verification.json': 'receipts/android-diagnostics-verification.json',
}
HEX64 = re.compile(r'[0-9a-f]{64}')
SHA40 = re.compile(r'[0-9a-f]{40}')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _sha(value, message):
    require(isinstance(value, str) and HEX64.fullmatch(value), message)
    return value


def _artifact_sha(value, message):
    require(isinstance(value, str), message)
    if value.startswith('sha256:'):
        value = value.removeprefix('sha256:')
    return _sha(value, message)


def _int(value, message):
    require(type(value) is int and value > 0, message)
    return value


def _commit(value, message):
    require(isinstance(value, str) and SHA40.fullmatch(value), message)
    return value


def _session(value, message):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), message)
    return value


def _relative(value, message):
    require(isinstance(value, str), message)
    relative = PurePosixPath(value)
    require(relative.as_posix() == value and not relative.is_absolute() and '..' not in relative.parts and value != '.', message)
    return relative


def _regular(root, relative, message):
    relative = _relative(relative, message)
    root = Path(root).resolve()
    raw = root / relative
    require(raw.is_file() and not raw.is_symlink(), message)
    path = raw.resolve()
    require(path.is_relative_to(root), message)
    return path


def _load(path, message):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(message) from error
    require(isinstance(value, dict), message)
    return value


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _fresh_directory(path):
    path = Path(path)
    require(not path.exists(), 'Evidence output directory must be fresh: ' + str(path))
    path.mkdir(parents=True, mode=0o700)
    return path


def _files(release):
    apk = 'LightForge-' + release + '.apk'
    return (apk, 'background-tests.apk', 'diagnostics-tests.apk', apk + '.json', apk + '.sha256')


def _file_inventory(root, names, label):
    root = Path(root).resolve()
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() or path.is_symlink()}
    require(actual == set(names), label + ' contains an unexpected or missing file')
    expected_directories = {str(PurePosixPath(name).parent) for name in names if str(PurePosixPath(name).parent) != '.'}
    actual_directories = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_dir() and not path.is_symlink()}
    require(actual_directories == expected_directories, label + ' contains an unexpected directory')
    result = {}
    for name in names:
        path = _regular(root, name, label + ' contains a non-regular file: ' + name)
        result[name] = {'bytes': path.stat().st_size, 'sha256': sha256_file(path)}
    return result


def _candidate_manifest(candidate_dir, release, head_sha=None):
    root = Path(candidate_dir).resolve()
    names = (*_files(release), 'candidate-manifest.json')
    inventory = _file_inventory(root, names, 'Candidate artifact')
    manifest_path = _regular(root, 'candidate-manifest.json', 'Candidate manifest is missing')
    manifest = _load(manifest_path, 'Candidate manifest is invalid')
    require(set(manifest) == {'schema_version', 'kind', 'release', 'source', 'pipeline', 'source_hashes', 'files'},
            'Candidate manifest fields are invalid')
    require(manifest.get('schema_version') == SCHEMA_VERSION and manifest.get('kind') == CANDIDATE_KIND,
            'Candidate manifest schema is invalid')
    require(manifest.get('release') == release, 'Candidate manifest release differs')
    source = manifest.get('source')
    require(isinstance(source, dict) and set(source) == {'commit', 'tree_sha'}, 'Candidate manifest source is invalid')
    commit = _commit(source.get('commit'), 'Candidate manifest source commit is invalid')
    _commit(source.get('tree_sha'), 'Candidate manifest source tree is invalid')
    if head_sha is not None:
        require(commit == _commit(head_sha, 'Expected source commit is invalid'), 'Candidate manifest source differs from workflow')
    pipeline = manifest.get('pipeline')
    require(isinstance(pipeline, dict) and set(pipeline) == {'run_id', 'run_attempt', 'evidence_session'},
            'Candidate manifest pipeline is invalid')
    _int(pipeline.get('run_id'), 'Candidate manifest run id is invalid')
    _int(pipeline.get('run_attempt'), 'Candidate manifest run attempt is invalid')
    _session(pipeline.get('evidence_session'), 'Candidate manifest evidence session is invalid')
    _source_hashes(manifest.get('source_hashes'), 'Candidate manifest source hashes are invalid')
    files = manifest.get('files')
    require(isinstance(files, dict) and set(files) == set(_files(release)), 'Candidate manifest file inventory is invalid')
    for name in _files(release):
        expected = files[name]
        require(isinstance(expected, dict), 'Candidate manifest file record is invalid: ' + name)
        require(expected.get('bytes') == inventory[name]['bytes'] and _sha(expected.get('sha256'), 'Candidate manifest digest is invalid: ' + name) == inventory[name]['sha256'],
                'Candidate artifact digest differs: ' + name)
    app_metadata = _load(root / ('LightForge-' + release + '.apk.json'), 'Candidate APK metadata is invalid')
    apk_name = 'LightForge-' + release + '.apk'
    require(app_metadata.get('bytes') == inventory[apk_name]['bytes'] and _sha(app_metadata.get('sha256'), 'Candidate APK metadata digest is invalid') == inventory[apk_name]['sha256'],
            'Candidate APK metadata differs from the APK')
    sums = (root / (apk_name + '.sha256')).read_text(encoding='utf-8').strip().split()
    require(sums == [inventory[apk_name]['sha256'], apk_name], 'Candidate APK checksum file differs')
    return {
        'identity_sha256': inventory['candidate-manifest.json']['sha256'],
        'manifest': manifest,
        'files': {name: inventory[name] for name in _files(release)},
    }


def create_candidate(args):
    source = Path(args.input_dir).resolve()
    output = _fresh_directory(args.output_dir)
    names = _files(args.release)
    inventory = _file_inventory(source, names, 'Candidate input')
    apk_metadata = _load(source / ('LightForge-' + args.release + '.apk.json'), 'Candidate APK metadata is invalid')
    apk = 'LightForge-' + args.release + '.apk'
    require(apk_metadata.get('bytes') == inventory[apk]['bytes'] and _sha(apk_metadata.get('sha256'), 'Candidate APK metadata digest is invalid') == inventory[apk]['sha256'],
            'Candidate APK metadata differs from the APK')
    checks = (source / (apk + '.sha256')).read_text(encoding='utf-8').strip().split()
    require(checks == [inventory[apk]['sha256'], apk], 'Candidate APK checksum file differs')
    source_hashes = _load(args.source_hashes, 'Candidate source hashes are invalid')
    _source_hashes(source_hashes, 'Candidate source hashes are invalid')
    for name in names:
        shutil.copyfile(_regular(source, name, 'Candidate input file is invalid: ' + name), output / name)
    manifest = {
        'schema_version': SCHEMA_VERSION,
        'kind': CANDIDATE_KIND,
        'release': args.release,
        'source': {'commit': _commit(args.head_sha, 'Candidate source commit is invalid'),
                   'tree_sha': _commit(args.tree_sha, 'Candidate source tree is invalid')},
        'pipeline': {'run_id': _int(args.run_id, 'Candidate run id is invalid'),
                     'run_attempt': _int(args.run_attempt, 'Candidate run attempt is invalid'),
                     'evidence_session': _session(args.evidence_session, 'Candidate evidence session is invalid')},
        'source_hashes': source_hashes,
        'files': inventory,
    }
    _atomic_json(output / 'candidate-manifest.json', manifest)
    checked = _candidate_manifest(output, args.release, args.head_sha)
    print(json.dumps({'candidate_identity_sha256': checked['identity_sha256']}, sort_keys=True))


def candidate_binding(candidate_dir, release, *, artifact_id, artifact_digest, head_sha=None,
                      run_id=None, run_attempt=None, evidence_session=None):
    candidate = _candidate_manifest(candidate_dir, release, head_sha)
    pipeline = candidate['manifest']['pipeline']
    if run_id is not None:
        require(pipeline['run_id'] == _int(run_id, 'Expected candidate run id is invalid'),
                'Candidate manifest run differs from its recorded producer')
    if run_attempt is not None:
        require(pipeline['run_attempt'] == _int(run_attempt, 'Expected candidate run attempt is invalid'),
                'Candidate manifest attempt differs from its recorded producer')
    if evidence_session is not None:
        require(pipeline['evidence_session'] == _session(evidence_session, 'Expected candidate session is invalid'),
                'Candidate manifest session differs from its recorded producer')
    return {
        'artifact_id': _int(artifact_id, 'Candidate artifact id is invalid'),
        'artifact_digest': _artifact_sha(artifact_digest, 'Candidate artifact digest is invalid'),
        'identity_sha256': candidate['identity_sha256'],
        'source': candidate['manifest']['source'],
        'pipeline': candidate['manifest']['pipeline'],
        'source_hashes': candidate['manifest']['source_hashes'],
        'files': candidate['files'],
    }


def _source_hashes(value, message):
    require(isinstance(value, dict) and value, message)
    for path, checksum in value.items():
        _relative(path, message)
        _sha(checksum, message)
    return value


def validate_source_hashes(source_hashes, source_root):
    """Verify the candidate's declared source bytes in the publisher checkout."""
    hashes = _source_hashes(source_hashes, 'Candidate source hashes are invalid')
    root = Path(source_root).resolve()
    for relative, checksum in hashes.items():
        path = _regular(root, relative, 'Candidate source path is invalid: ' + relative)
        require(sha256_file(path) == checksum, 'Candidate source hash differs: ' + relative)
    return hashes


def _receipt(receipt, name, *, release, run_id, run_attempt, head_sha, session, candidate):
    require(receipt.get('passed') is True and receipt.get('errors') == [], 'Android receipt did not pass: ' + name)
    require(receipt.get('release') == release, 'Android receipt release differs: ' + name)
    hashes = _source_hashes(receipt.get('source_hashes'), 'Android receipt source binding is invalid: ' + name)
    ci = receipt.get('ci')
    require(isinstance(ci, dict), 'Android receipt CI binding is missing: ' + name)
    require(ci == {'run_id': run_id, 'run_attempt': run_attempt, 'head_sha': head_sha, 'evidence_session': session},
            'Android receipt CI binding differs: ' + name)
    require(receipt.get('candidate') == candidate, 'Android receipt candidate binding differs: ' + name)
    return {'passed': True, 'release': release, 'source_hashes_sha256': canonical_sha256(hashes)}


def write_evidence(args):
    run_id = _int(args.run_id, 'Android evidence run id is invalid')
    attempt = _int(args.run_attempt, 'Android evidence run attempt is invalid')
    head = _commit(args.head_sha, 'Android evidence head SHA is invalid')
    session = _session(args.evidence_session, 'Android evidence session is invalid')
    candidate = candidate_binding(args.candidate_dir, args.release, artifact_id=args.candidate_artifact_id,
                                  artifact_digest=args.candidate_artifact_digest, head_sha=head,
                                  run_id=args.candidate_run_id, run_attempt=args.candidate_run_attempt,
                                  evidence_session=args.candidate_evidence_session)
    inputs = {
        'android-background-verification.json': Path(args.background_receipt),
        'android-diagnostics-verification.json': Path(args.diagnostics_receipt),
    }
    output = _fresh_directory(args.output_dir)
    copied = {}
    try:
        for name, source in inputs.items():
            require(source.is_file() and not source.is_symlink(), 'Android receipt is missing: ' + name)
            receipt = _load(source, 'Android receipt is invalid: ' + name)
            summary = _receipt(receipt, name, release=args.release, run_id=run_id, run_attempt=attempt,
                               head_sha=head, session=session, candidate=candidate)
            target = output / RECEIPTS[name]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied[name] = {'path': RECEIPTS[name], 'bytes': target.stat().st_size,
                            'sha256': sha256_file(target), **summary}
        manifest = {
            'schema_version': SCHEMA_VERSION,
            'kind': KIND,
            'release': args.release,
            'pipeline': {'workflow': '.github/workflows/verify-v2.yml', 'run_id': run_id,
                         'run_attempt': attempt, 'head_sha': head, 'evidence_session': session},
            'candidate': candidate,
            'receipts': copied,
        }
        _atomic_json(output / 'android-evidence-manifest.json', manifest)
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    verify_evidence(output, release=args.release, run_id=run_id, run_attempt=attempt, head_sha=head)
    print(json.dumps({'manifest_sha256': sha256_file(output / 'android-evidence-manifest.json')}, sort_keys=True))


def verify_evidence(artifact_dir, *, release, run_id, run_attempt, head_sha):
    root = Path(artifact_dir).resolve()
    expected = {'android-evidence-manifest.json', *RECEIPTS.values()}
    _file_inventory(root, expected, 'Android evidence artifact')
    manifest_path = _regular(root, 'android-evidence-manifest.json', 'Android evidence manifest is missing')
    manifest = _load(manifest_path, 'Android evidence manifest is invalid')
    require(set(manifest) == {'schema_version', 'kind', 'release', 'pipeline', 'candidate', 'receipts'},
            'Android evidence manifest fields are invalid')
    require(manifest.get('schema_version') == SCHEMA_VERSION and manifest.get('kind') == KIND,
            'Android evidence manifest schema is invalid')
    require(manifest.get('release') == release, 'Android evidence manifest release differs')
    pipeline = manifest.get('pipeline')
    require(isinstance(pipeline, dict) and pipeline == {
        'workflow': '.github/workflows/verify-v2.yml', 'run_id': run_id, 'run_attempt': run_attempt,
        'head_sha': head_sha, 'evidence_session': pipeline.get('evidence_session') if isinstance(pipeline, dict) else None,
    }, 'Android evidence manifest pipeline differs')
    session = _session(pipeline['evidence_session'], 'Android evidence manifest session is invalid')
    candidate = manifest.get('candidate')
    require(isinstance(candidate, dict), 'Android evidence manifest candidate is invalid')
    require(set(candidate) == {'artifact_id', 'artifact_digest', 'identity_sha256', 'source', 'pipeline', 'source_hashes', 'files'},
            'Android evidence manifest candidate fields are invalid')
    _int(candidate['artifact_id'], 'Android evidence candidate artifact id is invalid')
    _artifact_sha(candidate['artifact_digest'], 'Android evidence candidate artifact digest is invalid')
    _sha(candidate['identity_sha256'], 'Android evidence candidate identity is invalid')
    source = candidate['source']
    require(isinstance(source, dict) and set(source) == {'commit', 'tree_sha'}
            and _commit(source.get('commit'), 'Android evidence candidate source is invalid') == head_sha,
            'Android evidence candidate source differs')
    _commit(source.get('tree_sha'), 'Android evidence candidate tree is invalid')
    candidate_pipeline = candidate['pipeline']
    require(isinstance(candidate_pipeline, dict) and set(candidate_pipeline) == {'run_id', 'run_attempt', 'evidence_session'},
            'Android evidence candidate pipeline is invalid')
    _int(candidate_pipeline.get('run_id'), 'Android evidence candidate run id is invalid')
    _int(candidate_pipeline.get('run_attempt'), 'Android evidence candidate run attempt is invalid')
    _session(candidate_pipeline.get('evidence_session'), 'Android evidence candidate session is invalid')
    require(candidate_pipeline['run_id'] == run_id, 'Android evidence candidate run differs')
    _source_hashes(candidate.get('source_hashes'), 'Android evidence candidate source hashes are invalid')
    receipt_records = manifest.get('receipts')
    require(isinstance(receipt_records, dict) and set(receipt_records) == set(RECEIPTS), 'Android evidence receipt inventory is invalid')
    for name, relative in RECEIPTS.items():
        record = receipt_records[name]
        require(isinstance(record, dict) and set(record) == {'path', 'bytes', 'sha256', 'passed', 'release', 'source_hashes_sha256'},
                'Android evidence receipt record is invalid: ' + name)
        require(record['path'] == relative and type(record['bytes']) is int and record['bytes'] >= 0 and _sha(record['sha256'], 'Android evidence receipt digest is invalid: ' + name),
                'Android evidence receipt fields are invalid: ' + name)
        path = _regular(root, relative, 'Android evidence receipt is missing: ' + name)
        require(path.stat().st_size == record['bytes'] and sha256_file(path) == record['sha256'], 'Android evidence receipt digest differs: ' + name)
        receipt = _load(path, 'Android evidence receipt is invalid: ' + name)
        summary = _receipt(receipt, name, release=release, run_id=run_id, run_attempt=run_attempt,
                           head_sha=head_sha, session=session, candidate=candidate)
        require(summary == {key: record[key] for key in summary}, 'Android evidence receipt summary differs: ' + name)
    return manifest


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    candidate = commands.add_parser('create-candidate')
    candidate.add_argument('--input-dir', type=Path, required=True)
    candidate.add_argument('--output-dir', type=Path, required=True)
    candidate.add_argument('--release', required=True)
    candidate.add_argument('--run-id', type=int, required=True)
    candidate.add_argument('--run-attempt', type=int, required=True)
    candidate.add_argument('--head-sha', required=True)
    candidate.add_argument('--tree-sha', required=True)
    candidate.add_argument('--evidence-session', required=True)
    candidate.add_argument('--source-hashes', type=Path, required=True)
    write = commands.add_parser('write')
    write.add_argument('--output-dir', type=Path, required=True)
    write.add_argument('--background-receipt', type=Path, required=True)
    write.add_argument('--diagnostics-receipt', type=Path, required=True)
    write.add_argument('--candidate-dir', type=Path, required=True)
    write.add_argument('--candidate-artifact-id', type=int, required=True)
    write.add_argument('--candidate-artifact-digest', required=True)
    write.add_argument('--candidate-run-id', type=int, required=True)
    write.add_argument('--candidate-run-attempt', type=int, required=True)
    write.add_argument('--candidate-evidence-session', required=True)
    write.add_argument('--release', required=True)
    write.add_argument('--run-id', type=int, required=True)
    write.add_argument('--run-attempt', type=int, required=True)
    write.add_argument('--head-sha', required=True)
    write.add_argument('--evidence-session', required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--artifact-dir', type=Path, required=True)
    verify.add_argument('--release', required=True)
    verify.add_argument('--run-id', type=int, required=True)
    verify.add_argument('--run-attempt', type=int, required=True)
    verify.add_argument('--head-sha', required=True)
    return parser


def main():
    args = _parser().parse_args()
    if args.command == 'create-candidate':
        create_candidate(args)
    elif args.command == 'write':
        write_evidence(args)
    else:
        manifest = verify_evidence(args.artifact_dir, release=args.release, run_id=args.run_id,
                                   run_attempt=args.run_attempt, head_sha=_commit(args.head_sha, 'Expected source commit is invalid'))
        print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()

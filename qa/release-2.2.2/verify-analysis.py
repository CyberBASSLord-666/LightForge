#!/usr/bin/env python3
"""Retain 2.2.1 numerical-kernel evidence for the exact reviewed 2.2.2 adapters.

This release-specific protocol is intentionally ineligible for other source
changes. It verifies immutable predecessor evidence, identical kernels/models,
and the exact reviewed diagnostics-only adapter transition. Current complete
browser and Android execution remain separate mandatory release gates.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = 'qa/release-2.2.2/'
PRIOR_COMMIT = 'f80de0d7fd075cf22506c60910e41ea9f625e922'
PRIOR_RECEIPT_SHA256 = 'e029c404496eb141288e506dd496a64eea4db6dab7f4a9a8d4514a83d2617e88'
PRIOR_MANIFEST_SHA256 = '8c33fa5a7b7bafd871b8caf0c476245ff40ede8fe70ee9703f50230c55a3ed71'
CURRENT_MANIFEST_SHA256 = '3757b3406d2e78f5c787a76d76320dc86d7124484468f891e7477eb16e883431'
PRIOR_VERSION_SHA256 = 'c2bb2ac7b87451cfb09a2cc087581ef8217cd7395ec87fdea0dc2e248f83f9df'
CURRENT_VERSION_SHA256 = '260929b89e63c8465eeeebe1f458fefe7b58bda709b546870174abbe1c0e1687'
ADAPTERS = {
    'analyzer.js': {
        'before': 'f9dcbf65960f6b4ca7164f0202354ad4c4e8e9b58efc8d024fa32eacf74a2162',
        'after': '4cc766458c07ef33e3d6bd1185f18e946ca5a173c7c59edb175c01f3db03a234',
        'review': 'Adds stage/progress/error diagnostic calls, preserves bounded worker error stacks and reports structured-clone message errors. Stage order, options, source requests, success values and numeric algorithms are unchanged.'
    },
    'worker.js': {
        'before': '237fc9f20f5947610cf65c307be62792438bc6752cdf76d0dfc65d9def50dfce',
        'after': 'ec0b42a5cb80da756a9a6492dffc6d6d787c6d8ff10079c8808a031abb0bf591',
        'review': 'Only the failure message is bounded to 3072 characters and its optional error stack to 8192 characters. The model inputs, transforms, inference, success results and cleanup are unchanged.'
    }
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'Invalid source path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file() and path.relative_to(root).as_posix() == relative,
            'Missing, noncanonical or external source: ' + relative)
    return path


def verify_bound(root, relative, expected, hashes):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Invalid source hash: ' + relative)
    path = file(root, relative)
    actual = digest(path)
    require(actual == expected, 'Source differs from reviewed evidence: ' + relative)
    hashes[relative] = actual
    return path


def verify_asset(root, relative, entry, hashes):
    require(isinstance(entry, dict) and set(entry) == {'bytes', 'sha256'} and type(entry['bytes']) is int and entry['bytes'] > 0,
            'Invalid asset metadata: ' + relative)
    path = verify_bound(root, 'web/analysis/' + relative, entry['sha256'], hashes)
    require(path.stat().st_size == entry['bytes'], 'Asset byte count changed: ' + relative)


def verify_transition(root, hashes):
    archived_manifest = verify_bound(root, OUT + 'prior-source/ASSET_MANIFEST.json', PRIOR_MANIFEST_SHA256, hashes)
    current_manifest = verify_bound(root, 'web/analysis/ASSET_MANIFEST.json', CURRENT_MANIFEST_SHA256, hashes)
    old, current = json.loads(archived_manifest.read_text()), json.loads(current_manifest.read_text())
    require(set(old) == set(current), 'The reviewed analysis inventory changed')
    differences = {name for name in old if old[name] != current[name]}
    require(differences == set(ADAPTERS), 'Unexpected analysis manifest changes')
    for name, reviewed in ADAPTERS.items():
        require(old[name]['sha256'] == reviewed['before'] and current[name]['sha256'] == reviewed['after'],
                'Unreviewed adapter transition: ' + name)
        previous = verify_bound(root, OUT + 'prior-source/' + name, reviewed['before'], hashes)
        require(previous.stat().st_size == old[name]['bytes'], 'Predecessor adapter byte count changed')
        verify_asset(root, name, current[name], hashes)
    return current


def verify_release(root=ROOT):
    root = Path(root).resolve()
    hashes = {}
    old_version = verify_bound(root, OUT + 'prior-version-2.2.1.json', PRIOR_VERSION_SHA256, hashes)
    current_version = verify_bound(root, 'version.json', CURRENT_VERSION_SHA256, hashes)
    require(json.loads(old_version.read_text()) == {'name': '2.2.1', 'code': 20201}, 'Wrong predecessor version')
    require(json.loads(current_version.read_text()) == {'name': '2.2.2', 'code': 20202}, 'This protocol belongs only to 2.2.2 / 20202')
    original_path = verify_bound(root, OUT + 'prior-source/analysis-verification.json', PRIOR_RECEIPT_SHA256, hashes)
    verify_bound(root, 'qa/release-2.2.1/analysis-verification.json', PRIOR_RECEIPT_SHA256, hashes)
    original = json.loads(original_path.read_text())
    require(original.get('release') == '2.2.1' and original.get('passed') is True and not original.get('errors'), 'Original numerical evidence did not pass')
    require(isinstance(original.get('source_hashes'), dict) and original['source_hashes'], 'Missing original source bindings')
    require(original['source_hashes']['version.json'] == PRIOR_VERSION_SHA256 and
            original['source_hashes']['web/analysis/ASSET_MANIFEST.json'] == PRIOR_MANIFEST_SHA256,
            'Original metadata binding changed')
    require(not any('web/analysis/' + name in original['source_hashes'] for name in ADAPTERS),
            'An adapter was directly measured by the original numeric gate; fresh measurement required')

    current = verify_transition(root, hashes)
    # Every source directly exercised by the old numeric gates stays exact. The
    # metadata cases above are explicit, immutable and version-specific.
    measured = {}
    for relative, expected in original['source_hashes'].items():
        if relative in {'version.json', 'web/analysis/ASSET_MANIFEST.json'}:
            continue
        verify_bound(root, relative, expected, hashes)
        measured[relative] = expected
    base = root / 'web/analysis'
    inventory = {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()
                 and p.name != 'ASSET_MANIFEST.json' and
                 not any(part.startswith('.') or part == '__pycache__' for part in p.relative_to(base).parts)}
    require(inventory == set(current), 'Installed analysis inventory differs from the reviewed manifest')
    # Generated model graphs are verified here in full, but publication's source
    # checkout does not contain them. Preserve all original direct bindings above;
    # record the complete asset inventory separately, anchored to the exact
    # current outer/model manifests. The publisher checks those packaged bytes.
    asset_hashes = {}
    for relative, expected in current.items():
        verify_asset(root, relative, expected, asset_hashes)

    clock_path = file(root, OUT + 'source-clock-verification.json')
    clock_digest = digest(clock_path)
    clock = json.loads(clock_path.read_text())
    require(clock.get('release') == '2.2.2' and clock.get('passed') is True and not clock.get('errors'), 'Current source-clock check did not pass')
    require(clock.get('samples') == 932143 and clock.get('chunks', 0) >= 4 and
            clock.get('contiguousSourceSamples') is True and clock.get('monotonicProgress') is True and
            0 <= clock.get('maxAbsError', float('inf')) < .000002, 'Current source-clock boundaries failed')
    require(isinstance(clock.get('source_hashes'), dict) and clock['source_hashes'], 'Current source-clock binding missing')
    for relative, expected in clock['source_hashes'].items():
        verify_bound(root, relative, expected, hashes)
    hashes[OUT + 'source-clock-verification.json'] = clock_digest
    for relative in [OUT + 'verify-analysis.py', OUT + 'ADAPTER_EVIDENCE_REVIEW.md']:
        hashes[relative] = digest(file(root, relative))
    for relative, expected in {**hashes, **asset_hashes}.items():
        require(digest(file(root, relative)) == expected, 'Source changed during verification: ' + relative)
    return {
        'release': '2.2.2', 'passed': True, 'errors': [], 'source_hashes': hashes,
        'analysis_asset_hashes': asset_hashes,
        'analysis_asset_binding': {
            'manifest_path': 'web/analysis/ASSET_MANIFEST.json',
            'manifest_sha256': CURRENT_MANIFEST_SHA256, 'verified_asset_count': len(asset_hashes),
            'scope': 'Every listed asset was hashed and size-checked during this gate. Generated graphs remain asset bindings rather than new checkout source bindings; all original directly measured source bindings are preserved. Publication independently verifies the complete APK against this exact manifest.'
        },
        'scope': 'Retained numerical kernel/model evidence from immutable 2.2.1 sources, plus a fresh source-clock regression. This is not a fresh neural benchmark, phone-performance measurement or validation of changed adapter execution. The exact reviewed diagnostics/error-adapter bytes and their outer manifest are bound separately; current full-browser pipeline and Android lifecycle gates remain mandatory.',
        'checks': [
            'Immutable 2.2.1 numerical receipt, outer asset manifest and predecessor adapters match the fetched release-candidate commit.',
            'Every directly measured kernel/runtime/source and every model graph retains its exact measured bytes.',
            'The outer asset manifest changes exactly analyzer.js and worker.js to the reviewed diagnostics/error-handling hashes; all other entries and the complete inventory are unchanged.',
            'Fresh 2.2.2 source-clock regression preserves every sample across four overlapping windows including the final odd sample.',
            'Current actual browser pipeline and Android lifecycle execution are separate mandatory release gates; no historical execution result is relabeled as current.'
        ],
        'retained_evidence': {
            'release': '2.2.1', 'source_commit': PRIOR_COMMIT,
            'path': OUT + 'prior-source/analysis-verification.json', 'sha256': PRIOR_RECEIPT_SHA256,
            'original_manifest_sha256': PRIOR_MANIFEST_SHA256,
            'measured_source_hashes': measured,
            'numerical_results': {'wasm': original.get('wasm'), 'native': original.get('native'), 'roles': original.get('roles')}
        },
        'reviewed_adapter_transition': {
            'source_commit': PRIOR_COMMIT, 'prior_manifest_sha256': PRIOR_MANIFEST_SHA256,
            'current_manifest_sha256': CURRENT_MANIFEST_SHA256, 'adapters': ADAPTERS,
            'review': OUT + 'ADAPTER_EVIDENCE_REVIEW.md',
            'required_current_gates': ['analysis-browser-verification.json', 'android-background-verification.json']
        },
        'metadata_migration': {'prior': {'name': '2.2.1', 'code': 20201}, 'current': {'name': '2.2.2', 'code': 20202},
                               'prior_sha256': PRIOR_VERSION_SHA256, 'current_sha256': CURRENT_VERSION_SHA256},
        'fresh_source_clock': {'path': OUT + 'source-clock-verification.json', 'sha256': clock_digest,
                               'samples': clock['samples'], 'maxAbsError': clock['maxAbsError']},
        'limitations': ['Historical neural inference is retained, not rerun.',
                       'Diagnostics and failure handling can affect runtime/lifecycle behavior; separate current browser and Android execution is required.',
                       'No physical phone, full-song performance or Tesla timing result is implied.'],
        'completedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


def main():
    receipt = verify_release()
    output = ROOT / OUT / 'analysis-verification.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=output.parent, prefix='.numeric-kernel-retention-', suffix='.tmp', delete=False) as stream:
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
    print(json.dumps({key: value for key, value in receipt.items() if key not in {'source_hashes', 'analysis_asset_hashes', 'retained_evidence'}}, indent=2))


if __name__ == '__main__':
    main()

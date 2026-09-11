#!/usr/bin/env python3
"""Publish an exact, locally signed CI build after provenance/signature gates."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from apk_archive import verify_native_libraries
from apk_delta import apply_delta, digest
from package_release import SIGNING_SHA256
from release_quality_gate import (
    QUALITY_ARTIFACT,
    RELEASE_WORKFLOW,
    derive_release_scope,
    sha256_canonical_json,
    validate_declaration_receipt,
    validate_publication_evidence,
    validate_release_declaration,
    validate_version,
    version_key,
)

ROOT = Path(__file__).resolve().parents[1]

# These determine whether the release publisher actually applies its
# provenance/signature checks.  A post-CI release-request commit may add
# receipts and deltas, but it may not swap the enforcement code or entrypoint.
RELEASE_ENFORCEMENT_PATHS = (
    '.github/workflows/publish-release.yml',
    'tools/publish_github_release.py',
    'tools/release_quality_gate.py',
    'tools/apk_archive.py',
    'tools/apk_delta.py',
    'tools/package_release.py',
    'tools/performance_quality_gate.py',
    'tools/analysis_benchmark_contract.py',
    'tools/locked_benchmark_runner.py',
    'tools/differential_analysis.py',
)


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def run_bytes(*args, **kwargs):
    """Run a command whose NUL-delimited output must not be normalized."""
    return subprocess.check_output(args, **kwargs)


def api(path):
    return json.loads(run('gh', 'api', path))


def require(value, message):
    if not value:
        raise ValueError(message)


def require_protected_main(environment):
    """Keep protected-ref enforcement inside the publisher, not only YAML."""
    require(environment.get('GITHUB_REF') == 'refs/heads/main', 'Releases publish only from main')
    require(environment.get('LIGHTFORGE_REF_PROTECTED') == 'true', 'Releases publish only from protected main')


def _commit_sha(value, message):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value), message)
    return value


def _tree_sha(record, message):
    tree = record.get('tree') if isinstance(record, dict) else None
    return _commit_sha(tree.get('sha') if isinstance(tree, dict) else None, message)


def _release_version_from_tag(tag):
    require(isinstance(tag, str) and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag), 'Published release tag is not a stable semantic version')
    return {'name': tag[1:], 'code': None}


def _latest_published_release(repo, candidate_version):
    """Return the newest canonical published release older than candidate.

    The base is resolved here, never from a release request.  A source author
    therefore cannot choose an older tree that hides their runtime change.
    """
    candidate = validate_version(candidate_version)
    releases = []
    for page in range(1, 1001):  # bounded: a pathological API response cannot loop forever
        batch = api(f'repos/{repo}/releases?per_page=100&page={page}')
        require(isinstance(batch, list), 'Published release baseline response is invalid')
        releases.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Published release baseline pagination exceeded its safe bound')
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') is True or release.get('prerelease') is True:
            continue
        try:
            parsed = _release_version_from_tag(release.get('tag_name'))
        except ValueError:
            continue
        if version_key({'name': parsed['name'], 'code': 1}) < version_key(candidate):
            candidates.append((version_key({'name': parsed['name'], 'code': 1}), release, parsed['name']))
    require(candidates, 'No prior canonical published release exists for a non-performance waiver')
    candidates.sort(key=lambda item: item[0])
    _, release, name = candidates[-1]
    target = _commit_sha(release.get('target_commitish'), 'Published release target must be an immutable full commit SHA')
    return release, {'name': name, 'target_commit': target}


def _baseline_request(target_commit, base_version):
    """Read the immutable release ledger at a published release target."""
    relative = 'releases/v' + base_version['name'] + '/request.json'
    try:
        value = json.loads(run('git', 'show', target_commit + ':' + relative))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise ValueError('Prior published release has no valid source-bound request ledger') from error
    require(isinstance(value, dict), 'Prior published release request ledger is not an object')
    request_version = validate_version(value.get('version'))
    require(request_version['name'] == base_version['name'], 'Prior published request ledger version disagrees with its tag')
    require(type(value.get('run_id')) is int and value['run_id'] > 0, 'Prior published request ledger has an invalid CI run')
    source = _commit_sha(value.get('source_commit'), 'Prior published request ledger has an invalid source commit')
    delta = value.get('delta_sha256')
    require(isinstance(delta, str) and re.fullmatch('[0-9a-f]{64}', delta), 'Prior published request ledger has an invalid APK delta digest')
    return {
        'version': request_version,
        'run_id': value['run_id'],
        'source_commit': source,
    }


def _verified_published_baseline(repo, candidate_version):
    """Recover the exact source tree that produced the previous release.

    A release tag can point at a later publication/request commit than the CI
    candidate whose APK was released.  The tag locates the immutable request
    ledger; its successful verify-v2 run then identifies the true baseline.
    Missing legacy evidence is a fail-closed performance classification.
    """
    release, published = _latest_published_release(repo, candidate_version)
    target_commit = published['target_commit']
    target_record = api(f'repos/{repo}/git/commits/{target_commit}')
    _tree_sha(target_record, 'Published release target tree is invalid')
    run('git', 'fetch', '--no-tags', 'origin', target_commit)
    ledger = _baseline_request(target_commit, {'name': published['name'], 'code': 1})
    base_run = api(f'repos/{repo}/actions/runs/{ledger["run_id"]}')
    require(isinstance(base_run, dict), 'Prior published release CI record is invalid')
    require(base_run.get('status') == 'completed' and base_run.get('conclusion') == 'success', 'Prior published release CI did not pass')
    require(base_run.get('head_repository', {}).get('full_name') == repo, 'Prior published release CI repository differs')
    require(base_run.get('head_sha') == ledger['source_commit'], 'Prior published release CI source differs from its ledger')
    require(base_run.get('path') == RELEASE_WORKFLOW, 'Prior published release did not use production verification')
    base_record = api(f'repos/{repo}/git/commits/{ledger["source_commit"]}')
    return {
        'tag': 'v' + published['name'],
        'target_commit': target_commit,
        'source_commit': ledger['source_commit'],
        'source_tree_sha': _tree_sha(base_record, 'Prior published release source tree is invalid'),
        'version': ledger['version'],
    }


def _generated_web_version(version):
    value = json.dumps({'name': version['name'], 'code': version['code']}, separators=(',', ':'))
    return (
        '/* Generated by tools/sync_version.py from version.json. */\n'
        '(function(root){const value=Object.freeze(' + value + ');root.LightForgeVersion=value;'
        'if(typeof module!=="undefined"&&module.exports)module.exports=value;})(typeof window!=="undefined"?window:globalThis);\n'
    )


def _generated_web_version_is_exact(source_commit, version):
    try:
        value = run_bytes('git', 'show', source_commit + ':web/version.js').decode('utf-8')
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return False
    return value == _generated_web_version(version)


def _unwaivable_performance_scope(source_commit, source_tree_sha, version, reason):
    """Return a source-bound receipt that can only authorize a full gate.

    A legacy or malformed published baseline must never be interpreted as a
    waiver.  It should not, however, prevent a candidate with independently
    validated PASS_TARGET evidence from shipping.  The returned, hashed reason
    makes that conservative decision auditable in the publisher result.
    """
    release = validate_version(version)
    scope = {
        'schema_version': 1,
        'kind': 'lightforge-release-scope',
        'base_release': None,
        'source': {
            'commit': _commit_sha(source_commit, 'release scope candidate source commit is invalid'),
            'tree_sha': _commit_sha(source_tree_sha, 'release scope candidate source tree is invalid'),
        },
        'release': release,
        'changes': [],
        'classification': 'performance',
        'waiver_blocker': reason,
    }
    # This is not self-referential: the digest is computed before it is added.
    scope['sha256'] = sha256_canonical_json(scope)
    return scope


def _derive_published_release_scope(repo, source_commit, source_tree_sha, version):
    """Fetch the trusted baseline and derive a complete mode-aware scope."""
    try:
        base = _verified_published_baseline(repo, version)
        # The release workflow checks out complete history.  Fetching explicit
        # commits also covers a source candidate that is not HEAD at publication.
        run('git', 'fetch', '--no-tags', 'origin', base['target_commit'], base['source_commit'], source_commit)
        run('git', 'merge-base', '--is-ancestor', base['source_commit'], base['target_commit'])
        run('git', 'merge-base', '--is-ancestor', base['source_commit'], source_commit)
        raw = run_bytes(
            'git', 'diff', '--raw', '--no-abbrev', '--no-renames', '-z',
            base['source_commit'], source_commit,
        )
        return derive_release_scope(
            base_release=base,
            source_commit=source_commit,
            source_tree_sha=source_tree_sha,
            version=version,
            raw_tree_diff=raw,
            generated_web_version_valid=_generated_web_version_is_exact(source_commit, version),
        )
    except (ValueError, subprocess.CalledProcessError):
        return _unwaivable_performance_scope(
            source_commit,
            source_tree_sha,
            version,
            'unavailable_or_unverifiable_published_baseline',
        )


def lookup_release(repo, tag, release_id=None):
    # The /releases/tags endpoint deliberately returns published releases only.
    if release_id is not None:
        release = api(f'repos/{repo}/releases/{release_id}')
    else:
        matches = [r for r in api(f'repos/{repo}/releases?per_page=100') if r['tag_name'] == tag]
        require(len(matches) == 1, 'New draft release was not found uniquely')
        release = matches[0]
    require(release['tag_name'] == tag, 'Release identity mismatch')
    return release


def create_draft(repo, tag, target, notes):
    # The creation response identifies the new draft even before release lists
    # reflect it. Do not rediscover it by tag or retry a successful mutation.
    metadata = {'tag_name': tag, 'target_commitish': target,
                'name': 'LightForge ' + tag.removeprefix('v'), 'body': notes,
                'draft': True, 'prerelease': False}
    release = json.loads(run('gh', 'api', '--method', 'POST',
                             f'repos/{repo}/releases', '--input', '-',
                             input=json.dumps(metadata)))
    require(isinstance(release, dict), 'Invalid draft creation response')
    require(type(release.get('id')) is int and release['id'] > 0,
            'Invalid created draft ID')
    require(release.get('tag_name') == tag and release.get('target_commitish') == target,
            'Created draft identity mismatch')
    require(release.get('draft') is True and release.get('assets') == [],
            'Created release is not an empty draft')
    return release


def update_metadata(repo, release, tag, target, notes, publish=False):
    require(release['draft'], 'Published release metadata cannot be changed')
    # Always include identity: an omitted tag can become an untagged draft.
    metadata = {'tag_name': tag, 'target_commitish': target,
                'name': 'LightForge ' + tag.removeprefix('v'), 'body': notes,
                'draft': not publish, 'prerelease': False}
    if publish:
        metadata['make_latest'] = 'true'
    result = json.loads(run('gh', 'api', '--method', 'PATCH',
                            f'repos/{repo}/releases/{release["id"]}', '--input', '-',
                            input=json.dumps(metadata)))
    require(result['id'] == release['id'] and result['tag_name'] == tag,
            'Updated release identity mismatch')
    require(result['draft'] is (not publish), 'Unexpected publication state')
    return result


def asset_plan(release, expected, allow_metadata_update=False):
    require(release['draft'], 'Published release assets cannot be changed')
    assets = {a['name']: a for a in release['assets']}
    require(len(assets) == len(release['assets']) and set(assets) <= set(expected), 'Unexpected release assets')
    result = []
    for name, info in expected.items():
        asset = assets.get(name)
        if asset and asset.get('state') == 'uploaded' and asset['size'] == info['bytes'] and asset.get('digest') == 'sha256:' + info['sha256']:
            continue
        if asset:
            require(allow_metadata_update and not name.endswith('.apk'), 'Existing release APK or metadata identity mismatch')
        result.append((name, asset is not None))
    return result


def verify_uploaded(release, expected):
    assets = {a['name']: a for a in release['assets']}
    require(len(assets) == len(release['assets']) and set(assets) == set(expected), 'Incomplete or unexpected release assets')
    for name, info in expected.items():
        asset = assets[name]
        require(asset.get('state') == 'uploaded' and asset['size'] == info['bytes'] and asset.get('digest') == 'sha256:' + info['sha256'], 'GitHub uploaded asset identity mismatch: ' + name)


def verify_apk(apk, version):
    toolchain = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
    sdk = toolchain / 'android-sdk/build-tools/35.0.0'
    env = dict(os.environ, JAVA_HOME=str(toolchain / 'jdk17'))
    signature = run(str(sdk / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk), env=env)
    certs = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)', signature)
    require(certs == [SIGNING_SHA256], 'APK does not have the original sole signer')
    run(str(sdk / 'zipalign'), '-c', '-P', '16', '4', str(apk))
    badging = run(str(sdk / 'aapt2'), 'dump', 'badging', str(apk))
    for marker in ["package: name='com.cyberbasslord.lightforge'", f"versionName='{version['name']}'", f"versionCode='{version['code']}'", "minSdkVersion:'26'", "targetSdkVersion:'35'"]:
        require(marker in badging, 'Manifest mismatch: ' + marker)
    require('android.permission.INTERNET' not in badging, 'Unexpected Internet permission')
    with zipfile.ZipFile(apk) as archive:
        verify_native_libraries(archive, ROOT/'android/native-runtime.json')
        require(archive.testzip() is None, 'APK CRC failure')
        names = archive.namelist()
        require(len(set(names)) == len(names), 'Duplicate APK paths')
        bundled = {name for name in names if name.startswith('assets/') and not name.endswith('/')}
        expected = {}
        for path in (ROOT / 'web').rglob('*'):
            relative = path.relative_to(ROOT / 'web')
            if path.is_file() and not any(p.startswith('.') or p in {'node_modules', '__pycache__'} for p in relative.parts):
                expected['assets/' + relative.as_posix()] = digest(path)
        manifest = json.loads((ROOT / 'web/analysis/ASSET_MANIFEST.json').read_text())
        for name, data in manifest.items():
            expected['assets/analysis/' + name] = data['sha256']
        require(bundled == set(expected), 'APK asset inventory differs from source')
        for name, checksum in expected.items():
            with archive.open(name) as stream:
                require(hashlib.file_digest(stream, 'sha256').hexdigest() == checksum, 'Stale APK asset: ' + name)


def _signature_metadata(name):
    """Return whether a ZIP entry is signer metadata, not application payload."""
    if not name.startswith('META-INF/'):
        return False
    leaf = name.rsplit('/', 1)[-1]
    return leaf == 'MANIFEST.MF' or re.fullmatch(r'.+\.(?:SF|RSA|DSA|EC)', leaf) is not None


def apk_payload_manifest(apk):
    """Hash every application ZIP entry without reading an APK into memory."""
    result = {}
    with zipfile.ZipFile(apk) as archive:
        require(archive.testzip() is None, 'APK CRC failure while comparing candidate payload')
        for info in archive.infolist():
            name = info.filename
            require(name and not name.endswith('/'), 'APK contains a directory or empty payload entry')
            if _signature_metadata(name):
                continue
            require(name not in result, 'APK contains duplicate application payload entries')
            with archive.open(info) as stream:
                result[name] = {
                    'bytes': info.file_size,
                    'sha256': hashlib.file_digest(stream, 'sha256').hexdigest(),
                }
    return result


def verify_candidate_payload_equivalence(candidate, final):
    """Forbid a post-CI APK delta from changing code or resources.

    Signing changes ZIP metadata and the APK signing block, so those signer
    records are excluded.  Every application payload—including classes*.dex,
    manifest, resources, native libraries and assets—must remain byte-identical
    to the successful CI candidate before the locally signed APK can publish.
    """
    require(
        apk_payload_manifest(candidate) == apk_payload_manifest(final),
        'Post-CI APK delta changed an application payload from the verified CI candidate',
    )


def source_release_declaration(source_commit, version):
    """Read the explicit rule that was present in the verified candidate tree.

    The source declaration cannot contain its own commit/tree hash.  The
    release request binds its canonical digest to those values after CI has
    produced the candidate commit; see ``validate_declaration_receipt``.
    """
    relative = 'releases/v' + version['name'] + '/quality-gate-declaration.json'
    try:
        declaration = json.loads(run('git', 'show', source_commit + ':' + relative))
    except subprocess.CalledProcessError as error:
        raise ValueError('Release quality declaration was not present in the verified candidate source') from error
    return validate_release_declaration(declaration, version=version)


def single_artifact_file(root, name):
    matches = list(root.rglob(name))
    require(len(matches) == 1 and matches[0].is_file(), 'Quality-gate artifact must contain exactly one ' + name)
    return matches[0]


def verify_release_quality(request, version, repo, ci, source_commit, source_tree_sha):
    """Require an authoritative gate unless the derived source scope is prose-only."""
    declaration = source_release_declaration(source_commit, version)
    receipt = request.get('quality_gate_policy')
    require(isinstance(receipt, dict), 'Release request is missing quality_gate_policy')
    validate_declaration_receipt(
        receipt,
        version=version,
        source_commit=source_commit,
        source_tree_sha=source_tree_sha,
        declaration=declaration,
    )
    scope = _derive_published_release_scope(repo, source_commit, source_tree_sha, version)
    if declaration['requirement'] == 'not_required':
        require(
            scope['classification'] == 'non-performance',
            'Non-performance declaration cannot waive a performance-affecting source change',
        )
        require('quality_gate' not in request, 'Non-performance release policy must not carry an unused quality-gate run')
        return {
            'requirement': 'not_required',
            'classification': 'non-performance',
            'reason': declaration['reason'],
            'scope': scope,
        }
    quality_request = request.get('quality_gate')
    require(isinstance(quality_request, dict) and set(quality_request) == {'run_id'}, 'Performance release requires exactly quality_gate.run_id')
    quality_run_id = quality_request['run_id']
    require(type(quality_run_id) is int and quality_run_id > 0, 'Invalid quality_gate.run_id')
    quality_run = api(f'repos/{repo}/actions/runs/{quality_run_id}')
    require(quality_run.get('status') == 'completed' and quality_run.get('conclusion') == 'success', 'Quality-gate workflow has not passed')
    require(quality_run.get('head_repository', {}).get('full_name') == repo, 'Quality-gate workflow provenance mismatch')
    require(quality_run.get('head_sha') == source_commit, 'Quality-gate workflow commit differs from release candidate')
    quality_commit = api(f'repos/{repo}/git/commits/{quality_run["head_sha"]}')
    transfer = ROOT / 'build/release-quality'
    transfer.mkdir(parents=True, exist_ok=False)
    run('gh', 'run', 'download', str(quality_run_id), '--name', QUALITY_ARTIFACT, '--dir', str(transfer))
    report_path = single_artifact_file(transfer, 'quality-gate-report.json')
    provenance_path = single_artifact_file(transfer, 'quality-gate-provenance.json')
    evidence = validate_publication_evidence(
        json.loads(report_path.read_text()),
        json.loads(provenance_path.read_text()),
        version=version,
        source_declaration=declaration,
        source_commit=source_commit,
        source_tree_sha=source_tree_sha,
        quality_run=quality_run,
        quality_commit=quality_commit,
        release_candidate_run=ci,
        release_candidate_commit=api(f'repos/{repo}/git/commits/{ci["head_sha"]}'),
        report_sha256=digest(report_path),
    )
    return {'requirement': 'performance_quality_gate', 'scope': scope, **evidence}


def main():
    os.chdir(ROOT)
    request = json.loads(Path(sys.argv[1]).read_text())
    version = json.loads((ROOT / 'version.json').read_text())
    repo = os.environ['GH_REPO']
    require(repo == 'CyberBASSLord-666/LightForge', 'Unexpected publishing repository')
    require_protected_main(os.environ)
    require(request['version'] == version, 'Release request version mismatch')
    require(type(request['run_id']) is int and request['run_id'] > 0, 'Invalid CI run')
    source_commit = request['source_commit']
    require(re.fullmatch('[0-9a-f]{40}', source_commit), 'Invalid source commit')
    ci = api(f'repos/{repo}/actions/runs/{request["run_id"]}')
    require(ci['status'] == 'completed' and ci['conclusion'] == 'success', 'Candidate CI has not passed')
    require(ci['head_sha'] == source_commit and ci['head_repository']['full_name'] == repo, 'Candidate provenance mismatch')
    require(ci['path'] == '.github/workflows/verify-v2.yml', 'Candidate used an unexpected workflow')
    run('git', 'fetch', '--no-tags', 'origin', source_commit)
    run(
        'git',
        'diff',
        '--exit-code',
        source_commit,
        'HEAD',
        '--',
        'web',
        'android',
        'version.json',
        *RELEASE_ENFORCEMENT_PATHS,
    )
    source_commit_record = api(f'repos/{repo}/git/commits/{source_commit}')
    source_tree_sha = source_commit_record.get('tree', {}).get('sha')
    require(isinstance(source_tree_sha, str) and re.fullmatch('[0-9a-f]{40}', source_tree_sha), 'Candidate source tree is invalid')
    quality = verify_release_quality(request, version, repo, ci, source_commit, source_tree_sha)
    gates = ROOT / ('qa/release-' + version['name'])
    required_gates=['regression-verification.json', 'browser-verification.json', 'native-verification.json', 'analysis-browser-verification.json', 'analysis-verification.json']
    if version['code']>=20200:required_gates.append('android-background-verification.json')
    if version['code']>=20202:required_gates.append('android-diagnostics-verification.json')
    for name in required_gates:
        evidence = json.loads((gates / name).read_text())
        require(evidence.get('passed') is True and not evidence.get('errors') and evidence['release'] == version['name'], 'Failed gate: ' + name)
        require(bool(evidence.get('source_hashes')), 'Missing source binding: ' + name)
        for relative, checksum in evidence['source_hashes'].items():
            path = (ROOT / relative).resolve()
            require(path.is_relative_to(ROOT) and path.is_file() and digest(path) == checksum, 'Stale evidence: ' + relative)
    transfer = ROOT / 'build/release-candidate'
    transfer.mkdir(parents=True, exist_ok=False)
    run('gh', 'run', 'download', str(request['run_id']), '--name', 'lightforge-' + version['name'] + '-ci-candidate', '--dir', str(transfer))
    apk_name = 'LightForge-' + version['name'] + '.apk'
    candidates = list(transfer.rglob(apk_name))
    require(len(candidates) == 1, 'CI artifact must contain exactly one APK')
    release_dir = ROOT / 'dist'
    release_dir.mkdir(exist_ok=True)
    apk = release_dir / apk_name
    delta_path = ROOT / ('releases/v' + version['name'] + '/signed-apk.delta.json')
    require(digest(delta_path) == request['delta_sha256'], 'Delta identity mismatch')
    apply_delta(candidates[0], json.loads(delta_path.read_text()), apk)
    verify_candidate_payload_equivalence(candidates[0], apk)
    receipt = json.loads((ROOT / 'release-verification.json').read_text())
    require(receipt['release']['sha256'] == digest(apk), 'Packaged release receipt mismatch')
    verify_apk(apk, version)
    sums = release_dir / 'SHA256SUMS.txt'
    sums.write_text(digest(apk) + '  ' + apk_name + '\n')
    tag = 'v' + version['name']
    notes = (ROOT / 'RELEASE_NOTES.md').read_text()
    # Resume only a specifically identified draft; never overwrite its APK.
    resume = request.get('resume_release_id')
    if resume is not None:
        require(type(resume) is int and resume > 0, 'Invalid draft release ID')
        resume_tag = request.get('resume_tag_name', tag)
        require(resume_tag == tag or re.fullmatch(r'untagged-[0-9a-f]+', resume_tag), 'Invalid recovery tag')
        release = lookup_release(repo, resume_tag, resume)
        require(release['draft'] and release['target_commitish'] in {request.get('resume_target_commit'), os.environ['GITHUB_SHA']}, 'Unexpected draft target')
    else:
        release = create_draft(repo, tag, os.environ['GITHUB_SHA'], notes)
    files = {p.name: p for p in [apk, sums, ROOT / 'RELEASE_NOTES.md', ROOT / 'release-verification.json']}
    expected = {name: {'bytes': path.stat().st_size, 'sha256': digest(path)} for name, path in files.items()}
    uploads = asset_plan(release, expected, allow_metadata_update=resume is not None)
    # Validate the existing APK before repairing any explicitly identified draft.
    release = update_metadata(repo, release, tag, os.environ['GITHUB_SHA'], notes)
    for name, replace in uploads:
        args = ['gh', 'release', 'upload', tag, str(files[name])]
        if replace:args.append('--clobber')
        run(*args)
    uploaded = lookup_release(repo, tag, release['id'])
    verify_uploaded(uploaded, expected)
    update_metadata(repo, uploaded, tag, os.environ['GITHUB_SHA'], notes, publish=True)
    published = lookup_release(repo, tag, release['id'])
    require(not published['draft'], 'Release did not publish')
    verify_uploaded(published, expected)
    asset = next(a for a in published['assets'] if a['name'] == apk_name)
    print(json.dumps({'release': published['html_url'], 'apk': asset['browser_download_url'], 'sha256': digest(apk), 'quality_gate': quality}))


if __name__ == '__main__':
    main()

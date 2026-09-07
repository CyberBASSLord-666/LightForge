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

from apk_delta import apply_delta, digest
from package_release import SIGNING_SHA256

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def api(path):
    return json.loads(run('gh', 'api', path))


def require(value, message):
    if not value:
        raise ValueError(message)


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


def main():
    os.chdir(ROOT)
    request = json.loads(Path(sys.argv[1]).read_text())
    version = json.loads((ROOT / 'version.json').read_text())
    repo = os.environ['GH_REPO']
    require(repo == 'CyberBASSLord-666/LightForge', 'Unexpected publishing repository')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'Releases publish only from main')
    require(request['version'] == version, 'Release request version mismatch')
    require(type(request['run_id']) is int and request['run_id'] > 0, 'Invalid CI run')
    source_commit = request['source_commit']
    require(re.fullmatch('[0-9a-f]{40}', source_commit), 'Invalid source commit')
    ci = api(f'repos/{repo}/actions/runs/{request["run_id"]}')
    require(ci['status'] == 'completed' and ci['conclusion'] == 'success', 'Candidate CI has not passed')
    require(ci['head_sha'] == source_commit and ci['head_repository']['full_name'] == repo, 'Candidate provenance mismatch')
    require(ci['path'] == '.github/workflows/verify-v2.yml', 'Candidate used an unexpected workflow')
    run('git', 'fetch', '--no-tags', '--depth=1', 'origin', source_commit)
    run('git', 'diff', '--exit-code', source_commit, 'HEAD', '--', 'web', 'android', 'version.json')
    gates = ROOT / ('qa/release-' + version['name'])
    for name in ['regression-verification.json', 'browser-verification.json', 'native-verification.json', 'analysis-browser-verification.json', 'analysis-verification.json']:
        evidence = json.loads((gates / name).read_text())
        require(evidence.get('passed') is True and not evidence.get('errors') and evidence['release'] == version['name'], 'Failed gate: ' + name)
        require(bool(evidence.get('source_hashes')), 'Missing source binding: ' + name)
        for relative, checksum in evidence['source_hashes'].items():
            path = (ROOT / relative).resolve()
            require(path.is_relative_to(ROOT) and path.is_file() and digest(path) == checksum, 'Stale evidence: ' + relative)
    transfer = ROOT / 'build/release-candidate'
    transfer.mkdir(parents=True, exist_ok=False)
    run('gh', 'run', 'download', str(request['run_id']), '--name', 'lightforge-2.1-ci-candidate', '--dir', str(transfer))
    apk_name = 'LightForge-' + version['name'] + '.apk'
    candidates = list(transfer.rglob(apk_name))
    require(len(candidates) == 1, 'CI artifact must contain exactly one APK')
    release_dir = ROOT / 'dist'
    release_dir.mkdir(exist_ok=True)
    apk = release_dir / apk_name
    delta_path = ROOT / ('releases/v' + version['name'] + '/signed-apk.delta.json')
    require(digest(delta_path) == request['delta_sha256'], 'Delta identity mismatch')
    apply_delta(candidates[0], json.loads(delta_path.read_text()), apk)
    receipt = json.loads((ROOT / 'release-verification.json').read_text())
    require(receipt['release']['sha256'] == digest(apk), 'Packaged release receipt mismatch')
    verify_apk(apk, version)
    sums = release_dir / 'SHA256SUMS.txt'
    sums.write_text(digest(apk) + '  ' + apk_name + '\n')
    tag = 'v' + version['name']
    # Resume only a specifically identified draft; never overwrite its APK.
    resume = request.get('resume_release_id')
    if resume is not None:
        require(type(resume) is int and resume > 0, 'Invalid draft release ID')
        release = lookup_release(repo, tag, resume)
        require(release['draft'] and release['target_commitish'] in {request.get('resume_target_commit'), os.environ['GITHUB_SHA']}, 'Unexpected draft target')
    else:
        run('gh', 'release', 'create', tag, '--draft', '--target', os.environ['GITHUB_SHA'], '--title', 'LightForge ' + version['name'], '--notes-file', 'RELEASE_NOTES.md')
        release = lookup_release(repo, tag)
    files = {p.name: p for p in [apk, sums, ROOT / 'RELEASE_NOTES.md', ROOT / 'release-verification.json']}
    expected = {name: {'bytes': path.stat().st_size, 'sha256': digest(path)} for name, path in files.items()}
    for name, replace in asset_plan(release, expected, allow_metadata_update=resume is not None):
        args = ['gh', 'release', 'upload', tag, str(files[name])]
        if replace:args.append('--clobber')
        run(*args)
    # A draft has no published tag yet. Pin its target to the reviewed main
    # commit after recovery; published tags are never moved by this workflow.
    metadata = ROOT / 'build/release-metadata.json'
    metadata.write_text(json.dumps({'target_commitish': os.environ['GITHUB_SHA'], 'body': (ROOT / 'RELEASE_NOTES.md').read_text()}))
    run('gh', 'api', '--method', 'PATCH', f'repos/{repo}/releases/{release["id"]}', '--input', str(metadata))
    uploaded = lookup_release(repo, tag, release['id'])
    verify_uploaded(uploaded, expected)
    asset = next(a for a in uploaded['assets'] if a['name'] == apk_name)
    run('gh', 'release', 'edit', tag, '--draft=false', '--latest')
    require(not lookup_release(repo, tag, release['id'])['draft'], 'Release did not publish')
    print(json.dumps({'release': uploaded['html_url'], 'apk': asset['browser_download_url'], 'sha256': digest(apk)}))


if __name__ == '__main__':
    main()

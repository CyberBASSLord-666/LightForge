#!/usr/bin/env python3
"""Extract the original public Deux assets from the pinned public release APK.

Requires the completed CPU host preparation. This performs no model inference.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[4]
APK_PIN = dict(bytes=1205116958, sha256='af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f')
MANIFEST_PIN = dict(bytes=50401, sha256='6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9')


def pin(path):
    assert path.is_file() and not path.is_symlink(), f'Missing or linked input: {path}'
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def extract(archive, member, target, expected):
    info = archive.getinfo(member)
    assert not info.is_dir() and (info.external_attr >> 16) & 0o170000 != 0o120000
    assert info.file_size == expected['bytes']
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open('xb') as destination:
            shutil.copyfileobj(source, destination)
    observed = pin(target)
    assert all(observed[k] == expected[k] for k in expected), f'Integrity failure: {target}'
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    toolchain, assets = args.toolchain.resolve(), args.assets.resolve()
    host = toolchain / 'host-preparation-receipt.json'
    host_pin = pin(host)
    assert json.loads(host.read_text())['schema'] == 'lightforge.host-game-research-preparation.v1'
    receipt_path = toolchain / 'deux-preparation-receipt.json'
    assert not receipt_path.exists(), 'The preparation receipt is immutable.'
    apk = assets / 'LightForge-2.3.1.apk'
    assert pin(apk) == APK_PIN
    source_manifest = ROOT / 'web/analysis/models/deux/manifest.json'
    assert pin(source_manifest) == MANIFEST_PIN
    manifest = json.loads(source_manifest.read_text())
    assert len(manifest['files']) == 27
    models = assets / 'deux'
    with zipfile.ZipFile(apk) as archive:
        extract(archive, 'assets/analysis/models/deux/manifest.json', models / 'manifest.json', MANIFEST_PIN)
        observed = {}
        for name, expected in manifest['files'].items():
            assert Path(name).name == name
            observed[name] = extract(archive, 'assets/analysis/models/deux/' + name, models / name, expected)
        notices = {}
        for member in archive.namelist():
            name = Path(member).name
            if member.startswith('assets/analysis/models/deux/') and name.lower().startswith(('license', 'notice')):
                notices[name] = extract(archive, member, models / name, dict(bytes=archive.getinfo(member).file_size))
    assert pin(host) == host_pin and pin(source_manifest) == MANIFEST_PIN
    receipt = dict(schema='lightforge.host-deux-research-preparation.v1',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        hostPreparationReceipt=host_pin, publicApk=APK_PIN, modelManifest=MANIFEST_PIN,
        models=observed, notices=notices, restoreScript=pin(Path(__file__)),
        modelInferenceExecuted=False, cudaExecuted=False, qualityApproved=False,
        target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False)
    with receipt_path.open('x') as output:
        json.dump(receipt, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps(dict(receipt=str(receipt_path), **pin(receipt_path),
        modelFiles=len(observed), modelBytes=sum(p['bytes'] for p in observed.values())), indent=2), flush=True)


if __name__ == '__main__':
    main()

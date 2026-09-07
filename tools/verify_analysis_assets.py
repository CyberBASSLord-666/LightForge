#!/usr/bin/env python3
"""Fail a build if a bundled model, runtime, notice or adapter is missing/stale."""
from pathlib import Path
import hashlib, json

ROOT = Path(__file__).resolve().parents[1]

def verify():
    base = ROOT / 'web/analysis'
    manifest = json.loads((base / 'ASSET_MANIFEST.json').read_text())
    actual = {p.relative_to(base).as_posix() for p in base.rglob('*')
              if p.is_file() and p.name != 'ASSET_MANIFEST.json'
              and not any(x.startswith('.') or x == '__pycache__' for x in p.relative_to(base).parts)}
    if actual != set(manifest):
        raise RuntimeError('Analysis inventory mismatch. Missing: ' + str(sorted(set(manifest)-actual))
                           + '; unexpected: ' + str(sorted(actual-set(manifest)))
                           + '. Reproduce the pinned models using BUILD.md.')
    for name, expected in manifest.items():
        path = base / name
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != expected['bytes'] or digest != expected['sha256']:
            raise RuntimeError('Analysis asset differs from the release manifest: ' + name)
    return len(manifest)

if __name__ == '__main__':
    print('Verified', verify(), 'bundled analysis assets.')

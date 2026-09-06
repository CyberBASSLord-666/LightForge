#!/usr/bin/env python3
"""Reproduce the Spleeter comparison assets; these are not APK runtime models."""
import hashlib
import json
import pathlib
import tempfile
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent / 'models'
manifest = json.loads((BASE / 'separator-model.json').read_text())

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()

for stem, entry in manifest['models'].items():
    target = BASE / entry['file']
    if target.exists() and target.stat().st_size == entry['bytes'] and digest(target) == entry['sha256']:
        print(f'{stem}: already verified')
        continue
    staging = None
    try:
        request = urllib.request.Request(entry['url'], headers={'User-Agent': 'LightForge-Private-Evaluation/1.6'})
        with urllib.request.urlopen(request, timeout=120) as response, tempfile.NamedTemporaryFile(dir=BASE, suffix='.part', delete=False) as out:
            staging = pathlib.Path(out.name)
            total = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                total += len(chunk)
                if total > entry['bytes']:
                    raise ValueError(f'{stem}: download exceeded the pinned model size')
                out.write(chunk)
        if staging.stat().st_size != entry['bytes'] or digest(staging) != entry['sha256']:
            raise ValueError(f'{stem}: model size or SHA-256 differs from the pinned reference')
        staging.replace(target)
        print(f'{stem}: downloaded and verified {entry["bytes"]} bytes')
    finally:
        if staging is not None and staging.exists():
            staging.unlink()

#!/usr/bin/env python3
"""Bind completed model, DSP, streaming and independent quality evidence."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
QA = Path(__file__).resolve().parent

def read(name):
    return json.loads((QA / name).read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_sources(receipt):
    for path, expected in receipt.get('source_hashes', {}).items():
        assert digest(ROOT / path) == expected, f'Source changed after verification: {path}'

model = json.loads((ROOT / 'web/analysis/models/separator-mdx-model.json').read_text())
model_path = ROOT / 'web/analysis/models' / model['file']
assert model_path.stat().st_size == model['bytes']
assert digest(model_path) == model['sha256']
reference = read('separator-mdx-frontend-verification.json')
stream = read('separator-stream-verification.json')
inference = read('separator-mdx-inference-verification.json')
for receipt in [reference, stream, inference]:
    assert receipt['passed']
    verify_sources(receipt)

tracks = {'nightowl', 'stella', 'meaxic', 'grunge', 'falcon', 'sdrnr'}
expected = {f'{track}-{variant}' for track in tracks for variant in ['mix', 'instrumental', 'controlled']} | {'seam-mix'}
rows = {r['track']: r for r in inference['results']}
assert expected <= rows.keys(), f'Missing actual WASM cases: {expected - rows.keys()}'
for track in expected:
    row = rows[track]
    assert row['metadata']['modelSha256'] == model['sha256']
    assert row['metadata']['denoise'] is True
    assert row['metadata']['overlapFraction'] == .5
    assert row['mixtureReconstructionMaxError'] < 1e-6
    assert sum(c['count'] for c in row['chunks']) == row['samples']
    start = 0
    for chunk in row['chunks']:
        assert chunk['start'] == start
        start += chunk['count']
assert rows['seam-mix']['metadata']['chunks'] >= 10

quality = read('separator-quality-comparison.json')
qrows = quality['results']
mdx = {r['track']: r for r in qrows if r['model'] == 'UVR MDX-Net Voc FT polarity ensemble'}
spleeter = {r['track']: r for r in qrows if r['model'] == 'Spleeter 2 stems'}
for track in tracks:
    key = track + '-mix'
    assert mdx[key]['siSdrDb'] > spleeter[key]['siSdrDb'], f'Quality regression on reference {track}'
    assert mdx[key]['lengthMatch'] and mdx[key]['nonFiniteSamples'] == 0
    for variant in ['instrumental', 'controlled']:
        assert f'{track}-{variant}' in mdx

sources = ['web/analysis/separator-mdx.js', 'web/analysis/models/separator-mdx-model.json',
           'web/analysis/models/uvr-mdx-voc-ft.onnx', 'web/analysis/models/MDX-NET-LICENSE.txt',
           'web/analysis/models/UVR-MDX-NOTICE.md',
           'qa/release-1.6.0/test-separator-mdx-frontend.cjs',
           'qa/release-1.6.0/verify-separator-mdx-frontend.py',
           'qa/release-1.6.0/test-separator-stream.cjs', 'qa/release-1.6.0/verify-separator.py']
receipt = {
    'passed': True, 'release': '1.6.0', 'createdAt': datetime.now(timezone.utc).isoformat(),
    'model': model['name'], 'actualWasmTracks': len(expected),
    'frontendReference': reference,
    'streamClock': {k: stream[k] for k in ['samples', 'chunks', 'passes', 'maxExtraSeamJump']},
    'longSeam': rows['seam-mix'],
    'quality': {name: value for name, value in quality['summary'].items()
                if name in ['UVR MDX-Net Voc FT polarity ensemble', 'Spleeter 2 stems']},
    'qualityScope': quality['limitations'],
    'physicalPhoneOrTeslaTested': False,
    'reproductionHarness': {'path': 'qa/release-1.6.0/test-separator.cjs', 'sha256': digest(QA / 'test-separator.cjs'),
        'note': 'The Spleeter-only comparison route was relocated out of web during raw capture; all MDX inference, streaming, model and clock code remained unchanged.'},
    'models': {model['file']: {'sha256': model['sha256'], 'bytes': model['bytes']}},
    'source_hashes': {path: digest(ROOT / path) for path in sources},
    'evidence_hashes': {name: digest(QA / name) for name in [
        'separator-mdx-frontend-verification.json', 'separator-stream-verification.json',
        'separator-mdx-inference-verification.json', 'separator-quality-comparison.json']}
}
(QA / 'separator-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'passed': True, 'actualWasmTracks': len(expected), 'model': model['name'],
                  'quality': receipt['quality']}, indent=2))

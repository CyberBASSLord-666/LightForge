#!/usr/bin/env python3
"""Verify every preserved file in the original LightForge 1.6.0 source snapshot."""
from pathlib import Path
import hashlib
import json
import sys

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'SOURCE_MANIFEST.json').read_text())
errors = []
for item in manifest['files']:
    p = root / item['path']
    if not p.is_file():
        errors.append('Missing: ' + item['path'])
    elif p.stat().st_size != item['bytes'] or hashlib.file_digest(p.open('rb'), 'sha256').hexdigest() != item['sha256']:
        errors.append('Changed: ' + item['path'])
print(json.dumps({'version': manifest['version'], 'files': len(manifest['files']),
                  'passed': not errors, 'errors': errors}, indent=2))
sys.exit(bool(errors))

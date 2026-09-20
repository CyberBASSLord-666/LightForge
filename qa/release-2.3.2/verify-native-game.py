#!/usr/bin/env python3
"""Run production native GAME and original WASM; seal fresh retained note evidence."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from native_game_evidence import (
    ROOT, OUT, RELEASE, SCHEMA, INPUTS, SCOPE, digest, hash_sources, hash_assets,
    loads, retain_json, verify_retained, verify_receipt,
)


def write_atomic(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    output = ROOT / OUT / 'native-game-verification.json'
    receipt = {'schema': SCHEMA, 'release': RELEASE, 'passed': False, 'errors': []}
    # A missing model, failed JVM or interrupted capture cannot inherit old proof.
    write_atomic(output, receipt)
    try:
        session = os.environ.get('LIGHTFORGE_EVIDENCE_SESSION', '')
        if not re.fullmatch(r'[0-9a-f]{32,128}', session):
            raise ValueError('Native GAME verification requires a fresh evidence session')
        receipt.update({
            'evidenceSessionSchema': 'lightforge.evidence-session.v1',
            'evidenceSession': session, 'source_hashes': hash_sources(),
            'analysis_asset_hashes': hash_assets(), 'scope': SCOPE,
            'performanceTargetProven': False, 'androidIntegrationApproved': False,
            'fullAnalysisQualityApproved': False, 'runs': [],
            'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        toolchain = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain')).resolve()
        # Raw PCM/tensors remain temporary and are never committed, packaged or
        # uploaded by this producer. Retained JSON preserves every note delta.
        with tempfile.TemporaryDirectory(prefix='lightforge-native-game-verification-') as temporary:
            work = Path(temporary)
            for item in INPUTS:
                name = item['id']
                pcm = work / (name + '.f32')
                fixture = loads(subprocess.check_output([
                    'node', str(ROOT / OUT / 'prepare-game-input.cjs'), name, str(pcm)],
                    cwd=ROOT, text=True, timeout=60))
                directory = work / name
                subprocess.run([
                    sys.executable, str(ROOT / 'tools/game_benchmark/benchmark_native_process.py'),
                    '--production-engine', '--input', str(pcm),
                    '--models', str(ROOT / 'web/analysis/models/game'), '--output', str(directory),
                    '--toolchain', str(toolchain)], cwd=ROOT, check=True, timeout=1200)
                retained = retain_json(directory, fixture)
                result = verify_retained(ROOT, retained, item)
                relative = OUT + 'native-game-' + name + '-output.json'
                retained_path = ROOT / relative
                write_atomic(retained_path, retained)
                receipt['runs'].append({'path': relative, 'sha256': digest(retained_path),
                                        'bytes': retained_path.stat().st_size, 'result': result})
        receipt['source_hashes_after'] = hash_sources()
        receipt['analysis_asset_hashes_after'] = hash_assets()
        receipt['passed'] = True
        receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        verify_receipt(ROOT, receipt, session, {})
    except Exception as error:
        receipt['passed'] = False
        receipt['errors'] = [str(error)]
        write_atomic(output, receipt)
        raise
    write_atomic(output, receipt)
    print(json.dumps({'passed': True, 'release': RELEASE,
                      'runs': [run['result'] for run in receipt['runs']], 'scope': SCOPE}, indent=2))


if __name__ == '__main__':
    main()

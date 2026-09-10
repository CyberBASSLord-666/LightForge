#!/usr/bin/env python3
"""Source-bound behavior proof for Android threading and disabled GAME pooling.

This runs tiny mocked graph outputs through the actual worker and GAME adapter.
It is a routing/lifecycle proof, not numerical model or Android qualification.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCES = [
    'version.json', 'web/analysis/worker.js', 'web/analysis/analyzer.js',
    'web/analysis/game.js', 'web/analysis/game-worker.js', 'web/background/runner.js',
    'tests/analysis-thread-policy.test.cjs', 'qa/speedup-exact/wasm-policy/verify.py',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    receipt = {
        'schema': 'lightforge-wasm-thread-policy-1', 'release': '2.2.5', 'passed': False,
        'scope': 'Actual worker/analyzer/GAME routing with mocked graph outputs; no numerical model or Android runtime claim.',
        'source_hashes': {name: digest(ROOT / name) for name in SOURCES},
        'poolShipping': False, 'errors': [],
    }
    atomic(OUT / 'verification.json', receipt)
    try:
        if json.loads((ROOT / 'version.json').read_text()) != {'name': '2.2.5', 'code': 20205}:
            raise AssertionError('This qualification belongs to LightForge 2.2.5 / 20205')
        worker = (ROOT / 'web/analysis/worker.js').read_text()
        if 'const GAME_PASSAGE_POOL_ENABLED=false;' not in worker:
            raise AssertionError('The production GAME pool activation constant is not explicitly disabled')
        command = ['node', '--test', '--test-reporter=tap', 'tests/analysis-thread-policy.test.cjs']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        log = OUT / 'behavior-tests.log'
        log.write_text(result.stdout + result.stderr)
        counts = {}
        for name in ['tests', 'suites', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
            matches = re.findall(r'^# ' + name + r' (\d+)$', result.stdout, re.M)
            if len(matches) != 1:
                raise AssertionError('Missing unambiguous Node test count: ' + name)
            counts[name] = int(matches[0])
        receipt['tests'] = {
            'command': command, 'exitCode': result.returncode, **counts,
            'log': {'path': log.relative_to(ROOT).as_posix(), 'bytes': log.stat().st_size, 'sha256': digest(log)},
            'node': subprocess.check_output(['node', '--version'], text=True).strip(),
        }
        result.check_returncode()
        if counts['tests'] < 12 or counts['tests'] != counts['pass'] or any(counts[x] for x in ['fail', 'cancelled', 'skipped', 'todo']):
            raise AssertionError('Policy behavior suite did not execute every required case successfully')
        if receipt['source_hashes'] != {name: digest(ROOT / name) for name in SOURCES}:
            raise AssertionError('Production or test sources changed during verification')
        receipt['checks'] = [
            'Android stages and core boundaries select only qualified one/four-thread routes; browser two/three-thread selection is preserved.',
            'Missing shared memory or isolation preserves serial selection.',
            'Cached stages restore before runtime initialization and report null thread counts.',
            'Actual GAME adapter executes two nonzero PCM passages and all sixteen diffusion steps serially despite an eligible capacity callback; no query or child starts.',
            'ORT fallback after four-thread selection is reported independently and cannot activate the experimental pool.',
            'Callable foreground/background app bridges determine routing; thread metadata remains in diagnostics rather than musical output.',
            'A private one-thread classifier worker commits its handoff and terminates before four-thread GAME; five internal workers retain four public stages and combined voice timing.',
            'Missing, altered-model, truncated, nonfinite or wrong-type classifier records force complete one-thread voice before ORT initialization; complete voice and valid classifier caches skip private inference.',
            'Private-stage cancellation terminates its worker before GAME can start; no private classifier fields enter musical output.',
        ]
        receipt['passed'] = True
    except Exception as error:
        receipt['errors'].append(str(error))
    receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    atomic(OUT / 'verification.json', receipt)
    if receipt['passed']:
        history = [
            'qa/speedup-exact/game-pool/initial-failed/diagnostic-input/game-pool/verification.json',
            'qa/speedup-exact/game-memory/verification.json',
            'qa/speedup-exact/game-resource-policy/verification.json',
        ]
        decision = {
            'schema': 'lightforge-game-pool-release-decision-1', 'release': '2.2.5',
            'shipping': False, 'targetQualification': 'unqualified',
            'reason': 'The two-heap GAME experiment lacks accepted actual Android qualification. Production worker activation is explicitly disabled.',
            'activation': {'source': 'web/analysis/worker.js', 'sha256': receipt['source_hashes']['web/analysis/worker.js'],
                           'constant': 'GAME_PASSAGE_POOL_ENABLED', 'value': False},
            'currentBehaviorProof': {'path': (OUT / 'verification.json').relative_to(ROOT).as_posix(), 'sha256': digest(OUT / 'verification.json')},
            'historicalEvidence': [{'path': name, 'sha256': digest(ROOT / name), 'passed': json.loads((ROOT / name).read_text()).get('passed'),
                                    'bindingScope': 'Historical original receipt; not rebound to current source and not shipping Android pool qualification.'} for name in history],
        }
        atomic(ROOT / 'qa/speedup-exact/game-pool/release-decision.json', decision)
    print(json.dumps({'passed': receipt['passed'], 'tests': receipt.get('tests', {}).get('tests'), 'errors': receipt['errors']}))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

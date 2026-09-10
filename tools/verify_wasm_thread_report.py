"""Strict, side-effect-free validation of the two real Android probe phases."""
import hashlib
import json
import math
import re

ORIGIN = 'https://appassets.androidplatform.net'
FIXTURE = '5cfb46f063a2263e56c54d176841e0f6b1cfb69feb894896ef6875c697e3de22'
GRAPH_OUTPUTS = {
    'encoder': {'maskT', 'x_est', 'x_seg'}, 'dur2bd': {'boundaries'},
    'segmenter': {'boundaries'}, 'bd2dur': {'durations', 'maskN'},
    'estimator': {'presence', 'scores'},
}
GRAPH_ORDER = ['encoder', 'dur2bd'] + ['segmenter'] * 8 + ['bd2dur', 'estimator']
SOURCE_PATHS = {
    'web/analysis/worker.js', 'web/analysis/game.js', 'web/analysis/work-store.js',
    'web/analysis/vendor/ort.wasm.min.js', 'web/analysis/vendor/ort-wasm-simd-threaded.mjs',
    'web/analysis/vendor/ort-wasm-simd-threaded.wasm', 'web/analysis/models/game/manifest.json',
    *('web/analysis/models/game/' + name + '.onnx' for name in GRAPH_OUTPUTS),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def storage(value, retained):
    require(value.get('passed') is True and value.get('retained') is retained,
            'Default-profile storage phase/result differs')
    token = 'lightforge-default-profile-wasm-thread-proof-v1'
    require(value.get('opfs') == token and value.get('indexedDB') == token,
            'Default-profile OPFS/IndexedDB bytes differ')


def threads(value, expected):
    require(value.get('effectiveThreads') == expected, 'Effective ORT thread count differs')
    children = value.get('pthreadWorkers')
    require(isinstance(children, list) and len(children) == expected - 1,
            'Actual pthread worker count differs')
    for child in children:
        require(child.get('url') == ORIGIN + '/analysis/vendor/ort-wasm-simd-threaded.mjs'
                and child.get('options', {}).get('type') == 'module'
                and 'loaded' in child.get('messages', []), 'Pthread module/loading evidence missing')


def validate_worker(value, expected_mode, expected_threads, modern):
    require(value.get('mode') == expected_mode and value.get('passed') is True,
            'Worker mode did not complete successfully')
    require(value.get('threadSelectionScope') == 'actual-packaged-selector-direct-game'
            and value.get('productionDispatchExercised') is False,
            'Direct GAME selector proof is missing its limited scope')
    require(value.get('productionRequest') == {'stage': 'voice', 'androidApp': True, 'analysisQuality': 'balanced'},
            'Packaged selector input differs')
    require(value.get('configuredThreads') == (4 if modern else 1), 'Packaged selector count differs')
    require(value.get('crossOriginIsolated') is modern and value.get('secureContext') is True,
            'Worker isolation/security context differs')
    require(value.get('hardwareConcurrency', 0) >= 8, 'Actual guest CPU evidence differs')
    if modern:
        require(value.get('sharedArrayBuffer') is True, 'Worker SharedArrayBuffer missing')
    require(value.get('identityExact') is True
            and value.get('outputBits') == [1065353216, 3221225472, 1048576000, 2147483648],
            'Tiny graph did not preserve float32 bits including negative zero')
    require(value.get('checkpointNamespaceRemoved') is True and value.get('parentWorkerTerminated') is True,
            'Worker/checkpoint ownership cleanup missing')
    threads(value, expected_threads)
    require(value.get('workerLocation') == ORIGIN + '/analysis/__wasm_thread_probe__.js',
            'Unexpected worker origin or script')
    checks = value.get('policyChecks', [])
    require(len(checks) == 12, 'Incomplete packaged stage-selector coverage')
    observed = {}
    for row in checks:
        key = (row.get('simulatedCores'), row.get('stage'), row.get('quality'))
        require(key not in observed, 'Duplicate selector case')
        observed[key] = row.get('selected')
    expected = {}
    for cores in (4, 8):
        for stage, quality in [('rhythm', 'balanced'), ('bass', 'balanced'), ('separation', 'balanced'),
                               ('separation', 'precision'), ('voice-classifier', 'balanced'), ('voice', 'balanced')]:
            qualified = stage == 'voice' or stage == 'separation' and quality == 'precision'
            expected[(cores, stage, quality)] = 4 if modern and cores == 8 and qualified else 1
    require(observed == expected, 'Packaged Android stage-selector results differ')
    require(isinstance(value.get('seconds'), (float, int)) and math.isfinite(value['seconds'])
            and value['seconds'] >= 0, 'Instrumented worker duration missing')
    if expected_mode in ('tiny', 'restart'):
        require(value.get('records') == [] and value.get('sessions') == [], 'Tiny graph phase unexpectedly ran musical models')
        return
    require(value.get('fixtureSha256') == FIXTURE and value.get('samples') == 132300
            and value.get('sampleRate') == 44100 and value.get('seed') == 2025 and value.get('language') == 0,
            'Exact musical input/clock/settings differ')
    require(value.get('freshCheckpointMiss') is True and value.get('resumeWithoutInference') is True
            and value.get('modelSessionsReleased') is True, 'Fresh inference, exact restore or session release evidence missing')
    require(value.get('sessions') == ['encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator'], 'Model session set/order differs')
    records = value.get('records', [])
    require(len(records) == 12 and [row.get('graph') for row in records] == GRAPH_ORDER,
            'Incomplete or reordered raw graph evidence')
    counts = {}
    widths = {'float32': 4, 'bool': 1, 'int64': 8}
    for row in records:
        graph = row['graph']; ordinal = counts.get(graph, 0); counts[graph] = ordinal + 1
        require(row.get('ordinal') == ordinal and set(row.get('tensors', {})) == GRAPH_OUTPUTS[graph],
                'A graph output or diffusion step is missing')
        for tensor in row['tensors'].values():
            dims = tensor.get('dims'); kind = tensor.get('type')
            require(kind in widths and isinstance(dims, list)
                    and all(type(n) is int and n >= 0 for n in dims)
                    and tensor.get('bytes') == math.prod(dims) * widths[kind] and sha(tensor.get('sha256')),
                    'Raw tensor geometry/dtype/hash evidence is malformed')
    checkpoint_text = value.get('checkpointJson', '')
    require(sha(value.get('checkpointSha256')) and digest(checkpoint_text) == value['checkpointSha256'],
            'Unrounded checkpoint hash does not match exact JSON bytes')
    checkpoint = json.loads(checkpoint_text); notes = json.loads(value['transcriptionJson'])
    require(checkpoint.get('first') == 0 and checkpoint.get('last') == 132300 and checkpoint.get('steps') == 8
            and notes.get('steps') == 8 and notes.get('language') == 0
            and checkpoint.get('model') == notes.get('model') and isinstance(checkpoint.get('model'), str),
            'Checkpoint model or passage geometry differs')
    for values in (checkpoint.get('notes'), notes.get('notes')):
        require(isinstance(values, list), 'Note payload missing')
        for note in values:
            require(all(isinstance(note.get(k), (int, float)) and math.isfinite(note[k]) for k in ('start', 'end', 'midi'))
                    and 0 <= note['start'] < note['end'] <= 3.001 and 0 <= note['midi'] <= 127,
                    'Unrounded or final notes contain invalid values')
    require(sha(value.get('rawOutputsSha256')), 'Raw output aggregate hash missing')
    # All trace keys are ASCII. Python's compact insertion-order serialization
    # therefore reproduces the JavaScript JSON.stringify bytes exactly here.
    require(digest(json.dumps(records, separators=(',', ':'), ensure_ascii=False)) == value['rawOutputsSha256'],
            'Raw aggregate hash does not match retained complete tensor records')


def validate_phase(report, expected_mode):
    modern = expected_mode == 'modern'
    require(expected_mode in ('stock', 'modern') and report.get('mode') == expected_mode
            and report.get('passed') is True and report.get('diagnosticOnly') is True, 'Phase failed or mode differs')
    require(report.get('androidSdk') == 35 and 'x86_64' in report.get('supportedAbis', []), 'Unexpected emulator platform')
    if modern:
        require(report.get('webViewPackage') == 'com.android.webview' and report.get('webViewVersion') == '155.0.8051.0', 'Verified provider was not selected')
    else:
        require(report.get('webViewPackage') == 'com.google.android.webview'
                and str(report.get('webViewVersion', '')).startswith('124.'), 'Stock fallback provider differs')
    document = report.get('document', {})
    require(str(document.get('location', '')).startswith(ORIGIN + '/') and document.get('secureContext') is True
            and document.get('crossOriginIsolated') is modern and document.get('hardwareConcurrency', 0) >= 8,
            'Actual app document security/capability evidence differs')
    profile = report.get('profile', {})
    require(profile.get('allowlistSupported') is modern and profile.get('configureResult') is modern,
            'Public provider-gated configuration result differs')
    if modern:
        require(profile.get('supported') is True and profile.get('name') == profile.get('defaultName')
                and isinstance(profile.get('name'), str) and profile.get('allowlist') == [ORIGIN]
                and document.get('sharedArrayBuffer') is True, 'Default-profile exact-origin grant differs')
    predicates = report.get('originPredicates', {})
    expected_predicates = {ORIGIN: True, ORIGIN + '/index.html?x=1': True, 'null': False,
        'http://appassets.androidplatform.net': False, 'https://example.com': False,
        'https://user@appassets.androidplatform.net': False, 'https://appassets.androidplatform.net:443': False,
        'https://appassets.androidplatform.net.evil.example': False}
    require(predicates == expected_predicates, 'Trusted-origin predicate coverage differs')
    require(report.get('workerResponseHeaders', {}).get('Document-Isolation-Policy') == 'isolate-and-credentialless',
            'Actual shared production transport DIP header missing')
    storage(report.get('storage', {}), modern)
    sources = report.get('sourceHashes', {})
    require(set(sources) == SOURCE_PATHS and all(sha(value) for value in sources.values()), 'Packaged source/model/runtime bindings missing')
    require(report.get('fixtureSha256') == FIXTURE and sha(report.get('probeScriptSha256')), 'Fixture/probe binding missing')
    samples = report.get('memory', [])
    require(samples and all(row.get('lowMemory') is False and row.get('availableBytes', 0) > 0
                           and row.get('totalBytes', 0) >= row['availableBytes'] for row in samples),
            'Actual Android memory observations are incomplete or failed')
    validate_worker(report.get('tiny', {}), 'tiny', 4 if modern else 1, modern)
    if modern:
        a, b = report.get('reference', {}), report.get('candidate', {})
        validate_worker(a, 'reference', 1, True); validate_worker(b, 'candidate', 4, True)
        for key in ('records', 'rawOutputsSha256', 'checkpointJson', 'checkpointSha256', 'transcriptionJson', 'fixtureSha256'):
            require(a[key] == b[key], 'One-thread/four-thread GAME differs: ' + key)
        require(report.get('exact') is True, 'Exact Android comparison was not accepted')
        cancellation = report.get('cancel', {})
        require(cancellation.get('passed') is True and cancellation.get('terminated') is True
                and cancellation.get('noCompletionAfterTermination') is True, 'Parent cancellation evidence missing')
        active = cancellation.get('active', {}); threads(active, 4)
        require(active.get('mode') == 'cancel' and active.get('graph') == 'encoder'
                and active.get('samples') == 132300 and sha(active.get('checkpointKey')), 'Active neural cancellation context differs')
        cleanup = cancellation.get('cleanup', {})
        require(all(cleanup.get(k) is True for k in ('passed', 'checkpointAbsent', 'namespaceRemoved')), 'Cancellation left passage work')
        validate_worker(report.get('restart', {}), 'restart', 4, True)
        storage(report.get('storageAfterLifecycle', {}), True)
    return {'passed': True, 'mode': expected_mode, 'actualThreads': 4 if modern else 1,
            'rawGameCalls': 24 if modern else 0, 'scope': 'Direct GAME, not full classifier/voice dispatch'}


def validate_pair(stock, modern):
    validate_phase(stock, 'stock'); validate_phase(modern, 'modern')
    for key in ('sourceHashes', 'fixtureSha256', 'probeScriptSha256'):
        require(stock[key] == modern[key], 'App/probe bytes changed across provider replacement: ' + key)
    return {'passed': True, 'stockFallback': True, 'defaultProfileDataRetained': True,
            'actualFourThreadRuntime': True, 'rawGameOutputsExact': True,
            'unroundedCheckpointExact': True, 'finalNotesExact': True,
            'freshInferenceThenExactResume': True, 'parentCancellationAndTinyRestart': True}

#!/usr/bin/env python3
"""Fail closed on any raw GAME stage-output difference; never round notes."""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

BINDING = ('schema', 'sampleRate', 'samples', 'pcmSHA256', 'modelFiles', 'seed', 'language', 'steps')
TYPES = {'float32': ('f', 4), 'float64': ('d', 8), 'bool': ('B', 1), 'int64': ('q', 8), 'int32': ('i', 4)}
LABELS = ['encoder', 'dur2bd', *(f'segmenter-{i}' for i in range(8)), 'bd2dur', 'estimator']
OUTPUTS = {'encoder': {'x_seg', 'x_est', 'maskT'}, 'dur2bd': {'boundaries'},
           'segmenter': {'boundaries'}, 'bd2dur': {'durations', 'maskN'}, 'estimator': {'scores', 'presence'}}

def load(directory):
    receipt = json.loads((directory / 'receipt.json').read_text())
    if receipt.get('schema') != 'lightforge-game-benchmark-1' or receipt.get('steps') != 8 or not receipt.get('capture'):
        raise ValueError('A complete captured eight-step receipt is required')
    stages = receipt['stages']
    if [stage['label'] for stage in stages] != LABELS:
        raise ValueError('Missing, duplicated or reordered graph stages')
    tensors = {}
    for stage in stages:
        graph = stage['label'].split('-')[0]
        if stage['graph'] != graph or {v['name'] for v in stage['outputs']} != OUTPUTS[graph]:
            raise ValueError('Missing or unexpected graph outputs')
        for tensor in stage['outputs']:
            key = stage['label'] + '/' + tensor['name']
            file = tensor['file']
            if Path(file).name != file or key in tensors or tensor['type'] not in TYPES:
                raise ValueError('Invalid tensor identity')
            dims = tensor['dims']
            if not isinstance(dims, list) or any(type(v) is not int or v < 0 for v in dims):
                raise ValueError('Invalid tensor dimensions')
            data = (directory / file).read_bytes()
            if len(data) != tensor['bytes'] or len(data) != math.prod(dims) * TYPES[tensor['type']][1] or hashlib.sha256(data).hexdigest() != tensor['sha256']:
                raise ValueError('Tensor integrity failure')
            if tensor['type'].startswith('float') and any(not math.isfinite(value[0]) for value in struct.iter_unpack('<' + TYPES[tensor['type']][0], data)):
                raise ValueError('Nonfinite tensor value')
            tensors[key] = tensor, data
    return receipt, tensors

def compare(left, right):
    a, ta = load(left)
    b, tb = load(right)
    for field in BINDING:
        if a[field] != b[field]:
            raise ValueError('Different input/model/settings binding: ' + field)
    if ta.keys() != tb.keys():
        raise ValueError('Different output identities')
    results = []
    for key in ta:
        ma, ba = ta[key]
        mb, bb = tb[key]
        if ma['type'] != mb['type'] or ma['dims'] != mb['dims']:
            results.append({'tensor': key, 'shapeAndTypeMatch': False, 'byteIdentical': False})
            continue
        fmt, size = TYPES[ma['type']]
        mismatched = 0
        maximum = squares = 0.0
        for (x,), (y,) in zip(struct.iter_unpack('<' + fmt, ba), struct.iter_unpack('<' + fmt, bb)):
            if x != y:
                mismatched += 1
            delta = abs(x - y)
            maximum = max(maximum, delta)
            squares += delta * delta
        count = len(ba) // size
        results.append({'tensor': key, 'shapeAndTypeMatch': True, 'byteIdentical': ba == bb,
                        'elements': count, 'unequalElements': mismatched, 'maxAbsoluteDifference': maximum,
                        'rmsDifference': math.sqrt(squares / count) if count else 0})
    identical = all(item['byteIdentical'] for item in results) and a['notes'] == b['notes']
    notes = {'sameCount': len(a['notes']) == len(b['notes']), 'boundariesIdentical': False,
             'maxAcceptedPitchDifferenceMidi': None}
    if notes['sameCount']:
        pairs = list(zip(a['notes'], b['notes']))
        notes['boundariesIdentical'] = all(x['start'] == y['start'] and x['end'] == y['end'] for x, y in pairs)
        notes['maxAcceptedPitchDifferenceMidi'] = max((abs(x['midi'] - y['midi']) for x, y in pairs), default=0)
    return {'schema': 'lightforge-game-comparison-1', 'exactParity': identical,
            'leftRuntime': a['runtime'], 'rightRuntime': b['runtime'], 'pcmSHA256': a['pcmSHA256'],
            'unroundedNotesIdentical': a['notes'] == b['notes'], 'leftNoteCount': len(a['notes']),
            'rightNoteCount': len(b['notes']), 'noteDiagnostics': notes, 'tensors': results,
            'interpretation': 'Exact parity is required here; numeric differences are diagnostic, never automatic quality approval.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = compare(args.left, args.right)
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as output:
            output.write(text)
    print(text)
    return 0 if result['exactParity'] else 2

if __name__ == '__main__':
    raise SystemExit(main())

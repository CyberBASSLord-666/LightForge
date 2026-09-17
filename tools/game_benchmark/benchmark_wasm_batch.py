#!/usr/bin/env python3
"""Compare unchanged GAME WASM graphs with only symbolic batch B fixed to one.

This is a host experiment, never a production or Android qualification gate.
Every session.run output and every unrounded note must remain exactly equal.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import BINDING, LABELS, OUTPUTS, TYPES, compare

ROOT = Path(__file__).resolve().parents[2]
GRAPHS = ('encoder', 'dur2bd', 'segmenter', 'bd2dur', 'estimator')
EXPERIMENT_BINDING = (*BINDING, 'runtime', 'requestedThreads', 'runtimeReportedWasmThreads', 'shapeContractSHA256')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def inspect_models(models):
    # Import lazily so evidence-comparison tests do not need the model toolchain.
    import onnx
    manifest = json.loads((models / 'manifest.json').read_text())
    if (manifest['id'], manifest['steps'], manifest['sampleRate']) != ('game-large-1.0.3-lightforge-1', 8, 44100):
        raise ValueError('Unexpected production GAME manifest')
    result = {'schema': 'lightforge-game-batch-contract-1', 'manifestSHA256': sha256(models / 'manifest.json'),
              'onnxVersion': onnx.__version__, 'modelFiles': {}, 'graphs': {}}
    for name in GRAPHS:
        file = name + '.onnx'
        path = models / file
        expected = manifest['files'][file]
        if path.stat().st_size != expected['bytes'] or sha256(path) != expected['sha256']:
            raise ValueError('Original graph hash mismatch: ' + file)
        model = onnx.load(str(path), load_external_data=False)
        graph = {}
        for label, values in (('inputs', model.graph.input), ('outputs', model.graph.output)):
            graph[label] = []
            for value in values:
                tensor = value.type.tensor_type
                dims = [dimension.dim_param if dimension.HasField('dim_param') else
                        dimension.dim_value if dimension.HasField('dim_value') else None
                        for dimension in tensor.shape.dim]
                graph[label].append({'name': value.name, 'onnxElementType': tensor.elem_type, 'dims': dims})
        batch_inputs = [value for value in graph['inputs'] if 'B' in value['dims']]
        if not batch_inputs or any(value['dims'][0] != 'B' or value['dims'].count('B') != 1 for value in batch_inputs):
            raise ValueError('Expected original symbolic leading batch B in ' + file)
        result['modelFiles'][file] = expected
        result['graphs'][name] = graph
        del model
    return result


def fingerprints(receipt):
    """Reject incomplete evidence even if both runs contain the same omission."""
    if receipt.get('schema') != 'lightforge-game-benchmark-1' or receipt.get('steps') != 8:
        raise ValueError('Expected an eight-step GAME receipt')
    if [stage['label'] for stage in receipt['stages']] != LABELS:
        raise ValueError('Missing, duplicate or reordered inference stages')
    tensors = {}
    total_seconds = 0.0
    for stage in receipt['stages']:
        graph = stage['label'].split('-')[0]
        outputs = stage['outputs']
        if stage['graph'] != graph or {tensor['name'] for tensor in outputs} != OUTPUTS[graph] or len(outputs) != len(OUTPUTS[graph]):
            raise ValueError('Incomplete graph outputs')
        seconds = stage['seconds']
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Missing actual inference timing')
        total_seconds += seconds
        for tensor in outputs:
            dims = tensor['dims']
            if tensor['type'] not in TYPES or not isinstance(dims, list) or any(type(dim) is not int or dim < 0 for dim in dims):
                raise ValueError('Invalid output type/shape')
            if tensor['bytes'] != math.prod(dims) * TYPES[tensor['type']][1] or not re.fullmatch('[0-9a-f]{64}', tensor['sha256']) or tensor.get('finite') is not True:
                raise ValueError('Incomplete finite output fingerprint')
            tensors[stage['label'] + '/' + tensor['name']] = {key: tensor[key] for key in ('type', 'dims', 'bytes', 'sha256')}
    if not math.isclose(total_seconds, receipt['inferenceSeconds'], rel_tol=1e-12):
        raise ValueError('Inference timing is not the complete graph-call sum')
    notes = receipt['notes']
    if not isinstance(notes, list) or any(not isinstance(note, dict) or
            any(not isinstance(note.get(key), (int, float)) or not math.isfinite(note[key]) for key in ('start', 'end', 'midi'))
            for note in notes):
        raise ValueError('Invalid unrounded notes')
    return tensors


def require_exact(reference, candidate):
    for field in EXPERIMENT_BINDING:
        if reference[field] != candidate[field]:
            raise ValueError('Experiment binding differs: ' + field)
    if fingerprints(reference) != fingerprints(candidate):
        raise ValueError('At least one complete stage output differs')
    if reference['notes'] != candidate['notes']:
        raise ValueError('Unrounded note output differs')


def run_order(warmup_pairs, pairs):
    return [('warmup' if index < warmup_pairs else 'measured',
             index + 1 if index < warmup_pairs else index - warmup_pairs + 1,
             ('baseline', 'batch-one') if index % 2 == 0 else ('batch-one', 'baseline'))
            for index in range(warmup_pairs + pairs)]


def host_info(node):
    info = {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine(),
            'logicalCpus': os.cpu_count(), 'node': subprocess.check_output([node, '--version'], text=True).strip(),
            'python': platform.python_version()}
    if hasattr(os, 'sched_getaffinity'):
        info['processCpuAffinity'] = sorted(os.sched_getaffinity(0))
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        names = sorted({line.partition(':')[2].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')})
        info['cpuModels'] = names
    for name in ('cpu.max', 'memory.max'):
        path = Path('/sys/fs/cgroup') / name
        if path.exists():
            info['cgroup' + name.title().replace('.', '')] = path.read_text().strip()
    info['isolation'] = 'No exclusive CPU reservation is enforced; run on an otherwise idle host. Effective WASM workers are not independently observed.'
    return info


def summarize(runs):
    pairs = []
    for pair in sorted({run['pair'] for run in runs if run['phase'] == 'measured'}):
        values = {run['mode']: run for run in runs if run['phase'] == 'measured' and run['pair'] == pair}
        baseline, candidate = values['baseline'], values['batch-one']
        pairs.append({'pair': pair, 'baselineInferenceSeconds': baseline['inferenceSeconds'],
                      'batchOneInferenceSeconds': candidate['inferenceSeconds'],
                      'inferenceReductionPercent': 100 * (1 - candidate['inferenceSeconds'] / baseline['inferenceSeconds'])})
    aggregates = {}
    for mode in ('baseline', 'batch-one'):
        values = [run for run in runs if run['phase'] == 'measured' and run['mode'] == mode]
        aggregates[mode] = {key + 'Median': statistics.median(run[key] for run in values)
                            for key in ('inferenceSeconds', 'initializationSeconds', 'inferenceProcessCpuSeconds', 'processPeakRssKiB', 'wallSeconds')}
    return {'pairs': pairs, 'medians': aggregates,
            'medianPairedInferenceReductionPercent': statistics.median(pair['inferenceReductionPercent'] for pair in pairs),
            'everyMeasuredPairFaster': all(pair['inferenceReductionPercent'] > 0 for pair in pairs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', required=True, type=Path)
    parser.add_argument('--input', required=True, type=Path, help='One production-length mono Float32LE passage, at most 16 seconds')
    parser.add_argument('--output', required=True, type=Path, help='New private evidence directory outside the repository')
    parser.add_argument('--node', default='node')
    parser.add_argument('--seed', type=int, default=2025)
    parser.add_argument('--language', type=int, choices=range(5), default=0)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--warmup-pairs', type=int, default=1)
    parser.add_argument('--pairs', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=1800, help='Maximum seconds for each fresh process')
    args = parser.parse_args()
    if args.warmup_pairs < 1 or args.pairs < 3 or not 1 <= args.threads <= 64 or not 0 <= args.seed <= 0xffffffff or args.timeout <= 0:
        parser.error('Need at least one warmup and three measured pairs, valid seed/threads and a positive timeout')
    args.models, args.input, args.output = args.models.resolve(), args.input.resolve(), args.output.resolve()
    if args.output == ROOT or ROOT in args.output.parents:
        parser.error('Private evidence must be kept outside the repository')
    if args.output.exists():
        parser.error('Output directory must not exist')
    samples, remainder = divmod(args.input.stat().st_size, 4)
    if remainder or not 0 < samples <= 16 * 44100:
        parser.error('Expected a nonempty <=16-second mono Float32LE passage; do not truncate production context for timing')
    node = shutil.which(args.node)
    if not node:
        parser.error('Node executable was not found')
    contract = inspect_models(args.models)
    args.output.mkdir(parents=True)
    shape_path = args.output / 'shape-contract.json'
    write_json(shape_path, contract)
    sources = ('web/analysis/game.js', 'web/analysis/vendor/ort.wasm.min.js',
               'web/analysis/vendor/ort-wasm-simd-threaded.mjs', 'web/analysis/vendor/ort-wasm-simd-threaded.wasm',
               'tools/game_benchmark/capture_web.cjs', 'tools/game_benchmark/compare.py',
               'tools/game_benchmark/benchmark_wasm_batch.py')
    source_hashes = {file: sha256(ROOT / file) for file in sources}
    plan = {'schema': 'lightforge-game-wasm-batch-experiment-1', 'startedAt': datetime.now(timezone.utc).isoformat(),
            'host': host_info(node), 'sourceFiles': source_hashes, 'modelFiles': contract['modelFiles'],
            'shapeContractSHA256': sha256(shape_path), 'pcmSHA256': sha256(args.input), 'samples': samples,
            'sampleRate': 44100, 'seed': args.seed, 'language': args.language, 'requestedThreads': args.threads,
            'warmupPairs': args.warmup_pairs, 'measuredPairs': args.pairs,
            'onlyCandidateChange': 'Session freeDimensionOverrides B=1; original graph bytes, Float32 precision, complete passage, eight steps and all other settings retained',
            'processPolicy': 'Fresh Node process and five sessions for every passage; discarded alternating warmup pairs warm host/file caches, not retained sessions',
            'outputPolicy': 'Every output hashed and checked finite outside timed run calls; first warmup pair also captures and compares all original raw bytes and unrounded notes',
            'timingScope': 'Inference sums only awaited session.run calls. Initialization, output evidence and complete passage wall time are separate.',
            'claimScope': 'One fixed host passage and seed; not whole-song, phone, Android WebView, Tesla, comparative musical-quality or 75% speedup evidence',
            'productionRolloutQualified': False}
    write_json(args.output / 'plan.json', plan)
    runs = []
    reference = None
    quality_directories = {}
    try:
        for phase, pair, modes in run_order(args.warmup_pairs, args.pairs):
            for mode in modes:
                name = f'{phase}-{pair:02d}-{mode}'
                directory = args.output / name
                capture = phase == 'warmup' and pair == 1
                command = [node, str(ROOT / 'tools/game_benchmark/capture_web.cjs'), str(args.models), str(args.input),
                           str(directory), str(args.seed), str(args.language), str(args.threads), str(capture).lower(), mode, str(shape_path)]
                print(name, flush=True)
                with (args.output / (name + '.log')).open('x') as log:
                    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=args.timeout)
                receipt = json.loads((directory / 'receipt.json').read_text())
                if receipt['experiment'] != mode or receipt['freeDimensionOverrides'] != ({'B': 1} if mode == 'batch-one' else {}):
                    raise ValueError('Wrong candidate session configuration')
                if reference is None:
                    reference = receipt
                if capture:
                    quality_directories[mode] = directory
                if len(quality_directories) == 2 and not (args.output / 'raw-comparison.json').exists():
                    raw = compare(quality_directories['baseline'], quality_directories['batch-one'])
                    write_json(args.output / 'raw-comparison.json', raw)
                    if not raw['exactParity']:
                        raise ValueError('Raw full-stage comparison failed')
                require_exact(reference, receipt)
                run = {'phase': phase, 'pair': pair, 'mode': mode, 'directory': name, 'receiptSHA256': sha256(directory / 'receipt.json'),
                       'inferenceSeconds': receipt['inferenceSeconds'], 'initializationSeconds': sum(stage['seconds'] for stage in receipt['initialization']),
                       'inferenceProcessCpuSeconds': receipt['inferenceProcessCpuSeconds'], 'processPeakRssKiB': receipt['processPeakRssKiB'],
                       'wallSeconds': receipt['wallSeconds'], 'allStageOutputsAndUnroundedNotesExact': True}
                runs.append(run)
                write_json(args.output / (name + '-validated.json'), run)
        if any(sha256(ROOT / file) != digest for file, digest in source_hashes.items()) or sha256(args.input) != plan['pcmSHA256']:
            raise ValueError('Benchmark source or audio changed during the experiment')
        current_contract = inspect_models(args.models)
        if current_contract['manifestSHA256'] != contract['manifestSHA256'] or current_contract['modelFiles'] != contract['modelFiles']:
            raise ValueError('Original model manifest or graphs changed during the experiment')
        result = {**plan, 'completedAt': datetime.now(timezone.utc).isoformat(), 'runs': runs,
                  'allStageOutputsAndUnroundedNotesExact': True, **summarize(runs)}
        write_json(args.output / 'result.json', result)
        print(json.dumps({'result': str(args.output / 'result.json'), 'exactParity': True,
                          'medianPairedInferenceReductionPercent': result['medianPairedInferenceReductionPercent']}))
    except Exception as error:
        write_json(args.output / 'failed.json', {'schema': plan['schema'], 'completedRuns': runs,
                                               'error': str(error), 'productionRolloutQualified': False})
        raise


if __name__ == '__main__':
    main()

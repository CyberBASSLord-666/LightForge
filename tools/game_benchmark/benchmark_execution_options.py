#!/usr/bin/env python3
"""Isolated production GAME config screen: full-tensor parity, notes and sampled memory."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
SOURCE = ROOT / 'android/src/com/cyberbasslord/lightforge/NativeGame.java'
PROFILE = SOURCE.with_name('NativeGameProfile.java')
CONFIGS = {'baseline': (False, False, 4), 'dynamic4': (True, False, 4), 'arena': (False, True, 4),
           'dynamic4-arena': (True, True, 4), 'threads6-dynamic4': (True, False, 6)}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Production source changed; isolated observer insertion must be reviewed: ' + old)
    return source.replace(old, new)


def candidate(source, config):
    dynamic, arena, threads = CONFIGS[config]
    source = replace_once(source, 'try{check(cancellation);return result;}',
                          'try{NativeGameExecutionBenchmark.capture(graph,result);check(cancellation);return result;}')
    if dynamic:
        source = replace_once(source, 'options.addConfigEntry("session.intra_op.allow_spinning","0");',
                              'options.addConfigEntry("session.intra_op.allow_spinning","0");\n'
                              '                    options.addConfigEntry("session.dynamic_block_base","4");')
    if arena:
        for option in ('setCPUArenaAllocator', 'setMemoryPatternOptimization'):
            source = replace_once(source, f'options.{option}(false);', f'options.{option}(true);')
    if threads != 4:
        source = replace_once(source, 'Math.min(4,Runtime.getRuntime().availableProcessors())',
                              f'Math.min({threads},Runtime.getRuntime().availableProcessors())')
    return source


def run_measured(command, directory):
    rss_peak = hwm_peak = 0
    started = time.monotonic()
    with (directory / 'execution.log').open('w') as log:
        process = subprocess.Popen(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            try:
                for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
                    if line.startswith('VmRSS:'):
                        rss_peak = max(rss_peak, int(line.split()[1]))
                    if line.startswith('VmHWM:'):
                        hwm_peak = max(hwm_peak, int(line.split()[1]))
            except FileNotFoundError:
                pass
            time.sleep(.05)
    if process.returncode:
        raise RuntimeError(f'Execution failed: {directory / "execution.log"}')
    return {'processWallSeconds': time.monotonic() - started,
            'observedPeakRssKiB': rss_peak or None, 'observedVmHwmKiB': hwm_peak or None,
            'memoryScope': '/proc sampled every 50ms; last observed VmHWM may omit exit-adjacent peak'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchain')
    parser.add_argument('--models', type=Path, default=ROOT / 'web/analysis/models/game')
    parser.add_argument('--configs', nargs='+', choices=CONFIGS, default=['baseline', 'dynamic4', 'arena'])
    parser.add_argument('--trials', type=int, default=1)
    parser.add_argument('--passage', type=int, help='Screen one original production window; no whole-song stitching claim')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.trials < 1 or args.trials > 10 or 'baseline' not in args.configs:
        parser.error('Use one to ten trials and include baseline')
    total = args.input.stat().st_size // 4
    if total < 1 or args.input.stat().st_size != total * 4:
        parser.error('Nonempty complete float32 PCM required')
    plan = json.loads(subprocess.check_output(['node', str(TOOL / 'process_capture.cjs'), '--plan', str(total), '0'], text=True))
    if args.passage is not None:
        plan = [passage for passage in plan if passage['index'] == args.passage]
        if len(plan) != 1:
            parser.error('Passage is outside the production window plan')
    args.output.mkdir(parents=True, exist_ok=True)
    dependencies = [args.toolchain / 'onnx/onnxruntime-1.25.1.jar', args.toolchain / 'test-json.jar',
                    args.toolchain / 'android-sdk/platforms/android-35/android.jar']
    classpath = os.pathsep.join(map(str, dependencies))
    source = SOURCE.read_text()
    inventory = [SOURCE, PROFILE, TOOL / 'NativeGameExecutionBenchmark.java', Path(__file__),
                 TOOL / 'compare.py', TOOL / 'process_capture.cjs', ROOT / 'web/analysis/game.js']
    provenance = {'schema': 'lightforge-game-options-screen-1', 'sourceSha256': {str(p.relative_to(ROOT)): digest(p) for p in inventory},
                  'inputSha256': digest(args.input), 'modelManifestSha256': digest(args.models / 'manifest.json'),
                  'dependencySha256': {p.name: digest(p) for p in dependencies}, 'plan': plan, 'trials': args.trials,
                  'configs': args.configs, 'captureTiming': True, 'androidPerformanceMeasured': False,
                  'completePassagePlan': args.passage is None,
                  'configScope': 'Only reviewed option substitutions and a post-run tensor observer in isolated source copies',
                  'cpuAffinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                  'cpuQuota': Path('/sys/fs/cgroup/cpu.max').read_text().strip()}
    prepared = args.output / 'experiment.json'
    if prepared.exists() and json.loads(prepared.read_text()) != provenance:
        raise ValueError('Experiment inputs/source changed after preparation')
    prepared.write_text(json.dumps(provenance, indent=2) + '\n')
    for path in inventory:
        snapshot = args.output / 'source-snapshots' / path.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, snapshot)
    for config in args.configs:
        directory = args.output / config
        directory.mkdir(exist_ok=True)
        engine = directory / 'NativeGame.java'
        engine.write_text(candidate(source, config))
        classes = directory / 'classes'
        classes.mkdir(exist_ok=True)
        subprocess.run([str(args.toolchain / 'jdk17/bin/javac'), '--release', '8', '-cp', classpath, '-d', str(classes),
                        str(engine), str(PROFILE), str(TOOL / 'NativeGameExecutionBenchmark.java')], check=True)
    if args.prepare_only:
        print('Prepared isolated source/configs; no neural inference performed.')
        return
    spec = importlib.util.spec_from_file_location('game_comparison', TOOL / 'compare.py')
    comparator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparator)
    runs = []
    pcm = args.input.read_bytes()
    for trial in range(args.trials):
        # Reverse alternation reduces systematic order bias; every trial has fresh processes/sessions.
        configs = args.configs if trial % 2 == 0 else list(reversed(args.configs))
        for passage in plan:
            passage_input = args.output / f'input-{passage["index"]}.f32'
            passage_input.write_bytes(pcm[passage['first'] * 4:passage['last'] * 4])
            for config in configs:
                directory = args.output / config / f'trial-{trial}-passage-{passage["index"]}'
                directory.mkdir()
                output = directory / 'capture'
                runtime_classpath = os.pathsep.join([str(args.output / config / 'classes'), classpath])
                command = [args.toolchain / 'jdk17/bin/java', '-Xmx2g', '-XX:MaxDirectMemorySize=2g', '-cp', runtime_classpath,
                           'com.cyberbasslord.lightforge.NativeGameExecutionBenchmark', args.models, passage_input,
                           output, str(passage['seed']), '0']
                measured = run_measured(command, directory)
                receipt = json.loads((output / 'receipt.json').read_text())
                profile = dict(field.split('=', 1) for field in receipt['profile'].split())
                runs.append({'trial': trial, 'passage': passage['index'], 'config': config, **measured,
                             'processPeakRssKiB': receipt.get('processPeakRssKiB'),
                             'wallSeconds': receipt['wallSeconds'], 'inferenceWallMs': int(profile['inferenceWallMs']),
                             'modelInitWallMs': int(profile['modelInitWallMs']), 'notes': len(receipt['notes']),
                             'receiptSha256': digest(output / 'receipt.json')})
                print(json.dumps(runs[-1]), flush=True)
    comparisons = []
    for trial in range(args.trials):
        for passage in plan:
            baseline = args.output / 'baseline' / f'trial-{trial}-passage-{passage["index"]}' / 'capture'
            for config in args.configs:
                if config == 'baseline':
                    continue
                other = args.output / config / f'trial-{trial}-passage-{passage["index"]}' / 'capture'
                comparison = comparator.compare(baseline, other)
                comparisons.append({'trial': trial, 'passage': passage['index'], 'config': config, **comparison})
    replay_input = {'manifest': json.loads((args.models / 'manifest.json').read_text()),
                    'pcm': str(args.input.resolve()), 'records': {}}
    for trial in range(args.trials):
        for config in args.configs:
            records = []
            for passage in plan:
                receipt = json.loads((args.output / config / f'trial-{trial}-passage-{passage["index"]}' / 'capture/receipt.json').read_text())
                records.append({**passage, 'notes': receipt['notes'], 'pcmSha256': receipt['pcmSHA256']})
            replay_input['records'][f'{trial}:{config}'] = records
    replay_file = args.output / 'stitch-input.json'
    replay_file.write_text(json.dumps(replay_input) + '\n')
    replay_code = """const fs=require('fs'),h=require(process.argv[1]),v=JSON.parse(fs.readFileSync(process.argv[2]));
        (async()=>{const out={},pcm=fs.readFileSync(v.pcm);for(const [key,records]of Object.entries(v.records))
        out[key]=await h.processNativeRecords(v.manifest,pcm,0,records);console.log(JSON.stringify(out));})()
        .catch(e=>{console.error(e);process.exitCode=1;});"""
    replay = None if args.passage is not None else json.loads(subprocess.check_output(['node', '-e', replay_code, str(TOOL / 'process_capture.cjs'), str(replay_file)], text=True))
    stitched_equal = None if replay is None else all(replay[f'{trial}:baseline']['transcription'] == replay[f'{trial}:{config}']['transcription']
                                                    for trial in range(args.trials) for config in args.configs)
    report = {'provenance': provenance, 'runs': runs, 'comparisons': comparisons, 'nativeReplay': replay,
              'stitchedNotesIdentical': stitched_equal,
              'exactParity': all(result['exactParity'] for result in comparisons),
              'timing': {config: {'medianPassageWallSeconds': statistics.median(run['wallSeconds'] for run in runs if run['config'] == config),
                                  'totalInferenceWallMs': sum(run['inferenceWallMs'] for run in runs if run['config'] == config)} for config in args.configs},
              'limits': ['Host CPU screen; no Android execution, whole-analysis speedup, or broad musical-quality claim.',
                         'Graph captures add identical observer work outside kernel timing; fresh processes include cold session setup.']}
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'exactParity': report['exactParity'], 'timing': report['timing']}))


if __name__ == '__main__':
    main()

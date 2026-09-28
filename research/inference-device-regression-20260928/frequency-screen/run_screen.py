#!/usr/bin/env python3
"""Original frequency graph only; no production/device or full-passage claim."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TC = ROOT.parent / 'toolchain'
MODELS = ROOT / 'web/analysis/models/deux'
JAR = TC / 'onnx/onnxruntime-1.25.1.jar'
JAVA = TC / 'jdk17/bin/java'
TRANSFORM = ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java'
sha = lambda p: hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()

def counters():
    return {p.name: p.read_text() for p in (Path('/sys/fs/cgroup/cpu.stat'), Path('/sys/fs/cgroup/memory.events'), Path('/sys/fs/cgroup/memory.current'))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--batches', type=int, nargs='+', default=[1])
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    assert not args.output.exists() and all(b in (1, 4, 16, 32, 128) for b in args.batches)
    assert 1 <= args.repeats <= 3
    args.work.mkdir(parents=True, exist_ok=True)
    classes = args.work / 'classes'
    classes.mkdir(exist_ok=True)
    runtime = json.loads((ROOT / 'android/native-runtime.json').read_text())
    assert runtime['version'] == '1.25.1' and sha(JAR) == runtime['host']['sha256']
    manifest = json.loads((MODELS / 'manifest.json').read_text())
    graph_names = ['front.onnx', 'block-00-time.onnx', 'block-00-frequency.onnx']
    assert all(sha(MODELS / n) == manifest['files'][n]['sha256'] for n in graph_names)
    subprocess.run([str(TC / 'jdk17/bin/javac'), '-cp', str(JAR), '-d', str(classes), str(TRANSFORM), str(HERE / 'NativeFrequencyScreen.java')], check=True)
    cp = os.pathsep.join(map(str, (classes, JAR)))
    affinity = sorted(os.sched_getaffinity(0))[:7]
    assert len(affinity) == 7
    def invoke(*values):
        before = counters(); start = time.monotonic_ns()
        result = subprocess.run([str(JAVA), '-Xmx512m', '-cp', cp, 'com.cyberbasslord.lightforge.NativeFrequencyScreen', *map(str, values)], capture_output=True, text=True, preexec_fn=lambda: os.sched_setaffinity(0, affinity), timeout=60)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)
        return dict(observation=json.loads(result.stdout.strip()), wholeProcessWallNanos=time.monotonic_ns()-start,
                    countersBefore=before, countersAfter=counters(), stderr=result.stderr)
    input_file = args.work / 'frequency-input.f32'
    prepare = invoke('prepare', MODELS, ROOT / 'web/demo/glass-castle.wav', input_file)
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in [HERE / 'NativeFrequencyScreen.java', Path(__file__), TRANSFORM, ROOT / 'android/native-runtime.json']}
    report = dict(schema='lightforge.original-frequency-screen.v1', createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Host graph-only exploration, original first frequency graph, complete 1301 independent frames with original 60-band attention and Float32. Fresh session and complete call/worker retirement per arm. Timers exclude immutable input loading and output hashing. Not complete-passage, Android, sustained, or admission evidence.',
                  baselineGeometry=dict(batch=128, workers=1, intraThreads=4),
                  candidateGeometry=dict(batches=args.batches, workers=[4,8], intraThreads=1),
                  sourceHashes=frozen, runtimeSha256=sha(JAR), modelManifestSha256=sha(MODELS/'manifest.json'),
                  modelHashes={n: sha(MODELS/n) for n in graph_names}, audioSha256=sha(ROOT/'web/demo/glass-castle.wav'),
                  inputSha256=sha(input_file), prepare=prepare, childCpuAffinity=affinity,
                  compiledClassHashes={str(p.relative_to(classes)): sha(p) for p in classes.rglob('*.class')}, runs=[])
    assert report['inputSha256'] == prepare['observation']['inputSha256']
    def save(): args.output.write_text(json.dumps(report, indent=2)+'\n')
    save()
    for batch in args.batches:
        for workers in (4,8):
            for round_number in range(args.repeats):
                variants=[(128,1),(batch,workers)]
                if round_number%2: variants.reverse()
                for bs,ws in variants:
                    arm=invoke('measure',MODELS,input_file,bs,ws,round_number,'screen')
                    arm['pairKey']=[batch,workers,round_number]
                    report['runs'].append(arm); save()
                    print(json.dumps(arm['observation']), flush=True)
    report['allOutputsExact']=len({r['observation']['outputSha256'] for r in report['runs']})==1
    report['sourceUnchanged']=all(sha(ROOT/k)==v for k,v in frozen.items())
    save()
    assert report['sourceUnchanged']
    print(json.dumps({'allOutputsExact':report['allOutputsExact'],'receipt':str(args.output)}),flush=True)

if __name__=='__main__':main()

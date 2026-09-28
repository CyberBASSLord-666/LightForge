#!/usr/bin/env python3
"""Frozen-source paired host experiment for independent-B1 outer parallelism.

This does not alter Android sources/models or qualify a release. Profile per-run
durations overlap; only full-passage wall time is a performance comparison.
"""
import argparse, datetime, hashlib, importlib.util, json, statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers',type=int,choices=[8],default=8)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--screen',action='store_true',help='Two alternating screening pairs, no qualification claim')
    a=p.parse_args();work=a.output.resolve()
    if work.exists():raise ValueError('New output directory required; prior receipts are immutable')
    work.mkdir(parents=True);shared=work/'shared';shared.mkdir();(work/'tests').mkdir()
    formal_path=ROOT/'research/inference-2.4.1/separator-scheduler-paired.json'
    formal=json.loads(formal_path.read_text())
    b=load('benchmark',ROOT/'tools/benchmark_deux_execution.py')
    generator_path=ROOT/'research/inference-2.4.1/parallel_b4_probe.py'
    generator=load('parallel_generator',generator_path)
    for path,content in formal['frozenSourceSnapshots'].items():
        if path.startswith('android/'):(shared/Path(path).name).write_text(content)
        if path=='tests/NativeDeuxExecutionBenchmark.java':(work/path).write_text(content)
    b.SOURCE=shared;b.ROOT=work
    source=work/'baseline-source.java';source.write_text(formal['frozenSourceSnapshots']['baseline/NativeDeux.java'])
    candidate=work/'candidate-source.java';candidate_source=generator.generate(a.workers,1)
    b.require(candidate_source.count('TIME_BATCH=4,')==1,'One original batch constant required')
    candidate.write_text(candidate_source.replace('TIME_BATCH=4,','TIME_BATCH=1,'))
    tc=ROOT.parent/'toolchain';java=tc/'jdk17/bin'
    deps=[tc/'test-json.jar',tc/'android-sdk/platforms/android-35/android.jar',tc/'onnx/onnxruntime-1.25.1.jar']
    models=ROOT/'web/analysis/models/deux';audio=ROOT/'web/demo/glass-castle.wav';manifest=json.loads((models/'manifest.json').read_text())
    runtime=json.loads((ROOT/'android/native-runtime.json').read_text())
    b.require(b.sha(deps[-1])==runtime['host']['sha256'],'Pinned runtime checksum mismatch')
    for name,entry in manifest['files'].items():
        b.require((models/name).stat().st_size==entry['bytes'] and b.sha(models/name)==entry['sha256'],'Original graph integrity failure: '+name)
    report={'schema':'lightforge.deux-parallel-b1-paired.v1','startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'Two alternating exploratory pairs'if a.screen else'One warmup pair and three alternating measured pairs; host only',
        'originalGraphCount':27,'baselineInferenceCalls':335,'candidateInferenceCalls':875,'baselineTimeBatch':4,'candidateTimeBatch':1,'workers':a.workers,'temporalIntraThreads':1,
        'frequencyIntraThreads':4,'contextFrames':1301,'samplesPerStem':573300,'host':b.host_metadata(),
        'runtimeVersion':'1.25.1','runtimeSha256':b.sha(deps[-1]),'modelManifestSha256':b.sha(models/'manifest.json'),
        'modelHashes':{name:entry['sha256']for name,entry in manifest['files'].items()},'audioSha256':b.sha(audio),'startSample':661500,
        'bindings':{str(path.relative_to(ROOT)):b.sha(path)for path in[formal_path,generator_path,Path(__file__),ROOT/'tools/benchmark_deux_execution.py']},
        'sharedSourceHashes':{p.name:b.sha(p)for p in shared.glob('*.java')},'sourceHashes':{},'runs':[],
        'timingCaution':'inferenceMillis sums concurrent-call elapsed durations and is not critical-path wall. Compare wallNanos/processCpuNanos only.',
        'androidSpeedupProven':False,'wholeAnalysisSpeedupProven':False,'productionApproved':False,'passed':False}
    # Separate experimental coverage validator. The production 335-call gate is unchanged.
    # A candidate has 60 B1 calls per temporal graph: all original 60 bands, full 1301 frames.
    def full_b1_profile(path):
        records=[dict(part.split('=',1)for part in line.split())for line in path.read_text().splitlines()]
        summary=records[0]
        b.require(len(records)==43 and summary.get('schema')=='native-inference-profile-v2' and summary.get('outcome')=='completed' and summary.get('graphRecords')=='27' and summary.get('stageRecords')=='15' and summary.get('droppedGraphRecords')=='0' and summary.get('droppedStageRecords')=='0','Incomplete original graph/stage profile')
        graphs=[r for r in records[1:]if r.get('schema')=='native-inference-graph-v2'];stages=[r for r in records[1:]if r.get('schema')=='native-inference-stage-v1']
        b.require(len(graphs)==27 and {r.get('graph')for r in graphs}==b.GRAPH_NAMES and len(stages)==15 and {r.get('stage')for r in stages}==b.STAGE_NAMES,'Graph/stage inventory changed')
        time_calls=60 if path.parent.name=='candidate' else 15
        b.require(all(int(r['runCount'])==(1 if r['graph']=='front' else time_calls if r['graph'].endswith('-time') else 11)for r in graphs),'Full independent band/frame coverage changed')
        b.require(int(summary['inferenceCount'])==1+12*time_calls+12*11+2*11,'Wrong declared full-coverage call count')
        for key in ['inferenceWallMs','modelInitWallMs']:b.require(float(summary[key])>0,'Invalid timing')
        return summary
    b.profile_fields=full_b1_profile
    classes={}
    for name,path in [('baseline',source),('candidate',candidate)]:classes[name],report['sourceHashes'][name]=b.compile_variant(name,path,work,java,deps)
    receipt=work/'receipt.json';receipt.write_text(json.dumps(report,indent=2)+'\n')
    phases=[('screen',2)]if a.screen else[('warmup',1),('measurement',3)]
    for phase,count in phases:
        for number in range(count):
            for name in (('baseline','candidate')if number%2==0 else('candidate','baseline')):
                report['runs'].append(b.measure(name,number,phase,classes[name],work,java,deps,models,audio,661500))
                receipt.write_text(json.dumps(report,indent=2)+'\n')
            b.require(len({r['outputSha256']for r in report['runs']})==1,'Complete Float32 outputs differ; candidate rejected')
            pair=[r for r in report['runs']if r['phase']==phase and r['round']==number]
            by_name={r['variant']:r for r in pair}
            print(json.dumps({'phase':phase,'pair':number,'baselineSeconds':by_name['baseline']['wallNanos']/1e9,'candidateSeconds':by_name['candidate']['wallNanos']/1e9,'exact':True}),flush=True)
    chosen=[r for r in report['runs']if r['phase']==('screen'if a.screen else'measurement')]
    medians={name:{key:statistics.median(r[key]for r in chosen if r['variant']==name)for key in['wallNanos','processCpuNanos','peakRssBytes']}for name in['baseline','candidate']}
    report.update(passed=True,allOutputsByteIdentical=True,medians=medians,
        exploratoryOrHostMedianWallReductionPercent=100*(1-medians['candidate']['wallNanos']/medians['baseline']['wallNanos']))
    for name,expected in report['modelHashes'].items():b.require(b.sha(models/name)==expected,'Graph changed during run: '+name)
    b.require(b.sha(audio)==report['audioSha256'],'Audio changed during run')
    receipt.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':True,'medians':medians,'wallReductionPercent':report['exploratoryOrHostMedianWallReductionPercent']}),flush=True)


if __name__=='__main__':main()

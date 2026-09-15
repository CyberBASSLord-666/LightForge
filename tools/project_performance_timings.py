#!/usr/bin/env python3
"""Project executed application timing probes, without qualifying a release.

The capture's source declaration remains caller-declared. An independently
bound diagnostic, controlled paired workload and quality review are separate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

STAGES = ('rhythm', 'separation', 'voice', 'bass')
PROBE_SCOPES = {
    'audio_decode': 'Analysis-time WAV/float PCM parsing, downmix and numeric sample normalization; excludes compressed-media import and awaited reads.',
    'resample_normalize': 'Executed WAV, vocal, bass and stem-output resampling kernels; excludes awaited reads and compressed-media import.',
    'feature_generation': 'Executed DSP, rhythm model frontend, vocal and bass feature kernels; rhythm frontend model time also appears in model inference. Separator encoding is preprocessing.',
    'tempo_inference': 'Executed global/local period estimation and final interval/BPM estimation inside rhythm decoding.',
    'beat_tracking': 'Executed passage construction and beat lattice/manual decoding, excluding separately observed tempo and downbeat work.',
    'downbeat_tracking': 'Executed meter scoring, phase selection and downbeat selection, excluding beat lattice and tempo estimation.',
    'drum_analysis': 'Executed optional percussion estimator only; estimated percussion provenance is unchanged.',
    'structural_analysis': 'Executed section, recurring-section and phrase/impact construction, plus optional recurrence evidence capture and sidecar construction; excludes recurrence validation and IO.',
    'model_initialization': 'Actual WASM InferenceSession.create calls, including lazy/repeated sessions; excludes native initialization and module import/bootstrap.',
    'model_inference': 'Actual WASM session.run calls including frontend, ensemble and GAME diffusion/subgraph calls; excludes native bridge calls.',
    'preprocessing': 'Selected executed input layout, reflection, peak checks and tensor preparation kernels; excludes input IO and separately timed decode/resampling.',
    'postprocessing': 'Selected executed output conversion, overlap/stitching, score reduction, fusion and PCM encoding kernels; excludes durable IO/digest operations.',
    'choreography_planning': 'Executed setup, semantic, movement and light candidate/diagnostic planning; excludes separately timed collision and realization intervals.',
    'collision_resolution': 'Executed light allocation, conflict handling and rescue/fallback attempts.',
    'vehicle_realization': 'Executed movement/light frame painting, interior mapping and manual cue realization; no physical observation.',
    'validation': 'Executed compiler synchronization, choreography quality, perceptual and show-format validation, including repeat header validation.',
    'fseq_generation': 'Compiler header serialization only in capture; payload transfer or Node artifact concatenation is not full application export.',
}
COMPILER = frozenset({'choreography_planning','collision_resolution','vehicle_realization','validation','fseq_generation'})
NATIVE_INCOMPLETE = frozenset({'model_initialization','model_inference','preprocessing','postprocessing','feature_generation','resample_normalize','audio_decode'})
STAGE_METRICS = {'rhythm':'rhythm_analysis','separation':'source_separation','voice':'vocal_analysis','bass':'bass_analysis'}
EXTRA = {'total_wall_clock','synchronization_waiting','checkpoint_resume_overhead','cache_hit_rate','cache_miss_cost'}
METRIC_IDS = frozenset('performance.'+name+('' if name=='cache_hit_rate' else '_seconds') for name in set(PROBE_SCOPES)|set(STAGE_METRICS.values())|EXTRA)

def finite(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0

def require(value, message):
    if not value: raise ValueError(message)

def blank(metric, scope, reason):
    return {'metric_id':metric,'status':'unavailable','value':None,'unit':'ratio' if metric.endswith('cache_hit_rate') else 'seconds','scope':scope,'reason':reason,'observations':[]}

def observed(metric, scope, values):
    if not values: return blank(metric,scope,'no-executed-measurement')
    value=sum(row['seconds'] for row in values)
    require(finite(value),'Timing aggregation overflow')
    return {**blank(metric,scope,None),'status':'observed','value':value,'observations':values}

def profile_ok(profile, stage):
    if not isinstance(profile,dict) or profile.get('kind')!='analysis-stage-profile' or profile.get('schemaVersion')!=1 or profile.get('stage')!=stage:
        return False
    attributes=profile.get('attributes',{})
    if not isinstance(attributes,dict):return False
    if stage=='compiler':return attributes.get('timingContract')=='compiler-phases-v1' and attributes.get('action')=='generate' and attributes.get('outcome')=='completed'
    return attributes.get('performanceProbeVersion')==1

def complete_summary(profile,stage):
    if not profile_ok(profile,stage):return False
    coverage=profile.get('spanSummaryCoverage',{})
    return isinstance(coverage,dict) and coverage.get('namesComplete') is True and type(coverage.get('omittedSpanCount')) is int and coverage['omittedSpanCount']==0 and isinstance(profile.get('spanSummary'),dict)

def span(profile, stage, name):
    if not complete_summary(profile,stage):return None
    summary=profile.get('spanSummary',{})
    if not isinstance(summary,dict):return None
    row=summary.get('performance.'+name)
    if row is None:return None
    require(isinstance(row,dict),'Malformed timing summary')
    require(type(row.get('count')) is int and row['count']>0,'Invalid timing observation count')
    unavailable=row.get('unavailableCount',0)
    require(type(unavailable) is int and 0<=unavailable<=row['count'],'Invalid unavailable timing count')
    if unavailable or row.get('overflowed') is True or row.get('totalMs') is None:return None
    require(finite(row.get('totalMs')) and finite(row.get('maxMs')) and row['maxMs']<=row['totalMs'],'Invalid cumulative timing values')
    timing=profile.get('timing',{})
    if not isinstance(timing,dict) or timing.get('source') not in {'performance.now','date.now'}:return None
    # A later unrelated clock failure does not erase earlier finite completed
    # spans. The accumulator records null if this named interval ever failed.
    return {'stage':stage,'span':'performance.'+name,'count':row['count'],'seconds':row['totalMs']/1000,'clock_source':timing['source']}

def wall(profile,stage):
    if not profile_ok(profile,stage):return None
    timing=profile.get('timing',{})
    if not isinstance(timing,dict) or timing.get('source') not in {'performance.now','date.now'} or timing.get('state') not in {'available','fallback'} or not finite(profile.get('totalWallClockMs')):return None
    return {'stage':stage,'field':'profile.totalWallClockMs','seconds':profile['totalWallClockMs']/1000,'clock_source':timing['source']}

def project(capture, *, capture_sha256):
    require(isinstance(capture,dict) and capture.get('schema')=='lightforge.app-capture.v1' and capture.get('status')=='captured','A completed actual application capture is required')
    require(isinstance(capture_sha256,str) and len(capture_sha256)==64 and all(c in '0123456789abcdef' for c in capture_sha256),'Invalid capture digest')
    engine=capture.get('engine',{})
    stages=engine.get('stages',{}) if isinstance(engine,dict) else {}
    require(isinstance(stages,dict) and set(stages)<=set(STAGES)|{'recurrence'},'Unsupported analysis stage population')
    profiles={stage:value.get('profile') for stage,value in stages.items() if isinstance(value,dict)}
    compiler=capture.get('compiler_profile')
    profiles['compiler']=compiler
    separation=engine.get('separationModel',{}) if isinstance(engine,dict) else {}
    native=isinstance(separation,dict) and (separation.get('runtime')=='onnxruntime-android-cpu' or type(separation.get('nativeModelPasses')) is int and separation['nativeModelPasses']>0)
    runtime_known=isinstance(separation,dict) and separation.get('runtime') in {'onnxruntime-web-wasm','onnxruntime-android-cpu'}
    prior_attempts=isinstance(engine,dict) and bool(engine.get('nativeFallback'))
    instrumented=all(complete_summary(profiles.get(stage),stage) for stage in [*STAGES,*(['recurrence'] if 'recurrence' in stages else [])])
    output={}
    for name,scope in PROBE_SCOPES.items():
        metric='performance.'+name+'_seconds'
        population=['compiler'] if name in COMPILER else [*STAGES,*(['recurrence'] if 'recurrence' in stages else [])]
        measurements=[value for stage in population if (value:=span(profiles.get(stage),stage,name)) is not None]
        row=observed(metric,scope,measurements)
        invalid_intervals=any(isinstance(profiles.get(stage),dict) and isinstance(profiles[stage].get('spanSummary'),dict) and 'performance.'+name in profiles[stage]['spanSummary'] and span(profiles[stage],stage,name) is None for stage in population)
        incomplete=(name not in COMPILER and (not instrumented or prior_attempts)) or ((native or not runtime_known) and name in NATIVE_INCOMPLETE) or invalid_intervals
        if name=='fseq_generation':incomplete=True
        if incomplete and measurements:
            row['status']='partial';row['observed_subtotal']=row['value'];row['value']=None
            row['reason']='header-only-not-complete-export' if name=='fseq_generation' else 'incomplete-attempt-population' if prior_attempts and name not in COMPILER else 'native-subphases-unavailable' if native and name in NATIVE_INCOMPLETE else 'runtime-coverage-unknown' if not runtime_known and name in NATIVE_INCOMPLETE else 'unavailable-named-interval' if invalid_intervals else 'incomplete-instrumented-stage-population'
        output[metric]=row
    for stage,name in STAGE_METRICS.items():
        metric='performance.'+name+'_seconds';value=wall(profiles.get(stage),stage)
        output[metric]=observed(metric,'Inclusive actual worker stage, including measured cache restoration, nested probes and persistence; excludes worker bootstrap and admission wait.',[value] if value else [])
        if prior_attempts and value:output[metric].update(status='partial',observed_subtotal=output[metric]['value'],value=None,reason='incomplete-attempt-population')
    metric='performance.total_wall_clock_seconds';timing=capture.get('timing',{})
    values=[]
    if isinstance(timing,dict) and timing.get('clock')=='performance.now' and all(finite(timing.get(k)) for k in ['analysis_ms','analysis_start_ms','analysis_end_ms']):
        require(timing['analysis_end_ms']>=timing['analysis_start_ms'] and math.isclose(timing['analysis_ms'],timing['analysis_end_ms']-timing['analysis_start_ms'],abs_tol=1e-6,rel_tol=0),'Inconsistent capture analysis interval')
        values=[{'field':'capture.timing.analysis_ms','seconds':timing['analysis_ms']/1000,'clock_source':'performance.now'}]
    output[metric]=observed(metric,'Whole analyzer call on already decoded WAV; excludes compilation and compressed-media import.',values)
    metric='performance.synchronization_waiting_seconds';resource=engine.get('resourceDiagnostics',{}) if isinstance(engine,dict) else {};scheduler=resource.get('scheduler',{}) if isinstance(resource,dict) else {}
    values=[{'field':'engine.resourceDiagnostics.scheduler.waitMilliseconds','seconds':scheduler['waitMilliseconds']/1000}] if isinstance(scheduler,dict) and scheduler.get('status')=='available' and finite(scheduler.get('waitMilliseconds')) else []
    output[metric]=observed(metric,'Analysis admission wait only; excludes native gate waits and other synchronization.',values)
    if prior_attempts and values:output[metric].update(status='partial',observed_subtotal=output[metric]['value'],value=None,reason='incomplete-attempt-population')
    metric='performance.checkpoint_resume_overhead_seconds'
    output[metric]=blank(metric,'Verified interrupted-parent checkpoint read/validation and resume admission.','interrupted-parent-lineage-not-collected')
    cache=[]
    population=[*STAGES,*(['recurrence'] if 'recurrence' in stages else [])]
    for stage in population:
        profile=profiles.get(stage)
        if not profile_ok(profile,stage):break
        entries=profile.get('cache',[])
        if not isinstance(entries,list):break
        outcomes=[row.get('outcome') for row in entries if isinstance(row,dict) and row.get('domain')==stage and row.get('outcome') in {'restore','miss'}]
        if len(outcomes)!=1:break
        cache.append({'stage':stage,'outcome':outcomes[0]})
    complete_cache=len(cache)==len(population) and not prior_attempts
    metric='performance.cache_hit_rate'
    output[metric]=blank(metric,'Exactly the top-level analysis stage cache population, plus recurrence if selected.','incomplete-top-level-cache-population')
    if complete_cache:output[metric].update(status='observed',value=sum(row['outcome']=='restore' for row in cache)/len(cache),reason=None,observations=cache)
    metric='performance.cache_miss_cost_seconds';misses=[row['stage'] for row in cache if row['outcome']=='miss']
    walls=[wall(profiles.get(stage),stage) for stage in misses]
    output[metric]=observed(metric,'Inclusive actual wall time of top-level stages with observed cache misses, not counterfactual slowdown.',walls if complete_cache and walls and all(v is not None for v in walls) else [])
    require(set(output)==METRIC_IDS and len(output)==26,'Performance metric inventory mismatch')
    return {'schema':'lightforge.performance-timing-projection.v1','production_ready':False,'qualification_status':'not_evaluated','capture_sha256':capture_sha256,'source_identity':capture.get('identity'),'source_identity_binding':capture.get('source_identity_binding'),'source_lock_sha256':capture.get('source_lock_sha256'),'served_source_hashes':capture.get('served_source_hashes'),'metrics':output,'metric_values':{key:row['value'] for key,row in output.items() if row['status']=='observed'},'limitations':['Scopes are explicit engineering observations, not an approved acceptance policy or complete profiler diagnostic.','Inclusive analysis stages overlap the named inner probes; do not sum all metrics into total elapsed time.','Compressed import, verified interruption/resume lineage, native subphase coverage and complete application FSEQ export remain outside this capture boundary.','Fresh origin cache is observed; host cache, thermal/resource controls, paired statistical comparison and authenticated human review remain separate.','Capture commit/tree declarations require independent Git-to-inventory binding before release evidence admission.']}

def load_strict(raw):
    def pairs(values):
        out={}
        for key,value in values:
            require(key not in out,'Duplicate JSON key: '+key);out[key]=value
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Non-finite JSON number: '+value)))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with args.capture.open('rb') as stream:raw=stream.read(32*1024**2+1)
    require(0<len(raw)<=32*1024**2,'Capture size outside bounds')
    result=project(load_strict(raw),capture_sha256=hashlib.sha256(raw).hexdigest())
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')

if __name__=='__main__':main()

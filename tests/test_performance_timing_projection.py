import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('performance_projection',ROOT/'tools/project_performance_timings.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def profile(stage,names=()):
    return {'schemaVersion':1,'kind':'analysis-stage-profile','stage':stage,'totalWallClockMs':1000,'timing':{'source':'performance.now','state':'available'},'attributes':{'performanceProbeVersion':1},'spanSummaryCoverage':{'namesComplete':True,'omittedSpanCount':0},'spanSummary':{'performance.'+name:{'count':120,'totalMs':120,'maxMs':1} for name in names},'cache':[{'domain':stage,'outcome':'miss'}]}

def capture():
    stages={stage:{'restored':False,'seconds':1,'profile':profile(stage)} for stage in module.STAGES}
    for name in module.PROBE_SCOPES:
        if name not in module.COMPILER:stages['rhythm']['profile']['spanSummary']['performance.'+name]={'count':120,'totalMs':120,'maxMs':1}
    compiler=profile('compiler',module.COMPILER)
    compiler['attributes']={'timingContract':'compiler-phases-v1','action':'generate','outcome':'completed','fseqGenerationScope':'header-only'}
    return {'schema':'lightforge.app-capture.v1','status':'captured','engine':{'stages':stages,'separationModel':{'runtime':'onnxruntime-web-wasm'},'resourceDiagnostics':{'scheduler':{'status':'available','waitMilliseconds':0}}},'compiler_profile':compiler,'timing':{'clock':'performance.now','analysis_ms':4000,'analysis_start_ms':10,'analysis_end_ms':4010},'source_identity_binding':{'git_to_inventory_binding':'requires-independent-release-orchestration'}}

class TimingProjectionTests(unittest.TestCase):
    def project(self,value=None):return module.project(capture() if value is None else value,capture_sha256='a'*64)
    def test_maps_all26_ids_and_uses_cumulative120_observations(self):
        result=self.project();self.assertEqual(len(result['metrics']),26)
        row=result['metrics']['performance.model_inference_seconds']
        self.assertEqual(row['value'],.12);self.assertEqual(row['observations'][0]['count'],120)
        self.assertEqual(result['metric_values']['performance.total_wall_clock_seconds'],4)
        self.assertEqual(result['metric_values']['performance.cache_miss_cost_seconds'],4)
        self.assertFalse(result['production_ready'])
        self.assertEqual(result['source_identity_binding']['git_to_inventory_binding'],'requires-independent-release-orchestration')
    def test_full_fseq_and_checkpoint_are_not_fabricated(self):
        result=self.project()
        self.assertEqual(result['metrics']['performance.fseq_generation_seconds']['status'],'partial')
        self.assertEqual(result['metrics']['performance.fseq_generation_seconds']['observed_subtotal'],.12)
        for name in ['fseq_generation','checkpoint_resume_overhead']:
            self.assertNotIn('performance.'+name+'_seconds',result['metric_values'])
    def test_zero_requires_actual_clock_observation(self):
        result=self.project();self.assertEqual(result['metric_values']['performance.synchronization_waiting_seconds'],0)
        value=capture();value['engine']['resourceDiagnostics']['scheduler']['waitMilliseconds']=None
        self.assertIsNone(self.project(value)['metrics']['performance.synchronization_waiting_seconds']['value'])
        value=capture();value['engine']['stages']['rhythm']['profile']['spanSummary'].pop('performance.drum_analysis')
        self.assertIsNone(self.project(value)['metrics']['performance.drum_analysis_seconds']['value'])
    def test_unavailable_named_interval_blocks_partial_sum(self):
        value=capture();bad=profile('voice',['model_inference']);bad['spanSummary']['performance.model_inference'].update(totalMs=None,maxMs=None,unavailableCount=1)
        value['engine']['stages']['voice']['profile']=bad
        result=self.project(value);row=result['metrics']['performance.model_inference_seconds']
        self.assertEqual(row['status'],'partial');self.assertIsNone(row['value']);self.assertEqual(row['observed_subtotal'],.12)
        self.assertNotIn(row['metric_id'],result['metric_values'])
    def test_name_omission_old_module_or_missing_stage_cannot_claim_coverage(self):
        for field in ['omitted','old','missing']:
            value=capture()
            if field=='omitted':value['engine']['stages']['voice']['profile']['spanSummaryCoverage'].update(namesComplete=False,omittedSpanCount=1)
            elif field=='old':value['engine']['stages']['voice']['profile']['attributes'].clear()
            else:del value['engine']['stages']['voice']
            self.assertEqual(self.project(value)['metrics']['performance.model_inference_seconds']['status'],'partial')
    def test_native_unknown_runtime_and_prior_attempts_remain_partial(self):
        for kind in ['native','unknown','retry']:
            value=capture()
            if kind=='native':value['engine']['separationModel']['runtime']='onnxruntime-android-cpu'
            elif kind=='unknown':value['engine']['separationModel'].clear()
            else:value['engine']['nativeFallback']={'reason':'native-fallback'}
            result=self.project(value)
            self.assertEqual(result['metrics']['performance.model_inference_seconds']['status'],'partial')
            if kind=='retry':
                self.assertNotIn('performance.cache_hit_rate',result['metric_values'])
                self.assertNotIn('performance.synchronization_waiting_seconds',result['metric_values'])
                self.assertEqual(result['metrics']['performance.rhythm_analysis_seconds']['status'],'partial')
            self.assertEqual(result['metrics']['performance.choreography_planning_seconds']['status'],'observed')
    def test_restored_stage_uses_observed_profile_not_synthetic_zero(self):
        value=capture();row=value['engine']['stages']['rhythm'];row.update(restored=True,seconds=0);row['profile']['cache']=[{'domain':'rhythm','outcome':'restore'}]
        result=self.project(value)
        self.assertEqual(result['metric_values']['performance.rhythm_analysis_seconds'],1)
        self.assertEqual(result['metric_values']['performance.cache_hit_rate'],.25)
        self.assertEqual(result['metric_values']['performance.cache_miss_cost_seconds'],3)
    def test_completed_span_survives_later_clock_failure_but_wall_does_not(self):
        value=capture();value['engine']['stages']['rhythm']['profile']['timing']['state']='observed-error'
        result=self.project(value);self.assertEqual(result['metric_values']['performance.model_inference_seconds'],.12)
        self.assertNotIn('performance.rhythm_analysis_seconds',result['metric_values'])
        self.assertNotIn('performance.cache_miss_cost_seconds',result['metric_values'])
    def test_malformed_nonfinite_or_duplicate_evidence_is_rejected(self):
        for bad in [float('inf'),-1,True]:
            value=capture();value['engine']['stages']['rhythm']['profile']['spanSummary']['performance.model_inference']['totalMs']=bad
            with self.assertRaises(ValueError):self.project(value)
        value=capture();value['timing']['analysis_end_ms']=0
        with self.assertRaises(ValueError):self.project(value)
        for raw in ['{"x":1,"x":2}','{"x":NaN}']:
            with self.assertRaises(ValueError):module.load_strict(raw)
    def test_failed_or_restore_compiler_does_not_become_generation_evidence(self):
        value=capture();value['compiler_profile']['attributes']['action']='restore'
        result=self.project(value)
        self.assertNotIn('performance.choreography_planning_seconds',result['metric_values'])

if __name__=='__main__':unittest.main()

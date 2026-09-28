from research_paths import REPO, MODELS, WORK, DEMO
from pathlib import Path
import hashlib,json,time,resource,statistics
import numpy as np
import onnxruntime as ort
assert ort.__version__ == "1.25.1"
ROOT=REPO
models={'q64':MODELS/'block-00-time.onnx','q128':WORK/'block-00-time-q128.onnx','q256':WORK/'block-00-time-q256.onnx'}
# Deterministic model-level regression input, not full-passage quality evidence.
x=np.random.default_rng(12031).normal(0,0.7,(4,1301,256)).astype(np.float32)
options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;options.enable_cpu_mem_arena=True;options.enable_mem_pattern=True;options.add_session_config_entry('session.intra_op.allow_spinning','0')
outputs={};rows=[]
for repeat in range(4):
 for name in (list(models) if repeat%2==0 else list(reversed(models))):
  before=time.perf_counter();s=ort.InferenceSession(str(models[name]),sess_options=options,providers=['CPUExecutionProvider']);init=time.perf_counter()-before
  before=time.perf_counter();out=s.run(None,{'input':x})[0];elapsed=time.perf_counter()-before
  if name not in outputs:outputs[name]=out
  row={'repeat':repeat,'name':name,'initSeconds':init,'runSeconds':elapsed,'sha256':hashlib.sha256(out.tobytes()).hexdigest(),'finite':bool(np.isfinite(out).all()),'maxAbsFromBaseline':float(np.abs(out-outputs['q64']).max()),'equalBytes':out.tobytes()==outputs['q64'].tobytes(),'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
  rows.append(row);print(json.dumps(row),flush=True);del s
edge_checks=[]
for case,edge in [('silence',np.zeros_like(x)),('sparse',np.where(np.indices(x.shape)[1]%113==0,x,0).astype(np.float32))]:
 baseline=None
 for name in models:
  s=ort.InferenceSession(str(models[name]),sess_options=options,providers=['CPUExecutionProvider']);out=s.run(None,{'input':edge})[0]
  if baseline is None:baseline=out
  edge_checks.append({'case':case,'name':name,'equalBytes':out.tobytes()==baseline.tobytes(),'finite':bool(np.isfinite(out).all()),'maxAbsFromBaseline':float(np.abs(out-baseline).max())});del s
receipt={'edges':edge_checks,'runtime':ort.__version__,'criterion':'synthetic full1301-frame single temporal graph only, warmup index0','models':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in models.items()},'inputSha256':hashlib.sha256(x.tobytes()).hexdigest(),'runs':rows,'medianRunSeconds':{n:statistics.median(r['runSeconds'] for r in rows if r['name']==n and r['repeat']>0) for n in models},'allEqual':all(r['equalBytes'] and r['finite'] for r in rows+edge_checks)}
(WORK/'screen.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:receipt[k] for k in ['medianRunSeconds','allEqual']}),flush=True)

from research_paths import REPO, MODELS, WORK, DEMO
from pathlib import Path
import hashlib,json,time,statistics,resource
import numpy as np,onnxruntime as ort
assert ort.__version__=='1.25.1'
root=REPO;out=WORK
models={'baseline':MODELS/'block-00-time.onnx','split':out/'block00-split-qkv.onnx'}
x=np.load(out/'real-time-input.npy');o=ort.SessionOptions();o.intra_op_num_threads=4;o.inter_op_num_threads=1;o.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;o.add_session_config_entry('session.intra_op.allow_spinning','0')
sessions={n:ort.InferenceSession(str(p),sess_options=o,providers=['CPUExecutionProvider']) for n,p in models.items()}
baseline=sessions['baseline'].run(None,{'input':x})[0];rows=[]
for repeat in range(8):
 for name in (list(models) if repeat%2==0 else list(reversed(models))):
  at=time.perf_counter();v=sessions[name].run(None,{'input':x})[0];elapsed=time.perf_counter()-at
  row={'repeat':repeat,'name':name,'seconds':elapsed,'equal':v.tobytes()==baseline.tobytes(),'finite':bool(np.isfinite(v).all()),'maxAbs':float(np.abs(v-baseline).max())};rows.append(row);print(json.dumps(row),flush=True)
report={'runtime':ort.__version__,'scope':'Original block00 temporal graph real-input screening, not fullpassage/Android acceptance. Interleaved8pairs, firstpairwarmup.','models':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in models.items()},'inputSha256':hashlib.sha256(x.tobytes()).hexdigest(),'rows':rows,'allEqual':all(r['equal'] and r['finite'] for r in rows),'median':{n:statistics.median(r['seconds'] for r in rows if r['repeat']>0 and r['name']==n) for n in models},'processPeakRss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
(out/'qkv-screen.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['allEqual','median','processPeakRss']}))

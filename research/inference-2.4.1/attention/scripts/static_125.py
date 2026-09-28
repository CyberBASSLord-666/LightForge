from research_paths import REPO, MODELS, WORK, DEMO
from pathlib import Path
from collections import Counter
import hashlib,json,time,statistics
import numpy as np, onnx, onnxruntime as ort
assert ort.__version__=='1.25.1'
root=REPO;out=WORK;model=MODELS/'block-00-time.onnx';x=np.load(out/'real-time-input.npy')
sessions={}
for static in [False,True]:
 o=ort.SessionOptions();o.intra_op_num_threads=4;o.inter_op_num_threads=1;o.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;o.add_session_config_entry('session.intra_op.allow_spinning','0');o.optimized_model_filepath=str(out/('block00-static-125.onnx' if static else 'block00-dynamic-125.onnx'))
 if static:o.add_free_dimension_override_by_name('batch',4)
 sessions[static]=ort.InferenceSession(str(model),sess_options=o,providers=['CPUExecutionProvider'])
baseline=sessions[False].run(None,{'input':x})[0];rows=[]
for r in range(6):
 for static in ([False,True] if r%2==0 else [True,False]):
  at=time.perf_counter();v=sessions[static].run(None,{'input':x})[0];elapsed=time.perf_counter()-at
  rows.append({'round':r,'static':static,'seconds':elapsed,'equal':v.tobytes()==baseline.tobytes(),'finite':bool(np.isfinite(v).all())})
report={'runtime':ort.__version__,'scope':'Diagnostic static-dimension screening only; simultaneous unrelated quality-only process means no performance-acceptance evidence.','rows':rows,'median':{str(k):statistics.median(r['seconds'] for r in rows if r['static']==k) for k in sessions},'ops':{label:dict(Counter(n.op_type for n in onnx.load(out/('block00-'+label+'-125.onnx')).graph.node)) for label in ['dynamic','static']}}
(out/'static-125-summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

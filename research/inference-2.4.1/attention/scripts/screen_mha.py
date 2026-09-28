from research_paths import REPO, MODELS, WORK, DEMO
"""Research screening only. Each subprocess has an isolated peak RSS receipt."""
from pathlib import Path
import json,sys,subprocess,statistics,hashlib
root=REPO;out=WORK
models={'baseline':MODELS/'block-00-time.onnx','nonflash':out/'block00-mha-nonflash.onnx','flash':out/'block00-mha-flash.onnx'}
if len(sys.argv)>1:
 import resource,time,numpy as np,onnxruntime as ort
 assert ort.__version__=='1.25.1';name=sys.argv[1]
 o=ort.SessionOptions();o.intra_op_num_threads=4;o.inter_op_num_threads=1;o.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;o.add_session_config_entry('session.intra_op.allow_spinning','0')
 s=ort.InferenceSession(str(models[name]),sess_options=o,providers=['CPUExecutionProvider']);x=np.load(out/'real-time-input.npy')
 refpath=out/'mha-original-output.npy';base=np.load(refpath) if refpath.exists() else None
 rows=[]
 for i in range(4):
  at=time.perf_counter();v=s.run(None,{'input':x})[0];elapsed=time.perf_counter()-at
  if base is None:assert name=='baseline';base=v.copy();np.save(refpath,base)
  delta=v.astype(np.float64)-base.astype(np.float64)
  rows.append({'run':i,'seconds':elapsed,'equal':v.tobytes()==base.tobytes(),'finite':bool(np.isfinite(v).all()),'maxAbs':float(np.max(np.abs(delta))),'rmse':float(np.sqrt(np.mean(delta*delta)))})
 print(json.dumps({'name':name,'rows':rows,'peakRss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'modelSha256':hashlib.sha256(models[name].read_bytes()).hexdigest(),'inputSha256':hashlib.sha256(x.tobytes()).hexdigest(),'referenceSha256':hashlib.sha256(base.tobytes()).hexdigest(),'outputSha256':hashlib.sha256(v.tobytes()).hexdigest()}));sys.exit(0)
reference=out/'mha-original-output.npy'
if reference.exists():reference.unlink()
rows=[]
for name in ['baseline','nonflash','flash','flash','nonflash','baseline']:
 p=subprocess.run([sys.executable,__file__,name],check=True,text=True,capture_output=True);r=json.loads(p.stdout);rows.append(r);print(json.dumps(r),flush=True)
report={'runtime':'1.25.1','scope':'Single real-input block00 temporal graph host screening, not fullpassage or Android acceptance. Two sequential process orders, 1 warmup+3 timed graph calls each; isolated process peak RSS.','rows':rows,'summary':{n:{'medianSeconds':statistics.median(r['seconds'] for p in rows if p['name']==n for r in p['rows'] if r['run']>0),'allEqual':all(r['equal'] and r['finite'] for p in rows if p['name']==n for r in p['rows']),'peakRss':max(p['peakRss'] for p in rows if p['name']==n)} for n in models}}
(out/'mha-screen.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['summary']))

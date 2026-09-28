from research_paths import REPO, MODELS, WORK, DEMO
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,time,wave
import numpy as np
import onnx,onnxruntime as ort
assert ort.__version__=='1.25.1'
repo=REPO;out=WORK;models=MODELS
with wave.open(str(DEMO)) as w:
 assert w.getnchannels()==2 and w.getsampwidth()==2 and w.getframerate()==44100
 w.setpos(661500);pcm=np.frombuffer(w.readframes(573300),dtype='<i2').reshape(-1,2).T.astype(np.float32)/32768
padded=np.pad(pcm,((0,0),(1024,1024)),mode='reflect');window=.5-.5*np.cos(2*np.pi*np.arange(2048)/2048)
frames=np.lib.stride_tricks.sliding_window_view(padded,2048,axis=1)[:,::441,:][:,:1301]
z=np.fft.rfft(frames*window,axis=-1).transpose(2,0,1).reshape(2050,1301)
spectrum=np.stack((z.real,z.imag),axis=-1).astype(np.float32)[None]
del padded,frames,z
opts=ort.SessionOptions();opts.intra_op_num_threads=4;opts.inter_op_num_threads=1;opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL;opts.add_session_config_entry('session.intra_op.allow_spinning','0')
front=ort.InferenceSession(str(models/'front.onnx'),sess_options=opts,providers=['CPUExecutionProvider']);latents=front.run(None,{'input':spectrum})[0][0];del front
x=np.ascontiguousarray(latents[:,24:28,:].transpose(1,0,2));np.save(out/'real-time-input.npy',x)
opts.enable_profiling=True;opts.profile_file_prefix=str(out/'ort125-temporal');opts.optimized_model_filepath=str(out/'block00-optimized-125.onnx')
session=ort.InferenceSession(str(models/'block-00-time.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
for i in range(4):result=session.run(None,{'input':x})[0]
profile=Path(session.end_profiling());events=json.loads(profile.read_text());ops=Counter();nodes=Counter();shapes={}
for e in events:
 if e.get('cat')=='Node' and e['name'].endswith('_kernel_time'):
  op=e['args'].get('op_name','?');ops[op]+=e['dur'];nodes[e['name']]+=e['dur'];shapes[e['name']]={'op':op,'input':e['args'].get('input_type_shape'),'output':e['args'].get('output_type_shape')}
report={'runtime':ort.__version__,'scope':'Four representative original block00 temporal runs on real demo-derived input. Python FFT preprocessing, not full Java pipeline qualification. Timings are diagnostic while unrelated quality-only task runs.','profilePath':profile.name,'modelSha256':hashlib.sha256((models/'block-00-time.onnx').read_bytes()).hexdigest(),'inputSha256':hashlib.sha256(x.tobytes()).hexdigest(),'inputShape':list(x.shape),'outputSha256':hashlib.sha256(result.tobytes()).hexdigest(),'opMicroseconds':dict(ops.most_common()),'topNodes':[{'name':n,'microseconds':v,**shapes[n]} for n,v in nodes.most_common(20)]}
(out/'profile-125-summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
print('optimizedOperators',dict(Counter(n.op_type for n in onnx.load(out/'block00-optimized-125.onnx').graph.node)))

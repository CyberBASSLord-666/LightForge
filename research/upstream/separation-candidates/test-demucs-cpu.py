from pathlib import Path
import onnx,numpy as np,onnxruntime as ort,soundfile as sf,json,collections,time,resource
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];model=HERE/'StemSplitio--htdemucs-ft-vocals-onnx--htdemucs_ft_vocals.onnx'
m=onnx.load(model,load_external_data=False)
shape=lambda x:[d.dim_value if d.HasField('dim_value') else d.dim_param for d in x.type.tensor_type.shape.dim]
r={'opset':[(x.domain,x.version) for x in m.opset_import],'ir':m.ir_version,'nodes':len(m.graph.node),'ops':dict(collections.Counter(n.op_type for n in m.graph.node)),'inputs':[(x.name,shape(x)) for x in m.graph.input],'outputs':[(x.name,shape(x)) for x in m.graph.output],'initializerBytes':sum(len(t.raw_data) for t in m.graph.initializer)};del m
print(json.dumps(r),flush=True)
audio,sr=sf.read(ROOT/'qa/release-1.5.0/vocal-fixtures/sung.wav',always_2d=True,dtype='float32')
if sr!=44100:
 from scipy.signal import resample_poly
 import math
 audio=resample_poly(audio,44100//math.gcd(sr,44100),sr//math.gcd(sr,44100))
if audio.shape[1]==1:audio=np.tile(audio,(1,2))
x=np.ascontiguousarray(audio[44100*5:44100*5+343980,:2].T)
if x.shape[1]<343980:x=np.pad(x,((0,0),(0,343980-x.shape[1])))
x.tofile(HERE/'demucs-input.f32')
options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
start=time.perf_counter();s=ort.InferenceSession(str(model),options,providers=['CPUExecutionProvider']);r['loadSeconds']=time.perf_counter()-start
start=time.perf_counter();y=s.run(None,{'mix':x[None]})[0];r['runSeconds']=time.perf_counter()-start
r.update({'finite':bool(np.isfinite(y).all()),'shape':list(y.shape),'rms':float(np.sqrt(np.mean(y*y))),'maxRSSBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'runtime':ort.__version__})
y.tofile(HERE/'demucs-reference.f32');sf.write(HERE/'demucs-vocals.wav',y[0,3].T,44100,subtype='FLOAT')
(HERE/'demucs-cpu-verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2),flush=True)

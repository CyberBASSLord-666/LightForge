"""Research capture: pretrained FT vocal specialist, upstream normalization, fixed full context.
No reference audio is read and no per-output alignment or gain fitting is performed.
"""
from pathlib import Path
import onnxruntime as ort,numpy as np,soundfile as sf,json,resource,time,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];FIX=ROOT/'qa/release-1.6.0/fixtures';N=343980
model=HERE/'StemSplitio--htdemucs-ft-vocals-onnx--htdemucs_ft_vocals.onnx'
options=ort.SessionOptions();options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL;options.intra_op_num_threads=2;options.inter_op_num_threads=1
start=time.perf_counter();session=ort.InferenceSession(str(model),options,providers=['CPUExecutionProvider']);print('Loaded',time.perf_counter()-start,flush=True)
manifest={'model':'HTDemucs FT vocals ONNX research4shift','modelSHA256':hashlib.file_digest(open(model,'rb'),'sha256').hexdigest(),'runtime':ort.__version__,'graphOptimization':'disabled','threads':2,'normalization':'Per-track mono-reference mean/std with torch unbiased sample standard deviation; restore after inference','context':'343980 frames at44100Hz, full upstream tensor context with4deterministic shifts drawn from random.Random(42) in[0,22050]; inverse shifts before average; no reference-based adjustment','shifts':[20952,3648,819,9012],'captures':[],'researchOnly':True,'weightLicense':'HF export says MIT; upstream author issue327 says provided only for scientific purposes, so private personal-app redistribution is not established.'}
for slug in [x+'-'+v for v in ['mix','instrumental'] for x in ['nightowl','stella','meaxic','grunge','falcon','sdrnr']]:
 a,sr=sf.read(FIX/(slug+'.wav'),always_2d=True,dtype='float32');assert sr==44100 and a.shape[1]==2
 mix=a.T;reference=mix.mean(axis=0);mean=np.float32(reference.mean());std=np.float32(reference.std(ddof=1));x=np.ascontiguousarray((mix-mean)/(std+1e-8));count=x.shape[1];assert count<=N
 start=time.perf_counter();acc=np.zeros((2,count),dtype=np.float32);offsets=[20952,3648,819,9012];maximumShift=22050
 padded=np.pad(x,((0,0),(maximumShift,maximumShift)))
 for offset in offsets:
  shiftedLength=count+maximumShift-offset;delta=N-shiftedLength;windowStart=offset-delta//2;windowEnd=windowStart+N
  correctStart=max(0,windowStart);correctEnd=min(padded.shape[1],windowEnd)
  input=np.pad(padded[:,correctStart:correctEnd],((0,0),(correctStart-windowStart,windowEnd-correctEnd)))
  assert input.shape==(2,N)
  stems=session.run(['stems'],{'mix':input[None]})[0]
  left=(N-shiftedLength)//2;shifted=stems[0,3,:,left:left+shiftedLength]
  acc+=shifted[:,maximumShift-offset:]
 vocals=((acc/len(offsets))*(std+1e-8)+mean).mean(axis=0).astype('<f4');assert np.isfinite(vocals).all() and len(vocals)==count
 dest=FIX/(slug+'-demucs4-separated-vocals.f32');vocals.tofile(dest)
 entry={'model':'HTDemucs FT vocals4shift','track':slug,'path':str(dest.relative_to(ROOT)),'sampleRate':sr,'channels':1,'samples':count,'seconds':time.perf_counter()-start,'mean':float(mean),'std':float(std),'shiftOffsets':offsets,'maxRSSBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
 manifest['captures'].append(entry);(HERE/'demucs4-fixture-captures.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(entry),flush=True)

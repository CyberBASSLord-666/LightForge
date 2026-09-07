"""Original-checkpoint vs staged ONNX parity on an actual mixture, same context."""
import pathlib,sys,time,json,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument('--checkpoint',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[2];p=args.output;p.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(root/'research/upstream/deux'))
with args.checkpoint.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa'
import torch,yaml,numpy as np,soundfile as sf,onnxruntime as ort
from models.bs_roformer.mel_band_roformer import MelBandRoformer
cfg=yaml.load((root/'research/upstream/deux/config.yaml').read_text(),Loader=yaml.FullLoader);torch.set_num_threads(6)
m=MelBandRoformer(**cfg['model']).eval();m.load_state_dict(torch.load(args.checkpoint,map_location='cpu',weights_only=True),strict=True)
audio,rate=sf.read(root/'qa/release-1.6.0/fixtures/falcon-mix.wav',dtype='float32');audio=np.pad(audio.T,((0,0),(66150,573300-66150-len(audio))));a=torch.from_numpy(audio)[None];t=time.time()
with torch.inference_mode():
 ref=m(a)[0].numpy();spec=torch.view_as_real(torch.stft(a[0],n_fft=2048,hop_length=441,win_length=2048,window=torch.hann_window(2048),return_complex=True)).permute(1,0,2,3).reshape(1,2050,1301,2).numpy()
print('torch seconds',time.time()-t,flush=True);np.save(p/'deux-reference.npy',ref);np.save(p/'deux-spectrum.npy',spec);del m
opt=ort.SessionOptions();opt.intra_op_num_threads=6;opt.enable_cpu_mem_arena=False
x=spec
for name in ['front']+[f'block-{i:02}' for i in range(12)]:
 t=time.time();s=ort.InferenceSession(str(root/'web/analysis/models/deux'/(name+'.onnx')),sess_options=opt);x=s.run(None,{'input':x})[0];del s;print(name,x.shape,time.time()-t,flush=True)
np.save(p/'deux-latents.npy',x);meta=json.loads((root/'web/analysis/models/deux/manifest.json').read_text());out=[]
for i in range(2):
 t=time.time();s=ort.InferenceSession(str(root/'web/analysis/models/deux'/f'head-{i}.onnx'),sess_options=opt);mask=s.run(None,{'input':x})[0];del s;print('head',i,mask.shape,time.time()-t,flush=True)
 summed=np.zeros_like(spec)
 for j,k in enumerate(meta['indices']):summed[:,k]+=mask[:,j]
 denom=np.repeat(np.array(meta['bandsPerFrequency']),2).astype('float32');summed/=np.maximum(1e-8,denom[None,:,None,None]);z=spec[...,0]+1j*spec[...,1];z*=summed[...,0]+1j*summed[...,1];z=z.reshape(1,1025,2,1301).transpose(0,2,1,3).reshape(2,1025,1301).copy()
 with torch.inference_mode():wav=torch.istft(torch.from_numpy(z),n_fft=2048,hop_length=441,win_length=2048,window=torch.hann_window(2048),length=573300).numpy()
 out.append(wav);print('error',float(np.max(np.abs(wav-ref[i]))),float(np.sqrt(np.mean((wav-ref[i])**2))),flush=True)
np.save(p/'deux-onnx-output.npy',np.stack(out));(p/'deux-parity.json').write_text(json.dumps({'maxAbsError':float(np.max(np.abs(np.stack(out)-ref))),'rmsError':float(np.sqrt(np.mean((np.stack(out)-ref)**2)))},indent=2))

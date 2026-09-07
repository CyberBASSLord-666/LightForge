#!/usr/bin/env python3
"""Reproduce bounded Deux graphs. Author weights CC BY-NC 4.0 (becruily).
Original float32 weights, full 13s context, independent band/frame batches.
Install tools/model-requirements.txt and CPU torch==2.6.0 first.
"""
import sys,pathlib,time,types,json,hashlib,argparse,urllib.request,tempfile,os
ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='https://huggingface.co/becruily/mel-band-roformer-deux/resolve/2da74427d682a3df47a774378fc24d7a1a0cdaad/becruily_deux.ckpt'
SHA='10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa'
parser=argparse.ArgumentParser();parser.add_argument('--checkpoint',type=pathlib.Path);args=parser.parse_args()
checkpoint=args.checkpoint or ROOT/'build/models/deux.ckpt'
if not checkpoint.exists():
 checkpoint.parent.mkdir(parents=True,exist_ok=True)
 tmp=checkpoint.with_suffix('.part')
 try:urllib.request.urlretrieve(URL,tmp);tmp.replace(checkpoint)
 finally:
  if tmp.exists():tmp.unlink()
with checkpoint.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==SHA,'Deux checkpoint hash mismatch'

sys.path.insert(0,str(ROOT/'research/upstream/deux'))
import torch,yaml,numpy as np
from torch import nn
from models.bs_roformer.mel_band_roformer import MelBandRoformer
from models.bs_roformer.attend import Attend
p=ROOT/'research/upstream/deux';out=ROOT/'web/analysis/models/deux';out.mkdir(parents=True,exist_ok=True);torch.set_num_threads(6)
cfg=yaml.load((p/'config.yaml').read_text(),Loader=yaml.FullLoader);model=MelBandRoformer(**cfg['model']).eval();model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True),strict=True)
def tiled(self,q,k,v):
 scale=self.scale or q.shape[-1]**-.5
 return torch.cat([torch.softmax(torch.matmul(q[:,:,a:a+64,:],k.transpose(-2,-1))*scale,dim=-1)@v for a in range(0,q.shape[-2],64)],dim=-2)
for m in model.modules():
 if isinstance(m,Attend):m.forward=types.MethodType(tiled,m)
class Front(nn.Module):
 def __init__(self,m):super().__init__();self.bands=m.band_split;self.register_buffer('indices',m.freq_indices)
 def forward(self,spectrum):
  x=spectrum[:,self.indices].permute(0,2,1,3).flatten(2);return self.bands(x)
class Head(nn.Module):
 def __init__(self,m,i):super().__init__();self.head=m.mask_estimators[i]
 def forward(self,x):return self.head(x).reshape(1,x.shape[1],-1,2).permute(0,2,1,3)
converter_sha=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
try:previous=json.loads((out/'manifest.json').read_text())
except (FileNotFoundError,json.JSONDecodeError):previous={}
frames=1301;x=torch.zeros(1,frames,60,256)
modules=[('front',Front(model),torch.zeros(1,2050,frames,2))]
for i,(time_block,frequency_block) in enumerate(model.layers):
 modules.extend([(f'block-{i:02}-time',time_block,torch.zeros(4,frames,256)),(f'block-{i:02}-frequency',frequency_block,torch.zeros(128,60,256))])
modules.extend((f'head-{i}',Head(model,i),x[:,:128]) for i in range(2))
for name,m,example in modules:
 dest=out/(name+'.onnx');t=time.time()
 entry=previous.get('files',{}).get(dest.name,{})
 cached=dest.exists() and previous.get('converterSHA256')==converter_sha and entry.get('bytes')==dest.stat().st_size and entry.get('sha256')==hashlib.sha256(dest.read_bytes()).hexdigest()
 if not cached:
  dynamic={'input':{0:'batch'},'output':{0:'batch'}} if name.startswith('block-') else {'input':{1:'frames'},'output':{2:'frames'}} if name.startswith('head-') else None
  with torch.inference_mode():torch.onnx.export(m.eval(),example,str(dest),input_names=['input'],output_names=['output'],dynamic_axes=dynamic,opset_version=17,do_constant_folding=True)
 print(name,dest.stat().st_size,round(time.time()-t,2),flush=True)
# Remove only the superseded combined blocks; no other model family is touched.
for i in range(12):(out/f'block-{i:02}.onnx').unlink(missing_ok=True)
meta={'converterSHA256':converter_sha,'id':'mel-band-roformer-deux-lightforge-2','name':'Mel-Band RoFormer Deux','author':'becruily','origin':URL,'checkpointSHA256':SHA,'license':'CC-BY-NC-4.0','licenseURL':'https://creativecommons.org/licenses/by-nc/4.0/','sourceCommit':'0e5f1159fc5ea87fc13b957584e178b4977e5dd3','conversion':'Float32; independent time-band batches of 4, frequency-frame and mask-head batches of 128; query tiles of 64 with complete key/value context; no weight quantization.','execution':'bounded-independent-batches-v1','headFrames':128,'frames':frames,'samples':573300,'fftSize':2048,'hop':441,'indices':model.freq_indices.tolist(),'bandsPerFrequency':model.num_bands_per_freq.tolist(),'files':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(out.glob('*.onnx'))}};(out/'manifest.json').write_text(json.dumps(meta,indent=2))

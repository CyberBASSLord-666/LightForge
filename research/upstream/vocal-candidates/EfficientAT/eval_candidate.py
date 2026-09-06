"""Evaluate original EfficientAT pretrained weights, without threshold fitting."""
import json,time,hashlib,sys, pathlib
import numpy as np
import torch, librosa
from models.mn.model import get_model
from models.preprocess import AugmentMelSTFT
from helpers.utils import labels

ROOT=pathlib.Path(__file__).resolve().parents[4]
OUT=ROOT/'qa/release-1.5.0/efficientat-candidate-verification.json'
FIX=ROOT/'qa/release-1.5.0/vocal-fixtures'
torch.set_num_threads(2)
model=get_model(pretrained_name='mn10_as').eval()
mel=AugmentMelSTFT().eval()
roles=['Singing','Choir','Vocal music','Speech','Music','Guitar','Piano','Drum','Bass guitar','Chant','Humming']
ids={k:labels.index(k) for k in roles if k in labels}
r={'model':'EfficientAT mn10_as','upstream':'https://github.com/fschmid56/EfficientAT','commit':'a425fdce92572e602a1d5634799bd9f1f2efa806','license':'MIT','checkpointSha256':hashlib.sha256(pathlib.Path('resources/mn10_as_mAP_471.pt').read_bytes()).hexdigest(),'classes':ids,'fixtures':{}}
for name in ['sung','instrumental','speech','percussion','silence','glass']:
 p=FIX/(name+'.wav')
 if not p.exists():continue
 y,sr=librosa.load(p,sr=32000,mono=True)
 runs={}
 for window in [10,3]:
  hop=window/2;length=round(window*sr);frames=[];t0=time.monotonic()
  for start in np.arange(0,len(y)/sr,hop):
   wav=y[round(start*sr):round(start*sr)+length]
   if len(wav)<length:wav=np.pad(wav,(0,length-len(wav)))
   with torch.no_grad():
    spec=mel(torch.from_numpy(wav)[None,:]); pred=torch.sigmoid(model(spec.unsqueeze(0))[0][0]).numpy()
   top=np.argsort(pred)[-5:][::-1]
   frames.append({'start':float(start),'end':min(len(y)/sr,float(start+window)), 'scores':{k:float(pred[v]) for k,v in ids.items()},'top':[[labels[i],float(pred[i])] for i in top]})
  runs[str(window)]={'seconds':time.monotonic()-t0,'frames':frames,'max':{k:max(f['scores'][k] for f in frames) for k in ids},'mean':{k:float(np.mean([f['scores'][k] for f in frames])) for k in ids}}
  print(name,window,runs[str(window)]['max'],flush=True)
 r['fixtures'][name]={'duration':len(y)/sr,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'runs':runs}
 OUT.write_text(json.dumps(r,indent=2))
print(OUT)

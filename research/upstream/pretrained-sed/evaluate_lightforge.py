import os,sys,json,time
from pathlib import Path
import torch,numpy as np,soundfile as sf
from scipy.signal import resample_poly
from models.frame_mn.Frame_MN_wrapper import FrameMNWrapper
from models.prediction_wrapper import PredictionsWrapper
from data_util.audioset_classes import as_strong_train_classes
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
os.chdir(HERE);torch.set_num_threads(1)
base=FrameMNWrapper(1.0);dim=base.state_dict()['frame_mn.features.16.1.bias'].shape[0];model=PredictionsWrapper(base,checkpoint='frame_mn10_strong_1',embed_dim=dim).eval()
names=as_strong_train_classes
ids=[i for i,x in enumerate(names) if x in ['Singing','Choir','Chant','Humming','Rapping']]
print('ids',[(i,names[i]) for i in ids],flush=True)
results={}
for name in ['sung','instrumental','speech','percussion','glass']:
 x,sr=sf.read(ROOT/'qa/release-1.5.0/vocal-fixtures'/f'{name}.wav');x=resample_poly(x,320,441).astype('float32');scores=[];t=time.time()
 for first in range(0,len(x),160000):
  chunk=np.zeros(160000,dtype='float32');chunk[:min(160000,len(x)-first)]=x[first:first+160000]
  with torch.no_grad(): m=model.mel_forward(torch.from_numpy(chunk[None]));out=model(m)[0];scores.append(torch.sigmoid(out)[0].numpy())
 scores=np.concatenate(scores,axis=1)[:,:int(np.ceil(len(x)/640))];s=scores[ids].max(axis=0)
 r={'maxSinging':float(s.max()),'meanSinging':float(s.mean()),'fractionAbove035':float(np.mean(s>=.35)),'seconds':time.time()-t,'topClasses':[(names[i],float(scores[i].mean()),float(scores[i].max())) for i in np.argsort(scores.mean(axis=1))[-12:][::-1]],'vocalScores':s.tolist()};results[name]=r;print(name,json.dumps({k:v for k,v in r.items() if k!='vocalScores'}),flush=True)
(ROOT/'qa/release-1.5.0/vocal-sed-candidate.json').write_text(json.dumps(results))

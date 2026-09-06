"""Convert credited BeatNet model1 to a state-explicit ONNX for mobile WASM."""
from pathlib import Path
import importlib.util,json,hashlib,sys
import numpy as np
import torch
from torch import nn
from scipy.signal import firwin
root=Path(__file__).resolve().parents[1]
src=root/'research/upstream/BeatNet/model.py'
spec=importlib.util.spec_from_file_location('beatnet_model',src)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
m=mod.BDA(272,150,2,'cpu')
weights=root/'research/upstream/BeatNet/model_1_weights.pt'
m.load_state_dict(torch.load(weights,weights_only=True));m.eval()
class Export(nn.Module):
 def __init__(self,m):
  super().__init__();self.m=m
 def forward(self,features,h,c):
  z=features.reshape(-1,1,272)
  z=torch.nn.functional.max_pool1d(torch.relu(self.m.conv1(z)),2).flatten(1)
  z=self.m.linear0(z).reshape(1,-1,150)
  z,(h,c)=self.m.lstm(z,(h,c))
  p=torch.softmax(self.m.linear(z),dim=2)
  return p,h,c
model=Export(m).eval();torch.set_num_threads(2)
x=torch.rand(1,100,272);h=torch.zeros(2,1,150);c=h.clone()
out=root/'web/analysis/models/beatnet-v1.onnx'
torch.onnx.export(model,(x,h,c),str(out),dynamo=False,opset_version=17,input_names=['features','h','c'],output_names=['probabilities','hn','cn'],dynamic_axes={'features':{1:'frames'},'probabilities':{1:'frames'}})
import onnx,onnxruntime as ort
onnx.checker.check_model(onnx.load(str(out)))
s=ort.InferenceSession(str(out),providers=['CPUExecutionProvider'])
npout=s.run(None,{'features':x.numpy(),'h':h.numpy(),'c':c.numpy()})
with torch.no_grad(): ref=model(x,h,c)
err=max(float(np.max(np.abs(a-b.numpy()))) for a,b in zip(npout,ref))
assert err<1e-4,err
# Build exact Madmom136-band triangle bank used to train this model.
# Only this build step reads madmom; exported numeric coefficients require noPython on-device.
filtersrc=(root/'research/upstream/madmom/filters.py').read_text().replace('from ..processors import Processor','class Processor: pass')
ns={'__name__':'filter_reference'};exec(filtersrc,ns)
freq=np.fft.fftfreq(1410,1/22050)[:705]
fb=ns['LogarithmicFilterbank'](freq,num_bands=24,fmin=30,fmax=17000,norm_filters=True)
assert fb.shape==(705,136),fb.shape
sparse=[]
for i in range(136):
 bins=np.flatnonzero(fb[:,i]);sparse.append({'start':int(bins[0]),'weights':fb[bins,i].astype(float).tolist(),'frequency':float(freq[np.argmax(fb[:,i])])})
config={'sampleRate':22050,'windowLength':1411,'hop':441,'fftBins':705,'bands':sparse,'resampleHalfFIR':firwin(63,0.47,window=('kaiser',8.6)).tolist(),'featureOrder':'136log10(1+filteredMagnitude),136positiveFirstDifferences','source':'https://github.com/mjhydri/BeatNet','model':'model_1_weights.pt','sourceSha256':hashlib.sha256(weights.read_bytes()).hexdigest(),'onnxSha256':hashlib.sha256(out.read_bytes()).hexdigest(),'exportMaxAbsError':err}
(root/'web/analysis/models/features.json').write_text(json.dumps(config,separators=(',',':')))
print(json.dumps({'onnxBytes':out.stat().st_size,'exportMaxAbsError':err,'sha256':config['onnxSha256']},indent=2))

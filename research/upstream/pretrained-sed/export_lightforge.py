"""Export unmodified pretrained Frame-MN10 strong head, numerical reference tests.
MIT upstream https://github.com/fschmid56/PretrainedSED, checkpoint frame_mn10_strong_1.
"""
import os,sys,json,hashlib,contextlib,io
from pathlib import Path
import torch,torchaudio,numpy as np,onnxruntime as ort,onnx
from models.frame_mn.Frame_MN_wrapper import FrameMNWrapper
from models.prediction_wrapper import PredictionsWrapper
from data_util.audioset_classes import as_strong_train_classes
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'web/analysis/models';QA=ROOT/'qa/release-1.5.0'
os.chdir(HERE);torch.set_num_threads(1)
with contextlib.redirect_stdout(io.StringIO()):
 base=FrameMNWrapper(1.0);dim=base.state_dict()['frame_mn.features.16.1.bias'].shape[0];model=PredictionsWrapper(base,checkpoint='frame_mn10_strong_1',embed_dim=dim).eval()
class Strong(torch.nn.Module):
 def __init__(self,m):super().__init__();self.m=m
 def forward(self,mel):return torch.sigmoid(self.m(mel)[0])
core=Strong(model);rng=np.random.default_rng(51773);pcm=rng.normal(0,.2,160000).astype('float32')
with torch.no_grad():
 features=model.mel_forward(torch.from_numpy(pcm[None]));reference=core(features).numpy()
out=OUT/'frame-mn10-singing.onnx'
torch.onnx.export(core,features,str(out),input_names=['log_mel'],output_names=['scores'],opset_version=17,dynamo=False,do_constant_folding=True)
graph=onnx.load(out);onnx.checker.check_model(graph)
session=ort.InferenceSession(str(out),providers=['CPUExecutionProvider']);actual=session.run(None,{'log_mel':features.numpy()})[0];maximum=float(np.max(np.abs(actual-reference)));assert maximum<5e-5,maximum
names=as_strong_train_classes;singing=[i for i,x in enumerate(names) if x in ['Singing','Male singing','Female singing','Child singing','Choir','Chant','Humming','Rapping','Synthetic singing','Yodeling','Mantra']];speech=[i for i,x in enumerate(names) if x in ['Speech','Male speech, man speaking','Female speech, woman speaking','Child speech, kid speaking','Narration, monologue']]
manifest={'name':'PretrainedSED Frame-MN10','id':'frame-mn10-strong-1','file':out.name,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size,'license':'MIT','source':'https://github.com/fschmid56/PretrainedSED','weightsSource':'https://github.com/fschmid56/PretrainedSED/releases/download/v0.0.1/frame_mn10_strong_1.pt','weightsSHA256':hashlib.sha256((HERE/'resources/frame_mn10_strong_1.pt').read_bytes()).hexdigest(),'sampleRate':16000,'inputShape':[1,1,128,1000],'outputShape':[1,447,250],'contextSeconds':10,'frameSeconds':.04,'classNames':names,'singingClassIds':singing,'speechClassIds':speech,'capabilities':['Singing activity trained with strong frame-level AudioSet labels','Male/female/child singing, choir, humming, chant and rap','No source separation, lyrics or individual sung-note transcription']}
(OUT/'vocal-model.json').write_text(json.dumps(manifest,indent=2)+'\n');(OUT/'VOCAL-MODEL-LICENSE.txt').write_bytes((HERE/'LICENSE').read_bytes())
mel,_=torchaudio.compliance.kaldi.get_mel_banks(128,512,16000,0,7000,vtln_low=100,vtln_high=-500,vtln_warp_factor=1)
# Include literal float32 filter/window coefficients from the author's frontend.
front={'sampleRate':16000,'fft':512,'window':400,'hop':160,'mels':128,'preemphasis':.97,'floor':1e-7,'normalizeAdd':4.5,'normalizeDivide':5,'melWeights':[[[int(k),float(v)] for k,v in enumerate(row) if v>0] for row in mel.numpy()],'windowValues':model.model.mel.window_400.numpy().tolist()}
(OUT/'vocal-frontend.json').write_text(json.dumps(front,separators=(',',':'))+'\n')
(QA/'vocal-fixtures/sed-frontend-reference.json').write_text(json.dumps({'pcm':pcm.tolist(),'frames':1000,'mel':features.numpy().ravel().tolist()},separators=(',',':')))
receipt={'passed':True,'torch':torch.__version__,'onnxruntime':ort.__version__,'maxAbsScoreError':maximum,'model':{k:v for k,v in manifest.items() if k not in ['classNames']},'meaning':'Numerical agreement to original pretrained Frame-MN10 strong model, not an accuracy benchmark'}
(QA/'vocal-reference-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

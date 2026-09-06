#!/usr/bin/env python3
"""Compare original Google Keras model to shipped ONNX and make JS frontend oracle."""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL']='3';os.environ['TF_ENABLE_ONEDNN_OPTS']='0';os.environ['CUDA_VISIBLE_DEVICES']=''
from pathlib import Path
import sys,json,hashlib,time
import numpy as np,tensorflow as tf,onnxruntime as ort
import params,yamnet,features
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];QA=ROOT/'qa/release-1.5.0';P=params.Params()
tf.config.threading.set_inter_op_parallelism_threads(1);tf.config.threading.set_intra_op_parallelism_threads(1)
model=yamnet.yamnet_frames_model(P);model.load_weights(str(HERE/'yamnet.h5'))
session=ort.InferenceSession(str(ROOT/'web/analysis/models/yamnet.onnx'),providers=['CPUExecutionProvider'])
rng=np.random.default_rng(51773);pcm=(rng.uniform(-.3,.3,15600)+.3*np.sin(2*np.pi*220*np.arange(15600)/16000)).astype(np.float32)
mel,patches=features.waveform_to_log_mel_spectrogram_patches(pcm,P)
ref=model(pcm)[0].numpy();actual=session.run(None,{'log_mel':patches.numpy()[:,None]})[0]
maximum=float(np.max(np.abs(ref-actual)));assert maximum<2e-5,maximum
names=[r for r in yamnet.class_names(str(HERE/'yamnet_class_map.csv'))]
checks=[]
for name,wav,expected in [('silence',np.zeros(15600,dtype=np.float32),'Silence'),('sine440',np.sin(2*np.pi*440*np.arange(15600)/16000).astype(np.float32),'Sine wave'),('noise',rng.uniform(-1,1,15600).astype(np.float32),'White noise')]:
 m,p=features.waveform_to_log_mel_spectrogram_patches(wav,P);r=model(wav)[0].numpy();a=session.run(None,{'log_mel':p.numpy()[:,None]})[0];d=float(np.max(np.abs(r-a)));top=[names[i] for i in np.argsort(a[0])[-10:][::-1]];assert d<2e-5,(name,d);assert expected in top,(expected,top);checks.append({'fixture':name,'maxAbsScoreError':d,'expectedClass':expected,'topClasses':top})
(QA/'vocal-fixtures').mkdir(exist_ok=True);(QA/'vocal-fixtures/frontend-reference.json').write_text(json.dumps({'pcm':pcm.tolist(),'frames':96,'mel':mel.numpy().ravel().tolist()}))
receipt={'passed':True,'tensorflow':tf.__version__,'onnxruntime':ort.__version__,'coreMaxAbsScoreError':maximum,'checks':checks,'meaning':'Numerical agreement with the original Google model; not a singing accuracy benchmark','model_sha256':hashlib.sha256((ROOT/'web/analysis/models/yamnet.onnx').read_bytes()).hexdigest()};(QA/'vocal-reference-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

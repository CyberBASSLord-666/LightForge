#!/usr/bin/env python3
"""Reproduce Google's unmodified YAMNet classifier core in ONNX, opset 13.
Downloads are separately recorded. No training, quantization or label changes.
Inference batch normalization is folded algebraically into each convolution.
"""
from pathlib import Path
import hashlib,json,csv
import h5py,numpy as np,onnx
from onnx import helper as H,numpy_helper as N,TensorProto as T
HERE=Path(__file__).resolve().parent
OUT=HERE.parents[2]/'web/analysis/models'
h=h5py.File(HERE/'yamnet.h5','r');nodes=[];initializers=[];cur='log_mel';channels=1

def weight(name,value):
 initializers.append(N.from_array(np.asarray(value,dtype=np.float32),name));return name

def conv(prefix,stride,depthwise=False):
 global cur,channels
 k=np.asarray(h[f'{prefix}/{prefix}/'+('depthwise_kernel:0' if depthwise else 'kernel:0')])
 w=k.transpose(2,3,0,1) if depthwise else k.transpose(3,2,0,1)
 bn=prefix+'/bn';mean=np.asarray(h[f'{bn}/{bn}/moving_mean:0']);var=np.asarray(h[f'{bn}/{bn}/moving_variance:0']);beta=np.asarray(h[f'{bn}/{bn}/beta:0'])
 scale=1/np.sqrt(var+np.float32(1e-4));w=w*scale[:,None,None,None];bias=beta-mean*scale
 y=prefix+'_out';a=prefix+'_relu';group=channels if depthwise else 1
 nodes.append(H.make_node('Conv',[cur,weight(prefix+'_W',w),weight(prefix+'_B',bias)],[y],name=prefix,strides=[stride,stride],auto_pad='SAME_UPPER',group=group))
 nodes.append(H.make_node('Relu',[y],[a],name=a));cur=a;channels=len(bias)
conv('layer1/conv',2)
for layer,stride in enumerate([1,2,1,2,1,2,1,1,1,1,1,2,1],start=2):
 conv(f'layer{layer}/depthwise_conv',stride,True);conv(f'layer{layer}/pointwise_conv',1)
nodes.append(H.make_node('GlobalAveragePool',[cur],['pooled']))
nodes.append(H.make_node('Flatten',['pooled'],['embedding'],axis=1))
nodes.append(H.make_node('Gemm',['embedding',weight('classifier_W',h['logits/logits/kernel:0']),weight('classifier_B',h['logits/logits/bias:0'])],['logits']))
nodes.append(H.make_node('Sigmoid',['logits'],['scores']))
graph=H.make_graph(nodes,'Google YAMNet pretrained classifier',[H.make_tensor_value_info('log_mel',T.FLOAT,['batch',1,96,64])],[H.make_tensor_value_info('scores',T.FLOAT,['batch',521])],initializer=initializers)
model=H.make_model(graph,producer_name='LightForge reproducible YAMNet port',opset_imports=[H.make_opsetid('',13)],ir_version=8)
model.doc_string='Google YAMNet AudioSet classifier, original pretrained yamnet.h5 weights; Apache-2.0. Log-mel input must match upstream features.py.'
onnx.checker.check_model(model);OUT.mkdir(parents=True,exist_ok=True);dest=OUT/'yamnet.onnx';onnx.save_model(model,dest)
classes=list(csv.DictReader((HERE/'yamnet_class_map.csv').open()))
manifest={'name':'Google YAMNet','id':'google-yamnet-audioset-v1','file':dest.name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bytes':dest.stat().st_size,'license':'Apache-2.0','source':'https://github.com/tensorflow/models/tree/master/research/audioset/yamnet','weightsSource':'https://storage.googleapis.com/audioset/yamnet.h5','weightsSHA256':hashlib.sha256((HERE/'yamnet.h5').read_bytes()).hexdigest(),'sampleRate':16000,'inputShape':['batch',1,96,64],'patchWindowSeconds':.975,'patchHopSeconds':.24,'classNames':[x['display_name'] for x in classes],'singingClassIds':[int(x['index']) for x in classes if x['display_name'] in ['Singing','Choir','Yodeling','Chant','Mantra','Child singing','Synthetic singing']],'speechClassIds':[0,1,2,3,4,5,6]}
(OUT/'vocal-model.json').write_text(json.dumps(manifest,indent=2)+'\n');(OUT/'YAMNET-LICENSE.txt').write_bytes((HERE/'LICENSE').read_bytes())
print(json.dumps({k:v for k,v in manifest.items() if k!='classNames'},indent=2))

from research_paths import REPO, MODELS, WORK, DEMO
"""Research-only ORT 1.25 MHA rewrite. Neither variant is production-qualified."""
from pathlib import Path
import onnx,numpy as np,hashlib,json
from onnx import numpy_helper,helper
root=REPO
source=MODELS/'block-00-time.onnx'
for flash in [False,True]:
 m=onnx.load(source);before={w.name:w.SerializeToString() for w in m.graph.initializer}
 prod={o:n for n in m.graph.node for o in n.output}
 concat=next(n for n in m.graph.node if n.name.endswith('/attend/Concat'))
 assert len(concat.input)==21
 value=prod[concat.input[0]];softmax=prod[value.input[0]];scale=prod[softmax.input[0]];qk=prod[scale.input[0]];query=prod[qk.input[0]];kt=prod[qk.input[1]]
 assert [n.op_type for n in [value,softmax,scale,qk,query,kt]]==['MatMul','Softmax','Mul','MatMul','Slice','Transpose']
 assert helper.get_attribute_value(kt.attribute[0])==[0,1,3,2]
 q,k,v=query.input[0],kt.input[0],value.input[1]
 scale_pow=prod[scale.input[1]]
 assert scale_pow.op_type=='Pow'
 assert float(numpy_helper.to_array(prod[scale_pow.input[1]].attribute[0].t))==-0.5
 scale_value=64**-0.5;assert scale_value==0.125
 ns=[];prefix='lightforge/mha'
 m.graph.initializer.append(numpy_helper.from_array(np.array([0,0,512],dtype=np.int64),prefix+'/flatten'))
 m.graph.initializer.append(numpy_helper.from_array(np.array([0,0,8,64],dtype=np.int64),prefix+'/unflatten'))
 def flatten(name,source):
  ns.append(helper.make_node('Transpose',[source],[prefix+'/'+name+'/transposed'],name=prefix+'/'+name+'/Transpose',perm=[0,2,1,3]))
  ns.append(helper.make_node('Reshape',[prefix+'/'+name+'/transposed',prefix+'/flatten'],[prefix+'/'+name+'/flat'],name=prefix+'/'+name+'/Reshape'))
  return prefix+'/'+name+'/flat'
 q=flatten('query',q)
 if flash:k=flatten('key',k);v=flatten('value',v)
 ns.append(helper.make_node('MultiHeadAttention',[q,k,v],[prefix+'/out'],name=prefix+'/Attention',domain='com.microsoft',num_heads=8,scale=0.125,unidirectional=0))
 ns.append(helper.make_node('Reshape',[prefix+'/out',prefix+'/unflatten'],[prefix+'/out-shaped'],name=prefix+'/OutputReshape'))
 ns.append(helper.make_node('Transpose',[prefix+'/out-shaped'],list(concat.output),name=prefix+'/OutputTranspose',perm=[0,2,1,3]))
 allnodes=[]
 for n in m.graph.node:
  if n.name==concat.name:allnodes.extend(ns)
  else:allnodes.append(n)
 needed={o.name for o in m.graph.output};keep=[]
 for n in reversed(allnodes):
  if any(o in needed for o in n.output):keep.append(n);needed.update(n.input)
 del m.graph.node[:];m.graph.node.extend(reversed(keep))
 m.opset_import.append(helper.make_opsetid('com.microsoft',1))
 assert all(next(w.SerializeToString() for w in m.graph.initializer if w.name==n)==b for n,b in before.items())
 onnx.checker.check_model(m)
 dest=WORK/('block00-mha-'+('flash' if flash else 'nonflash')+'.onnx');onnx.save(m,dest)
 print(json.dumps({'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'model':str(dest),'flash':flash,'allOriginalInitializerBytesPreserved':True,'nodes':len(m.graph.node)}))

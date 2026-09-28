from research_paths import REPO, MODELS, WORK, DEMO
"""Research-only pinned ORT 1.25 nonflash MHA for the original 21 query tiles."""
from pathlib import Path
import onnx,numpy as np,hashlib,json
from onnx import numpy_helper,helper
root=REPO;source=MODELS/'block-00-time.onnx';dest=WORK/'block00-mha-tiled.onnx'
m=onnx.load(source);before={w.name:w.SerializeToString() for w in m.graph.initializer};prod={o:n for n in m.graph.node for o in n.output}
concat=next(n for n in m.graph.node if n.name.endswith('/attend/Concat'));assert len(concat.input)==21
prefix='lightforge/tiled_mha';m.graph.initializer.extend([numpy_helper.from_array(np.array([0,0,512],dtype=np.int64),prefix+'/flatten'),numpy_helper.from_array(np.array([0,0,8,64],dtype=np.int64),prefix+'/unflatten')]);replacements={};shared=None
for tile,out in enumerate(concat.input):
 value=prod[out];softmax=prod[value.input[0]];scale=prod[softmax.input[0]];qk=prod[scale.input[0]];query=prod[qk.input[0]];kt=prod[qk.input[1]]
 assert [n.op_type for n in [value,softmax,scale,qk,query,kt]]==['MatMul','Softmax','Mul','MatMul','Slice','Transpose']
 assert helper.get_attribute_value(kt.attribute[0])==[0,1,3,2]
 assert [numpy_helper.to_array(prod[s].attribute[0].t).tolist() for s in query.input[1:]]==[[64*tile],[64*(tile+1)],[2],[1]]
 pow_node=prod[scale.input[1]];assert pow_node.op_type=='Pow' and float(numpy_helper.to_array(prod[pow_node.input[1]].attribute[0].t))==-0.5
 current=(query.input[0],kt.input[0],value.input[1],scale.input[1])
 if shared is None:shared=current
 assert current==shared
 name=prefix+'/'+str(tile)
 replacements[value.name]=[
  helper.make_node('Transpose',[qk.input[0]],[name+'/transposed'],name=name+'/QueryTranspose',perm=[0,2,1,3]),
  helper.make_node('Reshape',[name+'/transposed',prefix+'/flatten'],[name+'/flat'],name=name+'/QueryReshape'),
  helper.make_node('MultiHeadAttention',[name+'/flat',kt.input[0],value.input[1]],[name+'/out'],name=name+'/Attention',domain='com.microsoft',num_heads=8,scale=0.125,unidirectional=0),
  helper.make_node('Reshape',[name+'/out',prefix+'/unflatten'],[name+'/out-shaped'],name=name+'/OutputReshape'),
  helper.make_node('Transpose',[name+'/out-shaped'],[out],name=name+'/OutputTranspose',perm=[0,2,1,3])]
allnodes=[]
for n in m.graph.node:allnodes.extend(replacements.get(n.name,[n]))
needed={o.name for o in m.graph.output};keep=[]
for n in reversed(allnodes):
 if any(o in needed for o in n.output):keep.append(n);needed.update(n.input)
del m.graph.node[:];m.graph.node.extend(reversed(keep));m.opset_import.append(helper.make_opsetid('com.microsoft',1))
assert all(next(w.SerializeToString() for w in m.graph.initializer if w.name==n)==b for n,b in before.items())
onnx.checker.check_model(m);onnx.save(m,dest)
print(json.dumps({'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'allOriginalInitializerBytesPreserved':True,'queryTileCount':21,'queryTileSize':64,'fullContext':1301,'nodes':len(m.graph.node)}))

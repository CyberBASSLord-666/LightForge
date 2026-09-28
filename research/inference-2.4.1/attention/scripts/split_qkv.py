from research_paths import REPO, MODELS, WORK, DEMO
"""Research-only QKV projection split; the trained weight values are preserved exactly."""
from pathlib import Path
import onnx,numpy as np,hashlib,json
from onnx import numpy_helper,helper
ROOT=REPO;source=MODELS/'block-00-time.onnx';dest=WORK/'block00-split-qkv.onnx'
m=onnx.load(source)
qkv=next(n for n in m.graph.node if n.name=='/layers.0.0/to_qkv/MatMul');split=next(n for n in m.graph.node if n.name=='/layers.0.0/Split')
assert qkv.op_type=='MatMul' and split.op_type=='Split' and len(split.output)==3
squeezes=[next(n for n in m.graph.node if n.op_type=='Squeeze' and n.input[0]==o) for o in split.output]
weights=next(w for w in m.graph.initializer if w.name==qkv.input[1]);w=numpy_helper.to_array(weights);assert w.shape==(256,1536) and w.dtype==np.float32
parts=[np.ascontiguousarray(w[:,i*512:(i+1)*512]) for i in range(3)];assert np.concatenate(parts,axis=1).tobytes()==w.tobytes()
shape_name='lightforge/qkv/split_shape';m.graph.initializer.append(numpy_helper.from_array(np.array([0,0,8,64],dtype=np.int64),shape_name))
new=[]
for i,part in enumerate(parts):
 name='lightforge/qkv/'+str(i);m.graph.initializer.append(numpy_helper.from_array(part,name+'/weight'))
 new.append(helper.make_node('MatMul',[qkv.input[0],name+'/weight'],[name+'/projected'],name=name+'/MatMul'))
 new.append(helper.make_node('Reshape',[name+'/projected',shape_name],[name+'/shaped'],name=name+'/Reshape'))
 new.append(helper.make_node('Transpose',[name+'/shaped'],[squeezes[i].output[0]],name=name+'/Transpose',perm=[0,2,1,3]))
nodes=[];removed={split.name,*[n.name for n in squeezes]}
for n in m.graph.node:
 if n.name==qkv.name:nodes.extend(new)
 elif n.name not in removed:nodes.append(n)
needed={o.name for o in m.graph.output};kept=[]
for n in reversed(nodes):
 if any(o in needed for o in n.output):kept.append(n);needed.update(n.input)
del m.graph.node[:];m.graph.node.extend(reversed(kept))
kept_weights=[w for w in m.graph.initializer if w.name in needed];del m.graph.initializer[:];m.graph.initializer.extend(kept_weights)
onnx.checker.check_model(m);onnx.save(m,dest)
print(json.dumps({'candidate':str(dest),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'qkvWeightBytesPreserved':True,'nodes':len(m.graph.node)}))

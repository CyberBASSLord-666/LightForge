from research_paths import REPO, MODELS, WORK, DEMO
"""Research-only exact semantic query retile; leaves all weights/context untouched."""
from pathlib import Path
import argparse, copy, hashlib, json, collections
import numpy as np
import onnx
from onnx import numpy_helper, helper

def retile(source, dest, tile):
    assert tile in [128,256]
    m=onnx.load(source)
    before={x.name:x.SerializeToString() for x in m.graph.initializer}
    producers={out:n for n in m.graph.node for out in n.output}
    concats=[n for n in m.graph.node if n.name.endswith('/attend/Concat')]
    assert len(concats)==1
    concat=concats[0]
    assert len(concat.input)==21 and helper.get_attribute_value(concat.attribute[0])==-2
    keep=[]
    shared=None
    uses=collections.Counter(x for n in m.graph.node for x in n.input)
    for i,out in enumerate(concat.input):
        mv=producers[out];assert mv.op_type=='MatMul'
        sm=producers[mv.input[0]];assert sm.op_type=='Softmax'
        assert helper.get_attribute_value(sm.attribute[0])==-1
        scale=producers[sm.input[0]];assert scale.op_type=='Mul'
        mm=producers[scale.input[0]];assert mm.op_type=='MatMul'
        sl=producers[mm.input[0]];assert sl.op_type=='Slice'
        current=(sl.input[0],mm.input[1],mv.input[1],scale.input[1])
        if shared is None:shared=current
        assert current==shared, 'Every query tile must use the same Q, K, V and scale'
        assert uses[sl.input[2]]==1, 'Tile-end constant must not affect another graph operation'
        consts=[producers[x] for x in sl.input[1:]]
        assert all(c.op_type=='Constant' for c in consts)
        vals=[numpy_helper.to_array(c.attribute[0].t) for c in consts]
        assert [v.tolist() for v in vals]==[[64*i],[64*(i+1)],[2],[1]]
        if i%(tile//64)==0:
            keep.append(out)
            consts[1].attribute[0].t.CopyFrom(numpy_helper.from_array(np.array([min(1301,64*i+tile)],dtype=np.int64)))
    del concat.input[:];concat.input.extend(keep)
    needed={o.name for o in m.graph.output}
    chosen=[]
    for n in reversed(m.graph.node):
        if any(out in needed for out in n.output):
            chosen.append(n)
            needed.update(n.input)
    del m.graph.node[:];m.graph.node.extend(reversed(chosen))
    # No tensor value_info exists in original exporter; do not trust stale shapes.
    assert len(m.graph.value_info)==0
    after={x.name:x.SerializeToString() for x in m.graph.initializer}
    assert before==after
    onnx.checker.check_model(m)
    dest.parent.mkdir(parents=True,exist_ok=True)
    onnx.save(m,dest)
    return {'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'queryTile':tile,'attentionTiles':len(keep),'nodes':len(m.graph.node),'weightsByteIdentical':True,'contextFrames':1301}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('dest',type=Path);p.add_argument('--tile',type=int,required=True);a=p.parse_args()
    print(json.dumps(retile(a.source,a.dest,a.tile)))

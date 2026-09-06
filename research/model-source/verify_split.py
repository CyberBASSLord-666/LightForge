#!/usr/bin/env python3
"""Verify split mesh preserves every triangle's vertex attributes and all embedded textures."""
import json,struct,pathlib,hashlib,collections,numpy as np
r=pathlib.Path(__file__).resolve().parent

def load(p):
 b=p.read_bytes();assert b[:4]==b'glTF';assert struct.unpack_from('<I',b,8)[0]==len(b);n=struct.unpack_from('<I',b,12)[0];return json.loads(b[20:20+n]),b[28+n:]
def arr(g,b,i):
 a=g['accessors'][i];v=g['bufferViews'][a['bufferView']];dt=np.dtype({5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']]);w={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']];return np.ndarray((a['count'],w),dtype=dt,buffer=b,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',w*dt.itemsize),dt.itemsize)).copy()
def fingerprints(g,b):
 result=collections.Counter();count=0
 for m in g['meshes']:
  for p in m['primitives']:
   attrs=np.concatenate([arr(g,b,v)for k,v in sorted(p['attributes'].items())],axis=1);tri=arr(g,b,p['indices']).reshape(-1,3);attrtri=attrs[tri]
   for row in attrtri:result[(p['material'],hashlib.sha256(row.tobytes()).digest())]+=1
   count+=len(tri)
 return result,count
source,sb=load(r/'2024_tesla_model_3.glb');split,pb=load(r/'2024_tesla_model_3_components_v2_raw.glb');a,ac=fingerprints(source,sb);b,bc=fingerprints(split,pb);assert a==b and ac==bc==179692
assert source['materials']==split['materials'] and source['textures']==split['textures']
for si,pi in zip(source['images'],split['images']):
 sv=source['bufferViews'][si['bufferView']];pv=split['bufferViews'][pi['bufferView']];x=sb[sv.get('byteOffset',0):sv.get('byteOffset',0)+sv['byteLength']];y=pb[pv.get('byteOffset',0):pv.get('byteOffset',0)+pv['byteLength']];assert x==y
result={'passed':True,'triangles':ac,'split_meshes':len(split['meshes']),'all_triangle_positions_normals_uvs_other_attributes_bit_exact':True,'triangle_winding_preserved':True,'all_textures_bit_exact':True,'materials_unchanged':True,'original_source_unchanged':hashlib.sha256((r/'2024_tesla_model_3.glb').read_bytes()).hexdigest()=='6ef6933d93ee0812d4049446a38e9b46273cab03b21be1e2ef1d502eccdb684b'}
(r/'split-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

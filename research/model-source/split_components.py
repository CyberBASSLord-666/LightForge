#!/usr/bin/env python3
"""Split only existing disconnected islands; preserve all original triangles/attributes/materials."""
import json,struct,pathlib,numpy as np,copy,hashlib
ROOT=pathlib.Path(__file__).resolve().parent
b=(ROOT/'2024_tesla_model_3.glb').read_bytes();n=struct.unpack_from('<I',b,12)[0];g=json.loads(b[20:20+n]);binary=b[28+n:]
labels=np.load(ROOT/'component-maps.npz');audit=json.loads((ROOT/'component-audit.json').read_text());am={(m['mesh'],c['component']):c for m in audit['meshes'] for c in m['components']}
out=copy.deepcopy(g);out['meshes']=[];out['nodes']=[{'name':'Highland_SourceAxes','matrix':g['nodes'][0]['matrix'],'children':[]}];out['scenes']=[{'nodes':[0]}];out['scene']=0;out['accessors']=[];out['bufferViews']=[];data=bytearray()
out['asset']['extras']['modifications']='Disconnected geometry islands split into independently addressable meshes. Positions, normals, UVs, materials, textures and triangle winding preserved.'

def push(buf,target=None):
 while len(data)%4:data.append(0)
 v={'buffer':0,'byteOffset':len(data),'byteLength':len(buf)}
 if target:v['target']=target
 out['bufferViews'].append(v);data.extend(buf);return len(out['bufferViews'])-1
for image in out.get('images',[]):
 v=g['bufferViews'][image['bufferView']];image['bufferView']=push(binary[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']])
types={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
def get(i):
 a=g['accessors'][i];v=g['bufferViews'][a['bufferView']];dt=np.dtype(types[a['componentType']]);w={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']];off=v.get('byteOffset',0)+a.get('byteOffset',0);stride=v.get('byteStride',dt.itemsize*w)
 return np.ndarray(shape=(a['count'],w),dtype=dt,buffer=binary,offset=off,strides=(stride,dt.itemsize)).copy()
def attr(source,values):
 a={k:v for k,v in g['accessors'][source].items()if k not in ['bufferView','byteOffset','min','max','count']};a['bufferView']=push(values.tobytes(),34962);a['count']=len(values);a['min']=values.min(0).tolist();a['max']=values.max(0).tolist();out['accessors'].append(a);return len(out['accessors'])-1
triangles=0;components=[]
for mi,m in enumerate(g['meshes']):
 for pi,p in enumerate(m['primitives']):
  originaltri=get(p['indices']).reshape(-1,3);tc=labels[f'mesh_{mi}_primitive_{pi}_triangle_components'];attributes={k:get(v)for k,v in p['attributes'].items()}
  unwelded=None
  if mi==9:
   parent=list(range(len(attributes['POSITION'])))
   def find(a):
    while a!=parent[a]:parent[a]=parent[parent[a]];a=parent[a]
    return a
   for a,c,d in originaltri:
    x=find(int(a));parent[find(int(c))]=x;parent[find(int(d))]=x
   unwelded=np.array([find(i)for i in range(len(parent))]);unwelded_tri=unwelded[originaltri[:,0]]
  chunks=[]
  for ci in sorted(np.unique(tc)):
   name=f'mat{p["material"]:02d}_mesh{mi:02d}_component{ci:03d}'
   if mi==9 and ci==21:
    selected=np.zeros(len(originaltri),dtype=bool)
    for seed,suffix,expected in [(8800,'trunk_deck',922),(9564,'trunk_upper',842),(9753,'trunk_lower',441)]:
     mask=unwelded_tri==unwelded[seed];assert np.count_nonzero(mask)==expected and np.all(tc[mask]==21);selected|=mask;chunks.append((ci,name+'_'+suffix,originaltri[mask]))
    chunks.append((ci,name,originaltri[(tc==ci)&~selected]))
   else:chunks.append((ci,name,originaltri[tc==ci]))
  for ci,name,tri in chunks:
   verts=np.unique(tri);remap=np.full(len(attributes['POSITION']),-1,dtype=np.int32);remap[verts]=np.arange(len(verts));newtri=remap[tri].astype('<u2' if len(verts)<=65535 else '<u4');ct=5123 if newtri.dtype.itemsize==2 else 5125;idx={'bufferView':push(newtri.tobytes(),34963),'componentType':ct,'count':int(newtri.size),'type':'SCALAR','min':[int(newtri.min())],'max':[int(newtri.max())]};out['accessors'].append(idx);idxindex=len(out['accessors'])-1
   ap={k:attr(p['attributes'][k],v[verts])for k,v in attributes.items()};q=attributes['POSITION'][verts];scale=4.72/17.5137303;qn=np.column_stack((-(q[:,1]+9.9304299)*scale,(q[:,2]+.000031352)*scale,-(q[:,0]+5.26653516)*scale));extra={'sourceMesh':mi,'sourcePrimitive':pi,'sourceComponent':int(ci),'materialIndex':p['material'],'normalizedBounds':{'min':qn.min(0).tolist(),'max':qn.max(0).tolist(),'center':qn.mean(0).tolist()}}
   out['meshes'].append({'name':name,'primitives':[{'attributes':ap,'indices':idxindex,'material':p['material'],'mode':4}],'extras':extra});out['nodes'].append({'name':name,'mesh':len(out['meshes'])-1,'extras':extra});out['nodes'][0]['children'].append(len(out['nodes'])-1);triangles+=len(tri);components.append({'name':name,**extra,'vertices':len(verts),'triangles':len(tri)})
while len(data)%4:data.append(0)
out['buffers']=[{'byteLength':len(data)}];js=json.dumps(out,separators=(',',':')).encode();js+=b' '*((-len(js))%4);glb=struct.pack('<4sII',b'glTF',2,28+len(js)+len(data))+struct.pack('<I4s',len(js),b'JSON')+js+struct.pack('<I4s',len(data),b'BIN\x00')+data
(ROOT/'2024_tesla_model_3_components_v2_raw.glb').write_bytes(glb);(ROOT/'component-names-v2.json').write_text(json.dumps(components,indent=2));assert triangles==179692
print(json.dumps({'path':str(ROOT/'2024_tesla_model_3_components_v2_raw.glb'),'bytes':len(glb),'sha256':hashlib.sha256(glb).hexdigest(),'meshes':len(out['meshes']),'triangles':triangles,'original_unchanged':hashlib.sha256(b).hexdigest()=='6ef6933d93ee0812d4049446a38e9b46273cab03b21be1e2ef1d502eccdb684b'},indent=2))

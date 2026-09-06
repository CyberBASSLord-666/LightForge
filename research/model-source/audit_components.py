#!/usr/bin/env python3
"""Read-only connectivity audit of source GLB. Welds positions to 1e-5 units."""
import json,struct,pathlib,numpy as np
ROOT=pathlib.Path(__file__).resolve().parent
b=(ROOT/'2024_tesla_model_3.glb').read_bytes();n=struct.unpack_from('<I',b,12)[0];g=json.loads(b[20:20+n]);binary=b[28+n:]
SCALE=4.72/17.5137303

def accessor(i):
 a=g['accessors'][i];v=g['bufferViews'][a['bufferView']];types={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'};dt=np.dtype(types[a['componentType']]);width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']];off=v.get('byteOffset',0)+a.get('byteOffset',0);stride=v.get('byteStride',dt.itemsize*width)
 return np.ndarray(shape=(a['count'],width),dtype=dt,buffer=binary,offset=off,strides=(stride,dt.itemsize)).copy()
def normalized(pos):
 return np.column_stack((-(pos[:,1]+9.9304299)*SCALE,(pos[:,2]+.000031352)*SCALE,-(pos[:,0]+5.26653516)*SCALE))
result={'weld_tolerance_source_units':1e-5,'normalization_scale':SCALE,'meshes':[]};maps={}
for mi,mesh in enumerate(g['meshes']):
 for pi,prim in enumerate(mesh['primitives']):
  pos=accessor(prim['attributes']['POSITION']);tri=accessor(prim['indices']).reshape(-1,3);pn=normalized(pos);parent=list(range(len(pos)));rank=[0]*len(pos)
  def find(x):
   while parent[x]!=x: parent[x]=parent[parent[x]];x=parent[x]
   return x
  def union(a,c):
   a=find(a);c=find(c)
   if a==c:return
   if rank[a]<rank[c]:a,c=c,a
   parent[c]=a
   if rank[a]==rank[c]:rank[a]+=1
  for aa,cc,dd in tri:
   union(int(aa),int(cc));union(int(aa),int(dd))
  seen={}
  for vi,v in enumerate(np.round(pos/1e-5).astype(np.int64)):
   key=tuple(v)
   if key in seen:union(vi,seen[key])
   else:seen[key]=vi
  roots=np.array([find(x) for x in range(len(pos))]);labels={int(v):i for i,v in enumerate(np.unique(roots))};comp=np.array([labels[int(v)]for v in roots],dtype=np.int32);tc=comp[tri[:,0]];components=[]
  for ci in range(len(labels)):
   verts=np.flatnonzero(comp==ci);tis=np.flatnonzero(tc==ci);p=pos[verts];p2=pn[verts]
   components.append({'component':ci,'vertices':len(verts),'triangles':len(tis),'raw_min':p.min(0).tolist(),'raw_max':p.max(0).tolist(),'min':p2.min(0).tolist(),'max':p2.max(0).tolist(),'center':p2.mean(0).tolist()})
  components.sort(key=lambda c:-c['triangles'])
  result['meshes'].append({'mesh':mi,'primitive':pi,'name':mesh.get('name'),'material':prim.get('material'),'material_name':g['materials'][prim['material']].get('name'),'vertices':len(pos),'triangles':len(tri),'components':components})
  maps[f'mesh_{mi}_primitive_{pi}_vertex_components']=comp;maps[f'mesh_{mi}_primitive_{pi}_triangle_components']=tc
(ROOT/'component-audit.json').write_text(json.dumps(result,indent=2));np.savez_compressed(ROOT/'component-maps.npz',**maps)
for m in result['meshes']:
 print('MESH',m['mesh'],m['material_name'],'components',len(m['components']))
 for c in m['components']:
  if c['triangles']<30:continue
  print(' C',c['component'],'tris',c['triangles'],'min',[round(v,3)for v in c['min']],'max',[round(v,3)for v in c['max']])

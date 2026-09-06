#!/usr/bin/env python3
"""Structural and metric regression checks for the bundled Highland GLB."""
import pathlib,struct,json,math,hashlib,sys
p=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'app/lightforge/web/preview/models/highland.glb');b=p.read_bytes();magic,ver,size=struct.unpack_from('<III',b);assert(magic,ver,size)==(0x46546c67,2,len(b));jl,jt=struct.unpack_from('<II',b,12);assert jt==0x4e4f534a;g=json.loads(b[20:20+jl]);o=20+jl;bl,bt=struct.unpack_from('<II',b,o);assert bt==0x004e4942 and o+8+bl==len(b);raw=b[o+8:]
assert not any(x.get('uri') for x in g.get('buffers',[])+g.get('images',[]));assert all('matrix' not in n and 'rotation' not in n and 'scale' not in n for n in g['nodes'])
ids=set();tri=0;names=[];mins=[math.inf]*3;maxs=[-math.inf]*3
for m in g['meshes']:
 names.append(m['name'])
 for q in m['primitives']:
  a=g['accessors'][q['attributes']['POSITION']];v=g['bufferViews'][a['bufferView']];stride=v.get('byteStride',12);start=v.get('byteOffset',0)+a.get('byteOffset',0)
  for i in range(a['count']):
   xyz=struct.unpack_from('<fff',raw,start+i*stride);assert all(math.isfinite(t) for t in xyz)
   for j,t in enumerate(xyz):mins[j]=min(mins[j],t);maxs[j]=max(maxs[j],t)
  ia=g['accessors'][q['indices']];iv=g['bufferViews'][ia['bufferView']];fmt={5121:'B',5123:'H',5125:'I'}[ia['componentType']];step=struct.calcsize(fmt);istart=iv.get('byteOffset',0)+ia.get('byteOffset',0)
  assert ia['count']%3==0;tri+=ia['count']//3
  assert all(struct.unpack_from('<'+fmt,raw,istart+i*step)[0]<a['count'] for i in range(ia['count']))
assert len(names)==len(set(names));assert tri==179692;assert abs(maxs[2]-mins[2]-4.72)<1e-5;assert abs(mins[1])<1e-5;assert abs(mins[0]+maxs[0])<1e-5;assert abs(mins[2]+maxs[2])<1e-5
print(json.dumps({'status':'PASS','sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'meshCount':len(names),'triangles':tri,'bounds':[mins,maxs],'embeddedResources':True,'validIndices':True,'uniqueComponentNames':True,'lengthMeters':maxs[2]-mins[2],'sourceAssetLicense':g['asset']['extras']['license']},indent=2))

#!/usr/bin/env python3
"""Bake the licensed model's axis and metric normalization, preserving textures."""
import sys,json,struct,pathlib,math,hashlib,os
src=pathlib.Path(sys.argv[1]);dst=pathlib.Path(sys.argv[2]);b=src.read_bytes();magic,version,n=struct.unpack_from('<III',b);assert magic==0x46546c67 and version==2 and n==len(b)
jlen,jtype=struct.unpack_from('<II',b,12);g=json.loads(b[20:20+jlen]);off=20+jlen;blen,btype=struct.unpack_from('<II',b,off);blob=bytearray(b[off+8:off+8+blen]);assert btype==0x004e4942
# Input remains raw OBJ Z-up, +X forward, +Y driver side. Ignore exporter wrapper rotation.
position_ids={p['attributes']['POSITION'] for m in g['meshes'] for p in m['primitives']}
mins=[min(g['accessors'][i]['min'][a] for i in position_ids) for a in range(3)];maxs=[max(g['accessors'][i]['max'][a] for i in position_ids) for a in range(3)];cx=(mins[0]+maxs[0])/2;cy=(mins[1]+maxs[1])/2;s=4.72/(maxs[0]-mins[0]);ground=mins[2]
seen=set()
for m in g['meshes']:
 for p in m['primitives']:
  for kind,aid in p['attributes'].items():
   if kind not in ('POSITION','NORMAL','TANGENT') or aid in seen:continue
   seen.add(aid);a=g['accessors'][aid];v=g['bufferViews'][a['bufferView']];assert a['componentType']==5126
   width=4 if kind=='TANGENT' else 3;start=v.get('byteOffset',0)+a.get('byteOffset',0);stride=v.get('byteStride',width*4);pmin=[float('inf')]*width;pmax=[-float('inf')]*width
   for i in range(a['count']):
    pos=start+i*stride;vals=struct.unpack_from('<'+'f'*width,blob,pos);x,y,z=vals[:3]
    out=(-(y-cy)*s,(z-ground)*s,-(x-cx)*s) if kind=='POSITION' else (-y,z,-x)
    if width==4:out=out+(vals[3],)
    struct.pack_into('<'+'f'*width,blob,pos,*out)
    for d,val in enumerate(out):pmin[d]=min(pmin[d],val);pmax[d]=max(pmax[d],val)
   if 'min' in a:a['min']=pmin
   if 'max' in a:a['max']=pmax
for node in g['nodes']:
 for k in ('matrix','translation','rotation','scale'):node.pop(k,None)
g['asset'].setdefault('extras',{})['lightforge_modifications']='Split independent geometric components; baked axes x driver side negative, y up, z front negative; centered and scaled to 4.72m length; embedded source textures and normals retained.'
g['asset']['extras']['lightforge_source_sha256']='6ef6933d93ee0812d4049446a38e9b46273cab03b21be1e2ef1d502eccdb684b'
g['asset']['extras']['lightforge_normalization']={'scale':s,'rawCenterX':cx,'rawCenterY':cy,'rawGround':ground,'lengthMeters':4.72}
j=json.dumps(g,separators=(',',':')).encode();j+=b' ' *((-len(j))%4);blob+=b'\0'*((-len(blob))%4);out=struct.pack('<III',0x46546c67,2,28+len(j)+len(blob))+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(blob),0x004e4942)+blob
dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_suffix('.glb.tmp')
with open(tmp,'wb') as f:f.write(out);f.flush();os.fsync(f.fileno())
os.replace(tmp,dst)
print(json.dumps({'path':str(dst),'bytes':len(out),'sha256':hashlib.sha256(out).hexdigest(),'scale':s,'rawBounds':[mins,maxs],'meshCount':len(g['meshes']),'bounds':[[-(maxs[1]-cy)*s,0,-(maxs[0]-cx)*s],[-(mins[1]-cy)*s,(maxs[2]-ground)*s,-(mins[0]-cx)*s]]},indent=2))

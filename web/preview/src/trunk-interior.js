import * as THREE from 'three';

// The source artist joined the two stationary quarter-panel returns below the
// rear glass to the deck skin. Split that one surface at the cargo seal. Clip
// crossing triangles on both sides so the closed outline and UVs still match.
function splitDeckAtSeal(deck,root){
 const source=deck.geometry,position=source.attributes.position;
 const signedDistance=i=>position.getZ(i)-(1.965-.055*(position.getX(i)/.7)**2);
 const split=[[],[]],corners=[];
 for(let i=0;i<source.index.count;i+=3){
  corners.length=0;
  for(let j=0;j<3;j++){const index=source.index.getX(i+j);corners.push({index,d:signedDistance(index)});}
  for(let half=0;half<2;half++){
   const polygon=[];
   for(let j=0;j<3;j++){
    const a=corners[j],b=corners[(j+1)%3];
    if((a.d>=0)===Boolean(half))polygon.push(a);
    if((a.d>=0)!==(b.d>=0))polygon.push({index:a.index,next:b.index,t:a.d/(a.d-b.d)});
   }
   for(let j=1;j+1<polygon.length;j++)split[half].push(polygon[0],polygon[j],polygon[j+1]);
  }
 }
 const geometryFor=vertices=>{
  const geometry=new THREE.BufferGeometry();
  for(const [name,attribute] of Object.entries(source.attributes)){
   const data=new Float32Array(vertices.length*attribute.itemSize);let offset=0;
   for(const vertex of vertices)for(let j=0;j<attribute.itemSize;j++){
    const a=attribute.getComponent(vertex.index,j);
    data[offset++]=vertex.next===undefined?a:a+(attribute.getComponent(vertex.next,j)-a)*vertex.t;
   }
   geometry.setAttribute(name,new THREE.BufferAttribute(data,attribute.itemSize));
  }
  geometry.normalizeNormals();return geometry;
 };
 const fixed=new THREE.Mesh(geometryFor(split[0]),deck.material);
 fixed.name='Rear_quarter_returns';fixed.castShadow=fixed.receiveShadow=true;root.add(fixed);
 deck.geometry=geometryFor(split[1]);source.dispose();
}
// These four runs in the normalized 9/21 body mesh are the two small
// painted shoulders and the paired narrow horizontal C-lamp edges. The
// neighboring upper gutter and load-opening flanges stay fixed on the body.
function attachDeckEdges(body,deck,root,trunk,attach){
 const geometry=body.geometry,index=geometry.index;
 if(!index||index.count!==10313*3||index.getX(2457*3)!==1645||index.getX(3560*3)!==2779)return;
 const runs=[[2599,2600],[2635,2638],[2680,2760],[3017,3021]],moving=[],fixed=[];
 let run=0;
 for(let i=0;i<index.count;i+=3){
  const face=i/3;
  if(run<runs.length&&face===runs[run][1])run++;
  const target=run<runs.length&&face>=runs[run][0]?moving:fixed;
  target.push(index.getX(i),index.getX(i+1),index.getX(i+2));
 }
 const edgesGeometry=new THREE.BufferGeometry();
 for(const [key,attribute] of Object.entries(geometry.attributes))edgesGeometry.setAttribute(key,attribute);
 edgesGeometry.setIndex(moving);geometry.setIndex(fixed);
 const edges=new THREE.Mesh(edgesGeometry.toNonIndexed(),deck.material);
 edges.name='Trunk_painted_edge_returns';edges.castShadow=edges.receiveShadow=true;
 root.add(edges);attach(edges,trunk);
}
// Close the back of the fixed lamp mounting recesses. These follow the
// imported pocket perimeter and are only visible behind the lifted C lamps.
function fitRearLampPockets(root){
 const edge=[[.515,.750,2.146],[.625,.749,2.136],[.734,.754,2.079],
  [.771,.787,2.035],[.765,.863,2.023],[.733,.927,2.007],
  [.673,.955,2.017],[.592,.965,2.036],[.510,.932,2.080]];

 const vertices=[],indices=[];
 for(const side of [-1,1]){
  const start=vertices.length/3;
  for(const [x,y,z] of edge)vertices.push(side*x,y,z);
  for(const [x,y,z] of edge)vertices.push(side*(.640+(x-.640)*.65),.847+(y-.847)*.64,z-.012);
  vertices.push(side*.640,.847,2.082);
  for(let i=0;i<edge.length;i++){
   const j=(i+1)%edge.length,inner=start+edge.length,center=inner+edge.length;
   indices.push(start+i,start+j,inner+j,start+i,inner+j,inner+i,inner+i,inner+j,center);
  }
 }
 const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
 geometry.setIndex(indices);geometry.computeVertexNormals();
 const pockets=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0x24282c,roughness:.85,side:THREE.DoubleSide}));
 pockets.name='Rear_body_lamp_recesses';pockets.receiveShadow=true;root.add(pockets);
}
// The upper gutter bridges the fixed rear-glass surround and the original
// cargo seal, continuing into the two lamp pockets. Its stepped cross section
// prevents an open view through the underside of the exterior sheet metal.
function fitTrunkGutter(root){
 const rows=[
  [[0,1.083,1.968],[0,1.060,1.992],[0,1.043,2.024]],
  [[.25,1.068,1.941],[.25,1.050,1.969],[.25,1.036,2.012]],
  [[.43,1.046,1.907],[.43,1.023,1.941],[.43,1.006,1.975]],
  [[.51,1.021,1.891],[.51,.996,1.935],[.51,.958,2.034]],
  [[.60,1.004,1.890],[.60,.978,1.943],[.60,.936,2.045]],
  [[.67,.976,1.907],[.67,.953,1.953],[.67,.917,2.035]],
  [[.71,.946,1.927],[.71,.932,1.962],[.71,.906,2.018]]
 ];
 const mirrored=rows.slice(1).reverse().map(row=>row.map(([x,y,z])=>[-x,y,z]));
 const positions=[...mirrored,...rows].flat(2),indices=[];
 for(let i=0;i<positions.length/3-3;i++){
  if(i%3!==2)indices.push(i,i+1,i+3,i+1,i+4,i+3);
 }
 const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
 geometry.setIndex(indices);geometry.computeVertexNormals();
 const gutter=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0x17191c,roughness:.65,side:THREE.DoubleSide}));
 gutter.name='Rear_trunk_gutter';gutter.receiveShadow=true;root.add(gutter);
}
// UVs on the imported carpet panels have independent origins. A small,
// repeating, mipmapped textile tile keeps them uniformly matte at orbit scale.
export function cargoTextile(){
 const size=64,rgba=new Uint8Array(size*size*4);let seed=17;
 for(let i=0;i<rgba.length;i+=4){
  seed=(Math.imul(seed,1664525)+1013904223)>>>0;
  const fiber=166+(seed>>>25)*.7;
  rgba[i]=rgba[i+1]=rgba[i+2]=fiber;rgba[i+3]=255;
 }
 const texture=new THREE.DataTexture(rgba,size,size);
 texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.repeat.set(5,5);
 texture.magFilter=THREE.LinearFilter;texture.minFilter=THREE.LinearMipmapLinearFilter;
 texture.generateMipmaps=true;texture.needsUpdate=true;return texture;
}
// The imported asset includes the load floor, wheelhouse liners, seatbacks and
// sill, but supplies only exterior sheet metal for the three decklid pieces.
// This molded trim follows their inner contour up to the swept rear window edge.
function fitTrunkLidTrim(root,trunk,attach,textile){
 const sections=[
  // Half width, center height/depth, outer-edge height/depth in the closed model.
  [.560,1.044,1.950,1.008,1.942],
  [.644,1.029,2.045,.962,1.956],
  [.693,.993,2.146,.919,1.987],
  [.716,.962,2.190,.890,2.007],
  [.712,.924,2.204,.859,2.020],
  [.686,.871,2.192,.818,2.037],
  [.610,.812,2.175,.788,2.075],
  [.550,.725,2.194,.727,2.123],
  [.497,.660,2.226,.665,2.163],
  [.460,.638,2.251,.649,2.192]
 ];
 const positions=[],indices=[],uv=[],columns=31;
 for(const [width,centerY,centerZ,edgeY,edgeZ] of sections){
  for(let column=0;column<columns;column++){
   const x=2*column/(columns-1)-1,curve=x*x;
   // Molded edge flanges curl away from the luggage compartment.
   const flange=Math.max(0,(Math.abs(x)-.88)/.12);
   const y=centerY+(edgeY-centerY)*curve+.008*flange,z=centerZ+(edgeZ-centerZ)*curve+.008*flange;
   positions.push(width*x,y,z);uv.push(width*x,z-y);
  }
 }
 for(let row=0;row<sections.length-1;row++)for(let column=0;column<columns-1;column++){
  const i=row*columns+column;indices.push(i,i+1,i+columns,i+1,i+columns+1,i+columns);
 }
 const geometry=new THREE.BufferGeometry();
 geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
 geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
 geometry.setIndex(indices);geometry.computeVertexNormals();
 const liner=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({name:'Trunk_lid_trim',color:0x484647,roughness:.96,map:textile}));
 liner.material.addEventListener('dispose',()=>textile.dispose());
 liner.name='Trunk_lid_trim';liner.receiveShadow=true;root.add(liner);attach(liner,trunk);

 // The latch cover and close switch sit on the underside of the closing lip.
 const hardware=new THREE.MeshStandardMaterial({color:0x17191a,roughness:.76});
 for(const [name,x,width,height] of [['Trunk_latch_cover',0,.086,.049],['Trunk_close_switch',.27,.046,.025]]){
  const pad=new THREE.Shape(),r=.006,w=width/2,h=height/2;
  pad.moveTo(-w+r,-h);pad.lineTo(w-r,-h);pad.quadraticCurveTo(w,-h,w,-h+r);
  pad.lineTo(w,h-r);pad.quadraticCurveTo(w,h,w-r,h);pad.lineTo(-w+r,h);
  pad.quadraticCurveTo(-w,h,-w,h-r);pad.lineTo(-w,-h+r);pad.quadraticCurveTo(-w,-h,-w+r,-h);
  const mesh=new THREE.Mesh(new THREE.ExtrudeGeometry(pad,{depth:.005,bevelEnabled:false,curveSegments:4}),hardware);
  mesh.name=name;mesh.rotation.y=Math.PI;mesh.position.set(x,.688,2.202-.060*(x/.5)**2);
  root.add(mesh);attach(mesh,trunk);
 }
 // Paired hinge arms share the decklid pivot. A point on the rotation axis
 // stays fixed against the body while the curved end stays attached to the lid.
 const hingeMaterial=new THREE.MeshStandardMaterial({color:0x30353b,metalness:.40,roughness:.44});
 for(const side of [-1,1]){
  const curve=new THREE.CatmullRomCurve3([
   [side*.555,trunk.position.y,trunk.position.z],[side*.55,.984,1.596],
   [side*.54,.909,1.714],[side*.51,.930,1.859],[side*.505,.989,2.041]
  ].map(point=>new THREE.Vector3(...point)));
  const arm=new THREE.Mesh(new THREE.TubeGeometry(curve,18,.015,8,false),hingeMaterial);
  arm.name=side<0?'Trunk_hinge_L':'Trunk_hinge_R';arm.castShadow=true;root.add(arm);attach(arm,trunk);
 }
}

export function fitTrunkInterior(root,trunk,attach,deck,body,textile){
 if(deck){
  splitDeckAtSeal(deck,root);
  if(body)attachDeckEdges(body,deck,root,trunk,attach);
 }
 fitRearLampPockets(root);
 fitTrunkGutter(root);
 fitTrunkLidTrim(root,trunk,attach,textile);
}

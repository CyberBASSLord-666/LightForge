import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {cargoTextile,fitTrunkInterior} from './trunk-interior.js';
// RBLXSupercars / Brandon Leong, CC BY 4.0. Geometry adaptation is documented
// in models/CREDITS.md. All closures use deterministic ShowEngine estimates.
const zeroRGB=[0,0,0];
const windowBindings=[['windowFL',37],['windowRL',38],['windowFR',39],['windowRR',40]];
const clamp=v=>Math.max(0,Math.min(1,Number(v)||0));
const V=p=>new THREE.Vector3(...p);
export function buildHighlandRig(source){
 const textile=cargoTextile();
 const root=new THREE.Group();root.name='Highland_Model_3';root.add(source);root.updateMatrixWorld(true);
 const nodes=[],parts={},lamps=[],drivers=[],materials=new Map(),cutaway=[],brakeEmitters=[];
 source.traverse(o=>{if(o.isMesh){nodes.push(o);}});
 const node=(mesh,c)=>nodes.find(o=>o.userData.sourceMesh===mesh&&o.userData.sourceComponent===c&&!o.name.includes('_trunk_'));
 const group=(key,pivot)=>{const g=new THREE.Group();g.name=key;g.position.copy(V(pivot));root.add(g);parts[key]=g;return g;};
 const trunk=group('trunk',[0,1.135,1.55]),charge=group('charge',[-.788,.86,1.814]);
 const chargeHingeAxis=new THREE.Vector3(-.94,-.34,0).normalize();
 for(const [k,p] of Object.entries({mirrorL:[-.86,.947,-.73],mirrorR:[.86,.947,-.73],windowFL:[0,0,0],windowRL:[0,0,0],windowFR:[0,0,0],windowRR:[0,0,0]}))group(k,p);
 root.updateMatrixWorld(true);
 const attach=(o,g)=>{if(o){g.attach(o);o.userData.rigPart=g.name;}};
 for(const o of nodes){const m=o.userData.sourceMesh,c=o.userData.sourceComponent;let type='base';if(m===16&&c>=4)type='seat';
  if(o.name.includes('_trunk_'))type='lid';
  // Preserve the original asymmetric floor, side bins, loading lip and split seatback geometry.
  if(m===12&&[5,29,39,43,137,140].includes(c))type='cargo';
  if(m===12&&[4,73,74].includes(c))type='lampPocket';
  const old=o.material,key=old.name+type;let material=materials.get(key);
  if(!material){material=old.clone();material.emissive?.set(0);material.emissiveIntensity=0;material.envMapIntensity=.7;material.side=THREE.FrontSide;
   if(m===9)material=new THREE.MeshPhysicalMaterial({name:old.name,color:0x06080b,metalness:.14,roughness:.23,clearcoat:1,clearcoatRoughness:.19,envMapIntensity:.70});
   if(m===11||m===12){material.color.set(0x111318);material.roughness=.5;material.metalness=.16;}
   if(m===13){material.color.set(0x434a53);material.roughness=.29;material.metalness=.78;}
   if(m===10){material.roughness=.26;material.metalness=.8;}
   if(m===17){material.roughness=.91;material.metalness=0;}
   if(type==='lid')material.side=THREE.DoubleSide;
   if(type==='lampPocket'){material.color.set(0x28292a);material.roughness=.88;material.metalness=0;material.side=THREE.DoubleSide;}
   if(type==='cargo'){material.map=textile;material.name='Cargo_carpet';material.color.set(0x383739);material.roughness=.98;material.metalness=0;material.vertexColors=true;material.envMapIntensity=.25;}
   if(type==='seat'){material.color.set(0x252930);material.roughness=.7;material.metalness=0;}
   if(old.transparent){material.color.set(0x101a24);material.opacity=.62;material.depthWrite=false;material.roughness=.11;material.metalness=.25;material.side=THREE.DoubleSide;}
   if(m===16&&c<4){material.color.set(0x414950);material.roughness=.22;}
   if(m===0||m===1){material.emissiveMap=null;material.color.set(0x0b0d10);}
   materials.set(key,material);
  }
  if(type==='cargo'){
   // A dark textile contact gradient around the wheelhouses, seatback and
   // load-floor edges keeps their shapes readable under the mobile light rig.
   const p=o.geometry.attributes.position,colors=new Float32Array(p.count*3);
   for(let i=0;i<p.count;i++){
    const x=Math.abs(p.getX(i)),y=p.getY(i),z=p.getZ(i);
    const side=clamp((x-.30)/.20),front=clamp((1.55-z)/.32),lip=clamp((z-2.07)/.16);
    const sideWall=clamp((y-.54)/.27);
    const v=.99-.24*side-.19*front-.11*lip-.12*sideWall;
    colors[i*3]=colors[i*3+1]=colors[i*3+2]=v;
   }
   o.geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
  }
  o.material=material;o.castShadow=!old.transparent;o.receiveShadow=true;
  if(m===5&&(c===0||c===1))attach(o,parts[c===1?'windowFL':'windowRL']);
  if(m===7&&(c===0||c===1))attach(o,parts[c===1?'windowFR':'windowRR']);
  if((m===9&&c===11)||(m===11&&c===269)||(m===10&&c===2))attach(o,parts.mirrorL);
  if((m===9&&c===15)||(m===11&&c===226)||(m===10&&c===3))attach(o,parts.mirrorR);
  if(o.name.includes('_trunk_'))attach(o,trunk);
  // Mesh 12 includes the body-side lamp mounting pockets behind the moving C lamps.
  const b=o.userData.normalizedBounds;
  if(b&&b.min[2]>1.90&&b.min[1]>.60&&b.max[1]<1.09&&m!==9&&m!==8&&m!==12)attach(o,trunk);
  // The rear driver-side port cover is separate from the lid-mounted rear lamp.
  if((m===4&&[17,19,22].includes(c))||(m===14&&c===5))attach(o,charge);
  if(m===8&&(c===0||c===1))cutaway.push(o);
  if(m===4&&c===32)cutaway.push(o);
 }
 const cloneLamp=(o)=>{if(!o)return null;if(!o.userData.lamp){o.material=o.material.clone();o.material.emissiveMap=null;o.userData.lamp=true;o.castShadow=false;}return o;};
 const addLamp=(ids,objects,value,tint=0xe7f5ff,normal=[0,0,-1],estimatedMapping=false,peakIntensity=7)=>{
  objects=objects.filter(Boolean).map(cloneLamp);if(!objects.length)return;
  ids=Array.isArray(ids)?ids:[ids];
  const records=ids.map(id=>({id,channels:ids.filter(Number.isInteger),object:objects[0],objects,value:0,physicalValue:0,normal:V(normal),estimatedMapping}));lamps.push(...records);
  let lastLevel=NaN,lastR=NaN,lastG=NaN,lastB=NaN;const color=new THREE.Color();
  drivers.push(data=>{const level=clamp(value(data));color.set(typeof tint==='function'?tint(data):tint);
   for(const record of records){record.physicalValue=level;record.value=typeof record.id==='number'?clamp(data?.lights?.[record.id-1]):level;}
   if(level!==lastLevel||color.r!==lastR||color.g!==lastG||color.b!==lastB){for(const o of objects){o.material.emissive.copy(color);o.material.emissiveIntensity=level*peakIntensity;}lastLevel=level;lastR=color.r;lastG=color.g;lastB=color.b;}
  });return records[0];
 };
 // Keep the model's inner optical cavities in place. Only their forward-facing
 // facets emit light; the black housing, roof and chrome surrounds never glow.
 const reflectorEmitter=(original,name,select=(center,n)=>n.z<-.70&&Math.abs(n.y)<.40)=>{
  if(!original)return null;const raw=original.geometry.index?original.geometry.toNonIndexed():original.geometry.clone();
  const a=raw.attributes.position,keep=[],p0=new THREE.Vector3(),p1=new THREE.Vector3(),p2=new THREE.Vector3(),n=new THREE.Vector3(),center=new THREE.Vector3();
  for(let i=0;i<a.count;i+=3){p0.fromBufferAttribute(a,i);p1.fromBufferAttribute(a,i+1);p2.fromBufferAttribute(a,i+2);center.copy(p0).add(p1).add(p2).multiplyScalar(1/3);n.crossVectors(p1.sub(p0),p2.sub(p0)).normalize();if(select(center,n))keep.push(i,i+1,i+2);}
  if(!keep.length){raw.dispose();return null;}
  const geometry=new THREE.BufferGeometry();for(const [key,attribute] of Object.entries(raw.attributes)){const array=new attribute.array.constructor(keep.length*attribute.itemSize);keep.forEach((index,j)=>{for(let k=0;k<attribute.itemSize;k++)array[j*attribute.itemSize+k]=attribute.array[index*attribute.itemSize+k];});geometry.setAttribute(key,new THREE.BufferAttribute(array,attribute.itemSize,attribute.normalized));}raw.dispose();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({name,color:0x2e363e,metalness:.35,roughness:.3,emissive:0,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1}));mesh.name=name;original.parent.add(mesh);mesh.position.copy(original.position);mesh.quaternion.copy(original.quaternion);mesh.scale.copy(original.scale);return mesh;
 };
 const reverseOptics=[],fasciaTailOptics=[];
 // The OE assembly has a red reflector above the active clear strip. Fit the
 // three emitters to existing rear-facing lens facets along the molded strip.
 // Sector boundaries follow this model; they are not OEM lens measurements.
 const fasciaSector=(lenses,role,side,inner,outer)=>lenses.map(lens=>{
  const name='Rear_fascia_'+side+'_'+role+'_'+lens.userData.sourceComponent;
  const mesh=reflectorEmitter(lens,name,(center,normal)=>{
   const span=Math.abs(center.x);
   return normal.z>.70&&span>=inner&&span<outer;
  });
  if(mesh){
   mesh.userData.sourceMesh=lens.userData.sourceMesh;
   mesh.userData.sourceComponent=lens.userData.sourceComponent;
  }
  return mesh;
 }).filter(Boolean);
 const light=(data,ch)=>clamp(data?.lights?.[ch-1]);
 const usesFasciaTails=()=>positions[41]>0;
 const sharedFasciaTail=d=>usesFasciaTails()?Math.max(light(d,26),light(d,27)):0;

 const tube=(name,points,radius=.008,parent=root)=>{const path=new THREE.CatmullRomCurve3(points.map(V));const o=new THREE.Mesh(new THREE.TubeGeometry(path,Math.max(8,points.length*8),radius,6,false),new THREE.MeshStandardMaterial({name,color:0x11161c,metalness:.08,roughness:.3,emissive:0}));o.name=name;parent.add(o);return o;};
 for(const side of [-1,1]){const left=side<0;
  // The old rig mistook the chrome projector surround for the outer beam. The
  // outer beam now uses the actual optical face. Highland's exact FSEQ sector
  // allocation is not published (teslamotors/light-show issue 113); the inner
  // beam/4-6 groups share the real inner reflector assembly in this preview.
  addLamp(left?1:2,[node(16,left?3:1),node(10,left?20:22)],d=>light(d,left?1:2),0xe7f5ff,[0,0,-1],true);
  const inner=reflectorEmitter(node(11,left?222:194),'Inner_optics_'+(left?'L':'R'));
  const innerChannels=left?[3,7,9,11]:[4,8,10,12];
  addLamp(innerChannels,[inner],d=>Math.max(light(d,innerChannels[0]),light(d,innerChannels[1]),light(d,innerChannels[2]),light(d,innerChannels[3])),0xe7f5ff,[0,0,-1],true);
  // Use the actual J-shaped signature diffuser, without a duplicate tube.
  addLamp(left?5:6,left?[node(10,8),node(10,11)]:[node(10,7),node(10,29)],d=>light(d,left?5:6),0xe7f5ff,[0,0,-1],true);
  // Estimated front-turn allocation uses the lower diffuser. It stays amber
  // and does not respond to the unrelated combined headlight 4-6 requests.
  addLamp(left?13:14,[node(15,left?0:3),node(10,left?10:23)],d=>light(d,left?13:14),0xff9214,[0,0,-1],true);
  // No lower front-fog/aux-park assembly is installed on Highland. Its North
  // American side-marker lens sits at the outer headlamp corner. This small
  // lens adaptation is fitted inside that existing housing, not on the fender.
  const sidePark=reflectorEmitter(node(7,left?4:3),'Headlamp_side_marker_'+side,(center,n)=>Math.abs(center.x)>.81&&center.z>-1.9&&n.x*side>.1);
  addLamp(left?[17,19]:[18,20],[sidePark],d=>Math.max(light(d,17),light(d,18),light(d,19),light(d,20)),0xffa328,[side,0,0],true);
  const repeat=node(15,left?1:4);addLamp(left?21:22,[repeat,node(10,left?13:14)],d=>light(d,left?21:22),0xff9318,[side,0,0]);
  // The C-shaped rear lamp geometry is on the trunk. The separate side-facing
  // charge-cover/quarter-panel lens is excluded from brake and tail requests.
  const tailNodes=nodes.filter(o=>o.userData.sourceMesh===14&&[0,1,2,3,6,7,8].includes(o.userData.sourceComponent)&&(o.userData.normalizedBounds.center[0]<0)===left);
  brakeEmitters.push(...tailNodes);
  const tailChannel=left?26:27,turnChannel=left?23:24;
  addLamp(tailChannel,tailNodes,d=>Math.max(usesFasciaTails()?0:light(d,tailChannel),light(d,25)),0xff0205,[0,0,1],true);
  addLamp(turnChannel,[node(15,left?2:5)],d=>usesFasciaTails()?0:light(d,turnChannel),0xff9116,[0,0,1],true);

  // Road-mode Highland observations show auxiliary tail/turn operation with
  // the trunk open. Use estimated lid position for the preview handoff;
  // the shared lower tail and independent turns reuse existing FSEQ commands.
  const sideName=left?'left':'right';
  const lenses=left?[node(10,5),node(10,6)]:[node(10,4)];
  const red=fasciaSector(lenses,'tail',sideName,.514,Infinity);
  const amber=fasciaSector(lenses,'turn',sideName,.45,.514);
  const white=fasciaSector(lenses,'reverse',sideName,.389,.45);
  const lowerTail=addLamp('fascia-tail-'+sideName,red,sharedFasciaTail,0xff0205,[0,0,1],true);
  lowerTail.channels=[26,27];
  const lowerTurn=addLamp('fascia-turn-'+sideName,amber,d=>usesFasciaTails()?light(d,turnChannel):0,0xff9116,[0,0,1],true);
  lowerTurn.channels=[turnChannel];
  reverseOptics.push(white);
  fasciaTailOptics.push(red);
 }
 addLamp(28,reverseOptics.flat(),d=>light(d,28),0xe8f4ff,[0,0,1],true);
 const brake=addLamp(25,[node(10,9),node(10,12)],d=>light(d,25),0xff0103,[0,0,1],true);
 // Report every physical surface responding to the brake channel. Tail drivers
 // above combine stop/tail values without a later driver overwriting them.
 if(brake)brake.objects=brake.objects.concat(brakeEmitters);
 // The innermost clear sector and the upper reflector never emit for the
 // unavailable North American rear-fog show channel.
 // The plate and plate lights move with the powered trunk.
 const plate=new THREE.Mesh(new THREE.PlaneGeometry(.38,.115),new THREE.MeshStandardMaterial({color:0x78828a,metalness:0,roughness:.55}));plate.name='Rear_plate';plate.position.set(0,.715,2.302);root.add(plate);attach(plate,trunk);
 const plateLamps=[-1,1].map(side=>{const lamp=new THREE.Mesh(new THREE.BoxGeometry(.043,.008,.021),new THREE.MeshStandardMaterial({color:0x697077,emissive:0,roughness:.3}));lamp.name='License_plate_lamp_'+(side<0?'L':'R');lamp.position.set(side*.115,.788,2.302);root.add(lamp);attach(lamp,trunk);return lamp;});
 addLamp(30,plateLamps,d=>light(d,30),0xf1f4e5,[0,-.8,.2]);
 const plateSpill=new THREE.PointLight(0xfff3da,0,.65,2);plateSpill.position.set(0,.79,2.40);root.add(plateSpill);attach(plateSpill,trunk);drivers.push(d=>plateSpill.intensity=light(d,30)*.11);
 // Real interior ambient trim surfaces from the imported cabin and front display.
 // The official RGB interface exposes the center FRONT display only. The rear
 // passenger screen remains a normal screen, not a seventh RGB output.
 const rgbBindings=[[node(1,0)],[node(3,1)],[node(6,1)],[node(6,2)],[node(6,0)],[node(3,0)]];
 for(let i=0;i<6;i++){const objects=rgbBindings[i].filter(Boolean),tint=new THREE.Color();addLamp('rgb-'+i,objects,d=>{const rgb=d?.interior?.[i]||zeroRGB;return Math.max(rgb[0],rgb[1],rgb[2])/255;},d=>{const rgb=d?.interior?.[i]||zeroRGB,peak=Math.max(rgb[0],rgb[1],rgb[2],1);return tint.setRGB(rgb[0]/peak,rgb[1]/peak,rgb[2]/peak,THREE.SRGBColorSpace);},[0,1,0],false,i===0?7:3);}
 // The port status light is the Tesla T-shaped indicator, not a glowing ring.
 const logoCap=new THREE.Shape();logoCap.moveTo(-.037,.026);logoCap.quadraticCurveTo(0,.043,.037,.026);logoCap.lineTo(.035,.020);logoCap.quadraticCurveTo(0,.034,-.035,.020);logoCap.closePath();
 const logoStem=new THREE.Shape();logoStem.moveTo(-.029,.017);logoStem.quadraticCurveTo(0,.029,.029,.017);logoStem.lineTo(.008,.009);logoStem.lineTo(.003,-.032);logoStem.lineTo(-.003,-.032);logoStem.lineTo(-.008,.009);logoStem.closePath();
 const chargeLED=new THREE.Mesh(new THREE.ShapeGeometry([logoCap,logoStem],16),new THREE.MeshStandardMaterial({color:0x18202a,emissive:0,roughness:.3,side:THREE.DoubleSide}));chargeLED.name='Charge_status_T';chargeLED.rotation.y=-Math.PI/2;chargeLED.position.set(-.797,.889,1.895);chargeLED.scale.setScalar(.48);root.add(chargeLED);
 const chargeTint=new THREE.Color();
 // The unplugged port shows a white/light-blue T while open. The existing
 // Dance command temporarily replaces that status with the decoded rainbow.
 addLamp('charge-led',[chargeLED],()=>positions[46]>.04?1:0,d=>{
  const closure=d?.closures?.find(c=>c.channel===46);
  if(!closure?.rainbow)return 0xe6f3ff;
  const rgb=closure.rainbowColor;
  return chargeTint.setRGB(rgb[0]/255,rgb[1]/255,rgb[2]/255,THREE.SRGBColorSpace);
 },[-1,0,0]);
 // The inlet stays in the fender behind the rising cover, beside the T.
 const inletOutline=new THREE.Shape();
 inletOutline.moveTo(-.030,.007);
 inletOutline.quadraticCurveTo(-.030,.022,-.012,.022);
 inletOutline.lineTo(.012,.022);inletOutline.quadraticCurveTo(.030,.022,.030,.007);
 inletOutline.quadraticCurveTo(.030,-.020,0,-.031);
 inletOutline.quadraticCurveTo(-.030,-.020,-.030,.007);
 const socket=new THREE.Mesh(new THREE.ShapeGeometry(inletOutline),new THREE.MeshStandardMaterial({color:0x07090b,roughness:.82}));
 socket.name='Charge_inlet';socket.rotation.y=-Math.PI/2;socket.position.set(-.793,.878,1.976);root.add(socket);
 // Two larger upper contacts, two small pilot contacts and a lower center
 // contact match the visible NACS inlet face in the US manual illustration.
 for(const [x,y,r] of [[-.013,.008,.008],[.013,.008,.008],[-.013,-.009,.003],[.013,-.009,.003],[0,-.018,.005]]){
  const bore=new THREE.Path();bore.absarc(x,y,r,0,2*Math.PI,true);inletOutline.holes.push(bore);
 }
 const bezel=new THREE.Mesh(new THREE.ShapeGeometry(inletOutline),new THREE.MeshStandardMaterial({color:0x34383e,roughness:.59,metalness:.12}));
 bezel.name='NACS_inlet_face';bezel.position.z=.001;socket.add(bezel);
 fitTrunkInterior(root,trunk,attach,nodes.find(o=>o.name.endsWith('_trunk_deck')),node(9,21),textile);
 // Merge static geometry after assigning motion and emissive groups. Keeps the
 // detailed mesh at mobile-friendly draw counts rather than 684 draw calls.
 root.updateMatrixWorld(true);const buckets=new Map();
 for(const o of nodes){if(o.userData.lamp||cutaway.includes(o)||o.userData.rigPart)continue;
  const k=o.material.uuid;if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(o);
 }
 for(const list of buckets.values()){if(list.length<2)continue;const geometries=list.map(o=>o.geometry.clone().applyMatrix4(o.matrixWorld));const merged=mergeGeometries(geometries,false);geometries.forEach(g=>g.dispose());if(!merged)continue;const mesh=new THREE.Mesh(merged,list[0].material);mesh.name='Static_'+list[0].material.name;mesh.castShadow=list[0].castShadow;mesh.receiveShadow=true;root.add(mesh);list.forEach(o=>o.removeFromParent());}
 root.updateMatrixWorld(true);const fitPoints=[];
 root.traverse(o=>{if(!o.isMesh)return;const a=o.geometry.attributes.position,step=Math.max(1,Math.ceil(a.count/240));for(let i=0;i<a.count;i+=step){const p=new THREE.Vector3().fromBufferAttribute(a,i).applyMatrix4(o.matrixWorld);fitPoints.push(p);if(o.userData.rigPart==='trunk')for(const angle of [.75,1.55])fitPoints.push(p.clone().sub(trunk.position).applyAxisAngle(new THREE.Vector3(1,0,0),-angle).add(trunk.position));}});
 // Environmental spill originates at the same physical optic surfaces as the
 // visible emitters. Fascia reverse lamps stay body-fixed when the lid opens.
 const opticCenter=objects=>{const bounds=new THREE.Box3();for(const o of objects)bounds.expandByObject(o);return bounds.getCenter(new THREE.Vector3());};
 const lightingAnchors={tail:[26,27].map(id=>opticCenter(lamps.find(l=>l.id===id)?.objects||[])),headlights:[1,2].map(id=>opticCenter(lamps.find(l=>l.id===id)?.objects||[])),reverse:reverseOptics.map(opticCenter),fasciaTail:fasciaTailOptics.map(opticCenter)};
 const positions=new Float64Array(47),lastPositions=new Float64Array(47);lastPositions.fill(NaN);
 const usedClosures=[35,36,37,38,39,40,41,46];
 return {root,lamps,parts,chargeLED,fitPoints,lightingAnchors,usesFasciaTails,
  update(data){
   positions.fill(0);positions[35]=positions[36]=1;
   for(const c of data?.closures||[]){if(c.channel>=0&&c.channel<positions.length)positions[c.channel]=clamp(c.openFraction??c.estimatedPosition??positions[c.channel]);}
   let moved=false;for(const ch of usedClosures){if(positions[ch]!==lastPositions[ch]){moved=true;lastPositions[ch]=positions[ch];}}
   if(moved){for(const [key,ch] of windowBindings)parts[key].position.y=-positions[ch]*.53;
    parts.mirrorL.rotation.y=(1-positions[35])*1.32;parts.mirrorR.rotation.y=-(1-positions[36])*1.32;
    trunk.rotation.x=-positions[41]*1.55;charge.quaternion.setFromAxisAngle(chargeHingeAxis,positions[46]*1.65);socket.visible=chargeLED.visible=positions[46]>.04;
   }
   for(const apply of drivers)apply(data);return moved;
  },
  setCutaway(value){for(const o of cutaway)o.visible=!value;}
 };
}

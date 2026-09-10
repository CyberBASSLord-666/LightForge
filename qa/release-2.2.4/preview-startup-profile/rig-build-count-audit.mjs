import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
// Usage: node rig-build-count-audit.mjs [output-directory]
// Optional: LF_GRAPHICS_NODE_MODULES=/path/to/node_modules
// A fresh temporary directory is used by default; existing results are never overwritten.
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const graphicsModules=path.resolve(process.env.LF_GRAPHICS_NODE_MODULES||path.join(repo,'../toolchain/graphics/node_modules'));
const threeURL=pathToFileURL(path.join(graphicsModules,'three/build/three.module.js')).href;
const loaderURL=pathToFileURL(path.join(graphicsModules,'three/examples/jsm/loaders/GLTFLoader.js')).href;
const utilsURL=pathToFileURL(path.join(graphicsModules,'three/examples/jsm/utils/BufferGeometryUtils.js')).href;
const THREE=await import(threeURL);
const {GLTFLoader}=await import(loaderURL);
const outputDirectory=process.argv[2]?path.resolve(process.argv[2]):fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-rig-build-count-'));
fs.mkdirSync(outputDirectory,{recursive:true});
const outputPath=path.join(outputDirectory,'rig-build-count-audit.json');
if(fs.existsSync(outputPath))throw new Error('Refusing to overwrite existing audit: '+outputPath);
const bytes=fs.readFileSync(repo+'/web/preview/models/highland.glb');
const loader=new GLTFLoader().register(()=>({name:'CPU_audit_texture_stub',loadTexture(){return Promise.resolve(new THREE.Texture());}}));
const parseStart=performance.now();
const gltf=await loader.parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.length),'');
const parseMs=performance.now()-parseStart;
const counters={},nonIndexed=[],applied=[],merges=[];
const samples={sourceMeshes:0,positionVertices:0,indexEntries:0,initialBounds:0,initialSpheres:0,nonIdentityLocalMatrices:0};
gltf.scene.traverse(o=>{if(o.isMesh){samples.sourceMeshes++;samples.positionVertices+=o.geometry.attributes.position.count;samples.indexEntries+=o.geometry.index?.count||0;samples.initialBounds+=!!o.geometry.boundingBox;samples.initialSpheres+=!!o.geometry.boundingSphere;samples.nonIdentityLocalMatrices+=!o.matrix.equals(new THREE.Matrix4());}});
for(const [proto,names] of [[THREE.BufferGeometry.prototype,['clone','applyMatrix4','toNonIndexed','computeBoundingBox','computeBoundingSphere','computeVertexNormals','dispose']],[THREE.Object3D.prototype,['updateMatrixWorld','updateWorldMatrix','traverse','attach']],[THREE.Material.prototype,['clone']]])for(const name of names){const fn=proto[name];const key=(proto===THREE.BufferGeometry.prototype?'geometry.':proto===THREE.Object3D.prototype?'object.':'material.')+name;proto[name]=function(...args){counters[key]=(counters[key]||0)+1;if(key==='geometry.toNonIndexed')nonIndexed.push({vertices:this.attributes.position.count,indexEntries:this.index.count,attributes:Object.keys(this.attributes),attributeBytes:Object.values(this.attributes).reduce((s,a)=>s+a.array.byteLength,0),expandedAttributeBytes:Object.values(this.attributes).reduce((s,a)=>s+this.index.count*a.itemSize*a.array.BYTES_PER_ELEMENT,0)});if(key==='geometry.applyMatrix4')applied.push({vertices:this.attributes.position.count,indexEntries:this.index?.count||0,identity:args[0].equals(new THREE.Matrix4()),attributes:Object.keys(this.attributes)});return fn.apply(this,args);};}
globalThis.__rigAuditMerges=merges;
let source=fs.readFileSync(repo+'/web/preview/src/highland-rig.js','utf8');
if(!source.includes("from 'three'")||!source.includes("import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';"))throw new Error('Rig imports changed; review the audit instrumentation before running.');
source=source.replace("from 'three'",'from '+JSON.stringify(threeURL)).replace("import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';",'import {mergeGeometries as realMerge} from '+JSON.stringify(utilsURL)+'; const mergeGeometries=(gs,groups)=>{globalThis.__rigAuditMerges.push({count:gs.length,vertices:gs.reduce((s,g)=>s+g.attributes.position.count,0),indices:gs.reduce((s,g)=>s+(g.index?.count||0),0)});return realMerge(gs,groups);};');
const {buildHighlandRig}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const buildStart=performance.now();
const rig=buildHighlandRig(gltf.scene);
const buildMs=performance.now()-buildStart;
const counted={...counters};
let finalMeshes=0,finalPositionVertices=0,trunkSamples=0,baseFitPoints=0;
rig.root.traverse(o=>{if(!o.isMesh)return;finalMeshes++;const n=o.geometry.attributes.position.count;finalPositionVertices+=n;const sampled=Math.ceil(n/Math.max(1,Math.ceil(n/240)));baseFitPoints+=sampled;if(o.userData.rigPart==='trunk')trunkSamples+=sampled;});
const result={provenance:'Exact bundled GLB and production rig source; CPU-only Node audit, texture decode stubbed. Timings do not model Android or shader compilation.',parseMs,buildMs,samples,counters:counted,nonIndexed,applied:{count:applied.length,vertices:applied.reduce((s,x)=>s+x.vertices,0),identityCount:applied.filter(x=>x.identity).length},merges,final:{meshes:finalMeshes,vertices:finalPositionVertices,fitPoints:rig.fitPoints.length,baseFitPoints,trunkSamples,avoidableAxisAllocations:trunkSamples*2}};
fs.writeFileSync(outputPath,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.error('Audit written to '+outputPath);
console.log(JSON.stringify(result,null,2));

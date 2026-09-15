'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),zlib=require('node:zlib'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),asset=path.join(root,'web/preview/models/studio-environment.rgba16f.gz');
const source=fs.readFileSync(path.join(root,'web/preview/src/studio-environment.js'),'utf8').replace(/^import .*;\s*$/gm,'').replace(/^export /gm,'');
function harness(response){
 const THREE={RGBAFormat:1023,HalfFloatType:1016,CubeUVReflectionMapping:306,LinearSRGBColorSpace:'srgb-linear',LinearFilter:1006,DataTexture:class{constructor(data,width,height,format,type){Object.assign(this,{image:{data,width,height},format,type});}}};
 const context={THREE,fetch:async()=>response,Blob,DecompressionStream,Uint8Array,Uint16Array,DataView,Error};
 vm.runInNewContext(source+'\nthis.api={loadStudioEnvironment,createStudioEnvironmentTexture,STUDIO_ENVIRONMENT};',context);return {...context.api,THREE};
}
const raw=()=>zlib.gunzipSync(fs.readFileSync(asset));
const response=bytes=>({ok:true,arrayBuffer:async()=>Uint8Array.from(bytes).buffer});
test('baked atlas retains the complete original half-float PMREM and source provenance',()=>{
 const compressed=fs.readFileSync(asset),data=raw(),manifest=JSON.parse(fs.readFileSync(asset+'.json'));
 const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
 assert.equal(manifest.three_revision,'180');assert.equal(manifest.width,768);assert.equal(manifest.height,1024);
 assert.equal(manifest.bytes,6291456);assert.equal(data.length,manifest.bytes);assert.equal(hash(data),manifest.sha256);
 assert.equal(compressed.length,manifest.compressed_bytes);assert.equal(hash(compressed),manifest.compressed_sha256);
 assert.equal(hash(fs.readFileSync(path.join(root,'web/preview/src/studio-environment-source.js'))),manifest.source_sha256);
 assert.equal(hash(fs.readFileSync(path.join(root,'web/preview/src/package-lock.json'))),manifest.graphics_lock_sha256);
 let maximum=0;for(let i=0;i<data.length;i+=2){const value=data.readUInt16LE(i);assert.notEqual(value&0x7c00,0x7c00,'Atlas must contain finite half-floats');maximum=Math.max(maximum,value);}
 assert.ok(maximum>0x3c00,'HDR lighting must retain values above 1');
});
test('loader preserves every half-float word and texture uploads do not reconvolve or flip the atlas',async()=>{
 const h=harness(response(fs.readFileSync(asset))),data=await h.loadStudioEnvironment(),expected=raw();
 assert.equal(data.length,expected.length/2);for(let i=0;i<data.length;i++)assert.equal(data[i],expected.readUInt16LE(i*2));
 const t=h.createStudioEnvironmentTexture(data);assert.equal(t.image.data,data);assert.equal(t.image.width,768);assert.equal(t.image.height,1024);
 assert.equal(t.type,h.THREE.HalfFloatType);assert.equal(t.mapping,h.THREE.CubeUVReflectionMapping);assert.equal(t.colorSpace,h.THREE.LinearSRGBColorSpace);
 assert.equal(t.minFilter,h.THREE.LinearFilter);assert.equal(t.magFilter,h.THREE.LinearFilter);assert.equal(t.flipY,false);assert.equal(t.generateMipmaps,false);assert.equal(t.needsUpdate,true);
 const restored=h.createStudioEnvironmentTexture(data);assert.notEqual(restored,t);assert.equal(restored.image.data,data,'Context restoration uploads the same immutable atlas');
});
for(const [name,bytes] of [['truncated output',zlib.gzipSync(Buffer.alloc(4))],['excess output',zlib.gzipSync(Buffer.alloc(6291458))],['corrupt archive',Buffer.from('invalid gzip')],['empty archive',Buffer.alloc(0)]]){
 test('invalid lighting cannot report model readiness: '+name,async()=>{await assert.rejects(harness(response(bytes)).loadStudioEnvironment());});
}
test('missing lighting fails without falling back to the blocking GPU convolution',async()=>{await assert.rejects(harness({ok:false}).loadStudioEnvironment(),/could not be read/);});
test('unavailable or incorrectly sized atlas cannot be uploaded',()=>{const h=harness();for(const value of [null,new Uint16Array(2),new Uint8Array(6291456)])assert.throws(()=>h.createStudioEnvironmentTexture(value),/unavailable/);});

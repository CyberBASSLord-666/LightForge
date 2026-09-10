'use strict';
/* Neutral-mask transform/overlap test, not model inference or model accuracy.
 * Real production STFT, complex mask scatter, ISTFT and chunk ownership run
 * across several nonzero context windows, including impulses at seams. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
require(root+'/web/analysis/dsp.js');const Deux=require(root+'/web/analysis/separator-deux.js'),manifest=JSON.parse(fs.readFileSync(root+'/web/analysis/models/deux/manifest.json'));
const masks=new Map();function mask(frames){if(!masks.has(frames)){const data=new Float32Array(manifest.indices.length*frames*2);for(let i=0;i<data.length;i+=2)data[i]=1;masks.set(frames,data);}return masks.get(frames);}
class Tensor{constructor(type,data,dims){this.data=data;this.dims=dims;}dispose(){}}
const ort={Tensor,InferenceSession:{create:async url=>({run:async({input})=>({output:new Tensor('float32',String(url).includes('head-')?mask(input.dims[1]):String(url).endsWith('/front.onnx')?new Float32Array(1301*60*256):input.data,[])}),release:async()=>{}})}};
global.fetch=async()=>({json:async()=>manifest});
const sources=['web/analysis/separator-deux.js','web/analysis/dsp.js','web/analysis/models/deux/manifest.json','qa/release-2.2.4/test-source-clock.cjs'];
const hashes=()=>Object.fromEntries(sources.map(p=>[p,sha(path.join(root,p))])),sourceHashes=hashes();
(async()=>{
 const total=Math.round(21.137*44100)+1,left=new Float32Array(total),right=new Float32Array(total);for(let i=0;i<total;i++){left[i]=.1*Math.sin(i*2*Math.PI*237/44100);right[i]=.08*Math.sin(i*2*Math.PI*411/44100+.3);}
 for(const at of [0,220499,220500,440999,441000,661499,661500,total-1]){left[at]+=.5;right[at]-=.2;}
 const out=new Float32Array(total);let emitted=0,maximum=0,previous=0;
 const separator=await Deux.create({ort,baseUrl:'https://neutral.invalid/'}),result=await separator.process(async(start,count)=>[left,right].map(source=>{const a=new Float32Array(count),lo=Math.max(0,start),hi=Math.min(total,start+count);if(hi>lo)a.set(source.subarray(lo,hi),lo-start);return a;}),total,chunk=>{assert.equal(chunk.startSample,emitted);assert.deepEqual(chunk.vocals,chunk.accompaniment);out.set(chunk.vocals,emitted);emitted+=chunk.vocals.length;},p=>{assert.ok(p.progress>=previous-1e-9);previous=p.progress;});await separator.release();
 assert.equal(emitted,total);assert.equal(previous,1);assert.ok(result.chunks>=4);
 for(let i=0;i<total;i++)maximum=Math.max(maximum,Math.abs(out[i]-(left[i]+right[i])/2));assert.ok(maximum<.000002,'Round-trip error '+maximum);
 assert.deepEqual(hashes(),sourceHashes,'Source changed while verifying its clock');const receipt={release:'2.2.4',passed:true,errors:[],source_hashes:sourceHashes,scope:'Neutral masks and fake graph sessions; actual production STFT/scatter/ISTFT and overlapping chunk scheduler. No neural inference.',samples:total,chunks:result.chunks,maxAbsError:maximum,contiguousSourceSamples:true,monotonicProgress:true};fs.writeFileSync(path.join(__dirname,'source-clock-verification.json'),JSON.stringify(receipt,null,2));console.log(receipt);
})().catch(e=>{console.error(e);process.exitCode=1;});

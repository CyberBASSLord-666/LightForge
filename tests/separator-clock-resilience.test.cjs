'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),source=name=>fs.readFileSync(path.join(root,'web','analysis',name),'utf8');
const deuxManifest={id:'deux-test',checkpointSHA256:'a'.repeat(64),execution:'bounded-independent-batches-v1',headFrames:128,frames:1301,samples:573300,indices:new Array(3958).fill(0),bandsPerFrequency:new Array(1025).fill(1)};
const mdxManifest={id:'mdx-test',sha256:'b'.repeat(64),sampleRate:44100,nFFT:7680,file:'mdx.onnx',compensate:1};
function harness(kind,configure,{central=true}={}){
 const context=vm.createContext({URL,Float32Array,Float64Array,Number,Math,Promise,setTimeout,clearTimeout,console,LightForgeDSP:{FFT:class{run(){}}},fetch:async()=>({json:async()=>deuxManifest})});context.self=context;configure(context);
 if(central)vm.runInContext(source('diagnostic-clock.js'),context);
 vm.runInContext(source(kind==='deux'?'separator-deux.js':'separator-mdx.js'),context);
 return context;
}
async function process(kind,configure,options){
 const context=harness(kind,configure,options),samples=kind==='deux'?573300:261120,zero=new Float32Array(samples),chunks=[];
 const separator=kind==='deux'?await context.LightForgeDeux.create({ort:{},baseUrl:'https://test/models/' }):await context.LightForgeMdxSeparator.create({ort:{},manifest:mdxManifest,denoise:false});
 const result=kind==='deux'?await separator.process(async()=>[zero,zero],1,async chunk=>chunks.push(chunk)):await separator.process(async()=>[zero,zero],1,async chunk=>chunks.push(chunk));
 await separator.release();assert.equal(chunks.length,1);assert.equal(result.chunks,1);assert.equal(result.analysisSeconds,0);return result;
}

test('live Deux and MDX result shapes report zero restored passages without checkpoint hits',async()=>{
 for(const kind of ['deux','mdx']){
  const result=await process(kind,scope=>{scope.performance={now:()=>0};scope.Date={now:()=>0};});
  assert.equal(result.restoredPassages,0,kind);
 }
});

test('MDX counts only finite accepted ensemble checkpoint passages',async()=>{
 const context=harness('mdx',scope=>{scope.performance={now:()=>0};scope.Date={now:()=>0};}),C=context.LightForgeMdxSeparator.constants,zero=new Float32Array(C.INPUT_LENGTH),reads=[];
 const invalid=new Float32Array(C.INPUT_LENGTH);invalid[0]=NaN;
 const separator=await context.LightForgeMdxSeparator.create({ort:{},manifest:mdxManifest,checkpoint:{readFloats:async name=>{reads.push(name);return reads.length===1?[new Float32Array(C.INPUT_LENGTH)]:[invalid];},writeFloats:async()=>{throw Error('Silent cache misses must not be written.');}}});
 const chunks=[],result=await separator.process(async()=>[zero,zero],C.CORE+1,async chunk=>chunks.push(chunk));await separator.release();
 assert.deepEqual(reads,['mdx-ensemble-0','mdx-ensemble-'+C.STRIDE]);
 assert.equal(chunks.length,2);assert.equal(result.chunks,2);assert.equal(result.restoredPassages,1);assert.equal(result.modelPasses,0);
});
const scenarios=[
 ['blocked-getter',context=>{context.performance={};Object.defineProperty(context.performance,'now',{get(){throw Error('blocked performance getter');}});context.Date={};}],
 ['late-call',context=>{let calls=0;context.performance={now(){if(++calls===1)return 10;throw Error('late performance call');}};context.Date={now:()=>1789000000000};}],
 ['performance-source-swap',context=>{let reads=0;Object.defineProperty(context,'performance',{get(){reads++;return reads===1?{now:()=>10}:{now:()=>1789000000000};}});context.Date={now:()=>1789000000000};context.assertClockReads=()=>assert.equal(reads,1);}],
 ['date-source-swap',context=>{let reads=0;context.performance={};Object.defineProperty(context,'Date',{get(){reads++;return reads===1?{now:()=>10}:{now:()=>1789000000000};}});context.assertClockReads=()=>assert.equal(reads,1);}]
];
for(const kind of ['deux','mdx'])test(kind+' separation completes with hostile central timing sources',async()=>{
 for(const [name,configure] of scenarios){const context=harness(kind,configure),samples=kind==='deux'?573300:261120,zero=new Float32Array(samples),chunks=[];const separator=kind==='deux'?await context.LightForgeDeux.create({ort:{},baseUrl:'https://test/models/'}):await context.LightForgeMdxSeparator.create({ort:{},manifest:mdxManifest,denoise:false});const result=await separator.process(async()=>[zero,zero],1,async chunk=>chunks.push(chunk));await separator.release();assert.equal(chunks.length,1,name);assert.equal(result.chunks,1,name);assert.equal(result.analysisSeconds,0,name);context.assertClockReads?.();}
});
for(const kind of ['deux','mdx'])test(kind+' separation local timing fallback completes with hostile sources',async()=>{
 for(const [name,configure] of scenarios){const context=harness(kind,configure,{central:false}),samples=kind==='deux'?573300:261120,zero=new Float32Array(samples),chunks=[];const separator=kind==='deux'?await context.LightForgeDeux.create({ort:{},baseUrl:'https://test/models/'}):await context.LightForgeMdxSeparator.create({ort:{},manifest:mdxManifest,denoise:false});const result=await separator.process(async()=>[zero,zero],1,async chunk=>chunks.push(chunk));await separator.release();assert.equal(chunks.length,1,name);assert.equal(result.chunks,1,name);assert.equal(result.analysisSeconds,0,name);context.assertClockReads?.();}
});
for(const kind of ['deux','mdx'])test(kind+' separation retains normal elapsed-time semantics',async()=>{
 let calls=0;const context=harness(kind,scope=>{scope.performance={now:()=>++calls*100};scope.Date={now:()=>1789000000000};}),samples=kind==='deux'?573300:261120,zero=new Float32Array(samples),separator=kind==='deux'?await context.LightForgeDeux.create({ort:{},baseUrl:'https://test/models/'}):await context.LightForgeMdxSeparator.create({ort:{},manifest:mdxManifest,denoise:false});
 const result=await separator.process(async()=>[zero,zero],1,async()=>{});await separator.release();assert.equal(result.analysisSeconds,.1);
});

'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const constants={BINS:3072,FRAMES:256,INPUT_FLOATS:4*3072*256,INPUT_BYTES:4*4*3072*256};
const token='12345678-1234-1234-1234-123456789abc';
function load(){
 const window={LightForgeDiagnostics:{log(){}}};
 const context={window,DOMException,setTimeout,clearTimeout,btoa,Float32Array,ArrayBuffer,DataView,fetch:global.fetch};
 vm.runInNewContext(fs.readFileSync(require.resolve('../web/background/native-mdx.js'),'utf8'),context);
 return window.LightForgeNativeMdx;
}
function responseBytes(){
 const bytes=new ArrayBuffer(constants.INPUT_BYTES),view=new DataView(bytes);view.setFloat32(0,Math.fround(1e-8),true);view.setFloat32(constants.INPUT_BYTES-4,-.25,true);return bytes;
}
test('balanced native bridge uploads bounded chunks and returns exact little-endian output',async()=>{
 const uploaded=[];let state='idle',statusCalls=0,releaseCalls=0;
 const output=responseBytes();
 const bridge={
  nativeMdxAvailability(){return JSON.stringify({available:true});},
  nativeMdxBegin(id,bytes){assert.equal(id,'job');assert.equal(bytes,constants.INPUT_BYTES);state='uploading';return JSON.stringify({token,state,progress:0});},
  nativeMdxAppend(id,t,chunk){assert.equal(id,'job');assert.equal(t,token);const bytes=Buffer.from(chunk,'base64');assert.ok(bytes.length<=64*1024);uploaded.push(bytes);return JSON.stringify({token,state:'uploading',progress:.25});},
  nativeMdxRun(){state='completed';return JSON.stringify({token,state,url:'https://appassets.androidplatform.net/background/native-mdx/'+token+'.bin'});},
  nativeMdxStatus(){statusCalls++;return JSON.stringify({token,state,url:'https://appassets.androidplatform.net/background/native-mdx/'+token+'.bin'});},
  nativeMdxCancel(){assert.fail('unexpected cancellation');},
  nativeMdxRelease(){releaseCalls++;return '{}';}
 };
 const previous=global.fetch;global.fetch=async url=>{assert.equal(url,'https://appassets.androidplatform.net/background/native-mdx/'+token+'.bin');return {ok:true,arrayBuffer:async()=>output};};
 try{
  const native=load(),predict=native.create(bridge,'job'),input=new Float32Array(constants.INPUT_FLOATS);let progress=[];input[0]=Math.fround(.125);input[input.length-1]=Math.fround(-.5);
  const value=await predict(input,new AbortController().signal,p=>progress.push(p));
  assert.equal(value.length,constants.INPUT_FLOATS);assert.equal(value[0],Math.fround(1e-8));assert.equal(value.at(-1),Math.fround(-.25));
  assert.equal(Buffer.concat(uploaded).length,constants.INPUT_BYTES);assert.equal(Buffer.compare(Buffer.concat(uploaded),Buffer.from(input.buffer)),0);assert.equal(uploaded.length,256);assert.ok(progress.some(p=>p.progress===1));assert.equal(statusCalls,0);
  await predict.release();assert.equal(releaseCalls,1);
 }finally{global.fetch=previous;}
});
test('balanced native bridge falls back cleanly when Android reports no compatible runtime',()=>{
 let message='';const native=load(),predict=native.create({nativeMdxAvailability:()=>JSON.stringify({available:false}),nativeMdxBegin(){},nativeMdxAppend(){},nativeMdxRun(){}},'job',value=>{message=value;});assert.equal(predict,undefined);assert.match(message,/WebAssembly/);
});
test('native MDX output validation disables only the optional accelerator',async()=>{
 let runs=0,compatibility=0;const bridge={nativeMdxAvailability:()=>JSON.stringify({available:true}),nativeMdxBegin:()=>JSON.stringify({token,state:'uploading'}),nativeMdxAppend:()=>JSON.stringify({token,state:'uploading'}),nativeMdxRun:()=>{runs++;return JSON.stringify({token,state:'completed',url:'https://appassets.androidplatform.net/background/native-mdx/'+token+'.bin'});},nativeMdxStatus:()=>JSON.stringify({token,state:'completed',url:'https://appassets.androidplatform.net/background/native-mdx/'+token+'.bin'}),nativeMdxCancel(){},nativeMdxRelease:()=>('{}')};
 const previous=global.fetch;global.fetch=async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(8)});
 try{const predict=load().create(bridge,'job',()=>compatibility++),input=new Float32Array(constants.INPUT_FLOATS);assert.equal(await predict(input),undefined);assert.equal(await predict(input),undefined);assert.equal(runs,1);assert.equal(compatibility,1);}finally{global.fetch=previous;}
});

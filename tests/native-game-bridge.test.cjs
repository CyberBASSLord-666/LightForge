'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const token='12345678-1234-1234-1234-123456789abc';
function load(){const window={LightForgeDiagnostics:{log(){}}};vm.runInNewContext(fs.readFileSync(require.resolve('../web/background/native-game.js'),'utf8'),{window,DOMException,setTimeout,clearTimeout,btoa,Float32Array,Uint8Array,DataView,Number,JSON,Error});return window.LightForgeNativeGame;}
function fixture(change={}){
 const seen={chunks:[],release:0,cancel:0,begin:0},settings={samples:44100,language:0,seed:2025},notes=[{start:.1,end:.8,midi:60.123456789}];let state='idle';
 const status=()=>({token,state,progress:.5,sampleRate:44100,...settings,steps:8,model:'game-large-1.0.3-lightforge-1',notes});
 const bridge={
  nativeGameAvailability:()=>JSON.stringify({available:true}),
  nativeGameBegin(id,bytes,language,seed){assert.equal(id,'job');seen.begin++;Object.assign(settings,{samples:bytes/4,language,seed});state='uploading';return JSON.stringify(status());},
  nativeGameAppend(id,t,chunk){assert.equal(id,'job');assert.equal(t,token);seen.chunks.push(Buffer.from(chunk,'base64'));return JSON.stringify(status());},
  nativeGameRun(){state='completed';return JSON.stringify(status());},
  nativeGameStatus:()=>JSON.stringify(status()),
  nativeGameCancel(){seen.cancel++;state='cancelled';},
  nativeGameRelease(){seen.release++;state='idle';return '{}';},...change
 };
 return {bridge,seen,settings,notes,status,setState:value=>{state=value;}};
}
test('GAME bridge uploads finite PCM in bounded little-endian chunks and retains unrounded notes',async()=>{
 const f=fixture(),api=load(),predict=api.create(f.bridge,'job'),whole=new Float32Array(44102),pcm=whole.subarray(1,44101);pcm[0]=.125;pcm[pcm.length-1]=-.5;
 const notes=await predict(pcm,3,0xffffffff);assert.equal(notes[0].midi,60.123456789);assert.equal(f.seen.release,1);assert.ok(f.seen.chunks.every(x=>x.length<=48*1024));
 const bytes=Buffer.concat(f.seen.chunks);assert.equal(bytes.length,pcm.byteLength);assert.equal(bytes.readFloatLE(0),.125);assert.equal(bytes.readFloatLE(bytes.length-4),-.5);
 assert.deepEqual(f.settings,{samples:44100,language:3,seed:0xffffffff});assert.equal(predict.analysisCacheProfile,api.analysisCacheProfile);
 await predict.release();await assert.rejects(()=>predict(pcm,0,2025),/closed/);
});
test('GAME bridge refuses invalid PCM and settings before native allocation',async()=>{
 const f=fixture(),predict=load().create(f.bridge,'job');
 for(const [pcm,language,seed] of [[new Float32Array(0),0,2025],[new Float32Array(705601),0,2025],[Float32Array.of(NaN),0,2025],[Float32Array.of(Infinity),0,2025],[new Float32Array(44100),5,2025],[new Float32Array(44100),0,-1],[new Float32Array(44100),0,1.5],[new Float32Array(44100),0,0x100000000]])await assert.rejects(()=>predict(pcm,language,seed));
 assert.equal(f.seen.begin,0);
});
test('missing or unavailable GAME runtime remains optional',()=>{
 const f=fixture();delete f.bridge.nativeGameCancel;assert.equal(load().create(f.bridge,'job'),undefined);
 let warned=0;const unavailable=fixture({nativeGameAvailability:()=>'{"available":false}'});assert.equal(load().create(unavailable.bridge,'job',()=>warned++),undefined);assert.equal(warned,1);
});
test('GAME result metadata cannot substitute another sample, model, seed or language',async()=>{
 for(const mutation of [{samples:123},{sampleRate:22050},{language:2},{seed:7},{steps:4},{model:'other'}]){
  const f=fixture();f.bridge.nativeGameRun=()=>{f.setState('completed');return JSON.stringify({...f.status(),...mutation});};
  const predict=load().create(f.bridge,'job');assert.equal(await predict(new Float32Array(44100),0,2025),undefined);assert.equal(f.seen.release,1);assert.equal(await predict(new Float32Array(44100),0,2025),undefined);assert.equal(f.seen.begin,1);
 }
});
test('malformed GAME notes cannot become a successful passage',async()=>{
 for(const notes of [[{start:.2,end:.1,midi:60}],[{start:-.1,end:.8,midi:60}],[{start:0,end:2,midi:60}],[{start:0,end:.8,midi:128}],[{start:0,end:.8,midi:60},{start:.4,end:.9,midi:61}],Array(1602).fill({start:0,end:.8,midi:60})]){
  const f=fixture();f.bridge.nativeGameRun=()=>{f.setState('completed');return JSON.stringify({...f.status(),notes});};assert.equal(await load().create(f.bridge,'job')(new Float32Array(44100),0,2025),undefined);assert.equal(f.seen.release,1);
 }
});
test('unknown retirement is fatal rather than a WASM fallback',async()=>{
 const f=fixture({nativeGameStatus:()=>{throw Error('bridge unavailable');}});f.bridge.nativeGameRun=()=>{f.setState('failed');return JSON.stringify(f.status());};
 const predict=load().create(f.bridge,'job');await assert.rejects(()=>predict(new Float32Array(44100),0,2025),error=>error.code==='native-game-retirement-pending');
});
test('native destructor failure cannot authorize fallback or successful release',async()=>{
 let fallback=0;const f=fixture();
 f.bridge.nativeGameRun=()=>{f.setState('retirement-failed');return JSON.stringify(f.status());};
 f.bridge.nativeGameCancel=()=>{f.seen.cancel++;};
 const predict=load().create(f.bridge,'job',()=>fallback++);
 await assert.rejects(()=>predict(new Float32Array(44100),0,2025),error=>error.code==='native-game-retirement-pending');
 await assert.rejects(()=>predict.release(),error=>error.code==='native-game-retirement-pending');
 assert.equal(fallback,0);assert.equal(f.seen.release,0);
});
test('unknown native token never authorizes a fallback',async()=>{
 const f=fixture({nativeGameBegin:()=>'{"token":"bad","state":"uploading"}'}),predict=load().create(f.bridge,'job');await assert.rejects(()=>predict(new Float32Array(44100),0,2025),error=>error.code==='native-game-retirement-pending');
});
test('abort cancels and confirms cleanup before the call rejects',async()=>{
 const f=fixture(),controller=new AbortController();f.bridge.nativeGameRun=()=>{f.setState('running');controller.abort();return JSON.stringify(f.status());};
 await assert.rejects(()=>load().create(f.bridge,'job')(new Float32Array(44100),0,2025,controller.signal),error=>error.name==='AbortError');assert.ok(f.seen.cancel>0);assert.equal(f.seen.release,1);
});
test('concurrent and callback-reentrant passages are rejected',async()=>{
 const f=fixture(),predict=load().create(f.bridge,'job');let rejected;
 await predict(new Float32Array(44100),0,2025,undefined,()=>{rejected??=assert.rejects(()=>predict(new Float32Array(44100),0,2025),/already active/);});await rejected;assert.equal(f.seen.begin,1);
});
test('release from the final upload callback cannot become a WASM fallback',async()=>{
 const f=fixture();let fallback=0,closing,runs=0;f.bridge.nativeGameRun=()=>{runs++;throw Error('No run after close');};
 const predict=load().create(f.bridge,'job',()=>fallback++);
 await assert.rejects(()=>predict(new Float32Array(44100),0,2025,undefined,()=>{if(f.seen.chunks.length===4)closing=predict.release();}),error=>error.name==='AbortError');
 await closing;assert.equal(runs,0);assert.equal(fallback,0);
});
test('abort from the final upload callback is observed before native Run',async()=>{
 const f=fixture(),controller=new AbortController();let runs=0,fallback=0;f.bridge.nativeGameRun=()=>{runs++;throw Error('No run after abort');};
 await assert.rejects(()=>load().create(f.bridge,'job',()=>fallback++)(new Float32Array(44100),0,2025,controller.signal,()=>{if(f.seen.chunks.length===4)controller.abort();}),error=>error.name==='AbortError');
 assert.equal(runs,0);assert.equal(fallback,0);
});
test('abort from the completion callback never returns successful notes',async()=>{
 const f=fixture(),controller=new AbortController();let fallback=0;
 await assert.rejects(()=>load().create(f.bridge,'job',()=>fallback++)(new Float32Array(44100),0,2025,controller.signal,p=>{if(p.progress===1)controller.abort();}),error=>error.name==='AbortError');assert.equal(fallback,0);
});

'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{createHash}=require('node:crypto');
const RATE=44100,PROTOCOL='native-game-pair-v1',TOKEN='12345678-1234-1234-1234-123456789abc',MODEL='game-large-1.0.3-lightforge-1';
const source=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
function notesFor(request){const duration=request.pcm.length/RATE;return [{start:.123456,end:.423456,midi:63.123456789},{start:.6,end:duration-.05,midi:60.23456789}];}
function adapter({batch=true,records=new Map(),silent=[],failure,invalid,onUnary}={}){
 const stats={unary:[],pairs:[],calls:[],reads:[],checkpointReads:[],writes:[],wasm:0},context={};new Function('self','fetch',source('web/analysis/game.js'))(context,async()=>({json:async()=>({id:MODEL})}));
 const signature=request=>({samples:request.pcm.length,language:request.language,seed:request.seed,sha256:createHash('sha256').update(Buffer.from(request.pcm.buffer,request.pcm.byteOffset,request.pcm.byteLength)).digest('hex')});
 const nativeInfer=async(pcm,language,seed,onProgress)=>{const request={pcm,language,seed},call=signature(request);stats.unary.push(call);stats.calls.push(call);await onUnary?.(request);onProgress?.(.5);return notesFor(request);};
 if(batch)nativeInfer.batch=async(requests,onProgress)=>{const calls=requests.map(signature);stats.pairs.push(calls);stats.calls.push(...calls);for(const progress of [.2,.8,.4,1])onProgress?.(progress);if(failure)throw failure;return invalid===undefined?requests.map(notesFor):invalid;};
 return {stats,records,nativeInfer,api:context.LightForgeGAME,create:()=>context.LightForgeGAME.create({ort:{InferenceSession:{create:async()=>{stats.wasm++;throw Error('Unexpected WASM');}}},baseUrl:'https://app.test/models/game/',nativeInfer,checkpoint:{read:async key=>{stats.checkpointReads.push(key);return records.get(key);},write:async(key,value)=>{stats.writes.push(key);records.set(key,value);}}}),
  read:async(first,count)=>{stats.reads.push({first,count});const index=first===0?0:Math.round((first/RATE+2)/12);return new Float32Array(count).fill(silent.includes(index)?0:.125+(first%997)/10000);}};
}
test('pair scheduling preserves complete unary notes, source clocks, seeds, checkpoints and monotonic progress',async()=>{
 const unary=adapter({batch:false}),paired=adapter(),a=await unary.create(),b=await paired.create(),progress=[];
 const expected=await a.process(unary.read,Math.round(53.137*RATE),{language:4}),actual=await b.process(paired.read,Math.round(53.137*RATE),{language:4,onProgress:(value,info)=>{progress.push(value);if(value===2.6/5&&paired.stats.writes.length===1){assert.equal(info.passageIndex,3);assert.equal(info.passagesCompleted,1);}}});
 assert.deepEqual(plain(actual),plain(expected));assert.deepEqual(plain([...paired.records]),plain([...unary.records]));
 assert.equal(paired.stats.pairs.length,1);assert.equal(paired.stats.unary.length,3);assert.deepEqual(paired.stats.calls,unary.stats.calls);assert.ok(paired.stats.pairs.every(pair=>pair[0].samples===pair[1].samples));
 assert.ok(progress.every((value,index)=>!index||value>=progress[index-1]));assert.ok(progress.includes(2.6/5),'progress advances during the second passage');assert.equal(progress.at(-1),1);assert.deepEqual(paired.stats.reads,unary.stats.reads);assert.equal(paired.stats.wasm,0);await a.release();await b.release();
});
test('every mixed four-passage restore combination runs each missing passage once without reading restored PCM',async()=>{
 const total=Math.round(38.137*RATE),seed=adapter({batch:false}),initial=await seed.create();const expected=await initial.process(seed.read,total);await initial.release();
 for(let mask=0;mask<16;mask++){
  const records=new Map([...seed.records].filter(([key])=>(mask&(1<<Number(key.split('-').at(-1))))!==0).map(([key,value])=>[key,structuredClone(value)])),h=adapter({records}),game=await h.create(),actual=await game.process(h.read,total);
  assert.deepEqual(plain(actual),plain(expected),`restore mask ${mask}`);const inferred=h.stats.pairs.flat().concat(h.stats.unary).sort((a,b)=>a.seed-b.seed),missing=seed.stats.unary.filter((_request,index)=>(mask&(1<<index))===0);
  assert.deepEqual(inferred,missing,`inference mask ${mask}`);assert.deepEqual(h.stats.calls,missing);assert.equal(h.stats.pairs.length,(mask&2)===0&&(mask&4)===0?1:0);assert.equal(h.stats.reads.length,missing.length);assert.equal(h.stats.writes.length,missing.length);await game.release();
 }
});
test('unequal first and tail geometries stay unary without padding or redundant reads',async()=>{
 for(const duration of [13,26]){const h=adapter(),game=await h.create();await game.process(h.read,duration*RATE);assert.equal(h.stats.pairs.length,0);assert.equal(h.stats.unary.length,Math.ceil(duration/12));assert.equal(h.stats.reads.length,h.stats.unary.length);assert.deepEqual(h.stats.unary.map(call=>call.samples),duration===13?[13*RATE,3*RATE]:[14*RATE,16*RATE,4*RATE]);await game.release();}
});
test('metadata-only lookahead is rechecked after native work rather than retaining stale hits or misses',async()=>{
 const total=Math.round(38.137*RATE),seed=adapter({batch:false}),initial=await seed.create(),expected=await initial.process(seed.read,total);await initial.release();
 for(const [index,restored]of [[0,true],[0,false],[1,true]]){
  const key='game-0-'+index,nextKey='game-0-'+(index+1),firstSeed=(2025+index*104729)>>>0,nextSeed=(2025+(index+1)*104729)>>>0,records=new Map([...seed.records].map(([name,value])=>[name,structuredClone(value)])),next=structuredClone(records.get(nextKey));records.delete(key);if(!restored)records.delete(nextKey);
  const h=adapter({records,onUnary:request=>{if(request.seed===firstSeed){if(restored)records.delete(nextKey);else records.set(nextKey,next);}}}),game=await h.create(),actual=await game.process(h.read,total);
  assert.deepEqual(plain(actual),plain(expected));assert.deepEqual(h.stats.calls.map(call=>call.seed),restored?[firstSeed,nextSeed]:[firstSeed]);assert.equal(h.stats.checkpointReads.filter(name=>name===nextKey).length,2);assert.equal(h.stats.pairs.length,0);assert.equal(h.stats.reads.length,restored?2:1);await game.release();
 }
});
test('silent passages and final singleton keep unary work and exact final stitching',async()=>{
 for(const silent of [[0],[1],[2],[0,1],[1,2],[0,1,2,3]]){
  const unary=adapter({batch:false,silent}),paired=adapter({silent}),a=await unary.create(),b=await paired.create();const expected=await a.process(unary.read,38*RATE),actual=await b.process(paired.read,38*RATE);
  assert.deepEqual(plain(actual),plain(expected));assert.deepEqual(paired.stats.calls,unary.stats.calls);assert.equal(paired.stats.reads.length,4);assert.deepEqual(plain([...paired.records]),plain([...unary.records]));await a.release();await b.release();
 }
});
test('incomplete or invalid pair results never publish either checkpoint or invoke WASM',async()=>{
 for(const invalid of [null,{},[],[[]],[[],[],[]],[[],undefined],new Array(2),[[],new Array(1)],[[],[{start:0,end:1,midi:NaN}]],[[],[{start:0,end:17,midi:60}]],[[],[{start:.3,end:.5,midi:60},{start:.1,end:.4,midi:60}]]]){
  const h=adapter({invalid}),game=await h.create();await assert.rejects(game.process(h.read,24*RATE),error=>error.code==='native-game-fallback');assert.equal(h.records.size,0);assert.equal(h.stats.writes.length,0);assert.equal(h.stats.unary.length,0);assert.equal(h.stats.wasm,0);await game.release();
 }
});
test('sparse pair requests and sparse note arrays fail before any inference or checkpoint',async()=>{
 const h=adapter(),game=await h.create(),request={pcm:new Float32Array(RATE),language:0,seed:2025};
 await assert.rejects(game.inferBatch([request,,]),error=>error.code==='native-game-fallback');assert.equal(h.stats.pairs.length,0);assert.equal(h.api.validNotes(new Array(1),RATE),false);assert.equal(h.api.validNotes([],undefined),false);assert.equal(h.records.size,0);await game.release();
});
test('pair cancellation, unconfirmed retirement and failed cache fencing preserve their fatal identities',async()=>{
 for(const failure of [new DOMException('cancelled','AbortError'),Object.assign(Error('pending'),{code:'native-game-retirement-pending'}),Object.assign(Error('fence'),{code:'native-game-fence-failed'})]){
  const h=adapter({failure}),game=await h.create();await assert.rejects(game.process(h.read,24*RATE),error=>error===failure);assert.equal(h.records.size,0);assert.equal(h.stats.wasm,0);await game.release();
 }
});
function bridgeFixture(){
 const seen={chunks:[],begin:0,batch:0,release:0,cancel:0,run:0},notes=[[{start:.1,end:.5,midi:60.123456789}],[{start:.01,end:.3,midi:72.987654321}]];let state='idle',passages=[];
 const status=()=>({token:TOKEN,state,progress:.5,sampleRate:RATE,steps:8,model:MODEL,batchProtocol:PROTOCOL,passages,notes});
 const bridge={nativeGameAvailability:()=>JSON.stringify({available:true,batchProtocol:PROTOCOL,maxBatchPassages:2,maxBatchInputBytes:2*RATE*16*4}),nativeGameBegin(){seen.begin++;throw Error('Unary not expected');},
  nativeGameBeginBatch(id,descriptors){assert.equal(id,'job');seen.batch++;passages=JSON.parse(descriptors);state='uploading';return JSON.stringify(status());},
  nativeGameAppend(id,token,chunk){assert.equal(token,TOKEN);seen.chunks.push(Buffer.from(chunk,'base64'));return JSON.stringify(status());},
  nativeGameRun(){seen.run++;state='completed';return JSON.stringify(status());},nativeGameStatus:()=>JSON.stringify(status()),
  nativeGameCancel(){seen.cancel++;if(state==='uploading'||state==='running')state='cancelled';},nativeGameRelease(){seen.release++;state='idle';return '{}';}};
 const window={LightForgeDiagnostics:{log(){}}};vm.runInNewContext(source('web/background/native-game.js'),{window,DOMException,setTimeout,clearTimeout,btoa,Float32Array,Uint8Array,DataView,Number,JSON,Error});
 return {api:window.LightForgeNativeGame,bridge,seen,notes,status,setState:value=>{state=value;},requests:[{pcm:new Float32Array(RATE).fill(.125),language:4,seed:2025},{pcm:new Float32Array(RATE*.75).fill(-.5),language:0,seed:0xffffffff}]};
}
test('native pair capability is attached only for the exact advertised protocol and method',()=>{
 for(const mutate of [f=>{delete f.bridge.nativeGameBeginBatch;},f=>{f.bridge.nativeGameAvailability=()=>JSON.stringify({available:true});},f=>{f.bridge.nativeGameAvailability=()=>JSON.stringify({available:true,batchProtocol:PROTOCOL,maxBatchPassages:3,maxBatchInputBytes:2*RATE*16*4});}]){const f=bridgeFixture();mutate(f);const predictor=f.api.create(f.bridge,'job');assert.equal(typeof predictor,'function');assert.equal(predictor.batch,undefined);}
});
test('native pair bridge uploads ordered bounded PCM and returns two exact notes only after release',async()=>{
 const f=bridgeFixture(),predict=f.api.create(f.bridge,'job'),result=await predict.batch(f.requests);assert.deepEqual(plain(result),f.notes);assert.equal(f.seen.release,1);assert.equal(f.seen.batch,1);assert.equal(f.seen.begin,0);assert.ok(f.seen.chunks.every(chunk=>chunk.length<=48*1024));
 const bytes=Buffer.concat(f.seen.chunks);assert.equal(bytes.length,f.requests.reduce((sum,request)=>sum+request.pcm.byteLength,0));assert.equal(bytes.readFloatLE(0),.125);assert.equal(bytes.readFloatLE(f.requests[0].pcm.byteLength),-.5);await predict.release();
});
test('all pair inputs are checked before any native allocation',async()=>{
 for(const requests of [[],[{}],[{},{}],new Array(2),[{pcm:new Float32Array(1),language:0,seed:0},,],[{pcm:new Float32Array(1),language:0,seed:0},{pcm:Float32Array.of(NaN),language:0,seed:0}],[{pcm:new Float32Array(1),language:0,seed:0},{pcm:new Float32Array(RATE*16+1),language:0,seed:0}]]){const f=bridgeFixture(),predict=f.api.create(f.bridge,'job');await assert.rejects(predict.batch(requests));assert.equal(f.seen.batch,0);}
});
test('pair metadata/order and either malformed note list force complete fallback after retirement',async()=>{
 for(const mutate of [state=>({...state,batchProtocol:'other'}),state=>({...state,passages:state.passages.slice().reverse()}),state=>({...state,notes:[state.notes[0]]}),state=>({...state,notes:[state.notes[0],[{start:0,end:1,midi:72}]]}),state=>({...state,model:'other'})]){
  const f=bridgeFixture();f.bridge.nativeGameRun=()=>{f.setState('completed');return JSON.stringify(mutate(f.status()));};const predict=f.api.create(f.bridge,'job');assert.equal(await predict.batch(f.requests),undefined);assert.equal(f.seen.release,1);assert.equal(await predict.batch(f.requests),undefined);assert.equal(f.seen.batch,1);
 }
});
test('pair abort, reentrant unary calls and release share the same native owner',async()=>{
 const f=bridgeFixture(),controller=new AbortController(),predict=f.api.create(f.bridge,'job');let concurrent;
 await assert.rejects(predict.batch(f.requests,controller.signal,()=>{concurrent??=assert.rejects(predict(new Float32Array(1),0,1),/already active/);controller.abort();}),error=>error.name==='AbortError');await concurrent;assert.ok(f.seen.cancel>0);assert.equal(f.seen.release,1);assert.equal(f.seen.run,0);assert.equal(f.seen.batch,1);
});
test('pair retirement failures never authorize fallback or successful release',async()=>{
 const f=bridgeFixture();f.bridge.nativeGameRun=()=>{f.setState('retirement-failed');return JSON.stringify(f.status());};const predict=f.api.create(f.bridge,'job');await assert.rejects(predict.batch(f.requests),error=>error.code==='native-game-retirement-pending');await assert.rejects(predict.release(),error=>error.code==='native-game-retirement-pending');assert.equal(f.seen.release,0);
});

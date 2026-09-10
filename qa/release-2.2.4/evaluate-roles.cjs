'use strict';
/* Component gate on actual source estimates, never original reference vocals.
 * Arguments: estimate directory, optional track IDs. Uses production Float32
 * downsampler, Frame-MN10, vocal detail and GAME; file transport replaces OPFS.
 * The public worker and OPFS are tested separately in analysis-browser.cjs. */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),analysis=path.join(root,'web/analysis'),input=path.resolve(process.argv[2]),tracks=process.argv.slice(3);
if(!tracks.length)for(const variant of ['mix','instrumental','controlled'])for(const slug of ['nightowl','stella','meaxic','grunge','falcon','sdrnr'])tracks.push(slug+'-'+variant);
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const ort=require(analysis+'/vendor/ort.wasm.min.js');ort.env.wasm.numThreads=4;ort.env.wasm.wasmPaths=analysis+'/vendor/';
require(analysis+'/dsp.js');require(analysis+'/stem-cache.js');const Reader=require(analysis+'/wav-reader.js'),Vocals=require(analysis+'/vocal.js'),Detail=require(analysis+'/vocal-detail.js'),GAME=require(analysis+'/game.js');
global.location={href:'https://models.invalid/'};
const local=u=>path.join(analysis,new URL(u,location.href).pathname),native=ort.InferenceSession.create.bind(ort.InferenceSession);
const runtime={Tensor:ort.Tensor,InferenceSession:{create:(u,o)=>native(fs.readFileSync(local(u)),o)}};
global.fetch=async u=>({json:async()=>JSON.parse(fs.readFileSync(local(u)))});
async function reader(bytes){const r=new Reader('');r.bytes=async(a,b)=>{r.totalBytes=bytes.length;return Uint8Array.from(bytes.subarray(a,b+1)).buffer;};await r.open();return r;}
const config=JSON.parse(fs.readFileSync(analysis+'/models/features.json'));
async function source(file){const r=await reader(fs.readFileSync(file)),parts=await r.stereo44100(0,r.samples);return parts[0].map((x,i)=>(x+parts[1][i])/2);}
async function half(pcm){const chunks=[Buffer.from(LightForgeStemCache.header(Math.ceil(pcm.length/2)))],stream={write:async b=>chunks.push(Buffer.from(b)),close:async()=>{}};const w=new LightForgeStemCache.DownsampleWriter(stream,config.resampleHalfFIR,pcm.length);for(let i=0;i<pcm.length;i+=8191)await w.push(pcm.subarray(i,i+8191),i);await w.finish();return reader(Buffer.concat(chunks));}
const boundSources=['qa/release-2.2.4/evaluate-roles.cjs','qa/release-2.1.0/role-component-results.json',
 'web/analysis/dsp.js','web/analysis/wav-reader.js','web/analysis/stem-cache.js','web/analysis/vocal.js','web/analysis/vocal-detail.js','web/analysis/game.js','web/analysis/models/features.json','web/analysis/models/game/manifest.json','web/analysis/models/vocal-model.json','web/analysis/models/vocal-frontend.json'];
boundSources.push('web/analysis/models/game/config.json');
const graphPins=JSON.parse(fs.readFileSync(analysis+'/models/game/manifest.json')).files;
function modelHashes(){const result={};for(const [name,pin]of Object.entries(graphPins)){const p=analysis+'/models/game/'+name;assert.equal(fs.statSync(p).size,pin.bytes,'GAME graph size changed');assert.equal(sha(p),pin.sha256,'GAME graph changed');result['web/analysis/models/game/'+name]=pin.sha256;}return result;}
boundSources.push('web/analysis/models/'+JSON.parse(fs.readFileSync(analysis+'/models/vocal-model.json')).file);
for(const name of fs.readdirSync(analysis+'/vendor'))if(name.endsWith('.wasm')||name.endsWith('.mjs')||name==='ort.wasm.min.js')boundSources.push('web/analysis/vendor/'+name);
const sourceHashes=()=>Object.fromEntries(boundSources.map(p=>[p,sha(path.join(root,p))]));
const receipt={release:'2.2.4',passed:false,errors:[],checks:[],source_hashes:sourceHashes(),model_hashes:modelHashes(),threads:4,scope:'Fresh production role inference on the exact archived original-PyTorch source estimates from 18 reference cases. GAME predictions are recomputed. This is not a new full-mixture separation benchmark or human note annotation test; actual current native/WASM separator parity and public pipeline are separate gates.'};
(async()=>{
 if(process.env.LIGHTFORGE_TRANSCRIPTION_CACHE)throw Error('Current release role gate requires fresh neural predictions.');
 const references=JSON.parse(fs.readFileSync(path.join(root,'qa/release-2.1.0/role-component-results.json')));
 const results=[],cached=null;
 if(cached)for(const [p,h]of Object.entries(cached.source_hashes))assert.equal(sha(path.join(root,p)),h,'Cached transcription source changed: '+p);
 for(const track of tracks){
  const voiceFile=path.join(input,track+'-deux-vocals.wav'),backFile=path.join(input,track+'-deux-accompaniment.wav');
  const reference=references.find(r=>r.track===track);assert.ok(reference,'No declared reference estimate for '+track);assert.equal(sha(voiceFile),reference.inputVoiceSHA256);assert.equal(sha(backFile),reference.inputAccompanimentSHA256);
  const pcm=await source(voiceFile),voice=await half(pcm),back=await half(await source(backFile)),start=Date.now();
  const classified=await Vocals.analyze(voice,config,{ort:runtime,includeClassifierScores:true});
  const ex=new Detail.Extractor({sampleRate:22050,duration:pcm.length/44100});
  for(let i=0;i<voice.samples;i+=22050*8){const n=Math.min(22050*8,voice.samples-i);ex.push(await voice.mono22050(i,n,config),i,await back.mono22050(i,n,config));}
  let notes;const prior=cached?.results.find(r=>r.track===track);if(prior){assert.equal(prior.inputVoiceSHA256,sha(voiceFile));notes=prior.detail.transcription;}else{const game=await GAME.create({ort:runtime,baseUrl:'https://models.invalid/models/game/'});notes=await game.process(async(a,n)=>pcm.slice(a,a+n),pcm.length);await game.release();}const detail=GAME.fuse(ex.finish({classifier:classified.classifier,model:classified.model,transcription:notes}),notes);
  const result={track,transcriptionReused:!!prior,inputVoiceSHA256:sha(voiceFile),inputAccompanimentSHA256:sha(backFile),seconds:(Date.now()-start)/1000,phraseCount:detail.phrases.length,noteCount:detail.notes.length,accentCount:detail.accents.length,neuralCandidates:notes.notes.length,detail};results.push(result);
  console.log(track,result.phraseCount,result.noteCount,result.accentCount,result.seconds);fs.writeFileSync(path.join(input,'role-results.json'),JSON.stringify(results));
 }
 const negatives=results.filter(r=>r.track.endsWith('-instrumental')),positives=results.filter(r=>!r.track.endsWith('-instrumental'));
 assert.ok(negatives.every(r=>r.phraseCount===0&&r.noteCount===0&&r.accentCount===0),'Instrument-only input created voice events');assert.ok(positives.every(r=>r.phraseCount>0&&r.noteCount>0),'Reference singing disappeared');
 assert.equal(results.length,18);assert.equal(negatives.length,6);assert.equal(positives.length,12);assert.ok(results.every(r=>r.transcriptionReused===false));
 assert.deepEqual(sourceHashes(),receipt.source_hashes,'Role source changed during verification');assert.deepEqual(modelHashes(),receipt.model_hashes,'Role model changed during verification');
 receipt.results=results;receipt.checks=['All 12 positive estimated-source cases retained phrases and notes.','All six instrumental estimated-source cases produced zero vocal phrases, notes and accents.','All neural predictions are fresh; every estimate is bound to the declared archived reference hash.'];receipt.passed=true;
 fs.writeFileSync(path.join(__dirname,'role-component-results.json'),JSON.stringify(results,null,2)+'\n');
 console.log('PASS:',results.length,'estimated-source role cases');
})().catch(e=>{receipt.errors.push(e.stack);console.error(e);process.exitCode=1;}).finally(()=>{receipt.completedAt=new Date().toISOString();fs.writeFileSync(path.join(__dirname,'role-verification.json'),JSON.stringify(receipt,null,2)+'\n');});

'use strict';
/* Component gate on actual source estimates, never original reference vocals.
 * Arguments: estimate directory, optional track IDs. Uses production Float32
 * downsampler, Frame-MN10, vocal detail and GAME; file transport replaces OPFS.
 * The public worker and OPFS are tested separately in analysis-browser.cjs. */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),analysis=path.join(root,'web/analysis'),input=path.resolve(process.argv[2]),tracks=process.argv.slice(3);
if(!tracks.length)for(const variant of ['mix','instrumental','controlled'])for(const slug of ['nightowl','stella','meaxic','grunge','falcon','sdrnr'])tracks.push(slug+'-'+variant);
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const ort=require(analysis+'/vendor/ort.wasm.min.js');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=analysis+'/vendor/';
require(analysis+'/dsp.js');require(analysis+'/stem-cache.js');const Reader=require(analysis+'/wav-reader.js'),Vocals=require(analysis+'/vocal.js'),Detail=require(analysis+'/vocal-detail.js'),GAME=require(analysis+'/game.js');
global.location={href:'https://models.invalid/'};
const local=u=>path.join(analysis,new URL(u,location.href).pathname),native=ort.InferenceSession.create.bind(ort.InferenceSession);
const runtime={Tensor:ort.Tensor,InferenceSession:{create:(u,o)=>native(fs.readFileSync(local(u)),o)}};
global.fetch=async u=>({json:async()=>JSON.parse(fs.readFileSync(local(u)))});
async function reader(bytes){const r=new Reader('');r.bytes=async(a,b)=>{r.totalBytes=bytes.length;return Uint8Array.from(bytes.subarray(a,b+1)).buffer;};await r.open();return r;}
const config=JSON.parse(fs.readFileSync(analysis+'/models/features.json'));
async function source(file){const r=await reader(fs.readFileSync(file)),parts=await r.stereo44100(0,r.samples);return parts[0].map((x,i)=>(x+parts[1][i])/2);}
async function half(pcm){const chunks=[Buffer.from(LightForgeStemCache.header(Math.ceil(pcm.length/2)))],stream={write:async b=>chunks.push(Buffer.from(b)),close:async()=>{}};const w=new LightForgeStemCache.DownsampleWriter(stream,config.resampleHalfFIR,pcm.length);for(let i=0;i<pcm.length;i+=8191)await w.push(pcm.subarray(i,i+8191),i);await w.finish();return reader(Buffer.concat(chunks));}
(async()=>{
 const results=[];
 for(const track of tracks){
  const voiceFile=path.join(input,track+'-deux-vocals.wav'),backFile=path.join(input,track+'-deux-accompaniment.wav');
  const pcm=await source(voiceFile),voice=await half(pcm),back=await half(await source(backFile)),start=Date.now();
  const classified=await Vocals.analyze(voice,config,{ort:runtime,includeClassifierScores:true});
  const ex=new Detail.Extractor({sampleRate:22050,duration:pcm.length/44100});
  for(let i=0;i<voice.samples;i+=22050*8){const n=Math.min(22050*8,voice.samples-i);ex.push(await voice.mono22050(i,n,config),i,await back.mono22050(i,n,config));}
  let detail=ex.finish({classifier:classified.classifier,model:classified.model});
  const game=await GAME.create({ort:runtime,baseUrl:'https://models.invalid/models/game/'});const notes=await game.process(async(a,n)=>pcm.slice(a,a+n),pcm.length);detail=GAME.fuse(detail,notes);await game.release();
  const result={track,inputVoiceSHA256:sha(voiceFile),inputAccompanimentSHA256:sha(backFile),seconds:(Date.now()-start)/1000,phraseCount:detail.phrases.length,noteCount:detail.notes.length,accentCount:detail.accents.length,neuralCandidates:notes.notes.length,detail};results.push(result);
  console.log(track,result.phraseCount,result.noteCount,result.accentCount,result.seconds);fs.writeFileSync(path.join(input,'role-results.json'),JSON.stringify(results));
 }
 const negatives=results.filter(r=>r.track.endsWith('-instrumental')),positives=results.filter(r=>!r.track.endsWith('-instrumental'));
 assert.ok(negatives.every(r=>r.phraseCount===0&&r.noteCount===0&&r.accentCount===0),'Instrument-only input created voice events');assert.ok(positives.every(r=>r.phraseCount>0&&r.noteCount>0),'Reference singing disappeared');
 console.log('PASS:',results.length,'estimated-source role cases');
})().catch(e=>{console.error(e);process.exitCode=1;});

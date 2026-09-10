'use strict';
/* Bundled browser ONNX Runtime Web, running its actual CPU WASM engine under
 * Node. Production WAV decoding, MDX frontend and waveform decoder are used. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),work=path.resolve(process.argv[3]),phase=process.argv[2];
require(root+'/web/analysis/dsp.js');
const M=require(root+'/web/analysis/separator-mdx.js'),Wav=require(root+'/web/analysis/wav-reader.js');
const write=(name,x)=>fs.writeFileSync(path.join(work,name+'.float32le'),Buffer.from(x.buffer,x.byteOffset,x.byteLength));
const read=name=>{const b=fs.readFileSync(path.join(work,name+'.float32le'));assert.equal(b.byteLength,4*4*3072*256);return new Float32Array(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength));};
(async()=>{
 assert.equal(require('os').endianness(),'LE');
 if(phase==='prepare'){
  const b=fs.readFileSync(path.join(root,process.argv[5])),wav=new Wav('host://source');wav.cached=b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);wav.totalBytes=b.length;await wav.open();
  assert.ok(['web/demo/glass-castle.wav','qa/release-1.6.0/fixtures/falcon-mix.wav'].includes(process.argv[5]));assert.ok(Number.isSafeInteger(Number(process.argv[4])));const frontend=new M.Frontend(),input=frontend.encode(await wav.stereo44100(Number(process.argv[4]),M.constants.INPUT_LENGTH));write('input-positive',input);
  const negative=input.map(x=>-x);write('input-negative',negative);return;
 }
 if(phase==='wasm'){
  const ort=require(root+'/web/analysis/vendor/ort.wasm.min.js');ort.env.wasm.numThreads=4;ort.env.wasm.proxy=false;ort.env.wasm.wasmPaths=root+'/web/analysis/vendor/';
  const session=await ort.InferenceSession.create(fs.readFileSync(root+'/web/analysis/models/uvr-mdx-voc-ft.onnx'),{executionProviders:['wasm'],enableCpuMemArena:false,enableMemPattern:false,graphOptimizationLevel:'all'});
  try{for(const polarity of ['positive','negative']){const x=new ort.Tensor('float32',read('input-'+polarity),[1,4,3072,256]),at=performance.now();let result;try{result=await session.run({[session.inputNames[0]]:x});write('wasm-'+polarity,result[session.outputNames[0]].data);console.log(JSON.stringify({polarity,seconds:(performance.now()-at)/1000,runtime:ort.env.versions.web,executionProvider:'wasm',threads:4}));}finally{x.dispose();if(result)for(const y of Object.values(result))y.dispose();}}}finally{await session.release();}
  return;
 }
 assert.equal(phase,'decode');const manifest=JSON.parse(fs.readFileSync(root+'/web/analysis/models/separator-mdx-model.json')),frontend=new M.Frontend();
 for(const runtime of ['native','wasm']){const p=read(runtime+'-positive'),n=read(runtime+'-negative');for(let i=0;i<p.length;i++)p[i]=(p[i]-n[i])*.5;write(runtime+'-waveform',frontend.decode(p,manifest.compensate));}
})().catch(e=>{console.error(e);process.exitCode=1;});

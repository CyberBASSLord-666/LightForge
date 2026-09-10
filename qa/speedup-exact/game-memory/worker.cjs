'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{fileURLToPath,pathToFileURL}=require('node:url');
const ROOT='/workspace/scratch/9a5ec23b7f4b/LightForge',OUT=__dirname;
const sha=b=>crypto.createHash('sha256').update(b).digest('hex'),bytes=t=>Buffer.from(t.data.buffer,t.data.byteOffset,t.data.byteLength),digestTensor=t=>({type:t.type,dims:t.dims,sha256:sha(bytes(t))});
const ids=process.argv.slice(2),mode=process.env.GAME_POOL_MODE||'serial';let active,graphs=[],records=[];
const snapshot=()=>({rss:process.memoryUsage().rss,maxRss:process.resourceUsage().maxRSS*1024});
function emit(type,data={}){const r={type,...data,...snapshot()};records.push(r);console.log(JSON.stringify(r));}
async function main(){
 const manifest=JSON.parse(fs.readFileSync(path.join(OUT,'inputs.json'))),GAME=require(ROOT+'/web/analysis/game.js');
 global.location={href:pathToFileURL(ROOT+'/web/analysis/worker.js').href};global.fetch=async input=>new Response(fs.readFileSync(fileURLToPath(new URL(String(input),global.location.href))));
 const raw=require(ROOT+'/web/analysis/vendor/ort.wasm.min.js');raw.env.wasm.numThreads=1;raw.env.wasm.proxy=false;raw.env.wasm.wasmPaths=ROOT+'/web/analysis/vendor/';
 const ort={Tensor:raw.Tensor,env:raw.env,InferenceSession:{async create(source,options){const p=fileURLToPath(source),name=path.basename(p).replace('.onnx',''),model=fs.readFileSync(p),at=performance.now(),session=await raw.InferenceSession.create(model,options);emit('load',{name,seconds:(performance.now()-at)/1000,modelSha256:sha(model)});return{async run(feeds){const feedHashes=Object.fromEntries(Object.entries(feeds).map(([k,t])=>[k,digestTensor(t)])),at=performance.now(),outputs=await session.run(feeds),seconds=(performance.now()-at)/1000;graphs.push({name,seconds,feeds:feedHashes,outputs:Object.fromEntries(Object.entries(outputs).map(([k,t])=>[k,digestTensor(t)]))});emit('graph',{id:active,name,seconds});return outputs;},async release(){await session.release();}};}}};
 const game=await GAME.create({ort,baseUrl:pathToFileURL(ROOT+'/web/analysis/models/game/').href}),results=[];
 try{for(const id of ids){const spec=manifest.fixtures.find(x=>x.id===id);if(!spec)throw Error('Unknown fixture');const rawPcm=fs.readFileSync(path.join(OUT,spec.file));if(sha(rawPcm)!==spec.sha256)throw Error('Fixture changed');const pcm=new Float32Array(rawPcm.buffer.slice(rawPcm.byteOffset,rawPcm.byteOffset+rawPcm.byteLength));active=id;graphs=[];const start=performance.now();emit('begin',{id});const notes=await game.infer(pcm,0,spec.seed);const result={id,seed:spec.seed,pcmSha256:spec.sha256,notes,graphs,elapsedSeconds:(performance.now()-start)/1000,...snapshot()};results.push(result);emit('passage',{id,seconds:result.elapsedSeconds,notes:notes.length});}}
 finally{await game.release();}
 const output={mode,ids,runtime:raw.env.versions.web,threads:raw.env.wasm.numThreads,results,records,...snapshot()};fs.writeFileSync(path.join(OUT,`${mode}-${ids.join('-')}.json`),JSON.stringify(output,null,2)+'\n');emit('complete',{file:`${mode}-${ids.join('-')}.json`});
}
main().catch(error=>{console.error(error);process.exitCode=1;});

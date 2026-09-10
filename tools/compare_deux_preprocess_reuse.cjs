#!/usr/bin/env node
'use strict';
/* Paired, actual-model gate for the experimental adjacent-passage STFT reuse.
 * It is deliberately separate from release verification: the candidate stays
 * disabled by default until this gate is repeated on controlled hardware.
 *
 * `--evidence-mode resumable-exactness --state-dir …` persists only whole,
 * completed arms. It is an output-equivalence/recovery proof, never timing
 * evidence: resumed state intentionally makes performance acceptance false. */
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),args=process.argv.slice(2),options={};
for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||args[i+1]===undefined)throw Error('Expected --option value');options[args[i].slice(2)]=args[i+1];}
const resolve=(value,fallback)=>path.resolve(value||fallback);
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const shaFile=file=>sha(fs.readFileSync(file));
const parseOnOff=(name,fallback='off')=>{const value=options[name]||fallback;if(!['on','off'].includes(value))throw Error('--'+name+' must be on or off');return value==='on';};
const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'?'{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
const stable=canonical;
function compareBytes(left,right){
 if(left.length!==right.length)return {byteIdentical:false,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:null};
 if(left.equals(right))return {byteIdentical:true,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:null};
 let first=0;while(first<left.length&&left[first]===right[first])first++;
 return {byteIdentical:false,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:first,leftByte:left[first],rightByte:right[first]};
}
function required(condition,message){if(!condition)throw Error(message);}
function readJson(file,label='JSON receipt'){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch(error){throw Error(label+' is unreadable: '+file+' ('+error.message+')');}}
function syncFile(file){const descriptor=fs.openSync(file,'r');try{fs.fsyncSync(descriptor);}finally{fs.closeSync(descriptor);}}
function syncDirectory(directory){const descriptor=fs.openSync(directory,'r');try{fs.fsyncSync(descriptor);}finally{fs.closeSync(descriptor);}}
function writeJsonAtomic(file,value){
 const directory=path.dirname(file);fs.mkdirSync(directory,{recursive:true});
 const temporary=path.join(directory,'.'+path.basename(file)+'.'+process.pid+'.'+crypto.randomBytes(8).toString('hex')+'.tmp');
 try{const descriptor=fs.openSync(temporary,'w');try{fs.writeFileSync(descriptor,JSON.stringify(value,null,2)+'\n');fs.fsyncSync(descriptor);}finally{fs.closeSync(descriptor);}fs.renameSync(temporary,file);syncDirectory(directory);}finally{if(fs.existsSync(temporary))fs.rmSync(temporary,{force:true});}
}
function stateChild(stateRoot,...parts){
 const target=path.resolve(stateRoot,...parts),relative=path.relative(stateRoot,target);
 required(relative!==''&&!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative),'Evidence state target escaped its root.');
 return target;
}
function fileIdentity(file,label='file'){
 required(fs.existsSync(file),label+' is missing: '+file);
 const stat=fs.statSync(file);required(stat.isFile(),label+' is not a file: '+file);
 return {bytes:stat.size,sha256:shaFile(file)};
}
function exactPcm(left,right){
 const result={};
 for(const role of ['vocals','accompaniment'])result[role]=compareBytes(fs.readFileSync(left.pcmPrefix+'-'+role+'.f32'),fs.readFileSync(right.pcmPrefix+'-'+role+'.f32'));
 return result;
}
function pcmIdentity(prefix,samples){
 const result={};
 for(const role of ['vocals','accompaniment']){
  const file=prefix+'-'+role+'.f32',identity=fileIdentity(file,role+' PCM');
  required(identity.bytes===samples*4,role+' PCM byte length does not match the exact Float32 sample count.');
  result[role]={file:path.basename(file),...identity};
 }
 return result;
}
function validateReport(report,{enabled,minPassages,recovery=false}){
 required(report?.passed===true,'Benchmark report did not pass.');
 required(report?.result?.chunks>=minPassages,'Benchmark did not exercise '+minPassages+' passages.');
 required(report?.samples%2===1,'Benchmark did not retain the required odd final source length.');
 required(report?.mode?.spectrumReuse?.enabled===enabled,'Benchmark mode did not bind the requested spectrum reuse state.');
 required(report?.mode?.coldProcess===true,'Benchmark did not use a fresh process.');
 required(report?.mode?.filesystemCache?.state==='uncontrolled'&&report.mode.filesystemCache.strictColdIo===false,'Benchmark must not relabel an uncontrolled filesystem cache as strict cold I/O.');
 required(report?.mode?.thermalState?.available===false,'Benchmark must explicitly mark thermal state unavailable.');
 required(report?.result?.preprocessing?.spectrumReuse?.enabled===enabled,'Separator receipt did not bind the requested spectrum reuse state.');
 required(report?.performanceProfile?.resources?.cpuTimeMs?.available===false,'Profiler must explicitly mark unavailable CPU time.');
 required(report?.runtime?.sessionConfiguration?.executionProviders?.length===1&&report.runtime.sessionConfiguration.executionProviders[0]==='wasm'&&report.runtime.sessionConfiguration.graphOptimizationLevel==='all'&&report.runtime.sessionConfiguration.enableCpuMemArena===false&&report.runtime.sessionConfiguration.enableMemPattern===false,'Benchmark did not bind the production WASM session configuration.');
 if(enabled)required(Number(report?.performanceProfile?.counters?.['transform.frames.reused']||0)>0,'Enabled candidate did not reuse any exact interior STFT frames.');
 else required(Number(report?.performanceProfile?.counters?.['transform.frames.reused']||0)===0,'Disabled baseline unexpectedly reused STFT frames.');
 if(recovery){required(report?.recovery?.controlledInterruption===true,'Recovery run did not record its controlled interruption.');required(report?.recovery?.restoredPassages>=1,'Recovery run did not restore a checkpoint.');}
}
function sameBinding(left,right){
 return left.sourceSHA256===right.sourceSHA256&&left.fixtureSHA256===right.fixtureSHA256&&stable(left.fixtureProvenance)===stable(right.fixtureProvenance)&&left.manifestSHA256===right.manifestSHA256&&left.model?.checkpointSHA256===right.model?.checkpointSHA256&&left.threads===right.threads&&left.samples===right.samples&&stable(left.source_hashes)===stable(right.source_hashes)&&left.runtime?.ortWebVersion===right.runtime?.ortWebVersion&&stable(left.runtime?.sessionConfiguration)===stable(right.runtime?.sessionConfiguration);
}
function checkoutBinding(file,implementation,assetManifest){
 if(!file)return null;
 const receipt=readJson(file,'Checkout identity receipt'),implementationPath=path.relative(root,implementation),assetPath=path.relative(root,assetManifest);
 required(receipt?.schema==='lightforge.deux-checkout-identities.v1','Checkout identity receipt has an unexpected schema.');
 required(/^[0-9a-f]{40}$/i.test(receipt.commit||'')&&/^[0-9a-f]{40}$/i.test(receipt.tree||''),'Checkout identity receipt must bind an exact commit and tree.');
 required(receipt.files?.[implementationPath]?.sha256===shaFile(implementation),'Checkout identity receipt does not bind the implementation bytes.');
 required(receipt.files?.[assetPath]?.sha256===shaFile(assetManifest),'Checkout identity receipt does not bind the analysis asset manifest bytes.');
 return {sha256:shaFile(file),commit:receipt.commit,tree:receipt.tree,implementation:{gitBlobSha1:receipt.files[implementationPath].gitBlobSha1,sha256:receipt.files[implementationPath].sha256},assetManifest:{gitBlobSha1:receipt.files[assetPath].gitBlobSha1,sha256:receipt.files[assetPath].sha256}};
}
function assetInventoryBinding(file,assetManifest){
 if(!file)return null;
 const receipt=readJson(file,'Deux asset inventory receipt'),manifestSha256=shaFile(assetManifest);
 required(receipt?.schema==='lightforge.analysis-asset-manifest.v1'&&receipt.scope==='deux','Asset inventory receipt must be the scoped Deux manifest verification.');
 required(receipt?.upToDate===true&&receipt?.graphInventory?.matches===true&&receipt.graphInventory.requiredGraphCount===27&&receipt.graphInventory.manifestGraphCount===27&&receipt.graphInventory.actualGraphCount===27&&receipt.graphInventory.boundGraphCount===27,'Asset inventory receipt does not prove all 27 shipped Deux graphs.');
 required(receipt.generatedManifestSha256===manifestSha256&&receipt.actualManifestSha256===manifestSha256,'Asset inventory receipt does not bind the committed analysis manifest bytes.');
 return {sha256:shaFile(file),generatedManifestSha256:receipt.generatedManifestSha256,graphInventory:receipt.graphInventory,assetCount:receipt.assetCount,allowedAssetPaths:receipt.allowedAssetPaths};
}
function makeEvidenceBinding({benchmark,implementation,models,fixture,fixtureProvenance,threads,total,minPassages,verifyRecovery,checkoutIdentities,assetInventory}){
 const analysisRoot=path.resolve(models,'../..'),assetManifest=path.join(analysisRoot,'ASSET_MANIFEST.json'),modelManifest=path.join(models,'manifest.json');
 required(fs.existsSync(modelManifest),'Deux model manifest is missing: '+modelManifest);
 required(fs.existsSync(assetManifest),'Analysis asset manifest is missing: '+assetManifest);
 const checkout=checkoutBinding(checkoutIdentities,implementation,assetManifest),inventory=assetInventoryBinding(assetInventory,assetManifest);
 required(checkout,'Resumable exactness evidence requires --checkout-identities.');
 required(inventory,'Resumable exactness evidence requires --asset-inventory.');
 return {schema:'lightforge.deux-preprocess-evidence-binding.v1',comparatorSHA256:shaFile(__filename),benchmarkSHA256:shaFile(benchmark),implementationSHA256:shaFile(implementation),modelManifestSHA256:shaFile(modelManifest),analysisAssetManifestSHA256:shaFile(assetManifest),fixtureSHA256:shaFile(fixture),fixtureProvenanceSHA256:fixtureProvenance?shaFile(fixtureProvenance):null,invocation:{threads,total,minPassages,verifyRecovery},checkout,assetInventory:inventory};
}
function assertReportMatchesEvidence(report,binding,implementation){
 required(report.sourceSHA256===binding.implementationSHA256,'Stored arm implementation binding differs from the current evidence binding.');
 required(report.manifestSHA256===binding.modelManifestSHA256,'Stored arm model manifest differs from the current evidence binding.');
 required(report.fixtureSHA256===binding.fixtureSHA256,'Stored arm fixture differs from the current evidence binding.');
 required((report.fixtureProvenance?.sha256||null)===binding.fixtureProvenanceSHA256,'Stored arm fixture provenance differs from the current evidence binding.');
 required(report.threads===binding.invocation.threads&&report.samples===binding.invocation.total,'Stored arm invocation geometry differs from the current evidence binding.');
 required(report.source_hashes?.[path.relative(root,implementation)]===binding.implementationSHA256,'Stored arm does not bind the implementation source hash.');
 required(report.source_hashes?.['tools/benchmark_deux_runtime.cjs']===binding.benchmarkSHA256,'Stored arm does not bind the benchmark runner hash.');
}
function createEvidenceState(directory,binding){
 const rootDir=path.resolve(directory),bindingSha256=sha(Buffer.from(canonical(binding))),bindingFile=stateChild(rootDir,'binding.json');
 fs.mkdirSync(rootDir,{recursive:true});
 if(fs.existsSync(bindingFile)){
  const stored=readJson(bindingFile,'Evidence state binding');
  required(stored?.schema==='lightforge.deux-preprocess-evidence-state.v1'&&stored.bindingSha256===bindingSha256&&canonical(stored.binding)===canonical(binding),'Existing evidence state does not exactly match this source/model/fixture/invocation binding.');
 }else writeJsonAtomic(bindingFile,{schema:'lightforge.deux-preprocess-evidence-state.v1',bindingSha256,binding});
 function armDirectory(name){return stateChild(rootDir,'arms',name);}
 function load(name,{enabled,minPassages,recovery,recoveryAfter,implementation}){
  const armDir=armDirectory(name),done=stateChild(rootDir,'arms',name,'complete.json');
  if(!fs.existsSync(done)){
   required(!fs.existsSync(armDir),'Evidence arm '+name+' is incomplete; refusing to use an uncommitted artifact.');
   return null;
  }
  const record=readJson(done,'Evidence arm completion record');
  required(record?.schema==='lightforge.deux-preprocess-evidence-arm.v1'&&record.name===name&&record.bindingSha256===bindingSha256,'Evidence arm '+name+' does not bind this exact state.');
  required(record?.configuration?.spectrumReuse===enabled&&record.configuration.recoveryAfter===recoveryAfter,'Evidence arm '+name+' was created with a different experimental mode or recovery point.');
  const reportFile=stateChild(rootDir,'arms',name,'report.json'),reportIdentity=fileIdentity(reportFile,'Evidence arm report');
  required(reportIdentity.bytes===record.report?.bytes&&reportIdentity.sha256===record.report?.sha256,'Evidence arm '+name+' report hash changed after completion.');
  const report=readJson(reportFile,'Evidence arm report');validateReport(report,{enabled,minPassages,recovery});assertReportMatchesEvidence(report,binding,implementation);
  const pcmPrefix=stateChild(rootDir,'arms',name,'pcm'),pcm=pcmIdentity(pcmPrefix,report.samples);
  for(const role of ['vocals','accompaniment'])required(pcm[role].bytes===record.pcm?.[role]?.bytes&&pcm[role].sha256===record.pcm?.[role]?.sha256,'Evidence arm '+name+' '+role+' PCM changed after completion.');
  return {report,pcmPrefix,resumed:true,completion:record};
 }
 function stage(name){
  const token='.pending-'+name+'-'+process.pid+'-'+crypto.randomBytes(8).toString('hex'),directory=stateChild(rootDir,token);fs.mkdirSync(directory,{recursive:false});return directory;
 }
 function commit(name,staging,{enabled,recoveryAfter,report,implementation}){
 const target=armDirectory(name);required(!fs.existsSync(target),'Evidence arm '+name+' already exists; refusing to overwrite a completed or incomplete artifact.');
  const reportFile=path.join(staging,'report.json'),reportIdentity=fileIdentity(reportFile,'New evidence arm report'),pcmPrefix=path.join(staging,'pcm'),pcm=pcmIdentity(pcmPrefix,report.samples);
  assertReportMatchesEvidence(report,binding,implementation);
  syncFile(reportFile);for(const role of ['vocals','accompaniment'])syncFile(pcmPrefix+'-'+role+'.f32');
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.renameSync(staging,target);syncDirectory(path.dirname(target));
  const record={schema:'lightforge.deux-preprocess-evidence-arm.v1',name,bindingSha256,configuration:{spectrumReuse:enabled,recoveryAfter},report:{file:'report.json',...reportIdentity},pcm};
  writeJsonAtomic(path.join(target,'complete.json'),record);
  return {report,pcmPrefix:path.join(target,'pcm'),resumed:false,completion:record};
 }
 return {root:rootDir,binding,bindingSha256,load,stage,commit};
}
function main(){
 const benchmark=resolve(options.benchmark,root+'/tools/benchmark_deux_runtime.cjs');
 const implementation=resolve(options.implementation,root+'/web/analysis/separator-deux.js');
 const models=resolve(options.models,root+'/web/analysis/models/deux');
 const fixture=resolve(options.fixture,root+'/qa/release-1.6.0/fixtures/falcon-mix.wav');
 const fixtureProvenance=options['fixture-provenance']?resolve(options['fixture-provenance']):null;
 const output=resolve(options.output,root+'/build/deux-preprocess-comparison.json');
 const threads=Number(options.threads||4),total=Number(options['total-samples']),verifyRecovery=parseOnOff('verify-recovery'),minPassages=Number(options['min-passages']||(verifyRecovery?3:2));
 const evidenceMode=options['evidence-mode']||'none',stateDirectory=options['state-dir']?resolve(options['state-dir']):null;
 if(!Number.isInteger(threads)||threads<1||threads>8)throw Error('Invalid --threads');
 if(!Number.isSafeInteger(total)||total<1||total%2!==1)throw Error('--total-samples must be an odd positive integer so the final passage is not an even-length special case');
 if(!Number.isSafeInteger(minPassages)||minPassages<(verifyRecovery?3:2))throw Error('--min-passages must be at least '+(verifyRecovery?'three for recovery':'two'));
 if(!['none','resumable-exactness'].includes(evidenceMode))throw Error('--evidence-mode must be none or resumable-exactness');
 if((evidenceMode==='resumable-exactness')!==!!stateDirectory)throw Error('Resumable exactness evidence requires both --evidence-mode resumable-exactness and --state-dir.');
 const keepTemp=parseOnOff('keep-temp'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-deux-preprocess-'));
 let state=null;
 if(stateDirectory)state=createEvidenceState(stateDirectory,makeEvidenceBinding({benchmark,implementation,models,fixture,fixtureProvenance,threads,total,minPassages,verifyRecovery,checkoutIdentities:options['checkout-identities']?resolve(options['checkout-identities']):null,assetInventory:options['asset-inventory']?resolve(options['asset-inventory']):null}));
 const receipt={schema:2,passed:false,errors:[],criterion:{fullPrecisionModels:true,unchangedContextOverlapAndGraphs:true,requiredByteIdentity:true,requiredFiniteOutputs:true,requiredOddLength:true,minimumPassages:minPassages,recoveryRequested:verifyRecovery},measurement:{scope:state?'Resumable whole-arm exactness evidence. Completed arms may be reused only after source/model/fixture/hash revalidation; this receipt intentionally makes no timing claim.':'One parent process launches a fresh Node process per arm. Kernel file-cache and thermal state remain uncontrolled.',freshProcessPerArm:true,strictColdIo:false,filesystemCacheState:'uncontrolled',thermalState:'unavailable',resumedArms:[]},bindings:{implementationSHA256:shaFile(implementation),fixtureSHA256:shaFile(fixture),fixtureProvenanceSHA256:fixtureProvenance?shaFile(fixtureProvenance):null,modelsPath:path.relative(root,models),...(state?{evidenceState:{bindingSha256:state.bindingSha256,checkout:state.binding.checkout,assetInventory:state.binding.assetInventory}}:{})},...(state?{resumableEvidence:{schema:'lightforge.deux-preprocess-resumable-receipt.v1',bindingSha256:state.bindingSha256,arms:{}}}:{}),runs:{},comparison:{}};
 const invoke=(name,reuse,recoveryAfter=0,staging=null)=>{
  const reportPath=staging?path.join(staging,'report.json'):path.join(temp,name+'.json'),pcmPrefix=staging?path.join(staging,'pcm'):path.join(temp,name),argv=[benchmark,'--implementation',implementation,'--models',models,'--fixture',fixture,'--threads',String(threads),'--total-samples',String(total),'--spectrum-reuse',reuse,'--output',reportPath,'--pcm',pcmPrefix];
  if(fixtureProvenance)argv.push('--fixture-provenance',fixtureProvenance);
  if(recoveryAfter)argv.push('--recover-after-chunks',String(recoveryAfter));
  const child=spawnSync(process.execPath,argv,{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024});
  if(child.error)throw child.error;
  if(child.status!==0)throw Error(name+' benchmark failed (exit '+String(child.status)+'): '+String(child.stderr||child.stdout).slice(-4000));
  return {report:readJson(reportPath,name+' benchmark report'),pcmPrefix};
 };
 const runArm=(name,reuse,recoveryAfter=0)=>{
  const enabled=reuse==='on',recovery=recoveryAfter>0,restored=state?.load(name,{enabled,minPassages,recovery,recoveryAfter,implementation});
  if(restored){receipt.measurement.resumedArms.push(name);return restored;}
  const staging=state?.stage(name);
  try{
   const result=invoke(name,reuse,recoveryAfter,staging);validateReport(result.report,{enabled,minPassages,recovery});
   return state?state.commit(name,staging,{enabled,recoveryAfter,report:result.report,implementation}):result;
  }catch(error){if(staging&&fs.existsSync(staging))fs.rmSync(staging,{recursive:true,force:true});throw error;}
 };
 try{
  const baseline=runArm('cold-baseline','off'),candidate=runArm('cold-candidate','on');
  if(state){receipt.resumableEvidence.arms['cold-baseline']=baseline.completion;receipt.resumableEvidence.arms['cold-candidate']=candidate.completion;}
  required(sameBinding(baseline.report,candidate.report),'Baseline and candidate did not retain identical source, model, fixture, thread and sample bindings.');
  const baselineCandidate=exactPcm(baseline,candidate);
  required(Object.values(baselineCandidate).every(value=>value.byteIdentical),'Experimental STFT reuse changed final PCM bytes.');
  receipt.runs.baseline=baseline.report;receipt.runs.candidate=candidate.report;receipt.comparison.baselineVsCandidate=baselineCandidate;
  receipt.observedWallClockReductionPercent=state?null:baseline.report.seconds?100*(baseline.report.seconds-candidate.report.seconds)/baseline.report.seconds:null;
  receipt.performanceAcceptance={accepted:false,reason:state?'Resumable exactness evidence verifies complete-arm Float32 identity and recovery only; it intentionally records no paired timing result.':'One fresh-process pair with uncontrolled filesystem-cache and thermal state is diagnostic evidence only; repeat under the locked corpus, equivalent controlled conditions and quality gate before enabling the candidate.'};
  if(verifyRecovery){
   const recovered=runArm('warm-recovery','on',1);
   if(state)receipt.resumableEvidence.arms['warm-recovery']=recovered.completion;
   required(sameBinding(candidate.report,recovered.report),'Recovery run did not retain the candidate source/model/input bindings.');
   const candidateRecovery=exactPcm(candidate,recovered);
   required(Object.values(candidateRecovery).every(value=>value.byteIdentical),'Controlled cancellation/recovery changed final PCM bytes.');
   receipt.runs.recovery=recovered.report;receipt.comparison.candidateVsRecovery=candidateRecovery;
  }
  receipt.passed=true;
 }catch(error){receipt.errors.push(error.stack||String(error));}
 finally{
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n');
  if(!keepTemp)fs.rmSync(temp,{recursive:true,force:true});
 }
 process.stdout.write(JSON.stringify(receipt,null,2)+'\n');if(!receipt.passed)process.exitCode=1;
}
if(require.main===module)main();
module.exports={compareBytes,validateReport,sameBinding,canonical,createEvidenceState,assertReportMatchesEvidence};

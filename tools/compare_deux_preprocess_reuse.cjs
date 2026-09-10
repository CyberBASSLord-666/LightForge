#!/usr/bin/env node
'use strict';
/* Paired, actual-model gate for the experimental adjacent-passage STFT reuse.
 * It is deliberately separate from release verification: the candidate stays
 * disabled by default until this gate is repeated on controlled hardware. */
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),args=process.argv.slice(2),options={};
for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||args[i+1]===undefined)throw Error('Expected --option value');options[args[i].slice(2)]=args[i+1];}
const resolve=(value,fallback)=>path.resolve(value||fallback);
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const parseOnOff=(name,fallback='off')=>{const value=options[name]||fallback;if(!['on','off'].includes(value))throw Error('--'+name+' must be on or off');return value==='on';};
function compareBytes(left,right){
 if(left.length!==right.length)return {byteIdentical:false,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:null};
 if(left.equals(right))return {byteIdentical:true,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:null};
 let first=0;while(first<left.length&&left[first]===right[first])first++;
 return {byteIdentical:false,byteLengthLeft:left.length,byteLengthRight:right.length,firstDifferentByte:first,leftByte:left[first],rightByte:right[first]};
}
function required(condition,message){if(!condition)throw Error(message);}
function exactPcm(left,right){
 const result={};
 for(const role of ['vocals','accompaniment'])result[role]=compareBytes(fs.readFileSync(left.pcmPrefix+'-'+role+'.f32'),fs.readFileSync(right.pcmPrefix+'-'+role+'.f32'));
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
function stable(value){return JSON.stringify(value,Object.keys(value||{}).sort());}
function sameBinding(left,right){
 return left.sourceSHA256===right.sourceSHA256&&left.fixtureSHA256===right.fixtureSHA256&&stable(left.fixtureProvenance)===stable(right.fixtureProvenance)&&left.manifestSHA256===right.manifestSHA256&&left.model?.checkpointSHA256===right.model?.checkpointSHA256&&left.threads===right.threads&&left.samples===right.samples&&stable(left.source_hashes)===stable(right.source_hashes)&&left.runtime?.ortWebVersion===right.runtime?.ortWebVersion&&stable(left.runtime?.sessionConfiguration)===stable(right.runtime?.sessionConfiguration);
}
function main(){
 const benchmark=resolve(options.benchmark,root+'/tools/benchmark_deux_runtime.cjs');
 const implementation=resolve(options.implementation,root+'/web/analysis/separator-deux.js');
 const models=resolve(options.models,root+'/web/analysis/models/deux');
 const fixture=resolve(options.fixture,root+'/qa/release-1.6.0/fixtures/falcon-mix.wav');
 const fixtureProvenance=options['fixture-provenance']?resolve(options['fixture-provenance']):null;
 const output=resolve(options.output,root+'/build/deux-preprocess-comparison.json');
 const threads=Number(options.threads||4),total=Number(options['total-samples']),verifyRecovery=parseOnOff('verify-recovery'),minPassages=Number(options['min-passages']||(verifyRecovery?3:2));
 if(!Number.isInteger(threads)||threads<1||threads>8)throw Error('Invalid --threads');
 if(!Number.isSafeInteger(total)||total<1||total%2!==1)throw Error('--total-samples must be an odd positive integer so the final passage is not an even-length special case');
 if(!Number.isSafeInteger(minPassages)||minPassages<(verifyRecovery?3:2))throw Error('--min-passages must be at least '+(verifyRecovery?'three for recovery':'two'));
 const keepTemp=parseOnOff('keep-temp'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-deux-preprocess-'));
 const receipt={schema:1,passed:false,errors:[],criterion:{fullPrecisionModels:true,unchangedContextOverlapAndGraphs:true,requiredByteIdentity:true,requiredFiniteOutputs:true,requiredOddLength:true,minimumPassages:minPassages,recoveryRequested:verifyRecovery},measurement:{scope:'One parent process launches a fresh Node process per arm. Kernel file-cache and thermal state remain uncontrolled.',freshProcessPerArm:true,strictColdIo:false,filesystemCacheState:'uncontrolled',thermalState:'unavailable'},bindings:{implementationSHA256:sha(fs.readFileSync(implementation)),fixtureSHA256:sha(fs.readFileSync(fixture)),fixtureProvenanceSHA256:fixtureProvenance?sha(fs.readFileSync(fixtureProvenance)):null,modelsPath:path.relative(root,models)},runs:{},comparison:{}};
 const invoke=(name,reuse,recoveryAfter=0)=>{
  const reportPath=path.join(temp,name+'.json'),pcmPrefix=path.join(temp,name),argv=[benchmark,'--implementation',implementation,'--models',models,'--fixture',fixture,'--threads',String(threads),'--total-samples',String(total),'--spectrum-reuse',reuse,'--output',reportPath,'--pcm',pcmPrefix];
  if(fixtureProvenance)argv.push('--fixture-provenance',fixtureProvenance);
  if(recoveryAfter)argv.push('--recover-after-chunks',String(recoveryAfter));
  const child=spawnSync(process.execPath,argv,{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024});
  if(child.error)throw child.error;
  if(child.status!==0)throw Error(name+' benchmark failed (exit '+String(child.status)+'): '+String(child.stderr||child.stdout).slice(-4000));
  const report=JSON.parse(fs.readFileSync(reportPath,'utf8'));
  return {report,pcmPrefix};
 };
 try{
  const baseline=invoke('cold-baseline','off'),candidate=invoke('cold-candidate','on');
  validateReport(baseline.report,{enabled:false,minPassages});
  validateReport(candidate.report,{enabled:true,minPassages});
  required(sameBinding(baseline.report,candidate.report),'Baseline and candidate did not retain identical source, model, fixture, thread and sample bindings.');
  const baselineCandidate=exactPcm(baseline,candidate);
  required(Object.values(baselineCandidate).every(value=>value.byteIdentical),'Experimental STFT reuse changed final PCM bytes.');
  receipt.runs.baseline=baseline.report;receipt.runs.candidate=candidate.report;receipt.comparison.baselineVsCandidate=baselineCandidate;
  // Both runs use separate Node processes. Kernel file-cache and thermal state
  // remain uncontrolled; one pair never constitutes performance acceptance.
  receipt.observedWallClockReductionPercent=baseline.report.seconds?100*(baseline.report.seconds-candidate.report.seconds)/baseline.report.seconds:null;
  receipt.performanceAcceptance={accepted:false,reason:'One fresh-process pair with uncontrolled filesystem-cache and thermal state is diagnostic evidence only; repeat under the locked corpus, equivalent controlled conditions and quality gate before enabling the candidate.'};
  if(verifyRecovery){
   const recovered=invoke('warm-recovery','on',1);
   validateReport(recovered.report,{enabled:true,minPassages,recovery:true});
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
module.exports={compareBytes,validateReport,sameBinding};

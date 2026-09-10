/* Typed, provenance-aware stem routing. This module never performs separation,
 * never upgrades a mixture into an isolated stem, and never mutates analysis. */
(function(root){'use strict';
 const SCHEMA_VERSION=1,CLOCK='original-decoded-audio',LEGACY_CACHE_KEY=/^stem-[a-f0-9-]{36}$/;
 const ROLES=new Set(['combined-vocals','accompaniment','lead-vocals','backing-vocals','drums','bass','harmonic']);
 const EXTERNAL_ROLES=new Set(['lead-vocals','backing-vocals','drums','bass','harmonic']);
 const TASKS={
  'vocal-transcription':[{roles:['lead-vocals'],kind:'preferred'},{roles:['combined-vocals'],kind:'legacy-vocal-mixture'}],
  'vocal-activity':[{roles:['lead-vocals'],kind:'preferred'},{roles:['combined-vocals'],kind:'legacy-vocal-mixture'},{roles:['backing-vocals'],kind:'backing-only'}],
  'backing-vocal-analysis':[{roles:['backing-vocals'],kind:'preferred'}],
  'drum-analysis':[{roles:['drums'],kind:'supplied-semantic-stem'}],
  'bass-analysis':[{roles:['bass'],kind:'preferred'},{roles:['accompaniment'],kind:'fallback-accompaniment-mixture'}],
  'harmonic-analysis':[{roles:['harmonic'],kind:'preferred'},{roles:['accompaniment'],kind:'fallback-accompaniment-mixture'}]
 };
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const text=value=>typeof value==='string'&&value.trim()?value.trim():null;
 const object=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
 const clone=value=>JSON.parse(JSON.stringify(value));
 const compareText=(left,right)=>left===right?0:(left<right?-1:1);
 function confidence(value){
  if(value===undefined||value===null)return {valid:true,value:null};
  return finite(value)&&value>=0&&value<=1?{valid:true,value}:{valid:false,value:null};
 }
 function provenance(input,defaults){
  const source=text(input?.provenance?.source)||text(input?.source)||defaults.source;
  if(!source)return null;
  const isolation=text(input?.provenance?.isolationEvidence)||defaults.isolationEvidence;
  if(!['pipeline-separated','verified','declared','unknown'].includes(isolation))return null;
  const result={source,isolationEvidence:isolation};
  const model=text(input?.provenance?.model)||text(input?.model)||defaults.model;
  if(model)result.model=model;
  return result;
 }
 function descriptor(input,defaults,reject){
  if(!object(input)){reject('descriptor-must-be-an-object');return null;}
  const audioRef=text(input.audioRef),id=text(input.id)||defaults.id,role=defaults.role||text(input.role),clock=text(input.clock)||defaults.clock;
  if(!audioRef){reject('missing-audio-ref');return null;}
  if(!id){reject('missing-id');return null;}
  if(!ROLES.has(role)){reject('unsupported-role');return null;}
  if(clock!==CLOCK){reject('clock-must-match-original-decoded-audio');return null;}
  const score=confidence(input.confidence);if(!score.valid){reject('confidence-must-be-between-zero-and-one');return null;}
  const evidence=provenance(input,defaults);if(!evidence){reject('missing-or-invalid-provenance');return null;}
  return {id,role,origin:defaults.origin,audioRef,clock:CLOCK,confidence:score.value,provenance:evidence};
 }
 function recordSort(left,right){
  return compareText(left.role,right.role)||compareText(left.id,right.id)||compareText(left.provenance.source,right.provenance.source);
 }
 function build(input={}){
  const records=[],rejected=[],ids=new Set();
  const reject=(scope,reason)=>rejected.push({scope,reason});
  const add=(scope,value,defaults)=>{
   const item=descriptor(value,defaults,reason=>reject(scope,reason));if(!item)return;
   if(ids.has(item.id)){reject(scope,'duplicate-stem-id');return;}
   ids.add(item.id);records.push(item);
  };
  const legacy=object(input.legacyStems)?input.legacyStems:{};
  if(legacy.vocals!==undefined)add('legacyStems.vocals',legacy.vocals,{id:'legacy-vocals',role:'combined-vocals',origin:'legacy-separated',clock:CLOCK,source:'legacy-vocal-accompaniment-separation',isolationEvidence:'pipeline-separated'});
  if(legacy.accompaniment!==undefined)add('legacyStems.accompaniment',legacy.accompaniment,{id:'legacy-accompaniment',role:'accompaniment',origin:'legacy-separated',clock:CLOCK,source:'legacy-vocal-accompaniment-separation',isolationEvidence:'pipeline-separated'});
  const external=Array.isArray(input.semanticStems)?input.semanticStems:[];
  for(let index=0;index<external.length;index++){
   const value=external[index],role=text(value?.role);
   if(!EXTERNAL_ROLES.has(role)){reject('semanticStems['+index+']','role-must-be-a-supported-external-semantic-stem');continue;}
   add('semanticStems['+index+']',value,{id:'semantic-'+role+'-'+index,role,origin:'externally-supplied',clock:null,source:null,isolationEvidence:'unknown'});
  }
  records.sort(recordSort);rejected.sort((left,right)=>compareText(left.scope,right.scope)||compareText(left.reason,right.reason));
  return {schemaVersion:SCHEMA_VERSION,clock:CLOCK,stems:records,diagnostics:{acceptedStemCount:records.length,rejected}};
 }
 function fromAnalysis(analysis,semanticStems=[]){
  const cache=analysis?.stemCache,key=text(cache?.key);
  if(!key||!LEGACY_CACHE_KEY.test(key)||!object(analysis?.separation))return build({semanticStems});
  const model=text(analysis.separation.modelId)||text(analysis.separation.model);
  const shared={clock:CLOCK,confidence:confidence(analysis.separation.confidence).valid?analysis.separation.confidence:undefined,provenance:{model:model||undefined}};
  return build({legacyStems:{
   vocals:{...shared,audioRef:'stem-cache:'+key+'/vocals.wav'},
   accompaniment:{...shared,audioRef:'stem-cache:'+key+'/accompaniment.wav'}
  },semanticStems});
 }
 function validate(contract){
  const errors=[];
  if(!object(contract)||contract.schemaVersion!==SCHEMA_VERSION||contract.clock!==CLOCK||!Array.isArray(contract.stems)||!object(contract.diagnostics))errors.push('Invalid stem-routing envelope.');
  const ids=new Set();
  for(const stem of contract?.stems||[]){
   if(!object(stem)||!text(stem.id)||ids.has(stem.id))errors.push('Duplicate or missing stem id.');ids.add(stem?.id);
   if(!ROLES.has(stem?.role)||!['legacy-separated','externally-supplied'].includes(stem?.origin)||!text(stem?.audioRef)||stem?.clock!==CLOCK)errors.push('Invalid stem descriptor.');
   if(stem?.confidence!==null&&(!finite(stem?.confidence)||stem.confidence<0||stem.confidence>1))errors.push('Invalid stem confidence.');
   if(!object(stem?.provenance)||!text(stem.provenance.source)||!['pipeline-separated','verified','declared','unknown'].includes(stem.provenance.isolationEvidence))errors.push('Invalid stem provenance.');
   if(stem?.origin==='legacy-separated'&&stem?.provenance?.isolationEvidence!=='pipeline-separated')errors.push('Legacy stem isolation provenance is invalid.');
   if(stem?.origin==='externally-supplied'&&!EXTERNAL_ROLES.has(stem?.role))errors.push('Invalid external semantic stem role.');
  }
  if(!Number.isSafeInteger(contract?.diagnostics?.acceptedStemCount)||contract.diagnostics.acceptedStemCount!==(contract?.stems||[]).length||!Array.isArray(contract?.diagnostics?.rejected))errors.push('Invalid stem-routing diagnostics.');
  return {valid:errors.length===0,errors};
 }
 function rank(left,right){
  const leftKnown=left.confidence===null?0:1,rightKnown=right.confidence===null?0:1;
  return rightKnown-leftKnown||((right.confidence??-1)-(left.confidence??-1))||compareText(left.id,right.id);
 }
 function route(contract,task){
  const check=validate(contract);if(!check.valid)throw Error('Stem routing requires a valid contract: '+check.errors.join('; ').slice(0,512));
  const policy=TASKS[task];if(!policy)return {schemaVersion:SCHEMA_VERSION,task,status:'unsupported-task',selected:null,alternatives:[],reason:'No routing policy exists for this task.'};
  for(const step of policy){
   const matches=contract.stems.filter(stem=>step.roles.includes(stem.role)).sort(rank);
   if(matches.length)return {schemaVersion:SCHEMA_VERSION,task,status:'routed',routeKind:step.kind,selected:clone(matches[0]),alternatives:matches.slice(1).map(clone),reason:null};
  }
  return {schemaVersion:SCHEMA_VERSION,task,status:'unavailable',selected:null,alternatives:[],reason:'No supplied or actual legacy stem is eligible for this task.'};
 }
 const api={build,fromAnalysis,route,validate,roles:[...ROLES],tasks:Object.keys(TASKS),schemaVersion:SCHEMA_VERSION};
 root.LightForgeStemRouting=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);

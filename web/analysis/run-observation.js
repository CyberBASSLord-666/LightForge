/* Strict, privacy-safe evidence emitted only after a completed fresh app run.
 * This observes aggregate facts only; it must never affect analysis, cache
 * identity, choreography, FSEQ output, exports, or quality-gate scoring.
 */
(function(root){'use strict';
 const VERSION=1,KIND='lightforge.completed-analysis-run',RUN_KIND='fresh-completed';
 const MAX_SECONDS=21600,MAX_COUNTER=1000000;
 const STAGES=Object.freeze(['bass','recurrence','rhythm','separation','voice']);
 const stageIds=new Set(STAGES),sources=new Set(['performance.now','date.now','unavailable']);
 const states=new Set(['available','fallback','unavailable','observed-error']);
 const reasons=new Set(['clock-unavailable','clock-observed-error','worker-clock-unavailable','worker-clock-observed-error','restored-stage-zero-cost']);
 const implementations=Object.freeze({
  precision:Object.freeze({rhythmModelFamily:'beat-this-full',separationModelFamily:'deux'}),
  balanced:Object.freeze({rhythmModelFamily:'beat-this-compact',separationModelFamily:'mdx'})
 });
 const runtimeKinds=new Set(['android-cpu-plus-web','web-wasm','unknown']);
 const plain=value=>!!value&&Object.getPrototypeOf(value)===Object.prototype;
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const seconds=value=>finite(value)&&value>=0&&value<=MAX_SECONDS;
 const counter=value=>Number.isSafeInteger(value)&&value>=0&&value<=MAX_COUNTER;
 const keys=(value,expected,label)=>{
  if(!plain(value)||Object.keys(value).sort().join(',')!==expected.slice().sort().join(','))throw Error('Invalid '+label+' shape.');
  return value;
 };
 const rounded=value=>Math.round(value*1000000)/1000000;
 const has=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
 function unavailableTiming(status='unavailable',source='unavailable',scope='clock'){
  const observedError=status==='observed-error'&&(source==='performance.now'||source==='date.now');
  const reason=scope==='restored'?'restored-stage-zero-cost':scope==='worker'?(observedError?'worker-clock-observed-error':'worker-clock-unavailable'):(observedError?'clock-observed-error':'clock-unavailable');
  return {source:observedError?source:'unavailable',status:observedError?'observed-error':'unavailable',seconds:null,reason};
 }
 function observedTiming(value,scope='clock'){
  if(!plain(value))return unavailableTiming('unavailable','unavailable',scope);
  const source=sources.has(value.source)?value.source:'unavailable';
  const status=states.has(value.status)?value.status:'unavailable';
  if(value.measured===true){
   if(!seconds(value.milliseconds/1000))throw Error('Invalid observed timing.');
   if((status==='available'&&source==='performance.now')||(status==='fallback'&&source==='date.now'))return {source,status,seconds:rounded(value.milliseconds/1000),reason:null};
  }
  return unavailableTiming(status,source,scope);
 }
 function stageTiming(value){
  if(!plain(value)||typeof value.restored!=='boolean'||!seconds(value.seconds))throw Error('Invalid analysis stage.');
  if(value.restored)return unavailableTiming('unavailable','unavailable','restored');
  const attributes=plain(value.profile)&&plain(value.profile.attributes)?value.profile.attributes:null;
  if(!attributes||attributes.workerClockMeasured!==true)return unavailableTiming('unavailable','unavailable','worker');
  const source=sources.has(attributes.workerClockSource)?attributes.workerClockSource:'unavailable';
  const status=states.has(attributes.workerClockStatus)?attributes.workerClockStatus:'unavailable';
  if((status==='available'&&source==='performance.now')||(status==='fallback'&&source==='date.now'))return {source,status,seconds:rounded(value.seconds),reason:null};
  return unavailableTiming(status,source,'worker');
 }
 function resourceSummary(engine){
  const pipeline=engine.resourceDiagnostics;
  if(!plain(pipeline)||pipeline.schemaVersion!==1||pipeline.kind!=='analysis-pipeline-resources'||!plain(pipeline.stages))return {status:'unavailable',schedulerWaitSeconds:null,observedStageCount:0};
  const observedStageCount=STAGES.filter(stage=>has(pipeline.stages,stage)).length;
  const scheduler=plain(pipeline.scheduler)?pipeline.scheduler:null;
  const wait=scheduler&&scheduler.status==='available'&&seconds(scheduler.waitMilliseconds/1000)?rounded(scheduler.waitMilliseconds/1000):null;
  return {status:'available',schedulerWaitSeconds:wait,observedStageCount};
 }
 function runtimeKind(separation){
  if(!plain(separation))return 'unknown';
  if(Number.isSafeInteger(separation.nativeModelPasses)&&separation.nativeModelPasses>0)return 'android-cpu-plus-web';
  if(separation.runtime==='onnxruntime-android-cpu')return 'android-cpu-plus-web';
  if(separation.runtime==='onnxruntime-web-wasm')return 'web-wasm';
  return 'unknown';
 }
 function build(input){
  if(!plain(input)||input.analysisPerformed!==true||!plain(input.engine))throw Error('A completed fresh analysis engine is required.');
  const engine=input.engine,separation=engine.separationModel,quality=engine.quality;
  if(!has(implementations,quality)||!plain(separation)||!plain(engine.stages))throw Error('Invalid completed analysis profile.');
  const incomingStageIds=Object.keys(engine.stages);
  if(!incomingStageIds.length||incomingStageIds.some(stage=>!stageIds.has(stage)))throw Error('Invalid completed analysis stage map.');
  const stages=STAGES.filter(stage=>has(engine.stages,stage)).map(stageId=>({stageId,restored:engine.stages[stageId].restored,timing:stageTiming(engine.stages[stageId])}));
  const restoredStageNames=stages.filter(stage=>stage.restored).map(stage=>stage.stageId);
  const separationRestoredPassages=counter(separation.restoredPassages)?separation.restoredPassages:null;
  const result={
   schemaVersion:VERSION,
   kind:KIND,
   runKind:RUN_KIND,
   privacy:{audioContent:'excluded',projectIdentity:'excluded',userContent:'excluded'},
   timing:{analysis:observedTiming(input.analysisTiming),choreography:observedTiming(input.choreographyTiming),total:observedTiming(input.totalTiming)},
   analysis:{quality,implementation:{...implementations[quality],runtimeKind:runtimeKind(separation)},stages,cache:{restoredStageCount:restoredStageNames.length,restoredStageNames,separationRestoredPassages}},
   resources:resourceSummary(engine)
  };
  validate(result);return result;
 }
 function validateTiming(value,label,scope){
  const timing=keys(value,['reason','seconds','source','status'],label);
  if(!sources.has(timing.source)||!states.has(timing.status)||!(timing.seconds===null||seconds(timing.seconds))||!(timing.reason===null||reasons.has(timing.reason)))throw Error('Invalid '+label+'.');
  if(timing.status==='available'){
   if(timing.source!=='performance.now'||timing.seconds===null||timing.reason!==null)throw Error('Invalid '+label+' state.');
  }else if(timing.status==='fallback'){
   if(timing.source!=='date.now'||timing.seconds===null||timing.reason!==null)throw Error('Invalid '+label+' state.');
  }else if(timing.status==='observed-error'){
   if((timing.source!=='performance.now'&&timing.source!=='date.now')||timing.seconds!==null||timing.reason!==(scope==='worker'?'worker-clock-observed-error':'clock-observed-error'))throw Error('Invalid '+label+' state.');
  }else if(timing.seconds!==null||timing.source!=='unavailable')throw Error('Invalid '+label+' state.');
  return timing;
 }
 function validate(value){
  keys(value,['analysis','kind','privacy','resources','runKind','schemaVersion','timing'],'analysis run observation');
  if(value.schemaVersion!==VERSION||value.kind!==KIND||value.runKind!==RUN_KIND)throw Error('Unsupported analysis run observation.');
  keys(value.privacy,['audioContent','projectIdentity','userContent'],'analysis observation privacy');
  for(const field of ['audioContent','projectIdentity','userContent'])if(value.privacy[field]!=='excluded')throw Error('Analysis observation privacy boundary is invalid.');
  keys(value.timing,['analysis','choreography','total'],'analysis observation timing');
  const timing={analysis:validateTiming(value.timing.analysis,'analysis observation analysis timing','clock'),choreography:validateTiming(value.timing.choreography,'analysis observation choreography timing','clock'),total:validateTiming(value.timing.total,'analysis observation total timing','clock')};
  for(const name of ['analysis','choreography'])if(timing.total.seconds!==null&&timing[name].seconds!==null&&timing.total.seconds+1e-6<timing[name].seconds)throw Error('Total observation timing is smaller than a completed phase.');
  keys(value.analysis,['cache','implementation','quality','stages'],'analysis observation profile');
  if(!has(implementations,value.analysis.quality))throw Error('Invalid analysis observation quality.');
  keys(value.analysis.implementation,['rhythmModelFamily','runtimeKind','separationModelFamily'],'analysis observation implementation');
  const expectedImplementation={...implementations[value.analysis.quality],runtimeKind:value.analysis.implementation.runtimeKind};
  if(!runtimeKinds.has(expectedImplementation.runtimeKind)||JSON.stringify(value.analysis.implementation)!==JSON.stringify(expectedImplementation))throw Error('Invalid analysis observation implementation.');
  if(!Array.isArray(value.analysis.stages)||!value.analysis.stages.length||value.analysis.stages.length>STAGES.length)throw Error('Invalid analysis observation stages.');
  let previous='',restored=[];
  for(const stage of value.analysis.stages){
   keys(stage,['restored','stageId','timing'],'analysis observation stage');
   if(!stageIds.has(stage.stageId)||stage.stageId<=previous||typeof stage.restored!=='boolean')throw Error('Invalid analysis observation stage.');
   previous=stage.stageId;const stageTimingValue=validateTiming(stage.timing,'analysis observation stage timing','worker');
   if(stage.restored){
    if(stageTimingValue.status!=='unavailable'||stageTimingValue.reason!=='restored-stage-zero-cost')throw Error('Restored analysis stage timing is ambiguous.');
    restored.push(stage.stageId);
   }else if(stageTimingValue.status==='unavailable'&&stageTimingValue.reason!=='worker-clock-unavailable')throw Error('Invalid unavailable analysis stage timing.');
  }
  const cache=keys(value.analysis.cache,['restoredStageCount','restoredStageNames','separationRestoredPassages'],'analysis observation cache');
  if(!counter(cache.restoredStageCount)||!(cache.separationRestoredPassages===null||counter(cache.separationRestoredPassages))||!Array.isArray(cache.restoredStageNames)||cache.restoredStageCount!==restored.length||cache.restoredStageNames.length!==restored.length||cache.restoredStageNames.join(',')!==restored.join(','))throw Error('Invalid analysis observation cache.');
  keys(value.resources,['observedStageCount','schedulerWaitSeconds','status'],'analysis observation resources');
  if((value.resources.status!=='available'&&value.resources.status!=='unavailable')||!counter(value.resources.observedStageCount)||value.resources.observedStageCount>STAGES.length||!(value.resources.schedulerWaitSeconds===null||seconds(value.resources.schedulerWaitSeconds))||(value.resources.status==='unavailable'&&(value.resources.observedStageCount!==0||value.resources.schedulerWaitSeconds!==null)))throw Error('Invalid analysis observation resources.');
  return true;
 }
 function completed(input){try{return build(input);}catch(_){return null;}}
 const api={build,completed,validate};root.LightForgeAnalysisRunObservation=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof self!=='undefined'?self:globalThis);

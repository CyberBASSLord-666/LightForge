'use strict';
/* Canonical, bounded measurement projection for the real browser analyzer.
 * It carries observed timings and cache/profile provenance only; it contains no
 * threshold, baseline comparison, or claim that one run is performant. */
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const plain=value=>value&&Object.getPrototypeOf(value)===Object.prototype;
const text=(value,label)=>{
  if(typeof value!=='string'||!value||value.length>256)throw Error('Invalid '+label+'.');
  return value;
};
const nonnegative=(value,label)=>{
  if(!finite(value)||value<0)throw Error('Invalid '+label+'.');
  return Math.round(value*1000000)/1000000;
};
const integer=(value,label)=>{
  if(!Number.isSafeInteger(value)||value<0)throw Error('Invalid '+label+'.');
  return value;
};
const exact=(value,keys,label)=>{
  if(!plain(value)||Object.keys(value).sort().join(',')!==keys.slice().sort().join(','))throw Error('Invalid '+label+' shape.');
  return value;
};
function build(engine,totalWallClockSeconds){
  if(!plain(engine))throw Error('Invalid analyzer engine.');
  const stagesSource=engine.stages;
  if(!plain(stagesSource))throw Error('Invalid analyzer stage map.');
  const entries=Object.entries(stagesSource).sort(([left],[right])=>left<right?-1:left>right?1:0);
  if(!entries.length||entries.length>64)throw Error('Invalid analyzer stage count.');
  const stages={};
  for(const [name,stage] of entries){
    if(!/^[a-z][a-z0-9-]{0,63}$/.test(name))throw Error('Invalid analyzer stage name.');
    if(!plain(stage)||!Object.hasOwn(stage,'seconds')||!Object.hasOwn(stage,'restored'))throw Error('Invalid analyzer stage shape.');
    if(typeof stage.restored!=='boolean')throw Error('Invalid analyzer stage restoration state.');
    stages[name]={seconds:nonnegative(stage.seconds,'analyzer stage seconds'),restored:stage.restored};
  }
  const separation=engine.separation;
  if(!plain(separation))throw Error('Invalid separation profile.');
  const profile={
    name:text(engine.name,'engine name'),modelId:text(engine.modelId,'engine model id'),
    quality:text(engine.quality,'analysis quality'),runtime:text(engine.runtime,'analysis runtime'),
    recoverable:engine.recoverable===true,
    separation:{
      modelId:text(separation.modelId,'separation model id'),runtime:text(separation.runtime,'separation runtime'),
      chunks:integer(separation.chunks,'separation chunk count'),
      restoredPassages:integer(separation.restoredPassages,'restored passage count')
    }
  };
  const restoredStages=Object.keys(stages).filter(name=>stages[name].restored);
  const result={schemaVersion:1,totalWallClockSeconds:nonnegative(totalWallClockSeconds,'total wall-clock seconds'),
    analyzerReportedSeconds:nonnegative(engine.analysisSeconds,'analyzer reported seconds'),stages,
    cache:{restoredStageCount:restoredStages.length,restoredStageNames:restoredStages,separationRestoredPassages:profile.separation.restoredPassages},
    profile};
  validate(result);
  return result;
}
function validate(value){
  exact(value,['analyzerReportedSeconds','cache','profile','schemaVersion','stages','totalWallClockSeconds'],'analysis performance projection');
  if(value.schemaVersion!==1)throw Error('Unsupported analysis performance schema.');
  nonnegative(value.totalWallClockSeconds,'total wall-clock seconds');
  nonnegative(value.analyzerReportedSeconds,'analyzer reported seconds');
  if(!plain(value.stages)||!Object.keys(value.stages).length)throw Error('Invalid projected stage map.');
  for(const [name,stage] of Object.entries(value.stages)){
    if(!/^[a-z][a-z0-9-]{0,63}$/.test(name))throw Error('Invalid projected stage name.');
    exact(stage,['restored','seconds'],'projected stage');
    nonnegative(stage.seconds,'projected stage seconds');
    if(typeof stage.restored!=='boolean')throw Error('Invalid projected stage restoration state.');
  }
  exact(value.cache,['restoredStageCount','restoredStageNames','separationRestoredPassages'],'analysis cache summary');
  integer(value.cache.restoredStageCount,'restored stage count');
  integer(value.cache.separationRestoredPassages,'restored passage count');
  if(!Array.isArray(value.cache.restoredStageNames)||value.cache.restoredStageNames.length!==value.cache.restoredStageCount||
    value.cache.restoredStageNames.some(name=>typeof name!=='string'||!value.stages[name]||value.stages[name].restored!==true)||
    new Set(value.cache.restoredStageNames).size!==value.cache.restoredStageNames.length)throw Error('Invalid restored-stage summary.');
  exact(value.profile,['modelId','name','quality','recoverable','runtime','separation'],'analysis profile summary');
  text(value.profile.name,'projected engine name');text(value.profile.modelId,'projected model id');
  text(value.profile.quality,'projected quality');text(value.profile.runtime,'projected runtime');
  if(typeof value.profile.recoverable!=='boolean')throw Error('Invalid projected recovery flag.');
  exact(value.profile.separation,['chunks','modelId','restoredPassages','runtime'],'projected separation profile');
  text(value.profile.separation.modelId,'projected separation model id');text(value.profile.separation.runtime,'projected separation runtime');
  integer(value.profile.separation.chunks,'projected chunk count');integer(value.profile.separation.restoredPassages,'projected restored passages');
  if(value.cache.separationRestoredPassages!==value.profile.separation.restoredPassages)throw Error('Cache and separation restoration summaries differ.');
  return true;
}
module.exports={build,validate};

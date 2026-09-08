/* A service-owned document runs the same production workers without the studio UI. */
(function(root){'use strict';
 const controller=new AbortController(),id=new URL(location.href).searchParams.get('job');
 let started=false;
 root.BackgroundAnalysis={cancel(){root.LightForgeDiagnostics?.log('info','background','Cancel received');controller.abort();}};
 const check=()=>{if(controller.signal.aborted)throw new DOMException('Analysis cancelled','AbortError');};
 const report=(progress,detail,info={})=>{
  root.LightForgeDiagnostics?.progress('background',{...info,progress});
  if(typeof BackgroundJob.progressInfo==='function')BackgroundJob.progressInfo(id,progress,detail,JSON.stringify(info));
  else BackgroundJob.progress(id,progress,detail);
 };
 async function run(){
  if(started)return;started=true;root.LightForgeDiagnostics?.log('info','background','Runner started');
  try{
   const response=await fetch('/background/request.json',{cache:'no-store',signal:controller.signal});
   if(!response.ok)throw Error('The saved analysis request could not be opened.');
   const request=await response.json();root.LightForgeDiagnostics?.protectText(request.name);const settings=request.settings||{},projectId=request.projectId;
   if(!/^[A-Za-z0-9_-]{1,80}$/.test(projectId))throw Error('Invalid analysis project.');
   // A killed renderer can leave an incomplete OPFS namespace. Native job
   // ownership guarantees no other analysis is writing when a new runner starts.
   if(navigator.storage?.getDirectory){
    const storage=await navigator.storage.getDirectory();let stems;
    try{stems=await storage.getDirectoryHandle('lightforge-stems-v1');}catch(error){if(error.name!=='NotFoundError')throw error;}
    if(stems)for await(const [key,entry]of stems.entries()){
     check();if(entry.kind!=='directory'||!LightForgeStemCache.validKey(key))continue;
     try{await entry.getFileHandle('complete.json');}catch(error){if(error.name==='NotFoundError')await LightForgeStemCache.discard(key);else throw error;}
    }
   }
   const base='/project/'+encodeURIComponent(projectId)+'/';
   let music=request.music;
   if(!music||request.needAnalysis||(music.analysisVersion||1)<5){
    music=await MusicAnalyzer.analyze(new URL(base+'audio.wav',location.href).href,{
     projectId,analysisIdentity:request.analysisIdentity,analysisUrl:new URL(base+'analysis.wav',location.href).href,sensitivity:settings.sensitivity,
     bpmOverride:settings.bpmOverride||undefined,analysisQuality:settings.analysisQuality,
     nativePredict:root.LightForgeNativeDeux?.create(BackgroundJob,id)
    },p=>report(.96*Math.max(0,Math.min(1,Number(p.progress)||0)),p.detail||p.message||p.stage||'Analyzing music',p),controller.signal);
   }
   check();const duration=Number(request.duration);
   if(Number.isFinite(duration)&&duration>0&&music.duration!==duration){
    const sections=music.sections?.map(s=>({...s}));if(sections?.length)sections[sections.length-1].end=duration;
    music={...music,duration,sections};
   }
   if(!BackgroundJob.checkpoint(id,JSON.stringify(music)))throw Error('The analysis checkpoint could not be saved.');
   check();
   const result=await ShowCompiler.generate(music,settings,p=>report(.96+.035*Math.max(0,Math.min(1,Number(p.progress)||0)),p.detail||'Choreographing your show',{stage:'generate'}),controller.signal);
   check();report(.999,'Saving your complete show',{stage:'save'});
   const saved={version:1,projectId,name:request.name,updatedAt:Date.now(),settings,music,needAnalysis:false,compiled:result.compiled,
    provenance:{app:LightForgeVersion.name,planner:result.show.version,profile:VehicleProfile.version,analysis:music.analysisVersion,model:music.engine,frameSHA256:result.compiled.sha256}};
   if(!BackgroundJob.complete(id,JSON.stringify(saved)))throw Error('Your completed show could not be saved.');
   root.LightForgeDiagnostics?.log('info','background','Completed show committed');
  }catch(error){root.LightForgeDiagnostics?.log(error.name==='AbortError'?'info':'error','background',error);BackgroundJob.failed(id,error.message||'Analysis could not finish.',error.name==='AbortError');}
 }
 run();
})(window);

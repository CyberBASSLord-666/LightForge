/* Local, bounded troubleshooting history. Never serializes application payloads. */
(function(root){'use strict';
 const KEY='lightforge-diagnostics-v1',MAX_EVENTS=240,MAX_CHARS=131072,MAX_MESSAGE=3072;
 const sources=new Set(['app','window','promise','resource','console','bridge','operation','progress','analysis','analysis-worker','composition-worker','background','lifecycle','export']);
 const stages=['rhythm','separation','voice','vocal','bass','generate','save','restore','import','decode','model','neural','beats','structure','export','duplicate','prepare'];
 const scripts=new Set(['app.js','diagnostics.js','version.js','channel-studio.js','music-insights.js','studio-tools.js','precision-studio.js','ui-polish.js','cockpit.js',
  'analysis/worker.js','analysis/analyzer.js','analysis/stem-cache.js','analysis/work-store.js','analysis/wav-reader.js','analysis/dsp.js','analysis/vocal-detail.js','analysis/game.js','analysis/vocal.js','analysis/separator-deux.js','analysis/separator-mdx.js','analysis/bass-notes.js',
  'engine/worker.js','engine/client.js','engine/show-engine.js','engine/vehicle-profile.js','engine/light-planner.js','engine/movement-planner.js','engine/music-cues.js','engine/sync-review.js','background/runner.js','background/native-deux.js','preview/vehicle-preview.js']);
 let records=[],chars=0,persistTimer=null,pending=null,dropped=0,lastProgress=new Map(),burstAt=0,burstCount=0;
 let status='',statusError=false,recoveryNeeded=false;const privateText=new Set();
 const nativeBridge=()=>root.Android||root.BackgroundJob;
 function scriptLocation(value){
  try{
   const suffix=value.match(/:\d+(?::\d+)?$/)?.[0]||'',url=new URL(suffix?value.slice(0,-suffix.length):value,root.location.href);
   const path=url.pathname.replace(/^\//,'');
   if(url.origin===root.location.origin&&scripts.has(path))return path.replaceAll('/','.')+suffix;
   return '[uri]'+suffix;
  }catch{return '[uri]';}
 }
 function clean(value){
  let s=typeof value==='string'?value:typeof value==='number'||typeof value==='boolean'?String(value):'[non-text detail omitted]';
  s=s.slice(0,12288).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,'');
  for(const value of privateText)s=s.split(value).join('[private text]');
  s=s.replace(/\b(?:bearer\s+)[^\s,;]+/gi,'Bearer [redacted]')
   .replace(/\b(?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+/gi,'credential=[redacted]')
   .replace(/\bsk[-_][A-Za-z0-9_-]+/g,'[credential]')
   .replace(/\b(?:https?|file|content|blob):[^\s)]+/gi,scriptLocation)
   .replace(/\bdata:[^\s)]+/gi,'[data omitted]')
   .replace(/(?:[A-Za-z]:[\\/]|\/)(?:[^\s:;()]+[\\/])*[^\s:;()]*/g,'[path]')
   .replace(/["“][^"”\n]*["”]|'[^'\n]*'/g,'[quoted text omitted]')
   .replace(/\b[^\s]+\.(?:wav|mp3|m4a|flac|ogg|opus|aac|mp4|webm|mka|zip|fseq)\b/gi,'[file]')
   .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi,'[email]')
   .replace(/\b(?:show|stem)-[A-Za-z0-9_-]+\b/g,'[local id]')
   .replace(/\b[A-Za-z0-9+/_=-]{96,}\b/g,'[long data omitted]');
  return s.length>MAX_MESSAGE?s.slice(0,MAX_MESSAGE-20)+' … [truncated]':s;
 }
 function describe(value){
  if(value&&typeof value==='object'){
   // Error fields only. Objects, arrays, project JSON and PCM buffers are never serialized.
   try{
    if(typeof value.stack==='string'||typeof value.message==='string'){
     const name=typeof value.name==='string'?clean(value.name).slice(0,80):'Error';
     const message=typeof value.message==='string'?clean(value.message):'No error message';
     const stack=typeof value.stack==='string'?value.stack.split('\n').slice(1,13).map(clean).join('\n'):'';
     return clean(name+': '+message+(stack?'\n'+stack:''));
    }
   }catch{return '[unreadable error detail]';}
  }
  return clean(value);
 }
 function append(record){
  records.push(record);chars+=record.message.length+100;
  while(records.length>MAX_EVENTS||chars>MAX_CHARS){chars-=records.shift().message.length+100;dropped++;}
 }
 function persist(){
  root.clearTimeout(persistTimer);persistTimer=null;
  try{root.localStorage.setItem(KEY,JSON.stringify({version:1,dropped,records}));}catch{/* Full or disabled storage must never break analysis. */}
 }
 function log(level,source,value){
  try{
   level=['debug','info','warn','error'].includes(level)?level:'info';source=sources.has(source)?source:'app';
   const now=Date.now();if(now-burstAt>=1000){burstAt=now;burstCount=0;}
   if(++burstCount>40){dropped++;return;}
   const message=describe(value),last=records[records.length-1];
   if(last&&last.level===level&&last.source===source&&last.message===message&&now-Date.parse(last.time)<2000){dropped++;return;}
   const entry={time:new Date(now).toISOString(),level,source,message};append(entry);
   if(level==='error'){recoveryNeeded=true;const card=root.document?.getElementById('diagnosticRecovery');if(card)card.hidden=false;}
   const bridge=nativeBridge();
   if(typeof bridge?.logDiagnostic==='function'){
    try{bridge.logDiagnostic(level,source,message);return;}catch{/* Keep a browser copy if the bridge is unavailable. */}
   }
   if(level==='error')persist();else if(persistTimer===null)persistTimer=root.setTimeout(persist,300);
  }catch{/* Diagnostics must not cause a second failure. */}
 }
 function progress(source,info={}){
  try{
   const stageText=typeof info.stage==='string'?info.stage.toLowerCase():'',stage=stages.find(x=>stageText.includes(x))||'working';
   const now=Date.now(),p=Number(info.progress),percent=Number.isFinite(p)?Math.round(Math.max(0,Math.min(1,p>1?p/100:p))*100):null;
   const previous=lastProgress.get(source),passage=Number.isSafeInteger(info.passageIndex)?info.passageIndex:null;
   if(previous&&previous.stage===stage&&previous.passage===passage&&now-previous.time<15000)return;
   lastProgress.set(source,{stage,passage,time:now});
   const fields=['stage='+stage];if(percent!==null)fields.push('progress='+percent+'%');
   for(const key of ['passageIndex','passageCount','passagesCompleted','restoredPassages','completedStages','restoredStages'])if(Number.isSafeInteger(info[key])&&info[key]>=0&&info[key]<=100000)fields.push(key+'='+info[key]);
   if(typeof info.checkpointSaved==='boolean')fields.push('checkpointSaved='+info.checkpointSaved);
   log('info',source,fields.join(' '));
  }catch{}
 }
 function report(){
  const threads=Number(root.navigator?.hardwareConcurrency),memory=Number(root.navigator?.deviceMemory);
  return ['LightForge diagnostic log','Format: 1','Exported: '+new Date().toISOString(),
   'App: '+clean(root.LightForgeVersion?.name||'version unavailable'),
   'Runtime: '+(nativeBridge()?'Android WebView':'browser'),
   'CPU threads: '+(Number.isFinite(threads)?threads:'unavailable'),'Device memory class (GB): '+(Number.isFinite(memory)?memory:'unavailable'),
   'Retained events: '+records.length,'Older, repeated or rate-limited events omitted: '+dropped,
   'Music, lyrics, project contents and file URLs are excluded. Error text is sanitized.','',
   ...records.map(r=>r.time+' '+r.level.toUpperCase()+' ['+r.source+'] '+r.message),''].join('\n');
 }
 function showStatus(message,error=false){
  status=message;statusError=error;
  root.document?.querySelectorAll('[data-diagnostic-status]').forEach(el=>{el.textContent=status;el.hidden=!status;el.classList.toggle('diagnostic-error',statusError);});
 }
 function busy(value){root.document?.querySelectorAll('[data-export-diagnostics]').forEach(button=>{button.disabled=value;button.setAttribute('aria-busy',String(value));});}
 function handleNativeEvent(type,payload){
  if(type!=='diagnosticExported'&&type!=='diagnosticExportFailed')return false;
  let data;try{data=typeof payload==='string'?JSON.parse(payload):payload||{};}catch{data={};}
  const task=pending;pending=null;busy(false);
  if(type==='diagnosticExported'&&typeof data.name==='string'&&data.name&&typeof data.location==='string'&&data.location){
   showStatus('Saved '+data.name+' to '+data.location+'. You can attach this file when reporting a problem.');
   task?.resolve(data);
  }else{
   const cancelled=data.cancelled===true;
   const error=new Error(cancelled?'Log export canceled.':data.message||'The diagnostic log could not be saved. Try exporting again.');
   if(cancelled)error.name='AbortError';else log('error','export',error);
   showStatus(error.message,!cancelled);task?.reject(error);
  }
  return true;
 }
 async function exportLog(){
  if(pending)return pending.promise;
  log('info','export','Diagnostic export requested');
  const bridge=nativeBridge();
  if(bridge){
   if(typeof bridge.exportDiagnostics!=='function'){
    const error=new Error('This installed version cannot export diagnostic logs. Update LightForge and try again.');showStatus(error.message,true);throw error;
   }
   let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});pending={resolve,reject,promise};
   busy(true);showStatus('Preparing your log. If a save dialog opens, choose Downloads and tap Save.');
   try{bridge.exportDiagnostics();}catch(error){handleNativeEvent('diagnosticExportFailed',{message:error?.message||'The diagnostic log could not be saved.'});}
   // Android's save picker can remain open indefinitely. Only its actual result completes this request.
   return promise;
  }
  let url,link;
  try{
   persist();const name='LightForge-diagnostics-'+new Date().toISOString().replace(/[:.]/g,'-')+'.log';
   const blob=new Blob([report()],{type:'text/plain;charset=utf-8'});url=URL.createObjectURL(blob);
   link=root.document.createElement('a');link.href=url;link.download=name;root.document.body.appendChild(link);link.click();link.remove();
   const downloadURL=url;root.setTimeout(()=>URL.revokeObjectURL(downloadURL),60000);
   showStatus('Download requested: '+name+'. Your browser chooses the download location; select Downloads if prompted.');
   return {name,location:'Browser download location',bytes:blob.size,requested:true};
  }catch(error){link?.remove();if(url)URL.revokeObjectURL(url);log('error','export',error);showStatus('The log download could not start. '+clean(error?.message||'Try again.'),true);throw error;}
 }
 try{
  const raw=root.localStorage.getItem(KEY);
  if(raw&&raw.length<=MAX_CHARS*2){const stored=JSON.parse(raw);if(stored.version===1&&Array.isArray(stored.records)){
   dropped=Number.isSafeInteger(stored.dropped)&&stored.dropped>=0?stored.dropped:0;
   for(const r of stored.records.slice(-MAX_EVENTS))if(r&&typeof r.message==='string'&&typeof r.time==='string'&&/^\d{4}-\d\d-\d\dT/.test(r.time))append({time:r.time.slice(0,24),level:['debug','info','warn','error'].includes(r.level)?r.level:'info',source:sources.has(r.source)?r.source:'app',message:clean(r.message)});
  }}
 }catch{}
 root.LightForgeDiagnostics={log,progress,exportLog,handleNativeEvent,report,protectText(value){if(typeof value==='string'&&value.length>=3&&value.length<=512&&privateText.size<500)privateText.add(value);}};
 if(typeof root.onNativeEvent!=='function')root.onNativeEvent=(type,payload)=>handleNativeEvent(type,payload);
 root.addEventListener('error',event=>{
  if(event.target&&event.target!==root){const tag=event.target.tagName;if(['SCRIPT','LINK','AUDIO','VIDEO'].includes(tag))log('error','resource',tag+' resource failed to load'+(tag==='SCRIPT'?' '+scriptLocation(event.target.src):''));return;}
  log('error','window',event.error||((event.message||'Unhandled script error')+(event.filename?' at '+scriptLocation(event.filename)+':'+(Number(event.lineno)||0)+':'+(Number(event.colno)||0):'')));
 },true);
 root.addEventListener('unhandledrejection',event=>log('error','promise',event.reason));
 // Android already captures WebChromeClient console errors in its native store.
 // In a browser retain only text/error summaries, while preserving console behavior.
 if(!nativeBridge()&&root.console)for(const level of ['warn','error']){
  const original=root.console[level];if(typeof original==='function')root.console[level]=function(...args){
   try{log(level,'console',args.slice(0,4).map(describe).join(' '));}catch{}
   return Reflect.apply(original,this,args);
  };
 }
 root.addEventListener('pagehide',()=>{log('info','lifecycle','Document hidden or closed');if(!nativeBridge())persist();});
 root.document?.addEventListener('visibilitychange',()=>log('info','lifecycle',root.document.hidden?'Document hidden':'Document visible'));
 function attach(){
  root.document?.querySelectorAll('[data-export-diagnostics]').forEach(button=>{button.onclick=()=>{exportLog().catch(()=>{});};});
  const card=root.document?.getElementById('diagnosticRecovery');if(card)card.hidden=!recoveryNeeded;
  const dismiss=root.document?.getElementById('dismissDiagnosticRecovery');if(dismiss)dismiss.onclick=()=>{recoveryNeeded=false;if(card)card.hidden=true;};
  showStatus(status,statusError);busy(!!pending);
 }
 if(root.document?.readyState==='loading')root.document.addEventListener('DOMContentLoaded',attach,{once:true});else attach();
 log('info','lifecycle','Diagnostic capture started');
})(window);

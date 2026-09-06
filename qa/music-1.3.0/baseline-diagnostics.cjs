/* Independent inspection of frozen 1.2.0 output, not an acceptance test for new code.
   Run from workspace root after capture-baseline.cjs. */
const fs=require('fs'),crypto=require('crypto');
const root='/tmp/lightforge-1.2.0-baseline';
const Engine=require(root+'/engine/show-engine.js');
const output='app/lightforge/qa/music-1.3.0/';
const round=x=>Math.round(x*10000)/10000;
const nearest=(arr,t)=>arr.length?Math.min(...arr.map(a=>Math.abs(a-t))):Infinity;
const percentile=(a,p)=>{a=a.slice().sort((a,b)=>a-b);return a[Math.floor((a.length-1)*p)]||0};
function metrics(m,show,raw){
 const step=show.stepMs/1000,transitions=[],attackTimes=new Set(),boolean=[1,2,17,21,22,23,24,25,26,27,28,30];
 let on=0,active=0,rest=0,restActive=0,total=0;const groups=[1,2,3,4,5,6,7,8,13,14,17,21,22,23,24,25,26,27,28,30];
 for(let f=0;f<show.frameCount;f++){
  let lit=0;for(const ch of groups)if(show.frames[f*200+ch-1]>127)lit++;
  if(lit)active++;on+=lit;total+=groups.length;
  if(raw&&raw.rms[Math.min(raw.rms.length-1,Math.round(f*step*50))]<.0002){rest++;if(lit)restActive++;}
  for(const ch of boolean)if(show.frames[f*200+ch-1]===255&&(!f||show.frames[(f-1)*200+ch-1]===0)){transitions.push({channel:ch,time:round(f*step)});attackTimes.add(round(f*step));}
 }
 const pulses=m.beats.flatMap((t,i)=>i+1<m.beats.length?[t,(t+m.beats[i+1])/2]:[t]);
 const timing=Array.from(attackTimes).map(t=>nearest(pulses.concat(m.onsets.filter(o=>o.strength>.5).map(o=>o.time)),t)*1000);
 const movements=show.movements.map(e=>({...e,nearestBeatMs:round(nearest(m.beats,e.start)*1000),nearestDownbeatMs:round(nearest(m.downbeats,e.start)*1000),section:m.sections.find(s=>e.start>=s.start&&e.start<s.end)?.label,localRms:raw?raw.rms[Math.min(raw.rms.length-1,Math.round(e.start*50))]:null}));
 return {duration:m.duration,bpm:m.bpm,meter:m.meter,beatCount:m.beats.length,beatConfidence:m.beatConfidence,onsetCount:m.onsets.length,onsetsPerSecond:round(m.onsets.length/m.duration),booleanAttackEvents:transitions.length,distinctBooleanAttackTimes:attackTimes.size,physicalGroupDutyFraction:round(on/total),exteriorActiveFraction:round(active/show.frameCount),silentFrameCount:rest,exteriorLitDuringSilentFrames:restActive,timingProxyNote:'Distance to inferred beats/eighths or inferred strong onsets; this is not independent audio or physical timing ground truth.',timingProxyP50Ms:round(percentile(timing,.5)),timingProxyP95Ms:round(percentile(timing,.95)),movements,validation:show.validation,stats:show.stats};
}
const vm=require('vm'),{createRequire}=require('module');
const context={module:{exports:{}},require:createRequire(root+'/engine/show-engine.js'),Uint8Array,console};
const instrumented=fs.readFileSync(root+'/engine/show-engine.js','utf8').replace('      cleanBooleanRuns(frames,n,step,s);','      root.__beforeBoolean=new Uint8Array(frames);cleanBooleanRuns(frames,n,step,s);root.__afterBoolean=new Uint8Array(frames);');
vm.runInNewContext(instrumented,context);
function cleanupDiagnostics(m){context.module.exports.generate(m,{dance:'expressive',sensitivity:.82});const a=context.__beforeBoolean,b=context.__afterBoolean,channels=[1,2,17,18,19,20,21,22,23,24,25,26,27,28,30];let beforeAttacks=0,afterAttacks=0,lostAttacks=0,addedOnFrames=0,removedOnFrames=0;const examples=[];for(const ch of channels)for(let f=0;f<a.length/200;f++){const p=f*200+ch-1,before=a[p]===255&&(!f||a[p-200]===0),after=b[p]===255&&(!f||b[p-200]===0);if(before)beforeAttacks++;if(after)afterAttacks++;if(before&&!after){lostAttacks++;if(examples.length<12)examples.push({channel:ch,time:round(f*.02)});}if(a[p]===0&&b[p]===255)addedOnFrames++;if(a[p]===255&&b[p]===0)removedOnFrames++;}return {beforeAttacks,afterAttacks,lostAttacks,addedOnFrames,removedOnFrames,examples};}
const report={version:'1.2.0',sourceSha256:{},tracks:{},synthetic:{},source:'https://github.com/teslamotors/light-show',limits:{liftgateOpenSeconds:14,liftgateCloseSeconds:4,windowTravelSeconds:4,mirrorAndChargeTravelSeconds:2,windowActuations:6,trunkActuations:6,mirrorActuations:20,chargeActuations:3,recommendedDanceSeconds:30,booleanMinimumOnMs:15,booleanPleasingOnOffMs:100,rampCodes:[0,26,51,77,178,204,230,255]}};
for(const f of ['engine/show-engine.js','analysis/dsp.js','analysis/worker.js'])report.sourceSha256[f]=crypto.createHash('sha256').update(fs.readFileSync(root+'/'+f)).digest('hex');
for(const name of ['demo','sample'])if(fs.existsSync(output+'baseline-'+name+'-music.json')){
 const m=JSON.parse(fs.readFileSync(output+'baseline-'+name+'-music.json')),raw=JSON.parse(fs.readFileSync(output+'baseline-'+name+'-activations.json'));
 report.tracks[name]=metrics(m,Engine.generate(m,{dance:'expressive',sensitivity:.82}),raw);report.tracks[name].booleanCleanup=cleanupDiagnostics(m);
}
function fixture(){const duration=40,beats=Array.from({length:80},(_,i)=>i*.5);return {duration,bpm:120,meter:4,beatConfidence:1,beats,downbeats:beats.filter((_,i)=>i%4===0),onsets:beats.map(time=>({time,band:'bass',strength:1})),sections:[{start:0,end:duration,energy:.9,label:'Groove'}],waveform:Array(2000).fill(.9),energy:Array(2000).fill(.9),energyStep:.02};}
let m=fixture();m.waveform.fill(0,1000,1400);m.energy.fill(0,1000,1400);m.beats=m.beats.filter(t=>t<20||t>=28);m.downbeats=m.downbeats.filter(t=>t<20||t>=28);m.onsets=m.onsets.filter(o=>o.time<20||o.time>=28);let show=Engine.generate(m,{dance:'off',sensitivity:0});
let lit=[];for(let f=1050;f<1350;f++)if(Array.from(show.frames.subarray(f*200,f*200+30)).some(v=>v>127))lit.push(round(f*.02));report.synthetic.trueSilenceWithinLoudSection={silence:[20,28],examined:[21,27],litFrameCount:lit.length,firstLitSeconds:lit.slice(0,12),reason:'One invented midpoint pulse bridges the omitted beat gap; section-average energy overrides local silence. Interior base gain also stays lit.'};
m=fixture();m.duration=10;m.beats=m.beats.filter(t=>t<10);m.downbeats=m.downbeats.filter(t=>t<10);m.onsets=m.onsets.filter(o=>o.time<10);m.sections[0].end=10;m.waveform=Array(500).fill(.9);m.energy=m.waveform.slice();show=Engine.generate(m,{dance:'off',style:'pulse',sensitivity:1});report.synthetic.endingAttack={beatSeconds:9,rawInnerCommandAtBeat:show.frames[450*200+2],expectedAccent:255,actualCommandMeaning:'77 =2-second ramp off',reason:'Unconditional ending ramp overwrites supported lamp accents across final2.15s.'};
fs.writeFileSync(output+'baseline-diagnostics.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({tracks:Object.fromEntries(Object.entries(report.tracks).map(([k,v])=>[k,{...v,movements:v.movements.length}])),synthetic:report.synthetic},null,2));

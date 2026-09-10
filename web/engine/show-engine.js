/* LightForge — offline music-to-Tesla choreography.
 * Vehicle profile: 2025 Model 3 Long Range RWD, North America.
 * Reference: https://github.com/teslamotors/light-show (reviewed 2026-09-05).
 * This is a deterministic musical arrangement engine, not a hosted AI model.
 */
(function (root) {
  'use strict';
  const VERSION = (root.LightForgeVersion || require('../version.js')).name;
  const CUES = root.MusicCues || (typeof require === 'function' ? require('./music-cues.js') : null);
  const SYNC = root.SyncReview || (typeof require === 'function' ? require('./sync-review.js') : null);
  const QUALITY = root.ChoreographyQuality || (typeof require === 'function' ? require('./choreography-quality.js') : null);
  const SEMANTIC_CHOREOGRAPHY = root.SemanticChoreography || (typeof require === 'function' ? require('./semantic-choreography.js') : null);
  const VOCAL_CHOREOGRAPHY = root.VocalChoreography || (typeof require === 'function' ? require('./vocal-choreography.js') : null);
  const PROFILE = root.VehicleProfile || (typeof require === 'function' ? require('./vehicle-profile.js') : null);
  const LIGHTS = root.LightPlanner || (typeof require === 'function' ? require('./light-planner.js') : null);
  const MOVEMENT = root.MovementPlanner || (typeof require === 'function' ? require('./movement-planner.js') : null);
  const CHANNELS = 200;
  const COMMAND = Object.freeze({Idle: 0, Open: 63, Dance: 127, Close: 191, Stop: 255});
  const COMMAND_NAME = Object.freeze({0: 'Idle', 63: 'Open', 127: 'Dance', 191: 'Close', 255: 'Stop'});
  const channelMap = Object.freeze({
    1:'Left outer beam',2:'Right outer beam',3:'Left inner beam',4:'Right inner beam',
    5:'Left signature',6:'Right signature',7:'Left channel 4',8:'Right channel 4',
    9:'Left channel 5',10:'Right channel 5',11:'Left channel 6',12:'Right channel 6',
    13:'Left front turn',14:'Right front turn',15:'Left front fog',16:'Right front fog',
    17:'Left auxiliary park',18:'Right auxiliary park',19:'Left side marker',20:'Right side marker',
    21:'Left side repeater',22:'Right side repeater',23:'Left rear turn',24:'Right rear turn',
    25:'Brake lights',26:'Left tail',27:'Right tail',28:'Reverse lights',29:'Rear fog',30:'License plate',
    35:'Left mirror',36:'Right mirror',37:'Left front window',38:'Left rear window',
    39:'Right front window',40:'Right rear window',41:'Trunk',46:'Charge port',
    176:'Display red',177:'Display green',178:'Display blue',179:'Right rear red',180:'Right rear green',181:'Right rear blue',
    182:'Right front red',183:'Right front green',184:'Right front blue',185:'Center front red',186:'Center front green',187:'Center front blue',
    188:'Left front red',189:'Left front green',190:'Left front blue',191:'Left rear red',192:'Left rear green',193:'Left rear blue'
  });
  const groups = Object.freeze({
    leftFront:[1,3,5,7,9,11],rightFront:[2,4,6,8,10,12],front:[1,2,3,4,5,6,7,8,9,10,11,12],
    leftRear:[26,30],rightRear:[27,28],rear:[25,26,27,28,30],leftAmber:[13,21,23],rightAmber:[14,22,24],
    amber:[13,14,21,22,23,24],sides:[17,18,19,20],signatures:[5,6],windows:[37,38,39,40],mirrors:[35,36],
    interior:[176,179,182,185,188,191]
  });
  const ABSENT = new Set([15,16,29]);
  const RAMP = new Set([3,4,5,6,7,8,9,10,11,12,13,14]);
  const RAMP_CODES = new Set([0,26,51,77,178,204,230,255]);
  const CLOSURES = [35,36,37,38,39,40,41,46];
  const PALETTES = Object.freeze({aurora:[[0,220,255],[230,10,255],[0,255,150]],neon:[[25,150,255],[255,20,165],[110,255,40]],fire:[[255,55,10],[255,185,5],[255,10,75]],ice:[[65,225,255],[115,100,255],[195,255,255]],monochrome:[[255,255,255],[125,155,195],[220,240,255]]});
  const previewCache = new WeakMap();
  const clamp = (x,a=0,b=1) => Math.max(a,Math.min(b,x));
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const quant = (t,step) => Math.floor(t/step+0.5+1e-8);
  const lowerBound = (arr,t,key) => {let l=0,r=arr.length;while(l<r){const m=(l+r)>>>1;if((key?arr[m][key]:arr[m])<t)l=m+1;else r=m;}return l;};
  const nearest = (arr,t) => {if(!arr.length)return t;const i=lowerBound(arr,t);if(!i)return arr[0];if(i===arr.length)return arr[i-1];return t-arr[i-1]<arr[i]-t?arr[i-1]:arr[i];};
  function random(seed) {let a=seed>>>0;return () => {a+=0x6D2B79F5;let t=a;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296;};}
  function normalizeMusic(music, warnings) {
    if(!music || !finite(music.duration) || music.duration<=0)throw new Error('Choose a decodable audio track with a positive duration.');
    if(music.duration>14400)throw new Error('Tesla light shows cannot exceed four hours. Choose a shorter track.');
    const duration=music.duration;
    const times = data => Array.from(new Set(Array.from(data||[]).filter(t=>finite(t)&&t>=0&&t<duration))).sort((a,b)=>a-b);
    let bpm=finite(music.bpm)&&music.bpm>=20&&music.bpm<=400?music.bpm:120;
    let beats=times(music.beats);
    const onsets=Array.from(music.onsets||[]).filter(o=>o&&finite(o.time)&&o.time>=0&&o.time<duration&&finite(o.strength)).map(o=>({time:o.time,strength:clamp(o.strength,0,1),band:['bass','mid','high'].includes(o.band)?o.band:'mid'})).sort((a,b)=>a.time-b.time);
    const waveform=Array.from(music.waveform||[]).map(x=>finite(x)?clamp(Math.abs(x),0,1):0);
    let sections=Array.from(music.sections||[]).filter(s=>s&&finite(s.start)&&s.start>=0&&s.start<duration).map((s,i)=>({start:s.start,end:finite(s.end)?clamp(s.end,s.start,duration):duration,energy:clamp(finite(s.energy)?s.energy:.55,0,1),label:String(s.label||'Section '+(i+1)).slice(0,100),recurrenceGroup:typeof s.recurrenceGroup==='string'?s.recurrenceGroup.slice(0,80):null,similarity:clamp(finite(s.similarity)?s.similarity:0,0,1),repetitionIndex:Math.max(0,Math.floor(Number(s.repetitionIndex)||0))})).sort((a,b)=>a.start-b.start);
    if(!sections.length)sections=[{start:0,end:duration,energy:.55,label:'Main'}];
    const clean=[];
    for(const s of sections){if(clean.length&&s.start-clean[clean.length-1].start<.001)clean[clean.length-1]=s;else clean.push(s);}
    sections=clean;
    if(sections[0].start>0)sections.unshift({start:0,end:sections[0].start,energy:sections[0].energy*.7,label:'Opening'});
    for(let i=0;i<sections.length;i++){sections[i].end=i+1<sections.length?sections[i+1].start:duration;sections[i].index=i;}
    let peak=0;for(const x of waveform)peak=Math.max(peak,x);
    const silent=waveform.length?peak<1e-6:(!onsets.some(o=>o.strength>.001)&&sections.every(s=>s.energy===0));
    if(beats.length<2&&!silent){beats=[];for(let t=0;t<duration;t+=60/bpm)beats.push(t);warnings.push('No stable beat grid was supplied. A regular tempo grid is used; review the preview and tempo before export.');}
    const meter=music.meter===3?3:4;
    let downbeats=times(music.downbeats);if(!downbeats.length)downbeats=beats.filter((_,i)=>i%meter===0);
    const confidence=finite(music.beatConfidence)?clamp(music.beatConfidence,0,1):0;
    if(confidence<.4&&!silent)warnings.push('Beat confidence is low. Check the beat grid and timing offset against the music.');
    if(silent)warnings.push('This audio is silent. The exported sequence intentionally keeps all outputs off.');
    const ranges=Array.isArray(music.activityRanges)?music.activityRanges.filter(x=>x&&finite(x.start)&&finite(x.end)&&x.end>x.start).map(x=>({start:clamp(x.start,0,duration),end:clamp(x.end,0,duration)})).sort((a,b)=>a.start-b.start):null;
    const phrases=Array.from(music.phrases||[]).filter(x=>x&&finite(x.start)&&finite(x.end)&&x.end>x.start&&x.start<duration).map(x=>({...x,start:clamp(x.start,0,duration),end:clamp(x.end,0,duration),energy:clamp(x.energy||0,0,1),confidence:clamp(x.confidence||0,0,1)})).sort((a,b)=>a.start-b.start);
    const impacts=Array.from(music.impacts||[]).filter(x=>x&&finite(x.time)&&x.time>=0&&x.time<duration&&finite(x.strength)).map(x=>({...x,strength:clamp(x.strength,0,1)})).sort((a,b)=>a.time-b.time);
    const energy=Array.from(music.energy||[]).map(x=>finite(x)?clamp(x,0,1):0),energyStep=finite(music.energyStep)&&music.energyStep>0?music.energyStep:.02;
    const beatDetails=Array.from(music.beatDetails||[]).filter(x=>x&&finite(x.time)&&x.time>=0&&x.time<duration).map(x=>({...x}));
    const groove=music.groove&&typeof music.groove==='object'?{feel:['swing','straight','free'].includes(music.groove.feel)?music.groove.feel:'straight',subdivisionRatio:clamp(finite(music.groove.subdivisionRatio)?music.groove.subdivisionRatio:.5,.5,.75),confidence:clamp(finite(music.groove.confidence)?music.groove.confidence:0,0,1)}:{feel:'straight',subdivisionRatio:.5,confidence:0};
    // Source roles are explicit analysis products. Mid-band and low-band flux
    // remain generic spectral attacks; neither is promoted to singing or notes.
    const roleEvents=(items)=>Array.from(items||[]).filter(x=>x&&finite(x.start)&&finite(x.end)&&x.start>=0&&x.end>x.start&&x.start<duration&&finite(x.confidence)).map(x=>({start:x.start,end:Math.min(duration,x.end),confidence:clamp(x.confidence,0,1),strength:clamp(finite(x.strength)?x.strength:.6,0,1),...(finite(x.peakTime)?{peakTime:clamp(x.peakTime,x.start,Math.min(duration,x.end))}:{}),...(finite(x.accentTime)?{accentTime:clamp(x.accentTime,x.start,Math.min(duration,x.end))}:{}),...(finite(x.midi)?{midi:clamp(x.midi,0,127)}:{}),...(finite(x.frequency)?{frequency:Math.max(0,x.frequency)}:{})})).sort((a,b)=>a.start-b.start);
    const envelope=(input,step)=>Array.from(input||[]).slice(0,Math.ceil(duration/step)+1).map(x=>finite(x)?clamp(x,0,1):0);
    const voice=music.vocals&&typeof music.vocals==='object'?music.vocals:{},vocalStep=finite(voice.envelopeStep)&&voice.envelopeStep>=.005?voice.envelopeStep:.02;
    const separatedVoice=voice.source==='separated-vocals'&&voice.sourceSeparated===true;
    const phraseEvidence=new Map(Array.from(voice.phrases||[]).filter(Boolean).map(p=>[p.start,p]));
    const vocalPhrases=roleEvents(voice.phrases).map(p=>{const evidence=phraseEvidence.get(p.start)||{};return {...p,kind:['singing','speech','vocal'].includes(evidence.kind)?evidence.kind:'vocal',evidenceMode:separatedVoice&&evidence.evidenceMode==='separation-led'?'separation-led':'classifier-supported',stemEnergyRatio:clamp(finite(evidence.stemEnergyRatio)?evidence.stemEnergyRatio:0,0,1)};});
    const contour=voice.pitchContour&&typeof voice.pitchContour==='object'?voice.pitchContour:{},contourStep=finite(contour.step)&&contour.step>=.02?contour.step:.04;
    const vocals={available:voice.available===true,presence:['detected','not_detected','uncertain'].includes(voice.presence)?voice.presence:'uncertain',method:String(voice.method||'unavailable').slice(0,200),model:voice.model||null,source:separatedVoice?'separated-vocals':'mixture-estimate',sourceSeparated:separatedVoice,lyricsAligned:false,confidence:clamp(finite(voice.confidence)?voice.confidence:0,0,1),phrases:vocalPhrases,notes:separatedVoice?roleEvents(voice.notes).filter(x=>finite(x.midi)&&x.end-x.start>=.10).map(x=>({...x,type:x.end-x.start>=.35?'held-note':'note',estimated:true})):[],accents:Array.from(voice.accents||[]).filter(x=>x&&finite(x.time)&&x.time>=0&&x.time<duration&&finite(x.confidence)&&finite(x.strength)).map(x=>({time:x.time,confidence:clamp(x.confidence,0,1),strength:clamp(x.strength,0,1),estimated:true,source:separatedVoice&&x.source==='separated-vocals'?'separated-vocals':'mixture-estimate',kind:['entrance','syllabic-accent'].includes(x.kind)?x.kind:'contour'})).sort((a,b)=>a.time-b.time),pitchContour:separatedVoice?{step:contourStep,midi:Array.from(contour.midi||[]).slice(0,Math.ceil(duration/contourStep)+1).map(x=>finite(x)?clamp(x,0,127):0),confidence:envelope(contour.confidence,contourStep)}:null,envelope:envelope(voice.envelope,vocalStep),envelopeStep:vocalStep,timing:voice.timing||{}};
    const bass=music.bassAnalysis&&typeof music.bassAnalysis==='object'?music.bassAnalysis:{},bassStep=finite(bass.envelopeStep)&&bass.envelopeStep>=.005?bass.envelopeStep:.02;
    const bassNotes=roleEvents(music.bassNotes).filter(x=>finite(x.midi)||finite(x.frequency)&&x.frequency>0),bassAnalysis={method:String(bass.method||'unavailable').slice(0,200),source:String(bass.source||'mixture-estimate').slice(0,100),confidence:clamp(finite(bass.confidence)?bass.confidence:0,0,1),phrases:roleEvents(bass.phrases),envelope:envelope(bass.envelope,bassStep),envelopeStep:bassStep};
    return {duration,bpm,beats,downbeats,groove,vocals,bassNotes,bassAnalysis,onsets,waveform,sections,silent,beatConfidence:confidence,meter,meterConfidence:clamp(music.meterConfidence||0,0,1),phrases,impacts,activityRanges:ranges,energy,energyStep,beatDetails,analysisVersion:Number(music.analysisVersion)||1,timing:music.timing||{}};
  }
  const SALIENCE_TIERS=new Set(['micro','secondary','primary','phrase','structural','climax']);
  function semanticTimelineFingerprint(timeline){
    let hash=2166136261;
    const append=value=>{const text=value===undefined?'':value===null?'~':(finite(value)?String(Math.round(value*1000000)/1000000):String(value));for(let index=0;index<text.length;index++)hash=Math.imul(hash^text.charCodeAt(index),16777619);hash=Math.imul(hash^255,16777619);};
    append(timeline.schemaVersion);append(timeline.duration);append(timeline.clock);
    for(const event of timeline.events){
      append(event.id);append(event.type);append(event.time);append(event.duration);append(event.source);append(event.confidence);append(event.intensity);append(event.salience);
      append(event.rhythm?.barPosition);append(event.rhythm?.beatTime);append(event.structure?.sectionIndex);append(event.structure?.phraseIndex);
      append(event.relationships?.crossStemAgreement);append(event.recurrenceGroup);append(event.repetitionIndex);
    }
    return ('00000000'+(hash>>>0).toString(16)).slice(-8);
  }
  function matchingSemanticSalience(music){
    const timeline=music&&music.semanticTimeline,salience=music&&music.musicSalience;
    if(!timeline||!salience||!Number.isInteger(timeline.schemaVersion)||!finite(timeline.duration)||timeline.duration<=0||typeof timeline.clock!=='string'||!Array.isArray(timeline.events)||salience.schemaVersion!==1||salience.timelineSchemaVersion!==timeline.schemaVersion||salience.clock!==timeline.clock||!finite(salience.duration)||Math.abs(salience.duration-timeline.duration)>1e-6||typeof salience.timelineFingerprint!=='string'||!/^[0-9a-f]{8}$/.test(salience.timelineFingerprint)||salience.timelineFingerprint!==semanticTimelineFingerprint(timeline)||!Array.isArray(salience.events)||salience.events.length!==timeline.events.length)return null;
    const ids=new Set(),events=[];
    for(let index=0;index<timeline.events.length;index++){
      const event=timeline.events[index],ranked=salience.events[index];
      if(!event||typeof event.id!=='string'||!event.id||ids.has(event.id)||!finite(event.time)||event.time<0||event.time>timeline.duration||!ranked||ranked.id!==event.id||!finite(ranked.score)||ranked.score<0||ranked.score>1||!SALIENCE_TIERS.has(ranked.tier)||!Number.isInteger(ranked.rank)||ranked.rank<1)return null;
      ids.add(event.id);events.push({id:event.id,time:event.time,source:typeof event.source==='string'?event.source:'',score:ranked.score,tier:ranked.tier});
    }
    return {clock:timeline.clock,timelineSchemaVersion:timeline.schemaVersion,musicSalienceSchemaVersion:salience.schemaVersion,timelineFingerprint:salience.timelineFingerprint,events};
  }
  function nearestSalienceEvent(events,time,role,windowSeconds){
    if(!finite(time))return null;
    const preferred=role==='vocals'?'vocals':role==='bass'?'bass':null;let best=null;
    for(const event of events){
      const distance=Math.abs(event.time-time);if(distance>windowSeconds+1e-9)continue;
      const candidate={event,distance,preferred:preferred&&event.source===preferred?0:1};
      if(!best||candidate.distance<best.distance-1e-9||Math.abs(candidate.distance-best.distance)<=1e-9&&(candidate.preferred<best.preferred||candidate.preferred===best.preferred&&(candidate.event.score>best.event.score+1e-9||Math.abs(candidate.event.score-best.event.score)<=1e-9&&(candidate.event.time<best.event.time-1e-9||Math.abs(candidate.event.time-best.event.time)<=1e-9&&candidate.event.id<best.event.id))))best=candidate;
    }
    return best;
  }
  function annotateSalienceTargets(music,lightTargets,movementTargets,settings){
    const semantic=matchingSemanticSalience(music);if(!semantic)return null;
    const offset=finite(settings&&settings.offsetMs)?settings.offsetMs/1000:0,windowSeconds=Math.max(.08,(finite(settings&&settings.stepMs)?settings.stepMs:20)/1000*4);
    const annotate=(targets,kind)=>{
      const copied=[],records=[],qualityTargets=[];
      for(let index=0;index<(targets||[]).length;index++){
        const target=targets[index];
        if(!target||!finite(target.time)){copied.push(target);continue;}
        const musicTime=kind==='movement'?(finite(target.musicTime)?target.musicTime:target.time-offset):target.time;
        const match=nearestSalienceEvent(semantic.events,musicTime,target.role,windowSeconds);
        if(!match){copied.push(target);continue;}
        const deltaMs=Math.round((musicTime-match.event.time)*1000000)/1000;
        const record={targetIndex:index,targetTime:target.time,musicTime,semanticEventId:match.event.id,semanticEventTime:match.event.time,deltaMs,score:match.event.score,tier:match.event.tier};
        const annotated=Object.assign({},target,{salience:match.event.score,tier:match.event.tier,semanticEventId:match.event.id,semanticEventTime:match.event.time,semanticDeltaMs:deltaMs});
        copied.push(annotated);records.push(record);
        const qualityTarget=Object.assign({},annotated,{time:kind==='lighting'?target.time+offset:target.time});
        if(finite(target.end))qualityTarget.end=kind==='lighting'?target.end+offset:target.end;
        qualityTargets.push(qualityTarget);
      }
      return {copied,records,qualityTargets};
    };
    const light=annotate(lightTargets,'lighting'),movement=annotate(movementTargets,'movement');
    return {syncLightTargets:light.copied,syncMovementTargets:movement.copied,qualityTargets:light.qualityTargets.concat(movement.qualityTargets),public:{schemaVersion:1,clock:semantic.clock,timelineSchemaVersion:semantic.timelineSchemaVersion,musicSalienceSchemaVersion:semantic.musicSalienceSchemaVersion,timelineFingerprint:semantic.timelineFingerprint,matchWindowMs:windowSeconds*1000,light:light.records,movement:movement.records}};
  }
  function sceneSeed(seed,key){let value=seed>>>0;for(let i=0;i<key.length;i++)value=Math.imul(value^key.charCodeAt(i),16777619)>>>0;return value;}
  function correctVocalRegions(m,s){
    if(!s.vocalRegions.length)return m;
    const regions=s.vocalRegions.map(x=>({...x,end:Math.min(x.end,m.duration)})).filter(x=>x.start<m.duration&&x.end>x.start);
    const remove=(items,spans)=>{let result=items.map(x=>({...x}));for(const r of spans){const next=[];for(const p of result){if(p.end<=r.start||p.start>=r.end){next.push(p);continue;}if(p.start<r.start)next.push({...p,end:r.start});if(p.end>r.end)next.push({...p,start:r.end});}result=next;}return result.filter(p=>p.end-p.start>=.10).map(p=>({...p,...(finite(p.peakTime)?{peakTime:clamp(p.peakTime,p.start,p.end)}:{})}));};
    const silent=regions.filter(x=>x.kind==='instrumental'),manual=regions.filter(x=>x.kind==='voice');
    // User guides replace phrase ownership within the marked range, while
    // existing measured notes/articulations remain evidence, never inventions.
    const phrases=remove(m.vocals.phrases,regions).concat(manual.map(r=>({start:r.start,end:r.end,confidence:1,strength:.7,kind:'vocal',manual:true}))).sort((a,b)=>a.start-b.start);
    const vocals={...m.vocals,phrases,notes:remove(m.vocals.notes,silent),accents:m.vocals.accents.filter(a=>!silent.some(r=>a.time>=r.start&&a.time<r.end)),available:m.vocals.available||manual.length>0,presence:phrases.length?'detected':'not_detected',manualRegions:regions};
    return {...m,vocals};
  }
  function correctRhythm(m,s){
    const scale=s.tempoScale,meter=s.meterOverride||m.meter,requested=s.downbeatAnchor;
    const correction={tempoScale:scale,meterOverride:s.meterOverride,downbeatAnchor:requested,snappedAnchor:null};
    if(scale===1&&meter===m.meter&&requested===null)return {...m,rhythmCorrection:correction};
    let beats=m.beats.slice(),anchor=requested===null?(m.downbeats[0]??beats[0]??0):clamp(requested,0,m.duration);
    if(scale===2){const doubled=[];for(let i=0;i<beats.length;i++){doubled.push(beats[i]);if(i+1<beats.length)doubled.push((beats[i]+beats[i+1])/2);}beats=doubled;}
    else if(scale===.5&&beats.length){const near=nearest(beats,anchor),phase=beats.indexOf(near)%2;beats=beats.filter((_,i)=>i%2===phase);}
    const chosen=beats.length?nearest(beats,anchor):0,index=beats.indexOf(chosen),downbeats=beats.filter((_,i)=>((i-index)%meter+meter)%meter===0);
    correction.snappedAnchor=beats.length?chosen:null;
    const beatDetails=beats.map((time,i)=>({time,confidence:m.beatConfidence,barPosition:((i-index)%meter+meter)%meter+1,localBpm:60/(i+1<beats.length?beats[i+1]-time:i?time-beats[i-1]:60/(m.bpm*scale)),corrected:true}));
    return {...m,beats,downbeats,beatDetails,meter,bpm:m.bpm*scale,groove:scale===1?m.groove:{feel:'straight',subdivisionRatio:.5,confidence:0},rhythmCorrection:correction};
  }
  function normalizeSettings(input) {
    input=input||{};
    if(input.stepMs!==undefined&&![15,20].includes(Number(input.stepMs)))throw new Error('Choose a 20 ms recommended frame interval or 15 ms precision mode.');
    const number=(key,def,min,max)=>clamp(finite(input[key])?input[key]:def,min,max);
    return {stepMs:Number(input.stepMs)||20,sensitivity:number('sensitivity',.8,0,1),intensity:number('intensity',.85,0,1),
      musicCues:CUES.normalize(input.musicCues),vocalOffsetMs:number('vocalOffsetMs',0,-2000,2000),bassOffsetMs:number('bassOffsetMs',0,-2000,2000),movementDensity:number('movementDensity',.7,0,1),vocalFocus:number('vocalFocus',.85,0,1),bassFocus:number('bassFocus',.9,0,1),vocalRegions:normalizeVocalRegions(input.vocalRegions),downbeatAnchor:finite(input.downbeatAnchor)&&input.downbeatAnchor>=0?input.downbeatAnchor:null,meterOverride:[3,4].includes(input.meterOverride)?input.meterOverride:null,tempoScale:[.5,1,2].includes(input.tempoScale)?input.tempoScale:1,
      dance:['expressive','balanced','off'].includes(input.dance)?input.dance:'expressive',style:['festival','cinematic','pulse'].includes(input.style)?input.style:'festival',
      seed:finite(input.seed)?input.seed>>>0:666,palette:PALETTES[input.palette]?input.palette:'aurora',
      beatDivision:['auto','quarter','eighth'].includes(input.beatDivision)?input.beatDivision:'auto',offsetMs:number('offsetMs',0,-2000,2000),semanticChoreography:input.semanticChoreography===true,vocalChoreography:input.vocalChoreography===true,
      enabled:Object.assign({windows:true,mirrors:true,trunk:true,charge:true,interior:true},input.enabled||{}),optionalFog:false,
      outerBeamRamping:input.outerBeamRamping===true,outputEnabled:normalizeOutputEnabled(input.outputEnabled),manualCues:normalizeManualCues(input.manualCues,input.outerBeamRamping===true),
      sectionOverrides:input.sectionOverrides&&typeof input.sectionOverrides==='object'?input.sectionOverrides:{},
      ...(input.vehicleTimingCalibration===undefined?{}:{vehicleTimingCalibration:PROFILE.normalizePerceptualCalibration(input.vehicleTimingCalibration)})};
  }
  function outputById(id) {return PROFILE && PROFILE.outputs.find(output=>output.id===id);}
  function normalizeVocalRegions(input){
    if(input===undefined||input===null)return [];
    if(!Array.isArray(input)||input.length>1000)throw new Error('Use at most 1,000 voice guides per project.');
    const result=input.map(r=>{if(!r||!finite(r.start)||!finite(r.end)||r.start<0||r.end<=r.start||!['voice','instrumental'].includes(r.kind))throw new Error('A voice guide needs a valid start, end, and Voice or Instrumental choice.');return {start:r.start,end:r.end,kind:r.kind};}).sort((a,b)=>a.start-b.start);
    for(let i=1;i<result.length;i++)if(result[i].start<result[i-1].end)throw new Error('Voice guides must not overlap. Clear the existing guide before replacing it.');
    return result;
  }
  function normalizeOutputEnabled(input) {
    if(input===undefined || input===null)return {};
    if(typeof input!=='object'||Array.isArray(input))throw new Error('The saved output switches are damaged.');
    const result={};
    for(const id of Object.keys(input)){
      if(!outputById(id))throw new Error('Unknown vehicle output: '+id+'.');
      if(typeof input[id]!=='boolean')throw new Error('Choose Include in show or Off for '+outputById(id).name+'.');
      result[id]=input[id];
    }
    return result;
  }
  function normalizeManualCues(input,outerBeamRamping) {
    if(input===undefined||input===null)return [];
    if(!Array.isArray(input)||input.length>10000)throw new Error('Use at most 10,000 manual cues per project.');
    const ids=new Set();
    return input.map((item,index)=>{
      if(!item||typeof item!=='object')throw new Error('Manual cue '+(index+1)+' is damaged.');
      const output=outputById(item.outputId),name=output?output.name:'cue '+(index+1);
      if(!output)throw new Error('Manual cue '+(index+1)+' references an unknown vehicle output.');
      if(output.available===false)throw new Error(output.name+' is not available on this Model 3 Highland profile.');
      if(!finite(item.start)||!finite(item.end)||item.start<0||item.end<=item.start)throw new Error(name+': enter an end time after the start time.');
      const id=typeof item.id==='string'&&item.id.length<=100?item.id:'cue-'+index;
      if(ids.has(id))throw new Error('Each manual cue must have a unique identifier.');ids.add(id);
      const cue={id,outputId:output.id,start:item.start,end:item.end,label:String(item.label||output.name).slice(0,100)};
      if(output.mode==='rgb'){
        if(!Array.isArray(item.rgb)||item.rgb.length!==3||item.rgb.some(v=>!Number.isInteger(v)||v<0||v>255))throw new Error(name+': choose a valid RGB color.');
        cue.rgb=item.rgb.slice();
      }else{
        if(!Number.isInteger(item.value))throw new Error(name+': choose a supported command.');
        const allowed=output.mode==='closure'?[0,63,127,191,255]:(output.mode==='ramp'||outerBeamRamping&&output.channels.every(ch=>ch<=2))?Array.from(RAMP_CODES):[0,255];
        if(!allowed.includes(item.value))throw new Error(name+': this command is not supported.');
        if(output.mode==='closure'&&item.value===127&&output.channels.some(c=>c===35||c===36))throw new Error(name+': mirrors use Fold and Unfold; they do not support Dance.');
        cue.value=item.value;
      }
      return cue;
    });
  }
  function applyManualCues(show) {
    const {frames,frameCount:n,settings:s}=show,step=show.stepMs/1000,byOutput=new Map();
    for(const cue of s.manualCues){
      const output=outputById(cue.outputId),a=quant(cue.start,step),b=Math.min(n-1,quant(cue.end,step));
      if(cue.end>show.audioDuration+1e-7)throw new Error(output.name+': the cue ends after the music.');
      if(a<0||a>=n-1||b<=a)throw new Error(output.name+': the cue must contain at least one frame before the final off frame.');
      const track=byOutput.get(output.id)||[];
      if(track.some(other=>a<other.b&&b>other.a))throw new Error(output.name+': manual cues overlap. Move or shorten one cue.');
      track.push({cue,a,b});byOutput.set(output.id,track);
    }
    for(const [id,track] of byOutput){
      const output=outputById(id);
      if(output.mode==='closure'){
        for(const ch of output.channels)for(let f=0;f<n;f++)frames[f*200+ch-1]=0;
        show.movements=show.movements.map(event=>Object.assign({},event,{channels:event.channels.filter(c=>!output.channels.includes(c))})).filter(event=>event.channels.length);
      }
      for(const {cue,a,b} of track){
        for(let i=0;i<output.channels.length;i++){
          const ch=output.channels[i],value=cue.rgb?cue.rgb[i%3]:cue.value;
          for(let f=a;f<b;f++)frames[f*200+ch-1]=value;
        }
        if(output.mode==='closure')show.movements.push({channels:output.channels.slice(),start:a*step,end:b*step,value:cue.value,command:COMMAND_NAME[cue.value],label:cue.label,manual:true,cueId:cue.id});
      }
    }
    for(const output of PROFILE.outputs){
      if(output.available===false||s.outputEnabled[output.id]===false){
        for(const ch of output.channels)for(let f=0;f<n;f++)frames[f*200+ch-1]=0;
        if(output.mode==='closure')show.movements=show.movements.map(event=>Object.assign({},event,{channels:event.channels.filter(c=>!output.channels.includes(c))})).filter(event=>event.channels.length);
      }
    }
    frames.fill(0,(n-1)*200);
  }
  function generate(music, settings) {
    if(!LIGHTS||!MOVEMENT)throw new Error('The musical composition tools are unavailable. Restart the app.');
    const warnings=[],s=normalizeSettings(settings),m=correctRhythm(CUES.overlay(correctVocalRegions(CUES.apply(normalizeMusic(music,warnings),s),s),s),s);
    if(m.silent&&s.manualCues.length){const i=warnings.findIndex(w=>w.includes('This audio is silent.'));if(i>=0)warnings[i]='This audio is silent. Automatic choreography is disabled; your manual cues still play.';}
    const step=s.stepMs/1000,n=Math.ceil(m.duration/step-1e-9),duration=n*step;
    let frames;try{frames=new Uint8Array(n*CHANNELS);}catch(e){throw new Error('This track is too large for the available device memory. Choose a shorter track.');}
    const scenes=m.sections.map(section=>{
      const o=s.sectionOverrides[section.index]||{},key=section.recurrenceGroup||'section-'+section.index;
      const seed=finite(o.seed)?o.seed>>>0:sceneSeed(s.seed,key),variant=Math.floor(random(seed)()*6);
      return {style:['festival','cinematic','pulse'].includes(o.style)?o.style:s.style,intensity:finite(o.intensity)?clamp(o.intensity,0,1):s.intensity,variant,seed,locked:finite(o.seed),motifGroup:key};
    });
    const show={version:VERSION,vehicle:'2025 Tesla Model 3 Long Range RWD',channels:CHANNELS,channelCount:CHANNELS,frameCount:n,stepMs:s.stepMs,duration,audioDuration:m.duration,frames,
      movements:[],sections:m.sections.map((section,i)=>Object.assign({},section,scenes[i])),settings:s,stats:{},warnings};
    const semantic=matchingSemanticSalience(music);
    const semanticStrategy=s.semanticChoreography&&semantic&&SEMANTIC_CHOREOGRAPHY&&typeof SEMANTIC_CHOREOGRAPHY.create==='function'
      ?SEMANTIC_CHOREOGRAPHY.create(semantic,{stepMs:s.stepMs}):null;
    const vocalStrategy=s.vocalChoreography&&VOCAL_CHOREOGRAPHY&&typeof VOCAL_CHOREOGRAPHY.create==='function'
      ?VOCAL_CHOREOGRAPHY.create({music,normalizedMusic:m,settings:s},{enabled:true}):null;
    const movement=m.silent?{events:[],accents:[],targets:[],diagnostics:{selectedTargets:0}}:MOVEMENT.plan(m,s,PROFILE);
    for(const event of movement.events){
      const a=clamp(quant(event.start,step),0,n-1),b=clamp(quant(event.end,step),0,n-1);
      if(b<=a)continue;
      show.movements.push({...event,start:a*step,end:b*step});
      for(let f=a;f<b;f++)for(const ch of event.channels)frames[f*200+ch-1]=event.value;
    }
    const lighting=LIGHTS.compose(show,m,s,movement,semanticStrategy,vocalStrategy);
    const targetSalience=annotateSalienceTargets(music,lighting.targets,movement.targets,s),syncLightTargets=targetSalience?targetSalience.syncLightTargets:lighting.targets,syncMovementTargets=targetSalience?targetSalience.syncMovementTargets:movement.targets;
    if(!m.silent&&s.enabled.interior)paintInterior(show,m,s,lighting.context);
    applyManualCues(show);
    show.movements.sort((a,b)=>a.start-b.start||a.channels[0]-b.channels[0]);
    show.lightEvents=lighting.events;
    show.choreography={version:VERSION,analysisVersion:m.analysisVersion,meter:m.meter,meterConfidence:m.meterConfidence,phrases:m.phrases,impacts:m.impacts,targets:movement.targets,lighting:lighting.diagnostics,movement:movement.diagnostics,timing:m.timing,roles:{vocals:{available:m.vocals.available,presence:m.vocals.presence,confidence:m.vocals.confidence,method:m.vocals.method,phrases:m.vocals.phrases,accents:m.vocals.accents},bassNotes:m.bassNotes,bassAnalysis:{method:m.bassAnalysis.method,source:m.bassAnalysis.source,confidence:m.bassAnalysis.confidence,phrases:m.bassAnalysis.phrases}},rhythm:{beats:m.beats,downbeats:m.downbeats,meter:m.meter,bpm:m.bpm,groove:m.groove,correction:m.rhythmCorrection}};
    if(targetSalience)show.choreography.salienceTargets=targetSalience.public;
    if(s.semanticChoreography)show.choreography.semanticStrategy=lighting.diagnostics.semanticStrategy||{schemaVersion:1,requested:true,active:false,reason:semantic?'no-linkable-semantic-targets':'semantic-linkage-invalid'};
    if(s.vocalChoreography)show.choreography.vocalChoreography=lighting.diagnostics.vocalChoreography||{schemaVersion:1,requested:true,active:false,reason:VOCAL_CHOREOGRAPHY?'vocal-semantics-unavailable':'vocal-choreography-module-unavailable'};
    show.choreography.vocalDetail={phrases:m.vocals.phrases,notes:m.vocals.notes,accents:m.vocals.accents,sourceSeparated:m.vocals.sourceSeparated,source:m.vocals.source,presence:m.vocals.presence,manualRegions:m.vocals.manualRegions||[],lyricsAligned:false};
    show.stats={lightCues:lighting.events.length,manualCueCount:s.manualCues.length,beatCount:m.beats.length,onsetCount:m.onsets.length,bpm:m.bpm,beatConfidence:m.beatConfidence,beatLengthMs:60000/m.bpm,recommendedBeatDivision:m.bpm<=150?'eighth':'quarter',silent:m.silent,
      vocalPhraseCount:lighting.diagnostics.roles.vocals.eligibleEvents,bassNoteCount:lighting.diagnostics.roles.bass.eligibleEvents,vocalCues:lighting.diagnostics.roles.vocals.acceptedEvents,bassNoteCues:lighting.diagnostics.roles.bass.acceptedEvents,phraseCount:m.phrases.length,musicalImpactCount:m.impacts.length,movementTargets:movement.targets.length,lightQuantizationMaxMs:lighting.diagnostics.quantizationMaxMs};
    show.synchronization=SYNC.review(show,syncLightTargets,syncMovementTargets);
    if(QUALITY&&typeof QUALITY.evaluate==='function')show.choreography.quality=QUALITY.evaluate(show,targetSalience&&targetSalience.qualityTargets.length?{tierTargets:targetSalience.qualityTargets}:undefined);
    show.choreography.musicCues=m.musicCues;
    show.validation=validate(show,m);show.validation.synchronization=show.synchronization;show.stats=Object.assign(show.stats,show.validation.stats);
    if(!show.validation.valid)throw new Error('The generated show failed validation: '+show.validation.errors.join(' '));
    preparePreview(show);
    return show;
  }
  function paintInterior(show,m,s,ctx){
    const {frames,frameCount,stepMs}=show,step=stepMs/1000,palette=PALETTES[s.palette],separatedVoice=m.vocals.sourceSeparated===true;let bi=0,voiceLevel=0,bassLevel=0,pitchLevel=.5;
    for(let f=0;f<frameCount-1;f++){
      const time=f*step-s.offsetMs/1000;if(!ctx.active(time))continue;
      while(bi+1<m.beats.length&&m.beats[bi+1]<=time)bi++;
      const sec=ctx.sectionAt(time),scene=show.sections[sec.index],beat=m.beats[bi]||0,elapsed=Math.max(0,time-beat),period=ctx.periodAt(bi);
      const energy=ctx.energyAt(time),quiet=energy<.3||scene.style==='cinematic',bar=ctx.beatInfo(bi).bar,phrase=ctx.phraseAt(time);
      const pulse=Math.exp(-elapsed/(quiet?Math.min(period,.6):Math.min(period*.45,.26)));
      const gain=clamp((quiet?.1:.08)+pulse*(quiet?.45:.92))*clamp(energy*.95+.05)*(.3+.7*scene.intensity);
      const voice=ctx.vocalAt(time),bass=ctx.bassAt(time);
      // Separated PCM articulation receives a faster attack than legacy mixture
      // estimates. Melodic pitch shapes color and spatial emphasis continuously;
      // the original beat layer is retained in every scene.
      const sourceLed=voice?.evidenceMode==='separation-led',targetVoice=voice&&s.vocalFocus>0?ctx.roleEnvelope(m.vocals,time,voice.strength)*(sourceLed?.62:1):0,targetBass=bass&&s.bassFocus>0?ctx.roleEnvelope(m.bassAnalysis,time,bass.strength):0;
      voiceLevel+=(targetVoice-voiceLevel)*Math.min(1,step/(targetVoice>voiceLevel?(separatedVoice?.025:.10):(separatedVoice?.10:.22)));bassLevel+=(targetBass-bassLevel)*Math.min(1,step/(targetBass>bassLevel?.025:.10));
      const vocalNote=separatedVoice&&voice&&!sourceLed?ctx.vocalNoteAt(time):null,contour=m.vocals.pitchContour,ci=contour?Math.floor((time-(m.vocals.pitchOffset||0))/contour.step):-1,measuredPitch=sourceLed?null:contour?.confidence[ci]>=.45?contour.midi[ci]:vocalNote?.midi;
      if(measuredPitch>0)pitchLevel+=(clamp((measuredPitch-45)/36)-pitchLevel)*Math.min(1,step/.09);
      for(let zone=0;zone<6;zone++){
        const localBar=Math.max(0,ctx.beatInfo(bi).bar-ctx.beatInfo(Math.min(m.beats.length-1,lowerBound(m.beats,sec.start))).bar),pi=(Math.floor(localBar/2)+Math.floor(zone/2)+scene.variant)%palette.length,color=palette[pi],next=palette[(pi+1)%palette.length];
        const blend=quiet?clamp(elapsed/Math.max(period,.3),0,.5):clamp(elapsed/period,0,.25),balance=zone===0?.28:(quiet?.85:(bi-lowerBound(m.beats,sec.start)+zone)%3===0?1:.7);
        const focusedVoice=(zone===2||zone===3||zone===4)&&voice&&s.vocalFocus>0,focusedBass=(zone===1||zone===5)&&bass&&s.bassFocus>0;
        const noteAccent=vocalNote?Math.exp(-Math.max(0,time-vocalNote.start)/.16)*.10:0;
        const roleGain=focusedVoice?clamp(gain*(1-(separatedVoice?.60:.35)*s.vocalFocus)+(voiceLevel*(separatedVoice?.78:.58)+noteAccent)*s.vocalFocus*(.3+.7*scene.intensity)):focusedBass?clamp(gain*(1-.35*s.bassFocus)+bassLevel*s.bassFocus*.62*(.3+.7*scene.intensity)):gain;
        const voiceBlend=focusedVoice&&separatedVoice?pitchLevel*.52:blend,voiceBalance=focusedVoice&&separatedVoice?(zone===3?.72+.28*pitchLevel:zone===4?1-.28*pitchLevel:1):1;
        const start=groups.interior[zone]-1;for(let c=0;c<3;c++)frames[f*200+start+c]=Math.round((color[c]*(1-voiceBlend)+next[c]*voiceBlend)*roleGain*balance*voiceBalance);
      }
    }
  }
  function runs(show,ch){const result=[];const {frames,frameCount}=show;let start=0;while(start<frameCount){const value=frames[start*200+ch-1];let end=start+1;while(end<frameCount&&frames[end*200+ch-1]===value)end++;if(value!==0)result.push({start:start*show.stepMs/1000,end:end*show.stepMs/1000,value,command:COMMAND_NAME[value]});start=end;}return result;}
  function validate(show,music){
    const errors=[],warnings=Array.from(show&&show.warnings||[]),stats={};
    const error=s=>{if(!errors.includes(s))errors.push(s);};
    if(!show||!(show.frames instanceof Uint8Array))return {valid:false,errors:['Sequence data must be a Uint8Array.'],warnings,stats};
    if(show.channels!==200&&show.channelCount!==200)error('Sequence must contain 200 channels.');
    if(!Number.isInteger(show.frameCount)||show.frameCount<1||show.frames.length!==show.frameCount*200)error('Sequence length does not match its frame count.');
    if(!Number.isInteger(show.stepMs)||show.stepMs<15||show.stepMs>100)error('Frame interval must be 15–100 ms.');
    const duration=show.frameCount*show.stepMs/1000;
    if(!finite(duration)||duration>14400)error('Sequence duration exceeds the four-hour limit.');
    if(errors.length)return {valid:false,errors,warnings,stats};
    if(music&&finite(music.duration)&&(duration+1e-7<music.duration||duration-music.duration>show.stepMs/1000+1e-7))error('Audio and sequence duration do not match to one frame.');
    const frames=show.frames,n=show.frameCount,step=show.stepMs/1000,counts={},danceSeconds={};
    let activeFrames=0,lightTransitions=0,rampFrames=0,rgbFrames=0;
    for(let f=0;f<n;f++){
      const p=f*200;let active=false;
      for(let c=1;c<=30;c++){
        const v=frames[p+c-1];if(v>127)active=true;
        if(RAMP.has(c)||show.settings&&show.settings.outerBeamRamping&&c<=2){if(!RAMP_CODES.has(v))error('A ramp-capable lamp contains an unsupported command value.');if(v>0&&v<255)rampFrames++;}
        else if(v!==0&&v!==255)error('A boolean lamp contains an unsupported dimming value.');
        if(f&&v!==frames[p-200+c-1])lightTransitions++;
      }
      if(active)activeFrames++;
      if(frames[p+175]||frames[p+176]||frames[p+177])rgbFrames++;
      for(const ch of ABSENT)if(frames[p+ch-1])error(channelMap[ch]+' is not fitted to this North American Model 3 Highland profile.');
      for(let c=31;c<=200;c++){
        if(CLOSURES.includes(c)||c>=176&&c<=193)continue;
        if(frames[p+c-1]){error('An unsupported Model 3 channel is active.');break;}
      }
    }
    for(let c=0;c<200;c++)if(frames[(n-1)*200+c]){error('The last frame must turn every output off.');break;}
    for(const ch of CLOSURES){
      const events=runs(show,ch),limit=PROFILE.closureSpecifications[CLOSURE_KEYS[ch]].limit;
      let count=0,dance=0;
      for(const e of events){
        if(!COMMAND_NAME[e.value]){error(channelMap[ch]+' has an invalid movement command.');continue;}
        if([63,127,191].includes(e.value))count++;
        if(e.value===127){
          if(ch===35||ch===36)error('Mirrors do not support the Dance command.');
          dance+=e.end-e.start;
        }
      }
      // Follow actual command transitions, including Stop interruptions, short
      // Open/Close requests followed by Idle, and automatic charge-port close.
      // An Open does not require a four/14-second effect; the motor keeps going.
      const timeline=closureTimeline(show,ch);
      for(let i=1;i<timeline.length;i++){
        const entry=timeline[i];
        if(entry.command===COMMAND.Dance&&!entry.automatic&&!entry.acceptedDance){
          if(ch===41)error('Trunk dance starts before the trunk has time to open.');
          if(ch===46)error('Charge-port colors start before the port has time to open.');
        }
        if(ch===46&&entry.automatic&&entry.command===COMMAND.Dance)error('Charge-port use exceeds the automatic close window.');
      }
      counts[ch]=count;danceSeconds[ch]=Math.round(dance*1000)/1000;
      if(count>limit)error(channelMap[ch]+' exceeds its '+limit+'-command limit.');
      if(dance>PROFILE.closureSpecifications[CLOSURE_KEYS[ch]].danceSeconds+.001)error(channelMap[ch]+' exceeds the app’s 30-second dance budget. Shorten its Dance cues.');
      if(events.length){
        const final=motionAt(timeline[timeline.length-1].motion,duration-.04),target=ch<37?1:0;
        if(Math.abs(final.position-target)>.001||final.moving)error(channelMap[ch]+' must finish '+(target?'unfolded':'closed')+'. Add a final '+(target?'Open':'Close')+' cue with enough travel time.');
      }
    }
    Object.assign(stats,{frameCount:n,stepMs:show.stepMs,duration,sequenceBytes:frames.length,commandCounts:counts,danceSeconds,lightTransitions,activeExteriorPercent:Math.round(activeFrames/n*1000)/10,rampCommandFrames:rampFrames,interiorDisplayFrames:rgbFrames});
    return {valid:errors.length===0,errors,warnings:Array.from(new Set(warnings)),stats};
  }
  function fseqHeader(show,audioFilename='lightshow.wav'){
    const checked=validate(show);if(!checked.valid)throw new Error(checked.errors.join(' '));
    if(typeof audioFilename!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}\.(wav|mp3)$/i.test(audioFilename))throw new Error('Use a simple audio filename such as lightshow.wav.');
    const encoder=new TextEncoder(),media=encoder.encode(audioFilename+'\0'),producer=encoder.encode('LightForge '+VERSION+'\0');
    const fieldsLength=4+media.length+4+producer.length,offset=32+Math.ceil(fieldsLength/4)*4;
    const bytes=new Uint8Array(offset),view=new DataView(bytes.buffer);
    bytes.set([80,83,69,81],0);view.setUint16(4,offset,true);bytes[6]=0;bytes[7]=2;view.setUint16(8,32,true);view.setUint32(10,200,true);view.setUint32(14,show.frameCount,true);bytes[18]=show.stepMs;
    let p=32;for(const [code,payload] of [['mf',media],['sp',producer]]){view.setUint16(p,payload.length+4,true);bytes[p+2]=code.charCodeAt(0);bytes[p+3]=code.charCodeAt(1);bytes.set(payload,p+4);p+=4+payload.length;}
    // Reserved/compression fields and the optional UUID intentionally remain zero.
    return bytes;
  }
  function fseq(show,audioFilename='lightshow.wav'){
    const header=fseqHeader(show,audioFilename),bytes=new Uint8Array(header.length+show.frames.length);
    bytes.set(header);bytes.set(show.frames,header.length);return bytes;
  }
  // The simulator evaluates the command bytes that are exported, not musical
  // metadata. Tesla controls physical motors and does not publish dance travel
  // endpoints/cadence; those positions are explicitly marked as estimates.
  const CLOSURE_KEYS={35:'mirrorL',36:'mirrorR',37:'windowFL',38:'windowRL',39:'windowFR',40:'windowRR',41:'trunk',46:'charge'};
  const RAMP_SECONDS={26:.5,51:1,77:2,178:.5,204:1,230:2};
  function rampLevel(value,current,elapsed,target){
    const on=target===undefined?value>127:target,duration=RAMP_SECONDS[value]||0;
    return duration?clamp(current+(on?1:-1)*elapsed/duration,0,1):(on?1:0);
  }
  function movementDuration(channel,opening){const spec=PROFILE.closureSpecifications[CLOSURE_KEYS[channel]];return opening?spec.travel:spec.closeTravel;}
  function motionAt(motion,t){
    const elapsed=Math.max(0,t-motion.start);
    if(motion.kind==='hold')return {position:motion.from,moving:false,phase:0,direction:0};
    if(motion.kind==='travel'){
      const progress=motion.duration?clamp(elapsed/motion.duration,0,1):1;
      return {position:motion.from+(motion.target-motion.from)*progress,moving:progress<1,phase:progress,direction:progress<1?Math.sign(motion.target-motion.from):0};
    }
    // A deterministic travel estimate, deliberately independent of song BPM.
    // Dance endpoints are not exposed by Tesla's command protocol.
    const first=motion.first,firstDuration=Math.abs(first-motion.from)*(first>motion.from?motion.openSeconds:motion.closeSeconds);
    if(elapsed<firstDuration)return {position:motion.from+(first-motion.from)*elapsed/firstDuration,moving:true,phase:0,direction:Math.sign(first-motion.from)};
    const span=motion.high-motion.low,up=span*motion.openSeconds,down=span*motion.closeSeconds,period=up+down;
    const phase=(elapsed-firstDuration)%period;
    if(first===motion.high){
      return phase<down?{position:motion.high-phase/motion.closeSeconds,moving:true,phase:phase/period,direction:-1}:{position:motion.low+(phase-down)/motion.openSeconds,moving:true,phase:phase/period,direction:1};
    }
    return phase<up?{position:motion.low+phase/motion.openSeconds,moving:true,phase:phase/period,direction:1}:{position:motion.high-(phase-up)/motion.closeSeconds,moving:true,phase:phase/period,direction:-1};
  }
  function closureTimeline(show,channel){
    const step=show.stepMs/1000,initial=channel<37?1:0;
    let motion={kind:'hold',start:0,from:initial},command=0,commandStart=0,autoAt=Infinity;
    const result=[{start:0,command:0,commandStart:0,motion,automatic:false,acceptedDance:false}];
    function change(t,value,automatic){
      const position=motionAt(motion,t).position;
      if(!automatic){command=value;commandStart=t;}
      let acceptedDance=false;
      if(value===COMMAND.Open||value===COMMAND.Close){
        const target=value===COMMAND.Open?1:0;
        motion={kind:'travel',start:t,from:position,target,duration:Math.abs(target-position)*movementDuration(channel,target===1)};
        if(channel===46)autoAt=target===1?t+120:Infinity;
      }else if(value===COMMAND.Dance){
        acceptedDance=channel>=37&&(channel<=40||position>=.999);
        if(acceptedDance&&channel!==46){
          const low=channel===41?.68:.18,high=channel===41?1:.86;
          motion={kind:'dance',start:t,from:position,low,high,first:position>(low+high)/2?low:high,openSeconds:movementDuration(channel,true),closeSeconds:movementDuration(channel,false)};
        }else if(motion.kind!=='travel')motion={kind:'hold',start:t,from:position};
      }else if(value===COMMAND.Stop||motion.kind==='dance')motion={kind:'hold',start:t,from:position};
      // Idle allows an in-flight Open/Close to finish, but ends Dance now.
      result.push({start:t,command,commandStart,motion,automatic:!!automatic,acceptedDance});
    }
    for(let f=0;f<show.frameCount;f++){
      const t=f*step,value=show.frames[f*CHANNELS+channel-1];
      if(autoAt<=t){const deadline=autoAt;autoAt=Infinity;change(deadline,COMMAND.Close,true);}
      if(value!==command)change(t,value,false);
    }
    if(autoAt<=show.frameCount*step)change(autoAt,COMMAND.Close,true);
    return result;
  }
  function preparePreview(show){
    if(previewCache.has(show))return previewCache.get(show);
    if(show.previewIndex&&show.previewIndex.version===VERSION&&show.previewIndex.frameCount===show.frameCount&&show.previewIndex.stepMs===show.stepMs){previewCache.set(show,show.previewIndex);return show.previewIndex;}
    const step=show.stepMs/1000,raw=show.frames,indices=Array.from({length:30},(_,i)=>i).filter(i=>![8,9,10,11,17,18,19].includes(i));
    const lanes=indices.map(channel=>({channel,times:[],values:[],levels:[],targets:[]}));
    // Compile once in the generation worker. Rendering/seeking then costs one
    // binary lookup per physical lamp, independent of track length and seek span.
    for(let f=0;f<show.frameCount;f++){
      const offset=f*CHANNELS,t=f*step;
      for(const lane of lanes){
        const c=lane.channel,absent=ABSENT.has(c+1),value=absent?0:raw[offset+c];
        const on=absent?false:c===6||c===7?value>127||raw[offset+c+2]>127||raw[offset+c+4]>127:c===16?value>127||raw[offset+17]>127||raw[offset+18]>127||raw[offset+19]>127:value>127;
        const count=lane.times.length,last=count-1;
        if(count&&lane.values[last]===value&&lane.targets[last]===Number(on))continue;
        const ramp=RAMP.has(c+1)||show.settings&&show.settings.outerBeamRamping&&c<2;
        const from=count?(ramp?rampLevel(lane.values[last],lane.levels[last],t-lane.times[last],lane.targets[last]):lane.targets[last]):0;
        lane.times.push(t);lane.values.push(value);lane.levels.push(from);lane.targets.push(Number(on));
      }
    }
    const lights=lanes.map(lane=>({...lane,times:Float64Array.from(lane.times),values:Uint8Array.from(lane.values),levels:Float64Array.from(lane.levels),targets:Uint8Array.from(lane.targets)}));
    const cache={version:VERSION,frameCount:show.frameCount,stepMs:show.stepMs,lights,closures:CLOSURES.map(channel=>({channel,events:closureTimeline(show,channel)}))};
    show.previewIndex=cache;previewCache.set(show,cache);return cache;
  }
  function rainbowAt(elapsed){
    const h=((elapsed*.28)%1+1)%1*6,x=1-Math.abs(h%2-1),rgb=h<1?[1,x,0]:h<2?[x,1,0]:h<3?[0,1,x]:h<4?[0,x,1]:h<5?[x,0,1]:[1,0,x];
    return rgb.map(v=>Math.round(v*255));
  }
  function stateAt(show,time){
    const step=show.stepMs/1000,t=clamp(finite(time)?time:0,0,show.frameCount*step),frame=clamp(Math.floor(t/step+1e-9),0,show.frameCount-1),frameTime=frame*step;
    const cache=preparePreview(show),lights=new Float64Array(30);
    for(const lane of cache.lights){
      const c=lane.channel,i=Math.max(0,lowerBound(lane.times,t+1e-10)-1),ramp=RAMP.has(c+1)||show.settings&&show.settings.outerBeamRamping&&c<2;
      const level=ramp?rampLevel(lane.values[i],lane.levels[i],Math.max(0,t-lane.times[i]),lane.targets[i]):lane.targets[i];
      lights[c]=level;if(c===6||c===7)lights[c+2]=lights[c+4]=level;else if(c===16)lights[17]=lights[18]=lights[19]=level;
    }
    const raw=show.frames.subarray(frame*CHANNELS,(frame+1)*CHANNELS),interior=groups.interior.map(c=>Array.from(raw.subarray(c-1,c+2)));
    const closures=CLOSURES.map(channel=>{
      const events=cache.closures.find(item=>item.channel===channel).events;let i=lowerBound(events,t+1e-10,'start')-1;i=Math.max(0,i);
      const current=events[i],sample=motionAt(current.motion,t),position=clamp(sample.position,0,1);
      const dancing=current.command===COMMAND.Dance&&current.acceptedDance&&!current.automatic;
      const rainbow=channel===46&&dancing&&position>=.999;
      const motion=sample.moving?(current.motion.kind==='dance'?'dancing':sample.direction>0?'opening':'closing'):current.command===COMMAND.Stop?'stopped':'idle';
      return {channel,key:CLOSURE_KEYS[channel],name:channelMap[channel],command:COMMAND_NAME[current.command]||'Idle',rawCommand:current.command,
        motion,moving:sample.moving,dancing,progress:sample.phase,estimatedPosition:position,openFraction:position,foldedFraction:channel<37?1-position:undefined,
        previousCommand:i?COMMAND_NAME[events[i-1].command]||'Idle':'Idle',rainbow,rainbowColor:rainbow?rainbowAt(t-current.commandStart):[0,0,0],automatic:current.automatic,estimated:true};
    });
    const sections=show.sections||[],section=sections[Math.max(0,lowerBound(sections,t+1e-10,'start')-1)];
    return {frame,time:t,frameTime,raw,lights,interior,closures,closureState:Object.fromEntries(closures.map(c=>[c.key,c])),section,positionAccuracy:'estimated',lightAccuracy:'command-timed'};
  }
  const api={version:VERSION,getCapabilities:()=>PROFILE,normalizeSettings,generate,validate,fseq,fseqHeader,preparePreview,stateAt,frameAt:(show,time)=>show.frames.subarray(clamp(Math.floor(time*1000/show.stepMs),0,show.frameCount-1)*200,clamp(Math.floor(time*1000/show.stepMs),0,show.frameCount-1)*200+200),channelMap,groups,COMMAND,palettes:Object.keys(PALETTES),invalidatePreview:show=>{delete show.previewIndex;return previewCache.delete(show);}};
  root.ShowEngine=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

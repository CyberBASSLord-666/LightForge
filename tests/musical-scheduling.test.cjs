'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Engine=require('../web/engine/show-engine.js');
const Planner=require('../web/engine/light-planner.js');

function music(){
  const duration=8,beats=Array.from({length:16},(_,i)=>i*.5);
  return {duration,bpm:120,meter:4,beatConfidence:.95,beats,downbeats:[0,2,4,6],
    waveform:Array(400).fill(.7),energy:Array(400).fill(.7),energyStep:.02,
    activityRanges:[{start:0,end:duration}],sections:[{start:0,end:4,energy:.7,index:0},{start:4,end:8,energy:.7,index:1}],
    onsets:[],phrases:[],impacts:[],vocals:{available:false,presence:'not_detected',phrases:[],notes:[],accents:[],confidence:0},
    bassNotes:[],bassAnalysis:{phrases:[],confidence:0},groove:{},silent:false};
}
function compose(m=music(),changes={},movement={accents:[]},semanticStrategy=null){
  const settings={stepMs:20,offsetMs:0,outputEnabled:{},outerBeamRamping:false,vocalFocus:.85,bassFocus:.9,
    sensitivity:.5,beatDivision:'quarter',style:'pulse',seed:1,...changes};
  const show={frameCount:Math.ceil(m.duration*1000/settings.stepMs)+1,
    sections:m.sections.map(section=>({...section,style:'pulse',intensity:.9,variant:0,seed:1}))};
  show.frames=new Uint8Array(show.frameCount*200);
  return {show,result:Planner.compose(show,m,settings,movement,semanticStrategy)};
}
function frameAttacks(show,channel){
  const bytes=Buffer.from(Engine.fseq(show)),offset=bytes.readUInt16LE(4),step=bytes[18]/1000,frames=bytes.subarray(offset),times=[];
  for(let f=0;f<show.frameCount;f++)if(frames[f*200+channel-1]===255&&(f===0||frames[(f-1)*200+channel-1]===0))times.push(f*step);
  return times;
}

test('measured vocal and bass attacks immediately before a section boundary keep the original audio clock in FSEQ',()=>{
  for(const sourceSeparated of [false,true])for(const stepMs of [15,20])for(const offsetMs of [-137,0,173]){
    const m=music(),start=3.963;
    m.vocals={available:true,presence:'detected',sourceSeparated,source:sourceSeparated?'separated-vocals':'mixture-estimate',confidence:.96,
      phrases:[{start,end:5.21,confidence:.96,strength:.9,kind:'singing'}],notes:[],accents:[]};
    m.bassNotes=[{start,end:5.12,confidence:.96,strength:.7,midi:40}];
    const show=Engine.generate(m,{dance:'off',style:'pulse',stepMs,offsetMs});
    for(const [role,channel]of [['vocals',5],['bass',1]]){
      const attacks=frameAttacks(show,channel),target=start+offsetMs/1000;
      assert.ok(attacks.some(time=>Math.abs(time-target)<=stepMs/2000+1e-7),`${role} attack ${target}, received ${attacks}`);
      const events=show.lightEvents.filter(event=>event.role===role);
      assert.ok(events.length>0);
      assert.ok(events.every(event=>Math.abs(event.actualStart-target)<=stepMs/2000+1e-7),'a section label must not become a new source attack');
      assert.ok(events.every(event=>event.actualEnd>4+offsetMs/1000),'source span survives the arrangement boundary');
    }
  }
});

test('a held source releases at its musical ending rather than before every section boundary',()=>{
  const m=music();m.sections=[{start:0,end:2.01,energy:.7,index:0},{start:2.01,end:3.2,energy:.7,index:1},{start:3.2,end:8,energy:.7,index:2}];
  m.vocals={available:true,presence:'detected',confidence:.95,phrases:[{start:1.003,end:4.703,confidence:.95,strength:.9}],notes:[],accents:[]};
  const show=Engine.generate(m,{dance:'off',stepMs:20});
  for(const channel of [5,6]){
    for(const time of [1.6,2,2.2,2.8,3.2,3.6])assert.equal(show.frames[Math.round(time/.02)*200+channel-1],255);
    assert.equal(show.frames[Math.round(4.3/.02)*200+channel-1],26,'one legal release at the source end');
  }
});

test('a one-sided conflict suppresses the requested bilateral beat pair without shifting or erasing the winning attack',()=>{
  const {show,result}=compose(music(),{}, {accents:[{time:.9,channels:[37],strength:.95}]});
  const beats=result.events.filter(event=>event.kind==='beat pulse'&&event.start===1);
  assert.equal(beats.some(event=>event.id==='left-outer'||event.id==='right-outer'),false);
  assert.ok(beats.some(event=>event.id==='left-tail')&&beats.some(event=>event.id==='right-tail'),'other independent bilateral outputs remain usable');
  assert.ok(result.events.some(event=>event.kind==='movement arrival'&&event.id==='left-outer'&&event.actualStart===.9));
  assert.equal(show.frames[50*200+1],0,'the unpaired right flash must not leak into the binary frame');
  assert.ok(result.diagnostics.symmetry.collisionSuppressedPairs>0);
  const groups=new Map();for(const event of result.events)if(event.bilateralGroup){const group=groups.get(event.bilateralGroup)||[];group.push(event);groups.set(event.bilateralGroup,group);}
  for(const pair of groups.values()){assert.equal(pair.length,2);assert.equal(pair[0].actualStart,pair[1].actualStart);assert.equal(pair[0].actualEnd,pair[1].actualEnd);}
});

test('explicitly disabled fixtures do not silence the available side or manufacture a mirrored output',()=>{
  const {show,result}=compose(music(),{outputEnabled:{'left-outer':false}});
  assert.ok(result.events.some(event=>event.id==='right-outer'&&event.start===1));
  for(let frame=0;frame<show.frameCount;frame++)assert.equal(show.frames[frame*200],0);
});

test('independent cues keep the physical dark gap across arrangement boundaries',()=>{
  const {result}=compose(music(),{}, {accents:[{time:3.78,channels:[37],strength:.95},{time:4,channels:[37],strength:.9}]});
  const lane=result.events.filter(event=>event.id==='left-outer').sort((a,b)=>a.actualStart-b.actualStart);
  assert.ok(lane.some(event=>event.kind==='movement arrival'&&event.start===3.78));
  assert.equal(lane.some(event=>event.kind==='movement arrival'&&event.start===4),false,'a new section cannot join two independent attacks into one hold');
  for(let i=1;i<lane.length;i++)assert.ok(lane[i].actualStart-lane[i-1].actualEnd>=.08-1e-8);
});

test('off-grid transient selection follows the strongest local attack instead of its weaker precursor',()=>{
  const m=music();m.beats=[0,2,4,6];m.downbeats=[0,4];m.onsets=[{time:.703,strength:.76,band:'high'},{time:.823,strength:.98,band:'high'}];
  const {result}=compose(m),events=result.events.filter(event=>event.kind==='detected high attack');
  assert.ok(events.length>0);assert.ok(events.every(event=>event.start===.823));
  assert.ok(events.every(event=>Math.abs(event.actualStart-.823)<=.010001));
});

test('overlapping activity regions and held source notes remain active after a shorter nested interval ends',()=>{
  const m=music();m.activityRanges=[{start:0,end:8},{start:2,end:3}];
  m.vocals={available:true,presence:'detected',phrases:[{start:1,end:6,confidence:.95,strength:.8},{start:2,end:3,confidence:.95,strength:.9}],notes:[{start:1,end:6,confidence:.95,midi:60},{start:2,end:3,confidence:.95,midi:64}]};
  m.bassNotes=[{start:1,end:6,confidence:.95,midi:40},{start:2,end:3,confidence:.95,midi:43}];
  const before=JSON.stringify(m),context=Planner.context(m);
  assert.equal(context.active(5),true);assert.equal(context.vocalAt(4).start,1);assert.equal(context.vocalNoteAt(4).midi,60);assert.equal(context.bassAt(4).midi,40);
  assert.equal(context.vocalNoteAt(2.5).midi,64);assert.equal(context.bassAt(7),null);assert.equal(context.active(8),false);
  assert.equal(JSON.stringify(m),before,'the interval indexes must not mutate measured evidence');
});

test('a semantic filter cannot leave one half of a requested bilateral gesture',()=>{
  let removedGroup=null;
  const strategy={prepareTargets:()=>({links:[{}]}),filterCandidates(candidates){
    const removed=candidates.find(candidate=>candidate.bilateralGroup);removedGroup=removed.bilateralGroup;
    return {candidates:candidates.filter(candidate=>candidate!==removed)};
  }};
  const {result}=compose(music(),{}, {accents:[]},strategy);
  assert.ok(removedGroup);assert.equal(result.events.some(event=>event.bilateralGroup===removedGroup),false);
  assert.equal(result.diagnostics.symmetry.filteredPairs,1);
});

function heldSource(start,end){
  const m=music();m.vocals={available:true,presence:'detected',confidence:.96,
    phrases:[{start,end,confidence:.96,strength:.9,kind:'singing'}],notes:[],accents:[]};
  m.bassNotes=[{start,end,confidence:.96,strength:.7,midi:40}];return m;
}

test('negative offsets retain held source tails at frame zero without claiming a synchronized pre-show attack',()=>{
  for(const stepMs of [15,20])for(const offsetMs of [-106,-273]){
    const m=heldSource(.103,1.403),before=JSON.stringify(m),show=Engine.generate(m,{dance:'off',stepMs,offsetMs});
    for(const channel of [1,5,6])assert.equal(show.frames[channel-1],255,'held source must start visibly at frame zero');
    for(const role of ['vocals','bass']){
      const events=show.lightEvents.filter(event=>event.role===role);assert.ok(events.length>0);
      for(const event of events){assert.equal(event.sourceStart,.103);assert.equal(event.actualStart,0);assert.equal(event.boundaryClip.start,true);assert.ok(Math.abs(event.target-(.103+offsetMs/1000))<1e-9);}
      const row=show.synchronization.eventEvidence.find(event=>event.eventClass===role);
      assert.equal(row.realizationStatus,'outsideExport');assert.equal(row.boundaryClip.continuationObserved,true);assert.equal(row.commandTime,0);assert.equal(row.collisionLoss,false);
      assert.equal(show.synchronization.roles[role].matched,0);
    }
    assert.equal(show.synchronization.targets.outsideExport,2);assert.equal(show.synchronization.timing.command.lighting.count,0);
    assert.equal(show.choreography.lighting.boundaryClipping.startClippedOutputCues,4);assert.equal(JSON.stringify(m),before);
  }
});

test('an opening tail whose release began before export uses a legal hold and stops at the original shifted end',()=>{
  const show=Engine.generate(heldSource(.103,1.303),{dance:'off',stepMs:20,offsetMs:-1000});
  for(const channel of [5,6]){
    for(let f=0;f<15;f++)assert.equal(show.frames[f*200+channel-1],255);
    assert.equal(show.frames[15*200+channel-1],0);
  }
  const voice=show.lightEvents.filter(event=>event.role==='vocals');
  assert.ok(voice.every(event=>event.release===0&&event.releaseOmittedForBoundary&&Math.abs(event.actualEnd-.3)<1e-8));
  assert.equal(show.choreography.lighting.boundaryClipping.releaseOmittedOutputCues,2);
});

test('positive offsets truncate a held ending without moving its planned release earlier',()=>{
  for(const [start,end,releaseAt]of [[6.803,7.703,8.203],[6.303,7.203,7.703]]){
    const m=heldSource(start,end),show=Engine.generate(m,{dance:'off',stepMs:20,offsetMs:1000});
    const voice=show.lightEvents.filter(event=>event.role==='vocals');assert.equal(voice.length,2);
    for(const event of voice){assert.equal(event.boundaryClip.end,true);assert.ok(Math.abs(event.releaseStart-releaseAt)<1e-8);assert.equal(event.actualEnd,(show.frameCount-1)*.02);assert.equal(event.sourceEnd,end);assert.equal(event.boundaryClip.realizedEnd,event.actualEnd);}
    for(const channel of [5,6])for(let f=Math.round((start+1)/.02);f<show.frameCount-1;f++)assert.equal(show.frames[f*200+channel-1],f>=Math.round(releaseAt/.02)?26:255);
    assert.ok(show.frames.subarray(-200).every(value=>value===0));
    const row=show.synchronization.eventEvidence.find(event=>event.eventClass==='vocals');assert.equal(row.realizationStatus,'matched');assert.equal(row.boundaryClip.end,true);
    assert.ok(show.synchronization.maxErrorMs<=10.000001);
  }
});

test('musical holds may continue across zero while direct manual output cues keep their absolute export clock',()=>{
  const m=music(),show=Engine.generate(m,{dance:'off',offsetMs:-300,musicCues:[{id:'opening-hold',role:'vocals',action:'hold',start:.1,end:2,strength:.8}]});
  assert.equal(show.frames[4],255);const row=show.synchronization.manual[0];assert.equal(row.realizationStatus,'outsideExport');assert.equal(row.errorMs,null);assert.equal(row.boundaryClip.continuationObserved,true);
  const silent=music();silent.waveform.fill(0);silent.activityRanges=[];
  const manualCues=[{id:'absolute',outputId:'left-signature',start:.1,end:.5,value:255}],a=Engine.generate(silent,{dance:'off',offsetMs:0,manualCues}),b=Engine.generate(silent,{dance:'off',offsetMs:-300,manualCues});
  assert.deepEqual(a.frames,b.frames);assert.equal(b.frames[5*200+4],255);assert.equal(b.frames[4],0);
  assert.throws(()=>Engine.generate(m,{manualCues:[{...manualCues[0],start:-.1}]}),/end time after the start time/);
  assert.throws(()=>Engine.generate(m,{musicCues:[{id:'invalid',role:'vocals',action:'hold',start:-.1,end:1,strength:.8}]}),/0.10 seconds/);
});

test('manual masking is not mistaken for observed boundary continuation',()=>{
  const show=Engine.generate(heldSource(.103,1.403),{dance:'off',offsetMs:-273,manualCues:[
    {id:'left-off',outputId:'left-signature',start:0,end:.2,value:0},{id:'right-off',outputId:'right-signature',start:0,end:.2,value:0}
  ]});
  const row=show.synchronization.eventEvidence.find(event=>event.eventClass==='vocals');
  assert.equal(row.realizationStatus,'outsideExport');assert.equal(row.boundaryClip.continuationObserved,false);assert.equal(row.commandTime,undefined);
});

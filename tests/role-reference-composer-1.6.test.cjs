'use strict';
/* The inputs here were extracted from original MUSDB vocal stems. The rhythmic
 * scaffold is deliberately declared; this measures translation of real vocal
 * evidence into commands, not separator, beat or transcription accuracy. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),E=require('../web/engine/show-engine.js');
const root=path.resolve(__dirname,'..'),qa=path.join(root,'qa/release-1.6.0'),checks=[],results=[],files=['web/engine/show-engine.js','web/engine/light-planner.js','web/engine/movement-planner.js','web/engine/vehicle-profile.js'];
for(const name of ['meaxic','nightowl','falcon','stella','grunge','sdrnr']){
  const source='qa/release-1.6.0/vocal-detail-reference-'+name+'.json';files.push(source);
  try{
    const vocals=JSON.parse(fs.readFileSync(path.join(root,source))),duration=6.8034467120181406,beats=Array.from({length:Math.ceil(duration*2)},(_,i)=>i*.5).filter(t=>t<duration);
    const music={duration,bpm:120,meter:4,beats,downbeats:beats.filter((_,i)=>i%4===0),beatConfidence:.95,waveform:Array(340).fill(.8),sections:[{start:0,end:duration,energy:.8}],onsets:beats.map(time=>({time:time+.2,strength:.8,band:'high'})).filter(x=>x.time<duration),vocals};
    const show=E.generate(music,{dance:'off'}),role=show.choreography.lighting.roles.vocals,cues=show.lightEvents.filter(c=>c.role==='vocals');
    assert.equal(show.validation.valid,true);assert.ok(role.accentCues>=5,name+' retains genuine source articulation');assert.ok(cues.every(c=>c.end-c.start<=1.800001));
    const sources=vocals.phrases.map(p=>p.start).concat(vocals.accents.map(a=>a.time),vocals.notes.map(n=>n.start));
    for(const c of cues){assert.ok(sources.some(t=>Math.abs(t-c.sourceEventTime)<1e-8));assert.ok(Math.abs(c.actualStart-c.sourceEventTime)<=.010001);}
    let paired=0,single=0,count=0;for(const p of vocals.phrases)for(let time=p.start;time<p.end;time+=.04){const lights=E.stateAt(show,time).lights;paired+=lights[4]>.5&&lights[5]>.5?1:0;single+=(lights[4]>.5)!==(lights[5]>.5)?1:0;count++;}
    assert.ok(paired/count<.30,name+' avoids a continuous bilateral signature glow');assert.ok(single/count>.15,name+' has contrasting solo-lamp detail');
    if(vocals.confidence<.62)assert.equal(paired,0,'weak compound source evidence uses a single lamp');
    results.push({name,source,sourceConfidence:vocals.confidence,sourceArticulations:vocals.accents.length,acceptedArticulations:role.accentCues,acceptedNoteCues:role.noteCues,pairedSignatureBrightFraction:paired/count,singleSignatureBrightFraction:single/count,commandPlacementMaxMs:Math.max(...cues.map(c=>Math.abs(c.actualStart-c.sourceEventTime)*1000))});checks.push({name,passed:true});console.log('PASS '+name);
  }catch(e){checks.push({name,passed:false,error:e.stack});console.error('FAIL '+name+'\n'+e.stack);}
}
{
 const name='source-led controlled NightOwl',source='qa/release-1.6.0/detail-candidate-nightowl-controlled.json';files.push(source);
 try{const data=JSON.parse(fs.readFileSync(path.join(root,source))),vocals=data.vocals||data,duration=6.804,music={duration,bpm:120,beats:Array.from({length:14},(_,i)=>i*.5),waveform:Array(340).fill(.8),sections:[{start:0,end:duration,energy:.8}],vocals};
  assert.equal(vocals.phrases.length,2);assert.equal(vocals.notes.length,0);assert.ok(vocals.phrases.every(p=>p.evidenceMode==='separation-led'&&p.kind==='vocal'&&p.stemEnergyRatio>=.025&&p.confidence<.45));
  const show=E.generate(music,{dance:'off'}),cues=show.lightEvents.filter(c=>c.role==='vocals');assert.equal(show.choreography.lighting.roles.vocals.acceptedEvents,2);assert.ok(cues.filter(c=>c.articulation).length>=2);assert.ok(cues.every(c=>c.evidenceMode==='separation-led'&&!c.vocalNote&&c.end-c.start<=.300001));assert.equal(show.choreography.vocalDetail.notes.length,0);assert.equal(show.choreography.vocalDetail.presence,'uncertain');
  for(const cue of cues){assert.ok(cues.filter(other=>other.sourceEventTime===cue.sourceEventTime).length===1,'Uncertain evidence uses one signature lamp per cue');assert.ok(vocals.phrases.some(p=>cue.start>=p.start&&cue.end<=p.end));}
  const unsupported=structuredClone(music);unsupported.vocals.phrases.forEach(p=>p.stemEnergyRatio=.005);assert.equal(E.generate(unsupported,{dance:'off'}).stats.vocalCues,0,'Weak classifier evidence cannot use fallback without adequate separated-source energy');
  const noSource=structuredClone(music);noSource.vocals.sourceSeparated=false;assert.equal(E.generate(noSource,{dance:'off'}).stats.vocalCues,0,'Mixture estimates cannot enter the separated fallback');
  results.push({name,source,acceptedPhrases:2,acceptedArticulations:show.choreography.lighting.roles.vocals.accentCues,acceptedNoteCues:0,sourcePresence:vocals.presence,cueCount:cues.length,singleLampOnly:true});checks.push({name,passed:true});console.log('PASS '+name);
 }catch(e){checks.push({name,passed:false,error:e.stack});console.error('FAIL '+name+'\n'+e.stack);}
}
const errors=checks.filter(x=>!x.passed),receipt={release:'1.6.0',passed:!errors.length,checkedAt:new Date().toISOString(),checks,results,source_hashes:Object.fromEntries(files.map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')])),limitations:['Six short original MUSDB vocal stems and one controlled remix extracted by the production separator are acoustic references. This does not measure true beat accuracy, word timing, perceptual show quality or physical vehicle response.','A declared120BPM scaffold makes lighting translation reproducible; it is not asserted to be the tempo of these songs.','Source extraction confidence combines several estimates and is not a calibrated probability.','Expected physical lamp states are computed using the shipped preview simulator; independent fade-byte tests separately verify that simulator.']};fs.writeFileSync(path.join(qa,'role-reference-composer-verification.json'),JSON.stringify(receipt,null,2)+'\n');if(errors.length)process.exitCode=1;

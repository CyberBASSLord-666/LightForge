/* Musical light composition. Every accepted cue becomes a documented Tesla command.
 * Overlapping candidates compete by musical salience; accepted attacks never move
 * later to make room. The original audio clock is retained throughout. */
(function(root){
  'use strict';
  const PROFILE=root.VehicleProfile||(typeof require==='function'?require('./vehicle-profile.js'):null);
  const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,Number(x)||0));
  const lower=(a,t,key)=>{let l=0,r=a.length;while(l<r){const i=(l+r)>>>1;if((key?a[i][key]:a[i])<t)l=i+1;else r=i;}return l;};
  const hash=(x,seed)=>{let v=(x+1)^seed;v=Math.imul(v^(v>>>16),0x45d9f3b);v=Math.imul(v^(v>>>16),0x45d9f3b);return (v^(v>>>16))>>>0;};
  const median=a=>a.length?a.slice().sort((x,y)=>x-y)[Math.floor(a.length/2)]:0;
  const LEFT=['left-outer','left-inner','left-combined','left-tail'];
  const RIGHT=['right-outer','right-inner','right-combined','right-tail'];
  const FRONT=LEFT.slice(0,3).concat(RIGHT.slice(0,3));
  const REAR=['brakes','left-tail','right-tail','reverse','license-plate'];
  const WHITE=FRONT.concat(REAR,['left-signature','right-signature']);
  const AMBER_L=['left-front-turn','left-repeater','left-rear-turn'];
  const AMBER_R=['right-front-turn','right-repeater','right-rear-turn'];
  function context(m){
    const sections=m.sections,beats=m.beats,down=m.downbeats,meter=m.meter===3?3:4;
    const ranges=Array.isArray(m.activityRanges)?m.activityRanges:null;
    const sectionAt=t=>sections[Math.max(0,lower(sections,t+1e-8,'start')-1)];
    const active=t=>{
      if(t<0||t>=m.duration||m.silent)return false;
      if(ranges){const i=lower(ranges,t+1e-8,'start')-1;return i>=0&&t<ranges[i].end;}
      if(m.waveform.length)return (m.waveform[Math.min(m.waveform.length-1,Math.floor(t/m.duration*m.waveform.length))]||0)>.002;
      return sectionAt(t).energy>.005;
    };
    const energyAt=t=>{
      if(!active(t))return 0;
      if(m.energy?.length&&m.energyStep>0){const x=clamp(t/m.energyStep,0,m.energy.length-1),i=Math.floor(x),f=x-i;return clamp(m.energy[i]*(1-f)+(m.energy[Math.min(i+1,m.energy.length-1)]||0)*f);}
      const sec=sectionAt(t),wave=m.waveform.length?(m.waveform[Math.min(m.waveform.length-1,Math.floor(t/m.duration*m.waveform.length))]||0):sec.energy;
      return clamp(sec.energy*.65+wave*.35);
    };
    const periodAt=i=>clamp(i+1<beats.length?beats[i+1]-beats[i]:i?beats[i]-beats[i-1]:60/m.bpm,.15,3);
    const beatInfo=i=>{
      const t=beats[i],detail=m.beatDetails?.[i];
      if(detail&&Math.abs(detail.time-t)<.06&&detail.barPosition>=1&&detail.barPosition<=meter)return {slot:detail.barPosition-1,bar:Math.max(0,lower(down,t+1e-6)-1)};
      const di=Math.max(0,lower(down,t+1e-6)-1),base=down[di]??beats[0],first=lower(beats,base-.06);
      return {slot:((i-first)%meter+meter)%meter,bar:di};
    };
    const phraseAt=t=>m.phrases?.length?Math.max(0,lower(m.phrases,t+1e-8,'start')-1):Math.floor(Math.max(0,lower(down,t+1e-8)-1)/4);
    const vocalPhrases=m.vocals?.available&&m.vocals.presence!=='not_detected'?(m.vocals.phrases||[]).filter(p=>p.confidence>=.55):[],bassNotes=(m.bassNotes||[]).filter(p=>p.confidence>=.5);
    const roleAt=(events,t)=>{const i=lower(events,t+1e-8,'start')-1;return i>=0&&events[i].end>t?events[i]:null;};
    const roleEnvelope=(role,t,fallback)=>{if(!role.envelope?.length||!(role.envelopeStep>0))return clamp(fallback);const x=clamp(t/role.envelopeStep,0,role.envelope.length-1),i=Math.floor(x),f=x-i;return clamp(role.envelope[i]*(1-f)+(role.envelope[Math.min(i+1,role.envelope.length-1)]||0)*f);};
    return {active,energyAt,sectionAt,periodAt,beatInfo,phraseAt,meter,vocalAt:t=>roleAt(vocalPhrases,t),bassAt:t=>roleAt(bassNotes,t),roleEnvelope};
  }
  function compose(show,m,s,movement={accents:[]}){
    const ctx=context(m),step=s.stepMs/1000,shift=s.offsetMs/1000,end=show.frameCount*step-step;
    const outputs=PROFILE.outputs.filter(o=>o.available&&o.kind==='light'),byId=new Map(outputs.map(o=>[o.id,o]));
    const candidates=[],accepted=[],lanes=new Map(outputs.map(o=>[o.id,[]]));let serial=0;
    const vocalFocus=clamp(s.vocalFocus??.85),bassFocus=clamp(s.bassFocus??.9);
    const vocalPhrases=vocalFocus>0&&m.vocals?.available&&m.vocals.presence!=='not_detected'?(m.vocals.phrases||[]).filter(p=>p.confidence>=.55+(1-vocalFocus)*.15&&p.end-p.start>=.12):[];
    const bassNotes=bassFocus>0?(m.bassNotes||[]).filter(p=>p.confidence>=.5+(1-bassFocus)*.15&&p.end-p.start>=.10):[];
    const reservations=new Map(),reserve=(id,start,end)=>{const spans=reservations.get(id)||[];spans.push({start:start+shift-.08,end:end+shift+.08});reservations.set(id,spans);};
    // Dedicated physical lanes preserve role timing even where a whole-car
    // structural flash would otherwise suppress an entire held vocal phrase.
    // Combined beams, tails and amber remain available to the arrangement.
    const voiceRoutes=vocalPhrases.map((p,i)=>({p,ids:vocalFocus>=.55?['left-signature','right-signature']:[i%2?'right-signature':'left-signature'],length:vocalFocus>=.55?p.end-p.start:Math.min(p.end-p.start,.18+vocalFocus*.3)}));
    const bassRoutes=bassNotes.map((p,i)=>{const left=i%2===0,ids=[left?'left-outer':'right-outer'];if(bassFocus>=.55&&p.strength>=.65)ids.push('brakes');if(bassFocus>=.8&&p.strength>=.88&&p.end-p.start>=.5)ids.push(left?'right-outer':'left-outer');return {p,ids,length:bassFocus>=.55?Math.min(p.end-p.start,2.2):Math.min(p.end-p.start,.12+bassFocus*.2)};});
    for(const {p,ids,length}of voiceRoutes.concat(bassRoutes))for(const id of ids)reserve(id,p.start,p.start+length);
    for(const [id,spans]of reservations){const merged=[];for(const span of spans.sort((a,b)=>a.start-b.start)){const last=merged[merged.length-1];if(last&&span.start<=last.end)last.end=Math.max(last.end,span.end);else merged.push({...span});}reservations.set(id,merged);}
    const reserved=(id,start,finish)=>{const spans=reservations.get(id);if(!spans)return false;const i=lower(spans,finish,'start')-1;return i>=0&&spans[i].end>start;};
    const sceneAt=t=>{const section=ctx.sectionAt(t);return show.sections[section.index]||{style:s.style,intensity:s.intensity};};
    function snap(t,band,radius=.035){
      let best=t,score=.12;const start=lower(m.onsets,t-radius,'time');
      for(let i=start;i<m.onsets.length&&m.onsets[i].time<=t+radius;i++){
        const o=m.onsets[i];if(o.band!==band||o.strength<.35)continue;
        const value=o.strength*(1-Math.abs(t-o.time)/radius*.55);if(value>score){best=o.time;score=value;}
      }return best;
    }
    function add(ids,t,duration,priority,kind,strength=1,fade=0,absolute=false,details={}){
      const musicTime=absolute?t-shift:t;if(!ctx.active(musicTime))return;
      const section=ctx.sectionAt(musicTime),start=(absolute?t:t+shift),stop=Math.min(end,start+duration,section.end+shift);
      if(start<0||stop-start<step)return;
      for(const id of new Set(ids)){
        const o=byId.get(id);if(!o||s.outputEnabled[id]===false||!details.role&&reserved(id,start,stop))continue;
        const supports=o.mode==='ramp'||s.outerBeamRamping&&o.optionalMode==='ramp';
        candidates.push({...details,id,start,end:stop,sectionIndex:section.index,priority,kind,strength,fade:supports?fade:0,release:supports&&details.release?details.release:0,serial:serial++,target:start+(supports?fade:0)});
      }
    }
    const flash=(ids,t,width,priority,kind,strength=1,absolute=false)=>add(ids,t,Math.max(.10,width),priority,kind,strength,0,absolute);
    function breathe(ids,t,period,priority=12){
      const length=period>=4.2?2:period>=2.2?1:.5;
      add(ids,t,length*2+.08,priority,'phrase fade',.6,length);
    }
    if(!m.silent){
      for(const {p,ids,length}of voiceRoutes){
        // A singing estimate controls phrase-scale holds. Its entrance is not
        // snapped to a drum transient. Supported 500 ms release ramps finish at
        // the estimated phrase ending; short phrases receive an honest on/off.
        const finish=p.start+length,selected=[];
        if(vocalFocus>=.55)for(const accent of (m.vocals.accents||[]).filter(a=>a.time>=p.start+1.1&&a.time<=finish-.75&&a.confidence>=.55&&a.strength>=.76-vocalFocus*.14).sort((a,b)=>b.strength-a.strength||a.time-b.time)){
          if(selected.every(a=>Math.abs(a.time-accent.time)>=1.3))selected.push(accent);
        }
        // Sparse contours are supporting mixture estimates inside classified
        // singing, not isolated voice attacks. Legal releases provide contrast
        // before those points; there is no invented word or syllable timeline.
        const points=[{time:p.start},...selected.sort((a,b)=>a.time-b.time)];
        for(let i=0;i<points.length;i++)for(const sec of m.sections){
          const start=Math.max(points[i].time,sec.start),stop=Math.min(i+1<points.length?points[i+1].time-.08:finish,sec.end);if(stop-start<.1)continue;
          const release=vocalFocus>=.55&&stop-start>=.75?.5:0,accent=i>0&&start===points[i].time;
          add(ids,start,stop-start,64+vocalFocus*5,accent?'estimated vocal-region accent':'estimated vocal '+(release?'sustain':'entrance'),p.strength,0,false,{role:'vocals',release,sourceStart:p.start,sourceEnd:p.end,sourceConfidence:p.confidence,sourceEventTime:points[i].time,estimatedAccent:accent});
        }
      }
      for(const {p,ids,length}of bassRoutes){
        for(const sec of m.sections){const start=Math.max(p.start,sec.start),stop=Math.min(p.start+length,sec.end);if(stop-start<.1)continue;
          add(ids,start,stop-start,62+bassFocus*5+p.strength*2,'pitched bass note',p.strength,0,false,{role:'bass',sourceStart:p.start,sourceEnd:p.end,sourceConfidence:p.confidence,midi:p.midi,frequency:p.frequency});
        }
      }
      // Motifs repeat over phrases. Meter, phase and beat spacing come from the
      // analysis, rather than a hard-coded four-beat clock or average BPM.
      for(let i=0;i<m.beats.length;i++){
        const beat=m.beats[i];if(!ctx.active(beat))continue;
        const {slot,bar}=ctx.beatInfo(i),period=ctx.periodAt(i),energy=ctx.energyAt(beat),scene=sceneAt(beat),power=scene.intensity;
        const section=ctx.sectionAt(beat),phrase=Math.max(0,ctx.phraseAt(beat)-ctx.phraseAt(section.start)),baseBeat=Math.min(m.beats.length-1,lower(m.beats,section.start)),localBar=Math.max(0,bar-ctx.beatInfo(baseBeat).bar);
        const variant=(scene.variant+Math.floor(phrase/2))%6,quiet=energy<.29||(scene.style==='cinematic'&&energy<.59);
        const t=snap(beat,slot===0?'bass':'mid',Math.min(.035,period*.06));
        const width=clamp(period*(.19+.17*power+.014*variant),.10,quiet?.30:.34),side=(slot+localBar+variant)%2===0;
        if(quiet){
          if(slot===0){
            breathe(variant%3===0?['left-signature','right-signature']:side?['left-signature','right-inner']:['right-signature','left-inner'],t,period*ctx.meter,14);
            if(localBar%2===1)breathe(side?['left-inner','left-combined']:['right-inner','right-combined'],t,period*ctx.meter,11);
            if(energy>.12)flash(variant%2?['left-tail','right-tail','license-plate']:side?['left-tail','license-plate']:['right-tail','license-plate'],t,.18+.018*variant,22,'quiet downbeat');
          }
          continue;
        }
        const priority=slot===0?44:30;
        if(scene.style==='cinematic'){
          if(slot===0){flash(WHITE,t,.25+power*.12+variant*.012,45,'bar entrance');breathe(variant%2?['left-signature','right-inner']:['right-signature','left-inner'],t,period*ctx.meter,10);}
          else if(slot===ctx.meter-1)flash((variant<3?REAR:side?LEFT:RIGHT).concat(side?AMBER_L:AMBER_R),t,width,30,'bar response');
          else if(energy>.8&&localBar%4===3&&slot===1)flash(variant%2?['left-combined','right-tail']:['right-combined','left-tail'],t,width*.8,23,'phrase turnaround');
        }else if(scene.style==='pulse'){
          const core=slot===0?WHITE:slot%2?['left-inner','right-inner','brakes']:['left-outer','right-outer','left-tail','right-tail'];
          const ornament=variant===0?[]:variant===1?(side?AMBER_L:AMBER_R):variant===2?(side?['left-combined']:['right-combined']):variant===3?(slot%2?REAR:FRONT):variant===4?(side?LEFT:RIGHT):(side?['left-signature','right-tail']:['right-signature','left-tail']);
          flash(core.concat(ornament),t,width,priority,'beat pulse');
        }else{
          let route;
          if(variant===0)route=slot%2?REAR:FRONT;
          else if(variant===1)route=side?LEFT.concat(AMBER_L):RIGHT.concat(AMBER_R);
          else if(variant===2)route=side?LEFT.slice(0,3).concat('right-tail'):RIGHT.slice(0,3).concat('left-tail');
          else if(variant===3)route=slot===0?WHITE:slot%2?['left-inner','right-inner','brakes']:['left-outer','right-outer','left-tail','right-tail'];
          else if(variant===4)route=[LEFT.slice(0,3),RIGHT.slice(0,3),['right-tail','right-rear-turn'],['left-tail','left-rear-turn']][slot%4];
          else route=slot===0?WHITE:slot%2?LEFT.concat(AMBER_R):RIGHT.concat(AMBER_L);
          if(power>=.42||slot===0||slot===ctx.meter-1)flash(route,t,width,priority,'phrase motif');
        }
        if(slot===0){
          flash(['park-markers','license-plate'],t,Math.max(.16,width),32,'bar marker');
          if(localBar%2===0)breathe(['left-signature','right-signature'],t,period*ctx.meter,9);
          if(s.outerBeamRamping&&localBar%2===1&&t>=.5)add([localBar%4===1?'left-outer':'right-outer'],t-.5,1.08,48,'outer beam phrase fade',.7,.5);
        }
        // Subdivision accents require confidence and an actual high-band attack.
        // Explicit eighth-note selection allows a grid pulse even without one.
        if(i+1<m.beats.length&&energy>.45&&power>.45&&(s.beatDivision==='eighth'||s.beatDivision==='auto'&&m.beatConfidence>.58&&energy>.65)){
          const ratio=m.groove?.feel==='swing'&&m.groove.confidence>=.45?m.groove.subdivisionRatio:.5,half=beat+period*ratio,near=lower(m.onsets,half-.07,'time');let attack=null;
          for(let j=near;j<m.onsets.length&&m.onsets[j].time<=half+.07;j++){const o=m.onsets[j];if(o.band==='high'&&o.strength>.45&&(!attack||o.strength>attack.strength))attack=o;}
          if(attack||s.beatDivision==='eighth')flash(side?AMBER_R:AMBER_L,attack?.time??half,Math.min(.16,period*.22),18,'offbeat detail',attack?.strength||.4);
        }
      }
      // Actual attacks remain useful with a weak or unusual beat grid. Keep
      // each frequency band's role and prevent dense spectral peaks becoming noise.
      const last={bass:-10,mid:-10,high:-10};
      for(const o of m.onsets){
        if(!ctx.active(o.time)||ctx.energyAt(o.time)<.15)continue;
        const scene=sceneAt(o.time),threshold=(scene.style==='cinematic'?.79:.91)-s.sensitivity*.35;
        const spacing=scene.style==='cinematic'?.5:.22;
        if(o.strength<threshold||o.time-last[o.band]<spacing)continue;
        const bi=lower(m.beats,o.time),near=Math.min(Math.abs((m.beats[bi]??Infinity)-o.time),Math.abs((m.beats[bi-1]??-Infinity)-o.time));
        if(near<.065&&m.beatConfidence>=.4)continue;
        const left=hash(Math.floor((o.time-ctx.sectionAt(o.time).start)*2),scene.seed)%2===0;
        const route=o.band==='bass'?['left-outer','right-outer','brakes']:o.band==='mid'?['left-inner','right-inner','left-tail','right-tail']:(left?AMBER_L:AMBER_R);
        flash(route,o.time,.1+scene.intensity*.05,24+o.strength*10,'detected '+o.band+' attack',o.strength);last[o.band]=o.time;
      }
      // Reserve whole-car accents for selected structural moments. Rank first,
      // then suppress neighboring candidates, rather than accepting first-in-time.
      const impactPool=(m.impacts||[]).filter(x=>x.strength>=.58).map(x=>({...x}));
      for(let i=1;i<m.sections.length;i++){
        const sec=m.sections[i],previous=m.sections[i-1];
        if(sec.energy>previous.energy+.13)impactPool.push({time:sec.start,strength:clamp(sec.energy-previous.energy+.48),kind:'section entrance'});
      }
      const chosen=[];
      for(const impact of impactPool.sort((a,b)=>b.strength-a.strength||a.time-b.time)){
        if(!ctx.active(impact.time)||chosen.some(x=>Math.abs(x.time-impact.time)<3.2))continue;
        chosen.push(impact);if(chosen.length>=Math.max(1,Math.ceil(m.duration/7)))break;
      }
      for(const impact of chosen){
        const t=impact.time,scene=sceneAt(t),full=impact.strength>.78&&scene.intensity>.5;
        flash(full?WHITE.concat(AMBER_L,AMBER_R,['park-markers']):FRONT.concat(['brakes','left-tail','right-tail']),t,full?.25:.2,80+impact.strength,'musical impact',impact.strength);
        // Start a legal fade before the arrival. Its full brightness lands on
        // the accent, instead of beginning a slow ramp after the music hits.
        const rise=impact.strength>.85?1:.5;
        if(t>=rise&&ctx.active(t-rise))add(['left-signature','right-signature'],t-rise,rise*2+.08,60,'impact anticipation',impact.strength,rise);
      }
      for(const a of movement.accents||[]){
        const cs=a.channels||[];
        const ids=cs.includes(41)?WHITE:cs.includes(46)?AMBER_L.concat(AMBER_R):cs.length?Array.from(new Set(cs.flatMap(ch=>ch===37?LEFT.slice(0,3):ch===39?RIGHT.slice(0,3):ch===38?['left-tail','left-rear-turn']:ch===40?['right-tail','right-rear-turn']:ch===35?AMBER_L:ch===36?AMBER_R:outputs.filter(o=>o.channels.includes(ch)).map(o=>o.id)))):WHITE;
        flash(ids,a.time,.22,72,'movement arrival',a.strength||.75,true);
      }
    }
    // Greedy salience scheduling on physical output groups: no OR-alias fights,
    // no late pulse shifts, and no low-priority cue overwrites a strong attack.
    candidates.sort((a,b)=>b.priority-a.priority||b.strength-a.strength||a.start-b.start||a.serial-b.serial);
    let rejected=0;
    for(const cue of candidates){
      const a=Math.max(0,Math.round(cue.start/step)),b=Math.min(show.frameCount-1,Math.round(cue.end/step));
      if(b<=a){rejected++;continue;}
      const lane=lanes.get(cue.id),index=lower(lane,a,'a'),gap=Math.ceil(.08/step-1e-9);
      if(index>0&&lane[index-1].b+(lane[index-1].sectionIndex===cue.sectionIndex?gap:0)>a||index<lane.length&&b+(lane[index].sectionIndex===cue.sectionIndex?gap:0)>lane[index].a){rejected++;continue;}
      const item={...cue,a,b,actualStart:a*step,actualEnd:b*step};lane.splice(index,0,item);accepted.push(item);
    }
    const frames=show.frames;
    for(const cue of accepted){
      const o=byId.get(cue.id),up=cue.fade===2?230:cue.fade===1?204:178,down=cue.fade===2?77:cue.fade===1?51:26;
      const pivot=Math.round((cue.start+cue.fade+.04)/step);
      for(let f=cue.a;f<cue.b;f++){
        if(!ctx.active((f+.5)*step-shift))continue;
        const releaseAt=Math.round((cue.end-cue.release)/step),value=cue.release&&f>=releaseAt?26:cue.fade?(f<pivot?up:down):255;
        for(const ch of o.channels)frames[f*200+ch-1]=value;
      }
    }
    const errors=accepted.map(c=>Math.abs(c.actualStart-c.start)*1000);
    return {context:ctx,events:accepted.sort((a,b)=>a.start-b.start||a.serial-b.serial),diagnostics:{
      candidateCues:candidates.length,acceptedCues:accepted.length,suppressedCollisions:rejected,
      attackCues:accepted.filter(c=>c.kind.startsWith('detected')).length,fadeCues:accepted.filter(c=>c.fade>0||c.release>0).length,
      impactCues:accepted.filter(c=>c.kind==='musical impact').length,
      quantizationMaxMs:errors.reduce((a,b)=>Math.max(a,b),0),quantizationMedianMs:median(errors),
      roles:{vocals:{available:m.vocals?.available===true,presence:m.vocals?.presence||'uncertain',eligibleEvents:vocalPhrases.length,acceptedEvents:new Set(accepted.filter(c=>c.role==='vocals').map(c=>c.sourceStart)).size,accentCues:new Set(accepted.filter(c=>c.estimatedAccent).map(c=>c.sourceEventTime)).size,confidence:m.vocals?.confidence||0,focus:vocalFocus},bass:{eligibleEvents:bassNotes.length,acceptedEvents:new Set(accepted.filter(c=>c.role==='bass').map(c=>c.sourceStart)).size,confidence:m.bassAnalysis?.confidence||0,focus:bassFocus},percussion:{acceptedCues:accepted.filter(c=>c.kind==='offbeat detail'||c.kind==='detected high attack'||c.kind==='detected bass attack').length},arrangement:{acceptedCues:accepted.filter(c=>!c.role&&!['offbeat detail','detected high attack','detected bass attack'].includes(c.kind)).length}},
      meter:ctx.meter,recurringMotifGroups:Array.from(new Set(show.sections.filter(x=>x.recurrenceGroup).map(x=>x.recurrenceGroup))).length,lockedSections:show.sections.filter(x=>x.locked).length,timingScope:'Command placement within half a frame of the selected musical target. Audio detection and vehicle response are separate estimates.'
    }};
  }
  const api={compose,context,version:'1.5.0'};root.LightPlanner=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

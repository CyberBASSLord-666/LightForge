/* LightForge 1.6 — phrase-aware choreography for slow physical actuators.
 * Tesla command timing is exact to the exported frame; motor positions and
 * Dance endpoints are estimates. Never retime an oscillating motor to audio BPM.
 * Source: https://github.com/teslamotors/light-show#closures-channels
 */
(function(root){
  'use strict';
  const VERSION='1.6.0', COMMAND={Open:63,Dance:127,Close:191};
  const PROFILE=root.VehicleProfile||(typeof require==='function'?require('./vehicle-profile.js'):null);
  const SPECS=PROFILE.closureSpecifications;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const lower=(list,t,key)=>{let a=0,b=list.length;while(a<b){const m=(a+b)>>>1;if((key?list[m][key]:list[m])<t)a=m+1;else b=m;}return a;};
  const nearest=(list,t)=>{const i=lower(list,t);return !i?list[0]:i>=list.length?list[list.length-1]:t-list[i-1]<=list[i]-t?list[i-1]:list[i];};
  function plan(music,settings,profile){
    music=music||{};settings=settings||{};
    const activeProfile=profile||PROFILE,specifications=activeProfile&&activeProfile.closureSpecifications||SPECS;
    const resolveTiming=activeProfile&&typeof activeProfile.resolvePerceptualTiming==='function'?activeProfile.resolvePerceptualTiming:PROFILE&&typeof PROFILE.resolvePerceptualTiming==='function'?PROFILE.resolvePerceptualTiming:null;
    const perceptualTiming=resolveTiming?resolveTiming(settings.vehicleTimingCalibration):{schemaVersion:1,enabled:false,calibrationId:null,outputs:{}};
    const timingFor=id=>perceptualTiming.outputs&&perceptualTiming.outputs[id]||{calibrationConfigured:false,commandLatencyMs:0,activationLatencyMs:0,deactivationLatencyMs:0,openTravelMs:specifications[id]&&specifications[id].travel*1000,closeTravelMs:specifications[id]&&specifications[id].closeTravel*1000};
    const milliseconds=(id,key,fallback)=>{const value=timingFor(id)[key];return finite(value)?value/1000:fallback;};
    const commandLead=(id,phase)=>milliseconds(id,'commandLatencyMs',0)+milliseconds(id,phase==='close'?'deactivationLatencyMs':'activationLatencyMs',0);
    const openTravel=id=>milliseconds(id,'openTravelMs',specifications[id].travel);
    const closeTravel=id=>milliseconds(id,'closeTravelMs',specifications[id].closeTravel);
    const responseTimingEvidence=(id,phase)=>{
      const evidence=timingFor(id).responseTimingEvidence;
      return phase==='open'?evidence&&evidence.open===true:phase==='close'?evidence&&evidence.close===true:false;
    };
    // Preserve each legacy envelope exactly when no calibration is configured.
    // These margins are conservative planner allowances, not measured latencies.
    const openMargin=id=>id==='trunk'?.35:.30;
    const closeMargin=id=>id==='trunk'||specifications[id].group==='windows'?.35:.30;
    const openLead=id=>commandLead(id,'open')+openTravel(id)+openMargin(id);
    const closeLead=id=>commandLead(id,'close')+closeTravel(id)+closeMargin(id);
    const predictedArrival=(id,phase,start,legacy)=>{
      const row=timingFor(id);
      if(!perceptualTiming.enabled||!row.calibrationConfigured)return legacy;
      if(!responseTimingEvidence(id,phase))return null;
      const travel=phase==='close'?closeTravel(id):openTravel(id);
      return Number((start+commandLead(id,phase)+travel).toFixed(6));
    };
    const calibratedIntent=(id,phase,intent)=>{
      const row=timingFor(id);
      if(!perceptualTiming.enabled||!row.calibrationConfigured)return intent;
      return Object.assign({},intent,{perceptualTiming:{schemaVersion:1,calibrationId:perceptualTiming.calibrationId,phase,commandLatencyMs:row.commandLatencyMs,activationLatencyMs:row.activationLatencyMs,deactivationLatencyMs:row.deactivationLatencyMs,openTravelMs:row.openTravelMs,closeTravelMs:row.closeTravelMs,responseTimingEvidence:responseTimingEvidence(id,phase),travelEvidence:row.travelEvidence}});
    };
    const duration=finite(music.duration)?music.duration:0,step=([15,20].includes(settings.stepMs)?settings.stepMs:20)/1000;
    const shift=clamp(finite(settings.offsetMs)?settings.offsetMs:0,-2000,2000)/1000;
    const q=t=>Math.round(t/step+1e-8)*step,up=t=>Math.ceil(t/step-1e-8)*step;
    const end=Math.max(0,Math.floor((duration-.30)/step)*step),expressive=settings.dance!=='balanced',density=clamp(finite(settings.movementDensity)?settings.movementDensity:.7,0,1);
    const events=[],accents=[],targets=[],skipped=[],tracks=new Map();
    const diagnostics={version:VERSION,movementDensity:density,style:expressive?'expressive':'balanced',timingBasis:'Music arrival targets with conservative planning lead time; no command correction is applied without an explicit calibration.',offsetAppliedMs:shift*1000,commandCounts:{},danceSeconds:{},selectedTargets:0,consideredTargets:0,skipped,travelSeconds:{windows:4,mirrors:2,trunkOpen:14,trunkClose:4,charge:2},settlingMarginSeconds:.30,recoverySeconds:expressive?5:8};
    if(perceptualTiming.enabled)diagnostics.perceptualTiming={schemaVersion:1,calibrationId:perceptualTiming.calibrationId,status:'explicit-user-configuration',outputs:Object.fromEntries(Object.entries(perceptualTiming.outputs).filter(([,row])=>row.calibrationConfigured).map(([id,row])=>[id,{leadAdjusted:row.leadAdjusted,responseTimingEvidence:row.responseTimingEvidence,commandLatencyMs:row.commandLatencyMs,activationLatencyMs:row.activationLatencyMs,deactivationLatencyMs:row.deactivationLatencyMs,openTravelMs:row.openTravelMs,closeTravelMs:row.closeTravelMs,travelEvidence:row.travelEvidence}]))};
    // Calibration limits are physical output constraints, not advisory quality
    // warnings.  If a complete automatic gesture cannot meet one, omit that
    // output's automatic gesture rather than export an infeasible partial
    // command sequence (which could leave a closure in the wrong state).
    let timingLimitsApplied=false;
    function enforceTimingLimits(){
      if(timingLimitsApplied)return;
      timingLimitsApplied=true;
      for(const [id,track]of tracks){
        const row=timingFor(id);
        if(!row||!row.calibrationConfigured||!track.length)continue;
        const minimumMs=finite(row.minimumUsefulDurationMs)?row.minimumUsefulDurationMs:null;
        const repeatMs=finite(row.minimumRepeatIntervalMs)?row.minimumRepeatIntervalMs:null;
        if(minimumMs===null&&repeatMs===null)continue;
        const ordered=track.slice().sort((left,right)=>left.start-right.start||left.end-right.end||left.command.localeCompare(right.command));
        let reason=null;
        if(minimumMs!==null){
          const short=ordered.find(event=>(event.end-event.start)*1000+1e-7<minimumMs);
          if(short)reason='minimum useful duration '+minimumMs+' ms exceeds '+short.command+' run '+Math.round((short.end-short.start)*1000*1000)/1000+' ms';
        }
        if(!reason&&repeatMs!==null)for(let index=1;index<ordered.length;index++){
          const intervalMs=(ordered[index].start-ordered[index-1].start)*1000;
          if(intervalMs+1e-7<repeatMs){reason='minimum repeat interval '+repeatMs+' ms exceeds available '+Math.round(intervalMs*1000)/1000+' ms';break;}
        }
        if(!reason)continue;
        for(let index=events.length-1;index>=0;index--)if(events[index].outputId===id)events.splice(index,1);
        for(let index=accents.length-1;index>=0;index--)if(accents[index].outputId===id)accents.splice(index,1);
        for(let index=targets.length-1;index>=0;index--)if(targets[index].outputId===id)targets.splice(index,1);
        track.length=0;
        skipped.push(id+': automatic movement omitted because '+reason+'.');
      }
    }
    const result=()=>{enforceTimingLimits();events.sort((a,b)=>a.start-b.start||a.channels[0]-b.channels[0]);accents.sort((a,b)=>a.time-b.time);targets.sort((a,b)=>a.time-b.time);for(const [id,track]of tracks){diagnostics.commandCounts[id]=track.length;diagnostics.danceSeconds[id]=Math.round(track.filter(e=>e.command==='Dance').reduce((n,e)=>n+e.end-e.start,0)*1000)/1000;}diagnostics.selectedTargets=targets.length;return{events,accents,targets,diagnostics};};
    if(settings.dance==='off'||density===0||music.silent||duration<6){skipped.push(settings.dance==='off'||density===0?'Movement is switched off.':music.silent?'Silent audio has no automatic movement.':'Track is too short for a complete movement and return.');return result();}
    const safeTimes=list=>Array.from(new Set(Array.from(list||[]).filter(t=>finite(t)&&t>=0&&t<duration))).sort((a,b)=>a-b);
    const beats=safeTimes(music.beats),downbeats=safeTimes(music.downbeats);
    const sections=Array.from(music.sections||[]).filter(s=>s&&finite(s.start)).sort((a,b)=>a.start-b.start);
    const phrases=Array.from(music.phrases||[]).filter(p=>p&&finite(p.start)&&finite(p.end)&&p.end>p.start).sort((a,b)=>a.start-b.start);
    const activity=Array.isArray(music.activityRanges)?music.activityRanges.filter(r=>r&&finite(r.start)&&finite(r.end)&&r.end>r.start).sort((a,b)=>a.start-b.start):[{start:0,end:duration}];
    const hasEnvelope=!!(music.energy&&music.energy.length),energy=hasEnvelope?music.energy:music.waveform||[];
    // Legacy waveform bins span the whole song; they are not 20 ms analysis samples.
    const energyStep=hasEnvelope&&finite(music.energyStep)&&music.energyStep>0?music.energyStep:duration/Math.max(1,energy.length);
    const confidence=clamp(finite(music.beatConfidence)?music.beatConfidence:.5,0,1),recovery=expressive?5:8;
    const enabled=Object.assign({windows:true,mirrors:true,trunk:true,charge:true},settings.enabled||{}),manual=new Set((settings.manualCues||[]).map(c=>c.outputId));
    for(const [id,spec]of Object.entries(specifications)){
      const output=activeProfile&&activeProfile.outputs&&activeProfile.outputs.find(o=>o.id===id);
      if(enabled[spec.group]===false||settings.outputEnabled&&settings.outputEnabled[id]===false||manual.has(id)||output&&output.available===false)continue;
      tracks.set(id,[]);
    }
    const sectionAt=t=>{const i=lower(sections,t,'start');return sections[Math.max(0,i<sections.length&&sections[i].start===t?i:i-1)]||{energy:.5};};
    const energyAt=t=>{t=clamp(t,0,Math.max(0,duration-.001));const baseline=finite(sectionAt(t).energy)?sectionAt(t).energy:.5;return clamp(energy.length?.72*(Number(energy[Math.min(energy.length-1,Math.floor(t/energyStep))])||0)+.28*baseline:baseline,0,1);};
    const rangeAt=t=>{const i=lower(activity,t,'start');const r=activity[Math.max(0,i<activity.length&&activity[i].start===t?i:i-1)];return r&&t>=r.start&&t<r.end?r:null;};
    const phraseAt=t=>{const i=lower(phrases,t,'start');const p=phrases[Math.max(0,i<phrases.length&&phrases[i].start===t?i:i-1)];return p&&t>=p.start&&t<p.end?p:null;};
    const beatAt=t=>{const i=lower(beats,t),a=beats[Math.max(0,i-1)],b=beats[Math.min(beats.length-1,i)],c=beats[Math.min(beats.length-1,i+1)];return clamp(b>a?b-a:c>b?c-b:60/(music.bpm||120),.15,3);};
    const pool=new Map();
    function offer(time,kind,salience,sourceConfidence,role=null,roleEnd=null){
      if(!finite(time)||time<0||time>=duration||!rangeAt(time))return;
      let t=time;
      if(!role&&beats.length&&confidence>=.35){const beat=nearest(beats,time);if(Math.abs(beat-time)<=Math.min(.09,beatAt(time)*.18))t=beat;}
      const level=energyAt(t);if(level<.07)return;
      const rise=Math.max(0,level-energyAt(Math.max(0,t-Math.min(2,beatAt(t)*2))));
      const measuredConfidence=clamp(finite(sourceConfidence)?sourceConfidence:confidence,0,1);
      const score=.50*level+.29*clamp(salience,0,1)+.16*rise+.05*measuredConfidence;
      const candidate={musicTime:t,time:q(t+shift),kind,score,energy:level,confidence:measuredConfidence,role,roleEnd};
      const key=Math.round(t/.10);const previous=pool.get(key);
      if(!previous||candidate.score>previous.score)pool.set(key,candidate);
    }
    for(const p of phrases){const kind=p.kind||'phrase';offer(finite(p.accentTime)?p.accentTime:p.start,kind,/peak|drop|chorus|impact/i.test(kind)?1:/build|arrival/i.test(kind)?.82:.66,p.confidence);}
    for(let i=0;i<sections.length;i++){const s=sections[i],prev=sections[Math.max(0,i-1)];offer(s.start,'section arrival',clamp(.55+Math.max(0,(s.energy||0)-(prev.energy||0)),0,1),confidence);}
    for(const hit of music.impacts||[])if(hit&&finite(hit.time)&&Number(hit.strength)>=.35)offer(hit.time,hit.kind||'impact',Number(hit.strength),confidence);
    const vocalFocus=clamp(finite(settings.vocalFocus)?settings.vocalFocus:.85,0,1),bassFocus=clamp(finite(settings.bassFocus)?settings.bassFocus:.9,0,1);
    if(vocalFocus>0&&music.vocals?.available&&music.vocals.presence!=='not_detected')for(const p of music.vocals.phrases||[]){
      if(!p||p.confidence<.55+(1-vocalFocus)*.15||!finite(p.start)||!finite(p.end)||p.end-p.start<.4)continue;
      const separated=music.vocals.sourceSeparated===true,phraseWeight=separated?clamp((p.end-p.start)/6,.3,1):1;
      offer(p.start,separated?'vocal phrase entrance':'estimated vocal entrance',(.66+.29*vocalFocus)*phraseWeight*(p.kind==='speech'?.8:1),p.confidence,'vocals',p.end);
      if(p.end-p.start>=2)offer(p.end,'estimated vocal cadence',.5+.22*vocalFocus,p.confidence,'vocals');
    }
    if(vocalFocus>0&&music.vocals?.available&&music.vocals.presence!=='not_detected'&&music.vocals.sourceSeparated===true)for(const n of music.vocals.notes||[]){
      if(n.confidence>=.72&&n.strength>=.78&&n.end-n.start>=4.4)offer(n.start,'sustained vocal arrival',.72+.25*vocalFocus,n.confidence,'vocals',n.end);
    }
    if(bassFocus>0)for(const p of music.bassAnalysis?.phrases||[]){
      if(!p||p.confidence<.5+(1-bassFocus)*.15||!finite(p.start)||!finite(p.end)||p.end-p.start<.4)continue;
      offer(finite(p.accentTime)?p.accentTime:p.start,'pitched bass phrase',.62+.3*bassFocus,p.confidence,'bass',p.end);
    }
    // Individual notes only nominate an arrival after a musical gap or at a
    // sustained strong note. They never become per-note motor commands.
    let previousBassEnd=-Infinity;
    if(bassFocus>0)for(const note of music.bassNotes||[]){if(!note||!finite(note.start)||!finite(note.end)||note.confidence<.5+(1-bassFocus)*.15)continue;const gap=note.start-previousBassEnd;previousBassEnd=Math.max(previousBassEnd,note.end);if(gap>=1.1||note.end-note.start>=1.25&&note.strength>=.7)offer(note.start,'pitched bass arrival',.58+.3*bassFocus,note.confidence,'bass',note.end);}
    for(const t of downbeats.length?downbeats:beats.filter((_,i)=>i%(music.meter||4)===0))offer(t,'bar arrival',.36,confidence);
    // A measured transient still gives expressive, non-grid music a target.
    if(!pool.size)for(const onset of music.onsets||[])if(onset&&onset.strength>.45)offer(onset.time,'musical accent',onset.strength,confidence);
    const candidates=Array.from(pool.values()).sort((a,b)=>b.score-a.score||a.time-b.time);diagnostics.consideredTargets=candidates.length;
    if(!candidates.length){skipped.push('No confident active musical passage has room for choreography.');return result();}
    function add(id,start,finish,command,label,intent){
      const track=tracks.get(id),spec=specifications[id];if(!track)return false;
      const a=q(start),b=q(finish);
      if(a<0||b<=a||b>end+1e-7||track.length>=spec.limit||track.some(e=>a<e.end-1e-7&&b>e.start+1e-7))return false;
      if(command==='Dance'&&(spec.group==='mirrors'||track.filter(e=>e.command==='Dance').reduce((n,e)=>n+e.end-e.start,0)+b-a>spec.danceSeconds+1e-7))return false;
      const event={channels:[spec.channel],start:a,end:b,value:COMMAND[command],command,label,outputId:id,intent:intent||{}};
      events.push(event);track.push(event);return true;
    }
    function mark(id,candidate,kind,extra){
      const target=Object.assign({outputId:id,channels:[specifications[id].channel],time:candidate.time,musicTime:candidate.musicTime,kind,source:candidate.kind,role:candidate.role||'arrangement',score:Number(candidate.score.toFixed(4)),confidence:candidate.confidence},extra||{});
      targets.push(target);
      accents.push({time:candidate.time,channels:[specifications[id].channel],kind:kind==='dance'?'movement-arrival':kind,strength:clamp(candidate.score,.4,1),outputId:id});
    }
    function danceEnd(candidate,maxLength,minLength,latest){
      const t=candidate.time,musical=candidate.musicTime,range=rangeAt(musical),phrase=phraseAt(musical);
      if(!range)return null;
      // A short word or note cannot host a full motor gesture. Cadences can
      // receive mirror arrivals; they never start a new oscillation after voice
      // has ended. The source region, recovery and final return all must fit.
      if(candidate.role&&(candidate.kind.includes('cadence')||finite(candidate.roleEnd)&&candidate.roleEnd-musical<minLength))return null;
      let limit=Math.min(t+maxLength,range.end+shift-.08,latest);
      if(phrase&&phrase.end-musical>=minLength)limit=Math.min(limit,phrase.end+shift);
      if(finite(candidate.roleEnd)&&candidate.roleEnd-musical>=minLength)limit=Math.min(limit,candidate.roleEnd+shift);
      const absoluteBeats=beats,limitMusic=limit-shift,index=lower(absoluteBeats,limitMusic+1e-7)-1;
      let finish=index>=0&&absoluteBeats[index]+shift-t>=minLength?absoluteBeats[index]+shift:limit;
      finish=Math.floor((finish+1e-8)/step)*step;
      return finish-t>=minLength-1e-7?finish:null;
    }
    function select(make,maxCount){
      const selected=[];
      const available=candidates.map(make).filter(Boolean);
      while(available.length&&selected.length<maxCount){
        let best=-1,bestScore=-Infinity;
        for(let i=0;i<available.length;i++){
          const item=available[i];if(selected.some(other=>item.from<other.to+recovery&&item.to>other.from-recovery))continue;
          const separation=selected.length?Math.min(...selected.map(other=>Math.abs(item.candidate.time-other.candidate.time))):duration;
          // A small diversity reward resolves similar candidates without allowing
          // a weak passage to displace a substantially stronger musical entrance.
          const score=item.candidate.score+.045*Math.min(1,separation/Math.max(16,duration*.18));
          if(score>bestScore){best=i;bestScore=score;}
        }
        if(best<0)break;selected.push(available.splice(best,1)[0]);
      }
      return selected.sort((a,b)=>a.candidate.time-b.candidate.time);
    }
    // Windows remain open between gestures for cabin audio. A single final
    // re-open can restore audibility without consuming an extra command per beat.
    const windowIds=['windowFL','windowFR','windowRL','windowRR'].filter(id=>tracks.has(id));
    if(windowIds.length){
      // The strictest enabled window decides candidate eligibility. Individual
      // return commands retain their own calibrated lead time below.
      const closeStart=Math.min(...windowIds.map(id=>end-up(closeLead(id))),end),maxEpisodes=Math.max(1,Math.round((expressive?3:2)*density/.7)),maxDance=Math.min(expressive?9.4:8,5+6*density);
      const chosen=select(candidate=>{
        if(candidate.time<4.45||candidate.time>closeStart-4.5)return null;
        const finish=danceEnd(candidate,maxDance,4.4,closeStart-.25);
        if(finish===null)return null;
        return {candidate,from:candidate.time,to:finish,finish};
      },Math.min(expressive?3:2,maxEpisodes));
      if(chosen.length){
        const top=Math.max(...chosen.map(x=>x.candidate.score));
        for(let order=0;order<windowIds.length;order++){
          const id=windowIds[order],first=chosen[0].candidate,closeAt=end-up(closeLead(id)),openingStart=first.time-up(openLead(id));
          add(id,openingStart,first.time,'Open','Lower window ahead of musical entrance',calibratedIntent(id,'open',{type:'prepare',targetTime:first.time,travelSeconds:openTravel(id),estimatedArrival:predictedArrival(id,'open',openingStart,first.time-.30)}));
          let lastEnd=0,danceUsed=0;
          for(const item of chosen){
            let c=item.candidate;
            // The most salient passage is an ensemble gesture; other entrances
            // travel around the car on real local beats, including tempo changes.
            if(expressive&&!c.role&&c.score<top-1e-8&&order&&beats.length){
              const i=lower(beats,c.musicTime-1e-7),staggered=beats[i+order];
              if(finite(staggered)&&staggered-c.musicTime<=2.5)c=Object.assign({},c,{musicTime:staggered,time:q(staggered+shift)});
            }
            const finish=danceEnd(c,Math.min(maxDance,specifications[id].danceSeconds-danceUsed),4.4,Math.min(item.finish+2.5,closeAt-.25));
            if(finish===null||c.time<lastEnd+recovery-1e-7)continue;
            if(add(id,c.time,finish,'Dance',c.score===top?'Window ensemble at musical peak':'Window phrase response',calibratedIntent(id,'dance',{type:'dance',targetTime:c.time,source:c.kind,estimatedOscillation:true}))){danceUsed+=finish-c.time;lastEnd=finish;mark(id,c,'dance',{end:finish});}
          }
          if(lastEnd&&closeAt-lastEnd>8&&tracks.get(id).length<5)add(id,lastEnd,lastEnd+up(4.3),'Open','Restore open window for cabin audio',calibratedIntent(id,'open',{type:'recovery',travelSeconds:openTravel(id)}));
          add(id,closeAt,end,'Close','Return window closed before the ending',calibratedIntent(id,'close',{type:'return',travelSeconds:closeTravel(id),estimatedArrival:predictedArrival(id,'close',closeAt,closeAt+4)}));
        }
      }else skipped.push('Windows: no active phrase allows conservative travel, visible Dance and a closed finish.');
    }
    if(tracks.has('trunk')){
      const chosen=select(candidate=>{
        const start=candidate.time-up(openLead('trunk'));if(start<.05)return null;
        const finish=danceEnd(candidate,expressive?14:10,6,end-up(closeLead('trunk')));
        return finish===null?null:{candidate,from:start,to:finish+up(closeLead('trunk')),finish};
      },expressive&&density>=.6?2:1);
      for(const item of chosen){const t=item.candidate.time;
        add('trunk',item.from,t,'Open','Raise trunk early for musical arrival',calibratedIntent('trunk','open',{type:'prepare',targetTime:t,travelSeconds:openTravel('trunk'),estimatedArrival:predictedArrival('trunk','open',item.from,item.from+14)}));
        add('trunk',t,item.finish,'Dance','Trunk phrase at musical peak',calibratedIntent('trunk','dance',{type:'dance',targetTime:t,source:item.candidate.kind,estimatedOscillation:true}));
        add('trunk',item.finish,item.to,'Close','Recover trunk after the phrase',calibratedIntent('trunk','close',{type:'return',travelSeconds:closeTravel('trunk'),estimatedArrival:predictedArrival('trunk','close',item.finish,item.finish+4)}));
        mark('trunk',item.candidate,'dance',{end:item.finish,prepareStart:item.from,estimatedOpenArrival:predictedArrival('trunk','open',item.from,item.from+14)});
      }
      if(!chosen.length)skipped.push('Trunk: no phrase leaves conservative open travel, a visible Dance passage and return time.');
    }
    if(tracks.has('charge')){
      const chosen=select(candidate=>{const start=candidate.time-up(openLead('charge'));if(start<.05)return null;const finish=danceEnd(candidate,expressive?24:16,4,end-up(closeLead('charge')));return finish===null?null:{candidate,from:start,to:finish+up(closeLead('charge')),finish};},1);
      for(const item of chosen){const t=item.candidate.time;
        add('charge',item.from,t,'Open','Open charge port ahead of color arrival',calibratedIntent('charge','open',{type:'prepare',targetTime:t,travelSeconds:openTravel('charge'),estimatedArrival:predictedArrival('charge','open',item.from,item.from+2)}));
        add('charge',t,item.finish,'Dance','Rainbow charge-port colors for the phrase',calibratedIntent('charge','dance',{type:'color',targetTime:t,source:item.candidate.kind}));
        add('charge',item.finish,item.to,'Close','Close charge port after its color phrase',calibratedIntent('charge','close',{type:'return',travelSeconds:closeTravel('charge'),estimatedArrival:predictedArrival('charge','close',item.finish,item.finish+2)}));
        mark('charge',item.candidate,'rainbow',{end:item.finish,prepareStart:item.from});
      }
    }
    for(const [side,id]of ['mirrorL','mirrorR'].entries())if(tracks.has(id)){
      const chosen=select(candidate=>{
        let c=candidate;
        if(expressive&&!candidate.role&&side&&beats.length){const i=lower(beats,c.musicTime-1e-7),t=beats[i+1];if(finite(t)&&t-c.musicTime<=1.5)c=Object.assign({},c,{time:q(t+shift),musicTime:t});}
        if(!rangeAt(c.musicTime))return null;
        const unfold=c.time-up(openLead(id)),earliestFoldArrival=unfold-.65;
        let foldArrival=earliestFoldArrival;
        if(downbeats.length){const i=lower(downbeats,earliestFoldArrival-shift+1e-7)-1;if(i<0)return null;foldArrival=q(downbeats[i]+shift);}
        const fold=foldArrival-up(closeLead(id));
        if(fold<.10||c.time>end-.05||unfold<foldArrival+.50)return null;
        return {candidate:c,from:fold,to:c.time,foldArrival,unfold};
      },Math.max(1,Math.round((expressive?7:3)*density/.7)));
      for(const item of chosen){
        add(id,item.from,item.foldArrival,'Close','Fold mirror toward the preceding bar',calibratedIntent(id,'close',{type:'fold-arrival',targetTime:item.foldArrival,travelSeconds:closeTravel(id),estimatedArrival:predictedArrival(id,'close',item.from,item.from+2)}));
        add(id,item.unfold,item.to,'Open','Unfold mirror into musical arrival',calibratedIntent(id,'open',{type:'unfold-arrival',targetTime:item.to,travelSeconds:openTravel(id),estimatedArrival:predictedArrival(id,'open',item.unfold,item.unfold+2)}));
        mark(id,item.candidate,'mirror-arrival',{prepareStart:item.unfold,estimatedOpenArrival:predictedArrival(id,'open',item.unfold,item.unfold+2)});
      }
    }
    return result();
  }
  const api=Object.freeze({VERSION,plan,specifications:SPECS});
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.MovementPlanner=api;
})(typeof globalThis!=='undefined'?globalThis:this);

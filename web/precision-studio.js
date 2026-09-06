/* Precision studio: transactional musical edits through the application facade. */
(() => {
  'use strict';
  const app=window.LightForgeApp, $=id=>document.getElementById(id), audio=$('audio');
  if(!app)return;
  const panel=document.createElement('section');panel.id='precisionStudio';panel.className='precision-studio';panel.setAttribute('aria-labelledby','precisionTitle');
  panel.innerHTML=`<div class="section-heading"><div><div class="eyebrow">PRECISION STUDIO · 2.0</div><h3 id="precisionTitle">Give every cue a purpose</h3></div><span class="precision-chip">Voice + bass</span></div>
  <p class="muted small-copy">Listen, correct a musical moment, then review the lights it actually produces. Your original analysis is kept.</p>
  <div id="syncSummary" class="sync-summary" role="status"></div>
  <details id="syncDetails"><summary>Review synchronization</summary><p class="field-note">This checks selected musical targets against exported lamp commands. Detection timing and vehicle response still need listening and an in-car check.</p><div id="syncRoles" class="sync-role-grid"></div><div id="syncIssues" class="precision-list"></div></details>
  <details id="roleTiming"><summary>Correct timing for a musical part</summary><p class="field-note">Negative values place detected events earlier; positive values place them later. Your own cues stay at their entered times. The whole-show timing offset applies afterward.</p><form id="roleTimingForm" class="precision-form"><label>Voice correction (ms)<input id="vocalOffset" type="number" min="-2000" max="2000" step="1" value="0"></label><label>Bass correction (ms)<input id="bassOffset" type="number" min="-2000" max="2000" step="1" value="0"></label><button class="button secondary" type="submit">Apply part timing</button></form></details>
  <details id="cueWorkspace"><summary>Edit musical cues <span id="musicCueCount"></span></summary><p class="field-note">A cue replaces automatic interpretation for that part in its time range. Other instruments keep playing. Accent makes a short gesture; Hold sustains it; Ignore removes that part’s automatic cues.</p>
  <div class="precision-toolbar"><label>Musical part<select id="cueRole"><option value="vocals">Voice</option><option value="bass">Bass</option></select></label><button id="cueAtPlayhead" class="button secondary" type="button">Add at playhead</button></div>
  <details><summary>Start from a detected event</summary><div class="precision-toolbar"><button id="eventPrevious" class="text-button" type="button">Previous events</button><span id="eventPage" role="status"></span><button id="eventNext" class="text-button" type="button">Next events</button></div><div id="detectedEvents" class="precision-list"></div></details>
  <form id="musicCueForm" class="precision-form"><label>Start (seconds)<input id="musicCueStart" type="number" min="0" step="0.001" required value="0"></label><label>End (seconds)<input id="musicCueEnd" type="number" min="0.1" step="0.001" required value="0.3"></label><label>Gesture<select id="musicCueAction"><option value="accent">Accent</option><option value="hold">Hold</option><option value="mute">Ignore this part</option></select></label><label>Strength (%)<input id="musicCueStrength" type="number" min="10" max="100" step="1" value="80" required></label><label>Pitch (MIDI, optional)<input id="musicCuePitch" type="number" min="0" max="127" step="0.1" placeholder="No pitch specified"></label><label>Name (optional)<input id="musicCueLabel" maxlength="80" placeholder="e.g. Final held note"></label><div class="precision-actions"><button id="saveMusicCue" class="button secondary" type="submit">Save musical cue</button><button id="listenMusicCue" class="text-button" type="button">Loop this moment</button><button id="cancelMusicCue" class="text-button" type="button" hidden>Cancel edit</button></div></form>
  <p id="precisionMessage" class="field-note" role="status" aria-live="polite"></p><div id="savedMusicCues" class="precision-list"></div></details>`;
  $('musicIntelligence').after(panel);
  let editing=null,editingProject=null,page=0,lastMusic=null,lastShow=null,lastSettings=null,lastProject=null,events=[];
  const time=t=>`${Math.floor(t/60)}:${(t%60).toFixed(3).padStart(6,'0')}`;
  const blocked=()=>!app.state.music||app.state.busy||app.state.loadingProject||app.state.composing||app.state.auditionLoading||app.state.needAnalysis;
  const message=(s,error=false)=>{$('precisionMessage').textContent=s;$('precisionMessage').classList.toggle('error',error);};
  function seek(t){if(blocked())return;app.stopInspection();audio.currentTime=Math.max(0,Math.min(t,app.state.project.duration));app.renderFrame(audio.currentTime);app.drawWave();}
  function reset(){editing=null;editingProject=app.state.project?.id;$('cancelMusicCue').hidden=true;$('saveMusicCue').textContent='Save musical cue';}
  function populate(c){editing=c.id||null;editingProject=app.state.project?.id;$('cueRole').value=c.role;$('musicCueStart').value=c.start.toFixed(3);$('musicCueEnd').value=c.end.toFixed(3);$('musicCueAction').value=c.action||'accent';$('musicCueStrength').value=Math.round((c.strength||.8)*100);$('musicCuePitch').value=Number.isFinite(c.midi)?Math.round(c.midi*10)/10:'';$('musicCueLabel').value=c.label||'';$('cancelMusicCue').hidden=!editing;$('saveMusicCue').textContent=editing?'Update musical cue':'Save musical cue';$('cueWorkspace').open=true;message(editing?'Editing a saved musical cue.':'Review the timing and save this cue to replace automatic interpretation here.');seek(c.start);}
  function button(label,fn,cls='precision-row'){const b=document.createElement('button');b.type='button';b.className=cls;b.textContent=label;b.onclick=fn;b.disabled=blocked();return b;}
  function renderEvents(){const role=$('cueRole').value,shown=events.filter(e=>e.role===role),pages=Math.max(1,Math.ceil(shown.length/12));page=Math.min(page,pages-1);$('eventPage').textContent=`${shown.length} events · ${page+1} / ${pages}`;$('detectedEvents').replaceChildren(...shown.slice(page*12,page*12+12).map(c=>button(`${time(c.start)} · ${c.label}`,()=>populate(c))));if(!shown.length)$('detectedEvents').textContent='No detected events for this part. Add a cue at the playhead after listening.';$('eventPrevious').disabled=blocked()||page===0;$('eventNext').disabled=blocked()||page===pages-1;}
  function renderReview(show){
    const report=show?.synchronization;
    $('syncIssues').replaceChildren();$('syncRoles').replaceChildren();
    if(!report){$('syncSummary').textContent='Recreate this arrangement to review its exported musical timing.';return;}
    $('syncSummary').textContent=report.selected?`${report.matched} / ${report.selected} selected targets have a matching lamp attack${report.maxErrorMs===null?'':` · maximum frame error ${report.maxErrorMs.toFixed(1)} ms`}.`:'No vocal or bass targets selected. The instrumental arrangement remains active.';
    for(const [key,r] of Object.entries(report.roles)){const item=document.createElement('div');item.className='sync-role';const title=document.createElement('strong'),detail=document.createElement('span');title.textContent=key==='vocals'?'Voice':'Bass';detail.textContent=`${r.matched} / ${r.selected} matched · ${r.suppressed+r.heldWithoutAttack} to review`;item.append(title,detail);$('syncRoles').append(item);}
    for(const issue of report.issues.slice(0,20))$('syncIssues').append(button(`${time(issue.time)} · ${issue.role==='vocals'?'Voice':'Bass'} · ${issue.reason}`,()=>seek(issue.time)));
    if(report.selected>report.matched){const note=document.createElement('p');note.className='field-note';note.textContent='Review these moments by ear. Adjust the cue or enabled outputs if you want a distinct attack. '+(report.selected-report.matched>20?'Showing the first 20; the exported report contains up to 200.':'');$('syncIssues').append(note);}
  }
  function renderSaved(){
    const cues=app.state.settings.musicCues||[]; $('musicCueCount').textContent=cues.length?`(${cues.length})`:'';
    const fragment=document.createDocumentFragment();
    for(const c of cues){const row=document.createElement('div');row.className='saved-music-cue';row.append(button(`${time(c.start)}–${time(c.end)} · ${c.role==='vocals'?'Voice':'Bass'} · ${c.label||c.action}`,()=>populate(c)),button('Remove',async()=>{try{await app.commitChannelSettings({musicCues:(app.state.settings.musicCues||[]).filter(x=>x.id!==c.id)});if(editing===c.id)reset();message('Cue removed. Undo restores it.');}catch(e){message(e.message,true);}},'text-button compact'));fragment.append(row);}
    $('savedMusicCues').replaceChildren(fragment);
  }
  function refresh(){
    const state=app.state;panel.hidden=!state.music;
    panel.querySelectorAll('input,select,button').forEach(e=>e.disabled=blocked());
    const changed=lastProject!==state.project?.id||lastMusic!==state.music||lastSettings!==state.settings||lastShow!==state.show;
    if(!changed){renderEvents();return;}
    if(lastProject!==state.project?.id){reset();page=0;message('');}
    lastProject=state.project?.id;lastMusic=state.music;lastSettings=state.settings;lastShow=state.show;
    if(document.activeElement!==$('vocalOffset'))$('vocalOffset').value=state.settings.vocalOffsetMs||0;
    if(document.activeElement!==$('bassOffset'))$('bassOffset').value=state.settings.bassOffsetMs||0;
    // Display automatic model events with timing correction, without presenting
    // manual overlays as detections. Values remain on the soundtrack clock.
    const source=state.music||{},vs=(state.settings.vocalOffsetMs||0)/1000,bs=(state.settings.bassOffsetMs||0)/1000,duration=source.duration||0;
    events=[];
    for(const p of source.vocals?.phrases||[])events.push({role:'vocals',start:p.start+vs,end:p.end+vs,strength:p.strength,label:'Detected voice phrase',action:'hold'});
    for(const p of source.vocals?.accents||[])events.push({role:'vocals',start:p.time+vs,end:p.time+vs+.2,strength:p.strength,label:'Detected voice articulation',action:'accent'});
    for(const p of source.vocals?.notes||[])events.push({...p,role:'vocals',start:p.start+vs,end:p.end+vs,label:'Estimated voice note',action:'hold'});
    for(const p of source.bassNotes||[])events.push({...p,role:'bass',start:p.start+bs,end:p.end+bs,label:'Estimated bass note',action:p.end-p.start>=.5?'hold':'accent'});
    events=events.map(e=>({...e,start:Math.max(0,e.start),end:Math.min(duration,e.end)})).filter(e=>e.end-e.start>=.1-1e-8).sort((a,b)=>a.start-b.start);
    renderEvents();renderSaved();renderReview(state.show);
  }
  $('cueRole').onchange=()=>{reset();page=0;renderEvents();};
  $('eventPrevious').onclick=()=>{page--;renderEvents();};$('eventNext').onclick=()=>{page++;renderEvents();};
  $('cancelMusicCue').onclick=()=>{reset();message('Edit canceled. Your saved cue is unchanged.');};
  $('cueAtPlayhead').onclick=()=>{const duration=app.state.project.duration,start=Math.min(audio.currentTime||0,duration-.1);populate({role:$('cueRole').value,start,end:Math.min(duration,start+.3)});};
  $('listenMusicCue').onclick=()=>{const start=Number($('musicCueStart').value),end=Number($('musicCueEnd').value);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>app.state.project.duration){message('Choose a start and end within this soundtrack.',true);return;}if(window.StudioTools?.loopPassage(Math.max(0,start-.35),Math.min(app.state.project.duration,end+.35))){seek(Math.max(0,start-.35));message('This moment will repeat with a little listening space on either side. Press play.');}};
  $('roleTimingForm').onsubmit=async e=>{e.preventDefault();try{await app.commitChannelSettings({vocalOffsetMs:Number($('vocalOffset').value),bassOffsetMs:Number($('bassOffset').value)});message('Part timing applied. Your own cue times are unchanged.');}catch(error){message(error.message,true);}};
  $('musicCueForm').onsubmit=async e=>{e.preventDefault();if(blocked())return;try{
    if(editingProject&&editingProject!==app.state.project?.id)throw Error('This edit belongs to another project. Add a new cue here.');
    const c={id:editing||crypto.randomUUID(),role:$('cueRole').value,action:$('musicCueAction').value,start:Number($('musicCueStart').value),end:Number($('musicCueEnd').value),strength:Number($('musicCueStrength').value)/100,midi:$('musicCuePitch').value===''?null:Number($('musicCuePitch').value),label:$('musicCueLabel').value};
    const cues=MusicCues.normalize([...(app.state.settings.musicCues||[]).filter(x=>x.id!==editing),c]);
    await app.commitChannelSettings({musicCues:cues});reset();message('Musical cue saved. Listen to the result; Undo restores the previous arrangement.');
  }catch(error){message(error.message,true);}};
  document.addEventListener('lightforge:changed',refresh);refresh();
})();

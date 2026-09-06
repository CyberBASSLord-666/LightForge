/* Individual output editor. Uses the production generator for validation and preview. */
(() => {
  'use strict';
  const app=window.LightForgeApp,profile=window.VehicleProfile,$=id=>document.getElementById(id);
  if(!app||!profile)return;
  const values={Idle:0,Open:63,Dance:127,Close:191,Stop:255};
  const ramp=[[255,'On · instant'],[178,'Fade on · 500 ms'],[204,'Fade on · 1 second'],[230,'Fade on · 2 seconds'],[0,'Off · instant'],[26,'Fade off · 500 ms'],[51,'Fade off · 1 second'],[77,'Fade off · 2 seconds']];
  let kind='light',outputId='left-outer',editingId=null,projectId=null,actionSignature='';
  const output=()=>profile.outputs.find(o=>o.id===outputId);
  const mode=()=>output().optionalMode&&app.state.settings.outerBeamRamping?'ramp':output().mode;
  const cues=()=>app.state.settings.manualCues||[];
  const track=()=>cues().filter(c=>c.outputId===outputId).sort((a,b)=>a.start-b.start);
  const rgb=()=>[1,3,5].map(i=>parseInt($('cueColor').value.slice(i,i+2),16));
  const hex=color=>'#'+color.map(c=>c.toString(16).padStart(2,'0')).join('');
  const seconds=n=>Number(n.toFixed(3)).toString();
  const message=(value,error=false)=>{const el=$('channelMessage');el.textContent=value;el.hidden=!value;el.classList.toggle('error',error);};
  function actionOptions(){
    const o=output();
    if(o.kind==='rgb')return [['rgb','Set color']];
    if(o.kind==='light')return mode()==='ramp'?ramp:[[255,'On'],[0,'Off']];
    return o.commands.map(name=>{
      let label=name;
      if(o.id.startsWith('mirror'))label=name==='Open'?'Unfold':name==='Close'?'Fold':name;
      else if(o.id.startsWith('window'))label=name==='Open'?'Open · lower glass':name==='Close'?'Close · raise glass':name;
      else if(o.id==='charge'&&name==='Dance')label='Dance · rainbow LED';
      if(name==='Idle')label+=' · finish current travel';
      if(name==='Stop')label+=' · hold position';
      return [values[name],label];
    });
  }
  function setDefaultDuration(){
    const o=output(),v=Number($('cueAction').value);
    $('cueDuration').value=o.kind==='closure'?(v===127?8:o.id==='trunk'?(v===63?14:4):o.id.startsWith('window')?4:2):mode()==='ramp'&&[77,230].includes(v)?2:1;
  }
  function clearEdit(){editingId=null;$('cueEditorTitle').textContent='Add a cue';$('saveCue').textContent='Add cue';$('cancelCueEdit').hidden=true;}
  function select(id){
    app.stopInspection();outputId=id;kind=output().kind;actionSignature='';clearEdit();message('');refresh();
    $('cueAction').value=output().kind==='closure'?'63':output().kind==='rgb'?'rgb':'255';
    $('cueStart').value=seconds(Math.max(0,Math.min(app.state.project?.duration||0,$('audio').currentTime||0)));setDefaultDuration();
  }
  function edit(cue){
    editingId=cue.id;$('cueEditorTitle').textContent='Edit this cue';$('saveCue').textContent='Save cue';$('cancelCueEdit').hidden=false;
    $('cueStart').value=seconds(cue.start);$('cueDuration').value=seconds(cue.end-cue.start);
    if(cue.rgb){$('cueColor').value=hex(cue.rgb);$('cueColorText').textContent=hex(cue.rgb).toUpperCase();}else $('cueAction').value=cue.value;
    message('');$('cueStart').focus({preventScroll:true});
  }
  async function commit(patch,success){
    try{await app.commitChannelSettings(patch);clearEdit();refresh();message(success);return true;}
    catch(e){message(e.message||'This cue could not be saved.',true);return false;}
  }
  function renderTrack(){
    const list=$('outputCueList'),items=track();list.replaceChildren();$('clearOutputCues').disabled=!items.length||app.state.busy||app.state.composing||app.state.loadingProject;
    $('cueListHeading').textContent=items.length?`Custom cues · ${items.length}`:'Custom cues';
    if(!items.length){const p=document.createElement('p');p.className='cue-empty';p.textContent='Following your automatic choreography. Add a cue to make this output your own.';list.append(p);return;}
    const options=actionOptions();
    for(const cue of items){
      const row=document.createElement('div');row.className='cue-row';row.dataset.cueId=cue.id;
      const body=document.createElement('button');body.className='cue-open';body.disabled=app.state.busy||app.state.composing||app.state.loadingProject;body.setAttribute('aria-label',`Edit cue at ${seconds(cue.start)} seconds`);
      const title=document.createElement('b');title.textContent=cue.rgb?hex(cue.rgb).toUpperCase():options.find(o=>o[0]===cue.value)?.[1]||String(cue.value);
      if(cue.label==='Return closed'||cue.label==='Return unfolded'||cue.label==='Prepare to dance')title.textContent=cue.label+' · '+title.textContent;
      const time=document.createElement('small');time.textContent=`${seconds(cue.start)} – ${seconds(cue.end)} s · ${seconds(cue.end-cue.start)} s`;
      if(cue.rgb){const dot=document.createElement('i');dot.className='cue-swatch';dot.style.background=hex(cue.rgb);title.prepend(dot);}
      body.append(title,time);body.onclick=()=>edit(cue);
      const remove=document.createElement('button');remove.className='cue-remove';remove.textContent='×';remove.setAttribute('aria-label',`Remove cue at ${seconds(cue.start)} seconds`);remove.disabled=app.state.busy||app.state.composing||app.state.loadingProject;
      remove.onclick=()=>commit({manualCues:cues().filter(c=>c.id!==cue.id)},'Cue removed. Undo is available.');row.append(body,remove);list.append(row);
    }
  }
  function refresh(){
    const s=app.state;
    if(projectId!==s.project?.id){projectId=s.project?.id;clearEdit();message('');$('cueStart').value='0';}
    const o=output(),available=profile.outputs.filter(x=>x.available);
    $('channelSummary').textContent=`${available.filter(x=>x.kind==='light').length} light groups · 6 cabin zones · 8 moving parts`;
    document.querySelectorAll('[data-output-kind]').forEach(el=>{const selected=el.dataset.outputKind===kind;el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));});
    const selectEl=$('outputSelect');if(selectEl.dataset.kind!==kind){selectEl.replaceChildren(...available.filter(x=>x.kind===kind).map(x=>new Option(x.name,x.id)));selectEl.dataset.kind=kind;}
    selectEl.value=outputId;
    $('outputMode').textContent=o.kind==='closure'?`${o.commands.length} commands · ${o.commandLimit} actuations / show`:o.kind==='rgb'?'Full RGB color':mode()==='ramp'?'On / off + 3 fade lengths':'On / off';
    $('outputChannels').textContent='FSEQ '+o.channels.join(' · ');$('outputNote').textContent=o.note;
    if(!s.composing)$('outputEnabled').checked=s.settings.outputEnabled?.[outputId]!==false;$('outputEnabled').disabled=!s.project||s.busy||s.composing||s.loadingProject;
    $('outerRampOption').hidden=!o.optionalMode;if(!s.composing)$('outerBeamRamping').checked=!!s.settings.outerBeamRamping;
    $('outerBeamRamping').disabled=!s.project||s.busy||s.composing||s.loadingProject;
    const custom=track().length>0;
    $('outputUsage').textContent=s.settings.outputEnabled?.[outputId]===false?'Muted in preview and export':o.kind==='closure'&&custom?'Your custom track replaces automatic movement':'Automatic choreography with your custom cues';
    const options=actionOptions(),signature=JSON.stringify(options);
    if(signature!==actionSignature){const prior=$('cueAction').value;$('cueAction').replaceChildren(...options.map(([v,label])=>new Option(label,v)));if(options.some(x=>String(x[0])===prior))$('cueAction').value=prior;actionSignature=signature;}
    $('cueColorFields').hidden=o.kind!=='rgb';$('cueColorText').textContent=$('cueColor').value.toUpperCase();
    $('cueTrackNote').textContent=o.kind==='closure'?`Custom cues replace this part’s entire automatic track. Idle fills the gaps. ${o.id==='trunk'||o.id==='charge'?'Add Open before Dance. ':''}${o.id.startsWith('mirror')?'Alternate Fold and Unfold.':`Keep Dance sections around ${o.recommendedDanceSeconds} seconds or less.`} Travel is estimated.`:'Cues replace the selected light commands only during their time range. Other moments follow your automatic choreography. Timing snaps to the show’s frame interval.';
    const ready=!!s.music&&!s.needAnalysis&&!s.busy&&!s.composing&&!s.loadingProject;
    for(const id of ['cueStart','cueDuration','cueUsePlayhead','saveCue'])$(id).disabled=!ready;
    for(const id of ['cueAction','cueColor'])$(id).disabled=!s.project||s.busy||s.composing||s.loadingProject;
    $('inspectOutput').disabled=!s.project||s.busy||s.composing||s.loadingProject;
    $('saveCue').title=ready?'':'Create or re-analyze the music before adding cues.';
    $('cueStart').max=String(s.project?.duration||0);$('cueDuration').max=String(s.project?.duration||0);
    if(!ready&&s.project&&!s.busy)$('cueTrackNote').textContent='Create your show first to add timed cues. You can still inspect the selected output in the preview.';
    renderTrack();inspectionChanged();
  }
  function inspectionChanged(){const inspecting=!!app.state.soloPreview;$('inspectOutput').textContent=inspecting?'Stop inspection':'Inspect in preview';$('inspectOutput').setAttribute('aria-pressed',String(inspecting));$('channelStudio').classList.toggle('inspecting',inspecting);}
  document.querySelectorAll('[data-output-kind]').forEach(el=>el.onclick=()=>select(profile.outputs.find(o=>o.available&&o.kind===el.dataset.outputKind).id));
  $('outputSelect').onchange=()=>select($('outputSelect').value);
  $('outputEnabled').onchange=async()=>{const requested=$('outputEnabled').checked;if(!await commit({outputEnabled:{...app.state.settings.outputEnabled,[outputId]:requested}},requested?'Output included in your show.':'Output muted in your show.'))refresh();};
  $('outerBeamRamping').onchange=async()=>{if(!await commit({outerBeamRamping:$('outerBeamRamping').checked},'Outer-beam fade setting updated for both headlamps.'))refresh();};
  $('cueAction').onchange=()=>{app.stopInspection();if(!editingId)setDefaultDuration();};
  $('cueColor').oninput=()=>{$('cueColorText').textContent=$('cueColor').value.toUpperCase();};
  $('cueUsePlayhead').onclick=()=>{$('cueStart').value=seconds($('audio').currentTime||0);};
  $('inspectOutput').onclick=()=>{try{if(app.state.soloPreview)app.stopInspection();else{app.startInspection(output(),Number($('cueAction').value),rgb());document.querySelector('.preview-card').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}}catch(e){app.stopInspection();message('Preview could not start: '+e.message,true);}};
  $('saveCue').onclick=()=>{
    const start=Number($('cueStart').value),duration=Number($('cueDuration').value);
    if(!$('cueStart').value||!$('cueDuration').value||!Number.isFinite(start)||!Number.isFinite(duration)||start<0||duration<=0){message('Enter a start time of zero or later and a positive duration.',true);return;}
    const cue={id:editingId||'cue-'+Date.now()+'-'+Math.random().toString(36).slice(2,8),outputId,start,end:Number((start+duration).toFixed(6)),label:output().name};
    if(output().kind==='rgb')cue.rgb=rgb();else cue.value=Number($('cueAction').value);
    const next=cues().filter(c=>c.id!==cue.id);next.push(cue);let prepared=false,returned=false;
    const o=output(),mirror=o.id.startsWith('mirror'),home=mirror?63:191;
    if(o.kind==='closure'){
      const others=next.filter(c=>c.outputId===outputId&&c.id!==cue.id);
      if(cue.value===127&&(o.id==='trunk'||o.id==='charge')&&!others.some(c=>c.value===63&&c.start<cue.start)){
        const travel=o.id==='trunk'?14:2,start=Number((cue.start-travel-.04).toFixed(6));
        if(start<0){message(`Start Dance at ${travel+.04} seconds or later so the ${o.name.toLowerCase()} can open first, or add an Open cue before it.`,true);return;}
        next.push({id:'prepare-'+cue.id,outputId,start,end:cue.start,value:63,label:'Prepare to dance'});prepared=true;
      }
      const away=mirror?[191,255].includes(cue.value):[63,127,255].includes(cue.value);
      if(away&&!others.some(c=>c.value===home&&c.start>=cue.end)){
        const travel=mirror||o.id==='charge'?2:4,end=Number(((app.state.project?.duration||0)-.2).toFixed(6)),start=Number((end-travel).toFixed(6));
        next.push({id:'return-'+cue.id,outputId,start,end,value:home,label:mirror?'Return unfolded':'Return closed'});returned=true;
      }
    }
    const success=editingId?'Cue updated. Saved with your project.':'Cue added. Saved with your project.';
    commit({manualCues:next},success+(prepared?' An Open cue prepares the dance.':'')+(returned?' A visible return cue finishes the movement.':''));
  };
  $('cancelCueEdit').onclick=()=>{clearEdit();message('');};
  $('clearOutputCues').onclick=()=>commit({manualCues:cues().filter(c=>c.outputId!==outputId)},'Automatic choreography restored for this output.');
  $('capabilityScope').textContent=profile.scope;
  $('unavailableOutputs').textContent='Not fitted in this profile: '+profile.outputs.filter(o=>!o.available).map(o=>o.name.toLowerCase()).join(', ')+'.';
  $('unsupportedFeatures').textContent='No public show controls for: '+profile.unavailableFeatures.join('; ')+'.';
  document.addEventListener('lightforge:changed',refresh);document.addEventListener('lightforge:inspection',inspectionChanged);
  window.ChannelStudio={select,refresh};refresh();
})();

/* LightForge cockpit. Navigation and source-clock inspection; edits use the
 * existing transactional application facade. No alternate project state. */
(()=>{'use strict';
const app=window.LightForgeApp,$=id=>document.getElementById(id);if(!app)return;
const controls=document.querySelector('.controls-column'),preview=document.querySelector('.preview-column');
const workspace=document.createElement('section');workspace.className='cockpit-console';workspace.setAttribute('aria-label','Choreography workspace');
const tabs=document.createElement('div');tabs.className='cockpit-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Studio workspace');workspace.append(tabs);
const panels={};
for(const [id,label]of [['compose','Compose'],['music','Music'],['outputs','Outputs'],['review','Review']]){
 const b=document.createElement('button');b.id='workspace-'+id;b.type='button';b.textContent=label;b.setAttribute('role','tab');b.setAttribute('aria-controls','panel-'+id);b.dataset.workspace=id;tabs.append(b);
 const p=document.createElement('div');p.id='panel-'+id;p.className='cockpit-panel';p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby',b.id);panels[id]=p;workspace.append(p);
 b.onclick=()=>select(id);b.onkeydown=e=>{const all=[...tabs.children],i=all.indexOf(b);if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?all.length-1:(i+(e.key==='ArrowLeft'?-1:1)+all.length)%all.length;all[n].click();all[n].focus();};
}
controls.prepend(workspace);
const action=controls.querySelector('.action-card'),advanced=controls.querySelector('.advanced'),feel=controls.querySelector('.control-card'),focus=controls.querySelector('.musical-focus');
panels.compose.append(feel,focus,advanced);for(const card of [...controls.querySelectorAll(':scope > .control-card')])panels.outputs.append(card);
panels.outputs.append($('channelStudio'));$('channelStudio').open=true;
panels.music.append($('musicIntelligence'));panels.review.append($('precisionStudio'));
const sections=document.querySelector('.sections-card');panels.compose.append(sections);
const unavailable=document.createElement('p');unavailable.className='cockpit-unavailable';unavailable.textContent='Analyze your track to inspect its musical detail.';panels.music.prepend(unavailable);
controls.replaceChildren(workspace,action);
function select(id){for(const b of tabs.children){const yes=b.dataset.workspace===id;b.setAttribute('aria-selected',String(yes));b.tabIndex=yes?0:-1;panels[b.dataset.workspace].hidden=!yes;}document.dispatchEvent(new CustomEvent('lightforge:workspace',{detail:id}));}
select('compose');
// Keep deep links and contextual editing discoverable after reorganization.
document.addEventListener('lightforge:reveal',e=>{for(const [id,p]of Object.entries(panels))if(p.contains(e.detail))select(id);});
$('quickTune').onclick=()=>{select('compose');controls.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});};
const header=document.createElement('div');header.className='vehicle-identity';header.innerHTML='<div><span class="eyebrow">YOUR VEHICLE</span><h2>Model 3</h2><p>Long Range RWD <span>2025 · North America</span></p></div><span class="vehicle-ready">LOCAL STUDIO</span>';
preview.prepend(header);
const timeline=document.createElement('section');timeline.id='scoreTimeline';timeline.className='score-timeline';timeline.setAttribute('aria-labelledby','scoreTitle');
timeline.innerHTML='<div class="score-heading"><div><span class="eyebrow">SOURCE CLOCK</span><h3 id="scoreTitle">The musical score</h3></div><div class="score-zoom"><button id="scoreZoomOut" type="button" aria-label="Zoom out timeline">−</button><output id="scoreScale">Full track</output><button id="scoreZoomIn" type="button" aria-label="Zoom in timeline">+</button></div></div><div class="score-track"><canvas id="scoreCanvas" aria-hidden="true"></canvas><input id="scoreSeek" type="range" min="0" max="1" step="0.001" value="0" aria-label="Seek musical score"></div><div class="score-footer"><span>Voice · bass · musical cues</span><output id="scorePosition">0:00.000</output></div>';
document.querySelector('.preview-card').after(timeline);
const canvas=$('scoreCanvas'),ctx=canvas.getContext('2d'),audio=$('audio');let visible=true;let zoom=1,lastMusic=null,lastSettings=null,lastWidth=0,from=0,span=1,pending=false;
function draw(){pending=false;const music=app.state.music;timeline.hidden=!music;if(!music||!ctx)return;
 const duration=app.state.project?.duration||music.duration||1,time=Math.min(duration,audio.currentTime||0),width=Math.max(1,canvas.clientWidth),height=154,dpr=Math.min(2,devicePixelRatio||1);
 if(canvas.width!==Math.round(width*dpr)){canvas.width=Math.round(width*dpr);canvas.height=height*dpr;}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);span=Math.max(2,duration/zoom);from=zoom===1?0:Math.max(0,Math.min(duration-span,time-span*.35));
 const x=t=>(t-from)/span*width,intersects=(a,b)=>b>=from&&a<=from+span;
 ctx.fillStyle='#8e9299';ctx.font='10px Inter, sans-serif';ctx.textBaseline='middle';
 const tick=span>90?30:span>30?10:span>10?5:1;
 for(let t=Math.ceil(from/tick)*tick;t<from+span;t+=tick){ctx.fillStyle='#292b30';ctx.fillRect(x(t),22,1,126);ctx.fillStyle='#8e9299';ctx.fillText(Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0'),Math.max(2,x(t)+4),10);}
 const band=(a,b,y,h,color)=>{if(!intersects(a,b))return;const l=Math.max(0,x(a)),r=Math.min(width,x(b));ctx.fillStyle=color;ctx.fillRect(l,y,Math.max(1,r-l),h);};
 for(const p of music.vocals?.phrases||[])band(p.start+(app.state.settings.vocalOffsetMs||0)/1000,p.end+(app.state.settings.vocalOffsetMs||0)/1000,39,28,'#33373e');
 for(const n of music.vocals?.notes||[])band(n.start+(app.state.settings.vocalOffsetMs||0)/1000,n.end+(app.state.settings.vocalOffsetMs||0)/1000,60-Math.max(0,Math.min(24,(n.midi-45)*.55)),5,'#eceef1');
 for(const n of music.bassNotes||[])band(n.start+(app.state.settings.bassOffsetMs||0)/1000,n.end+(app.state.settings.bassOffsetMs||0)/1000,91-Math.max(0,Math.min(15,(n.midi-28)*.45)),8,'#b89b74');
 for(const c of app.state.settings.musicCues||[])band(c.start,c.end,113,16,c.action==='mute'?'#71434a':'#e84049');
 ctx.fillStyle='#a3a6ac';ctx.font='9px Inter, sans-serif';ctx.fillText('VOICE',5,29);ctx.fillText('BASS',5,75);ctx.fillText('EDITS',5,108);
 ctx.fillStyle='#ef414a';ctx.fillRect(x(time)-.5,20,1.5,124);ctx.beginPath();ctx.moveTo(x(time)-4,20);ctx.lineTo(x(time)+4,20);ctx.lineTo(x(time),25);ctx.fill();
 $('scoreSeek').min=from;$('scoreSeek').max=Math.min(duration,from+span);$('scoreSeek').value=time;$('scorePosition').textContent=Math.floor(time/60)+':'+(time%60).toFixed(3).padStart(6,'0');$('scoreScale').textContent=zoom===1?'Full track':Math.round(span)+' seconds';$('scoreZoomOut').disabled=zoom===1;$('scoreZoomIn').disabled=span<=2;
 lastMusic=music;lastSettings=app.state.settings;lastWidth=width;if(!audio.paused&&visible&&!document.hidden)setTimeout(schedule,32);
}
function schedule(){if(!visible||document.hidden)return;if(!pending){pending=true;requestAnimationFrame(draw);}}
$('scoreSeek').oninput=e=>{if(app.state.busy||app.state.loadingProject)return;app.stopInspection();audio.currentTime=Number(e.target.value);app.renderFrame(audio.currentTime);app.drawWave();schedule();};
$('scoreZoomIn').onclick=()=>{zoom=Math.min(256,zoom*2);schedule();};$('scoreZoomOut').onclick=()=>{zoom=Math.max(1,zoom/2);schedule();};
if(typeof IntersectionObserver==='function')new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)schedule();}).observe(timeline);
 audio.addEventListener('play',schedule);audio.addEventListener('timeupdate',schedule);audio.addEventListener('seeked',schedule);window.addEventListener('resize',schedule);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
document.addEventListener('lightforge:changed',()=>{unavailable.hidden=!!app.state.music;sections.hidden=!app.state.show;document.body.classList.toggle('has-project',!!app.state.project);if(lastMusic!==app.state.music||lastSettings!==app.state.settings||lastWidth!==canvas.clientWidth)schedule();});
window.LightForgeCockpit={select,draw};schedule();
})();

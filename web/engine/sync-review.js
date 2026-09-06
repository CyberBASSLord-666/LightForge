/* Review actual exported command bytes after overrides and output switches. */
(function(root){
  'use strict';
  const PROFILE=root.VehicleProfile||(typeof require==='function'?require('./vehicle-profile.js'):null);
  const key=t=>[t.role,t.cueId||'',Math.round(t.time*1e6)].join(':');
  function review(show, targets) {
    const step=show.stepMs/1000,byId=new Map(PROFILE.outputs.map(o=>[o.id,o]));
    const events=new Map();
    for(const e of show.lightEvents||[]) if(e.role){const k=key({role:e.role,cueId:e.cueId,time:e.sourceEventTime??e.sourceStart});const group=events.get(k)||[];group.push(e);events.set(k,group);}
    const roles={vocals:{selected:0,matched:0,suppressed:0,heldWithoutAttack:0},bass:{selected:0,matched:0,suppressed:0,heldWithoutAttack:0}};
    const issues=[],manual=[],errors=[],seen=new Set();
    for(const t of targets||[]) {
      const k=key(t);if(seen.has(k))continue;seen.add(k);
      const role=roles[t.role];if(!role)continue;role.selected++;
      const expected=t.time+show.settings.offsetMs/1000,frame=Math.round(expected/step);
      let status='suppressed',errorMs=null,output=null;
      for(const e of events.get(k)||[]) {
        const actual=Math.round(e.actualStart/step),o=byId.get(e.id);
        if(!o || actual<0 || actual>=show.frameCount-1 || Math.abs(actual*step-expected)>step/2+1e-7)continue;
        const values=o.channels.map(ch=>({now:show.frames[actual*200+ch-1],before:actual?show.frames[(actual-1)*200+ch-1]:0}));
        if(values.some(v=>[255,178,204,230].includes(v.now)&&v.now!==v.before)){status='matched';errorMs=(actual*step-expected)*1000;output=e.id;break;}
        if(values.some(v=>v.now>0))status='heldWithoutAttack';
      }
      role[status]++;if(errorMs!==null)errors.push(Math.abs(errorMs));
      const row={role:t.role,time:t.time,end:t.end,kind:t.kind,cueId:t.cueId||null,status,output,errorMs};
      if(t.cueId)manual.push(row);
      if(status!=='matched'&&issues.length<200)issues.push({...row,reason:frame<0||frame>=show.frameCount-1?'Outside exportable frames':status==='heldWithoutAttack'?'Output was already active':'Collision, disabled output, silence, or manual output override'});
    }
    errors.sort((a,b)=>a-b);
    const count=roles.vocals.selected+roles.bass.selected,matched=roles.vocals.matched+roles.bass.matched;
    return {version:1,scope:'Selected musical targets compared with final FSEQ commands; not detection accuracy or measured vehicle latency.',frameStepMs:show.stepMs,roles,selected:count,matched,coverage:count?matched/count:null,maxErrorMs:errors.length?errors[errors.length-1]:null,medianErrorMs:errors.length?errors[Math.floor(errors.length/2)]:null,issues,omittedIssues:Math.max(0,count-matched-issues.length),manual};
  }
  const api={review};root.SyncReview=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

/* Musical edits live beside model evidence. Times are seconds on the soundtrack. */
(function (root) {
  'use strict';
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  function normalize(input) {
    if (input == null) return [];
    if (!Array.isArray(input) || input.length > 2000) throw Error('Use at most 2,000 musical cues per project.');
    const ids = new Set();
    const cues = input.map(c => {
      if (!c || typeof c.id !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(c.id) || ids.has(c.id)) throw Error('Each musical cue needs a unique identifier.');
      ids.add(c.id);
      if (!['vocals', 'bass'].includes(c.role) || !['accent', 'hold', 'mute'].includes(c.action)) throw Error('Choose Voice or Bass and a musical cue action.');
      if (!finite(c.start) || !finite(c.end) || c.start < 0 || c.end > 14400 || c.end - c.start < .1 - 1e-8) throw Error('A musical cue needs at least 0.10 seconds between its start and end.');
      if (c.midi != null && (!finite(c.midi) || c.midi < 0 || c.midi > 127)) throw Error('Choose a pitch between MIDI 0 and 127, or leave it empty.');
      return {id:c.id, role:c.role, action:c.action, start:c.start, end:c.end, strength:clamp(finite(c.strength) ? c.strength : .8, .1, 1), midi:c.midi == null ? null : c.midi, label:String(c.label || '').slice(0, 80)};
    }).sort((a,b) => a.start - b.start || a.role.localeCompare(b.role) || a.id.localeCompare(b.id));
    for (const role of ['vocals','bass']) {
      const lane = cues.filter(c => c.role === role);
      for (let i=1; i<lane.length; i++) if (lane[i].start < lane[i-1].end - 1e-8) throw Error('Musical cues for the same part must not overlap. Edit or remove the existing cue first.');
    }
    return cues;
  }
  function apply(m, s) {
    const shiftSpans = (items, ms) => items.map(p => ({...p, start:clamp(p.start+ms/1000,0,m.duration), end:clamp(p.end+ms/1000,0,m.duration), ...(finite(p.peakTime)?{peakTime:clamp(p.peakTime+ms/1000,0,m.duration)}:{})})).filter(p => p.end-p.start >= .1-1e-8);
    const voiceShift=s.vocalOffsetMs||0, bassShift=s.bassOffsetMs||0;
    const shifted = {...m, vocals:{...m.vocals, phrases:shiftSpans(m.vocals.phrases,voiceShift), notes:shiftSpans(m.vocals.notes,voiceShift), accents:m.vocals.accents.map(p => ({...p,time:p.time+voiceShift/1000})).filter(p => p.time>=0 && p.time<m.duration), envelopeOffset:voiceShift/1000, pitchOffset:voiceShift/1000}, bassNotes:shiftSpans(m.bassNotes,bassShift), bassAnalysis:{...m.bassAnalysis,phrases:shiftSpans(m.bassAnalysis.phrases,bassShift),envelopeOffset:bassShift/1000}};
    return shifted;
  }
  function overlay(m, s) {
    const cues=s.musicCues || [];
    for(const c of cues) if(c.start>=m.duration || c.end>m.duration+1e-8) throw Error('A musical cue extends beyond this soundtrack. Shorten or remove it before composing.');
    if(!cues.length) return {...m,musicCues:[]};
    const overlaps=(p,c)=>p.start<c.end-1e-8 && p.end>c.start+1e-8;
    const voice=cues.filter(c=>c.role==='vocals'),bass=cues.filter(c=>c.role==='bass');
    // Keep phrasing outside edited spans; tagged continuations cannot invent a
    // new vocal attack at the end of a mute/hold region.
    function subtract(items, edits) {
      let result=items.map(p=>({...p}));
      for(const c of edits) result=result.flatMap(p=>!overlaps(p,c)?[p]:[...(p.start<c.start?[{...p,end:c.start}]:[]),...(p.end>c.end?[{...p,start:c.end,continuation:true}]:[])]);
      return result.filter(p=>p.end-p.start>=.1-1e-8);
    }
    const manualPhrase=c=>({start:c.start,end:c.end,confidence:1,strength:c.strength,kind:'vocal',manual:true,musicalCue:true,midi:c.midi});
    const phrases=subtract(m.vocals.phrases,voice).concat(voice.filter(c=>c.action!=='mute').map(manualPhrase)).sort((a,b)=>a.start-b.start);
    return {...m,musicCues:cues,vocals:{...m.vocals,phrases,available:m.vocals.available||phrases.length>0,presence:phrases.length?'detected':'not_detected',notes:subtract(m.vocals.notes,voice).concat(voice.filter(c=>c.action!=='mute'&&c.midi!==null).map(c=>({...manualPhrase(c),midi:c.midi}))).sort((a,b)=>a.start-b.start),accents:m.vocals.accents.filter(a=>!voice.some(c=>a.time>=c.start && a.time<c.end))},bassNotes:m.bassNotes.filter(p=>!bass.some(c=>overlaps(p,c))).concat(bass.filter(c=>c.action!=='mute').map(c=>({...manualPhrase(c),midi:c.midi}))).sort((a,b)=>a.start-b.start)};
  }
  const api={normalize,apply,overlay};root.MusicCues=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);

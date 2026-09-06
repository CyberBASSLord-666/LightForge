/* Explain actual source analysis and the effective, user-corrected musical plan. */
(() => {
  'use strict';
  const app = window.LightForgeApp, $ = id => document.getElementById(id);
  if (!app) return;
  const audio = $('audio'), clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  let shown = null, roleMusic = null, roleFrame = 0, lastTick = 0, nowVisible = false, lanesVisible = false;
  let vocalPhrases = [], vocalNotes = [], bassNotes = [], duration = 0, sourceSeparated = false;
  const time = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}.${Math.floor(t % 1 * 10)}`;
  const evidence = value => value == null || !Number.isFinite(Number(value)) ? 'Evidence unavailable' : Number(value) >= .8 ? 'Strong evidence' : Number(value) >= .55 ? 'Moderate evidence' : 'Uncertain evidence';
  const noteName = midi => { if (midi == null) return ''; const n = Math.round(Number(midi)); return Number.isFinite(n) ? `${['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'][((n % 12) + 12) % 12]}${Math.floor(n / 12) - 1}` : ''; };
  const validSpans = entries => (Array.isArray(entries) ? entries : []).filter(x => x && Number.isFinite(x.start) && Number.isFinite(x.end) && x.end > x.start && x.start >= 0 && x.start < duration).slice().sort((a, b) => a.start - b.start);
  function activeSpan(entries, t) {
    let lo = 0, hi = entries.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (entries[mid].start <= t) lo = mid + 1; else hi = mid; }
    const entry = entries[lo - 1];
    return entry && t < entry.end ? entry : null;
  }
  function roleStateAt(t) { return { vocal: activeSpan(vocalPhrases, t), vocalNote: activeSpan(vocalNotes, t), bass: activeSpan(bassNotes, t) }; }
  function setText(id, value) { const element = $(id); if (element.textContent !== value) element.textContent = value; }
  function phraseLabel(phrase) { return phrase?.manual ? 'Your voice guide' : phrase?.kind === 'speech' ? 'Spoken phrase' : phrase?.kind === 'vocal' ? 'Voice phrase' : 'Sung phrase'; }
  function updatePlayhead() {
    const t = clamp(audio.currentTime || 0, 0, duration || 0), current = roleStateAt(t);
    for (const role of ['vocal', 'bass']) {
      const chip = $(role + 'Now'), input = $(role + 'TimelineSeek'), active = current[role];
      chip.classList.toggle('active', !!active);
      const label = role === 'vocal' ? active ? phraseLabel(active) + (current.vocalNote ? ` · ${noteName(current.vocalNote.midi)}` : '') : vocalPhrases.length ? 'Between voice phrases' : 'No confident voice' : active ? `Bass ${noteName(active.midi)}`.trim() : bassNotes.length ? 'Between bass notes' : 'No confident bass notes';
      if (chip.lastElementChild.textContent !== label) chip.lastElementChild.textContent = label;
      input.value = t;
      input.setAttribute('aria-valuetext', `${time(t)} of ${time(duration)}${active ? role === 'vocal' ? ', estimated vocal phrase' : `, estimated bass ${noteName(active.midi)}` : ''}`);
      input.parentElement.style.setProperty('--playhead', `${duration ? t / duration * 100 : 0}%`);
    }
    const phrase = current.vocal, note = current.vocalNote;
    setText('vocalDetailPitch', note ? noteName(note.midi) || '♪' : '—');
    setText('vocalDetailTitle', phrase ? phraseLabel(phrase) : 'Between voice phrases');
    const detail = phrase
      ? `${time(phrase.start)}–${time(phrase.end)}${note ? ` · ${note.type === 'held-note' ? 'Held note' : 'Note'} ${(note.end - note.start).toFixed(2)} s · ${evidence(note.confidence).toLowerCase()}` : phrase.manual ? ' · Your guide shapes this passage; measured note detail is unchanged.' : ' · Phrase-level movement and light phrasing.'}`
      : vocalPhrases.length ? 'Drag the voice lane or jump to the next phrase to hear its entrance and release.' : 'No confident voice passage is available. You can add a guide below.';
    setText('vocalDetailText', detail);
    $('loopVocalPhrase').disabled = !phrase || phrase.end - phrase.start < .1 || app.state.busy || app.state.composing || app.state.loadingProject || app.state.auditionLoading;
  }
  function tick(now) {
    roleFrame = 0;
    if (audio.paused || document.hidden || (!nowVisible && !lanesVisible) || !roleMusic) return;
    if (now - lastTick > 80) { updatePlayhead(); lastTick = now; }
    roleFrame = requestAnimationFrame(tick);
  }
  function startTick() {
    cancelAnimationFrame(roleFrame); roleFrame = 0; updatePlayhead();
    if (!audio.paused && !document.hidden && (nowVisible || lanesVisible) && roleMusic) roleFrame = requestAnimationFrame(tick);
  }
  function seek(t) {
    if (!app.state.project || app.state.busy || app.state.composing || app.state.loadingProject || app.state.auditionLoading || !Number.isFinite(t)) return;
    app.stopInspection(); audio.currentTime = clamp(t, 0, duration || 0);
    app.renderFrame(audio.currentTime); app.drawWave(); updatePlayhead();
  }
  function seekNext(entries, label) {
    if (!entries.length) return;
    const t = audio.currentTime || 0, next = entries.find(x => x.start > t + .04);
    seek((next || entries[0]).start);
    if (!next) app.toast(`Back to the first estimated ${label}.`);
    document.querySelector('.preview-card').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }
  $('nextVocalPhrase').onclick = () => seekNext(vocalPhrases, 'vocal phrase');
  $('nextBassNote').onclick = () => seekNext(bassNotes, 'bass note');
  $('nextVocalNote').onclick = () => seekNext(vocalNotes, 'voice note');
  $('loopVocalPhrase').onclick = () => {
    const phrase = activeSpan(vocalPhrases, audio.currentTime || 0);
    if (phrase && window.StudioTools?.loopPassage(phrase.start, phrase.end)) app.toast('Voice phrase ready to repeat. Press play to review.');
  };
  for (const role of ['vocal', 'bass']) $(role + 'TimelineSeek').oninput = () => seek(Number($(role + 'TimelineSeek').value));
  for (const event of ['timeupdate', 'seeking', 'seeked', 'loadedmetadata']) audio.addEventListener(event, updatePlayhead);
  audio.addEventListener('play', startTick); audio.addEventListener('pause', startTick);
  document.addEventListener('visibilitychange', startTick);
  const visibility = new IntersectionObserver(entries => {
    for (const entry of entries) { if (entry.target.id === 'musicalNow') nowVisible = entry.isIntersecting; else lanesVisible = entry.isIntersecting; }
    startTick();
  });
  visibility.observe($('musicalNow')); visibility.observe($('musicalRoleTimelines'));
  function drawLane(role, entries, color) {
    const canvas = $(role + 'Timeline'), box = canvas.parentElement.getBoundingClientRect();
    if (box.width < 1) return;
    const scale = Math.min(2, devicePixelRatio || 1), width = Math.ceil(box.width), height = role === 'vocal' && vocalNotes.length ? 53 : 35;
    canvas.parentElement.classList.toggle('with-pitch', height > 35);
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
    const c = canvas.getContext('2d'); c.scale(scale, scale); c.clearRect(0, 0, width, height);
    c.fillStyle = '#162633'; c.fillRect(0, height / 2 - 1, width, 2);
    // Bucket spans to screen pixels; dense, long tracks never add per-frame DOM or canvas work.
    const buckets = new Float32Array(width);
    if (duration) for (const entry of entries) {
      const start = clamp(Math.floor(entry.start / duration * width), 0, width - 1), end = clamp(Math.ceil(entry.end / duration * width), start + 1, width);
      const strength = .25 + .75 * clamp(Number(entry.strength ?? entry.confidence) || .5, 0, 1);
      for (let i = start; i < end; i++) buckets[i] = Math.max(buckets[i], strength);
    }
    c.fillStyle = color;
    for (let i = 0; i < width; i++) if (buckets[i]) { const h = 8 + buckets[i] * 17; c.globalAlpha = .42 + buckets[i] * .5; c.fillRect(i, (height - h) / 2, 1, h); }
    c.globalAlpha = 1;
    if (role === 'vocal' && vocalNotes.length && duration) {
      // Render measured note spans as a compact pitch ribbon, once per analysis/layout change.
      const pitched = vocalNotes.filter(note => Number.isFinite(note.midi));
      let low = 128, high = 0;
      for (const note of pitched) { low = Math.min(low, note.midi); high = Math.max(high, note.midi); }
      const spread = Math.max(12, high - low), center = (high + low) / 2;
      c.fillStyle = '#f3dcff';
      for (const note of pitched) {
        const x = clamp(note.start / duration * width, 0, width), end = clamp(note.end / duration * width, x, width);
        const y = 9 + (1 - clamp((note.midi - center) / spread + .5, 0, 1)) * (height - 20);
        c.globalAlpha = .45 + .55 * clamp(note.confidence || .5, 0, 1); c.fillRect(x, y, Math.max(1, end - x), 2);
      }
      c.globalAlpha = 1;
    }
  }
  function drawTimelines() { drawLane('vocal', vocalPhrases, '#ddb2fc'); drawLane('bass', bassNotes, '#aceaa1'); updatePlayhead(); }
  new ResizeObserver(drawTimelines).observe($('musicalRoleTimelines'));
  function renderRoles(s) {
    const music = s.music, show = s.show, analyzedVocals = music?.vocals, vocals = show?.choreography?.vocalDetail || analyzedVocals, bass = music?.bassAnalysis;
    const legacy = !music || (music.analysisVersion || 1) < 4;
    duration = Number(music?.duration || show?.audioDuration || s.project?.duration) || 0;
    roleMusic = legacy ? null : music;
    vocalPhrases = legacy ? [] : validSpans(vocals?.phrases);
    vocalNotes = legacy ? [] : validSpans(vocals?.notes);
    sourceSeparated = vocals?.sourceSeparated === true && vocals?.source === 'separated-vocals';
    bassNotes = legacy ? [] : validSpans(music?.bassNotes);
    $('musicalNow').hidden = legacy || !show;
    $('musicalRoleTimelines').hidden = legacy || (!vocalPhrases.length && !bassNotes.length);
    $('vocalNoteCount').textContent = legacy ? '—' : String(vocalNotes.length);
    $('vocalNoteSource').textContent = legacy || (music?.analysisVersion || 1) < 5 ? 'Upgrade analysis' : sourceSeparated ? 'Separated voice' : 'Detail unavailable';
    $('vocalDetailCard').hidden = legacy || (!sourceSeparated && !vocalNotes.length && !s.settings.vocalRegions?.length);
    $('roleAnalysisBadge').textContent = sourceSeparated ? 'VOICE SEPARATED' : 'ESTIMATED';
    $('roleAnalysisBadge').classList.toggle('separated', sourceSeparated);
    $('roleTimelineHelp').textContent = vocalNotes.length ? 'The voice ribbon shows estimated note height and length. Drag either lane to hear that moment; the preview plays the exported light cues.' : 'Drag a lane to hear that moment. Colored spans follow the analysis; the preview plays the exported light cues.';
    $('vocalMethodText').textContent = sourceSeparated ? 'A trained model separates the voice waveform from accompaniment. Its entrances, held notes, accents and releases shape the show, with confidence checks for bleed and uncertainty. Note timing and pitch remain estimates; these are not recognized lyrics or word timings.' : 'Voice activity is estimated from the full music mix. Re-analyze with the current version to separate voice from accompaniment before measuring fine phrasing. Saved voice guides adjust choreography without changing the original analysis.';
    $('vocalPhraseCount').textContent = legacy ? '—' : String(vocalPhrases.length);
    $('bassNoteCount').textContent = legacy ? '—' : String(bassNotes.length);
    $('vocalConfidence').textContent = legacy ? 'Re-analyze to add' : !analyzedVocals?.available && !vocalPhrases.length ? 'Vocal analysis unavailable' : !vocalPhrases.length ? 'No confident phrases' : vocalPhrases.every(p => p.manual) ? 'Your guides' : evidence(analyzedVocals?.confidence);
    $('bassConfidence').textContent = legacy ? 'Re-analyze to add' : !bassNotes.length ? 'No confident notes' : evidence(bass?.confidence);
    $('roleAnalysisStatus').textContent = legacy || (music?.analysisVersion || 1) < 5 ? 'This track uses an earlier voice analysis. Re-analyze to separate voice from accompaniment and recover finer phrasing; your edits are preserved.'
      : show?.stats?.silent ? 'Silent audio: no sung phrases or pitched bass notes to follow.'
      : !analyzedVocals?.available && !vocalPhrases.length ? 'Voice analysis was unavailable for this track. Bass, percussion and arrangement cues still shape the show. You can guide a voice passage below.'
      : !vocalPhrases.length && s.settings.vocalRegions?.some(x => x.kind === 'instrumental') ? 'Your instrumental guides leave no voice phrases in this arrangement. Restore analysis in a guided range to bring them back.'
      : !vocalPhrases.length && analyzedVocals?.presence === 'not_detected' ? 'No confident voice found. Instrumental detail, bass and structure still shape the show. Add a voice guide if a passage was missed.'
      : !vocalPhrases.length ? 'Voice evidence is uncertain. The show keeps following the other musical layers; you can guide a missed passage below.'
      : vocalPhrases.every(p => p.manual) ? 'Your voice guides shape this arrangement. Measured note detail is retained where available; other musical layers stay involved.'
      : sourceSeparated ? 'Voice detail is measured from the separated waveform. Notes, entrances and releases shape the phrasing alongside bass, percussion and the full arrangement.' : 'Voice separation was unavailable. Broader phrase estimates and the rest of the music still shape the show; re-analyze to try again.';
    const roles = show?.choreography?.lighting?.roles, vocalCues = Number(roles?.vocals?.acceptedEvents ?? show?.stats?.vocalCues), bassCues = Number(roles?.bass?.acceptedEvents ?? show?.stats?.bassNoteCues);
    $('roleArrangementText').textContent = Number.isFinite(vocalCues) && Number.isFinite(bassCues)
      ? `${vocalCues} vocal ${vocalCues === 1 ? 'cue' : 'cues'} · ${bassCues} bass-note ${bassCues === 1 ? 'cue' : 'cues'}. Percussion, melody and energy remain part of the arrangement. Motor gestures use phrase-level arrivals and recovery time.`
      : 'Percussion, melody and the wider arrangement stay involved. Motor gestures follow phrase-level arrivals with time to travel and recover.';
    for (const role of ['vocal', 'bass']) { $(role + 'TimelineSeek').max = duration || 1; $(role + 'TimelineSeek').value = clamp(audio.currentTime || 0, 0, duration); }
    drawTimelines(); startTick();
  }
  function refresh() {
    const s = app.state, show = s.show, plan = show?.choreography, music = s.music;
    const busy = s.busy || s.composing || s.loadingProject || s.auditionLoading;
    $('musicIntelligence').hidden = !show;
    $('recomposeShow').disabled = !show || s.needAnalysis || busy;
    $('reanalyzeMusic').disabled = !s.project || busy;
    $('nextVocalPhrase').disabled = busy || !vocalPhrases.length;
    $('nextBassNote').disabled = busy || !bassNotes.length;
    $('nextVocalNote').disabled = busy || !vocalNotes.length;
    for (const role of ['vocal', 'bass']) $(role + 'TimelineSeek').disabled = busy || !roleMusic;
    if (!show) { shown = null; roleMusic = null; $('musicalNow').hidden = true; startTick(); return; }
    if (shown === show) return;
    shown = show;
    const targets = plan?.targets || [], phrases = plan?.phrases || [];
    $('insightMeter').textContent = plan?.rhythm?.meter || music.meter || 4;
    $('insightPhrases').textContent = phrases.length || '—';
    const grouped = new Map();
    for (const target of targets) { const key = Math.round(target.time * 50); if (!grouped.has(key)) grouped.set(key, { time: target.time, targets: [] }); grouped.get(key).targets.push(target); }
    $('insightMoments').textContent = grouped.size;
    const refined = (music.analysisVersion || 1) >= 5;
    $('musicInsightText').textContent = show.stats.silent ? 'This track is silent. Automatic lights and movements stay off.' : !refined ? 'Re-analyze this track to add separated voice detail. Your custom lighting cues and voice guides are preserved.' : s.settings.dance === 'off' ? 'Voice phrasing, bass notes and neural beats shape the lights. Percussion adds detail; quiet passages have room to breathe.' : 'The music shapes both light accents and larger gestures. Movements prepare ahead of musical arrivals, with travel time, recovery and command limits accounted for.';
    $('reanalyzeMusic').classList.toggle('upgrade-available', !refined);
    $('reanalyzeMusic').textContent = refined ? 'Re-analyze music' : 'Analyze voice detail';
    renderRoles(s);
    $('nextVocalPhrase').disabled = busy || !vocalPhrases.length;
    $('nextBassNote').disabled = busy || !bassNotes.length;
    $('nextVocalNote').disabled = busy || !vocalNotes.length;
    for (const role of ['vocal', 'bass']) $(role + 'TimelineSeek').disabled = busy || !roleMusic;
    const list = $('movementPlanList'); list.replaceChildren(); $('movementPlanCount').textContent = grouped.size ? String(grouped.size) : '';
    $('movementPlanDetails').hidden = !grouped.size;
    for (const group of [...grouped.values()].sort((a, b) => a.time - b.time)) {
      const button = document.createElement('button'); button.className = 'movement-moment'; button.dataset.time = group.time;
      const stamp = document.createElement('b'); stamp.textContent = time(group.time);
      const copy = document.createElement('span'), names = new Set(group.targets.map(t => VehicleProfile.outputs.find(o => o.id === t.outputId)?.name || t.outputId));
      const title = document.createElement('strong'); title.textContent = [...names].join(' + ');
      const subtitle = document.createElement('small'); subtitle.textContent = group.targets.some(t => t.outputId === 'charge') ? 'Musical arrival · rainbow color' : group.targets.every(t => t.outputId.startsWith('mirror')) ? 'Musical arrival · unfold' : 'Musical arrival · dance entrance';
      copy.append(title, subtitle); button.append(stamp, copy); button.setAttribute('aria-label', `Preview ${title.textContent} at ${time(group.time)}`);
      button.onclick = () => { app.stopInspection(); audio.pause(); audio.currentTime = group.time; const primary = group.targets.find(t => t.outputId === 'trunk') || group.targets[0], o = VehicleProfile.outputs.find(o => o.id === primary.outputId); app.vehiclePreview.setView(o?.camera || 'front'); app.renderFrame(group.time); document.querySelector('.preview-card').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); };
      list.append(button);
    }
  }
  $('recomposeShow').onclick = async () => { if (window.StudioTools) return window.StudioTools.newVariation(); try { const seed = new Uint32Array(1); crypto.getRandomValues(seed); await app.commitChannelSettings({ seed: seed[0] }); app.toast('New musical variation ready. Your custom cues stay in place.'); } catch (e) { app.toast(e.message, true); } };
  $('reanalyzeMusic').onclick = async () => { if (app.state.busy || app.state.composing || app.state.loadingProject || app.state.auditionLoading) return; try { app.state.needAnalysis = true; await app.generate(); } catch (e) { app.toast(e.message, true); } };
  document.addEventListener('lightforge:changed', refresh);
  window.MusicInsights = { refresh, roleStateAt };
  refresh();
})();

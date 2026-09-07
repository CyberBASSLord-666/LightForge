/* Local creative tools: rhythm correction, comparison, loop rehearsal and project recovery. */
(() => {
  'use strict';
  const app = window.LightForgeApp;
  if (!app) return;
  const $ = id => document.getElementById(id), audio = $('audio');
  const clone = value => JSON.parse(JSON.stringify(value));
  const stamp = value => {
    const t = Math.max(0, Number(value) || 0);
    return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}.${String(Math.floor(t % 1 * 100)).padStart(2, '0')}`;
  };
  const unavailable = () => app.state.busy || app.state.composing || app.state.loadingProject || app.state.auditionLoading;
  const ready = () => !!app.state.show && !app.state.needAnalysis && !unavailable();
  let projectId = null, comparing = false, branch = 'B', snapshots = {}, switching = false;
  let loop = { a: null, b: null, enabled: false }, loopFrame = 0, seekingLoop = false;
  let auditionSwitching = false;
  let calibrationTimer = 0, vocalRegionPage = 0, vocalRegionKey = null;
  function readLocal(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
  }
  function writeLocal(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
  }
  async function commit(patch, success) {
    try {
      const result = await app.commitChannelSettings(patch);
      if (result === false) return false;
      if (success) app.toast(success);
      refresh();
      return true;
    } catch (error) {
      app.toast(error.message || 'This change could not be saved.', true);
      refresh();
      return false;
    }
  }
  const rhythm = () => app.state.show?.choreography?.rhythm || app.state.music || {};
  function setPlayhead(time) {
    if (!app.state.project || !Number.isFinite(time)) return;
    app.stopInspection();
    const duration = Number.isFinite(audio.duration) ? audio.duration : app.state.project.duration;
    audio.currentTime = Math.max(0, Math.min(duration || 0, time));
    app.renderFrame(audio.currentTime);
    app.drawWave();
  }
  function seekBeat(direction) {
    const beats = rhythm().beats || [], t = audio.currentTime || 0;
    let lo = 0, hi = beats.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (beats[mid] < t + direction * .025) lo = mid + 1; else hi = mid; }
    const target = direction > 0 ? beats[lo] : beats[lo - 1];
    const beatLength = 60 / (rhythm().bpm || app.state.music?.bpm || 120);
    setPlayhead(Number.isFinite(target) ? target : t + direction * beatLength);
  }
  function saveLoop() {
    if (!projectId) return;
    const stored = readLocal('lightforge-rehearsal-loops-v1', {});
    stored[projectId] = { ...loop, updated: Date.now() };
    const recent = Object.entries(stored).sort((a, b) => (b[1].updated || 0) - (a[1].updated || 0)).slice(0, 50);
    writeLocal('lightforge-rehearsal-loops-v1', Object.fromEntries(recent));
  }
  function loopValid() { return Number.isFinite(loop.a) && Number.isFinite(loop.b) && loop.b - loop.a >= .1; }
  function renderLoop() {
    $('setLoopStart').textContent = loop.a === null ? 'Set A' : `A ${stamp(loop.a)}`;
    $('setLoopEnd').textContent = loop.b === null ? 'Set B' : `B ${stamp(loop.b)}`;
    $('toggleLoop').disabled = !loopValid() || unavailable();
    $('toggleLoop').classList.toggle('selected', loop.enabled);
    $('toggleLoop').setAttribute('aria-pressed', String(loop.enabled));
    $('toggleLoop').textContent = loop.enabled ? 'Loop on' : 'Loop';
    $('clearLoop').disabled = loop.a === null && loop.b === null;
    $('loopStatus').textContent = loopValid() ? `${loop.enabled ? 'Repeating' : 'Loop ready'} · ${stamp(loop.a)}–${stamp(loop.b)} · ${(loop.b - loop.a).toFixed(2)} seconds` : loop.a !== null ? 'Move forward and set B to finish the loop.' : 'Loop a passage to fine-tune its choreography.';
    for (const id of ['setLoopStart', 'setLoopEnd', 'previousMusicalBeat', 'nextMusicalBeat']) $(id).disabled = !app.state.project || unavailable();
    renderVoiceRange();
  }
  function loopTick() {
    loopFrame = 0;
    if (!loop.enabled || !loopValid() || audio.paused || document.hidden) return;
    if (audio.currentTime >= loop.b && !seekingLoop) {
      seekingLoop = true;
      setPlayhead(loop.a);
    }
    loopFrame = requestAnimationFrame(loopTick);
  }
  function startLoopTick() { cancelAnimationFrame(loopFrame); loopFrame = 0; if (loop.enabled && !audio.paused) loopFrame = requestAnimationFrame(loopTick); }
  $('previousMusicalBeat').onclick = () => seekBeat(-1);
  $('nextMusicalBeat').onclick = () => seekBeat(1);
  $('setLoopStart').onclick = () => {
    loop.a = audio.currentTime || 0;
    if (loop.b !== null && loop.b - loop.a < .1) { loop.b = null; loop.enabled = false; }
    saveLoop(); renderLoop(); startLoopTick();
  };
  $('setLoopEnd').onclick = () => {
    const end = audio.currentTime || 0;
    if (loop.a === null) loop.a = 0;
    if (end - loop.a < .1) { app.toast('Set B at least a tenth of a second after A.', true); return; }
    loop.b = end; loop.enabled = true;
    setPlayhead(loop.a); saveLoop(); renderLoop(); startLoopTick();
  };
  $('toggleLoop').onclick = () => {
    if (!loopValid()) return;
    loop.enabled = !loop.enabled;
    if (loop.enabled && (audio.currentTime < loop.a || audio.currentTime >= loop.b)) setPlayhead(loop.a);
    saveLoop(); renderLoop(); startLoopTick();
  };
  $('clearLoop').onclick = () => { loop = { a: null, b: null, enabled: false }; saveLoop(); renderLoop(); startLoopTick(); };
  $('loopSection').onclick = () => {
    const section = (app.state.show?.sections || app.state.music?.sections || [])[app.state.editing];
    if (!section) return;
    loop = { a: section.start, b: section.end, enabled: true };
    setPlayhead(loop.a); saveLoop(); renderLoop(); startLoopTick();
    document.querySelector('.preview-card').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    app.toast('Section loop ready. Press play to rehearse.');
  };
  audio.addEventListener('play', startLoopTick);
  audio.addEventListener('pause', startLoopTick);
  audio.addEventListener('seeked', () => { seekingLoop = false; });
  audio.addEventListener('ended', () => {
    if (!loop.enabled || !loopValid() || unavailable()) return;
    setPlayhead(loop.a);
    audio.play().catch(error => app.toast(error.message, true));
  });
  document.addEventListener('visibilitychange', startLoopTick);

  $('meterOverride').onchange = () => commit({ meterOverride: $('meterOverride').value === 'auto' ? null : Number($('meterOverride').value) }, 'Bar grouping updated.');
  document.querySelectorAll('[data-tempo-scale]').forEach(button => {
    button.onclick = () => commit({ tempoScale: Number(button.dataset.tempoScale) }, 'Beat interpretation updated.');
  });
  $('anchorDownbeat').onclick = () => commit({ downbeatAnchor: audio.currentTime || 0 }, 'Bar start aligned to the nearest musical beat.');
  $('resetRhythm').onclick = () => commit({ tempoScale: 1, meterOverride: null, downbeatAnchor: null }, 'Detected rhythm restored.');
  $('analysisQuality').onchange = () => commit({ analysisQuality: $('analysisQuality').value }, 'Analysis mode saved. Create or re-analyze to apply it.');
  $('movementDensity').oninput = () => {
    const value = Number($('movementDensity').value);
    $('movementDensityValue').textContent = `${Math.round(value * 100)}%`;
    $('movementDensity').style.setProperty('--fill', `${value * 100}%`);
  };
  $('movementDensity').onchange = () => commit({ movementDensity: Number($('movementDensity').value) }, 'Movement frequency updated.');
  const focusDefaults = { vocalFocus: .85, bassFocus: .9 };
  const focusPresets = { balanced: { vocalFocus: .65, bassFocus: .65 }, voice: { vocalFocus: 1, bassFocus: .75 }, bass: { vocalFocus: .65, bassFocus: 1 } };
  document.querySelectorAll('[data-musical-focus]').forEach(button => {
    button.onclick = () => commit({ ...focusPresets[button.dataset.musicalFocus] }, `${button.querySelector('b').textContent} emphasis applied. All musical layers stay involved.`);
  });
  function renderFocusInput(id) {
    const value = Math.max(0, Math.min(1, Number($(id).value) || 0));
    $(id + 'Value').textContent = `${Math.round(value * 100)}%`;
    $(id).style.setProperty('--fill', `${value * 100}%`);
    $(id).setAttribute('aria-valuetext', `${Math.round(value * 100)} percent emphasis`);
  }
  for (const id of Object.keys(focusDefaults)) {
    $(id).oninput = () => renderFocusInput(id);
    $(id).onchange = () => commit({ [id]: Number($(id).value) }, id === 'vocalFocus' ? 'Singing emphasis updated. The rest of the arrangement stays involved.' : 'Bass-note emphasis updated. Percussion keeps its own rhythm.');
  }
  $('resetMusicalFocus').onclick = () => commit({ ...focusDefaults }, 'Recommended singing and bass emphasis restored.');
  $('analyzeMusicalFocus').onclick = () => $('reanalyzeMusic').click();


  function loopPassage(start, end) {
    const duration = Number(app.state.music?.duration || app.state.project?.duration) || 0;
    if (unavailable() || !app.state.project || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > duration + .001 || end - start < .1) return false;
    loop = { a: start, b: Math.min(duration, end), enabled: true };
    setPlayhead(start); saveLoop(); renderLoop(); startLoopTick();
    return true;
  }
  function voiceRange() {
    const start = Number($('voiceRangeStart').value), end = Number($('voiceRangeEnd').value), duration = Number(app.state.music?.duration || app.state.project?.duration) || 0;
    const valid = $('voiceRangeStart').value.trim() !== '' && $('voiceRangeEnd').value.trim() !== '' && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end <= duration + .001 && end - start >= .1;
    return { start, end: Math.min(duration, end), valid, duration };
  }
  function renderVoiceRange() {
    const range = voiceRange(), blocked = !ready(), regions = app.state.settings.vocalRegions || [];
    for (const id of ['voiceRangeStart', 'voiceRangeEnd', 'voiceStartAtPlayhead', 'voiceEndAtPlayhead']) $(id).disabled = blocked;
    for (const id of ['markVoiceRegion', 'muteVoiceRegion', 'loopVoiceRange']) $(id).disabled = blocked || !range.valid;
    $('clearVoiceRegion').disabled = blocked || !range.valid || !regions.some(x => x.start < range.end && x.end > range.start);
    $('useVoiceLoop').disabled = blocked || !loopValid();
    $('voiceRangeStart').max = range.duration || 1; $('voiceRangeEnd').max = range.duration || 1;
    $('voiceCorrectionStatus').textContent = !app.state.show ? 'Create a show to guide a voice passage.' : app.state.needAnalysis ? 'Re-analyze before adding a voice guide. Saved guides will be preserved.' : !range.valid ? `Choose a passage of at least 0.10 seconds within this ${stamp(range.duration)} track.` : `Selected ${stamp(range.start)}–${stamp(range.end)}. A voice guide shapes phrasing; it does not invent notes or lyrics.`;
  }
  function overlayVoiceRegion(entries, start, end, kind) {
    const out = [];
    for (const entry of entries) {
      if (entry.end <= start || entry.start >= end) out.push({ ...entry });
      else {
        if (entry.start < start) out.push({ ...entry, end: start });
        if (entry.end > end) out.push({ ...entry, start: end });
      }
    }
    if (kind) out.push({ start, end, kind });
    out.sort((a, b) => a.start - b.start);
    const merged = [];
    for (const entry of out) {
      const previous = merged[merged.length - 1];
      if (previous && previous.kind === entry.kind && Math.abs(previous.end - entry.start) < .000001) previous.end = entry.end;
      else merged.push(entry);
    }
    return merged;
  }
  async function applyVoiceRegion(kind) {
    const range = voiceRange();
    if (!ready() || !range.valid) return;
    const guides = overlayVoiceRegion(app.state.settings.vocalRegions || [], range.start, range.end, kind);
    if (guides.length > 1000) { app.toast('This project has reached 1,000 voice guides. Restore or combine a nearby passage first.', true); return; }
    await commit({ vocalRegions: guides }, kind === 'voice' ? 'Voice phrasing added to this passage. Measured notes are preserved.' : kind === 'instrumental' ? 'Voice accents removed from this passage. Other musical layers stay involved.' : 'This passage follows the original voice analysis again.');
  }
  for (const id of ['voiceRangeStart', 'voiceRangeEnd']) $(id).oninput = renderVoiceRange;
  $('voiceStartAtPlayhead').onclick = () => { $('voiceRangeStart').value = (audio.currentTime || 0).toFixed(2); renderVoiceRange(); };
  $('voiceEndAtPlayhead').onclick = () => { $('voiceRangeEnd').value = (audio.currentTime || 0).toFixed(2); renderVoiceRange(); };
  $('useVoiceLoop').onclick = () => { if (!loopValid()) return; $('voiceRangeStart').value = String(loop.a); $('voiceRangeEnd').value = String(loop.b); renderVoiceRange(); };
  $('loopVoiceRange').onclick = () => { const r = voiceRange(); if (r.valid && loopPassage(r.start, r.end)) app.toast('Passage ready to repeat. Press play to review.'); };
  $('markVoiceRegion').onclick = () => applyVoiceRegion('voice');
  $('muteVoiceRegion').onclick = () => applyVoiceRegion('instrumental');
  $('clearVoiceRegion').onclick = () => applyVoiceRegion(null);
  $('previousVoiceRegionPage').onclick = () => { vocalRegionPage = Math.max(0, vocalRegionPage - 1); vocalRegionKey = null; renderVoiceGuides(); };
  $('nextVoiceRegionPage').onclick = () => { vocalRegionPage++; vocalRegionKey = null; renderVoiceGuides(); };
  function renderVoiceGuides() {
    const entries = app.state.settings.vocalRegions || [], blocked = !ready(), pages = Math.max(1, Math.ceil(entries.length / 6));
    vocalRegionPage = Math.min(vocalRegionPage, pages - 1);
    $('voiceCorrectionCount').textContent = entries.length ? `${entries.length} ${entries.length === 1 ? 'guide' : 'guides'}` : 'Auto';
    $('voiceRegionPagination').hidden = pages < 2;
    $('previousVoiceRegionPage').disabled = blocked || vocalRegionPage === 0;
    $('nextVoiceRegionPage').disabled = blocked || vocalRegionPage >= pages - 1;
    $('voiceRegionPageStatus').textContent = `${vocalRegionPage + 1} / ${pages}`;
    const key = JSON.stringify([entries, vocalRegionPage]);
    if (key !== vocalRegionKey) {
      vocalRegionKey = key; const list = $('voiceRegionList'); list.replaceChildren();
      for (const entry of entries.slice(vocalRegionPage * 6, vocalRegionPage * 6 + 6)) {
        const button = document.createElement('button'); button.className = 'voice-region'; button.dataset.kind = entry.kind;
        const title = document.createElement('b'); title.textContent = entry.kind === 'voice' ? 'Voice guide' : 'Instrumental guide';
        const times = document.createElement('span'); times.textContent = `${stamp(entry.start)}–${stamp(entry.end)}`;
        button.append(title, times); button.setAttribute('aria-label', `Select ${title.textContent.toLowerCase()} from ${stamp(entry.start)} to ${stamp(entry.end)}`);
        button.onclick = () => { $('voiceRangeStart').value = String(entry.start); $('voiceRangeEnd').value = String(entry.end); setPlayhead(entry.start); renderVoiceRange(); };
        list.append(button);
      }
    }
    $('voiceRegionList').querySelectorAll('button').forEach(button => button.disabled = blocked);
  }

  $('lockSectionMotif').onchange = () => {
    const state = app.state, index = state.editing, section = state.show?.sections?.[index];
    if (index === null || !section) return;
    const overrides = clone(state.settings.sectionOverrides || {}), override = { ...(overrides[index] || {}) };
    if ($('lockSectionMotif').checked) {
      if (!Number.isFinite(section.seed)) { app.toast('Create this show again before keeping its motif.', true); $('lockSectionMotif').checked = false; return; }
      override.seed = section.seed;
    } else delete override.seed;
    if (Object.keys(override).length) overrides[index] = override; else delete overrides[index];
    commit({ sectionOverrides: overrides }, $('lockSectionMotif').checked ? 'This section’s motif will stay in new variations.' : 'This section can vary again.');
  };
  $('redo').onclick = async () => {
    try { if (app.redo) await app.redo(); } catch (error) { app.toast(error.message, true); }
    refresh();
  };
  async function newVariation() {
    if (!ready() || switching) return;
    const previous = app.captureSnapshot?.();
    if (!previous) { app.toast('Comparison is unavailable. Reopen this project and try again.', true); return; }
    const random = new Uint32Array(1); crypto.getRandomValues(random);
    switching = true;
    try {
      const result = await app.commitChannelSettings({ seed: random[0] });
      if (result === false) return;
      snapshots = { A: previous, B: app.captureSnapshot() };
      comparing = true; branch = 'B';
      app.toast('New variation ready. Compare A and B at the same moment.');
    } catch (error) { app.toast(error.message || 'A new variation could not be created.', true); }
    finally { switching = false; refresh(); }
  }
  async function switchVariation(next) {
    if (!comparing || next === branch || switching || !ready()) return;
    const destination = snapshots[next];
    if (!destination) return;
    switching = true; refresh();
    try {
      snapshots[branch] = app.captureSnapshot();
      const result = await app.restoreSnapshot(destination);
      if (result !== false) branch = next;
    } catch (error) { app.toast(error.message || 'This variation could not be restored.', true); }
    finally { switching = false; refresh(); }
  }
  $('variationA').onclick = () => switchVariation('A');
  $('variationB').onclick = () => switchVariation('B');
  $('finishComparison').onclick = () => { snapshots = {}; comparing = false; refresh(); app.toast('Current variation kept and saved with your project.'); };
  $('previewQuality').onchange = () => {
    try { app.vehiclePreview.setQuality?.($('previewQuality').value); renderQuality(); }
    catch (error) { app.toast(error.message || 'Preview quality could not be changed.', true); }
  };
  function renderQuality() {
    const stats = app.vehiclePreview.getPerformance?.();
    if (!stats) return;
    const choice = stats.quality || stats.preference || stats.requestedQuality || readLocal('lightforge-preview-quality', null);
    if (['auto', 'high', 'balanced', 'battery'].includes(choice)) $('previewQuality').value = choice;
    $('previewQualityStatus').textContent = $('previewQuality').value === 'auto' && stats.effectiveQuality ? `Using ${stats.effectiveQuality} quality` : '';
  }
  $('carCanvas').addEventListener('previewperformance', renderQuality);

  document.querySelectorAll('[data-audition]').forEach(button => {
    button.onclick = async () => {
      if (auditionSwitching || unavailable() || !app.state.project || typeof app.setAudition !== 'function') return;
      auditionSwitching = true; renderAudition();
      try { await app.setAudition(button.dataset.audition); }
      catch (error) { app.toast(error.message || 'This audio layer could not be opened. Re-analyze the track to recreate it.', true); }
      finally { auditionSwitching = false; renderAudition(); }
    };
  });
  function renderAudition() {
    const state = app.state, mode = state.audition || 'mix', available = state.auditionAvailable === true;
    $('auditionControls').hidden = !state.project;
    for (const button of document.querySelectorAll('[data-audition]')) {
      const selected = button.dataset.audition === mode;
      button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
      button.disabled = !state.project || unavailable() || auditionSwitching || typeof app.setAudition !== 'function' || (button.dataset.audition !== 'mix' && !available);
    }
    $('auditionModeLabel').textContent = auditionSwitching ? 'Opening layer…' : mode === 'vocals' ? 'Voice' : mode === 'accompaniment' ? 'Backing' : 'Full song';
    $('auditionStatus').textContent = auditionSwitching ? 'Keeping your place in the music…' : available ? mode === 'mix' ? 'Switch layers to hear the voice and instrumentation that guide the show.' : 'Separated audio is a listening aid and may contain bleed. Export uses your full song.' : state.busy ? 'Separated listening previews will be ready when analysis finishes.' : 'Re-analyze this track to create voice and backing listening previews.';
  }

  const list = $('showList'), cardProjects = new WeakMap();
  const projectObserver = new MutationObserver(filterProjects);
  function filterProjects() {
    const cards = [...list.children], projects = app.state.projects || [];
    cards.forEach((card, index) => { if (!cardProjects.has(card)) cardProjects.set(card, projects[index] || {}); });
    const query = $('projectSearch').value.trim().toLocaleLowerCase(), sort = $('projectSort').value;
    const sorted = [...cards].sort((a, b) => {
      const pa = cardProjects.get(a), pb = cardProjects.get(b);
      if (sort === 'name') return String(pa.name || '').localeCompare(String(pb.name || ''), undefined, { sensitivity: 'base' });
      if (sort === 'duration') return (pa.duration || 0) - (pb.duration || 0);
      return (pb.updatedAt || pb.createdAt || 0) - (pa.updatedAt || pa.createdAt || 0);
    });
    if (sorted.some((card, index) => card !== cards[index])) {
      projectObserver.disconnect(); list.replaceChildren(...sorted); projectObserver.observe(list, { childList: true });
    }
    let visible = 0;
    for (const card of cards) {
      const p = cardProjects.get(card), matches = `${p.name || ''} ${p.style || ''}`.toLocaleLowerCase().includes(query);
      card.hidden = !matches; if (matches) visible++;
    }
    document.querySelector('.collection-filters').hidden = !projects.length;
    $('projectSearchStatus').textContent = !projects.length ? '' : query ? `${visible} of ${cards.length} shows${visible ? '' : ' · try another name or style'}` : `${cards.length} saved ${cards.length === 1 ? 'show' : 'shows'}`;
  }
  $('projectSearch').oninput = filterProjects;
  $('projectSort').onchange = () => { writeLocal('lightforge-project-sort', $('projectSort').value); filterProjects(); };
  const savedSort = readLocal('lightforge-project-sort', 'recent');
  if (['recent', 'name', 'duration'].includes(savedSort)) $('projectSort').value = savedSort;
  projectObserver.observe(list, { childList: true });

  const calibration = readLocal('lightforge-vehicle-observations-v1', {});
  $('calibrationFirmware').value = calibration.firmware || '';
  $('calibrationDate').value = calibration.date || '';
  $('calibrationNotes').value = calibration.notes || '';
  document.querySelectorAll('[data-calibration]').forEach(input => { input.checked = calibration.checks?.[input.dataset.calibration] === true; });
  function saveCalibration() {
    clearTimeout(calibrationTimer);
    const checks = Object.fromEntries([...document.querySelectorAll('[data-calibration]')].map(input => [input.dataset.calibration, input.checked]));
    const saved = writeLocal('lightforge-vehicle-observations-v1', { firmware: $('calibrationFirmware').value, date: $('calibrationDate').value, notes: $('calibrationNotes').value, checks, updatedAt: Date.now() });
    $('calibrationStatus').textContent = saved ? 'Your observations are saved on this device.' : 'These observations could not be saved. Free some device storage and try again.';
  }
  for (const id of ['calibrationFirmware', 'calibrationDate', 'calibrationNotes']) $(id).addEventListener('input', () => { clearTimeout(calibrationTimer); calibrationTimer = setTimeout(saveCalibration, 350); });
  document.querySelectorAll('[data-calibration]').forEach(input => input.onchange = saveCalibration);
  document.addEventListener('visibilitychange', () => { if (document.hidden && calibrationTimer) saveCalibration(); });
  $('openCalibrationEditor').onclick = () => {
    app.nav('studio');
    if (!app.state.project) { app.toast('Import music or open a project to use the preview inspector.'); return; }
    $('channelStudio').open = true;
    window.ChannelStudio?.select('left-outer');
    $('channelStudio').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  };
  $('resumeExport').onclick = async () => { try { await app.resumePendingExport?.(); } catch (error) { app.toast(error.message, true); } refresh(); };
  $('discardExport').onclick = async () => { try { await app.discardPendingExport?.(); } catch (error) { app.toast(error.message, true); } refresh(); };
  function refresh() {
    const state = app.state;
    if (projectId !== state.project?.id) {
      projectId = state.project?.id || null; snapshots = {}; comparing = false; branch = 'B'; vocalRegionPage = 0; vocalRegionKey = null; $('voiceRangeStart').value = '0'; $('voiceRangeEnd').value = String(Math.min(1, state.project?.duration || 1));
      const saved = readLocal('lightforge-rehearsal-loops-v1', {})[projectId], duration = state.project?.duration || 0;
      loop = saved && Number.isFinite(saved.a) && Number.isFinite(saved.b) && saved.a >= 0 && saved.b <= duration && saved.b - saved.a >= .1 ? { a: saved.a, b: saved.b, enabled: saved.enabled === true } : { a: null, b: null, enabled: false };
      startLoopTick();
    }
    const settings = state.settings, corrected = rhythm(), correction = corrected.correction || {}, blocked = !ready();
    if (!state.composing) $('meterOverride').value = settings.meterOverride == null ? 'auto' : String(settings.meterOverride);
    $('meterOverride').disabled = blocked;
    for (const button of document.querySelectorAll('[data-tempo-scale]')) {
      const selected = Number(button.dataset.tempoScale) === (settings.tempoScale || 1);
      button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected)); button.disabled = blocked;
    }
    $('anchorDownbeat').disabled = blocked; $('resetRhythm').disabled = blocked;
    const hasCorrection = settings.meterOverride != null || settings.downbeatAnchor != null || (settings.tempoScale || 1) !== 1;
    $('rhythmStatusBadge').textContent = hasCorrection ? 'Adjusted' : 'Auto';
    const confidence = Number(state.music?.meterConfidence);
    $('rhythmConfidence').textContent = `${Number(corrected.bpm || state.music?.bpm || 0).toFixed(1)} BPM · ${corrected.meter || state.music?.meter || 4} beats per bar. ${Number.isFinite(confidence) ? `Meter estimate: ${confidence >= .75 ? 'strong' : confidence >= .45 ? 'moderate' : 'uncertain'}. ` : ''}Listen for the bar’s first beat; automatic grouping can need correction.`;
    $('downbeatAnchorStatus').textContent = settings.downbeatAnchor != null ? `Your bar anchor: ${stamp(settings.downbeatAnchor)}${Number.isFinite(correction.snappedAnchor) ? ` · snapped to beat ${stamp(correction.snappedAnchor)}` : ''}.` : 'Pause on the first beat of any bar to align the arrangement.';
    $('analysisQuality').value = settings.analysisQuality || 'precision'; $('analysisQuality').disabled = !state.project || unavailable();
    $('analysisQualityNote').textContent = state.needAnalysis ? 'Music analysis has changed. Create or re-analyze to apply it; your edits are preserved.' : 'Studio uses Deux separation, GAME Large singing transcription and the full rhythm transformer. Balanced uses MDX separation and compact rhythm analysis. Both run offline; Studio needs more memory and time.';
    if (!state.composing) $('movementDensity').value = settings.movementDensity ?? .7;
    $('movementDensity').disabled = !state.project || unavailable() || settings.dance === 'off';
    $('movementDensityValue').textContent = `${Math.round(Number($('movementDensity').value) * 100)}%`;
    $('movementDensity').style.setProperty('--fill', `${Number($('movementDensity').value) * 100}%`);
    const legacyRoles = !!state.music && (state.music.analysisVersion || 1) < 5;
    for (const [id, fallback] of Object.entries(focusDefaults)) {
      if (!state.composing) $(id).value = settings[id] ?? fallback;
      $(id).disabled = !state.project || unavailable() || legacyRoles;
      renderFocusInput(id);
    }
    $('resetMusicalFocus').disabled = !state.project || unavailable() || legacyRoles;
    $('analyzeMusicalFocus').hidden = !legacyRoles;
    $('analyzeMusicalFocus').disabled = !state.project || unavailable();
    $('musicalFocusStatus').textContent = legacyRoles
      ? 'Upgrade this track’s analysis to separate the voice and inspect finer phrasing. Your custom cues and voice guides are preserved.'
      : state.needAnalysis ? 'Create or re-analyze to apply the current music settings. Your emphasis choices are saved.'
      : !state.show ? 'Your focus choices will shape the show when you create it.'
      : 'Emphasis changes phrasing and accents. Percussion, melody and energy stay involved.';

    for (const button of document.querySelectorAll('[data-musical-focus]')) {
      const preset = focusPresets[button.dataset.musicalFocus], selected = Object.entries(preset).every(([key, value]) => Math.abs(Number(settings[key] ?? focusDefaults[key]) - value) < .001);
      button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected)); button.disabled = !state.project || unavailable() || legacyRoles;
    }
    renderVoiceGuides();

    const section = state.show?.sections?.[state.editing], override = settings.sectionOverrides?.[state.editing];
    if (!state.composing) $('lockSectionMotif').checked = Number.isFinite(override?.seed);
    $('lockSectionMotif').disabled = blocked || !section;
    $('loopSection').disabled = !section || unavailable();
    document.querySelectorAll('.section-item').forEach(button => {
      const locked = Number.isFinite(settings.sectionOverrides?.[button.dataset.section]?.seed);
      button.classList.toggle('motif-locked', locked);
      button.title = locked ? 'Motif kept in new variations' : '';
    });
    $('redo').disabled = unavailable() || !(state.future?.length || state.redoHistory?.length);
    $('variationCompare').hidden = !comparing;
    $('variationStatus').textContent = `${audio.paused ? 'Viewing' : 'Playing'} ${branch}`;
    for (const key of ['A', 'B']) {
      const button = $('variation' + key); button.classList.toggle('selected', branch === key); button.setAttribute('aria-pressed', String(branch === key)); button.disabled = blocked || switching;
    }
    $('finishComparison').disabled = unavailable() || switching;
    $('exportRecovery').hidden = !state.pendingExport;
    $('exportRecoveryText').textContent = state.pendingExport?.name ? `${state.pendingExport.name} is prepared on this device. Choose where to save it.` : 'Your show files are prepared. Choose where to save the ZIP.';
    $('resumeExport').disabled = unavailable(); $('discardExport').disabled = unavailable();
    renderLoop(); filterProjects(); renderQuality(); renderVoiceRange(); renderAudition();
  }
  $('sectionList').addEventListener('click', () => queueMicrotask(refresh));
  audio.addEventListener('play', () => { if (comparing) refresh(); });
  audio.addEventListener('pause', () => { if (comparing) refresh(); });
  document.addEventListener('lightforge:changed', refresh);
  window.StudioTools = { refresh, newVariation, switchVariation, seekBeat, loopPassage, overlayVoiceRegion, getLoop: () => ({ ...loop }) };
  refresh();
})();

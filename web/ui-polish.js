/* LightForge interaction layer. Presentation only: no project, audio or export writes. */
(function () {
  'use strict';
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const audio = document.getElementById('audio');
  const seek = document.getElementById('seek');
  const activeTimers = new WeakMap();
  const inkSelector = '.button,.chip,.play-button,.nav-item,.scene-switch button,.preview-views button';

  function flash(element, name, duration) {
    if (!element || reducedMotion.matches) return;
    clearTimeout(activeTimers.get(element));
    element.classList.remove(name);
    requestAnimationFrame(function () {
      element.classList.add(name);
      activeTimers.set(element, setTimeout(function () { element.classList.remove(name); }, duration));
    });
  }

  document.addEventListener('pointerdown', function (event) {
    if (reducedMotion.matches || event.button !== 0) return;
    const target = event.target.closest(inkSelector);
    if (!target || target.disabled) return;
    const rect = target.getBoundingClientRect();
    const ink = document.createElement('span');
    ink.className = 'ui-ink';
    ink.setAttribute('aria-hidden', 'true');
    ink.style.setProperty('--ink-size', Math.ceil(Math.hypot(rect.width, rect.height) * 2) + 'px');
    ink.style.setProperty('--ink-x', (event.clientX - rect.left) + 'px');
    ink.style.setProperty('--ink-y', (event.clientY - rect.top) + 'px');
    target.appendChild(ink);
    ink.addEventListener('animationend', function () { ink.remove(); }, { once: true });
    setTimeout(function () { ink.remove(); }, 650);
  }, { passive: true });

  document.addEventListener('click', function (event) {
    const style = event.target.closest('[data-style]');
    if (style && !style.disabled) flash(style, 'celebrate', 800);
  });

  // Arrow keys select real existing controls, just as a tap does.
  document.addEventListener('keydown', function (event) {
    const button = event.target.closest('[role="radiogroup"] button,.preview-views button,.scene-switch button');
    if (!button || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const group = button.closest('[role="radiogroup"],.preview-views,.scene-switch');
    const buttons = Array.from(group.querySelectorAll('button')).filter(function (el) { return !el.disabled && !el.hidden; });
    if (!buttons.length) return;
    const index = buttons.indexOf(button);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
      (index + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length;
    event.preventDefault();
    buttons[next].focus();
    buttons[next].click();
  });

  document.addEventListener('input', function (event) {
    if (event.target.type !== 'range' || event.target.id === 'seek' || reducedMotion.matches) return;
    const label = document.querySelector('label[for="' + event.target.id + '"]');
    const output = label && label.querySelector('output');
    if (output && output.animate) {
      output.getAnimations().forEach(function (animation) { animation.cancel(); });
      output.animate([{ opacity: .68 }, { opacity: 1 }], { duration: 180 });
    }
  });

  function playbackState() {
    document.body.classList.toggle('is-playing', !!audio && !audio.paused && !audio.ended);
  }
  function spokenTime(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(seconds / 60);
    return minutes + (minutes === 1 ? ' minute ' : ' minutes ') + seconds % 60 + ' seconds';
  }
  function seekDescription() {
    if (!seek || !audio) return;
    seek.setAttribute('aria-valuetext', spokenTime(audio.currentTime) + ' of ' + spokenTime(audio.duration));
  }
  if (audio) {
    ['play', 'pause', 'ended', 'emptied'].forEach(function (name) { audio.addEventListener(name, playbackState); });
    ['timeupdate', 'loadedmetadata', 'seeked', 'emptied'].forEach(function (name) { audio.addEventListener(name, seekDescription); });
    playbackState();
    seekDescription();
  }

  const progressText = document.getElementById('progressPercent');
  const progressTrack = document.querySelector('.progress-track');
  if (progressText && progressTrack) {
    new MutationObserver(function () {
      progressTrack.setAttribute('aria-valuenow', String(Math.max(0, Math.min(100, parseInt(progressText.textContent, 10) || 0))));
    }).observe(progressText, { childList: true, characterData: true, subtree: true });
  }

  // Keep focus within visible overlays and return it to the triggering control.
  let priorFocus = null;
  let visibleOverlay = null;
  function focusables(container) {
    return Array.from(container.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],[tabindex="0"]'))
      .filter(function (element) { return !element.hidden && element.getClientRects().length; });
  }
  function syncOverlay() {
    const next = Array.from(document.querySelectorAll('.modal-backdrop')).find(function (element) { return !element.hidden; }) || null;
    if (next === visibleOverlay) return;
    if (next) {
      if (!visibleOverlay) priorFocus = document.activeElement;
      visibleOverlay = next;
      const first = focusables(next)[0];
      if (first) requestAnimationFrame(function () { if (visibleOverlay === next && !next.hidden) first.focus({ preventScroll: true }); });
    } else {
      visibleOverlay = null;
      if (priorFocus && priorFocus.isConnected && !priorFocus.disabled && priorFocus.getClientRects().length) priorFocus.focus({ preventScroll: true });
      priorFocus = null;
    }
  }
  const overlayObserver = new MutationObserver(syncOverlay);
  document.querySelectorAll('.modal-backdrop').forEach(function (overlay) { overlayObserver.observe(overlay, { attributes: true, attributeFilter: ['hidden'] }); });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab' || !visibleOverlay) return;
    const elements = focusables(visibleOverlay);
    if (!elements.length) { event.preventDefault(); return; }
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && (document.activeElement === first || !visibleOverlay.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !visibleOverlay.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  syncOverlay();
})();

/* ==========================================================================
   Presency — shared kiosk scripts
   Loaded from basic.html on every kiosk page (after jQuery/Bootstrap).
   1. Idle screensaver: dims the page after inactivity, wakes on touch.
   ========================================================================== */

(function () {
  'use strict';

  /* Idle timeout in milliseconds (10 minutes) — must stay >5 min so the
     screen doesn't appear blank during a short lull; wake on any touch */
  var IDLE_TIMEOUT_MS = 10 * 60 * 1000;
  var WAKE_EVENTS = 'pointerdown touchstart keydown mousemove';

  var idleTimer = null;

  function dim() {
    document.body.classList.add('kiosk-dimmed');
  }

  function wake() {
    if (document.body.classList.contains('kiosk-dimmed')) {
      document.body.classList.remove('kiosk-dimmed');
    }
    resetIdleTimer();
  }

  function resetIdleTimer() {
    if (idleTimer) {
      clearTimeout(idleTimer);
    }
    idleTimer = setTimeout(dim, IDLE_TIMEOUT_MS);
  }

  /* A browser tab that is hidden does not fire pointer events; re-arm the
     timer when the kiosk tab becomes visible again. */
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      wake();
    }
  });

  document.addEventListener('pointerdown', wake);
  document.addEventListener('touchstart', wake);
  document.addEventListener('keydown', wake);

  resetIdleTimer();
})();

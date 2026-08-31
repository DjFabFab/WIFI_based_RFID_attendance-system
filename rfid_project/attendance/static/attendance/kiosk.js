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

  window.kioskInhibitDim = false;

  function dim() {
    if (window.kioskInhibitDim || document.documentElement.dataset.alarmActive === "1") return;
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
    if (window.kioskInhibitDim || document.documentElement.dataset.alarmActive === "1") return;
    idleTimer = setTimeout(dim, IDLE_TIMEOUT_MS);
  }

  window.kioskWake = wake;
  window.wake = wake;
  window.kioskSetAlarmActive = function(a){ window.kioskInhibitDim=!!a; document.documentElement.dataset.alarmActive = a?"1":"0"; if(a) wake(); };

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

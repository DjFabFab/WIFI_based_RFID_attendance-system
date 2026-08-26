(function () {
  'use strict';

  var activeInput = null;
  var shiftOn = false;
  var capsOn = false;

  var LAYOUTS = {
    normal: [
      ['1','2','3','4','5','6','7','8','9','0','ß','⌫'],
      ['q','w','e','r','t','z','u','i','o','p','ü','+'],
      ['a','s','d','f','g','h','j','k','l','ö','ä','#'],
      ['⇧','y','x','c','v','b','n','m',',','.','-','⏎'],
      ['_','@','.',' ']
    ],
    shifted: [
      ['!','"','§','$','%','&','/','(',')','=','?','⌫'],
      ['Q','W','E','R','T','Z','U','I','O','P','Ü','*'],
      ['A','S','D','F','G','H','J','K','L','Ö','Ä',"'"],
      ['⇧','Y','X','C','V','B','N','M',';',':','_','⏎'],
      ['_','@','.',' ']
    ]
  };

  function getLayout() {
    return (shiftOn || capsOn) ? LAYOUTS.shifted : LAYOUTS.normal;
  }

  function createKey(label) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'vk-key';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('tabindex', '-1');

    if (label === '⌫') {
      btn.classList.add('vk-key-wide');
      btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H9"/><path d="M9 12l5-5"/><path d="M9 12l5 5"/><path d="M4 6h6l6 6-6 6H4z"/></svg>';
      btn.dataset.action = 'backspace';
    } else if (label === '⇧') {
      btn.classList.add('vk-key-wide');
      btn.textContent = '⇧';
      btn.dataset.action = 'shift';
      if (shiftOn || capsOn) btn.classList.add('vk-key-active');
    } else if (label === '⏎') {
      btn.classList.add('vk-key-wide');
      btn.textContent = '↵';
      btn.dataset.action = 'enter';
    } else if (label === ' ') {
      btn.classList.add('vk-key-space');
      btn.setAttribute('aria-label', 'Leertaste');
      btn.dataset.key = ' ';
    } else {
      btn.textContent = label;
      btn.dataset.key = label;
      if (label === '@' || label === '_' || label === '.') {
        btn.classList.add('vk-key-wide');
      }
    }
    return btn;
  }

  function buildKeyboard() {
    var container = document.getElementById('vk-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'vk-container';
      container.className = 'vk-container';
      container.setAttribute('aria-hidden', 'true');
      document.body.appendChild(container);
    }
    container.innerHTML = '';
    var layout = getLayout();
    layout.forEach(function (row, idx) {
      var rowEl = document.createElement('div');
      rowEl.className = 'vk-row';
      row.forEach(function (key) {
        var isSpaceRow = (idx === layout.length - 1);
        if (isSpaceRow && key === ' ') {
          var spaceBtn = createKey(' ');
          rowEl.appendChild(spaceBtn);
        } else if (isSpaceRow) {
          // Bottom row: wide keys + space + hide button
          var btn = createKey(key);
          if (key === '@' || key === '_' || key === '.') {
            // already handled
          }
          rowEl.appendChild(btn);
        } else {
          rowEl.appendChild(createKey(key));
        }
      });
      // Add hide/close button to bottom row
      if (idx === layout.length - 1) {
        var hideBtn = document.createElement('button');
        hideBtn.type = 'button';
        hideBtn.className = 'vk-key vk-key-extra-wide';
        hideBtn.textContent = '▼ Schließen';
        hideBtn.dataset.action = 'hide';
        hideBtn.setAttribute('aria-label', 'Tastatur schließen');
        rowEl.appendChild(hideBtn);
      }
      container.appendChild(rowEl);
    });
  }

  function showKeyboard(input) {
    activeInput = input;
    var container = document.getElementById('vk-container');
    if (!container) buildKeyboard();
    buildKeyboard();
    container = document.getElementById('vk-container');
    container.classList.add('vk-visible');
    container.setAttribute('aria-hidden', 'false');
    // Ensure input stays visible above keyboard
    setTimeout(function () {
      if (activeInput) {
        activeInput.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }, 100);
  }

  function hideKeyboard() {
    var container = document.getElementById('vk-container');
    if (container) {
      container.classList.remove('vk-visible');
      container.setAttribute('aria-hidden', 'true');
    }
    activeInput = null;
    shiftOn = false;
  }

  function isTextInput(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    if (tag === 'textarea') return true;
    if (tag === 'select') return false;
    if (tag !== 'input') return false;
    var type = (el.getAttribute('type') || 'text').toLowerCase();
    return ['text','search','email','number','tel','password','url'].indexOf(type) !== -1;
  }

  function insertAtCursor(input, text) {
    var start = input.selectionStart;
    var end = input.selectionEnd;
    var val = input.value;
    var newVal = val.slice(0, start) + text + val.slice(end);
    input.value = newVal;
    var newPos = start + text.length;
    input.setSelectionRange(newPos, newPos);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.focus();
  }

  function handleKeyClick(e) {
    var target = e.target.closest('.vk-key');
    if (!target || !activeInput) return;
    e.preventDefault();

    var action = target.dataset.action;
    var key = target.dataset.key;

    if (action === 'backspace') {
      var start = activeInput.selectionStart;
      var end = activeInput.selectionEnd;
      if (start === end && start > 0) {
        activeInput.value = activeInput.value.slice(0, start - 1) + activeInput.value.slice(end);
        activeInput.setSelectionRange(start - 1, start - 1);
      } else if (start !== end) {
        activeInput.value = activeInput.value.slice(0, start) + activeInput.value.slice(end);
        activeInput.setSelectionRange(start, start);
      }
      activeInput.dispatchEvent(new Event('input', { bubbles: true }));
      activeInput.focus();
    } else if (action === 'shift') {
      // Single shift vs caps: tap once = shift for next char, double-tap = caps lock
      if (shiftOn && !capsOn) {
        capsOn = true;
        shiftOn = false;
      } else if (capsOn) {
        capsOn = false;
        shiftOn = false;
      } else {
        shiftOn = true;
      }
      buildKeyboard();
    } else if (action === 'enter') {
      if (activeInput.form) {
        // Try to submit form or move to next input
        var form = activeInput.form;
        var submit = form.querySelector('button[type=submit], input[type=submit]');
        if (submit) {
          submit.click();
        } else {
          hideKeyboard();
          activeInput.blur();
        }
      } else {
        hideKeyboard();
        activeInput.blur();
      }
    } else if (action === 'hide') {
      hideKeyboard();
      if (activeInput) activeInput.blur();
    } else if (key !== undefined) {
      insertAtCursor(activeInput, key);
      if (shiftOn) {
        shiftOn = false;
        buildKeyboard();
      }
    }
  }

  function init() {
    buildKeyboard();
    var container = document.getElementById('vk-container');
    container.addEventListener('click', handleKeyClick);
    container.addEventListener('touchstart', function (e) {
      // Prevent input blur on touch
      e.preventDefault();
    }, { passive: false });

    // Don't show keyboard on initial page load — only on user gesture.
    // Some browsers may focus the first input on load; ignore focusin
    // for the first second unless it was triggered by a recent user interaction.
    var pageLoadTime = Date.now();
    var lastUserInteraction = 0;
    document.addEventListener('pointerdown', function () { lastUserInteraction = Date.now(); }, true);
    document.addEventListener('touchstart', function () { lastUserInteraction = Date.now(); }, true);

    // If something is autofocused on load, blur it so the keyboard doesn't pop up.
    setTimeout(function () {
      var ae = document.activeElement;
      if (isTextInput(ae) && Date.now() - pageLoadTime < 1500 && Date.now() - lastUserInteraction > 1000) {
        ae.blur();
      }
    }, 100);

    // Show on focus for text inputs, but only if triggered by user interaction
    // or more than 1s after page load (prevents autofocus on load).
    document.addEventListener('focusin', function (e) {
      if (isTextInput(e.target)) {
        var sinceLoad = Date.now() - pageLoadTime;
        var sinceInteraction = Date.now() - lastUserInteraction;
        // Allow if user recently interacted, or if it's been >1s since load (user tabbed/clicked)
        if (sinceInteraction < 2000 || sinceLoad > 1000) {
          showKeyboard(e.target);
        }
      }
    });

    // Also handle touchstart for inputs that may not fire focusin immediately on touch
    document.addEventListener('touchstart', function (e) {
      var el = e.target;
      if (isTextInput(el)) {
        // Delay to let focus happen
        setTimeout(function () {
          if (document.activeElement === el) showKeyboard(el);
        }, 50);
      }
    }, { passive: true });

    // Hide when tapping outside keyboard and outside inputs
    document.addEventListener('pointerdown', function (e) {
      var container = document.getElementById('vk-container');
      if (!container || !container.classList.contains('vk-visible')) return;
      var isInput = isTextInput(e.target);
      var isKeyboard = e.target.closest('#vk-container');
      if (!isInput && !isKeyboard) {
        hideKeyboard();
      }
    });

    // Hide on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideKeyboard();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

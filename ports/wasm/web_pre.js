// Start the game on the clean image bundled with the page (pw64.data).
Module['arguments'] = Module['arguments'] || ['--clean', '/pilotwings64.clean.z64'];

// ---- WebAudio output (called from web_audio.cpp on the main thread)
Module.pw64AudioOpen = function () {
  if (!Module.pw64Audio) {
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC();
    var q = { ctx: ctx, chunks: [], head: 0, frames: 0 };
    var node = ctx.createScriptProcessor(2048, 0, 2);
    node.onaudioprocess = function (e) {
      var L = e.outputBuffer.getChannelData(0), R = e.outputBuffer.getChannelData(1);
      var i = 0;
      while (i < L.length && q.chunks.length) {
        var c = q.chunks[0];
        var n = Math.min(L.length - i, (c.length >> 1) - q.head);
        for (var k = 0; k < n; k++) {
          L[i + k] = c[(q.head + k) * 2] / 32768;
          R[i + k] = c[(q.head + k) * 2 + 1] / 32768;
        }
        i += n; q.head += n; q.frames -= n;
        if (q.head * 2 >= c.length) { q.chunks.shift(); q.head = 0; }
      }
      for (; i < L.length; i++) { L[i] = 0; R[i] = 0; }
    };
    node.connect(ctx.destination);
    var resume = function () { if (ctx.state !== 'running') ctx.resume(); };
    ['pointerdown', 'keydown', 'touchstart', 'gamepadconnected'].forEach(function (ev) {
      window.addEventListener(ev, resume, { passive: true });
    });
    Module.pw64Audio = q;
  }
  return Module.pw64Audio.ctx.sampleRate;
};
Module.pw64AudioQueue = function (ptr, bytes) {
  var q = Module.pw64Audio;
  if (!q) return;
  var n = bytes >> 1;
  var c = new Int16Array(n);
  c.set(HEAP16.subarray(ptr >> 1, (ptr >> 1) + n));
  q.chunks.push(c);
  q.frames += n >> 1;
  // A suspended context (no user gesture yet) must not grow the queue forever.
  while (q.frames > q.ctx.sampleRate && q.chunks.length > 1) {
    q.frames -= (q.chunks.shift().length >> 1) - q.head; q.head = 0;
  }
};
Module.pw64AudioFrames = function () { return Module.pw64Audio ? Module.pw64Audio.frames : 0; };

// ---- Presentation (frames rendered by the software RDP on the gfx worker)
Module.pw64Present = function (ptr, w, h) {
  var cv = Module.pw64Canvas;
  if (!cv) {
    cv = document.getElementById('pw64screen');
    if (!cv) {
      cv = document.createElement('canvas');
      cv.id = 'pw64screen';
      cv.style.cssText = 'display:block;margin:0 auto;width:min(100vw,133.33vh);height:auto;image-rendering:auto;background:#000';
      document.body.insertBefore(cv, document.body.firstChild);
      var sdl = document.getElementById('canvas');
      if (sdl && sdl !== cv) sdl.style.display = 'none';
    }
    Module.pw64Canvas = cv;
    Module.pw64Ctx = cv.getContext('2d');
  }
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; Module.pw64Img = null; }
  if (!Module.pw64Img) Module.pw64Img = Module.pw64Ctx.createImageData(w, h);
  Module.pw64Img.data.set(HEAPU8.subarray(ptr, ptr + w * h * 4));
  Module.pw64Ctx.putImageData(Module.pw64Img, 0, 0);
  Module.pw64Frames = (Module.pw64Frames || 0) + 1;
};

// ---- Test hook: ?dump=5,12 logs the screen as PNG (base64, chunked) at those seconds
(function () {
  var m = /[?&]dump=([\d.,]+)/.exec(location.search);
  if (!m) return;
  m[1].split(',').forEach(function (sec, k) {
    setTimeout(function () {
      if (!Module.pw64Canvas) { console.log('PW64PNG:' + k + ':none'); return; }
      var url = Module.pw64Canvas.toDataURL('image/png');
      for (var i = 0; i < url.length; i += 4000) console.log('PW64PNG:' + k + ':' + url.substr(i, 4000));
      console.log('PW64PNG:' + k + ':END');
    }, parseFloat(sec) * 1000);
  });
})();

// ---- Dev: ?script=flight drives the game with an input script (like the desktop tests)
Module.preRun = Module.preRun || [];
Module.preRun.push(function () {
  var m = /[?&]script=([\w-]+)/.exec(location.search);
  if (m) ENV.PW64_INPUT_SCRIPT = '/scripts/' + m[1] + '.txt';
});

// ---- Input: keyboard + gamepad into shared memory (read by web_input.cpp)
Module.pw64InputInit = function (keyPtr, padPtr) {
  Module.pw64KeyPtr = keyPtr;
  Module.pw64PadPtr = padPtr;
  var sc = function (code) {
    if (/^Key[A-Z]$/.test(code)) return 4 + code.charCodeAt(3) - 65;
    return { Enter: 40, Space: 44, ArrowRight: 79, ArrowLeft: 80, ArrowDown: 81, ArrowUp: 82,
             ShiftLeft: 225, ShiftRight: 229 }[code];
  };
  var set = function (e, v) {
    var s = sc(e.code);
    if (s === undefined) return;
    HEAPU8[keyPtr + s] = v;
    if (s >= 79 && s <= 82 || s === 44 || s === 40) e.preventDefault();
  };
  window.addEventListener('keydown', function (e) { set(e, 1); });
  window.addEventListener('keyup', function (e) { set(e, 0); });
  window.addEventListener('blur', function () { HEAPU8.fill(0, keyPtr, keyPtr + 512); });
  var poll = function () {
    var pads = navigator.getGamepads ? navigator.getGamepads() : [];
    var p = null;
    for (var i = 0; i < pads.length; i++) if (pads[i] && pads[i].connected) { p = pads[i]; break; }
    HEAPU8[padPtr] = p ? 1 : 0;
    if (p) {
      for (var b = 0; b < 17; b++) HEAPU8[padPtr + 1 + b] = (p.buttons[b] && p.buttons[b].pressed) ? 1 : 0;
      var ax = function (k, v) { HEAP16[(padPtr + 20 + k * 2) >> 1] = Math.max(-32768, Math.min(32767, Math.round(v * 32767))); };
      ax(0, p.axes[0] || 0); ax(1, p.axes[1] || 0); ax(2, p.axes[2] || 0); ax(3, p.axes[3] || 0);
      ax(4, p.buttons[6] ? p.buttons[6].value : 0); ax(5, p.buttons[7] ? p.buttons[7].value : 0);
    }
    requestAnimationFrame(poll);
  };
  requestAnimationFrame(poll);
};

// ---- Dev: ?keys=5:Enter,8:Enter presses keys at those seconds (tests the input path)
(function () {
  var m = /[?&]keys=([\w.:,]+)/.exec(location.search);
  if (!m) return;
  m[1].split(',').forEach(function (spec) {
    var p = spec.split(':');
    setTimeout(function () {
      window.dispatchEvent(new KeyboardEvent('keydown', { code: p[1] }));
      setTimeout(function () { window.dispatchEvent(new KeyboardEvent('keyup', { code: p[1] })); }, 150);
    }, parseFloat(p[0]) * 1000);
  });
})();

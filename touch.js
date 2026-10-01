// On-screen gamepad for phones and tablets. Writes the pad to
// window.skateTouch = [buttons, lt, rt, lx, ly, rx, ry] (XInput bits, triggers
// 0..1, axes -1..1, up positive), which the engine merges into controller 1
// like a real gamepad (crates/skate-game/src/input/platform.rs). Shown on touch
// screens, or with ?touch=1; the "Pad" button hides it.
const params = new URLSearchParams(location.search);
const wanted = params.get('touch') ?? (matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window ? '1' : '0');
if (wanted === '1') install();

function install() {
  const state = [0, 0, 0, 0, 0, 0, 0];
  window.skateTouch = state;
  document.body.classList.add('touch');

  const css = document.createElement('style');
  css.textContent = `
    body.touch #bevy { touch-action: none; }
    body.touch #mapbar { bottom: auto; top: 8px; right: 50%; transform: translateX(50%); }
    #pad { position: fixed; inset: 0; z-index: 3; pointer-events: none; user-select: none; -webkit-user-select: none; }
    #pad.hidden > :not(#padtoggle) { display: none; }
    #pad .stick { position: absolute; bottom: 24px; width: 150px; height: 150px; border-radius: 50%;
      background: #ffffff14; border: 2px solid #ffffff30; pointer-events: auto; touch-action: none; }
    #pad .knob { position: absolute; left: 50%; top: 50%; width: 64px; height: 64px; margin: -32px 0 0 -32px;
      border-radius: 50%; background: #ffffff40; }
    #pad .btn { position: absolute; width: 52px; height: 52px; border-radius: 50%; background: #0b0f14aa;
      border: 2px solid #ffffff40; color: #fff; font: 600 16px system-ui, sans-serif; display: flex;
      align-items: center; justify-content: center; pointer-events: auto; touch-action: none; }
    #pad .btn.small { width: 64px; height: 36px; border-radius: 10px; font-size: 13px; }
    #pad .btn.on { background: #58a6ffaa; }
    #pad .A { border-color: #3fb950; } #pad .B { border-color: #f85149; }
    #pad .X { border-color: #58a6ff; } #pad .Y { border-color: #d29922; }`;
  document.head.append(css);

  const pad = document.createElement('div');
  pad.id = 'pad';
  document.body.append(pad);
  // Edge offsets clear the notch / home indicator in landscape.
  const inset = { left: 'left', right: 'right', top: 'top', bottom: 'bottom' };
  const safe = (style) => Object.fromEntries(Object.entries(style).map(([k, v]) =>
    inset[k] && v.endsWith('px') ? [k, `calc(${v} + env(safe-area-inset-${k}))`] : [k, v]));
  const el = (cls, text, style) => {
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = text;
    Object.assign(d.style, safe(style));
    pad.append(d);
    return d;
  };

  const sticks = [];
  // Sticks: drag from wherever the thumb lands inside the base.
  const stick = (style, ix, iy) => {
    const base = el('stick', '', style);
    sticks.push(base);
    const knob = document.createElement('div');
    knob.className = 'knob';
    base.append(knob);
    let id = null, cx = 0, cy = 0;
    const set = (x, y) => {
      const r = base.offsetWidth * 0.37;
      const len = Math.hypot(x, y), k = len > r ? r / len : 1;
      x *= k; y *= k;
      knob.style.transform = `translate(${x}px, ${y}px)`;
      state[ix] = x / r;
      state[iy] = -y / r;
    };
    base.addEventListener('pointerdown', e => {
      id = e.pointerId; base.setPointerCapture(id);
      const b = base.getBoundingClientRect();
      cx = b.left + b.width / 2; cy = b.top + b.height / 2;
      set(e.clientX - cx, e.clientY - cy);
      e.preventDefault();
    });
    base.addEventListener('pointermove', e => { if (e.pointerId === id) set(e.clientX - cx, e.clientY - cy); });
    const end = e => {
      if (e.pointerId !== id) return;
      id = null; set(0, 0);
    };
    base.addEventListener('pointerup', end);
    base.addEventListener('pointercancel', end);
  };

  const hold = (d, down, up) => {
    const ids = new Set();
    d.addEventListener('pointerdown', e => { ids.add(e.pointerId); d.setPointerCapture(e.pointerId); d.classList.add('on'); down(); e.preventDefault(); });
    const end = e => { if (ids.delete(e.pointerId) && !ids.size) { d.classList.remove('on'); up(); } };
    d.addEventListener('pointerup', end);
    d.addEventListener('pointercancel', end);
  };
  const button = (cls, text, bit, style) => {
    const d = el(cls, text, style);
    hold(d, () => { state[0] |= bit; }, () => { state[0] &= ~bit; });
    return d;
  };
  const trigger = (text, index, style) => hold(el('btn small', text, style), () => { state[index] = 1; }, () => { state[index] = 0; });
  // A key the engine reads from the keyboard directly (the MX bike's F9).
  const key = (text, code, keyCode, style) => {
    const canvas = document.getElementById('bevy');
    const send = type => canvas.dispatchEvent(new KeyboardEvent(type, { code, key: code, keyCode, bubbles: true }));
    hold(el('btn small', text, style), () => send('keydown'), () => send('keyup'));
  };

  stick({ left: '16px' }, 3, 4);
  // Right column: face buttons stacked directly above the right stick.
  stick({ right: '16px' }, 5, 6);
  const face = {
    A: button('btn A', 'A', 0x1000, {}),
    B: button('btn B', 'B', 0x2000, {}),
    X: button('btn X', 'X', 0x4000, {}),
    Y: button('btn Y', 'Y', 0x8000, {}),
  };
  // Size the sticks and the face-button diamond from the screen height so the
  // diamond always fits between the right stick and the top button row.
  const layout = () => {
    const avail = Math.max(160, innerHeight - 72);
    const s = Math.round(Math.min(150, avail * 0.45));
    const b = Math.round(Math.min(52, avail * 0.17));
    const step = Math.round(b * 0.8);
    for (const base of sticks) {
      Object.assign(base.style, { width: `${s}px`, height: `${s}px`, bottom: 'calc(16px + env(safe-area-inset-bottom))' });
      const knob = base.firstChild;
      Object.assign(knob.style, { width: `${s * 0.42}px`, height: `${s * 0.42}px`, margin: `${-s * 0.21}px 0 0 ${-s * 0.21}px` });
    }
    const cx = 16 + s / 2 - b / 2, a = 16 + s + 6;
    const at = (d, right, bottom) => Object.assign(d.style, {
      width: `${b}px`, height: `${b}px`,
      right: `calc(${right}px + env(safe-area-inset-right))`, bottom: `calc(${bottom}px + env(safe-area-inset-bottom))`,
    });
    at(face.A, cx, a);
    at(face.B, cx - step - 4, a + step);
    at(face.X, cx + step + 4, a + step);
    at(face.Y, cx, a + 2 * step);
  };
  layout();
  addEventListener('resize', layout);
  trigger('LT', 1, { left: '16px', top: '12px' });
  const lb = button('btn small', 'LB', 0x0100, { left: '16px', top: '56px' });
  trigger('RT', 2, { right: '16px', top: '12px' });
  button('btn small', 'RB', 0x0200, { right: '88px', top: '12px' });
  button('btn small', 'Start', 0x0010, { left: '96px', top: '12px' });
  button('btn small', 'Back', 0x0020, { left: '96px', top: '56px' });
  key('Bike', 'F9', 120, { right: '160px', top: '12px' });

  // Session marker, as on the controller: LB + D-pad down (tap) sets it,
  // LB + D-pad up (hold) goes back to it. LB goes down a moment before the
  // D-pad bit so the engine sees the modifier already held.
  const session = (text, dpad, style) => {
    let timer = 0;
    const down = () => {
      state[0] |= 0x0100;
      timer = setTimeout(() => { state[0] |= dpad; }, 60);
    };
    const up = () => {
      clearTimeout(timer);
      state[0] &= ~dpad;
      if (!lb.classList.contains('on')) state[0] &= ~0x0100;
    };
    hold(el('btn small', text, style), down, up);
    return { down, up };
  };
  // Left side, next to Start/Back, clear of the map bar and the face buttons.
  const setMarker = session('Set', 0x0002, { left: '176px', top: '12px' });
  const goMarker = session('Go to', 0x0001, { left: '176px', top: '56px' });

  // Dev check: ?sessiondemo=1 sets the marker at 20 s, pushes forward 25-35 s,
  // then holds Go to 38-50 s, with no hands.
  if (params.get('sessiondemo') === '1') {
    const at = (sec, fn) => setTimeout(fn, sec * 1000);
    at(20, setMarker.down); at(23, setMarker.up);
    at(25, () => { state[4] = 1; }); at(35, () => { state[4] = 0; });
    at(38, goMarker.down); at(50, goMarker.up);
  }

  // Dev check: ?touchdemo=1 pushes (A, 0.6 s of every second) from 15 s, with no hands.
  if (params.get('touchdemo') === '1') setTimeout(() => setInterval(() => {
    state[0] |= 0x1000; setTimeout(() => { state[0] &= ~0x1000; }, 600);
  }, 1000), 15000);

  // Safari keeps a page's zoom across visits; rewriting the viewport tag resets it.
  const viewport = document.querySelector('meta[name=viewport]');
  const lockedViewport = viewport.content;
  viewport.content = 'width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, viewport-fit=cover';
  setTimeout(() => { viewport.content = lockedViewport; }, 300);
  // Block zoom gestures only at 1x, so a page left zoomed in can still be pinched back out.
  const zoomed = () => (window.visualViewport?.scale ?? 1) > 1.01;
  for (const g of ['gesturestart', 'gesturechange', 'gestureend']) {
    document.addEventListener(g, (e) => { if (!zoomed() || e.scale > 1) e.preventDefault(); }, { passive: false });
  }
  document.addEventListener('dblclick', (e) => e.preventDefault(), { passive: false });
  document.addEventListener('touchmove', (e) => { if (!zoomed() && (e.touches.length > 1 || (e.scale && e.scale !== 1))) e.preventDefault(); }, { passive: false });
  let lastEnd = 0;
  document.addEventListener('touchend', (e) => {
    const now = performance.now();
    if (now - lastEnd < 350 && !e.target.closest('#hint, #mapbar')) e.preventDefault();
    lastEnd = now;
  }, { passive: false });

  const toggle = el('btn small', 'Pad', { left: '50%', bottom: '8px', transform: 'translateX(-50%)', opacity: '0.7' });
  toggle.id = 'padtoggle';
  toggle.addEventListener('click', () => pad.classList.toggle('hidden'));
}

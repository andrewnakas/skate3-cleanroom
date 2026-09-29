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
    #pad .btn { position: absolute; width: 56px; height: 56px; border-radius: 50%; background: #0b0f14aa;
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
  const el = (cls, text, style) => {
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = text;
    Object.assign(d.style, style);
    pad.append(d);
    return d;
  };

  // Sticks: drag from wherever the thumb lands inside the base.
  const stick = (style, ix, iy) => {
    const base = el('stick', '', style);
    const knob = document.createElement('div');
    knob.className = 'knob';
    base.append(knob);
    let id = null, cx = 0, cy = 0;
    const r = 55;
    const set = (x, y) => {
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
  const button = (cls, text, bit, style) => hold(el(cls, text, style), () => { state[0] |= bit; }, () => { state[0] &= ~bit; });
  const trigger = (text, index, style) => hold(el('btn small', text, style), () => { state[index] = 1; }, () => { state[index] = 0; });
  // A key the engine reads from the keyboard directly (the MX bike's F9).
  const key = (text, code, keyCode, style) => {
    const canvas = document.getElementById('bevy');
    const send = type => canvas.dispatchEvent(new KeyboardEvent(type, { code, key: code, keyCode, bubbles: true }));
    hold(el('btn small', text, style), () => send('keydown'), () => send('keyup'));
  };

  stick({ left: '24px' }, 3, 4);
  stick({ right: '176px' }, 5, 6);
  button('btn A', 'A', 0x1000, { right: '72px', bottom: '24px' });
  button('btn B', 'B', 0x2000, { right: '16px', bottom: '80px' });
  button('btn X', 'X', 0x4000, { right: '128px', bottom: '80px' });
  button('btn Y', 'Y', 0x8000, { right: '72px', bottom: '136px' });
  trigger('LT', 1, { left: '16px', top: '12px' });
  button('btn small', 'LB', 0x0100, { left: '16px', top: '56px' });
  trigger('RT', 2, { right: '16px', top: '12px' });
  button('btn small', 'RB', 0x0200, { right: '16px', top: '56px' });
  button('btn small', 'Start', 0x0010, { left: '96px', top: '12px' });
  button('btn small', 'Back', 0x0020, { left: '96px', top: '56px' });
  key('Bike', 'F9', 120, { right: '96px', top: '12px' });

  // Dev check: ?touchdemo=1 pushes (A, 0.6 s of every second) from 15 s, with no hands.
  if (params.get('touchdemo') === '1') setTimeout(() => setInterval(() => {
    state[0] |= 0x1000; setTimeout(() => { state[0] &= ~0x1000; }, 600);
  }, 1000), 15000);

  const toggle = el('btn small', 'Pad', { left: '50%', bottom: '8px', transform: 'translateX(-50%)', opacity: '0.7' });
  toggle.id = 'padtoggle';
  toggle.addEventListener('click', () => pad.classList.toggle('hidden'));
}

// Downloads core.pack + one map (see tools/web_pack.py), hands the bytes to
// the wasm module as globals (crates/skate-game/src/web.rs), then starts it.
const statusEl = document.getElementById('status');
const barEl = document.getElementById('progress');
const overlay = document.getElementById('overlay');
const picker = document.getElementById('map');

function status(text, error = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', error);
}
globalThis.skateFatal = (message) => {
  overlay.style.display = 'flex';
  status(message, true);
};
globalThis.skateSelectMap = (name) => {
  const url = new URL(location.href);
  url.searchParams.set('map', name || '__test');
  url.searchParams.delete('teleport');
  url.searchParams.delete('args');
  location.href = url.toString();
};

async function fetchParts(parts, total, onBytes) {
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) {
    const response = await fetch(part);
    if (!response.ok) throw new Error(`${part}: HTTP ${response.status}`);
    const reader = response.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (at + value.length > total) throw new Error(`${part}: larger than pack.json says`);
      out.set(value, at);
      at += value.length;
      onBytes(value.length);
    }
  }
  if (at !== total) throw new Error(`Downloaded ${at} of ${total} bytes; pack.json is stale`);
  return out;
}

async function main() {
  if (!navigator.gpu) {
    status('This page needs a WebGPU browser: Chrome/Edge 113+ (or Safari 26+ / Firefox 141+ with WebGPU enabled).', true);
    return;
  }
  if (!(await navigator.gpu.requestAdapter())) {
    status('WebGPU is present but no GPU adapter is available. Check chrome://gpu or enable hardware acceleration.', true);
    return;
  }
  const pack = await (await fetch('pack.json', { cache: 'no-cache' })).json();
  const params = new URLSearchParams(location.search);
  const wanted = params.get('map') ?? pack.default;
  const map = pack.maps.find((m) => m.name === wanted) ?? null;

  picker.add(new Option('Test world', '__test', false, map === null));
  for (const m of pack.maps) {
    picker.add(new Option(`${m.name} (${(m.size / 1e6).toFixed(0)} MB)`, m.name, false, m === map));
  }
  picker.onchange = () => globalThis.skateSelectMap(picker.value);

  const total = pack.core.size + (map ? map.size : 0);
  let done = 0;
  const tick = (n) => {
    done += n;
    barEl.style.width = `${(100 * done / total).toFixed(1)}%`;
    status(`Downloading ${map ? map.name : 'test world'}... ${(done / 1e6).toFixed(0)} / ${(total / 1e6).toFixed(0)} MB`);
  };
  const [core, mapBytes] = await Promise.all([
    fetchParts(pack.core.parts, pack.core.size, tick),
    map ? fetchParts(map.parts, map.size, tick) : Promise.resolve(null),
  ]);
  globalThis.SKATE_PACK = core;
  globalThis.SKATE_MAP_LIST = pack.maps.map((m) => m.name);
  if (map) {
    globalThis.SKATE_MAP_NAME = map.name;
    globalThis.SKATE_MAP_BYTES = mapBytes;
  }
  if (params.has('debugloop')) {
    let frames = 0;
    const count = () => { frames++; requestAnimationFrame(count); };
    requestAnimationFrame(count);
    setInterval(() => console.log(`LOOP t=${(performance.now() / 1000).toFixed(1)} raf=${frames} visible=${document.visibilityState} focus=${document.hasFocus()}`), 1000);
  }
  if (params.has('debugkeys')) {
    for (const t of ['keydown', 'keyup']) addEventListener(t, (e) => console.log(`${t} ${e.code} target=${e.target.id || e.target.tagName}`), true);
  }
  if (params.has('teleport')) globalThis.SKATE_TELEPORT = params.get('teleport') || 'none';
  const extra = params.get('args');
  if (extra) globalThis.SKATE_ARGS = JSON.parse(extra);

  status('Starting engine (decoding map, compiling shaders)...');
  const { default: init } = await import('./skate3rust.js');
  try {
    await init();
  } catch (e) {
    // Bevy's winit loop unwinds with a control-flow exception on the web; only report real failures.
    if (!String(e).includes('Using exceptions for control flow')) {
      globalThis.skateFatal(`Engine failed: ${e}`);
      throw e;
    }
  }
  // main() has loaded everything synchronously; the render loop is running.
  if (!statusEl.classList.contains('error')) {
    overlay.style.display = 'none';
    document.getElementById('bevy').focus();
  }
}

main().catch((e) => globalThis.skateFatal(String(e && e.stack || e)));

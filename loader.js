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

// Downloads are kept in Cache Storage keyed by the content hash from pack.json,
// so a map switch (a page reload) only downloads the new map. Entries whose
// hash is no longer in pack.json are deleted, so a new build replaces them.
const CACHE = 'skate3-pack';

async function openCache() {
  try { return await caches.open(CACHE); } catch { return null; }
}

async function cachedParts(cache, key, parts, total, onBytes) {
  if (cache && key) {
    try {
      const hit = await cache.match(key);
      if (hit) {
        const bytes = new Uint8Array(await hit.arrayBuffer());
        if (bytes.length === total) { onBytes(total); return bytes; }
      }
    } catch { /* fall through to the network */ }
  }
  const bytes = await fetchParts(parts, total, onBytes);
  if (cache && key) {
    // Fire and forget: a full disk or quota error must not block the game.
    cache.put(key, new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } })).catch(() => {});
  }
  return bytes;
}

async function pruneCache(cache, keep) {
  if (!cache) return;
  try {
    for (const request of await cache.keys()) {
      if (!keep.has(new URL(request.url).pathname.split('/').pop())) await cache.delete(request);
    }
  } catch { /* best effort */ }
}

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

  const engine = pack.engine;
  const total = pack.core.size + (map ? map.size : 0) + (engine ? engine.size : 0);
  let done = 0;
  const tick = (n) => {
    done += n;
    barEl.style.width = `${(100 * done / total).toFixed(1)}%`;
    status(`Loading ${map ? map.name : 'test world'}... ${(done / 1e6).toFixed(0)} / ${(total / 1e6).toFixed(0)} MB`);
  };
  const cache = await openCache();
  const key = (name, hash) => (hash ? `cache/${name}.${hash}` : null);
  const keep = new Set([
    engine && `engine.${engine.hash}`,
    `core.${pack.core.hash}`,
    ...pack.maps.map((m) => `map-${m.name}.${m.hash}`),
  ].filter(Boolean));
  const [core, mapBytes, wasmBytes] = await Promise.all([
    cachedParts(cache, key('core', pack.core.hash), pack.core.parts, pack.core.size, tick),
    map ? cachedParts(cache, key(`map-${map.name}`, map.hash), map.parts, map.size, tick) : Promise.resolve(null),
    engine ? cachedParts(cache, key('engine', engine.hash), ['skate3rust_bg.wasm'], engine.size, tick) : Promise.resolve(null),
  ]);
  pruneCache(cache, keep);
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
    await init(wasmBytes ? { module_or_path: wasmBytes } : undefined);
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

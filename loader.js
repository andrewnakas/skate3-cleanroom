// Downloads core.pack + one map (see tools/web_pack.py), hands the bytes to
// the wasm module as globals (crates/skate-game/src/web.rs), then starts it.
// The map is one of the pack's own, a community map fetched from
// skatemods.com (?smap=<id>), any .skate URL (?mapurl=) or a local file.
import { DEFAULT_RELAY, joinRoom, listRooms, newRoomCode, relayUp, validRoom } from './net.js';

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
// Browsers (iOS above all) start Web Audio suspended until a user gesture, and
// the engine opens its audio output at startup, before any tap. Track every
// AudioContext it creates and resume them on the first tap/click/key.
const audioContexts = [];
for (const name of ['AudioContext', 'webkitAudioContext']) {
  const Base = globalThis[name];
  if (!Base) continue;
  globalThis[name] = new Proxy(Base, {
    construct(target, args) {
      const ctx = Reflect.construct(target, args);
      audioContexts.push(ctx);
      console.log(`SKATE_AUDIO context created state=${ctx.state} rate=${ctx.sampleRate}`);
      return ctx;
    },
  });
}
const unlockAudio = () => {
  for (const ctx of audioContexts) {
    if (ctx.state !== 'running') ctx.resume().then(() => console.log(`SKATE_AUDIO resumed state=${ctx.state}`), () => {});
  }
};
for (const event of ['pointerdown', 'pointerup', 'touchend', 'click', 'keydown']) {
  addEventListener(event, unlockAudio, { capture: true, passive: true });
}

// Crash breadcrumbs. iOS silently reloads a tab it kills (memory, GPU), so the
// page saves a heartbeat every 2 s and, if the last session never said
// goodbye, shows how it ended on the next load.
const CRUMB = 'skate3-last-session';
const session = { map: null, lite: null, started: Date.now(), beat: Date.now(), frames: 0, wasmMB: 0, fps: 0, errors: [] };
const saveCrumb = (clean) => {
  try { localStorage.setItem(CRUMB, JSON.stringify({ ...session, clean })); } catch { /* private mode */ }
};
let previousCrumb = null;
try { previousCrumb = JSON.parse(localStorage.getItem(CRUMB) || 'null'); } catch { /* ignore */ }
addEventListener('error', (e) => { session.errors.push(String(e.message || e.error).slice(0, 160)); saveCrumb(false); });
addEventListener('unhandledrejection', (e) => { session.errors.push(String(e.reason).slice(0, 160)); saveCrumb(false); });
addEventListener('pagehide', () => saveCrumb(true));
(() => {
  let last = performance.now(), count = 0;
  const tick = () => { session.frames++; count++; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  setInterval(() => {
    const now = performance.now();
    session.fps = Math.round(count * 1000 / (now - last));
    last = now; count = 0;
    session.beat = Date.now();
    session.wasmMB = globalThis.SKATE_WASM_MB ?? session.wasmMB;
    saveCrumb(false);
  }, 2000);
})();
const describeCrumb = (c) => {
  const secs = Math.round((c.beat - c.started) / 1000);
  return `Last session (${c.map ?? '?'}${c.lite ? ', lite' : ''}) ended unexpectedly after `
    + `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}: ${c.frames} frames, ~${c.fps} fps, `
    + `engine memory ${c.wasmMB} MB${c.errors.length ? `, errors: ${c.errors.slice(-2).join(' | ')}` : ''}.`;
};

// Fullscreen the whole page (canvas + map bar); the canvas follows the window
// size, so the render resizes with it. Focus returns to the game for input.
const fullscreenButton = document.getElementById('fullscreen');
const hint = document.getElementById('hint');
const showHint = (html) => {
  hint.innerHTML = html;
  hint.style.display = 'block';
  hint.onclick = () => { hint.style.display = 'none'; };
};
// Launched from the home screen: already without browser bars.
if (navigator.standalone || matchMedia('(display-mode: fullscreen), (display-mode: standalone)').matches) {
  fullscreenButton.style.display = 'none';
}
fullscreenButton.onclick = async () => {
  const root = document.documentElement;
  const request = root.requestFullscreen ?? root.webkitRequestFullscreen;
  if (!request) {
    // iPhone Safari only fullscreens videos; a home-screen web app has no bars.
    showHint('<b>Fullscreen on iPhone</b><br>Safari cannot fullscreen a web page. Tap <b>Share</b> '
      + '&rarr; <b>Add to Home Screen</b>, then open <b>Skate 3</b> from your home screen: it runs '
      + 'with no browser bars.<br><br><small>Tap to close.</small>');
    return;
  }
  try {
    if (document.fullscreenElement ?? document.webkitFullscreenElement) {
      await (document.exitFullscreen ?? document.webkitExitFullscreen).call(document);
    } else {
      await request.call(root, { navigationUI: 'hide' });
    }
  } catch { /* denied (e.g. iframe without allowfullscreen): keep windowed */ }
  document.getElementById('bevy').focus();
};
for (const event of ['fullscreenchange', 'webkitfullscreenchange']) {
  document.addEventListener(event, () => {
    const on = document.fullscreenElement ?? document.webkitFullscreenElement;
    fullscreenButton.textContent = on ? 'Exit fullscreen' : 'Fullscreen';
  });
}

// Every way of choosing a map is a page reload with one of these parameters
// (the engine loads its map once, at startup).
const MAP_PARAMS = ['map', 'smap', 'mapurl', 'local'];
function go(param, value) {
  const url = new URL(location.href);
  if (param === 'room') { url.searchParams.set('room', value); location.href = url.toString(); return; }
  // ?room= and ?relay= stay: switching map keeps you in the room (everyone
  // has to pick the same map to see each other).
  for (const name of [...MAP_PARAMS, 'teleport', 'args']) url.searchParams.delete(name);
  url.searchParams.set(param, value);
  location.href = url.toString();
}
globalThis.skateSelectMap = (name) => go('map', name || '__test');

// Community maps. The catalog is skatemods.com (approved maps that have a
// .skate conversion); ?skatemods=<origin> points at another instance (tests).
// A map can also come from any URL that allows cross-origin reads (?mapurl=)
// or from a .skate file on this device ("Open .skate file").
const SKATEMODS = (new URLSearchParams(location.search).get('skatemods') ?? 'https://skatemods.com').replace(/\/+$/, '');
const LOCAL_KEY = 'cache/local-map';

function safeName(text, taken) {
  let name = String(text ?? '').normalize('NFKD').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48) || 'CommunityMap';
  // A built-in map's name would attach that map's props, sky and teleports.
  while (taken.has(name)) name += '_community';
  return name;
}

async function shortHash(text) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest).slice(0, 8)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`${new URL(url).host}: HTTP ${response.status}`);
  return response.json();
}

/** The map the URL asks for, if it is not one of the pack's own: {name, label, key, size, url}. */
async function externalMap(params, taken) {
  const id = params.get('smap');
  if (id) {
    const detail = await getJson(`${SKATEMODS}/api/maps/${encodeURIComponent(id)}`);
    const file = (detail.files ?? []).find((f) => f.kind === 'skate');
    if (!file) throw new Error(`"${detail.title}" has no .skate conversion on skatemods.com yet.`);
    return {
      name: safeName(detail.title, taken),
      label: `${detail.title} by ${detail.authorCredit}`,
      credit: `${detail.title} by ${detail.authorCredit} (${detail.licenseLabel ?? detail.license}), from skatemods.com`,
      page: `${SKATEMODS}/maps/view/?id=${encodeURIComponent(id)}`,
      key: `smap-${file.id}`,
      size: file.bytes,
      url: `${SKATEMODS}/api/maps/${encodeURIComponent(id)}/files/${encodeURIComponent(file.id)}?cors=1`,
    };
  }
  const link = params.get('mapurl');
  if (link) {
    const url = new URL(link, location.href);
    if (url.protocol !== 'https:' && url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') {
      throw new Error('?mapurl= must be an https:// address.');
    }
    const file = decodeURIComponent(url.pathname.split('/').pop() || 'map').replace(/\.skate$/i, '');
    return { name: safeName(file, taken), label: `${file} (${url.host})`, key: `url-${await shortHash(url.href)}`, size: 0, url: url.href };
  }
  const local = params.get('local');
  if (local) return { name: safeName(local, taken), label: `${local} (your file)`, key: 'local-map', size: 0, url: null };
  return null;
}

/** Download a map whose size may be unknown; checks that it is a .skate container. */
async function fetchMap(map, cache, onBytes, onTotal) {
  const key = `cache/${map.key}`;
  if (cache) {
    try {
      const hit = await cache.match(key);
      if (hit) {
        const bytes = new Uint8Array(await hit.arrayBuffer());
        if (!map.size || bytes.length === map.size) { onTotal(bytes.length); onBytes(bytes.length); return bytes; }
      }
    } catch { /* fall through to the network */ }
  }
  if (!map.url) throw new Error('That file is no longer stored in this browser. Choose "Open .skate file" again.');
  let response;
  try {
    response = await fetch(map.url);
  } catch (e) {
    throw new Error(`Could not download ${map.label}: the server did not answer or does not allow this page to read it (${e.message}).`);
  }
  if (!response.ok) throw new Error(`Could not download ${map.label}: HTTP ${response.status}`);
  const declared = map.size || Number(response.headers.get('Content-Length')) || 0;
  onTotal(declared);
  const chunks = [];
  let got = 0;
  const reader = response.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onBytes(value.length);
  }
  if (map.size && got !== map.size) throw new Error(`Downloaded ${got} of ${map.size} bytes of ${map.label}.`);
  const bytes = new Uint8Array(got);
  let at = 0;
  for (const chunk of chunks) { bytes.set(chunk, at); at += chunk.length; }
  if (!declared) onTotal(got);
  checkSkate(bytes, map.label);
  if (cache) cache.put(key, new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } })).catch(() => {});
  return bytes;
}

function checkSkate(bytes, label) {
  const magic = String.fromCharCode(...bytes.subarray(0, 5));
  if (magic !== 'SKATE') throw new Error(`${label} is not a .skate map (it starts with "${magic.replace(/[^ -~]/g, '?')}").`);
}

/** Fill the picker's community group from the skatemods.com catalog. */
async function listCommunity(group, currentId) {
  const note = (text) => { const o = new Option(text, '', false, false); o.disabled = true; group.replaceChildren(o); };
  note('loading...');
  try {
    const { maps } = await getJson(`${SKATEMODS}/api/maps`);
    const playable = (maps ?? []).filter((m) => (m.kinds ?? []).includes('skate'));
    if (!playable.length) { note('none published yet'); return; }
    group.replaceChildren(...playable.map((m) => new Option(`${m.title} by ${m.author_credit}`, `smap:${m.id}`, false, m.id === currentId)));
  } catch (e) {
    console.warn(`skatemods catalog: ${e.message}`);
    note('catalog unavailable');
  }
}

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

// Short messages over the game (joins, leaves, room problems).
function toast(text, sticky = false) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.style.display = 'block';
  clearTimeout(toast.timer);
  if (!sticky) toast.timer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// Room menu: new private room (invite link only), new public room (listed for
// everyone), or join a listed public room. In a room it becomes "copy invite".
function setupRoomButton(params, mapLabel, builtIn) {
  const button = document.getElementById('roombtn');
  const menu = document.getElementById('roommenu');
  const room = params.get('room');
  const relay = params.get('relay') || DEFAULT_RELAY;
  if (room) {
    button.hidden = false;
    button.textContent = `Room ${room}: copy invite`;
    button.onclick = async () => {
      try {
        await navigator.clipboard.writeText(location.href);
        toast('Invite link copied. Friends who open it join this room on this map.');
      } catch {
        toast(`Invite link: ${location.href}`, true);
      }
    };
    const leave = document.getElementById('roomleave');
    leave.hidden = false;
    leave.onclick = () => {
      const url = new URL(location.href);
      url.searchParams.delete('room');
      location.href = url.toString();
    };
    return;
  }
  // No relay reachable (not deployed, offline): no multiplayer menu.
  relayUp(relay).then(async (up) => {
    if (!up) return;
    menu.hidden = false;
    const fill = async () => {
      const rooms = await listRooms(relay);
      const here = rooms.filter((r) => r.map === mapLabel);
      const elsewhere = rooms.filter((r) => r.map !== mapLabel && builtIn.has(r.map));
      menu.replaceChildren(new Option('Multiplayer...', '', true, true),
        new Option('New private room (invite link)', 'new'), new Option('New public room (listed)', 'newpub'));
      const group = (label, list, value) => {
        if (!list.length) return;
        const g = document.createElement('optgroup');
        g.label = label;
        for (const r of list) g.append(new Option(`${value(r).label} (${r.players}/${r.max})`, value(r).value));
        menu.append(g);
      };
      group('Public rooms on this map', here, (r) => ({ label: r.code, value: `join:${r.code}` }));
      group('Public rooms on other maps', elsewhere, (r) => ({ label: `${r.map}: ${r.code}`, value: `join:${r.code}:${r.map}` }));
    };
    await fill();
    menu.onfocus = fill;
    menu.onchange = () => {
      const value = menu.value;
      if (value === 'new') go('room', newRoomCode());
      else if (value === 'newpub') go('room', `pub-${newRoomCode()}`);
      else if (value.startsWith('join:')) {
        const [, code, map] = value.split(':');
        const url = new URL(location.href);
        if (map) { for (const name of MAP_PARAMS) url.searchParams.delete(name); url.searchParams.set('map', map); }
        url.searchParams.set('room', code);
        location.href = url.toString();
      }
    };
  });
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
  const cache = await openCache();
  const builtIn = new Set(['__test', ...pack.maps.map((m) => m.name)]);
  // A community map, a URL or a local file; null for the pack's own maps.
  const external = await externalMap(params, builtIn);
  const wanted = params.get('map') ?? pack.default;
  const map = external ? null : pack.maps.find((m) => m.name === wanted) ?? null;

  picker.add(new Option('Test world', '__test', false, !external && map === null));
  for (const m of pack.maps) {
    picker.add(new Option(`${m.name} (${(m.size / 1e6).toFixed(0)} MB)`, m.name, false, m === map));
  }
  if (external && !params.get('smap')) picker.add(new Option(external.label, '', false, true));
  const community = document.createElement('optgroup');
  community.label = 'Community maps (skatemods.com)';
  picker.add(community);
  listCommunity(community, params.get('smap'));
  const more = document.createElement('optgroup');
  more.label = 'Your own';
  more.append(new Option('Open .skate file...', 'open-file'));
  picker.add(more);
  const fileInput = document.getElementById('mapfile');
  picker.onchange = () => {
    const value = picker.value;
    if (value === 'open-file') fileInput.click();
    else if (value.startsWith('smap:')) go('smap', value.slice(5));
    else if (value) globalThis.skateSelectMap(value);
  };
  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      checkSkate(bytes, file.name);
      if (!cache) throw new Error('This browser has storage switched off (private window?), so the file cannot be kept across the reload.');
      await cache.put(LOCAL_KEY, new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } }));
      go('local', file.name.replace(/\.skate$/i, ''));
    } catch (e) {
      globalThis.skateFatal(String(e.message || e));
    }
  };

  const engine = pack.engine;
  let total = pack.core.size + (map ? map.size : 0) + (external ? external.size : 0) + (engine ? engine.size : 0);
  let done = 0;
  const shown = external ? external.label : map ? map.name : 'test world';
  const tick = (n) => {
    done += n;
    barEl.style.width = `${Math.min(100, 100 * done / total).toFixed(1)}%`;
    status(`Loading ${shown}... ${(done / 1e6).toFixed(0)} / ${(total / 1e6).toFixed(0)} MB`);
  };
  const key = (name, hash) => (hash ? `cache/${name}.${hash}` : null);
  const keep = new Set([
    engine && `engine.${engine.hash}`,
    `core.${pack.core.hash}`,
    ...pack.maps.map((m) => `map-${m.name}.${m.hash}`),
    // The community map being played stays cached; others are dropped.
    external && external.key,
  ].filter(Boolean));
  // Phones: iOS reloads a tab that goes much past ~1 GB, so textures are halved
  // and MSAA is off there (?lite=0 / ?lite=1 override the touch-screen guess).
  globalThis.SKATE_DEBUGMEM = params.has('debugmem');
  session.map = shown;
  globalThis.SKATE_LITE = (params.get('lite') ?? (matchMedia('(pointer: coarse)').matches ? '1' : '0')) === '1';
  session.lite = globalThis.SKATE_LITE;
  if (previousCrumb && !previousCrumb.clean && previousCrumb.frames > 0) {
    const note = document.createElement('div');
    note.id = 'lastcrash';
    note.style.cssText = 'color:#ffa657;font-size:12px;margin-top:8px';
    note.textContent = describeCrumb(previousCrumb);
    document.getElementById('panel').append(note);
    console.log(`SKATE_LAST_SESSION ${note.textContent}`);
  }
  let [core, mapBytes, wasmBytes] = await Promise.all([
    cachedParts(cache, key('core', pack.core.hash), pack.core.parts, pack.core.size, tick),
    map ? cachedParts(cache, key(`map-${map.name}`, map.hash), map.parts, map.size, tick)
      : external ? fetchMap(external, cache, tick, (n) => { total += n - external.size; external.size = n; }) : Promise.resolve(null),
    engine ? cachedParts(cache, key('engine', engine.hash), ['skate3rust_bg.wasm'], engine.size, tick) : Promise.resolve(null),
  ]);
  pruneCache(cache, keep);
  globalThis.SKATE_PACK = core;
  globalThis.SKATE_MAP_LIST = pack.maps.map((m) => m.name);
  if (map || external) {
    globalThis.SKATE_MAP_NAME = (map ?? external).name;
    globalThis.SKATE_MAP_BYTES = mapBytes;
  }
  if (external) {
    console.log(`SKATE_COMMUNITY_MAP name=${external.name} bytes=${mapBytes.length} source=${external.url ?? 'local file'}`);
    const credit = document.getElementById('mapcredit');
    if (external.credit) {
      credit.textContent = external.credit;
      if (external.page) credit.href = external.page;
      credit.hidden = false;
    }
  }
  // The engine copies these into its own memory and clears the globals; do not
  // keep a second reference here for the whole session (~250 MB).
  core = null;
  mapBytes = null;
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

  // Multiplayer room (?room=CODE): join before the engine starts so it can open
  // its session at boot. The host is whoever was in the room first.
  const mapLabel = external ? external.name : map ? map.name : 'Test world';
  setupRoomButton(params, mapLabel, builtIn);
  const room = params.get('room');
  if (room) {
    if (!validRoom(room)) throw new Error('?room= must be 4-24 letters, digits, - or _.');
    document.getElementById('roommenu').hidden = true;
    status(`Joining room ${room}...`);
    const relay = params.get('relay') || DEFAULT_RELAY;
    const mapId = external ? external.key : map ? `${map.name}.${map.hash}` : '__test';
    const welcome = await joinRoom({ relay, room, map: mapId, label: mapLabel, onNotice: toast });
    console.log(`SKATE_ROOM room=${room} self=${welcome.self} host=${welcome.host} members=${welcome.members.length}`);
  }

  status('Starting engine (decoding map, compiling shaders)...');
  const { default: init } = await import('./skate3rust.js');
  try {
    const running = init(wasmBytes ? { module_or_path: wasmBytes } : undefined);
    wasmBytes = null;
    await running;
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

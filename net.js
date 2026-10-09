// Browser multiplayer: joins a room on the relay (skate3-cleanroom/relay)
// before the engine starts and gives the engine's Web transport
// (crates/skate-game/src/multiplayer/transport.rs) three functions:
//   skateNetSend(peer, Uint8Array)  queue one datagram to a room member
//   skateNetPoll()                  [[peer, Uint8Array], ...] received since last call
//   skateNetStatus()                one line for the HUD
// Room members are numbered by the relay; the oldest member hosts the session.
// Everyone in a room must be on the same map (the session checks it).

export const DEFAULT_RELAY = 'wss://skatemods.com/rooms';
const ROOM = /^[A-Za-z0-9_-]{4,24}$/;

/** True when the relay answers (the Multiplayer button is hidden otherwise). */
export async function relayUp(relay) {
  try {
    const url = relay.replace(/^ws/, 'http').replace(/\/+$/, '') + '/health';
    const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
    return response.ok;
  } catch {
    return false;
  }
}

export function validRoom(code) {
  return ROOM.test(code ?? '');
}

export function newRoomCode() {
  const alphabet = 'abcdefghjkmnpqrstuvwxyz23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return [...bytes].map((b) => alphabet[b % alphabet.length]).join('');
}

/** Session number shared by everyone in a room on a map: 16 hex digits, never 0. */
async function sessionFor(room, map) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`skate3-room/${room}/${map}`));
  const hex = [...new Uint8Array(digest).slice(0, 8)].map((b) => b.toString(16).padStart(2, '0')).join('');
  return /^0+$/.test(hex) ? '0000000000000001' : hex;
}

/**
 * Connect to `room` and wait for the relay's welcome. Resolves to
 * {self, host, members}; sets globalThis.SKATE_NET for the engine.
 * `onNotice(text)` reports joins, leaves and disconnects to the page.
 */
export async function joinRoom({ relay, room, map, onNotice }) {
  const inbox = [];
  const counts = { tx: 0, txBytes: 0, rx: 0, rxBytes: 0, polls: 0, dropped: 0 };
  // Debug line every 5 s with ?debugnet.
  if (new URLSearchParams(location.search).has('debugnet')) {
    setInterval(() => console.log(`SKATE_NETJS ${JSON.stringify(counts)} buffered=${socket.bufferedAmount}`), 5000);
  }
  let status = 'Connecting to room...';
  let members = new Set();
  let self = 0;
  let host = 0;
  const socket = new WebSocket(`${relay.replace(/\/+$/, '')}/room/${encodeURIComponent(room)}`);
  socket.binaryType = 'arraybuffer';
  const describe = () => `Room ${room}: ${members.size} player${members.size === 1 ? '' : 's'}`
    + `${self === host ? ' (you host)' : ''} | invite: ${location.href}`;

  globalThis.skateNetSend = (peer, bytes) => {
    if (socket.readyState !== WebSocket.OPEN) return;
    const out = new Uint8Array(4 + bytes.length);
    new DataView(out.buffer).setUint32(0, peer, true);
    out.set(bytes, 4);
    socket.send(out);
    counts.tx++; counts.txBytes += out.length;
  };
  globalThis.skateNetPoll = () => { counts.polls++; return inbox.splice(0, inbox.length); };
  globalThis.skateNetStatus = () => status;

  const welcome = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('The multiplayer relay did not answer within 10 s.')), 10000);
    socket.onerror = () => { clearTimeout(timer); reject(new Error(`Could not reach the multiplayer relay (${relay}).`)); };
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') return;
      const notice = JSON.parse(event.data);
      if (notice.type === 'full') { clearTimeout(timer); reject(new Error(`Room ${room} is full (${notice.max} players).`)); }
      if (notice.type === 'welcome') { clearTimeout(timer); resolve(notice); }
    };
  });
  self = welcome.self;
  host = welcome.host;
  members = new Set(welcome.members);
  status = describe();

  socket.onmessage = (event) => {
    if (typeof event.data === 'string') {
      const notice = JSON.parse(event.data);
      if (notice.type === 'join') { members.add(notice.id); onNotice?.(`A player joined (${members.size} in room)`); }
      if (notice.type === 'leave') { members.delete(notice.id); onNotice?.(`A player left (${members.size} in room)`); }
      if (notice.type === 'host-left') {
        status = `Room ${room}: the host left. Reload to start a new session in this room.`;
        onNotice?.(status, true);
      } else {
        status = describe();
      }
      return;
    }
    const data = new Uint8Array(event.data);
    if (data.length < 5) return;
    const from = new DataView(data.buffer).getUint32(0, true);
    inbox.push([from, data.subarray(4)]);
    counts.rx++; counts.rxBytes += data.length;
    // A tab in the background stops polling; do not let the queue grow forever.
    if (inbox.length > 4096) { counts.dropped += inbox.length - 4096; inbox.splice(0, inbox.length - 4096); }
  };
  socket.onclose = () => {
    status = `Room ${room}: disconnected from the relay. Reload to rejoin.`;
    onNotice?.(status, true);
  };

  globalThis.SKATE_NET = { self, host, session: await sessionFor(room, map) };
  return welcome;
}

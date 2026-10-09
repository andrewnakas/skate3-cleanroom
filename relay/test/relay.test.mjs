// Run `npx wrangler dev --port 8788` in relay/, then: node --test test/
import { test } from 'node:test';
import assert from 'node:assert/strict';

const BASE = process.env.RELAY ?? 'ws://localhost:8788';

function open(room) {
  const ws = new WebSocket(`${BASE}/room/${room}`);
  ws.binaryType = 'arraybuffer';
  const inbox = [];
  const waiters = [];
  ws.onmessage = (e) => {
    const item = typeof e.data === 'string' ? JSON.parse(e.data) : new Uint8Array(e.data);
    const w = waiters.shift();
    if (w) w(item); else inbox.push(item);
  };
  const next = () => (inbox.length ? Promise.resolve(inbox.shift()) : new Promise((r) => waiters.push(r)));
  return new Promise((resolve, reject) => {
    ws.onopen = () => resolve({ ws, next });
    ws.onerror = reject;
  });
}

function frame(target, bytes) {
  const out = new Uint8Array(4 + bytes.length);
  new DataView(out.buffer).setUint32(0, target, true);
  out.set(bytes, 4);
  return out;
}

test('members, forwarding, host leaving', async () => {
  const room = `t${Date.now().toString(36)}`;
  const a = await open(room);
  const wa = await a.next();
  assert.deepEqual([wa.type, wa.self, wa.host], ['welcome', 1, 1]);
  const b = await open(room);
  const wb = await b.next();
  assert.deepEqual([wb.type, wb.self, wb.host], ['welcome', 2, 1]);
  assert.deepEqual(await a.next(), { type: 'join', id: 2 });

  a.ws.send(frame(2, new Uint8Array([7, 8, 9])));
  const got = await b.next();
  assert.deepEqual([...got], [1, 0, 0, 0, 7, 8, 9]);
  b.ws.send(frame(1, new Uint8Array([1, 2])));
  assert.deepEqual([...(await a.next())], [2, 0, 0, 0, 1, 2]);

  a.ws.close();
  assert.deepEqual(await b.next(), { type: 'host-left' });
  b.ws.close();
});

test('room cap', async () => {
  const room = `c${Date.now().toString(36)}`;
  const members = [];
  for (let i = 0; i < 10; i++) { const m = await open(room); await m.next(); members.push(m); }
  const extra = await open(room);
  assert.equal((await extra.next()).type, 'full');
  for (const m of members) m.ws.close();
});

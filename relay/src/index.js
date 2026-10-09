// Room relay for the browser build's multiplayer (engine web/net.js).
//
//   GET [/rooms]/room/<code>  (WebSocket upgrade)   join room <code> (4-24 of [A-Za-z0-9_-])
//   GET [/rooms]/health
//   GET [/rooms]/list[?map=<label>]   public rooms: [{code, map, players, max}]
// A room whose code starts with "pub-" is public: it is listed (with the map
// label its first member passed as ?map=) while it has members. Any other code
// is private and known only to people who have the invite link.
// The /rooms prefix is the skatemods.com/rooms/* route; workers.dev has none.
//
// The relay knows nothing about the game. It numbers the members of a room
// (1, 2, 3, ... in join order), tells each one who it is and who the host is
// (the oldest member), and forwards binary frames:
//   client -> relay: u32 LE target member id, then the datagram
//   relay -> client: u32 LE source member id, then the datagram
// Text frames from the relay are JSON notices:
//   {"type":"welcome","self":N,"host":N,"members":[...]}
//   {"type":"join","id":N} / {"type":"leave","id":N}
//   {"type":"host-left"}   the session ends; the page offers to rejoin
//   {"type":"full"}        the room already has MAX_MEMBERS (connection closes)
import { DurableObject } from 'cloudflare:workers';

const MAX_MEMBERS = 10;          // skate-net lobby::MAX_PLAYERS
const MAX_DATAGRAM = 64 * 1024;  // generous; skate-net datagrams are ~1.2 KB
const ROOM = /^[A-Za-z0-9_-]{4,24}$/;

const cors = { 'Access-Control-Allow-Origin': '*' };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/rooms(?=\/)/, '');
    if (path === '/health') return Response.json({ ok: true }, { headers: cors });
    if (path === '/list') {
      const dir = env.DIRECTORY.get(env.DIRECTORY.idFromName('all'));
      return dir.fetch(new Request(`https://dir/list${url.search}`));
    }
    const match = path.match(/^\/room\/([^/]+)$/);
    if (!match || !ROOM.test(match[1])) return new Response('Not found', { status: 404, headers: cors });
    if (request.headers.get('Upgrade') !== 'websocket') {
      return new Response('Expected a WebSocket upgrade', { status: 426, headers: cors });
    }
    const room = env.ROOMS.get(env.ROOMS.idFromName(match[1]));
    return room.fetch(request);
  },
};

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    // Survives hibernation: the member id lives on each socket's attachment.
    this.next = 1;
    for (const ws of this.ctx.getWebSockets()) {
      const id = ws.deserializeAttachment()?.id ?? 0;
      if (id >= this.next) this.next = id + 1;
    }
  }

  members() {
    return this.ctx.getWebSockets()
      .map((ws) => ({ ws, id: ws.deserializeAttachment()?.id }))
      .filter((m) => m.id)
      .sort((a, b) => a.id - b.id);
  }

  // Public rooms report their member count to the directory.
  async report(count) {
    const info = await this.ctx.storage.get('info');
    if (!info) return;
    const dir = this.env.DIRECTORY.get(this.env.DIRECTORY.idFromName('all'));
    await dir.fetch(new Request('https://dir/report', { method: 'POST', body: JSON.stringify({ ...info, players: count }) }));
  }

  async fetch(request) {
    const url = new URL(request.url);
    const code = decodeURIComponent(url.pathname.split('/').pop());
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server);
    const members = this.members();
    if (members.length >= MAX_MEMBERS) {
      server.send(JSON.stringify({ type: 'full', max: MAX_MEMBERS }));
      server.close(4001, 'Room is full');
      return new Response(null, { status: 101, webSocket: client });
    }
    // An empty room starts numbering again, so a stale host id never lingers.
    if (!members.length) {
      this.next = 1;
      if (code.startsWith('pub-')) {
        const map = (url.searchParams.get('map') ?? '').replace(/[^A-Za-z0-9 _.-]/g, '').slice(0, 48) || 'Unknown map';
        await this.ctx.storage.put('info', { code, map });
      } else {
        await this.ctx.storage.delete('info');
      }
    }
    const id = this.next++;
    server.serializeAttachment({ id });
    const host = members.length ? members[0].id : id;
    server.send(JSON.stringify({ type: 'welcome', self: id, host, members: [...members.map((m) => m.id), id] }));
    for (const m of members) this.trySend(m.ws, JSON.stringify({ type: 'join', id }));
    this.ctx.waitUntil(this.report(members.length + 1));
    return new Response(null, { status: 101, webSocket: client });
  }

  trySend(ws, data) {
    try { ws.send(data); } catch { /* closing */ }
  }

  async webSocketMessage(ws, message) {
    if (typeof message === 'string') return; // clients only send binary
    const from = ws.deserializeAttachment()?.id;
    if (!from || message.byteLength < 5 || message.byteLength > MAX_DATAGRAM + 4) return;
    const target = new DataView(message).getUint32(0, true);
    const out = new Uint8Array(message.byteLength);
    out.set(new Uint8Array(message));
    new DataView(out.buffer).setUint32(0, from, true);
    for (const m of this.members()) {
      if (m.id === target && m.ws !== ws) { this.trySend(m.ws, out); break; }
    }
  }

  async webSocketClose(ws) { this.gone(ws); await this.report(this.members().length); }
  async webSocketError(ws) { this.gone(ws); await this.report(this.members().length); }

  gone(ws) {
    const id = ws.deserializeAttachment()?.id;
    if (!id) return;
    ws.serializeAttachment({ id: 0 });
    try { ws.close(1000, 'bye'); } catch { /* already closed */ }
    const rest = this.members();
    // The session was built around the host, so it cannot continue without it.
    const wasHost = rest.length && rest.every((m) => m.id > id);
    for (const m of rest) this.trySend(m.ws, JSON.stringify(wasHost ? { type: 'host-left' } : { type: 'leave', id }));
  }
}

// One instance: the list of public rooms that currently have members.
export class Directory extends DurableObject {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === 'POST') {
      const { code, map, players } = await request.json();
      if (players > 0) await this.ctx.storage.put(`room:${code}`, { code, map, players, seen: Date.now() });
      else await this.ctx.storage.delete(`room:${code}`);
      return new Response('ok');
    }
    const want = url.searchParams.get('map');
    const rooms = [];
    const stale = Date.now() - 6 * 3600 * 1000;   // a room that vanished without a close event
    for (const [key, room] of await this.ctx.storage.list({ prefix: 'room:' })) {
      if (room.seen < stale) { await this.ctx.storage.delete(key); continue; }
      if (!want || room.map === want) rooms.push({ code: room.code, map: room.map, players: room.players, max: MAX_MEMBERS });
    }
    rooms.sort((a, b) => b.players - a.players);
    return Response.json({ rooms: rooms.slice(0, 50) }, { headers: { ...cors, 'Cache-Control': 'no-store' } });
  }
}

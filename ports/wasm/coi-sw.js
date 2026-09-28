// Cross-origin isolation for static hosting (GitHub Pages cannot set headers).
// Re-serves same-origin responses with COOP/COEP so SharedArrayBuffer, and so
// WebAssembly threads, are available. Registered by the page on first load.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.cache === 'only-if-cached' && req.mode !== 'same-origin') return;
  e.respondWith(
    fetch(req).then((res) => {
      if (res.status === 0) return res;
      const headers = new Headers(res.headers);
      headers.set('Cross-Origin-Opener-Policy', 'same-origin');
      headers.set('Cross-Origin-Embedder-Policy', 'require-corp');
      headers.set('Cross-Origin-Resource-Policy', 'cross-origin');
      return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
    })
  );
});

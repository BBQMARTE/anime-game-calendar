/* 二游活动聚合 PWA Service Worker
   静态资源缓存优先;/api/events 网络优先、失败回退缓存(离线可看) */
const CACHE = 'ycal-v3';
const ASSETS = ['/', '/scraper.js', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  if (url.pathname === '/api/events') {
    // 网络优先:成功则更新缓存,离线回退上次数据
    e.respondWith(
      fetch(e.request).then((r) => {
        const cp = r.clone();
        caches.open(CACHE).then((c) => c.put('/api/events', cp));
        return r;
      }).catch(() => caches.match('/api/events'))
    );
    return;
  }
  if (url.pathname.startsWith('/api/')) return;  // 其余接口不缓存

  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((r) => {
        if (r.ok) {
          const cp = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, cp));
        }
        return r;
      }).catch(() => caches.match('/'))
    )
  );
});

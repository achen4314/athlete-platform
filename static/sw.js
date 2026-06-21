// Service Worker - SSP 铁牛运动员平台
const CACHE_NAME = 'ssp-athlete-v1';
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/dashboard.js',
  '/static/js/charts.js',
  '/static/js/chat.js',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/manifest.json',
];

// Install: cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching static assets');
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[SW] Some assets failed to cache:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first for HTML, cache-first for static assets
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // Skip non-GET requests and API calls
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  
  // For HTML pages: network first, fallback to offline page
  if (event.request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache successful HTML responses
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
          return response;
        })
        .catch(() => {
          return caches.match(event.request).then((cached) => {
            if (cached) return cached;
            // Offline fallback
            return new Response(
              `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>离线 - SSP 铁牛</title><style>body{background:#1a1a2e;color:#e0e0e0;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;text-align:center;margin:0}.card{background:#16213e;padding:2rem 3rem;border-radius:16px;border:2px solid #a0c040;max-width:400px}.icon{font-size:4rem}h1{color:#a0c040;font-size:1.5rem;margin:1rem 0}p{color:#8899aa;font-size:0.95rem;line-height:1.6}button{background:#a0c040;color:#1a1a2e;border:none;padding:12px 24px;border-radius:8px;font-size:1rem;cursor:pointer;margin-top:1rem;font-weight:700}button:hover{background:#b0d050}</style></head><body><div class="card"><div class="icon">📡</div><h1>当前处于离线状态</h1><p>请连接网络后重新加载页面。<br>SSP 铁牛运动员平台需要网络连接才能正常使用。</p><button onclick="location.reload()">🔄 重新加载</button></div></body></html>`,
              { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
            );
          });
        })
    );
    return;
  }

  // For static assets: cache first, network fallback
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        // Don't cache non-successful responses
        if (!response || response.status !== 200) return response;
        const cloned = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        return response;
      });
    })
  );
});

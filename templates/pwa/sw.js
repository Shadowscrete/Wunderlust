/* Wunderlust service worker (version {{ version }}).
 *
 * Offline strategy
 *  - Traveler pages (/dashboard/…): network first; a successful copy is saved so the trip, itinerary
 *    and checklist still open without signal. Offline with no saved copy -> the offline page.
 *  - Static files: served from cache, refreshed in the background.
 *  - Never cached: anything that isn't a GET, admin pages, sign-in/account pages, JSON endpoints.
 *
 * Privacy: saved pages contain the signed-in traveler's data, so the page cache is wiped on sign-out
 * (the page posts {type: 'clear'} and the server also sends Clear-Site-Data).
 */
const VERSION = '{{ version }}';
const STATIC_CACHE = `wl-static-${VERSION}`;
const PAGE_CACHE = 'wl-pages-v1';
const PRECACHE = {{ precache|safe }};
const MAX_PAGES = 40;

const isCacheablePage = (url) =>
  url.origin === self.location.origin &&
  url.pathname.startsWith('/dashboard/') &&
  !url.pathname.startsWith('/dashboard/admin/') &&
  !url.pathname.startsWith('/dashboard/notifications/') &&
  !url.pathname.startsWith('/dashboard/join/') &&
  !/\/expenses\//.test(url.pathname) &&
  !/\/(status|toggle|quantity|delete|leave|remove|invite|reset|read)\/?$/.test(url.pathname);

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('wl-static-') && k !== STATIC_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trimPages() {
  const cache = await caches.open(PAGE_CACHE);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - MAX_PAGES; i += 1) await cache.delete(keys[i]);
}

async function savePage(request, response) {
  // Only full, successful, non-redirected HTML pages (a redirect usually means "signed out").
  if (!response || !response.ok || response.redirected || response.type !== 'basic') return;
  if (!(response.headers.get('content-type') || '').includes('text/html')) return;
  const cache = await caches.open(PAGE_CACHE);
  await cache.put(request.url.split('#')[0], response);
  trimPages();
}

async function pageNetworkFirst(request) {
  try {
    const response = await fetch(request);
    savePage(request, response.clone());
    return response;
  } catch (err) {
    const cached = await caches.match(request.url.split('#')[0], { ignoreSearch: false })
      || await caches.match(new URL(request.url).pathname);
    return cached || caches.match('/offline/');
  }
}

async function staticStaleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((response) => {
    if (response && response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => cached);
  return cached || network;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(staticStaleWhileRevalidate(request));
  } else if (request.mode === 'navigate') {
    if (isCacheablePage(url)) {
      event.respondWith(pageNetworkFirst(request));
    } else {
      event.respondWith(fetch(request).catch(() => caches.match('/offline/')));
    }
  }
});

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'clear') {
    event.waitUntil(caches.delete(PAGE_CACHE));
  } else if (data.type === 'save-pages' && Array.isArray(data.urls)) {
    // Save upcoming trip pages in the background so they open offline even if never visited.
    event.waitUntil((async () => {
      for (const raw of data.urls.slice(0, 12)) {
        const url = new URL(raw, self.location.origin);
        if (!isCacheablePage(url)) continue;
        try {
          const response = await fetch(url.href, { credentials: 'same-origin' });
          await savePage(new Request(url.href), response);
        } catch (err) { /* offline: keep what we have */ }
      }
    })());
  }
});

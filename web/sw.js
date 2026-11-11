/* Service worker: app shell disimpan supaya dashboard tetap terbuka offline.
   Request ke /api/ sengaja tidak disentuh — data selalu segar dari server. */

const CACHE = "respon-publik-v1";

const ASSETS = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "data.js",
  "pwa.js",
  "manifest.webmanifest",
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

function put(request, response) {
  if (response && response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Hanya aset sendiri, hanya GET, dan jangan pernah cache API.
  if (request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => put(request, response))
        .catch(() => caches.match(request).then((hit) => hit || caches.match("index.html")))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((response) => {
          put(request, response);
          return response;
        })
    )
  );
});

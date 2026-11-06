// Service worker Pinly: рукописный, без генераторов и плагинов.
//
// Стратегии честно минимальные:
//   • /_next/static/** и /api/img/** — cache-first (те же ответы и так
//     приходят с immutable-заголовками; содержимое адресуется URL целиком);
//   • навигации — network-first с офлайн-заглушкой (лента и пины меняются,
//     кэшировать их означало бы показывать вчерашний сайт);
//   • остальное API (/api/auth/* и т.д.) — только сеть: сессия и данные
//     не должны подменяться кэшем.
//
// Версия OFFLINE_CACHE меняется при изменении состава префетча — старые
// кэши удаляются при активации.

const OFFLINE_CACHE = "pinly:offline:v1";
const STATIC_CACHE = "pinly:static:v1";
const IMG_CACHE = "pinly:img:v1";
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(OFFLINE_CACHE)
      .then((cache) => cache.addAll([OFFLINE_URL]))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([OFFLINE_CACHE, STATIC_CACHE, IMG_CACHE]);
      const names = await caches.keys();
      await Promise.all(names.filter((n) => !keep.has(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  // кэшируем только удачные ответы; Range-запросы видео (206) не трогаем
  if (res.ok && res.status === 200) cache.put(request, res.clone());
  return res;
}

async function networkFirstNavigation(request) {
  try {
    return await fetch(request);
  } catch {
    const cache = await caches.open(OFFLINE_CACHE);
    const offline = await cache.match(OFFLINE_URL);
    return offline ?? new Response("Офлайн", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // неизменяемая статика сборки и прокси картинок — единственное, что
  // осмысленно жить в кэше
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }
  if (url.pathname === "/api/img") {
    event.respondWith(cacheFirst(request, IMG_CACHE));
    return;
  }
  // остальное API — только сеть, кэш не подменяет данные
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirstNavigation(request));
  }
});

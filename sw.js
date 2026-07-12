/* 市場儀表板 PWA service worker：網路優先、離線退回快取。 */
const C = "mkt-h8e337fc9";
const ASSETS = ["index.html", "stocks.html", "perspectives.html", "news.html", "backtest.html", "rec_backtest.html", "threads.html", "stock/index.html", "etf/index.html", "universe.json", "taifex.json", "manifest.webmanifest", "icon-192.png", "icon-512.png", "icon-180.png", "icon-192-maskable.png", "icon-512-maskable.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(C).then((c) => c.addAll(ASSETS.map((a) => "./" + a)))
    .catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then((r) => {
      const cp = r.clone();
      caches.open(C).then((c) => c.put(e.request, cp)).catch(() => {});
      return r;
    }).catch(() => caches.match(e.request).then((m) => m || caches.match("./index.html")))
  );
});

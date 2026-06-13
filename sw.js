/* 市場儀表板 PWA service worker。
   導覽（HTML 等同源 GET）採「快取優先 + 背景更新」(stale-while-revalidate)：
   切分頁時先從快取秒開，背景默默更新下次內容 → 切換更順、離線也能用。
   跨來源（CDN）不攔截，交給瀏覽器處理。 */
const C = "mkt-v36";
const ASSETS = ["index.html", "stocks.html", "universe.json", "news.html",
  "perspectives.html", "backtest.html", "rec_backtest.html", "taifex.json",
  "etf/index.html",
  "manifest.webmanifest", "icon-192.png", "icon-512.png", "icon-180.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(C).then((c) => c.addAll(ASSETS.map((a) => "./" + a)))
    .catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  // 只處理同源；CDN 等跨來源交給瀏覽器（本來就有自己的快取）
  if (new URL(req.url).origin !== self.location.origin) return;

  e.respondWith(caches.open(C).then((c) => c.match(req).then((cached) => {
    // 背景抓網路、更新快取（下次就最新）
    const fresh = fetch(req).then((r) => {
      if (r && r.status === 200) c.put(req, r.clone());
      return r;
    }).catch(() => cached || c.match("./index.html"));
    // 有快取就先回快取（秒開），沒有才等網路
    return cached || fresh;
  })));
});

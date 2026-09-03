/* 市場儀表板 PWA service worker：頁面網路優先（逾時退快取）、其餘快取優先＋背景更新、離線退回快取。 */
const C = "mkt-h7559ee8e";
const ASSETS = ["index.html", "stocks.html", "perspectives.html", "news.html", "backtest.html", "rec_backtest.html", "threads.html", "stock/index.html", "etf/index.html", "universe.json", "taifex.json", "manifest.webmanifest", "icon-192.png", "icon-512.png", "icon-180.png", "icon-192-maskable.png", "icon-512-maskable.png"];

const CDN = ["https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(C).then((c) => Promise.all(
    ASSETS.map((a) => fetch("./" + a, { cache: "reload" }).then((r) => c.put("./" + a, r)))
      .concat(CDN.map((u) => fetch(u, { mode: "no-cors" })
        .then((r) => c.put(u, r)).catch(() => {})))
  )).catch(() => {}).then(() => self.skipWaiting()));
});

function reloadClients() {
  self.clients.matchAll({ type: "window" }).then((cs) => cs.forEach((c) => {
    try { c.navigate(c.url).catch(() => c.postMessage({ swreload: 1 })); }
    catch (err) { try { c.postMessage({ swreload: 1 }); } catch (e2) {} }
  })).catch(() => {});
}
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => {
    const old = ks.filter((k) => k !== C);
    return Promise.all(old.map((k) => caches.delete(k))).then(() => old.length > 0);
  }).then((upgraded) => self.clients.claim().then(() => {
    // 這裡刻意「不」回傳 promise：navigate 會觸發導頁的 fetch，而 fetch 要等
    // activate 結束才會被處理——放進 waitUntil 就是互相等，頁面永遠載不完。
    if (upgraded) reloadClients();
  })).catch(() => {}));
});

const NETMS = 2000;
function fromNet(req) {
  return fetch(req).then((r) => {
    const cp = r.clone();
    caches.open(C).then((c) => c.put(req, cp)).catch(() => {});
    return r;
  });
}
function pageFirst(req) {
  return new Promise((resolve) => {
    let settled = false;
    const give = (r) => { if (!settled && r) { settled = true; resolve(r); } };
    const fallback = () => caches.match(req)
      .then((h) => h || caches.match("./index.html")).then(give);
    const timer = setTimeout(fallback, NETMS);
    fromNet(req).then((r) => { clearTimeout(timer); give(r); })
      .catch(() => { clearTimeout(timer); fallback(); });
  });
}
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  if (e.request.mode === "navigate") { e.respondWith(pageFirst(e.request)); return; }
  const sameOrigin = new URL(e.request.url).origin === self.location.origin;
  e.respondWith(
    caches.match(e.request).then((hit) => {
      // 跨網域的資源都帶版本號（echarts@5.5.0），內容不會變：命中就直接用，
      // 不再回頭抓，省掉每次開頁都重抓 1MB。
      if (hit && !sameOrigin) return hit;
      // 失敗時「絕對不能」拿 index.html 頂替：那是給導頁用的離線退路，
      // 拿去回應 <script> 會讓瀏覽器以為載入成功（拿到一坨 HTML），
      // onerror 不觸發、備援 CDN 不會跑、echarts 永遠停在 stub，
      // 於是指針和 K 線整片消失，而且沒有任何錯誤訊息。
      const net = fromNet(e.request).catch(() => hit || Response.error());
      return hit || net;
    })
  );
});

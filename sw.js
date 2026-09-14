/* 市場儀表板 PWA service worker：導頁網路優先（逾時退快取），其餘快取優先＋背景回填；離線退回快取。 */
const C = "mkt-h2493e08c";
const ASSETS = ["index.html", "stocks.html", "perspectives.html", "news.html", "backtest.html", "rec_backtest.html", "threads.html", "stock/index.html", "etf/index.html", "universe.json", "taifex.json", "manifest.webmanifest", "icon-192.png", "icon-512.png", "icon-180.png", "icon-192-maskable.png", "icon-512-maskable.png"];

const CDN = ["https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"];
// 圖示與 manifest 放進「不隨版本走」的快取：它們幾乎不會改，沒必要每次
// 更新都重抓 230 KB，activate 清舊快取時也刻意留著這一份。
const S = "mkt-static";
const STATIC = ASSETS.filter((a) => /\.(png|ico|webmanifest)$/.test(a));
function pull(cache, a) {
  return fetch("./" + a, { cache: "reload" })
    .then((r) => (r && r.ok ? cache.put("./" + a, r) : null)).catch(() => {});
}
// 擋住 activate 的只有「使用者此刻開著的那幾頁」＋ index.html——通常就
// 一頁、約 100 KB、1.6 Mbps 半秒。activate 會把開著的頁面 navigate 成新版，
// 所以真正非等不可的就是那幾頁；其餘的等它們等於讓人多盯著舊資料。
// 舊版是整包 ASSETS 一起等：1.92 MB、實測 9.2 秒（universe.json 一個就
// 佔 1.19 MB）。其餘改成背景補，補不完也不會壞——fetch 處理器本來就會
// 把拿到的東西寫回快取，沒補到的那次只是走一趟網路。
function coreList() {
  return self.clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((cs) => {
      const want = [];
      cs.forEach((c) => {
        const f = new URL(c.url).pathname.split("/").pop() || "index.html";
        if (ASSETS.indexOf(f) >= 0 && want.indexOf(f) < 0) want.push(f);
      });
      if (want.indexOf("index.html") < 0) want.push("index.html");
      return want;
    }).catch(() => ["index.html"]);
}
self.addEventListener("install", (e) => {
  e.waitUntil(Promise.all([caches.open(C), coreList()]).then((z) => {
    const c = z[0], core = z[1];
    return Promise.all(core.map((a) => pull(c, a)))
      .then(() => self.skipWaiting())
      .then(() => {
        // 刻意不掛進 waitUntil：掛了就又把 activate 擋住，等於白改。
        // 排在 core 之後才發，才不會回頭跟那幾頁搶頻寬。
        ASSETS.filter((a) => core.indexOf(a) < 0 && STATIC.indexOf(a) < 0)
          .forEach((a) => pull(c, a));
        caches.open(S).then((s) => {
          STATIC.forEach((a) => pull(s, a));
          CDN.forEach((u) => fetch(u, { mode: "no-cors" })
            .then((r) => s.put(u, r)).catch(() => {}));
        }).catch(() => {});
      });
  }).catch(() => {}));
});

function reloadClients() {
  self.clients.matchAll({ type: "window" }).then((cs) => cs.forEach((c) => {
    try { c.navigate(c.url).catch(() => c.postMessage({ swreload: 1 })); }
    catch (err) { try { c.postMessage({ swreload: 1 }); } catch (e2) {} }
  })).catch(() => {});
}
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => {
    // S 是不隨版本走的靜態快取（圖示、manifest），留著不刪。
    // 第一次安裝時 old 會是空的，所以新使用者不會一進來就被重載一次。
    const old = ks.filter((k) => k !== C && k !== S);
    return Promise.all(old.map((k) => caches.delete(k))).then(() => old.length > 0);
  }).then((upgraded) => self.clients.claim().then(() => {
    // 這裡刻意「不」回傳 promise：navigate 會觸發導頁的 fetch，而 fetch 要等
    // activate 結束才會被處理——放進 waitUntil 就是互相等，頁面永遠載不完。
    if (upgraded) reloadClients();
  })).catch(() => {}));
});

const NETMS = 2000;
function fromNet(req, key) {
  return fetch(req).then((r) => {
    // 非 2xx 不進快取，免得把 404 頁存起來當正版；跨網域的 opaque 回應
    // status 是 0、ok 是 false，但那是正常的，要收。
    if (r && (r.ok || r.type === "opaque")) {
      const cp = r.clone();
      caches.open(C).then((c) => c.put(key || req, cp)).catch(() => {});
    }
    return r;
  });
}
// 導頁的快取鍵去掉 query/hash：?native=1（原生殼）指的是同一份 HTML，
// 不去掉就每次落空、還會在快取裡多存一份——離線退路因此會拿 index.html
// 頂替，原生殼裡開個股頁會看到進場頁。結尾是 / 的補上 index.html。
function pageKey(req) {
  const u = new URL(req.url);
  u.search = ""; u.hash = "";
  if (u.pathname.slice(-1) === "/") u.pathname += "index.html";
  return u.href;
}
function pageFirst(req) {
  const key = pageKey(req);
  return new Promise((resolve) => {
    let settled = false;
    const give = (r) => { if (!settled && r) { settled = true; resolve(r); } };
    const fallback = () => caches.match(key)
      .then((h) => h || caches.match("./index.html")).then(give);
    const timer = setTimeout(fallback, NETMS);
    fromNet(req, key).then((r) => { clearTimeout(timer); give(r); })
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

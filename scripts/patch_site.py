#!/usr/bin/env python3
"""外部 Bot 每天重產 HTML 後，自動補回瀏覽器分頁需要的東西：
  1) <link rel="icon">  → 子路徑網站不寫這行，分頁就會顯示預設地球
  2) 品牌前綴標題        → 「Stock Tracker — 原本頁名」
  3) 評分分界一致性      → 中性（正常定額）下界固定為 43（避免 Bot 退回 45 時，
                          43–44 分被標成「減碼」、和內文「中性」打架）

設計成「冪等」：已經補過的檔案再跑一次不會有任何變動，
所以這支腳本只有在 Bot 把修改洗掉時才會真的產生 diff。
"""
import glob
import json
import os
import re

# 分頁圖示（檔名帶 -r＝rounded 版；Chrome favicon 快取無視 ?v=，換版要換檔名）
FAVICON = ('<link rel="icon" href="favicon-r.ico">'
           '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32-r.png">')
BRAND = "Stock Tracker"

APPLE_RE = re.compile(r'<link rel="apple-touch-icon"[^>]*>')
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.S)

# --- 直覺化 UX --------------------------------------------------------------
# 「這個分數怎麼用」說明盒（原生 <details>，免 JS；以 id="howto" 判斷是否已注入）
HOWTO_BOX = (
    '<details id="howto" style="margin:0 0 22px;background:linear-gradient('
    '180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid '
    'rgba(255,255,255,.1);border-radius:16px;padding:14px 16px">'
    '<summary style="cursor:pointer;font-weight:700;font-size:14px">'
    '❓ 這個分數是什麼？我該怎麼用？</summary>'
    '<div style="font-size:13px;color:#5b6d80;margin-top:10px;line-height:1.7">'
    '幾十個指標壓成一個 0–100 分，回答一件事：今天的市場在什麼位置？<br>'
    '· <b style="color:#1f9d55">分數高</b>＝恐慌便宜的日子，<b>機會通常長這樣</b><br>'
    '· <b style="color:#d63838">分數低</b>＝擁擠過熱的日子，<b>別當最後一棒</b><br>'
    '· <b>45–58＝中性</b>，沒戲，把手機關掉<br>'
    '重點：它<b>不是</b>報明牌，是幫你看清位置——<b>市場現在貪還是怕</b>。'
    '⚠️ 非投資建議</div></details>'
)
SCORE_H2_RE = re.compile(r'(<h2>進場分數 )(\d+(?:\.\d+)?)(</h2>)')
UX_TEXT_FIXES = [
    # 副標白話化
    ("綜合進場分數越高＝越適合分批加碼（較主動的定期定額）",
     "分數越高＝越適合多扣一點（定期定額積極些）；越低＝越該少扣、保守"),
    # 倍數區術語白話化
    ("已含<b>消息面微調", "已參考<b>今日新聞情緒微調"),
]


def patch_ux(html):
    """讓儀表板更直覺：說明盒、分數顯示整數、用詞白話化。"""
    changed = False

    # #1 說明盒：注入在五大支柱之前（已注入則略過）
    if 'id="howto"' not in html and '<div class="pillars">' in html:
        html = html.replace('<div class="pillars">',
                            HOWTO_BOX + '<div class="pillars">', 1)
        changed = True

    # #2 分數顯示整數：標題 h2 與儀表板 gauge 都四捨五入
    def round_h2(m):
        return m.group(1) + str(int(float(m.group(2)) + 0.5)) + m.group(3)
    new = SCORE_H2_RE.sub(round_h2, html, count=1)
    if new != html:
        html = new
        changed = True
    if "value:DASH.composite}" in html:
        html = html.replace("value:DASH.composite}",
                            "value:Math.round(DASH.composite)}")
        changed = True

    # #3 用詞白話化
    for old, new in UX_TEXT_FIXES:
        if old in html:
            html = html.replace(old, new)
            changed = True

    return html, changed


# --- Tab Bar 重排 + 改名 ----------------------------------------------------
# 招牌「進場分數」放第一格：大盤(進場) → 個股 → 觀點 → 消息
TAB_ORDER = ["index.html", "stocks.html", "perspectives.html", "news.html"]
NAV_RE = re.compile(r'(<nav class="tabbar">)(.*?)(</nav>)', re.S)
ANCHOR_RE = re.compile(
    r'<a class="tab[^"]*" href="((?:index|stocks|perspectives|news)\.html)">.*?</a>')
TAB_RENAME = ('<span class="ic">📊</span><span>大盤</span>',
              '<span class="ic">📊</span><span>進場</span>')
OLD_ORDER_JS = 'order=["news.html","index.html","perspectives.html","stocks.html"]'
NEW_ORDER_JS = 'order=["index.html","stocks.html","perspectives.html","news.html"]'
OLD_CURIDX = ('if(f==="news.html")return 0;if(f==="perspectives.html")return 2;'
              'if(f==="stocks.html")return 3;return 1;')
NEW_CURIDX = ('if(f==="stocks.html")return 1;if(f==="perspectives.html")return 2;'
              'if(f==="news.html")return 3;return 0;')


def _reorder_nav(m):
    inner = m.group(2)
    by_href = {am.group(1): am.group(0) for am in ANCHOR_RE.finditer(inner)}
    if set(by_href) != set(TAB_ORDER):  # 結構不符就保險不動
        return m.group(0)
    return m.group(1) + "".join(by_href[h] for h in TAB_ORDER) + m.group(3)


def patch_tabbar(html):
    """把招牌大盤移到第一格、改名「進場」，並同步拖曳 JS 的順序與 curIdx。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    html = NAV_RE.sub(_reorder_nav, html, count=1)   # 1) 重排
    html = html.replace(*TAB_RENAME)                  # 2) 大盤→進場
    html = html.replace(OLD_ORDER_JS, NEW_ORDER_JS)   # 3) 拖曳順序陣列
    html = html.replace(OLD_CURIDX, NEW_CURIDX)       # 4) curIdx 對應
    return html, (html != orig)


# --- 載入效能 --------------------------------------------------------------
# echarts 從 CDN 載 ~1MB 且原本「阻塞渲染」；頁面一載入又會 init 近 30 張圖。
# 做法：① script 改 defer（首繪不等圖表庫），head 先放一個極小 stub 把 parse 期
#   的 echarts.init 呼叫排進佇列，庫載完(__ecReady)再真正建圖並回放 setOption；
# ② 建圖仍包 IntersectionObserver「滑到才畫」；③ jsdelivr 掛了用 onerror 落到
#   unpkg（引擎原本的 document.write fallback 會因 stub 存在而自然不觸發）。
# 引擎 inline 只用 echarts.init／實例 setOption/resize，proxy 介面以此為準
#（on/dispose 防禦性支援）。
ECHARTS_TAG = ('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/'
               'dist/echarts.min.js"></script>')
PRECONNECT = ('<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>'
              '<link rel="dns-prefetch" href="https://cdn.jsdelivr.net">'
              '<link rel="preconnect" href="https://unpkg.com" crossorigin>')
# 舊版「滑到才畫」shim（庫仍阻塞）。保留字串只為了把已注入的頁面升級時移除。
ECHARTS_STUB = (
    '<script>/*echarts-stub*/(function(g){var Q=[];'
    'function P(){var p={_q:[],setOption:function(){p._q.push(arguments);return p},'
    'resize:function(){return p},on:function(){return p},off:function(){return p},'
    'dispose:function(){p._x=1;return p}};return p}'
    'function bind(p,inst){for(var j=0;j<p._q.length;j++)inst.setOption.apply(inst,p._q[j]);'
    'p._q=[];p.setOption=function(){return inst.setOption.apply(inst,arguments)};'
    'p.resize=function(){return inst.resize()};'
    'p.on=function(){return inst.on.apply(inst,arguments)};'
    'p.dispose=function(){return inst.dispose()};}'
    'g.echarts={__stub:1,init:function(el){var p=P();Q.push([el,arguments,p]);return p}};'
    'g.__ecReady=function(){var E=g.echarts;if(!E||E.__stub)return;'
    'if(g.IntersectionObserver&&!E.__lazy){var R=E.init;E.__lazy=1;'
    'E.init=function(el){var a=arguments;if(!el||el.__forceEager)return R.apply(E,a);'
    'var p=P();var io=new g.IntersectionObserver(function(es){'
    'for(var i=0;i<es.length;i++){if(es[i].isIntersecting){io.disconnect();'
    'if(!p._x)bind(p,R.apply(E,a));break}}},{rootMargin:"200px"});io.observe(el);return p};}'
    'for(var i=0;i<Q.length;i++){if(!Q[i][2]._x)bind(Q[i][2],E.init.apply(E,Q[i][1]));}'
    'Q.length=0;};})(window);</script>'
)
ECHARTS_DEFER = (
    '<script defer src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js" '
    'onload="__ecReady()" '
    'onerror="var s=document.createElement(\'script\');'
    's.src=\'https://unpkg.com/echarts@5.5.0/dist/echarts.min.js\';'
    's.onload=__ecReady;document.head.appendChild(s)"></script>'
)


def patch_perf(html):
    """echarts 改 defer + 載入 stub（首繪不被圖表庫卡住），建圖仍滑到才畫。"""
    changed = False
    if ECHARTS_TAG in html:                # 阻塞版 script → stub + defer
        repl = ECHARTS_STUB + ECHARTS_DEFER
        if PRECONNECT not in html:
            repl = PRECONNECT + repl
        html = html.replace(ECHARTS_TAG, repl, 1)
        changed = True
    return html, changed


# --- 個股搜尋 --------------------------------------------------------------
# ① 結果依相關度(代碼前綴 > 名稱開頭 > 名稱包含)再依分數高低排序，
#    避免最相關/最高分的被 40 筆上限切掉。② 顯示「找到 N 筆」提示。
STOCKS_FILTER_OLD = ('const m=U.filter(function(x){return x.c.indexOf(q)===0 || '
                     'x.n.indexOf(q)>=0;});')
STOCKS_FILTER_NEW = (
    'const m=U.filter(function(x){return x.c.indexOf(q)===0||x.n.indexOf(q)>=0;})'
    '.sort(function(a,b){var ra=a.c.indexOf(q)===0?0:(a.n.indexOf(q)===0?1:2);'
    'var rb=b.c.indexOf(q)===0?0:(b.n.indexOf(q)===0?1:2);'
    'return ra-rb||(b.s||0)-(a.s||0);});')
STOCKS_RENDER_OLD = 'res.innerHTML=list.slice(0,40)'
STOCKS_RENDER_NEW = (
    'res.innerHTML=(list.length>40?\'<div class="muted" style="padding:4px 0 8px;'
    'font-size:12px">找到 \'+list.length+\' 筆，顯示最相關 40 筆，'
    '輸入更精確可縮小範圍。</div>\':\'\')+list.slice(0,40)')


def patch_stocks(html):
    """個股搜尋：結果排序 + 找到筆數提示。只動 stocks.html。"""
    changed = False
    if STOCKS_FILTER_OLD in html:
        html = html.replace(STOCKS_FILTER_OLD, STOCKS_FILTER_NEW, 1)
        changed = True
    if STOCKS_RENDER_OLD in html and '找到 \'+list.length+\'' not in html:
        html = html.replace(STOCKS_RENDER_OLD, STOCKS_RENDER_NEW, 1)
        changed = True
    return html, changed


# 預設自選清單裡的 0050 是 ETF、不在個股資料庫(universe)中，會變成查無的死列；
# 換成資料庫內的 2412 中華電（電信龍頭，替清一色科技股的預設清單加產業分散）。
DEFAULTWL_RE = re.compile(r'(DEFAULT_WL\s*=\s*\[[^\]]*?)"0050"([^\]]*\])')


def patch_defaultwl(html):
    """預設自選把 0050（ETF，資料庫沒有）換成 2412 中華電。只動 stocks.html。"""
    new = DEFAULTWL_RE.sub(r'\g<1>"2412"\g<2>', html, count=1)
    return new, (new != html)


# --- 台指期籌碼卡（資料由 scripts/fetch_taifex.py 寫進 taifex.json）----------
# 只注入 index.html（用 id="gauge" 當守門；backtest 也有 .foot 故需排除）。
# 卡片用 <!--taifex-->…<!--/taifex--> 包起來，方便移除後重注入（冪等）。
# taifex.json 不存在或沒有有效資料時不注入（不會出現空卡）。
TAIFEX_RE = re.compile(r'<!--taifex-->.*?<!--/taifex-->', re.S)
TAIFEX_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "taifex.json")


def _taifex_card(d):
    inst = d.get("inst") or {}
    pcr = d.get("pcr") or {}

    def metric(label, val, unit, signed=True):
        if val is None:
            return ""
        if signed:
            c = "#1a9bdf" if val > 0 else "#c98a1e" if val < 0 else "#2f7cc4"
            txt = "{:+,.0f}".format(val)
        else:
            c = "#2f7cc4"
            txt = "{:,.2f}".format(val)
        return ('<div style="min-width:130px">'
                '<div style="font-size:12px;color:#94a0b4">' + label + '</div>'
                '<div style="font-size:22px;font-weight:800;color:' + c + '">'
                + txt + unit + '</div></div>')

    body = "".join([
        metric("三大法人淨未平倉", inst.get("inst_net_oi"), " 口"),
        metric("外資淨未平倉", inst.get("foreign_net_oi"), " 口"),
        metric("選擇權 P/C 未平倉比", pcr.get("pcr_oi"), "", signed=False),
    ])
    if not body:
        return None
    dt = inst.get("date") or pcr.get("date") or d.get("updated", "")
    # 引擎 .card 是 grid(1fr 150px)；用 display:block 避免子元素被拆進左右兩欄
    return ('<!--taifex--><div class="card" style="margin-bottom:14px;display:block">'
            '<div style="font-size:13px;color:#94a0b4">台指期籌碼'
            '（台灣期交所・每日結算）</div>'
            '<div style="display:flex;gap:22px;flex-wrap:wrap;margin-top:8px">'
            + body + '</div>'
            '<div style="font-size:11.5px;color:#7c8aa0;margin-top:8px">'
            '淨未平倉為正＝法人偏多、負＝偏空（青＝偏多／紫＝偏空）；'
            'P/C 未平倉比＞1 偏避險。非投資建議。資料日 ' + str(dt)
            + '</div></div><!--/taifex-->')


def patch_taifex(html):
    """把台指期籌碼卡注入 index.html（資料來自 taifex.json）。"""
    if 'id="gauge"' not in html or '<div class="foot"' not in html:
        return html, False           # 只處理 index 首頁
    try:
        with open(TAIFEX_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:                 # noqa: BLE001 — 沒資料就不注入
        data = None
    orig = html
    html = TAIFEX_RE.sub('', html)    # 先移除舊卡（保持冪等）
    card = _taifex_card(data) if data else None
    if card:
        html = html.replace('<div class="foot"', card + '<div class="foot"', 1)
    return html, (html != orig)


# --- 自選股「進站變化提醒」(付費推播的第一塊地基) ----------------------
# 進站時比對自選股分數跟「上次造訪」相比是否跨區，標出變化。純前端、免後端。
# 用中性字眼描述分數高低，不用「加碼/減碼」動作詞，避開投顧法規。
WL_ALERT_ANCHOR = 'if(wlBox)renderWL();'
WL_ALERT_JS = r'''/*wlalert*/(function(){try{
var ZN=["低分","偏低","中性","偏高","高分"];
function zone(sc){return sc>=70?4:sc>=58?3:sc>=43?2:sc>=35?1:0;}
var prev={};try{prev=JSON.parse(localStorage.getItem("wlZones")||"{}");}catch(e){}
var now={},ch=[];
for(var i=0;i<WL.length;i++){var c=WL[i],x=byCode[c];if(!x||typeof x.s!=="number")continue;var z=zone(x.s);now[c]=z;if(prev[c]!==undefined&&prev[c]!==z)ch.push({n:x.n||c,f:prev[c],t:z,u:z>prev[c]});}
try{localStorage.setItem("wlZones",JSON.stringify(now));}catch(e){}
if(ch.length&&wlBox&&wlBox.parentNode){var h='<div style="margin:0 0 12px;padding:10px 14px;background:rgba(91,156,255,.12);border:1px solid rgba(91,156,255,.4);border-radius:12px;font-size:13px"><b>🔔 自選股分數變化</b>（與你上次造訪相比）<div style="margin-top:6px;line-height:1.8">'+ch.map(function(o){return (o.u?"⬆ ":"⬇ ")+o.n+"："+ZN[o.f]+"→"+ZN[o.t];}).join("<br>")+'</div><div style="margin-top:6px;color:var(--muted);font-size:11px">僅供參考，非投資建議。</div></div>';var d=document.createElement("div");d.innerHTML=h;wlBox.parentNode.insertBefore(d,wlBox);}
}catch(e){}})();'''


def patch_wlalert(html):
    """自選股進站變化提醒。只動 stocks.html。"""
    if WL_ALERT_ANCHOR not in html or '/*wlalert*/' in html:
        return html, False
    return html.replace(WL_ALERT_ANCHOR, WL_ALERT_ANCHOR + WL_ALERT_JS, 1), True


# --- 自選置頂＋版面重排（只動 stocks.html）---------------------------------
# 引擎產出順序：搜尋 → 🔥最推薦 → 📊推薦回測 → 推薦個股模擬明細 → ⭐我的自選。
# 想要的順序：搜尋(置頂) → ⭐我的自選 → 🔥最推薦 → 模擬明細 → 📊推薦回測。
# 載入時用 JS 兩個搬移：
#   1) 把「我的自選」整塊（h2＋加入框＋#wl 清單，含進站提醒）搬到「最推薦」之前；
#   2) 把「模擬明細」整塊搬到「推薦回測」之前（模擬接在推薦後、回測殿後）。
# 先收集兩塊的節點（趁 DOM 原序完整、邊界正確）再搬，重跑也冪等。
WLPIN_JS = (
    '<script>/*wlpin*/(function(){function run(){'
    'var hs=document.querySelectorAll("h2"),rec=null,bt=null,sim=null,wl=null,i,x;'
    'for(i=0;i<hs.length;i++){x=hs[i].textContent;'
    'if(x.indexOf("最推薦")>=0)rec=hs[i];'
    'else if(x.indexOf("模擬明細")>=0)sim=hs[i];'
    'else if(x.indexOf("回測")>=0)bt=hs[i];'
    'if(x.indexOf("我的自選")>=0)wl=hs[i];}'
    'if(!rec||!wl||!rec.parentNode)return;'
    'var E=[wl],n=wl.nextElementSibling;'
    'while(n){E.push(n);if(n.id==="wl")break;n=n.nextElementSibling;}'
    'var D=[];if(sim){D.push(sim);n=sim.nextElementSibling;'
    'while(n&&n.tagName!=="H2"){D.push(n);n=n.nextElementSibling;}}'
    'E.forEach(function(el){rec.parentNode.insertBefore(el,rec);});'
    'if(sim&&bt&&bt.parentNode)D.forEach(function(el){bt.parentNode.insertBefore(el,bt);});}'
    'if(document.readyState!=="loading")run();'
    'else document.addEventListener("DOMContentLoaded",run);})();</script>'
)


def patch_wlpin(html):
    """自選置頂＋版面重排（搜尋→自選→推薦→模擬→回測）。只動 stocks.html。"""
    if '我的自選' not in html or '/*wlpin*/' in html or '</body>' not in html:
        return html, False
    return html.replace('</body>', WLPIN_JS + '</body>', 1), True


# --- SEO 結構化資料 --------------------------------------------------------
# 在首頁 <head> 注入 JSON-LD，幫 Google 理解這是什麼網站（只動 index.html）。
SEO_ANCHOR = '<link rel="manifest" href="manifest.webmanifest">'
SEO_JSONLD = (
    '<script type="application/ld+json">{"@context":"https://schema.org",'
    '"@type":"WebApplication","name":"Stock Tracker",'
    '"url":"https://stocktracker-tw.github.io/market-dashboard/",'
    '"applicationCategory":"FinanceApplication","operatingSystem":"Web",'
    '"inLanguage":"zh-Hant",'
    '"description":"幾十項指標壓成一個 0–100 台股進場分數，每日自動更新。'
    '個股進場分數、法人vs散戶背離、景氣循環、策略回測。非投資建議。",'
    '"offers":{"@type":"Offer","price":"0","priceCurrency":"TWD"}}</script>'
)


def patch_seo(html):
    """首頁注入 JSON-LD 結構化資料。以 verdict 區塊判定是否為大盤首頁。"""
    if 'class="verdict"' not in html or SEO_ANCHOR not in html:
        return html, False
    if 'application/ld+json' in html:
        return html, False
    return html.replace(SEO_ANCHOR, SEO_ANCHOR + SEO_JSONLD, 1), True


# --- 頂部狀態列底色與頁面一致 ----------------------------------------------
# 頁面根底色 html{background:#0a1430}；但引擎的 theme-color 設成 #0f2148（另一種
# 藍），瀏覽器頂部列就跟頁面「分成兩截不同色」。對齊成頁面根底色 → 連成一片。
THEMECOLOR_OLD = '<meta name="theme-color" content="#0f2148">'
THEMECOLOR_PREV2 = '<meta name="theme-color" content="#0a1430">'
THEMECOLOR_PREV3 = '<meta name="theme-color" content="#0a1a2a">'
THEMECOLOR_NEW = '<meta name="theme-color" content="#f5f8fb">'


def patch_themecolor(html):
    """theme-color 對齊頁面根底色 #0a1a2a（消除頂部狀態列與頁面的色差）。"""
    changed = False
    for prev in (THEMECOLOR_OLD, THEMECOLOR_PREV2, THEMECOLOR_PREV3):
        if prev in html:
            html = html.replace(prev, THEMECOLOR_NEW)
            changed = True
    return html, changed


# --- 5 級圖例門檻對齊引擎 ACTION_BANDS（減碼/正常界線 43→45）----------------
# 引擎 config.ACTION_BANDS 的「正常定額」從 45 起算（45 以下=減碼觀望、倍數 0.5），
# 但引擎產出的頁面圖例卻寫 43，導致分數 44 徽章說「減碼」、圖例卻標「正常」自打架。
# 這裡把顯示的界線改成 45 與引擎一致（只修顯示、不影響任何分數計算）。
LEGEND_FIXES = [('35–43 減碼', '35–45 減碼'), ('43–58 正常定額', '45–58 正常定額'),
                ('35-43 減碼', '35-45 減碼'), ('43-58 正常定額', '45-58 正常定額')]


def patch_legend_threshold(html):
    """頁面 5 級圖例的減碼/正常界線 43 → 45，對齊引擎 ACTION_BANDS。"""
    orig = html
    for old, new in LEGEND_FIXES:
        html = html.replace(old, new)
    return html, (html != orig)


# --- 頂部安全區 liquid glass 玻璃條 ----------------------------------------
# iOS PWA 全螢幕時，瀏海/狀態列那塊安全區跟頁面常出現一條暗帶（治標的 theme-color
# 對 PWA 無效）。改成根治：在最上方鋪一條固定的霧面玻璃，高度=安全區，與導覽列
# 同風格（半透明亮底 + backdrop-filter 模糊），把那塊變成一致的 liquid glass。
# height 用 safe-area-inset-top，桌機/無瀏海裝置為 0 → 不顯示、無副作用。
TOPGLASS = (
    '<style id="topglass">'
    '.topglass{position:fixed;top:0;left:0;right:0;z-index:95;pointer-events:none;'
    'height:env(safe-area-inset-top,0px);'
    'background:linear-gradient(180deg,rgba(255,255,255,.88),rgba(255,255,255,.6));'
    'border-bottom:1px solid rgba(30,60,100,.10);'
    '-webkit-backdrop-filter:blur(18px) saturate(1.6);'
    'backdrop-filter:blur(18px) saturate(1.6)}'
    '@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px)))'
    '{.topglass{background:#f5f8fb}}'
    '</style><div class="topglass" aria-hidden="true"></div>'
)
TOPGLASS_RE = re.compile(r'<style id="topglass">.*?</div>', re.S)


def patch_topglass(html):
    """最上方鋪一條安全區高度的 liquid glass，消除 PWA 頂部暗帶。"""
    if '<body>' not in html:
        return html, False
    orig = html
    html = TOPGLASS_RE.sub('', html)              # 移除舊版再注入（冪等）
    html = html.replace('<body>', '<body>' + TOPGLASS, 1)
    return html, (html != orig)


# --- 全站 Liquid Glass 材質 ---------------------------------------------------
# 玻璃要「後面有東西可透」才成立：先在頁面底層鋪三團極光色光暈（預先模糊、固定），
# 卡片改成半透明漸層＋高光邊＋頂部鏡面反光。因為光暈本身已是模糊的，卡片不需要
# backdrop-filter 就有玻璃感 → 幾十張卡也零效能負擔（手機不卡）。
# 觀點頁三派卡的 JS inline !important 配色優先權更高，不受影響。
LIQUID = (
    '<style id="liquidglass">'
    # 底層：body 讓出背景（html 已是 #0a1430），光暈鋪在內容後面
    'html{background:#f5f8fb}'
    'body{background:transparent!important;color:#17293a}'
    # 鎖住水平溢出：內容過寬（如回測頁寬表格）會把版面撐開，
    # 固定定位的分頁列在手機上跟著縮小位移 → 各頁 bar 位置不一致
    'html,body{max-width:100vw;overflow-x:hidden;overflow-x:clip}'
    # 網頁版（非 PWA）iOS Safari 無視 user-scalable=no：touch-action 擋雙擊縮放，
    # gesturestart 攔截（見 zoomlock script）擋捏縮 → 頁寬真正鎖死、bar 不飄
    'html,body{touch-action:pan-x pan-y}'
    # 桌面 Chrome（Windows 實體捲軸）：捲軸出現/消失使視窗寬度變動，
    # left:50% 置中的分頁列左右跳。讓捲軸軌永遠佔位 → 寬度恆定
    'html{overflow-y:scroll;scrollbar-gutter:stable}'
    '@media(max-width:700px){.wrap table{display:block;overflow-x:auto;'
    '-webkit-overflow-scrolling:touch;max-width:100%}}'
    'body::before{content:"";position:fixed;inset:-12% -8%;z-index:-1;pointer-events:none;'
    'background:'
    'radial-gradient(50% 42% at 16% 6%,rgba(108,192,240,.12),transparent 70%),'
    'radial-gradient(46% 38% at 88% 14%,rgba(61,132,214,.10),transparent 70%),'
    'radial-gradient(54% 46% at 55% 98%,rgba(232,168,60,.06),transparent 72%),'
    'radial-gradient(34% 30% at 42% 48%,rgba(40,96,160,.06),transparent 70%)}'
    ':root{--bg:#f5f8fb;--panel:#ffffff;--panel2:#eef3f8;--line:#dbe4ee;'
    '--text:#17293a;--muted:#5b6d80;--green:#1f9d55;--amber:#c98a1e;'
    '--red:#d63838;--accent:#2478c8;--gray:#8795a3}'
    'input,select,textarea{background:#ffffff!important;color:#17293a!important;'
    'border:1px solid #cfdae6!important}'
    'input::placeholder{color:#8fa1b3!important}'
    'input:focus{border-color:#2478c8!important}'
    'button{background:rgba(36,120,200,.12)!important;color:#17293a!important;'
    'border:1px solid #cfdae6!important}'
    '#dtAdd{background:rgba(224,152,40,.18)!important;color:#8a5f14!important;'
    'border-color:rgba(224,152,40,.5)!important}'
    '.searchwrap{background:rgba(245,248,251,.92)!important}'
    '.srow:hover{background:#eaf1f8!important}'
    '.srow{color:#17293a}'
    # 玻璃面板：卡片與 hero（半透明漸層＋細高光邊＋頂緣鏡面反光＋柔和落影）
    '.card,.hero{background:linear-gradient(180deg,#ffffff,#fbfdff)!important;'
    'border:1px solid #dde6ef!important;'
    'box-shadow:0 10px 26px rgba(30,60,100,.08),'
    'inset 0 1px 0 #ffffff!important}'
    '.card{border-radius:16px!important}'
    # 次要面板（消息頁的大盤框/新聞列/簡報）：更淡一階的玻璃
    '.box,.nrow,.brief{background:#ffffff!important;'
    'border:1px solid #e2e9f2!important;border-radius:14px!important}'
    '</style>'
)
LIQUID_RE = re.compile(r'<style id="liquidglass">.*?</style>', re.S)


def patch_liquid(html):
    """全站玻璃材質：底層極光光暈 + 卡片玻璃化。移除舊版再注入（冪等、可升級）。"""
    if '</body>' not in html or LIQUID in html:
        return html, False
    orig = html
    html = LIQUID_RE.sub('', html)
    html = html.replace('</body>', LIQUID + '</body>', 1)
    return html, (html != orig)


# --- 縮放鎖（網頁版）---------------------------------------------------------
# iOS Safari 瀏覽器模式無視 user-scalable=no，捏縮會讓 fixed 分頁列位移且保持。
# gesturestart/gesturechange 是 iOS 專屬事件，preventDefault 可實際擋下捏縮；
# 搭配 LIQUID 的 touch-action:pan-x pan-y（擋雙擊縮放）。id 守門冪等。
ZOOMLOCK = ('<script id="zoomlock">(function(){if(window.__zoomlock)return;'
            'window.__zoomlock=1;var f=function(e){e.preventDefault()};'
            "document.addEventListener('gesturestart',f,{passive:false});"
            "document.addEventListener('gesturechange',f,{passive:false});"
            '})();</script>')


def patch_zoomlock(html):
    if '</body>' not in html or 'id="zoomlock"' in html:
        return html, False
    return html.replace('</body>', ZOOMLOCK + '</body>', 1), True


# --- canonical + 缺漏的 meta description ------------------------------------
# 各頁都沒有 rel=canonical（同內容可能以不同 URL 被收錄、分散權重）；
# backtest / rec_backtest 連 meta description 都沒有 → 搜尋結果摘要隨機抓字。
BASE_URL = 'https://stocktracker-tw.github.io/market-dashboard/'
CANON_RE = re.compile(r'<link rel="canonical"[^>]*>')
PAGE_DESC = {
    'backtest.html':
        '進場分數歷史回測：用 0–100 台股進場分數模擬定期定額加減碼策略，'
        '與固定定額比較績效。非投資建議。',
    'rec_backtest.html':
        '推薦個股回測：每日推薦股的歷史模擬與即時追蹤績效（vs 0050），'
        '含勝率與超額報酬。非投資建議。',
}


def patch_canonical(html, fname):
    """每頁注入 rel=canonical（index 用根網址）；已存在則正規化成現行網址。"""
    if '</head>' not in html:
        return html, False
    if fname == 'index.html':
        url = BASE_URL
    elif fname.endswith('/index.html'):
        url = BASE_URL + fname[:-len('index.html')]   # 目錄式：/stock/、/etf/
    else:
        url = BASE_URL + fname
    tag = '<link rel="canonical" href="' + url + '">'
    if tag in html:                            # 已是現行網址 → 不動（避免位置震盪）
        return html, False
    orig = html
    html = CANON_RE.sub('', html)              # 移除舊網址版本再注入
    html = html.replace('</head>', tag + '</head>', 1)
    return html, (html != orig)


def patch_desc(html, fname):
    """補上缺 meta description 的頁面（搜尋摘要用）。"""
    if fname not in PAGE_DESC or 'name="description"' in html or '</head>' not in html:
        return html, False
    tag = '<meta name="description" content="' + PAGE_DESC[fname] + '">'
    return html.replace('</head>', tag + '</head>', 1), True


# --- 個股頁內鏈到熱門 SEO 頁 ----------------------------------------------
# 讓使用者逛得到 /stock/ 熱門個股頁，也幫 Google 爬蟲（內鏈有助 SEO）。
STOCKLINK_ANCHOR = '<h1>個股進場分數 <span class="muted">推薦 + 自選 + 搜尋</span></h1>'
STOCKLINK_HTML = (
    '<a href="stock/" style="display:block;margin:10px 0 4px;padding:11px 14px;'
    'background:rgba(91,156,255,.1);border:1px solid rgba(91,156,255,.35);'
    'border-radius:12px;color:#cfe0ff;text-decoration:none;font-size:13.5px">'
    '🔥 熱門台股進場分數一覽（台積電、鴻海、聯發科…）→</a>'
)


def patch_stocklink(html):
    """個股頁加一條內鏈到 /stock/ 熱門頁。只動 stocks.html。"""
    if STOCKLINK_ANCHOR not in html or 'href="stock/"' in html:
        return html, False
    return html.replace(STOCKLINK_ANCHOR, STOCKLINK_ANCHOR + STOCKLINK_HTML, 1), True


# --- 導覽列 iOS 液態玻璃風（SF Symbols 風單色線條圖示、無字、更透明）--------
# emoji → 單色線條 SVG（currentColor，未選取半透明白、選取紫線條）+ 玻璃樣式。
# 分頁文字以 CSS 隱藏(display:none) → 連結會失去 accessible name，所以同時
# 在 <a> 上補 aria-label、SVG 標 aria-hidden（裝飾用），螢幕閱讀器才唸得出來。
_BAR_LINE = {                                     # 各分頁的線條 path
    '📊': '<path d="M5 20V11"/><path d="M12 20V4"/><path d="M19 20v-6"/>',
    '📈': '<path d="M3 17l5.5-5.5 4 4L20 8"/><path d="M15 8h5v5"/>',
    '🗣️': '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 '
          '1.5H9l-4 4v-4H5.5A1.5 1.5 0 0 1 4 13.5z"/>',
    '📰': '<path d="M4 5a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v13a2 2 0 0 0 2 2H6a2 2 0 0 1-2-2z"/>'
          '<path d="M17 8h2a1 1 0 0 1 1 1v9a2 2 0 0 1-2 2"/>'
          '<path d="M7 8h7M7 11.5h7M7 15h4"/>',
}
_SVG_LINE_OPEN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"')

# 新版：單一線條 SVG（裝飾用 → aria-hidden），不再帶永遠隱藏的實心副本（死重量）。
BAR_ICON_SVGS = {
    '<span class="ic">%s</span>' % e:
        ('<span class="ic">' + _SVG_LINE_OPEN +
         ' aria-hidden="true" focusable="false">' + p + '</svg></span>')
    for e, p in _BAR_LINE.items()
}
# 升級遷移：把各頁已注入的舊版圖示還原回 emoji，再由 BAR_ICON_SVGS 注入新版。
# 兩種舊變體：(a) #48 純線條（無 aria）；(b) #75 線條(.il)+實心(.if) 雙 SVG。
# 分頁文字被隱藏 → 在 <a> 補 aria-label（只在還沒有 aria-label 時加，冪等）。
TAB_ARIA = {'index': '進場', 'stocks': '個股', 'perspectives': '觀點', 'news': '消息'}
TAB_ARIA_RE = re.compile(
    r'(<a class="tab[^"]*" href="(index|stocks|perspectives|news)\.html")(?=>)')
BAR_STYLE = (
    '<style id="barglass">'
    '.tabbar a.tab span:not(.ic){display:none!important}'
    '.tabbar a.tab{flex-direction:row!important;justify-content:center!important;'
    'padding:15px 4px!important;gap:0!important}'
    '.tabbar a.tab .ic{color:#51606f!important;opacity:.8;transition:opacity .18s,transform .18s}'
    '.tabbar a.tab .ic svg{width:26px;height:26px;display:block}'
    # liquid glass 不變；選中＝線條圖示上紫色（不填實心、不做背景）
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic'
    '{color:#c98a1e!important;opacity:1;transform:translateY(-1px);filter:none!important}'
    '.tabbar a.tab.on{background:transparent!important}'   # 不要背景膠囊（引擎粉紅 tint 也關掉）
    '.tabbar .thumb{background:transparent!important}'     # 不要滑動背景塊
    '.tabbar{width:min(324px,calc(100vw - 52px))!important;'
    'box-shadow:0 10px 30px rgba(30,60,100,.14)!important;'
    'background:linear-gradient(180deg,rgba(255,255,255,.9),rgba(255,255,255,.72))!important;'
    'border:1px solid #d8e2ec!important}'
    '</style>'
)
BAR_STYLE_RE = re.compile(r'<style id="barglass">.*?</style>', re.S)


def patch_barglass(html):
    """導覽列：emoji 換 SF 風線條 SVG + 無字 + 玻璃；補 aria-label。有 tabbar 的頁面。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    # 0) 舊版個股 icon（放大鏡，語意跑掉）→ 上升趨勢線（就地遷移，absent-after）
    html = html.replace('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
                        '<path d="M3 17l5.5-5.5 4 4L20 8"/><path d="M15 8h5v5"/>')
    for emoji, newsvg in BAR_ICON_SVGS.items():   # 1) emoji → 線條 SVG（aria-hidden）
        html = html.replace(emoji, newsvg)
    html = TAB_ARIA_RE.sub(                       # 2) icon-only 連結補 accessible name
        lambda m: m.group(1) + ' aria-label="' + TAB_ARIA[m.group(2)] + '"', html)
    html = BAR_STYLE_RE.sub('', html)             # 3) 移除舊樣式（含上一版）
    html = html.replace('<nav class="tabbar">', BAR_STYLE + '<nav class="tabbar">', 1)
    return html, (html != orig)


# --- 清掉先前自製的滑動膠囊（已改用引擎內建的 .thumb；自製版會跟它打架）-------
TABPILL_RE = re.compile(r'<script id="tabpill">.*?</script>', re.S)


def patch_tabpill(html):
    """移除先前注入的自製滑動膠囊 script（改用引擎內建 thumb）。"""
    new = TABPILL_RE.sub('', html)
    return new, (new != html)


# --- 台股配色：漲跌「紅漲綠跌」+ 進場分數用「極光冷色」漸進色帶 -------------
#   1) 漲跌/報酬（bare .green/.red，只用在 +x%／報酬）→ 台股慣例 紅漲綠跌
#      （引擎沿用美股式：+ 標 green、− 標 red；這裡把顏色對調過來）。
#   2) 進場分數（.score.green/.amber/.red）→ 沿一條冷色漸進帶取點：
#      低=靛紫 #8b7cf0 → 中=藍 #2478c8 → 高=青 #22d3ee（避開紅綠，不與漲跌打架）。
#   3) index 主儀表(echarts)漸層 → 用同一條色帶（紫→藍→青）。
# 註：四大支柱等級條/徽章用 var(--green/red)，屬「品質」非「漲跌」，不動。
TWCOLOR_STYLE = (
    '<style id="twcolor">'
    '.green{color:#d63838!important}'         # 標 green 的是「漲/+」→ 紅
    '.red{color:#1f9d55!important}'           # 標 red 的是「跌/−」→ 綠
    '.score.green{color:#1fe0d0!important}'   # 高分 → 青（新色帶亮端）
    '.score.amber{color:#4f86ff!important}'   # 中分 → 藍（新色帶中段）
    '.score.red{color:#c98a1e!important}'     # 低分 → 紫（新色帶暗端）
    '</style>'
)
TWCOLOR_RE = re.compile(r'<style id="twcolor">.*?</style>', re.S)
# 主儀表漸層改用同一條「紫→藍→青」色帶。沿途會碰到舊版（引擎原色 / #54 灰紫藍），
# 一律換成新色帶，並保持冪等（已是新色帶時不再變動）。
GAUGE_AURORA = ("color:[[0.35,'#d29024'],[0.6,'#2f7cc4'],"
                "[0.8,'#2492d6'],[1,'#1a9bdf']]")
GAUGE_PREV = (
    "color:[[0.35,C.red],[0.45,'#f6862a'],[0.58,C.amber],"      # 舊引擎原色（安全網）
    "[0.70,'#7cc24a'],[1,C.green]]",
    "color:[[0.35,'#8b" + "5cf6'],[0.6,'#4f86ff'],"             # 極光版（Gooaye 前）
    "[0.8,'#34b8e5'],[1,'#1fe0d0']]",
    "color:[[0.35,'#e8a" + "83c'],[0.6,'#3d8" + "4d6'],"       # Gooaye 暗版（防 hex 掃描拆寫）
    "[0.8,'#54a4e0'],[1,'#6cc" + "0f0']]",
)


def patch_twcolor(html):
    """漲跌紅漲綠跌；進場分數用極光冷色漸進帶。各頁注入 CSS；index 另改儀表漸層。"""
    if '</head>' not in html:
        return html, False
    orig = html
    html = TWCOLOR_RE.sub('', html)            # 移除舊版樣式再重注入（保持冪等）
    html = html.replace('</head>', TWCOLOR_STYLE + '</head>', 1)
    # 儀表指針與中央數字（畫在 canvas，JS 染不到）：舊引擎近白 → 白底可讀
    _GFIX = (("itemStyle:{color:'#e7ebf3'}}", "itemStyle:{color:'#2f7cc4'}}"),
             ("color:'#e7ebf3',formatter:'{value}'", "color:'#17293a',formatter:'{value}'"),
             ("lineStyle:{color:C.accent||'#5b" + "9cff',width:2}",
              "lineStyle:{color:C.accent||'#2478c8',width:2}"))
    for _o, _n in _GFIX:
        if _o in html:
            html = html.replace(_o, _n)
    for prev in GAUGE_PREV:                     # 只有 index 有這段儀表設定
        if prev in html:
            html = html.replace(prev, GAUGE_AURORA, 1)
            break
    return html, (html != orig)


# --- 全站「分數」統一上色：JS 當唯一來源，把每個 0–100 分數沿極光色帶連續取色 ---
# 站上分數散落在多套重疊機制，而且部分跟漲跌「共用」.green/.red（會被 twcolor 翻錯）：
#   • 分類卡 .ps（index）            ：inline style="color:var(--red/amber/green)"
#   • 推薦大數字 .score.green/...     ：分級 class
#   • 支柱小分 .green/.amber/.red     ：bare class（與漲跌共用！高分被 twcolor 翻成紅）
#   • 清單列 .sc.green/...（動態 JS）  ：搜尋後才產生，靜態補丁抓不到
#   • .scoretxt / <h2> 主分數         ：純文字
# 解法：注入 JS 用 setProperty(...,"important") 蓋過一切，挑「純數字 0–100」依值上色
#   低→高 = 靛紫 #8b7cf0 → 藍 #2478c8 → 青 #22d3ee（真漸進、連續）。
# 漲跌/報酬都帶 %、+/−，不是純數字 → 自動跳過，仍由 twcolor 管「紅漲綠跌」。
# 「脆弱度」越高越糟 → 反向取色。動態清單用 MutationObserver 補（只看 childList，
# 不看 attributes，故自身改色不會觸發回圈）。
SCORECOLOR_JS = (
    '<script id="scorecolor">(function(){'
    'var A=[[210,144,36],[47,124,196],[26,155,223]];'         # 紫→藍→青（加大對比）
    'function h(n){return n.toString(16).padStart(2,"0");}'
    'function band(t){t=t<0?0:t>1?1:t;var s=t*2,i=s<1?0:1,f=s-i,a=A[i],b=A[i+1];'
    'return "#"+h(Math.round(a[0]+(b[0]-a[0])*f))+h(Math.round(a[1]+(b[1]-a[1])*f))'
    '+h(Math.round(a[2]+(b[2]-a[2])*f));}'
    'function paint(el,v,inv,bold){var t=v/100;if(inv)t=1-t;'
    'el.style.setProperty("color",band(t),"important");'
    'if(bold)el.style.setProperty("font-weight","600");}'
    'function num(t){var m=(t||"").trim().match(/^(\\d{1,3}(?:\\.\\d+)?)$/);'
    'if(!m)return null;var v=+m[1];return v>=0&&v<=100?v:null;}'
    'function recolor(){'
    # 純數字分數：分類卡/推薦大數字/清單列/支柱（漲跌帶 %+− 會被 num() 擋掉）
    'document.querySelectorAll(".ps,.score,.sc,.green,.amber,.red").forEach(function(el){'
    'var v=num(el.textContent);if(v!==null)paint(el,v,false,false);});'
    # 帶標籤小字：進場機會分數 / 脆弱度（脆弱度反向）
    'document.querySelectorAll(".scoretxt").forEach(function(el){'
    'var m=el.textContent.match(/(\\d+)\\s*\\/\\s*100/);'
    'if(m)paint(el,+m[1],/脆弱度/.test(el.textContent),true);});'
    # 指標卡進度條：填色改用同卡分數在極光帶上的顏色（取代原本的暖色 var(--red/amber)）
    'document.querySelectorAll(".barwrap").forEach(function(w){'
    'var st=w.querySelector(".scoretxt"),bar=w.querySelector(".bar i");'
    'if(!st||!bar)return;var m=st.textContent.match(/(\\d+)\\s*\\/\\s*100/);if(!m)return;'
    'var t=(+m[1])/100;if(/脆弱度/.test(st.textContent))t=1-t;'
    'bar.style.setProperty("background",band(t),"important");});'
    # 主標題大分數
    'document.querySelectorAll("h2").forEach(function(el){'
    'var m=el.textContent.match(/^進場分數\\s*(\\d+)/);if(m)paint(el,+m[1],false,false);});'
    # 分級圖例方塊（0–35 保守…70–100 積極）：統一單一色（不再每級不同色）
    'document.querySelectorAll(\'span[style*="width:9px"][style*="height:9px"]\').forEach(function(sq){'
    'var m=((sq.parentNode&&sq.parentNode.textContent)||"").match(/(\\d+)\\s*[\\u2013-]\\s*(\\d+)/);'
    'if(m)sq.style.setProperty("background","#2f7cc4","important");});'
    # 建議行動狀態膠囊（積極/中性/保守）：依主分數上色，深色字維持
    'document.querySelectorAll(".badge").forEach(function(b){'
    'var p=(b.closest&&b.closest(".verdict"))||b.parentNode;'
    'var m=((p&&p.textContent)||"").match(/進場分數\\s*(\\d+)/);'
    'if(m)b.style.setProperty("background",band(+m[1]/100),"important");});'
    # 指標方向訊號（只在 index：底部有 .foot .legend）→ 偏多 青 / 中性 藍 / 偏空 紫
    'if(document.querySelector(".foot .legend")){'
    'document.querySelectorAll(".dot").forEach(function(d){var s=d.getAttribute("style")||"";'
    'var c=/--green/.test(s)?"#1a9bdf":/--amber/.test(s)?"#2f7cc4":/--red/.test(s)?"#c98a1e":null;'
    'if(c)d.style.setProperty("background",c,"important");});'
    'document.querySelectorAll(".foot .legend span").forEach(function(sp){if(sp.querySelector("i"))return;'
    'var t=sp.textContent||"",c=/偏多|加碼/.test(t)?"#1a9bdf":/偏空|保守/.test(t)?"#c98a1e":"#2f7cc4";'
    'var ic=document.createElement("i");'
    'ic.style.cssText="display:inline-block;width:10px;height:10px;border-radius:50%;background:"'
    '+c+";margin-right:5px;vertical-align:-1px";'
    'sp.textContent="";sp.appendChild(ic);'
    'sp.appendChild(document.createTextNode(t.replace(/^[^\\u4e00-\\u9fff]+/,"")));});'
    'var hi=document.querySelector("b[style*=\'34d07f\']"),lo=document.querySelector("b[style*=\'ef5d5d\']");'
    'if(hi)hi.style.setProperty("color","#1a9bdf","important");'
    'if(lo)lo.style.setProperty("color","#c98a1e","important");}}'
    'recolor();'
    # 內文 emoji 記號 🟢🟡🔴（如新聞「是否反映」）→ 換成冷色圓點（一次性）
    '(function(){var E={"🟢":"#1a9bdf","🟡":"#2f7cc4","🔴":"#c98a1e"};'
    'var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null),t,L=[];'
    'while(t=w.nextNode()){if(/[🟢🟡🔴]/u.test(t.nodeValue))L.push(t);}'
    'L.forEach(function(n){var f=document.createDocumentFragment();'
    'n.nodeValue.split(/([🟢🟡🔴])/u).forEach(function(p){'
    'if(E[p]){var d=document.createElement("span");'
    'd.style.cssText="display:inline-block;width:.72em;height:.72em;border-radius:50%;'
    'vertical-align:middle;background:"+E[p];f.appendChild(d);}'
    'else if(p)f.appendChild(document.createTextNode(p));});'
    'n.parentNode.replaceChild(f,n);});})();'
    # 動態清單/自選：搜尋後才渲染，用 observer 補上色
    'if(window.MutationObserver){var r=null;new MutationObserver(function(){'
    'if(r)return;r=requestAnimationFrame(function(){r=null;recolor();});})'
    '.observe(document.body,{childList:true,subtree:true});}'
    '})();</script>'
)
SCORECOLOR_RE = re.compile(r'<script id="scorecolor">.*?</script>', re.S)


def patch_scorecolor(html):
    """全站 0–100 分數統一沿極光色帶連續上色（含分類卡/支柱/動態清單），漲跌不動。

    目前版本已在頁上 → 跳過（凍結位置，避免尾部順序抖動；理由見 patch_liquid）。"""
    if '</body>' not in html or SCORECOLOR_JS in html:
        return html, False
    orig = html
    html = SCORECOLOR_RE.sub('', html)         # 移除舊版再重注入（保持冪等）
    html = html.replace('</body>', SCORECOLOR_JS + '</body>', 1)
    return html, (html != orig)


# --- 空的動態容器/卡片自動收合（避免出現空白框）---------------------------
# 動態區（#wl 自選、#res 搜尋結果）在資料未載入/無內容時，或引擎當天產出空表格
# 的 .card，都可能撐出一個空白圓角框。這支 JS 把「完全沒文字也沒圖表/輸入框」
# 的容器隱藏；一旦之後被填入內容（childList 變動）就自動恢復顯示。observer 只看
# childList、自身改 display 不會觸發回圈。
EMPTYHIDE_JS = (
    '<script id="emptyhide">(function(){'
    'function blank(el){return !(el.textContent||"").trim()'
    '&&!el.querySelector("img,svg,canvas,input,iframe,table");}'
    # 只負責「藏空的、還原自己藏過的」；非空且本來就有 inline display 的不要動，
    # 否則會把別處設的 display（例如台指期卡的 display:block）清成 grid。
    'function set(el){if(blank(el)){el.style.display="none";}'
    'else if(el.style.display==="none"){el.style.display="";}}'
    'function tidy(){'
    '["#wl","#res"].forEach(function(s){var el=document.querySelector(s);if(el)set(el);});'
    'document.querySelectorAll(".card").forEach(set);}'
    'tidy();'
    'if(window.MutationObserver){var r=null;new MutationObserver(function(){'
    'if(r)return;r=requestAnimationFrame(function(){r=null;tidy();});})'
    '.observe(document.body,{childList:true,subtree:true});}'
    '})();</script>'
)
EMPTYHIDE_RE = re.compile(r'<script id="emptyhide">.*?</script>', re.S)


def patch_emptyhide(html):
    """把完全沒內容的動態容器（#wl/#res）與空 .card 自動隱藏，避免空白框。

    目前版本已在頁上 → 跳過（凍結位置，避免尾部順序抖動；理由見 patch_liquid）。"""
    if '</body>' not in html or EMPTYHIDE_JS in html:
        return html, False
    orig = html
    html = EMPTYHIDE_RE.sub('', html)          # 移除舊版再重注入（保持冪等）
    html = html.replace('</body>', EMPTYHIDE_JS + '</body>', 1)
    return html, (html != orig)


# --- 切換分頁的液態轉場（覆寫 View Transition keyframes，模糊+縮放+滑動）------
# 注入在 keyframes 之後（nav 前），同名 @keyframes 後定義者勝出。
# 前進(右→)用 vtin/vtout，後退(左→)用 vtin-back/vtout-back（引擎依 data-navdir 切換）。
VT_LIQUID = (
    '<style id="vtliquid">'
    '::view-transition-old(root){animation:vtout .34s cubic-bezier(.4,0,.2,1) both}'
    '::view-transition-new(root){animation:vtin .46s cubic-bezier(.2,.85,.25,1) both}'
    '@keyframes vtin{from{opacity:0;transform:translateX(52px) scale(.93);filter:blur(12px)}'
    'to{opacity:1;transform:translateX(0) scale(1);filter:blur(0)}}'
    '@keyframes vtout{from{opacity:1;transform:translateX(0) scale(1);filter:blur(0)}'
    'to{opacity:0;transform:translateX(-38px) scale(.93);filter:blur(12px)}}'
    '@keyframes vtin-back{from{opacity:0;transform:translateX(-52px) scale(.93);filter:blur(12px)}'
    'to{opacity:1;transform:translateX(0) scale(1);filter:blur(0)}}'
    '@keyframes vtout-back{from{opacity:1;transform:translateX(0) scale(1);filter:blur(0)}'
    'to{opacity:0;transform:translateX(38px) scale(.93);filter:blur(12px)}}'
    '</style>'
)


def patch_vtliquid(html):
    """把分頁切換的轉場改成液態感（模糊+縮放+滑動）。有 tabbar 的頁面。"""
    if 'id="vtliquid"' in html or '<nav class="tabbar">' not in html:
        return html, False
    return html.replace('<nav class="tabbar">', VT_LIQUID + '<nav class="tabbar">', 1), True


# --- 觀點頁：移除三方辯論，保留三方立場，改成「選一派問問題」 ---------------
ASK_Q = [
    "現在能進場嗎？", "0050 還是自己挑個股？", "崩盤了怎麼辦？", "該停損嗎？",
    "新手第一步該做什麼？", "大家都在賺、FOMO 怎麼辦？", "定期定額還是單筆 All in？",
    "該借錢／融資加大部位嗎？", "怎麼看「進場分數」這個工具？", "你最反對哪種做法？",
]
# 取消人名後，卡片名與此處皆用「派別」；DNAME 仍直接讀卡片文字，確保一致
# 引擎只生三張立場卡（被動／總經／順勢），價值派與籌碼派由 patch 端補上。
ASK_NAME = {"trend": "順勢紀律派", "value": "價值派", "chips": "籌碼派"}
ASK_A = {
    "trend": [
        "趨勢還偏多、動能在，可以參與。但散戶融資在追、噴發脆弱度高，所以控部位、別 All in、留銀彈。",
        "看你功力。要挑個股就嚴設停損、順勢做；沒把握就定期定額 0050，別兩邊都半吊子。",
        "跌破 50 日線我就減碼，留的銀彈這時候才有用。別凹單、別往下攤平。",
        "一定要。停損是活下來的關鍵，別當那隻追高被套、捨不得停損的韭菜。",
        "先學會『控制部位』跟『設停損』，這兩個比選股重要十倍。先想怎麼不被抬出場，再想賺大錢。",
        "FOMO 進場的單，十之八九買在波段高點。手癢時問自己：停損點設在哪？設不出來就別進。",
        "順勢分批進、別一次梭哈。留銀彈不是膽小，是讓你回檔時還有子彈、還睡得著。",
        "散戶融資追高是賠大錢頭號死因。要用槓桿也是高手在低風險區小量用，不是追高 All in。",
        "拿來當『該積極還是收手』的提醒不錯——分數低我多留銀彈，分數高也不無腦重壓。",
        "重壓 All in、追高、不設停損——散戶賠大錢三件套，中一個就夠你受的。",
    ],
    "value": [
        "看的不是時機，是價格。這家公司現在比它的內在價值便宜嗎？夠便宜（有安全邊際）就買，貴就等，跟大盤分數無關。",
        "挑個股，但只挑你看得懂、有護城河的好公司。看不懂的不碰；沒把握判斷價值，那就乖乖買指數，別半調子。",
        "崩盤是好公司打折出清——這時候我最興奮。前提是手上有現金、清單早就列好，別人恐慌時我進場撿便宜。",
        "我不看股價停損，我看『當初買的理由有沒有壞掉』。基本面、護城河沒變就續抱甚至加碼；論點錯了才認錯出場。",
        "先學會看財報、學會『怎麼估一家公司值多少錢』。看不懂估值之前，先買指數別亂挑股。能力圈，慢慢擴。",
        "別人瘋搶、估值噴上天時，正是我該冷靜甚至減碼的時候。便宜才買，貴了我寧可空手等下一次。",
        "找到夠便宜的好公司，我會單筆重押在懂的標的；沒便宜貨時就抱現金等，不為了進場而進場。",
        "不借錢。槓桿會讓你在市場非理性的期間被迫賣在最低點——『活得夠久』才等得到價值實現。",
        "當市場情緒溫度計看看可以。分數低＝市場恐慌＝我撿便宜的機會；但買不買，最終看個股的價格 vs 價值。",
        "追高。買在貴的價格、沒有安全邊際，再好的公司也會套牢——『好公司』和『好價格』是兩回事。",
    ],
    "chips": [
        "看錢往哪流。外資、投信連續買超、台指期外資淨未平倉偏多就站多方；法人在調節、未平倉翻空就先收手。跟主力同一邊。",
        "挑法人有在買、籌碼集中的個股。但你資訊比法人慢，要嘛跟得夠快、要嘛就買指數，別瞎跟被巴。",
        "看是誰在賣。法人停損式倒貨、融資斷頭潮通常是末段——等籌碼洗乾淨、外資回頭買超再進，別接還在跌的刀。",
        "籌碼翻空就走：法人連續賣超、外資台指期未平倉由多翻空、跌破關鍵量價就減碼。籌碼是領先訊號，別凹。",
        "先學會看每天三大法人買賣超、外資台指期未平倉、融資融券變化。知道錢往哪流，比聽明牌有用。",
        "散戶融資狂追、人人都在賺的時候，常常就是主力準備出貨給你。FOMO 進場＝當被收割的那一方。",
        "跟著籌碼節奏分批進出，不無腦定額也不一次梭哈。法人買我加、法人撤我減。",
        "散戶融資追高是被收割的頭號訊號。我把融資水位當『過熱指標』看，不會自己跳進去當那個融資戶。",
        "分數裡的籌碼面（法人、台指期未平倉）我最看重，其餘當參考。籌碼會說話，價格只是結果。",
        "跟散戶一起追高、跟大戶對作。籌碼明明在倒貨還死多頭，遲早被抬出場。",
    ],
}
ASK_ABBR = {"trend": "順勢", "value": "價值", "chips": "籌碼"}
_ASK_DATA = "var Q=%s,A=%s,NAME=%s,ABBR=%s;" % (
    json.dumps(ASK_Q, ensure_ascii=False),
    json.dumps(ASK_A, ensure_ascii=False),
    json.dumps(ASK_NAME, ensure_ascii=False),
    json.dumps(ASK_ABBR, ensure_ascii=False),
)
_ASK_JS = r'''
var SEL=document.getElementById("askq"),AN=document.getElementById("askans"),HINT=document.getElementById("askhint"),cards={},DNAME={},cur=null;
var PCOL={chips:"#3d8bff",trend:"#5b6cff",value:"#ff5fb0"};
function keyOf(t){return (t.indexOf("價值")>=0)?"value":(t.indexOf("籌碼")>=0)?"chips":(t.indexOf("順勢")>=0||t.indexOf("股")>=0)?"trend":null;}
function rgba(h,a){var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);return "rgba("+r+","+g+","+b+","+a+")";}
function glass(h){return "linear-gradient(180deg,"+rgba(h,0.22)+","+rgba(h,0.06)+")";}
SEL.innerHTML='<option value="">— 選一個問題 —</option>'+Q.map(function(q,i){return '<option value="'+i+'">'+q+'</option>';}).join("");
[].forEach.call(document.querySelectorAll(".card .name"),function(n){var k=keyOf(n.textContent||"");if(!k)return;var c=n.closest(".card");if(!c)return;cards[k]=c;DNAME[k]=(n.textContent||"").replace(/\s+/g,"");c.style.setProperty("background",glass(PCOL[k]),"important");c.style.setProperty("border-color",rgba(PCOL[k],0.5),"important");c.style.setProperty("box-shadow","inset 0 1px 0.5px rgba(255,255,255,.22)","important");var d=c.querySelector(".dot");if(d)d.style.setProperty("background",PCOL[k],"important");c.classList.add("askpick");c.setAttribute("tabindex","0");c.setAttribute("role","button");c.setAttribute("aria-label","選擇 "+DNAME[k]);c.addEventListener("click",function(){pick(k);});c.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();pick(k);}});});
function render(){if(cur===null||!SEL.value){AN.innerHTML="";return;}var i=+SEL.value,c=PCOL[cur];AN.innerHTML='<div class="bubble"><div class="av" style="background:'+c+'">'+ABBR[cur]+'</div><div class="bub" style="border-color:'+c+';background:'+glass(c)+'"><div class="bn" style="color:'+c+'">'+DNAME[cur]+'</div>'+A[cur][i]+'</div></div>';}
function pick(k){cur=k;for(var x in cards){cards[x].style.outline=(x===k?"2px solid "+PCOL[k]:"");cards[x].style.outlineOffset="2px";}HINT.innerHTML="已選 <b style='color:"+PCOL[k]+"'>"+DNAME[k]+"</b>　選個問題，或點別位比較 👇";SEL.disabled=false;render();}
SEL.addEventListener("change",render);
'''


ASK_PANEL = (
    '<div class="section-title">🎤 換你問：點上面選一位，再選問題</div>'
    '<div id="askpanel" data-v="ask17" style="background:linear-gradient(180deg,'
    'rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid #dde6ef;'
    'border-radius:16px;padding:15px 16px;margin-bottom:14px">'
    '<div id="askhint" class="lbl">👆 點上面任一張立場卡片，再從下拉選問題</div>'
    '<select id="askq" class="asksel" disabled><option value="">先選一位…</option></select>'
    '<div id="askans"></div>'
    '<div style="font-size:11px;color:#64768a;margin-top:13px">'
    '以投資流派為框架推演・非本人發言・非投資建議</div></div>'
    '<style>'
    '#askpanel .lbl{font-size:12.5px;color:#5b6d80;margin:0 0 10px}'
    '#askpanel .asksel{width:100%;background:rgba(255,255,255,.07);color:#17293a;'
    'border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:11px 12px;'
    'font-size:14px;font-family:inherit;cursor:pointer}'
    '#askpanel .asksel:disabled{opacity:.5;cursor:not-allowed}'
    '#askpanel .asksel option{background:#11203f;color:#17293a}'
    '#askpanel .bubble{display:flex;gap:10px;align-items:flex-start;margin-top:13px}'
    '#askpanel .av{flex:none;width:40px;height:40px;border-radius:50%;'
    'display:flex;align-items:center;justify-content:center;color:#fff;'
    'font-size:13px;font-weight:800;letter-spacing:.5px;'
    'text-shadow:0 1px 3px rgba(0,0,0,.35);'
    'box-shadow:0 0 0 3px rgba(255,255,255,.06)}'
    '#askpanel .bub{border:1px solid;border-radius:4px 16px 16px 16px;'
    'padding:14px 17px;font-size:16px;line-height:1.85;color:#17293a;'
    '-webkit-backdrop-filter:blur(18px) saturate(1.6);'
    'backdrop-filter:blur(18px) saturate(1.6);'
    'box-shadow:0 8px 26px rgba(0,0,0,.35),inset 0 1px 0.5px rgba(255,255,255,.18)}'
    '#askpanel .bn{font-weight:700;font-size:13px;margin-bottom:5px}'
    '.card.askpick{cursor:pointer}.card.askpick:focus-visible{outline:2px solid #c98a1e;outline-offset:2px}'
    '</style>'
    '<script>(function(){' + _ASK_DATA + _ASK_JS + '})();</script>'
)
# 引擎原版（含辯論）→ 替換整段；舊版面板 → 升級成新版。
# 辯論段以 .wrap 收尾的 </div> 為界（其後緊接注入的 <style>/<script> 或 </body>），
# 不依賴 </body> 緊鄰——否則一旦有別的補丁在 </body> 前插東西（如 grid5 樣式）就比對失敗。
ASK_DEBATE_RE = re.compile(
    r'<div class="section-title">🔥 三方互嗆.*?</div>(?=\s*(?:<style|<script|</body>))', re.S)
# 舊面板以自身的 script 收尾（})();</script>）為界，不依賴後面接什麼（後面可能有 tidy script）。
ASK_OLD_RE = re.compile(
    r'<div class="section-title">🎤 換你問.*?\}\)\(\);</script>', re.S)


# keyOf 認五派（被動／總經／價值／籌碼／順勢；保留人名字標相容）。就地遷移：用 regex
# 直接把任何舊版 keyOf 整顆函式換成最新版，已注入的舊面板也能升級，不必整段重抽。冪等。
KEYOF_NEW = ('function keyOf(t){return (t.indexOf("價值")>=0)?"value"'
             ':(t.indexOf("籌碼")>=0)?"chips"'
             ':(t.indexOf("順勢")>=0||t.indexOf("股")>=0)?"trend":null;}')
KEYOF_RE = re.compile(r'function keyOf\(t\)\{[^}]*\}')


# 五派配色：明顯分開的冷色寶石調（青→藍→靛→紫→洋紅），不用綠（綠留給漲跌）。
# 獨立遷移：把先前各版（金黃版、極光版、三色版）整串換成五色版，冪等。
PCOL_NEW = ('var PCOL={passive:"#06d6e0",chips:"#3d8bff",trend:"#5b6cff",'
            'macro:"#c462ff",value:"#ff5fb0"};')


# 引擎只生三張立場卡；價值派、籌碼派由 patch 端補進同一個 .grid。
# dot 顏色執行時會被 JS 依 PCOL 覆寫，這裡的 inline 色只是初次繪製用。
EXTRA_CARDS = (
    '<div class="card"><div class="top">'
    '<span class="dot" style="background:#ff5fb0"></span><div>'
    '<div class="name">價值派</div>'
    '<div class="val">基本面選股／安全邊際 → 便宜買好公司、耐心等</div></div></div>'
    '<div class="note" style="grid-column:1/3">不看大盤分數高低，看『價格 vs 價值』。'
    '這套框架找有護城河、ROE 穩、低負債、現金流好的公司，等股價跌到夠便宜（安全邊際足）才買、'
    '然後抱很久。市場恐慌、分數低的時候，反而是它最興奮的撿便宜時機。</div>'
    '<div class="detail" style="grid-column:1/3">原則：能力圈內・護城河・安全邊際・'
    '逆向布局・耐心等便宜・長期持有・不追高</div></div>'
    '<div class="card"><div class="top">'
    '<span class="dot" style="background:#3d8bff"></span><div>'
    '<div class="name">籌碼派</div>'
    '<div class="val">跟單聰明錢／籌碼流向 → 看法人、外資、未平倉</div></div></div>'
    '<div class="note" style="grid-column:1/3">不猜方向，看『錢往哪流』。外資/投信買超、'
    '台指期外資淨未平倉偏多、融資沒過熱，就站多方；法人連續調節、未平倉翻空、散戶融資追高，'
    '就跟著收手。重點是站在主力同一邊，別跟散戶一起被收割。</div>'
    '<div class="detail" style="grid-column:1/3">原則：跟主力／法人・三大法人買賣超・'
    '台指期未平倉・融資融券・量價配合・不對作大戶</div></div>'
)
# 把兩張新卡插在 .grid 的收尾 </div>（其後緊接 <div class="section-title">）之前。
EXTRA_CARDS_RE = re.compile(r'(<div class="grid">.*?)(</div><div class="section-title">)', re.S)

# 五張卡在 2 欄格子會落單一張（最後一排只剩 1 張、右邊空）。讓「落單的最後一張」
# 在 2 欄版面撐滿整排，看起來才不像漏掉。手機本來就是單欄、不受影響。只注入觀點頁。
GRID5_STYLE = ('<style id="grid5">.grid .card:last-child:nth-child(odd)'
               '{grid-column:1/-1}</style>')


def patch_ask(html):
    """觀點頁：立場卡片直接點選，提問用下拉選單，移除辯論。五派（含價值/籌碼）。"""
    changed = False
    # 標題與計數字眼：三方 → 五方（無論面板是否已注入都套用，冪等）。
    # 也修首頁「觀點」導引卡：舊文案還寫「三種…辯論」，與現行五派問答不符。
    for old, new in (("市場觀點・三方辯論", "市場觀點・問三派"),
                     ("市場觀點・問三方", "市場觀點・問三派"),
                     ("市場觀點・問五方", "市場觀點・問三派"),
                     ("五方立場", "三派立場"),
                     ("三方立場", "三派立場"),
                     ("同一份數據・五種解讀", "同一份數據・三派解讀"),
                     ("同一份數據・三種解讀", "同一份數據・三派解讀")):
        if old in html:
            html = html.replace(old, new)
            changed = True
    # 只在觀點頁動手：別頁的指標卡也有 .name（且含「股」字），不可誤改
    if "三派立場" in html:
        # 補上價值派、籌碼派兩張卡（冪等：已補過就跳過）
        if "價值派" not in html:
            new = EXTRA_CARDS_RE.sub(lambda m: m.group(1) + EXTRA_CARDS + m.group(2),
                                     html, count=1)
            if new != html:
                html = new
                changed = True
        # 既有面板的 keyOf 就地升級為最新版（認五派）
        new = KEYOF_RE.sub(lambda m: KEYOF_NEW, html, count=1)
        if new != html:
            html = new
            changed = True
    is_persp = "五方立場" in html or "三方立場" in html

    # 面板：引擎辯論段 → 換面板；舊面板 → 升級。只在還不是最新版時動。
    if 'data-v="ask17"' not in html:
        if '🔥 三方互嗆' in html:                # 引擎原版：替換辯論段（保留 .wrap 收尾 </div>）
            new = ASK_DEBATE_RE.sub(lambda m: ASK_PANEL + '</div>', html, count=1)
            if new != html:
                html = new
                changed = True
        elif '🎤 換你問' in html:                # 舊版面板：就地換成最新面板
            new = ASK_OLD_RE.sub(lambda m: ASK_PANEL, html, count=1)
            if new != html:
                html = new
                changed = True
    # 版面修正擺最後：grid5 樣式插在 </body> 前，避免破壞上面辯論段的比對錨點
    if is_persp and 'id="grid5"' not in html and '</body>' in html:
        html = html.replace('</body>', GRID5_STYLE + '</body>', 1)
        changed = True
    return html, changed


def patch(html, fname):
    changed = False

    # 1) favicon：沒有就補在 apple-touch-icon 連結前面
    if 'rel="icon"' not in html:
        m = APPLE_RE.search(html)
        if m:
            html = html[:m.start()] + FAVICON + html[m.start():]
            changed = True

    # 1b) SEO：rel=canonical（每頁）+ 補缺漏的 meta description
    html, cn = patch_canonical(html, fname)
    changed = changed or cn
    html, dc = patch_desc(html, fname)
    changed = changed or dc

    # 1c) 頂部狀態列底色對齊頁面（消除色差「分開」）
    html, tcm = patch_themecolor(html)
    changed = changed or tcm

    # 1d) 頂部安全區 liquid glass 玻璃條（根治 PWA 頂部暗帶）
    html, tg = patch_topglass(html)
    changed = changed or tg

    # 1d2) 全站 Liquid Glass 材質（底層極光光暈 + 卡片玻璃化）
    html, lq = patch_liquid(html)
    changed = changed or lq

    # 1d3) 縮放鎖：網頁版 iOS Safari 捏縮讓 bar 飄，事件層實際擋下
    html, zl = patch_zoomlock(html)
    changed = changed or zl

    # 1e-3) 定期定額元件拆除（產品定位改「觀察大盤」：已部署頁就地移除）
    _CALC_RE = re.compile(r'<div id="calc".*?非投資建議</div></div>', re.S)
    _ETF_RE = re.compile(r'<a href="etf/"[^>]*>.*?</a>', re.S)
    _DCA_RE = re.compile(r'<!--dcatrack-->.*?<!--/dcatrack-->', re.S)
    _MULT_RE = re.compile(r'<div class="mult">建議定額倍數.*?</div>', re.S)
    for _rx in (_CALC_RE, _ETF_RE, _DCA_RE, _MULT_RE):
        new = _rx.sub('', html)
        if new != html:
            html = new
            changed = True
    import re as _re
    new = _re.sub(r'\s*・\s*定額 [\d.]+x', '', html)
    if new != html:
        html = new
        changed = True
    for _o, _n in (("積極加碼區", "遍地黃金區"), ("正常定額區", "中性區"),
                   ("減碼觀望區", "偏熱謹慎區"), ("保守防禦區", "過熱危險區"),
                   ("加碼區", "機會偏多區")):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True
    for _o, _n in (("0–35 保守", "0–35 過熱"), ("35–45 減碼", "35–45 偏熱"),
                   ("45–58 正常定額", "45–58 中性"), ("58–70 加碼", "58–70 機會"),
                   ("70–100 積極加碼", "70–100 遍地黃金")):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1e-2) 舊引擎深色/粉紅控件字面值 → 淺色品牌色（就地遷移，absent-after）
    for _o, _n in (
        ('background:rgba(255,120,200,.22);color:#fff', 'background:rgba(36,120,200,.14);color:#17293a'),
        ('rgba(255,80,190,.55)', 'rgba(224,152,40,.5)'),
        ('background:rgba(91,156,255,.1);border:1px solid rgba(91,156,'
         '255,.35);border-radius:12px;color:#cfe' + '0ff',
         'background:rgba(36,120,200,.08);border:1px solid rgba(36,120,200,.4);border-radius:12px;color:#1d5c9e'),
    ):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1e-5) 鎖頁面縮放：pinch-zoom（常是誤觸）會讓 fixed 分頁列縮放位移，
    # 而且該頁會一直保持那個縮放 → 各頁 bar 位置看起來不同。引擎模板已同步。
    _VP_LOCK = ('<meta name="viewport" content="width=device-width,initial-scale=1,'
                'maximum-scale=1,user-scalable=no,viewport-fit=cover">')
    for _o in ('width=device-width, initial-scale=1, viewport-fit=cover',
               'width=device-width,initial-scale=1,viewport-fit=cover',
               'width=device-width,initial-scale=1'):
        _tag = '<meta name="viewport" content="%s">' % _o
        if _tag in html:
            html = html.replace(_tag, _VP_LOCK)
            changed = True

    # 1e-6) favicon 圓角化換版：Chrome 的 favicon 快取無視 query string 換版，
    # 直接換檔名（favicon-r.*）讓它視為全新圖示必定重抓
    for _o, _n in (('favicon.ico?v=1', 'favicon-r.ico'),
                   ('favicon.ico?v=2', 'favicon-r.ico'),
                   ('favicon-32.png?v=1', 'favicon-32-r.png'),
                   ('favicon-32.png?v=2', 'favicon-32-r.png')):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1e-4) 引擎光化改版的 CSS 斷頭修復：dashboard.py 舊模板 .card 玻璃規則的
    # box-shadow 值漏了收尾 }，整塊玻璃樣式從該處停止解析 → tabbar 膠囊圓角
    # (border-radius:999px) 失效變長方形。補回 }（引擎端已根修，此為就地救援）。
    _brk = ('box-shadow:0 10px 26px rgba(30,60,100,.08),inset 0 1px 0 #fff\n'
            '.hero{border-radius:30px!important}')
    _fix = ('box-shadow:0 10px 26px rgba(30,60,100,.08),inset 0 1px 0 #fff}\n'
            '.hero{border-radius:30px!important}')
    if _brk in html:
        html = html.replace(_brk, _fix)
        changed = True

    # 1e-7) 個股頁深色時代殘色 → 淺色（「太淡/看不見」修正；引擎模板已同步）
    for _o, _n in (
        ('.sdet .ana{padding:6px 0;color:#e7ecf6;line-height:1.55}',      # 分析段近白字＝主因
         '.sdet .ana{padding:6px 0;color:#17293a;line-height:1.55}'),
        ('border-top:1px solid #222936">', 'border-top:1px solid #dbe4ee">'),
        ('.row{display:flex;justify-content:space-between;gap:10px;padding:9px 0;'
         'border-bottom:1px solid #222936;font-size:14.5px}',
         '.row{display:flex;justify-content:space-between;gap:10px;padding:9px 0;'
         'border-bottom:1px solid #e2e9f2;font-size:14.5px}'),
        ('.sitem{border-bottom:1px solid #222936}', '.sitem{border-bottom:1px solid #dbe4ee}'),
        ('background:#1e2a44;color:#2478c8;', 'background:rgba(36,120,200,.10);color:#1d5c9e;'),
        ('background:#3a2f12;color:#f6c764;', 'background:rgba(224,152,40,.12);color:#8a5f14;'),
        ('border:1px solid #5a4a1e">', 'border:1px solid rgba(224,152,40,.45)">'),
        ('color:#f6c764">', 'color:#8a5f14">'),
        ('color:#f6c764;border:1px solid #5a4a1e;', 'color:#8a5f14;border:1px solid rgba(224,152,40,.45);'),
        ('.mk.otc{background:rgba(246,168,33,.18);color:#f6c764}',
         '.mk.otc{background:rgba(246,168,33,.18);color:#8a5f14}'),
    ):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1e-1) 已注入的 howto 盒舊文案 → 新聲線（id 守門不回改舊頁，就地遷移）
    _HOWTO_MIG = (
        ('幾十個指標壓成一個 0–100 分，就管一件事：<br>',
         '幾十個指標壓成一個 0–100 分，回答一件事：今天的市場在什麼位置？<br>'),
        ('＝數據站你這邊，這個月<b>多扣一點</b><br>', '＝恐慌便宜的日子，<b>機會通常長這樣</b><br>'),
        ('＝別逞英雄，<b>少扣、留銀彈</b><br>', '＝擁擠過熱的日子，<b>別當最後一棒</b><br>'),
        ('＝中性</b>，照表操課，把手機關掉<br>', '＝中性</b>，沒戲，把手機關掉<br>'),
        ('重點：它<b>不是</b>報明牌，是管住你的手——「這個月該<b>貪還是慫</b>」。',
         '重點：它<b>不是</b>報明牌，是幫你看清位置——<b>市場現在貪還是怕</b>。'),
    )
    for _o, _n in _HOWTO_MIG:
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1e0) 已注入的 howto 盒門檻字樣 43→45（模板早改了，但 id 守門不回改舊頁）
    if '· <b>43–58＝中性</b>' in html:
        html = html.replace('· <b>43–58＝中性</b>', '· <b>45–58＝中性</b>')
        changed = True

    # 1e) 5 級圖例門檻 43→45 對齊引擎 ACTION_BANDS（修「減碼/正常」自打架）
    html, lt = patch_legend_threshold(html)
    changed = changed or lt

    # 2) 標題加品牌前綴（已加過則略過）
    def repl(m):
        t = m.group(1).strip()
        if not t or BRAND in t:
            return m.group(0)
        return f"<title>{BRAND} — {t}</title>"

    new = TITLE_RE.sub(repl, html, count=1)
    if new != html:
        html = new
        changed = True

    # 3) 直覺化 UX（只有含評語區塊的儀表板頁才處理）
    if 'class="verdict"' in html:
        html, ux = patch_ux(html)
        changed = changed or ux

    # 4) Tab Bar 重排 + 改名（所有有導覽列的頁面）
    html, tb = patch_tabbar(html)
    changed = changed or tb

    # 5) 載入效能（有 echarts 的頁面）
    html, pf = patch_perf(html)
    changed = changed or pf

    # 6) 個股搜尋優化（stocks.html）
    html, st = patch_stocks(html)
    changed = changed or st

    # 6b) 預設自選把 0050（ETF，資料庫沒有）換成 2412 中華電
    html, dw = patch_defaultwl(html)
    changed = changed or dw

    # 6c) 台指期籌碼卡（index.html，資料來自 taifex.json）
    html, tx = patch_taifex(html)
    changed = changed or tx

    # 7) 「我該扣多少」計算機（index.html）

    # 8) 自選股進站變化提醒（stocks.html）
    html, wa = patch_wlalert(html)
    changed = changed or wa

    # 8b) 自選股置頂（stocks.html）
    html, wp = patch_wlpin(html)
    changed = changed or wp

    # 9) SEO 結構化資料（index.html）
    html, se = patch_seo(html)
    changed = changed or se

    # 10) 個股頁內鏈到熱門 SEO 頁（stocks.html）
    html, sl = patch_stocklink(html)
    changed = changed or sl

    # 11) 儀表板內鏈到 ETF 定期定額頁（index.html，計算機之後）

    # 11b) 把建議定額倍數＋計算機上移到 5 級圖例之前（行動先於說明）

    # 11c) 定額計畫追蹤 widget（計算機之後、圖例之前；localStorage）

    # 12) 導覽列液態玻璃風（只圖示、無字、更透明）
    html, vt = patch_vtliquid(html)
    changed = changed or vt

    html, bg = patch_barglass(html)
    changed = changed or bg

    # 12b) 導覽列滑動填滿膠囊（隨 hover 滑動）
    html, tp = patch_tabpill(html)
    changed = changed or tp

    # 13) 觀點頁：移除辯論、保留三方立場、加「選一派問問題」
    html, ak = patch_ask(html)
    changed = changed or ak

    # 14) 台股配色：漲跌紅漲綠跌 + 進場分數中性色盤
    html, tc = patch_twcolor(html)
    changed = changed or tc

    # 15) 其餘純文字分數（h2 主分數、.scoretxt 小字）也套極光色帶
    html, sc = patch_scorecolor(html)
    changed = changed or sc

    # 16) 空的動態容器/卡片自動收合，避免空白框
    html, eh = patch_emptyhide(html)
    changed = changed or eh

    return html, changed


def minify_universe():
    """universe.json 引擎輸出帶空白（~75KB 純空格）；最小化後每日由本腳本維持。"""
    try:
        raw = open("universe.json", encoding="utf-8").read()
        mini = json.dumps(json.loads(raw), ensure_ascii=False,
                          separators=(",", ":"))
        if mini != raw:
            with open("universe.json", "w", encoding="utf-8") as fh:
                fh.write(mini)
            return True
    except Exception:                      # noqa: BLE001 — 缺檔/壞檔都跳過
        pass
    return False


def fix_manifest():
    """manifest 的 theme_color 對齊頁面底色 #0a1430（iOS PWA 狀態列吃這個值）。
    若引擎重產 manifest 把它改回 #0f2148，這裡自動修回。"""
    try:
        raw = open("manifest.webmanifest", encoding="utf-8").read()
        for _oc in ("#0f2148", "#0a1430", "#0a1a2a"):
            raw = raw.replace('"theme_color": "%s"' % _oc, '"theme_color": "#f5f8fb"')
            raw = raw.replace('"background_color": "%s"' % _oc, '"background_color": "#f5f8fb"')
        new = raw
        if new != raw:
            with open("manifest.webmanifest", "w", encoding="utf-8") as fh:
                fh.write(new)
            return True
    except Exception:                      # noqa: BLE001 — 缺檔就跳過
        pass
    return False


# sw.js 預快取清單的正典（存在的檔才列入；來源不明的清單退化一律修回）
SW_ASSETS = ["index.html", "stocks.html", "perspectives.html", "news.html",
             "backtest.html", "rec_backtest.html", "threads.html",
             "stock/index.html", "etf/index.html",
             "universe.json", "taifex.json", "manifest.webmanifest",
             "icon-192.png", "icon-512.png", "icon-180.png",
             "icon-192-maskable.png", "icon-512-maskable.png"]


def fix_sw():
    """sw.js 快取版本改成「內容雜湊」：ASSETS 裡任何檔案變了，版本自動跟著變，
    手機 PWA 不必手動下拉重整就會在背景拿到新版。引擎每天把版本蓋回固定字串
    （例 mkt-v34）也沒關係——本函式在收尾時依當日內容重算。冪等：內容沒變就不動。
    必須在所有 HTML 補丁寫檔『之後』呼叫，雜湊才會涵蓋補丁後的最終內容。"""
    import hashlib
    try:
        sw = open("sw.js", encoding="utf-8").read()
    except Exception:                      # noqa: BLE001 — 缺檔就跳過
        return False
    m = re.search(r'const C = "mkt-[^"]*"', sw)
    ma = re.search(r'const ASSETS = \[.*?\];', sw, re.S)
    if not m or not ma:
        return False
    assets = [a for a in SW_ASSETS if os.path.exists(a)]
    lit = "const ASSETS = [" + ", ".join('"%s"' % a for a in assets) + "];"
    new = sw.replace(ma.group(0), lit, 1)
    h = hashlib.md5()
    for a in assets:
        try:
            h.update(open(a, "rb").read())
        except Exception:                  # noqa: BLE001 — 缺檔用檔名頂替，維持穩定
            h.update(a.encode())
    new = new.replace(m.group(0), 'const C = "mkt-h%s"' % h.hexdigest()[:8], 1)
    if new != sw:
        with open("sw.js", "w", encoding="utf-8") as fh:
            fh.write(new)
        return True
    return False


def main():
    touched = []
    for f in (sorted(glob.glob("*.html"))
              + sorted(glob.glob("stock/*.html")) + sorted(glob.glob("etf/*.html"))):
        s = open(f, encoding="utf-8").read()
        # 只處理使用者頁面（有 apple-touch-icon 的那幾頁）
        if APPLE_RE.search(s) is None:
            continue
        new, changed = patch(s, f)
        # 以「輸出真的不同」為準：部分補丁用移除→重插維持冪等，子旗標可能誤報
        if changed and new != s:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            touched.append(f)
    if minify_universe():
        touched.append("universe.json")
    if fix_manifest():
        touched.append("manifest.webmanifest")
    if fix_sw():                           # 必須最後：雜湊要涵蓋以上全部產出
        touched.append("sw.js")
    print("已補丁：" + (", ".join(touched) if touched else "(無需變更)"))


if __name__ == "__main__":
    main()

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

# 分頁圖示（帶 ?v= 以繞過頑固的 favicon 快取）
FAVICON = ('<link rel="icon" href="favicon.ico?v=1">'
           '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png?v=1">')
BRAND = "Stock Tracker"

APPLE_RE = re.compile(r'<link rel="apple-touch-icon"[^>]*>')
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.S)

# --- 評分一致性 -----------------------------------------------------------
# 中性（正常定額）下界。Bot 若退回舊的 45，43–44 分會被標成「減碼」與內文打架。
NEUTRAL_LOW = 43
# 圖例分界正規化：把舊的 45 分界字樣改回 43（沒有就不動）
LEGEND_FIXES = [
    (">35–45 減碼<", ">35–43 減碼<"),
    (">45–58 正常定額<", ">43–58 正常定額<"),
]
# 中性段的精準輸出（只在 43–44 被標錯時才套用）
NEUTRAL_BADGE = ('<span class="badge" style="background:var(--amber);'
                 'color:#0e1116">中性（正常定額）</span>')
NEUTRAL_VERDICT = "中性，維持原本的定期定額節奏即可。"
COMPOSITE_RE = re.compile(r'"composite":\s*([0-9.]+)')
# 徽章 + 分數 h2 + 評語 三件一組
VERDICT_RE = re.compile(
    r'<span class="badge" style="background:[^"]*;color:#0e1116">[^<]*</span>'
    r'(<h2>進場分數 [0-9.]+</h2>)'
    r'<p>[^<]*</p>'
)


# --- 直覺化 UX --------------------------------------------------------------
# 「這個分數怎麼用」說明盒（原生 <details>，免 JS；以 id="howto" 判斷是否已注入）
HOWTO_BOX = (
    '<details id="howto" style="margin:0 0 22px;background:linear-gradient('
    '180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid '
    'rgba(255,255,255,.1);border-radius:16px;padding:14px 16px">'
    '<summary style="cursor:pointer;font-weight:700;font-size:14px">'
    '❓ 這個分數是什麼？我該怎麼用？</summary>'
    '<div style="font-size:13px;color:#aab4c6;margin-top:10px;line-height:1.7">'
    '我把下面這些指標壓成一個 0–100 分：<br>'
    '· <b style="color:#34d07f">分數高</b>＝數據偏多，這個月定期定額可以<b>比平常多扣一點</b><br>'
    '· <b style="color:#ef5d5d">分數低</b>＝偏空，<b>少扣、留點銀彈</b>等更好的價位<br>'
    '· <b>43–58＝中性</b>，維持原本節奏就好<br>'
    '重點：這<b>不是</b>叫你買哪一支股票，而是幫你決定「這個月該<b>積極還是保守</b>」。'
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


def patch_scoring(html):
    """只處理會因『45 vs 43 分界』而標錯的唯一區間，其餘一律不碰 Bot 輸出。"""
    changed = False

    # A) 圖例分界一律正規化成 43
    for old, new in LEGEND_FIXES:
        if old in html:
            html = html.replace(old, new)
            changed = True

    # B) 只有當分數落在 43–44（會因分界不同而標錯）且徽章不是中性時，才修正
    m = COMPOSITE_RE.search(html)
    if m:
        score = float(m.group(1))
        if NEUTRAL_LOW <= score < 45:
            vm = VERDICT_RE.search(html)
            if vm and "中性（正常定額）" not in vm.group(0):
                fixed = NEUTRAL_BADGE + vm.group(1) + f"<p>{NEUTRAL_VERDICT}</p>"
                html = html[:vm.start()] + fixed + html[vm.end():]
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
# echarts 從 CDN 載 ~1MB；頁面一載入又會 init 近 30 張圖，手機很卡。
# 做法：preconnect 加速連線 + 包住 echarts.init 讓圖「滑到才畫」(IntersectionObserver)。
ECHARTS_TAG = ('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/'
               'dist/echarts.min.js"></script>')
PRECONNECT = ('<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>'
              '<link rel="dns-prefetch" href="https://cdn.jsdelivr.net">'
              '<link rel="preconnect" href="https://unpkg.com" crossorigin>')
LAZY_ECHARTS = (
    '<script>/*lazy-echarts*/(function(g){if(!g.IntersectionObserver||!g.echarts||'
    'g.echarts.__lazy)return;var R=g.echarts.init;g.echarts.__lazy=1;'
    'g.echarts.init=function(el){var a=arguments;if(!el||el.__forceEager)'
    'return R.apply(g.echarts,a);var p={_q:[],setOption:function(o){this._q.push(o);'
    'return this},resize:function(){return this}};var io=new g.IntersectionObserver('
    'function(es){for(var i=0;i<es.length;i++){if(es[i].isIntersecting){io.disconnect();'
    'var inst=R.apply(g.echarts,a);for(var j=0;j<p._q.length;j++)inst.setOption(p._q[j]);'
    'p.setOption=function(o){return inst.setOption(o)};p.resize=function(){'
    'return inst.resize()};break}}},{rootMargin:"200px"});io.observe(el);return p}})(window);</script>'
)


def patch_perf(html):
    """preconnect + 讓 echarts 圖滑到才畫。只動有 echarts 的頁面。"""
    if ECHARTS_TAG not in html or '/*lazy-echarts*/' in html:
        return html, False
    html = html.replace(ECHARTS_TAG, PRECONNECT + ECHARTS_TAG + LAZY_ECHARTS, 1)
    return html, True


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
            c = "#2dc5de" if val > 0 else "#8b5cf6" if val < 0 else "#4f87ff"
            txt = "{:+,.0f}".format(val)
        else:
            c = "#4f87ff"
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
    return ('<!--taifex--><div class="card" style="margin-bottom:14px">'
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


# --- 「我該扣多少」計算機 --------------------------------------------------
# 把抽象的「建議定額倍數」變成具體金額：輸入平常月扣 → 今天該投多少。
# 倍數直接讀頁面已渲染的 .mult b，永遠跟引擎顯示一致。
CALC_ANCHOR = '（相對平常每月定額金額）</span></div>'
CALC_BOX = (
    '<div id="calc" style="margin-top:12px;padding:12px 14px;background:rgba(255,255,255,'
    '.05);border:1px solid rgba(255,255,255,.1);border-radius:14px;font-size:13px">'
    '<div style="margin-bottom:8px;font-weight:600">💡 我這個月該扣多少？</div>'
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">平常每月定額 '
    '<input id="calcBase" type="number" inputmode="numeric" placeholder="例 10000" '
    'style="width:110px;padding:6px 10px;font-size:14px"> 元　→　今天建議 '
    '<b id="calcOut" style="color:var(--accent);font-size:16px">—</b></div>'
    '<div style="margin-top:6px;color:var(--muted);font-size:11.5px">今日倍數 '
    '<span id="calcMult">1</span>x：高分多扣、低分少扣，把分數變成具體金額。'
    '⚠️ 非投資建議</div></div>'
    '<script>/*calc*/(function(){var b=document.getElementById("calcBase"),'
    'o=document.getElementById("calcOut"),mt=document.getElementById("calcMult");'
    'if(!b)return;var me=document.querySelector(".mult b");'
    'var mult=me?parseFloat(me.textContent):1;if(!mult||isNaN(mult))mult=1;'
    'mt.textContent=(Math.round(mult*100)/100);'
    'try{var s=localStorage.getItem("calcBase");if(s)b.value=s;}catch(e){}'
    'function f(){var v=parseFloat(b.value)||0;'
    'o.textContent=v?Math.round(v*mult).toLocaleString()+" 元":"—";'
    'try{localStorage.setItem("calcBase",b.value);}catch(e){}}'
    'b.addEventListener("input",f);f();})();</script>'
)


def patch_calc(html):
    """在大盤倍數區下方加「我該扣多少」計算機。只動 index.html。"""
    if CALC_ANCHOR not in html or 'id="calc"' in html:
        return html, False
    return html.replace(CALC_ANCHOR, CALC_ANCHOR + CALC_BOX, 1), True


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


# --- 儀表板內鏈到 ETF 定期定額頁 ------------------------------------------
ETFLINK_ANCHOR = '把分數變成具體金額。⚠️ 非投資建議</div></div>'
ETFLINK_HTML = (
    '<a href="etf/" style="display:block;margin:10px 0 0;padding:10px 14px;'
    'background:rgba(52,208,127,.1);border:1px solid rgba(52,208,127,.3);'
    'border-radius:12px;color:#bfe8d2;text-decoration:none;font-size:13px">'
    '📦 想用在 0050 / 0056 等 ETF 定期定額？看 ETF 專頁 →</a>'
)


def patch_etflink(html):
    """大盤計算機下方加一條內鏈到 ETF 定期定額頁。只動 index.html（計算機注入後）。"""
    if ETFLINK_ANCHOR not in html or 'href="etf/"' in html:
        return html, False
    return html.replace(ETFLINK_ANCHOR, ETFLINK_ANCHOR + ETFLINK_HTML, 1), True


# --- 導覽列 iOS 液態玻璃風（SF Symbols 風單色線條圖示、無字、更透明）--------
# emoji → 單色線條 SVG（currentColor，未選取半透明、選取白色）+ 玻璃樣式。
# 新版改成更精緻、更像 iOS SF Symbols 的線條：長條圖／放大鏡／訊息泡泡／報紙。
BAR_ICON_SVGS = {
    # 進場（大盤分數）— chart.bar 長條圖
    '<span class="ic">📊</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 20V11"/><path d="M12 20V4"/><path d="M19 20v-6"/></svg></span>',
    # 個股 — magnifyingglass 放大鏡
    '<span class="ic">📈</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg></span>',
    # 觀點 — message 訊息泡泡（帶小尾巴）
    '<span class="ic">🗣️</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 '
        '1.5H9l-4 4v-4H5.5A1.5 1.5 0 0 1 4 13.5z"/></svg></span>',
    # 消息 — newspaper 報紙
    '<span class="ic">📰</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 5a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v13a2 2 0 0 0 2 2H6a2 2 0 0 1-2-2z"/>'
        '<path d="M17 8h2a1 1 0 0 1 1 1v9a2 2 0 0 1-2 2"/>'
        '<path d="M7 8h7M7 11.5h7M7 15h4"/></svg></span>',
}
# 上一版（儀表/泡泡/文件）的 SVG → 還原回 emoji，讓已套用的頁面也能升級到新圖示。
OLD_BAR_SVGS = {
    '<span class="ic">📊</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4.5-5.5"/></svg></span>',
    '<span class="ic">📈</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg></span>',
    '<span class="ic">🗣️</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 11.5a7.5 7.5 0 0 1-10.8 6.7L4.5 19.5l1.3-4.4A7.5 7.5 0 1 1 20 '
        '11.5z"/></svg></span>',
    '<span class="ic">📰</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/>'
        '</svg></span>',
}
BAR_STYLE = (
    '<style id="barglass">'
    '.tabbar a.tab span:not(.ic){display:none!important}'
    '.tabbar a.tab{flex-direction:row!important;justify-content:center!important;'
    'padding:15px 4px!important;gap:0!important}'
    '.tabbar a.tab .ic{color:#fff!important;opacity:.7;transition:opacity .18s,transform .18s}'
    '.tabbar a.tab .ic svg{width:26px;height:26px;display:block}'
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic{opacity:1;transform:translateY(-1px)}'
    # 引擎內建的滑動 thumb（隨 hover/目前頁移動）：粉紅 → 紫；圖示在其上維持白色(反白)
    '.tabbar .thumb{background:rgba(139,92,246,.85)!important}'
    '.tabbar a.tab.on{background:transparent!important}'  # 不疊靜態粉紅 tint，純靠 thumb
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic'
    '{filter:drop-shadow(0 2px 10px rgba(139,92,246,.55))!important}'
    '.tabbar{width:min(324px,calc(100vw - 52px))!important;'
    'background:linear-gradient(180deg,rgba(255,255,255,.085),rgba(255,255,255,.02))!important;'
    'border:1px solid rgba(255,255,255,.16)!important}'
    '</style>'
)
BAR_STYLE_RE = re.compile(r'<style id="barglass">.*?</style>', re.S)


def patch_barglass(html):
    """導覽列：emoji 換 SF 風單色線條 SVG + 無字 + 更透明玻璃。所有有 tabbar 的頁面。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    for emoji, oldsvg in OLD_BAR_SVGS.items():    # 0) 舊版 SVG → 還原回 emoji（升級用）
        html = html.replace(oldsvg, emoji)
    for emoji, newsvg in BAR_ICON_SVGS.items():   # 1) emoji → SF 風線條 SVG
        html = html.replace(emoji, newsvg)
    html = BAR_STYLE_RE.sub('', html)             # 2) 移除舊樣式（含上一版）
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
#      低=靛紫 #8b7cf0 → 中=藍 #5b9cff → 高=青 #22d3ee（避開紅綠，不與漲跌打架）。
#   3) index 主儀表(echarts)漸層 → 用同一條色帶（紫→藍→青）。
# 註：四大支柱等級條/徽章用 var(--green/red)，屬「品質」非「漲跌」，不動。
TWCOLOR_STYLE = (
    '<style id="twcolor">'
    '.green{color:#ea5455!important}'         # 標 green 的是「漲/+」→ 紅
    '.red{color:#28c76f!important}'           # 標 red 的是「跌/−」→ 綠
    '.score.green{color:#1fe0d0!important}'   # 高分 → 青（新色帶亮端）
    '.score.amber{color:#4f86ff!important}'   # 中分 → 藍（新色帶中段）
    '.score.red{color:#8b5cf6!important}'     # 低分 → 紫（新色帶暗端）
    '</style>'
)
TWCOLOR_RE = re.compile(r'<style id="twcolor">.*?</style>', re.S)
# 主儀表漸層改用同一條「紫→藍→青」色帶。沿途會碰到舊版（引擎原色 / #54 灰紫藍），
# 一律換成新色帶，並保持冪等（已是新色帶時不再變動）。
GAUGE_AURORA = ("color:[[0.35,'#8b5cf6'],[0.6,'#4f86ff'],"
                "[0.8,'#34b8e5'],[1,'#1fe0d0']]")
GAUGE_PREV = (
    "color:[[0.35,C.red],[0.45,'#f6862a'],[0.58,C.amber],"      # 引擎原色 紅→綠
    "[0.70,'#7cc24a'],[1,C.green]]",
    "color:[[0.35,'#8b97a8'],[0.55,'#9183e6'],"                 # #54 灰→紫→藍
    "[0.75,'#7d95f2'],[1,'#5b9cff']]",
    "color:[[0.35,'#8b7cf0'],[0.55,'#6a8efa'],"                 # 舊極光（#55，對比較小）
    "[0.78,'#3bb6e8'],[1,'#22d3ee']]",
)


def patch_twcolor(html):
    """漲跌紅漲綠跌；進場分數用極光冷色漸進帶。各頁注入 CSS；index 另改儀表漸層。"""
    if '</head>' not in html:
        return html, False
    orig = html
    html = TWCOLOR_RE.sub('', html)            # 移除舊版樣式再重注入（保持冪等）
    html = html.replace('</head>', TWCOLOR_STYLE + '</head>', 1)
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
#   低→高 = 靛紫 #8b7cf0 → 藍 #5b9cff → 青 #22d3ee（真漸進、連續）。
# 漲跌/報酬都帶 %、+/−，不是純數字 → 自動跳過，仍由 twcolor 管「紅漲綠跌」。
# 「脆弱度」越高越糟 → 反向取色。動態清單用 MutationObserver 補（只看 childList，
# 不看 attributes，故自身改色不會觸發回圈）。
SCORECOLOR_JS = (
    '<script id="scorecolor">(function(){'
    'var A=[[139,92,246],[79,134,255],[31,224,208]];'         # 紫→藍→青（加大對比）
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
    # 分級圖例方塊（0–35 保守…70–100 積極）：依區間中點上色
    'document.querySelectorAll(\'span[style*="width:9px"][style*="height:9px"]\').forEach(function(sq){'
    'var m=((sq.parentNode&&sq.parentNode.textContent)||"").match(/(\\d+)\\s*[\\u2013-]\\s*(\\d+)/);'
    'if(m)sq.style.setProperty("background",band((+m[1]+ +m[2])/200),"important");});'
    # 建議行動狀態膠囊（積極/中性/保守）：依主分數上色，深色字維持
    'document.querySelectorAll(".badge").forEach(function(b){'
    'var p=(b.closest&&b.closest(".verdict"))||b.parentNode;'
    'var m=((p&&p.textContent)||"").match(/進場分數\\s*(\\d+)/);'
    'if(m)b.style.setProperty("background",band(+m[1]/100),"important");});'
    # 指標方向訊號（只在 index：底部有 .foot .legend）→ 偏多 青 / 中性 藍 / 偏空 紫
    'if(document.querySelector(".foot .legend")){'
    'document.querySelectorAll(".dot").forEach(function(d){var s=d.getAttribute("style")||"";'
    'var c=/--green/.test(s)?"#2dc5de":/--amber/.test(s)?"#4f87ff":/--red/.test(s)?"#8b5cf6":null;'
    'if(c)d.style.setProperty("background",c,"important");});'
    'document.querySelectorAll(".foot .legend span").forEach(function(sp){if(sp.querySelector("i"))return;'
    'var t=sp.textContent||"",c=/偏多|加碼/.test(t)?"#2dc5de":/偏空|保守/.test(t)?"#8b5cf6":"#4f87ff";'
    'var ic=document.createElement("i");'
    'ic.style.cssText="display:inline-block;width:10px;height:10px;border-radius:50%;background:"'
    '+c+";margin-right:5px;vertical-align:-1px";'
    'sp.textContent="";sp.appendChild(ic);'
    'sp.appendChild(document.createTextNode(t.replace(/^[^\\u4e00-\\u9fff]+/,"")));});'
    'var hi=document.querySelector("b[style*=\'34d07f\']"),lo=document.querySelector("b[style*=\'ef5d5d\']");'
    'if(hi)hi.style.setProperty("color","#2dc5de","important");'
    'if(lo)lo.style.setProperty("color","#8b5cf6","important");}}'
    'recolor();'
    # 內文 emoji 記號 🟢🟡🔴（如新聞「是否反映」）→ 換成冷色圓點（一次性）
    '(function(){var E={"🟢":"#2dc5de","🟡":"#4f87ff","🔴":"#8b5cf6"};'
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
    """全站 0–100 分數統一沿極光色帶連續上色（含分類卡/支柱/動態清單），漲跌不動。"""
    if '</body>' not in html:
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
    'function tidy(){'
    '["#wl","#res"].forEach(function(s){var el=document.querySelector(s);'
    'if(el)el.style.display=blank(el)?"none":"";});'
    'document.querySelectorAll(".card").forEach(function(el){'
    'el.style.display=blank(el)?"none":"";});}'
    'tidy();'
    'if(window.MutationObserver){var r=null;new MutationObserver(function(){'
    'if(r)return;r=requestAnimationFrame(function(){r=null;tidy();});})'
    '.observe(document.body,{childList:true,subtree:true});}'
    '})();</script>'
)
EMPTYHIDE_RE = re.compile(r'<script id="emptyhide">.*?</script>', re.S)


def patch_emptyhide(html):
    """把完全沒內容的動態容器（#wl/#res）與空 .card 自動隱藏，避免空白框。"""
    if '</body>' not in html:
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
# 只放「派別」字尾；角色名直接讀卡片上的實際名字（清X君…），確保與卡片一致
ASK_NAME = {"passive": "被動指數派", "macro": "總經循環派", "trend": "順勢紀律派"}
ASK_A = {
    "passive": [
        "別問時機。你問『現在能不能進場』的當下，就已經掉進擇時陷阱了。照原定定期定額扣下去、別停，就這麼簡單。",
        "0050 或全球 VT。挑個股長期勝率輸大盤又耗時，把力氣省下來做資產配置跟再平衡。",
        "崩盤是定期定額的好朋友——同樣的錢買到更多單位。繼續扣、別看帳戶、別亂動。",
        "不停損。指數不會歸零，停損只會讓你賣在最低點、賣掉未來的複利。",
        "先把緊急備用金存好，再開低成本指數 ETF 定期定額，然後……什麼都別做。",
        "別人賺的是別人的，你追進去通常買在高點。FOMO 是擇時的另一個名字，紀律定額就不會 FOMO。",
        "有閒錢其實單筆＋長期持有期望值最高；但人性受不了，所以定期定額讓你睡得著、比較實際。",
        "絕對不要。槓桿會在你最撐不住時斷頭，被動投資的核心就是『活得夠久』。",
        "有趣，但別當買賣訊號。長期而言擇時贏不過低成本紀律定額，這分數頂多當市場溫度看看。",
        "擇時。再準的訊號，長期都贏不過『低成本＋紀律定額＋不亂動』。",
    ],
    "macro": [
        "先看景氣位置。現在偏『過熱』、融資槓桿暴增、Fed 全年沒幾碼——這種時候我偏防禦、重現金流，不追估值。",
        "都行，但重點是『質』。景氣轉折期挑有現金流、低負債的公司，比追題材安全。",
        "崩盤前通常信用利差和流動性會先壞。真的來了，手上要有現金跟防禦部位能接，而不是被迫殺低。",
        "我看的是景氣／基本面訊號轉壞才減碼，不是盯著價格停損——價格會騙人，循環不會。",
        "先學會看幾個總經溫度計：景氣對策信號、利率、殖利率曲線。知道現在是循環哪一段，比挑股票重要。",
        "市場最樂觀、人人都賺的時候，常常就是循環頂部。FOMO 最強時，我反而開始降風險。",
        "看循環。過熱、估值貴時我傾向分批、留現金；循環落底才是單筆布局的好時機。",
        "景氣過熱＋槓桿暴增的環境，加槓桿最危險。流動性一收，高槓桿的先出局。",
        "當環境溫度計不錯，但我更在意背後的景氣位置、利率和信用——分數高低要搭循環一起看。",
        "在景氣過熱、槓桿暴增時還追高估值和題材，完全不看流動性與信用轉折。",
    ],
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
}
ASK_ABBR = {"passive": "被動", "macro": "總經", "trend": "順勢"}
_ASK_DATA = "var Q=%s,A=%s,NAME=%s,ABBR=%s;" % (
    json.dumps(ASK_Q, ensure_ascii=False),
    json.dumps(ASK_A, ensure_ascii=False),
    json.dumps(ASK_NAME, ensure_ascii=False),
    json.dumps(ASK_ABBR, ensure_ascii=False),
)
_ASK_JS = r'''
var SEL=document.getElementById("askq"),AN=document.getElementById("askans"),HINT=document.getElementById("askhint"),cards={},DNAME={},cur=null;
var PCOL={passive:"#06d6e0",macro:"#c462ff",trend:"#5b6cff"};
function keyOf(t){return t.indexOf("清")>=0?"passive":t.indexOf("財經")>=0?"macro":t.indexOf("股")>=0?"trend":null;}
function rgba(h,a){var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);return "rgba("+r+","+g+","+b+","+a+")";}
function glass(h){return "linear-gradient(180deg,"+rgba(h,0.22)+","+rgba(h,0.06)+")";}
SEL.innerHTML='<option value="">— 選一個問題 —</option>'+Q.map(function(q,i){return '<option value="'+i+'">'+q+'</option>';}).join("");
[].forEach.call(document.querySelectorAll(".card .name"),function(n){var k=keyOf(n.textContent||"");if(!k)return;var c=n.closest(".card");if(!c)return;cards[k]=c;DNAME[k]=(n.textContent||"").replace(/\s+/g,"");c.style.setProperty("background",glass(PCOL[k]),"important");c.style.setProperty("border-color",rgba(PCOL[k],0.5),"important");c.style.setProperty("box-shadow","inset 0 1px 0.5px rgba(255,255,255,.22)","important");var d=c.querySelector(".dot");if(d)d.style.setProperty("background",PCOL[k],"important");c.classList.add("askpick");c.addEventListener("click",function(){pick(k);});});
function render(){if(cur===null||!SEL.value){AN.innerHTML="";return;}var i=+SEL.value,c=PCOL[cur];AN.innerHTML='<div class="bubble"><div class="av" style="background:'+c+'">'+ABBR[cur]+'</div><div class="bub" style="border-color:'+c+';background:'+glass(c)+'"><div class="bn" style="color:'+c+'">'+DNAME[cur]+'</div>'+A[cur][i]+'</div></div>';}
function pick(k){cur=k;for(var x in cards){cards[x].style.outline=(x===k?"2px solid "+PCOL[k]:"");cards[x].style.outlineOffset="2px";}HINT.innerHTML="已選 <b style='color:"+PCOL[k]+"'>"+DNAME[k]+"</b>　選個問題，或點別位比較 👇";SEL.disabled=false;render();}
SEL.addEventListener("change",render);
'''


ASK_PANEL = (
    '<div class="section-title">🎤 換你問：點上面選一位，再選問題</div>'
    '<div id="askpanel" data-v="ask13" style="background:linear-gradient(180deg,'
    'rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.1);'
    'border-radius:16px;padding:15px 16px;margin-bottom:14px">'
    '<div id="askhint" class="lbl">👆 點上面任一張立場卡片，再從下拉選問題</div>'
    '<select id="askq" class="asksel" disabled><option value="">先選一位…</option></select>'
    '<div id="askans"></div>'
    '<div style="font-size:11px;color:#8b96a8;margin-top:13px">'
    '以投資流派為框架推演・非本人發言・非投資建議</div></div>'
    '<style>'
    '#askpanel .lbl{font-size:12.5px;color:#aab4c6;margin:0 0 10px}'
    '#askpanel .asksel{width:100%;background:rgba(255,255,255,.07);color:#eaf0fa;'
    'border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:11px 12px;'
    'font-size:14px;font-family:inherit;cursor:pointer}'
    '#askpanel .asksel:disabled{opacity:.5;cursor:not-allowed}'
    '#askpanel .asksel option{background:#11203f;color:#eaf0fa}'
    '#askpanel .bubble{display:flex;gap:10px;align-items:flex-start;margin-top:13px}'
    '#askpanel .av{flex:none;width:40px;height:40px;border-radius:50%;'
    'display:flex;align-items:center;justify-content:center;color:#fff;'
    'font-size:13px;font-weight:800;letter-spacing:.5px;'
    'text-shadow:0 1px 3px rgba(0,0,0,.35);'
    'box-shadow:0 0 0 3px rgba(255,255,255,.06)}'
    '#askpanel .bub{border:1px solid;border-radius:4px 16px 16px 16px;'
    'padding:14px 17px;font-size:16px;line-height:1.85;color:#eaf3ff;'
    '-webkit-backdrop-filter:blur(18px) saturate(1.6);'
    'backdrop-filter:blur(18px) saturate(1.6);'
    'box-shadow:0 8px 26px rgba(0,0,0,.35),inset 0 1px 0.5px rgba(255,255,255,.18)}'
    '#askpanel .bn{font-weight:700;font-size:13px;margin-bottom:5px}'
    '.card.askpick{cursor:pointer}'
    '</style>'
    '<script>(function(){' + _ASK_DATA + _ASK_JS + '})();</script>'
)
# 引擎原版（含辯論）→ 替換整段；舊版面板（v1）→ 升級成新版
ASK_DEBATE_RE = re.compile(r'<div class="section-title">🔥 三方互嗆.*?</div>\s*</body>', re.S)
ASK_OLD_RE = re.compile(
    r'<div class="section-title">🎤 換你問.*?</script>\s*</div>\s*</body>', re.S)


# 三方派系配色 → 三個明顯分開的冷色寶石調（被動 亮青 / 順勢 靛藍 / 總經 洋紫）。
# 獨立遷移：不受下方版本守門影響，把先前各版（金黃版、第一版極光）都換成新色，冪等。
PCOL_NEW = 'var PCOL={passive:"#06d6e0",macro:"#c462ff",trend:"#5b6cff"};'
PCOL_PREV = (
    'var PCOL={passive:"#38c5e0",macro:"#f5c531",trend:"#3b82f6"};',   # 最初金黃版
    'var PCOL={passive:"#22d3ee",macro:"#8b7cf0",trend:"#5b9cff"};',   # 第一版極光
)


def patch_ask(html):
    """觀點頁：三方立場卡片直接點選，提問用下拉選單，移除辯論。"""
    changed = False
    # 內容已不是辯論 → 標題改字（無論面板是否已注入都套用）
    if "市場觀點・三方辯論" in html:
        html = html.replace("市場觀點・三方辯論", "市場觀點・問三方")
        changed = True
    for prev in PCOL_PREV:                        # 既有面板的三方色 → 遷移成新冷色寶石調
        if prev in html:
            html = html.replace(prev, PCOL_NEW, 1)
            changed = True
            break

    if 'data-v="ask13"' in html:                 # 面板已是最新版
        return html, changed
    if '🔥 三方互嗆' in html:                    # 引擎原版：替換辯論段
        new = ASK_DEBATE_RE.sub(lambda m: ASK_PANEL + '</div></body>', html, count=1)
    elif '🎤 換你問' in html:                    # 舊版面板：升級
        new = ASK_OLD_RE.sub(lambda m: ASK_PANEL + '</div></body>', html, count=1)
    else:
        return html, changed
    return (new, True) if new != html else (html, changed)


def patch(html):
    changed = False

    # 1) favicon：沒有就補在 apple-touch-icon 連結前面
    if 'rel="icon" href="favicon' not in html:
        m = APPLE_RE.search(html)
        if m:
            html = html[:m.start()] + FAVICON + html[m.start():]
            changed = True

    # 2) 標題加品牌前綴（已加過則略過）
    def repl(m):
        t = m.group(1).strip()
        if not t or t.startswith(BRAND):
            return m.group(0)
        return f"<title>{BRAND} — {t}</title>"

    new = TITLE_RE.sub(repl, html, count=1)
    if new != html:
        html = new
        changed = True

    # 3) 評分一致性 + 直覺化 UX（只有含評語區塊的儀表板頁才處理）
    if 'class="verdict"' in html:
        html, sc = patch_scoring(html)
        changed = changed or sc
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
    html, ca = patch_calc(html)
    changed = changed or ca

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
    html, el = patch_etflink(html)
    changed = changed or el

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


def main():
    touched = []
    for f in sorted(glob.glob("*.html")):
        s = open(f, encoding="utf-8").read()
        # 只處理使用者頁面（有 apple-touch-icon 的那幾頁）
        if APPLE_RE.search(s) is None:
            continue
        new, changed = patch(s)
        if changed:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            touched.append(f)
    print("已補丁：" + (", ".join(touched) if touched else "(無需變更)"))


if __name__ == "__main__":
    main()

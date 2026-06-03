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


# --- 導覽列 iOS 液態玻璃風（單色線條圖示、無字、更透明）--------------------
# emoji → 單色線條 SVG（currentColor，未選取半透明、選取白色實心）+ 玻璃樣式。
BAR_ICON_SVGS = {
    # 進場（大盤分數）— 儀表/錶針
    '<span class="ic">📊</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4.5-5.5"/></svg></span>',
    # 個股 — 放大鏡（搜尋）
    '<span class="ic">📈</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg></span>',
    # 觀點 — 對話泡泡
    '<span class="ic">🗣️</span>':
        '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 11.5a7.5 7.5 0 0 1-10.8 6.7L4.5 19.5l1.3-4.4A7.5 7.5 0 1 1 20 '
        '11.5z"/></svg></span>',
    # 消息 — 文件/報紙
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
    'padding:13px 4px!important;gap:0!important}'
    '.tabbar a.tab .ic{color:#fff!important;opacity:.7;transition:opacity .18s,transform .18s}'
    '.tabbar a.tab .ic svg{width:24px;height:24px;display:block}'
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic{opacity:1;transform:translateY(-1px)}'
    '.tabbar{width:min(290px,calc(100vw - 64px))!important;'
    'background:linear-gradient(180deg,rgba(255,255,255,.085),rgba(255,255,255,.02))!important;'
    'border:1px solid rgba(255,255,255,.16)!important}'
    '</style>'
)
BAR_STYLE_RE = re.compile(r'<style id="barglass">.*?</style>', re.S)


def patch_barglass(html):
    """導覽列：emoji 換單色線條 SVG + 無字 + 更透明玻璃。所有有 tabbar 的頁面。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    for old, new in BAR_ICON_SVGS.items():       # 1) emoji → 線條 SVG
        html = html.replace(old, new)
    html = BAR_STYLE_RE.sub('', html)            # 2) 移除舊樣式（含上一版）
    html = html.replace('<nav class="tabbar">', BAR_STYLE + '<nav class="tabbar">', 1)
    return html, (html != orig)


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
var PCOL={passive:"#34d07f",macro:"#ef5d5d",trend:"#f9b43a"};
function keyOf(t){return t.indexOf("清")>=0?"passive":t.indexOf("財經")>=0?"macro":t.indexOf("股")>=0?"trend":null;}
function rgba(h,a){var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);return "rgba("+r+","+g+","+b+","+a+")";}
function full(k){return DNAME[k]+"・"+NAME[k];}
SEL.innerHTML='<option value="">— 選一個問題 —</option>'+Q.map(function(q,i){return '<option value="'+i+'">'+q+'</option>';}).join("");
[].forEach.call(document.querySelectorAll(".card .name"),function(n){var k=keyOf(n.textContent||"");if(!k)return;var c=n.closest(".card");if(!c)return;cards[k]=c;DNAME[k]=(n.textContent||"").replace(/\s+/g,"");c.style.setProperty("background",rgba(PCOL[k],0.12),"important");c.style.setProperty("border-color",rgba(PCOL[k],0.5),"important");var d=c.querySelector(".dot");if(d)d.style.setProperty("background",PCOL[k],"important");c.classList.add("askpick");c.addEventListener("click",function(){pick(k);});});
function render(){if(cur===null||!SEL.value){AN.innerHTML="";return;}var i=+SEL.value,c=PCOL[cur];AN.innerHTML='<div class="bubble"><div class="av" style="background:'+c+'">'+ABBR[cur]+'</div><div class="bub" style="border-color:'+c+';background:'+rgba(c,0.12)+'"><div class="bn" style="color:'+c+'">'+full(cur)+'</div>'+A[cur][i]+'</div></div>';}
function pick(k){cur=k;for(var x in cards){cards[x].style.outline=(x===k?"2px solid "+PCOL[k]:"");cards[x].style.outlineOffset="2px";}HINT.innerHTML="已選 <b style='color:"+PCOL[k]+"'>"+DNAME[k]+"</b>　選個問題，或點別位比較 👇";SEL.disabled=false;render();}
SEL.addEventListener("change",render);
'''


ASK_PANEL = (
    '<div class="section-title">🎤 換你問：點上面選一位，再選問題</div>'
    '<div id="askpanel" data-v="ask10" style="background:linear-gradient(180deg,'
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
    'display:flex;align-items:center;justify-content:center;color:#0a1430;'
    'font-size:13px;font-weight:800;letter-spacing:.5px;'
    'box-shadow:0 0 0 3px rgba(255,255,255,.06)}'
    '#askpanel .bub{border:1px solid;border-radius:4px 16px 16px 16px;'
    'padding:14px 17px;font-size:16px;line-height:1.85;color:#eaf3ff}'
    '#askpanel .bn{font-weight:700;font-size:13px;margin-bottom:5px}'
    '.card.askpick{cursor:pointer}'
    '</style>'
    '<script>(function(){' + _ASK_DATA + _ASK_JS + '})();</script>'
)
# 引擎原版（含辯論）→ 替換整段；舊版面板（v1）→ 升級成新版
ASK_DEBATE_RE = re.compile(r'<div class="section-title">🔥 三方互嗆.*?</div>\s*</body>', re.S)
ASK_OLD_RE = re.compile(
    r'<div class="section-title">🎤 換你問.*?</script>\s*</div>\s*</body>', re.S)


def patch_ask(html):
    """觀點頁：三方立場卡片直接點選，提問用下拉選單，移除辯論。"""
    if 'data-v="ask10"' in html:                 # 已是最新版
        return html, False
    if '🔥 三方互嗆' in html:                    # 引擎原版：替換辯論段
        new = ASK_DEBATE_RE.sub(lambda m: ASK_PANEL + '</div></body>', html, count=1)
    elif '🎤 換你問' in html:                    # 舊版面板：升級
        new = ASK_OLD_RE.sub(lambda m: ASK_PANEL + '</div></body>', html, count=1)
    else:
        return html, False
    return (new, True) if new != html else (html, False)


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

    # 7) 「我該扣多少」計算機（index.html）
    html, ca = patch_calc(html)
    changed = changed or ca

    # 8) 自選股進站變化提醒（stocks.html）
    html, wa = patch_wlalert(html)
    changed = changed or wa

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
    html, bg = patch_barglass(html)
    changed = changed or bg

    # 13) 觀點頁：移除辯論、保留三方立場、加「選一派問問題」
    html, ak = patch_ask(html)
    changed = changed or ak

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

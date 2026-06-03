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


# --- 導覽列 iOS 液態玻璃風（只圖示、無字、更透明）-------------------------
# 用 !important 覆寫既有 tabbar 樣式；以 id="barglass" 判定是否已注入。
BARGLASS_ANCHOR = '<nav class="tabbar">'
BARGLASS_STYLE = (
    '<style id="barglass">'
    '.tabbar a.tab span:not(.ic){display:none!important}'           # 拿掉文字
    '.tabbar a.tab{flex-direction:row!important;justify-content:center!important;'
    'padding:13px 4px!important;gap:0!important}'
    '.tabbar a.tab .ic{font-size:23px!important;opacity:.42;'        # 未選取半透明
    'transition:opacity .18s,transform .18s}'
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic{opacity:1;transform:translateY(-1px)}'
    '.tabbar{width:min(290px,calc(100vw - 64px))!important;'        # 無字可收窄
    'background:linear-gradient(180deg,rgba(255,255,255,.085),rgba(255,255,255,.02))!important;'
    'border:1px solid rgba(255,255,255,.16)!important}'
    '</style>'
)


def patch_barglass(html):
    """導覽列改成只圖示、無字、更透明的液態玻璃風。所有有 tabbar 的頁面。"""
    if BARGLASS_ANCHOR not in html or 'id="barglass"' in html:
        return html, False
    return html.replace(BARGLASS_ANCHOR, BARGLASS_STYLE + BARGLASS_ANCHOR, 1), True


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

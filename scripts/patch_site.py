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
    # 排程器：所有圖表一進頁就全部建，只是每個 animation frame 建一張，
    # 這樣八九張疊在一起也不會把主執行緒佔住而讓首繪卡住。
    # 舊版是 IntersectionObserver（滑到才畫）——手機 PWA 沒辦法重整，捲不到
    # 的圖表就一直是空的，所以整條 lazy 路徑拔掉。__forceEager 保留為
    # 「現在就畫」的逃生口（個股頁 K 線自己有每幀迴圈，不需要再排一次）。
    'if(!E.__sched){var R=E.init;E.__sched=1;var W=[],pump=0;'
    'var RA=g.requestAnimationFrame||function(f){return setTimeout(f,16);};'
    'function drain(){pump=0;var j=W.shift();if(!j)return;'
    # 版面還沒算出來就先別建圖：echarts 在 0x0 的容器上什麼都畫不出來，而且不會
    # 自己重試——畫面就是一片空白，連錯誤都沒有。SPA 換頁時 rerun 緊接在 swap
    # 後面執行，這時容器往往還是 0x0，整頁圖表就這樣靜靜死掉。等它有尺寸再建。
    'var el=j[1][0];'
    'if(el&&el.nodeType===1&&!(el.clientWidth>0&&el.clientHeight>0)){'
    'j[2]=(j[2]||0)+1;if(j[2]<120){W.push(j);kick();return;}}'
    'if(!j[0]._x)bind(j[0],R.apply(E,j[1]));'
    'if(W.length)kick();}'
    'function kick(){if(pump)return;pump=1;RA(drain);}'
    'E.init=function(el){var a=arguments;if(!el||el.__forceEager)return R.apply(E,a);'
    'var p=P();W.push([p,a]);kick();return p};}'
    'for(var i=0;i<Q.length;i++){if(!Q[i][2]._x)bind(Q[i][2],E.init.apply(E,Q[i][1]));}'
    'Q.length=0;};'
    # 看門狗：真庫沒進來的話，圖表就靜靜卡在排隊狀態（畫面上是空的，沒有任何
    # 錯誤）。載完 1.5 秒還是 stub 就自己再載一次；回到前景時也再看一眼。
    # 兩支備援 CDN 輪流試，最多三次，避免網路一直不通時無限重試。
    'var SRC=["https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js",'
    '"https://unpkg.com/echarts@5.5.0/dist/echarts.min.js"],tries=0,busy=0;'
    'function retry(){'
    'if(busy||tries>=3||!g.echarts||!g.echarts.__stub)return;'
    'busy=1;var s=document.createElement("script");s.src=SRC[tries++%2];'
    's.onload=function(){busy=0;g.__ecReady();};s.onerror=function(){busy=0;};'
    'document.head.appendChild(s);}'
    'addEventListener("load",function(){setTimeout(retry,1500);});'
    'document.addEventListener("visibilitychange",function(){'
    'if(!document.hidden)setTimeout(retry,300);});'
    '})(window);</script>'
)
ECHARTS_DEFER = (
    '<script defer src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js" '
    'onload="__ecReady()" '
    'onerror="var s=document.createElement(\'script\');'
    's.src=\'https://unpkg.com/echarts@5.5.0/dist/echarts.min.js\';'
    's.onload=__ecReady;document.head.appendChild(s)"></script>'
)


# 已注入的舊 stub 就地升級用。ECHARTS_TAG 在第一次補丁後就不存在了，只靠上面
# 那條路徑的話，改了 stub 內容也只有「引擎重產的新 HTML」吃得到，已部署的頁面
# 會一直卡在舊版（lazy IntersectionObserver 那版就是這樣留下來的）。
ECHARTS_STUB_RE = re.compile(r'<script>/\*echarts-stub\*/.*?</script>', re.S)


def patch_perf(html):
    """echarts 改 defer + 載入 stub（首繪不被圖表庫卡住），建圖排程見 __ecReady。"""
    changed = False
    if ECHARTS_TAG in html:                # 阻塞版 script → stub + defer
        repl = ECHARTS_STUB + ECHARTS_DEFER
        if PRECONNECT not in html:
            repl = PRECONNECT + repl
        html = html.replace(ECHARTS_TAG, repl, 1)
        changed = True
    m = ECHARTS_STUB_RE.search(html)       # 舊 stub → 現行 stub（冪等：一樣就不動）
    if m and m.group(0) != ECHARTS_STUB:
        html = html[:m.start()] + ECHARTS_STUB + html[m.end():]
        changed = True
    return html, changed


# --- K 線一開始就畫（個股頁）------------------------------------------------
# 引擎給 .kchart[data-k] 掛了 IntersectionObserver（rootMargin 240px），所以第一
# 屏以外的 K 線要捲到才會出現。改成一進頁就全部畫完。
# 兩層 lazy 都要拆：
#   ① 引擎自己的 IO（下面這個 regex 換掉 run()）
#   ② 我們 echarts-stub 在 __ecReady 裡包的那層（rootMargin 200px）——從有 stub
#      的頁 SPA 換過來時，echarts.init 已經被換成 lazy 版。它留了 __forceEager
#      這個逃生口，所以畫之前先把旗標插上。
# 一次畫 8 張會把主執行緒佔住一兩百毫秒（每張 echarts.init 都不便宜），進頁面
# 就頓一下。改成「每幀一張」：第一張同步畫（那張本來就在第一屏），其餘每個
# animation frame 補一張，八張約 120ms 內畫完，但每幀只用掉一張的時間，捲動與
# 點擊都還跟得動。
# rAF 在背景分頁會被停掉——但那也代表使用者沒在看，切回前景就會續畫，不會像
# 之前玻璃重整那樣「漏一次就永久壞掉」。沒有 rAF 的環境退回 setTimeout。
# 換頁（SPA）把節點換掉之後就停手，不要對著已經脫離文件的元素畫。
KCHART_LAZY_RE = re.compile(
    # ① 引擎原版：IntersectionObserver（rootMargin 240px）
    r"function run\(\)\{\s*"
    r"if\(typeof IntersectionObserver==='undefined'\)\{els\.forEach\(draw\);return;\}\s*"
    r"var io=new IntersectionObserver\(.*?\{rootMargin:'240px'\}\);\s*"
    r"els\.forEach\(function\(el\)\{io\.observe\(el\);\}\);\s*\}"
    # ② 上一版「一次全部畫完」：已部署的頁面就地升級成每幀一張
    r"|function run\(\)\{els\.forEach\(function\(el\)\{el\.__forceEager=1;draw\(el\);\}\);\}",
    re.S)
KCHART_EAGER = (
    'function run(){'
    'var i=0,tries=0,R=window.requestAnimationFrame||function(f){return setTimeout(f,16);};'
    '(function step(){'
    'if(i>=els.length)return;'
    'var el=els[i];'
    'if(el.isConnected===false){i++;return R(step);}'
    # 同樣要等容器有尺寸：0x0 建出來的 echarts 是空的，而且不會自己補畫。
    'if(!(el.clientWidth>0&&el.clientHeight>0)&&tries<120){tries++;return R(step);}'
    'i++;tries=0;el.__forceEager=1;draw(el);'
    'R(step);'
    '})();}'
)


def patch_kchart_eager(html):
    """K 線不再等捲動，一進頁就每幀補一張，全部畫完。只有個股頁有 .kchart[data-k]。"""
    new = KCHART_LAZY_RE.sub(lambda m: KCHART_EAGER, html, count=1)
    return new, (new != html)


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

# --- 液態折射＋模糊「最高檔」（#lglass 加強版） ------------------------------
# 模糊開到最強；位移折射維持原設計 scale 30/34/38——加倍到 60/68/76 時，位移量
# 超過小元件（如 .fab 54px）本身，支援折射的新版 iOS Safari 會把背後內容抹成大團
# 光暈（使用者截圖回報）。折射層附帶 blur 16px、不支援折射的瀏覽器退回 blur 48px。
# 作法：先拆掉 Bot 版與舊注入版（冪等），再重插加強版 <svg> 濾鏡與 @supports 樣式。
LGLASS_CSS_RE = re.compile(
    r'(?:/\*[^*]*\*/\s*)?@supports \(backdrop-filter: url\("#lglass"\)\)'
    r'.*?\}\s*\}', re.S)
LGLASS_SVG_RE = re.compile(r'<svg[^>]*><filter id="lglass".*?</svg>', re.S)
MAXGLASS_RE = re.compile(r'<style id="maxglass">.*?</style>', re.S)

MAXGLASS_SVG = (
    '<svg width="0" height="0" style="position:absolute;pointer-events:none" '
    'aria-hidden="true"><filter id="lglass" x="0%" y="0%" width="100%" height="100%" '
    'color-interpolation-filters="sRGB">'
    '<feImage href="glassmap.png" preserveAspectRatio="none" x="0%" y="0%" '
    'width="100%" height="100%" result="map"/>'
    '<feDisplacementMap in="SourceGraphic" in2="map" scale="30" '
    'xChannelSelector="R" yChannelSelector="G" result="dR"/>'
    '<feDisplacementMap in="SourceGraphic" in2="map" scale="34" '
    'xChannelSelector="R" yChannelSelector="G" result="dG"/>'
    '<feDisplacementMap in="SourceGraphic" in2="map" scale="38" '
    'xChannelSelector="R" yChannelSelector="G" result="dB"/>'
    '<feColorMatrix in="dR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  '
    '0 0 0 0 0  0 0 0 1 0" result="cR"/>'
    '<feColorMatrix in="dG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  '
    '0 0 0 0 0  0 0 0 1 0" result="cG"/>'
    '<feColorMatrix in="dB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  '
    '0 0 1 0 0  0 0 0 1 0" result="cB"/>'
    '<feBlend in="cR" in2="cG" mode="screen" result="rg"/>'
    '<feBlend in="rg" in2="cB" mode="screen"/></filter></svg>'
    # 這裡原本還有一顆 #lglass-cap（膠囊專用、位移縮小成 10/12/14、濾鏡區域
    # 放大到 160%）。已移除：淺色主題下它不是折射背景，而是把 glassmap 這張
    # 法線貼圖本身畫出來，拖曳中的膠囊就成了一坨不透明灰。沒有其他地方用它。
)
MAXGLASS_CSS = (
    '<style id="maxglass">'
    '.card,.box,.pcard,.hero,.brief,.nrow,.tabbar,.topglass,.brandbar.scrolled{'
    '-webkit-backdrop-filter:blur(48px) saturate(2)!important;'
    'backdrop-filter:blur(48px) saturate(2)!important}'
    '@supports (backdrop-filter: url("#lglass")) or '
    '(-webkit-backdrop-filter: url("#lglass")){'
    '.card,.box,.pcard,.hero,.brief,.nrow,.tabbar,.topglass,.brandbar.scrolled{'
    '-webkit-backdrop-filter:url(#lglass) blur(16px) saturate(2)!important;'
    'backdrop-filter:url(#lglass) blur(16px) saturate(2)!important}}'
    '</style>'
)


def patch_reglass(html):
    """液態折射＋模糊最高檔：移除舊版再重插加強版（冪等、可升級）。"""
    if '</body>' not in html:
        return html, False
    if MAXGLASS_SVG + MAXGLASS_CSS in html:
        return html, False
    orig = html
    html = MAXGLASS_RE.sub('', html)
    html = LGLASS_CSS_RE.sub('', html)
    html = LGLASS_SVG_RE.sub('', html)
    anchor = '<nav class="tabbar">'
    ins = MAXGLASS_SVG + MAXGLASS_CSS
    if anchor in html:
        html = html.replace(anchor, ins + anchor, 1)
    else:
        html = html.replace('</body>', ins + '</body>', 1)
    return html, (html != orig)


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


# --- 固定頂部 logo 欄（與 Mindrise 邏輯統一：fixed 頂欄，捲動時變毛玻璃） ----
# logo 用 iOS 27 風格 Liquid Glass 表面處理；欄本體 pointer-events:none 不擋內容。
BRANDBAR_HTML = (
    '<header class="brandbar"><span class="brandlogo">'
    '<img src="icon-180.png" alt=""><i aria-hidden="true"></i></span>'
    '<span class="brandname">Stock Tracker<small>台股進場儀表板</small></span>'
    '__STAT__'
    '</header>'
    '<script id="brandbarjs">(function(){var b=document.querySelector(".brandbar");'
    'if(!b)return;var f=function(){b.classList.toggle("scrolled",(window.scrollY||0)>6)};'
    'addEventListener("scroll",f,{passive:true});f();})();</script>'
)
BRANDBAR_CSS = (
    '<style id="brandlogo">'
    '.brandbar{position:fixed;top:0;left:0;right:0;z-index:90;display:flex;'
    'align-items:center;gap:10px;pointer-events:none;'
    'padding:calc(14px + env(safe-area-inset-top,0px)) max(16px,calc((100vw - 1288px)/2)) 10px;'
    'background:transparent;transition:background .25s ease,box-shadow .25s ease}'
    '.brandbar.scrolled{background:rgba(245,248,251,.75);'
    '-webkit-backdrop-filter:blur(60px) saturate(1.7);'
    'backdrop-filter:blur(60px) saturate(1.7);'
    'box-shadow:0 1px 0 rgba(30,60,100,.08),0 14px 34px -22px rgba(30,60,100,.35)}'
    # 右側統計 chip：圓點＋短文字的膠囊（與頂欄同款玻璃質感）
    '.brandstat{margin-left:auto;display:inline-flex;align-items:center;gap:6px;'
    'padding:5px 11px;border-radius:999px;font-size:12px;font-weight:700;'
    'color:#17293a;white-space:nowrap;flex:none;'
    'background:rgba(255,255,255,.5);border:1px solid rgba(216,226,236,.95);'
    'box-shadow:inset 0 1px 0 rgba(255,255,255,.95),0 1px 3px rgba(30,60,100,.06)}'
    '.brandstat i{width:8px;height:8px;border-radius:50%;flex:none}'
    '.brandstat b{font-size:14px;font-weight:800;letter-spacing:.01em}'
    '.brandstat em{font-style:normal;font-weight:700;font-size:11.5px;margin-left:1px}'
    '.brandname{font-weight:800;font-size:20px;color:#17293a;letter-spacing:.03em;'
    'white-space:nowrap;'
    'line-height:1.7}'
    '.brandname small{display:block;font-size:11px;font-weight:600;color:#5b6d80;'
    'letter-spacing:.16em;margin-top:1px}'
    '.brandlogo{position:relative;display:inline-block;width:38px;height:38px;'
    'border-radius:11px;overflow:hidden;flex:0 0 auto;'
    'box-shadow:0 5px 14px -5px rgba(30,60,100,.45)}'
    '.brandlogo img{width:100%;height:100%;display:block}'
    '.brandlogo i{position:absolute;inset:0;border-radius:inherit;pointer-events:none;'
    'box-shadow:inset 0 1px 1px rgba(255,255,255,.8),'
    'inset 0 -1px 1px rgba(255,255,255,.4),'
    'inset 0 0 0 1px rgba(255,255,255,.28);'
    'background:linear-gradient(180deg,rgba(255,255,255,.26),rgba(255,255,255,0) 30%,'
    'rgba(255,255,255,0) 78%,rgba(255,255,255,.14))}'
    'body .wrap{padding-top:calc(80px + env(safe-area-inset-top,0px))!important}'
    # 窄螢幕：標題縮一級，讓「標題＋指數 chip」在 390px 也並排得下
    '@media(max-width:412px){.brandname{font-size:17px}'
    '.brandname small{font-size:10px;letter-spacing:.12em}}'
    # 極窄（≤380px）：連「加權」兩字都收起，只留圓點＋數字＋漲跌
    '@media(max-width:380px){.brandstat .lbl{display:none}}'
    '</style>'
)
BRANDLOGO_RE = re.compile(r'<style id="brandlogo">.*?</style>', re.S)

# --- 頂欄右側統計 chip -------------------------------------------------------
# 資料來源＝index.html（引擎每天重生的權威數字），patch 每次跑都重讀 →
# 全站各頁的頂欄都顯示同一個今日分數。抓不到就不出 chip（不影響版面）。
_STAT_CACHE = None


def _site_stat():
    """回傳 (分數, 較昨日, 加權指數)；抓不到的欄位給 None。
    分數／歷史／指數都取自 index.html 的 DASH payload（引擎每天重生的權威數字）：
    - 較昨日：composite 對比 score_history 前一日（若最後一筆已是今日則往前取一筆）
    - 加權指數：tq_twii 指標的 series 末值（引擎算趨勢時本來就帶著的收盤序列）"""
    global _STAT_CACHE
    if _STAT_CACHE is None:
        _STAT_CACHE = ()
        try:
            with open('index.html', encoding='utf-8') as f:
                h = f.read()
            m = re.search(r'進場分數\s*([\d.]+)', h)
            if not m:
                return None
            score = float(m.group(1))
            delta = twii = twii_chg = None
            mc = re.search(r'"composite":\s*([\d.]+)', h)
            mh = re.search(r'"score_history":\s*(\[\[.*?\]\])', h, re.S)
            if mc and mh:
                comp = float(mc.group(1))
                hist = json.loads(mh.group(1))
                if len(hist) >= 2:
                    prev = hist[-1][1] if abs(hist[-1][1] - comp) > 0.05 else hist[-2][1]
                    delta = comp - prev
            mt = re.search(r'"key":\s*"tq_twii",\s*"series":\s*(\[[^\]]*\])', h)
            if mt:
                ser = json.loads(mt.group(1))
                if ser:
                    twii = ser[-1]
                    # 指數自身日漲跌%：同一條收盤序列的末兩筆
                    if len(ser) >= 2 and ser[-2]:
                        twii_chg = (ser[-1] / ser[-2] - 1.0) * 100
            _STAT_CACHE = (score, delta, twii, twii_chg)
        except Exception:                      # noqa: BLE001 — 抓不到就不顯示
            pass
    return _STAT_CACHE or None


def _brandstat_html():
    st = _site_stat()
    if not st:
        return ''
    score, _delta, twii, twii_chg = st
    # 圓點顏色沿用儀表色帶：低分＝琥珀（過熱危險）→ 高分＝天藍（遍地黃金）
    col = ('#1a9bdf' if score >= 70 else '#2478c8' if score >= 58
           else '#2f7cc4' if score >= 45 else '#c98a1e')
    # 只留加權指數一顆（分數在首頁 hero 已是主角，頂欄不重複）；
    # 圓點仍用分數色帶帶出市場溫度，delta 保留給指數旁邊的漲跌色語彙。
    if not twii:
        return ''
    chg = ''
    if twii_chg is not None:
        cc = '#d63838' if twii_chg > 0 else '#1f9d55' if twii_chg < 0 else '#5b6d80'
        chg = '<em style="color:%s">%+.1f%%</em>' % (cc, twii_chg)
    return ('<span class="brandstat"><i style="background:%s"></i>'
            '<span class="lbl">加權 </span><b>%s</b>%s</span>'
            % (col, '{:,.0f}'.format(twii), chg))


BRANDBAR_RE = re.compile(r'<header class="brandbar">.*?</header>', re.S)
BRANDBARJS_RE = re.compile(r'<script id="brandbarjs">.*?</script>', re.S)
BRANDLOGO_IMG_RE = re.compile(
    r'(<span class="brandlogo">.*?</span>|<img class="brandlogo"[^>]*>)', re.S)


def patch_brandlogo(html, fname):
    """固定頂部 logo 欄，插在 <body> 開頭。移除舊版（含 h1 內 logo）再重插（冪等）。"""
    m = re.search(r'<body[^>]*>', html)
    if not m:
        return html, False
    pre = '../' if '/' in fname else ''
    ins = BRANDBAR_CSS + BRANDBAR_HTML.replace(
        'src="icon-180.png"', 'src="' + pre + 'icon-180.png"'
    ).replace('__STAT__', _brandstat_html())
    if ins in html:
        return html, False
    orig = html
    html = BRANDLOGO_RE.sub('', html)
    html = BRANDBARJS_RE.sub('', html)
    html = BRANDBAR_RE.sub('', html)
    html = BRANDLOGO_IMG_RE.sub('', html)
    m = re.search(r'<body[^>]*>', html)
    html = html[:m.end()] + ins + html[m.end():]
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
    '📊': '<path d="M4.4 17.2a8.6 8.6 0 1 1 15.2 0"/><path d="M12 16.4l3.8-6.2"/><circle cx="12" cy="16.4" r="1.35"/>',
    '📈': '<path d="M3 18l5.5-6.5 4 4L20 6.5"/><path d="M15 6.5h5v5"/>',
    # 觀點：雙泡泡（該頁是三派立場，單泡泡表達不出多方觀點）
    '🗣️': '<path d="M5 4.5h8A2.5 2.5 0 0 1 15.5 7v3.5A2.5 2.5 0 0 1 13 13H8.2l-3.2 2.8V13'
          'A2.5 2.5 0 0 1 2.5 10.5V7A2.5 2.5 0 0 1 5 4.5z"/>'
          '<path d="M18.2 9.2A2.5 2.5 0 0 1 20.7 11.7v3.4a2.5 2.5 0 0 1-2.5 2.5h-.3v2.6'
          'l-3-2.6h-3.2"/>',
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
# bar 中間那顆動作鈕：外觀就是一般 icon，跟其他分頁一樣的排法與尺寸，只是
    # 點下去開搜尋 sheet 而不是換頁。沒有圓底、沒有自己的玻璃。
    '.baract{flex:1 1 0;min-width:0;display:flex;align-items:center;'
    'justify-content:center;position:relative;background:none!important;'
    'border:0!important;padding:6px 4px!important;border-radius:999px;'
# color 一定要帶 !important：全域有 button{color:#17293a!important}，不帶的話
    # 這顆 icon 會變成深藍黑，比旁邊的分頁 icon 暗一大截（實測筆畫亮度 78 vs
    # 123，差 45）。background 與 border 之前已經踩過同一個坑，color 漏掉了。
    'color:#51606f!important;cursor:pointer;transition:color .16s}'
# 按住時的外觀完全交給真正的膠囊（.tabcap）——它會滑過來、放大、變成全透
    # 折射環，跟停在任何一個分頁上時一模一樣。這裡不再自己畫泡泡。
    '.baract.hl{color:#c98a1e!important}'
    '.baract.hl svg{opacity:1}'
    '.baract svg{position:relative;z-index:1}'
# 描邊粗細與淡度要跟其他分頁 icon 一致（.ic 是 opacity .8、stroke-width 1.8）。
    # 原本是全不透明加 stroke 2，並排時明顯比鄰居黑一階，一看就不是同一組。
    '.baract svg{width:32px;height:32px;display:block;fill:none;position:relative;z-index:1;'
    'opacity:.8;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;'
    'stroke-linejoin:round}'
    '.baract.press svg{opacity:1}'
    '.baract:hover{color:#c98a1e!important}'
    '.baract:focus:not(:focus-visible){outline:none}'
# 搜尋只留一個入口：頁面上原本那個搜尋框收起來，改由右下角放大鏡開啟的
    # 搜尋面板。面板裡放的就是「原本那兩個節點」（.searchwrap 與 #res），
    # 開啟時搬進來、關閉時搬回原位——搜尋邏輯完全沒動，也不必擔心 SPA 換頁
    # 之後節點被換掉（每次開啟都重新找）。
    '.searchwrap,#res{display:none}'
    '.searchpane .searchwrap,.searchpane #res{display:block}'
    '.searchpane{position:fixed;inset:0;z-index:70;display:none;'
# 這頁沒有全域 box-sizing 重置，不寫的話 fitVV 設的 height 會再加上一份
    # 內距（含安全區），面板整個比可見區高，貼底的 sheet 被推出畫面。
    'box-sizing:border-box;'
    'background:rgba(23,41,58,0);transition:background-color .26s ease;'
    '-webkit-backdrop-filter:blur(10px) saturate(1.2);'
    'backdrop-filter:blur(10px) saturate(1.2);'
    'align-items:flex-end;justify-content:center;'
    'padding:0 10px calc(env(safe-area-inset-bottom,0px) + 10px)}'
    '.searchpane.on{display:flex}'
    '.searchpane.shown{background:rgba(23,41,58,.42)}'
    '@media(min-width:560px){.searchpane{align-items:center;padding:10px}}'
    '.searchsheet{background:rgba(245,248,251,.97);width:100%;max-width:560px;'
# sheet 自己也要 border-box：不然 fitVV 算出來的 max-height 只框到內容盒，
    # 上下內距 30px 與 2px 邊框都是外加的，整張會比上限高 32px 而頂出畫面。
    'box-sizing:border-box;'
# min-height:0 一定要寫：sheet 是 flex item，flex item 的自動最小尺寸是內容高度，
    # 不寫的話 height／max-height 都會被內容撐破（實測 height:734 卻算出 766）。
    'max-height:calc(100vh - 100px);min-height:0;overflow-y:auto;border-radius:28px;'
    'border:1px solid rgba(190,206,222,.95);'
# 內距對齊 Mindrise 的 sheet（20/22），兩邊打開來留白一致。
    'padding:10px 20px 22px;'
    'box-shadow:0 18px 50px -14px rgba(30,60,100,.45),'
    'inset 0 1.5px 0 rgba(255,255,255,1)}'
# grabber 要能被抓，所以是真的元素不是 ::before（偽元素掛不上事件）。
    # 它同時也是關閉鈕：點一下＝關掉，鍵盤與讀螢幕也走得通，所以拿掉 ✕ 不會少一條路。
    '.sheet-grab{display:block;position:sticky;top:0;z-index:3;width:100%;'
    'background:none!important;border:0!important;color:inherit!important;'
    'padding:6px 0 12px;cursor:grab;touch-action:none}'
    '.sheet-grab:active{cursor:grabbing}'
    '.sheet-grab i{display:block;width:38px;height:5px;margin:0 auto;'
    'border-radius:999px;background:rgba(90,110,130,.32);transition:background .15s}'
    '.sheet-grab:hover i{background:rgba(90,110,130,.5)}'
    '.searchsheet{transition:margin-bottom .3s cubic-bezier(.32,.72,0,1)}'
    '.searchsheet.dragging{transition:none}'
    '.searchpane-head{margin-bottom:10px}'
    '.searchpane-head b{font-size:17px;color:#17293a}'
# 說明文字放在標題與輸入框之間（與 Mindrise 的 sheet 同一個結構）。
    # 引擎原本那段說明在 #res 裡、位置在輸入框「下面」；搜尋前它是 #res 的
    # 唯一內容，用 :only-child 把它藏起來就不會重複，一有結果它本來就會被換掉。
    '.searchpane-sub{margin:0 0 12px;font-size:13.5px;line-height:1.7;color:#5b6d80}'
    '.searchpane #res>.muted:only-child{display:none}'
    '.searchpane .searchwrap{margin:0 0 8px}'
# 搜尋框拿掉長方形描邊與 focus 外框，改成 iOS 搜尋列那種「圓角填色」。
    '.searchpane .searchwrap input,'
    '.searchpane .searchwrap input:focus,'
    '.searchpane .searchwrap input:focus-visible{'
    'border:0 none transparent!important;border-color:transparent!important;'
    'border-radius:999px!important;'
    'outline:0 none transparent!important;outline-color:transparent!important;'
    'box-shadow:none!important;'
    'background:rgba(120,140,165,.12)!important;'
    'padding:13px 18px!important;'
    'font-size:16px!important;'
    '-webkit-appearance:none!important;appearance:none!important;'
    '-webkit-tap-highlight-color:transparent}'
    '.searchpane .searchwrap input:focus{background:rgba(120,140,165,.17)!important}'
    '.tabbar a.tab{flex-direction:row!important;justify-content:center!important;'
    # 高度對齊原生浮動膠囊列：tab 26px icon + 上下 9px = 44px（Apple 的最小
    # 觸控目標就是 44pt，再矮就不好按），加上 bar 自己的 6px padding 與 1px
    # 邊框 → 整條 56px。原本 15px 讓 tab 56px、整條 70px，比原生厚了一截。
    'padding:6px 4px!important;gap:0!important}'
    '.tabbar a.tab .ic{color:#51606f!important;opacity:.8;transition:color .16s,opacity .18s,transform .18s}'
    # 有膠囊(JS 在)時，選取色只跟著 .hl 走；.on 但沒 .hl 的退回灰
    '.tabbar.hasthumb a.tab.on:not(.hl) .ic{color:#51606f!important;opacity:.8}'
    '.tabbar a.tab .ic svg{width:32px;height:32px;display:block}'
    # liquid glass 不變；選中＝線條圖示上色（不再上移 1px：icon 要正對膠囊中心）
    '.tabbar a.tab.on .ic,.tabbar a.tab.hl .ic'
    '{color:#c98a1e!important;opacity:1;filter:none!important}'
    # 選取指示：琥珀淡底膠囊（拖曳 .thumb 已移除，改靜態底）
    # .on 靜態琥珀底：只在拖曳膠囊 JS 沒跑時當備援指示（JS 有跑 → .hasthumb 關掉它、
    # 改由 .tabcap 玻璃膠囊表示，見 patch_tabthumb）
    # 一開始就透明：這塊琥珀底原是「JS 沒跑時的備援指示」，但 JS 跑起來前會先畫出來，
    # 等 .tabcap 玻璃膠囊建立才被蓋掉 → 使用者看到「先閃琥珀再變正常」。
    # 選取狀態本來就由圖示的琥珀色表示（有無 JS 都成立），底色不需要。
    '.tabbar a.tab.on{background:transparent!important}'
    # 底部膠囊玻璃＝頂欄（brandbar）完全同款：同底色 .75、backdrop-filter 交給 maxglass。
    # ★ iOS 真兇（A/B 實證）：頂欄 brandbar 用 left:0;right:0（無 transform）→ 毛玻璃正常；
    #   分頁列用 transform:translateX(-50%) → 毛玻璃失效變透明（WebKit 已知 bug：元素帶
    #   transform 會讓 backdrop-filter 不作用）。解法＝比照頂欄，改 left:0;right:0;margin:auto
    #   置中（不靠 transform），並清掉 view-transition-name（同樣會破壞 backdrop）。
    # ★ Liquid Glass 質感三件套（皆為純 CSS，不新增元素、不加 transform → iOS 安全）：
    #   1) 邊緣折射：由 glassmap.png 負責（位移集中在外緣、中心中性）
    #   2) 方向性高光：左上緣亮弧＋右下緣微弱反射（模擬單一光源），取代原本均勻白線
    #   3) 厚度：底緣內陰影，讓它從「貼紙」變成「有厚度的玻璃板」
        # 寬度對齊頂欄：brandbar 左右內距 16px，分頁列原本卻各留 33px → 兩條 bar 的
    # 邊界線對不齊，看起來「不夠寬/縮成一團」。改成同樣 16px（桌面上限 440px）。
# 底部這一組＝左邊的分頁膠囊 ＋ 右邊一顆獨立圓鈕（iOS 相簿那種排法）。
    # 兩者各自 fixed，靠 --bargrp 這條共同的「群組寬度」對齊：膠囊貼群組左緣、
    # 圓鈕貼群組右緣。刻意不用共同的 flex 容器包起來——分頁列是 backdrop-filter
    # 元素，多包一層容器容易連帶影響它的合成層。與 Mindrise 同一套變數。
# 尺寸對齊 iOS 原生浮動列（量 Threads 截圖 1179x2556、3x）：高 60.3px、
    # 左右邊距各 21px、離螢幕底 22px。以下就是照這組來的。
    # --barh 拿掉：圓鈕搬進 bar 之後就沒有東西參照它了。
    ':root{--bargrp:min(440px,calc(100vw - 42px));'
    '--barbot:max(8px,calc(env(safe-area-inset-bottom,0px) - 12px))}'
    '.tabbar{width:var(--bargrp)!important;'
# 1px 邊框 + 8 + tab 44 + 8 + 1px = 62。Threads 量到 61.3，而且它的圖示只有
    # 22px、上下各留 19.5px——留白比圖示還寬。我們原本 26px 圖示擠在同樣高度
    # 裡，看起來就侷促，侷促讀起來就矮。圖示改 22、tab 內距補到 11（維持 44px
    # 觸控目標），留白就跟 Threads 一樣是 20/22/20。
    'padding:8px!important;'
    # 位置：原本是 11px + safe-area。iPhone 的 safe-area-inset-bottom 約 34px，
    # 兩個相加＝離螢幕底部 45px，浮太高。改成從安全區往下收 8px：
    #   iPhone 26px（原 45）／沒有 home indicator 的裝置 8px（原 11）
    # 浮動膠囊列本來就會稍微進到安全區裡（Threads 那種），貼齊安全區邊界反而
    # 會顯得懸空。max() 保底，避免小螢幕貼到見底。與 Mindrise 用同一條規則。
    'bottom:var(--barbot)!important;'
    'left:calc(50% - var(--bargrp)/2)!important;right:auto!important;'
    'transform:none!important;'
    'margin-left:0!important;margin-right:0!important;'
    'view-transition-name:none!important;'
# bar 的底色要跟膠囊同一種材質。原本 .72 太透，底下的字直接穿出來，膠囊那塊
    # 卻是糊的——量出來 bar 區的像素變異是膠囊區的 2.5 倍，看起來就像「半透明
    # 的 bar 上面貼了一塊不透明的白」。提到 .90 之後兩區的遮蔽程度相同（1.0 倍），
    # 整條讀起來才是同一片玻璃。
    'background:rgba(245,248,251,.90)!important;'
    'border:1px solid rgba(216,226,236,.9)!important;'
    'box-shadow:'
    '0 10px 30px rgba(30,60,100,.14),'                      # 落影
    '0 2px 6px rgba(30,60,100,.07),'                        # 接觸影
    'inset 0 0 0 1px rgba(255,255,255,.30),'                # 內圈細光環（玻璃邊界）
    'inset 0 1.5px 0 rgba(255,255,255,.95),'                # 上緣鏡面亮線
    'inset 3px 4px 10px -6px rgba(255,255,255,.95),'        # 左上柔光弧
    'inset -3px -4px 10px -7px rgba(255,255,255,.55),'      # 右下微弱反射
    'inset 0 -1.5px 3px -1px rgba(70,95,125,.26)'           # 底緣厚度陰影
    '!important}'
    '</style>'
)
BAR_STYLE_RE = re.compile(r'<style id="barglass">.*?</style>', re.S)


# --- 拿掉舊的「加入自選股」浮動 ＋ 鈕 ------------------------------------
# 個股頁右下角原本就有一顆 54px 的 ＋（focus 自選股輸入框），現在放大鏡圓鈕
# 也在同一個角落：兩顆圓鈕上下疊著、相距 20px，大小還差 4px（54 vs 58）、
# 左緣也沒對齊，看起來就是多出來的東西。
# ＋ 的功能只是捲到並 focus #wlq，那個輸入框本來就在頁面上，拿掉只少一個
# 捷徑、不會少一條路。
FAB_RE = re.compile(
    r'<button class="fab".*?</button>\s*'
    r'<script>\s*\(function\(\)\{var f=document\.getElementById\(.fab.\).*?\}\);\}\)\(\);\s*</script>',
    re.S)


def patch_fab(html):
    """移除舊的浮動 ＋ 鈕（與右下角的放大鏡圓鈕重複）。"""
    out = FAB_RE.sub('', html)
    return out, (out != html)


def patch_barglass(html):
    """導覽列：emoji 換 SF 風線條 SVG + 無字 + 玻璃；補 aria-label。有 tabbar 的頁面。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    # 0) 舊版個股 icon（放大鏡，語意跑掉）→ 上升趨勢線（就地遷移，absent-after）
    html = html.replace('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
                        '<path d="M3 18l5.5-6.5 4 4L20 6.5"/><path d="M15 6.5h5v5"/>')
    # 0c) 觀點 icon 單泡泡 → 雙泡泡（已部署頁面的就地遷移）
    html = html.replace(
        '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v8a1.5 1.5 0 0 1-1.5 '
        '1.5H9l-4 4v-4H5.5A1.5 1.5 0 0 1 4 13.5z"/>',
        '<path d="M5 4.5h8A2.5 2.5 0 0 1 15.5 7v3.5A2.5 2.5 0 0 1 13 13H8.2l-3.2 2.8V13'
        'A2.5 2.5 0 0 1 2.5 10.5V7A2.5 2.5 0 0 1 5 4.5z"/>'
        '<path d="M18.2 9.2A2.5 2.5 0 0 1 20.7 11.7v3.4a2.5 2.5 0 0 1-2.5 2.5h-.3v2.6'
        'l-3-2.6h-3.2"/>')
    # 0a2) 個股趨勢線加高（原高度僅 9/24，全場最扁，與其他 icon 視覺重量不一致）
    html = html.replace('<path d="M3 17l5.5-5.5 4 4L20 8"/><path d="M15 8h5v5"/>',
                        '<path d="M3 18l5.5-6.5 4 4L20 6.5"/><path d="M15 6.5h5v5"/>')
    # 0b) 進場 icon 長條圖 → 儀表指針（與「個股」的趨勢線區隔；呼應首頁儀表）
    html = html.replace('<path d="M5 20V11"/><path d="M12 20V4"/><path d="M19 20v-6"/>',
                        '<path d="M4.4 17.2a8.6 8.6 0 1 1 15.2 0"/>'
                        '<path d="M12 16.4l3.8-6.2"/>'
                        '<circle cx="12" cy="16.4" r="1.35"/>')
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


# --- 拆掉引擎的分頁列拖曳膠囊（SWIPE_JS）------------------------------------
# 為什麼：它在分頁列裡動態插入一個會合成的 .thumb 子元素、還攔截 tab 點擊
# （preventDefault）。iOS WebKit 上「backdrop-filter 元素若含被提升為合成層的
# 子元素」毛玻璃會失效——這就是分頁列初始有霧、JS 一跑（或換頁後）霧就消失、
# 頂欄(靜態、無此腳本)卻一直正常的原因。拿掉它→分頁列變回像頂欄的靜態元素，
# 玻璃穩定；選取狀態改由 .on 的琥珀色圖示表示；點擊走原生 <a href> 導頁。
# （也符合「不要特效」：滑動膠囊本身就是特效。）
TABDRAG_RE = re.compile(
    r'<script>(?:(?!</script>)[\s\S])*?window\.__tabdrag(?:(?!</script>)[\s\S])*?</script>')


def patch_striptabdrag(html):
    # 選取指示已由 BAR_STYLE 的 .on 琥珀淡底處理；這裡只負責移除拖曳腳本本身。
    if 'window.__tabdrag' not in html:
        return html, False
    new = TABDRAG_RE.sub('', html)
    return new, (new != html)


# --- 懸浮可拖曳膠囊（列內版，但去除會破壞毛玻璃的合成觸發）--------------------
# 要「圖示亮 + 完整玻璃膠囊」只能把膠囊放回圖示「後面」（列內、z-index:0，圖示 z:1
# 蓋在上面）。當初破壞毛玻璃的不是「列內子元素」本身（tab 連結本來就是有 z-index
# 的定位子元素、玻璃照樣正常），而是膠囊的 transform 過場＋拖曳時的 backdrop-filter
# 這兩個「合成觸發」，加上 SPA 讓列跨頁不重建而永不恢復。現在 SPA 已關（整頁重載）、
# 且此膠囊只用 left/top/width/height 過場（不含 transform、不含 backdrop-filter、
# 無 will-change），不會被提升為合成層→毛玻璃應保持。用獨立 class .tabcap 避開引擎
# 舊 .thumb 樣式（那份含 transform 過場）。
TABTHUMB = (
    '<style id="tabthumbcss">'
    # 灰白玻璃膠囊，放在圖示後面（z-index:0）→ 圖示全亮蓋在上面；不透明灰底沒關係。
    # margin:-1px：JS 用 rect 相減定位、但 absolute 以「邊框內側」為基準，
    # 不補償會右下各偏 1px（分頁列有 1px border）→ 看起來沒置中
    '.tabbar .tabcap{position:absolute;z-index:0;top:6px;left:6px;pointer-events:none;'
    'margin:-1px 0 0 -1px;'
    'border-radius:999px;'
    # 速度對齊 iOS 原生（約 .35s，Apple 慣用的 cubic-bezier(.32,.72,0,1)）：這段動畫在點擊時只播得到前半段就被 pointerup
    # 打斷，太快的話根本看不出膠囊有「滑」過去。放大也一起放慢到 .24s。
    # 與 Mindrise 的 .lens 用同一組數值。
    'transition:left .35s cubic-bezier(.32,.72,0,1),top .18s,width .18s,height .18s}'
    # 靜止外觀與拖曳外觀各自一層，用 opacity 交叉淡入，而不是換 background。
    # CSS 不能在 linear-gradient 和 radial-gradient 之間內插（box-shadow 清單長度
    # 不同也一樣），直接切 background 的話外觀會在第一格就硬跳完、尺寸卻還要
    # .18s 才長好——兩件事完全不同步，那就是「變化的瞬間」看起來卡的原因。
    # 交叉淡入之後，外觀和尺寸走同一條 .18s 曲線。與 Mindrise 的 .lens 同作法。
    '.tabbar .tabcap::before,.tabbar .tabcap::after{content:"";position:absolute;'
    'inset:0;border-radius:inherit;transition:opacity .18s}'
    # 靜止：膠囊也做成玻璃：降低灰底不透明度（原 .92 像一坨實心灰，與周圍玻璃打架）、
    # 加自己的上緣亮線與內光環 → 讀起來像「更厚的一片玻璃」浮在 bar 裡。
    # 不用 backdrop-filter（玻璃裡再放玻璃＝iOS 毛玻璃失效的老地雷）。
    '.tabbar .tabcap::before{opacity:1;'
    'background:linear-gradient(180deg,rgba(255,255,255,.62),rgba(255,255,255,.18)),'
    'rgba(196,208,220,.55);'
    'box-shadow:inset 0 1.5px 0 rgba(255,255,255,.9),'
    'inset 0 0 0 1px rgba(255,255,255,.45),'
    'inset 0 -1px 2px -1px rgba(70,95,125,.18),'
    '0 2px 8px -3px rgba(90,105,120,.3)}'
    # 拖曳中：整顆放大、中央全透（底下內容直接透出）、只有四周折射亮環。
    # 淺色主題下亮環用帶藍的灰，白 bar 上才看得見；不用 transform／
    # backdrop-filter（合成觸發＋巢狀玻璃＝iOS 毛玻璃失效）。
    '.tabbar .tabcap::after{opacity:0;'
    'background:radial-gradient(closest-side,rgba(255,255,255,0) 58%,'
    'rgba(120,140,165,.10) 84%,rgba(120,140,165,.24) 100%);'
    'box-shadow:inset 0 0 0 1px rgba(255,255,255,.9),'
    'inset 0 1.5px 1px rgba(255,255,255,1),'
    'inset 0 -1px 2px -1px rgba(70,95,125,.28),'
    '0 4px 14px -5px rgba(30,60,100,.35)}'
    '.tabbar .tabcap.grab::before{opacity:0}'
    '.tabbar .tabcap.grab::after{opacity:1}'
    # 手指真的在拖的時候要即時跟手：只停掉膠囊自己的幾何過場，兩層外觀的
    # 交叉淡入要留著，不然按下後馬上滑動，外觀又會變回瞬間硬跳。
    '.tabbar .tabcap.drag{transition:none}'
    # 曾經在這裡讓膠囊自己吃 #lglass-cap 折射（真的扭曲背後內容）。已移除：
    # 淺色主題下那顆濾鏡不是折射背景，而是把 glassmap 這張法線貼圖本身畫出來
    # ——拖曳中的膠囊變成一坨帶斜向漸層的不透明灰。桌機、手機寬度都重現得到。
    # 「放大＋中央全透＋周圍折射亮環」本來就由上面的 radial-gradient 與內外
    # 陰影完成，不需要巢狀玻璃（那本來就是本專案自己列的 iOS 地雷）。
    # 圖示確保在膠囊之上、且選取時不再另加靜態底（由膠囊表示）
    '.tabbar a.tab{position:relative;z-index:1}'
    '.tabbar.hasthumb a.tab.on{background:transparent!important}'
    # 桌機用滑鼠按分頁時，連結會拿到焦點、瀏覽器畫出一圈粗黑外框（手機不會）。
    # 只在「非鍵盤操作」時取消，鍵盤 Tab 過去仍然看得到焦點框。
    '.tabbar a.tab:focus:not(:focus-visible){outline:none}'
    '</style>'
    '<script id="tabthumb">(function(){'
    'if(window.__tabthumb)return;window.__tabthumb=1;'
    'function mkAction(){'
    'if(document.querySelector(".baract"))return;'
    'if(!document.querySelector(".tabbar"))return;'
    'var a=document.createElement("button");a.className="baract";'
    'a.type="button";a.setAttribute("aria-label","搜尋個股");'
    'a.title="搜尋個股";'
    'a.innerHTML=\'<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="11" cy="11" r="6.6"/><path d="M16 16l4.6 4.6"/></svg>\';'
    'function grabDrag(box,grab){if(!box||!grab)return;'
    'var sy=0,dy=0,moved=false,on=false,raf=0,pend=0;'
    'function apply(){raf=0;box.style.marginBottom=(-pend)+"px";}'
    'grab.addEventListener("pointerdown",function(e){'
    'if(e.pointerType==="mouse"&&e.button!==0)return;'
    'on=true;moved=false;sy=e.clientY;dy=0;pend=0;box.classList.add("dragging");'
    'try{grab.setPointerCapture(e.pointerId);}catch(err){}});'
    'grab.addEventListener("pointermove",function(e){if(!on)return;'
    'dy=e.clientY-sy;if(Math.abs(dy)>3)moved=true;'
    'pend=dy>0?dy:0;'
    'if(!raf)raf=requestAnimationFrame(apply);});'
    'function end(){if(!on)return;on=false;'
    'if(raf){cancelAnimationFrame(raf);raf=0;}'
    'box.classList.remove("dragging");'
    'if(dy>90){closePane();return;}'
    'box.style.marginBottom="";'
    'if(!moved)closePane();}'
    'grab.addEventListener("pointerup",end);'
    'grab.addEventListener("pointercancel",end);}'
# iOS 鍵盤升起時 layout viewport 不會縮，只有 visual viewport 會縮——貼底的
    # fixed 面板因此整片躲到鍵盤後面（實測 sheet 完全看不到）。把面板改成釘在
    # visual viewport 上：top 取 offsetTop、height 取 vv.height，sheet 就一定
    # 落在鍵盤上方。沒有 visualViewport 的環境維持原本的 inset:0。
    'function fitVV(){var pn=document.querySelector(".searchpane");'
    'if(!pn||!pn.classList.contains("on"))return;'
    'var vv=window.visualViewport;if(!vv)return;'
    'pn.style.top=vv.offsetTop+"px";pn.style.height=vv.height+"px";'
    'pn.style.bottom="auto";'
# 鍵盤升起時 home indicator 那塊安全區已經被鍵盤蓋住，但
    # env(safe-area-inset-bottom) 還是回報 34px，面板繼續替它留位 →
    # sheet 底部和鍵盤之間多出 34px 空隙。鍵盤在的時候只留 10px。
    # 用 layout viewport 判斷：它不會隨鍵盤縮，只有 visual viewport 會。
    'var kbUp=vv.height<document.documentElement.clientHeight-80;'
    'pn.style.paddingBottom=kbUp?"10px":"";'
    'var shv=pn.querySelector(".searchsheet");'
    'if(shv){var pcs=getComputedStyle(pn);'
    'var pt=parseFloat(pcs.paddingTop)||0,pb=parseFloat(pcs.paddingBottom)||0;'
    'shv.style.maxHeight=Math.max(160,vv.height-pt-pb-24)+"px";}}'
    'function bindVV(){var vv=window.visualViewport;if(!vv)return;'
    'vv.addEventListener("resize",fitVV);vv.addEventListener("scroll",fitVV);}'
    'function unbindVV(){var vv=window.visualViewport;if(!vv)return;'
    'vv.removeEventListener("resize",fitVV);vv.removeEventListener("scroll",fitVV);}'
    'function pane(){var pn=document.querySelector(".searchpane");if(pn)return pn;'
    'pn=document.createElement("div");pn.className="searchpane";'
    'pn.innerHTML=\'<div class="searchsheet">'
    '<button class="sheet-grab" type="button" '
    'aria-label="關閉搜尋（也可以往下滑關掉、往上滑展開）"><i></i></button>'
    '<div class="searchpane-head"><b>搜尋個股</b></div>'
# 說明這行不要再寫檔數與「點結果展開明細」——底下輸入框的 placeholder 已經
    # 有了（而且那個數字是引擎從 universe.json 算的，會跟著更新）。原本這裡寫死
    # 1972，實際是 1968，兩行上下並排卻報不同的數字。
    '<p class="searchpane-sub">輸入代碼或名稱，即時查全市場。</p></div>\';'
    'pn.addEventListener("click",function(e){if(e.target===pn)closePane();});'
    'grabDrag(pn.querySelector(".searchsheet"),pn.querySelector(".sheet-grab"));'
    'document.body.appendChild(pn);return pn;}'
    'function openPane(){'
    'var sw=document.querySelector(".searchwrap");if(!sw)return false;'
    'var res=document.getElementById("res");'
    'var pn=pane();if(pn.classList.contains("on"))return true;'
    'pn.__home=sw.parentNode;pn.__after=(res?res.nextSibling:sw.nextSibling);'
    'var sh=pn.querySelector(".searchsheet");'
    'sh.appendChild(sw);if(res)sh.appendChild(res);'
# 頂欄是 fixed 的，面板若從 0 開始，標題與 ✕ 會被它蓋住。用實測的頂欄底緣
    # 當上邊距（getBoundingClientRect 已含安全區），比寫死數值可靠。
    'pn.classList.add("on");document.body.style.overflow="hidden";'
    'fitVV();bindVV();'
# 自動聚焦要在 sheet 還沒被推到畫面外之前做。iOS 只有在使用者手勢當下、
    # 而且目標真的在畫面上時才肯把鍵盤叫起來；等 sheet 挪到畫面外之後再
    # focus，WebKit 會安靜地不理你（Chromium 兩種順序都給焦點，所以這個
    # 差別只在真機上看得出來）。
    'var q0=document.getElementById("q");'
    'if(q0){try{q0.focus({preventScroll:true});}catch(e){q0.focus();}}'
    'sh.classList.add("dragging");'
    'sh.style.marginBottom=(-(sh.offsetHeight+40))+"px";'
    'requestAnimationFrame(function(){'
    'sh.classList.remove("dragging");sh.style.marginBottom="";'
    'pn.classList.add("shown");});'
    'return true;}'
    'function closePane(){var pn=document.querySelector(".searchpane");'
    'if(!pn||!pn.classList.contains("on")||pn.__closing)return;'
    'var shx=pn.querySelector(".searchsheet");'
    'pn.__closing=1;pn.classList.remove("shown");'
    'if(shx){shx.classList.remove("dragging");'
    'shx.style.marginBottom=(-(shx.offsetHeight+40))+"px";}'
    'setTimeout(function(){pn.__closing=0;finishClose();},260);}'
    'function finishClose(){var pn=document.querySelector(".searchpane");'
    'if(!pn)return;'
    'var sw=pn.querySelector(".searchwrap"),res=pn.querySelector("#res");'
    'if(pn.__home&&sw){pn.__home.insertBefore(sw,pn.__after||null);'
    'if(res)pn.__home.insertBefore(res,pn.__after||null);}'
    'var sh=pn.querySelector(".searchsheet");'
    'if(sh){sh.style.marginBottom="";sh.style.maxHeight="";sh.classList.remove("dragging");}'
    'unbindVV();pn.style.top="";pn.style.height="";pn.style.bottom="";'
    'pn.style.paddingBottom="";'
    'pn.classList.remove("on");document.body.style.overflow="";}'
    'document.addEventListener("keydown",function(e){'
    'if(e.key==="Escape")closePane();});'
# 動作本體掛在元素上，讓 bar 的膠囊邏輯在 pointerup 直接呼叫——bar 會
    # setPointerCapture，按鈕自己的 click 不一定收得到。click 只留給沒有
    # 指標的情況（鍵盤 Enter／輔助技術，那時 detail===0）。
    'a.__act=function(){'
    'var pn=document.querySelector(".searchpane");'
    'if(pn&&pn.classList.contains("on")){closePane();return;}'
    'if(openPane())return;'
    'if(window.__spaGo){window.__spaGo("stocks.html");'
    'var n=0,t=setInterval(function(){if(openPane()||++n>20)clearInterval(t);},100);}'
    'else{location.href="stocks.html";}};'
    'a.addEventListener("click",function(e){if(e.detail===0)a.__act();});'

# 放進 bar 裡面，第 2、3 個分頁中間。找不到第 3 個分頁就退回接在最後，
    # 至少不會整顆消失。
    'var nav=document.querySelector(".tabbar");'
    'var host=nav.querySelector(".inner")||nav;'
    'var tabs=host.querySelectorAll("a.tab");'
    'if(tabs.length>2)host.insertBefore(a,tabs[2]);else host.appendChild(a);}'
    'var order=["index.html","stocks.html","perspectives.html","news.html"];'
    'function curIdx(){var f=(location.pathname.split("/").pop()||"").toLowerCase();'
    'return f==="stocks.html"?1:f==="perspectives.html"?2:f==="news.html"?3:0;}'
    'function start(){'
    'var bar=document.querySelector(".tabbar");if(!bar)return;'
    'mkAction();'
    'var tabs=[].slice.call(bar.querySelectorAll("a.tab"));if(tabs.length<2)return;'
# 膠囊會停的每一站：四個分頁 ＋ 中間那顆動作鈕。動作鈕不是分頁（place()
    # 仍只認 tabs），但拖曳時膠囊照樣滑得過去、停得住，手感跟分頁一樣。
    'var stops=[].slice.call(bar.querySelectorAll("a.tab,.baract"));'
    'function isAct(i){return !!(stops[i]&&stops[i].classList.contains("baract"));}'
    'function tabIdx(i){return tabs.indexOf(stops[i]);}'
    'function stopIdx(t){return stops.indexOf(tabs[t]);}'
    'bar.classList.add("hasthumb");'
    'var cap=document.createElement("span");cap.className="tabcap";bar.insertBefore(cap,bar.firstChild);'
    'var cur=curIdx(),over=0,dragging=false;'
# 膠囊要跟著 bar 一起長。bar 這幾輪從 58 長到 62，膠囊卻一直跟著 tab 停在 44，
    # 比例從 76% 掉到 71%，看起來就縮水了。靜止改成比 tab 高 4px（48，佔 bar
    # 77%，貼回最初的 76%），上下各外擴 2px 保持置中。
    'function place(i,anim){var br=bar.getBoundingClientRect(),r=tabs[i].getBoundingClientRect();'
    'cap.classList.toggle("drag",!anim);'
    'cap.style.width=r.width+"px";cap.style.height=(r.height+8)+"px";'
    'cap.style.top=(r.top-br.top-4)+"px";cap.style.left=(r.left-br.left)+"px";}'
    'function nearest(x){var best=0,bd=1e9;for(var k=0;k<stops.length;k++){'
    'var r=stops[k].getBoundingClientRect(),c=r.left+r.width/2,d=Math.abs(x-c);'
    'if(d<bd){bd=d;best=k;}}return best;}'
    # 高亮跟著膠囊走：膠囊滑到誰身上，誰的圖示就變琥珀色（原本那顆同時退回灰）
    'function hl(i){for(var k=0;k<stops.length;k++)stops[k].classList.toggle("hl",k===i);}'
    'function follow(x){var br=bar.getBoundingClientRect();'
    'var r0=stops[0].getBoundingClientRect();'
    'cap.style.width=(r0.width+26)+"px";cap.style.height=(r0.height+20)+"px";'
    'cap.style.top=(stops[over].getBoundingClientRect().top-br.top-10)+"px";'
    'var w=cap.offsetWidth;'
    # 夾限用「膠囊中心」對齊頭尾分頁中心：放大後的膠囊會微微超出 bar 兩端，
    # 但拖到底時正好以第一顆／最後一顆 icon 為中心（夾膠囊邊緣會偏向內側）
    'var r1=stops[0].getBoundingClientRect(),rN=stops[stops.length-1].getBoundingClientRect();'
    'var loC=r1.left+r1.width/2-br.left,hiC=rN.left+rN.width/2-br.left;'
    'var cx=Math.max(loC,Math.min(hiC,x-br.left));var L=cx-w/2;'
    'cap.classList.add("drag");cap.style.left=L+"px";'
    'var o=nearest(x);if(o!==over){over=o;hl(o);}}'
    'requestAnimationFrame(function(){place(cur,false);hl(stopIdx(cur));});'
    # 按下就放大：把 follow() 的放大尺寸也套在 pointerdown 當下，膠囊以按到的
    # 那顆分頁為中心撐開。原本按下只換成 .grab（變透明），放大是移動時才由
    # follow() 做的——真實觸控因為手指一定有幾 px 位移所以看起來像有放大，
    # 但純粹的點擊沒有。移除 .drag 讓這一下走過場動畫（follow 之後會加回去）。
    # 回傳目標 left：up() 要用它算位移。不能在設完 style.left 之後讀 offsetLeft
    # ——過場還沒開始跑，讀到的是動畫前的舊值，位移會算成 0、收尾就提早了。
    'function grow(i){var br=bar.getBoundingClientRect(),r=stops[i].getBoundingClientRect();'
    'var w=r.width+26,h=r.height+20;'
    'cap.style.width=w+"px";cap.style.height=h+"px";'
    'cap.style.top=(r.top-br.top-10)+"px";'
    'var L=r.left+r.width/2-br.left-w/2;cap.style.left=L+"px";return L;}'
    'function down(x,e){dragging=true;over=nearest(x);cap.classList.add("grab");'
    'cap.classList.remove("drag");grow(over);hl(over);}'
    'function move(x,e){if(!dragging)return;follow(x);if(e.cancelable)e.preventDefault();}'
    # 放開之後的收尾：膠囊「維持放大＋全透」滑到目標分頁，等它真的到位了，才在
    # 那顆 icon 上方縮回原本大小、恢復不透明度。原本是放開當下就 remove("grab")
    # 並 place() 回正常尺寸，於是縮回與滑動同時發生——移動途中就變回不透明，
    # 形變也發生在兩顆 icon 之間的半路上。
    'var settling=false,settleTimer=0;'
    'function endSettle(t){settling=false;cap.classList.remove("grab");place(t,true);}'
    'function up(){if(!dragging)return;dragging=false;var t=over;'
# 停在動作鈕上：它不是分頁，不換頁也不留住膠囊——開 sheet，膠囊滑回目前選取
    # 的那個分頁。bar 的 setPointerCapture 會吃掉按鈕自己的 click，所以動作要
    # 在這裡發（a.__act 就是為此掛上去的）。
    'var act=isAct(t),home=act?stopIdx(curIdx()):t;'
    'hl(home);'
    'cap.classList.remove("drag");'          # 打開過場，讓它滑過去
    'var before=cap.offsetLeft;var L=grow(home);'     # 仍在 .grab：全程維持放大＋全透
    'var travel=Math.abs(L-before);'
    'settling=true;clearTimeout(settleTimer);'
    'settleTimer=setTimeout(function(){endSettle(tabIdx(home));},travel>2?175:100);'
    'if(act){var el=stops[t];if(el&&el.__act)el.__act();return;}'
    # 有 SPA 換頁時直接交給它：內容是即時抽換的，分頁列不重建，膠囊的滑動
    # 動畫會一路播完，所以完全不需要延遲。沒有 SPA（或它初始化失敗）才退回
    # 整頁重載，那時仍要等一下讓動畫播到一段落。
    'var ti=tabIdx(t);'
    'if(ti>=0&&ti!==curIdx()){if(window.__spaGo)window.__spaGo(order[ti]);'
    'else setTimeout(function(){location.href=order[ti];},260);}}'
    'if(window.PointerEvent){'
    'bar.addEventListener("pointerdown",function(e){if(e.button&&e.button!==0)return;'
    'down(e.clientX,e);try{bar.setPointerCapture(e.pointerId);}catch(_){}});'
    'bar.addEventListener("pointermove",function(e){move(e.clientX,e);});'
    'bar.addEventListener("pointerup",up);bar.addEventListener("pointercancel",up);'
    '}else{'
    'bar.addEventListener("touchstart",function(e){if(e.touches.length===1)down(e.touches[0].clientX,e);},{passive:true});'
    'bar.addEventListener("touchmove",function(e){if(e.touches.length===1)move(e.touches[0].clientX,e);},{passive:false});'
    'bar.addEventListener("touchend",up);bar.addEventListener("touchcancel",up);}'
    'for(var k=0;k<tabs.length;k++)tabs[k].addEventListener("click",function(e){e.preventDefault();});'
    'addEventListener("resize",function(){place(curIdx(),false);hl(curIdx());});'
    'addEventListener("pageshow",function(){place(curIdx(),false);hl(curIdx());});'
    # 給 SPA 換頁用：內容抽換後（尤其是上一頁／頁內連結那種不是從分頁列發起的），
    # 把膠囊與琥珀高亮重新對到目前網址對應的分頁上。
    # 收尾動畫進行中就別動：膠囊正維持放大＋全透滑向目標分頁，這時 place()
    # 會把它拉回正常尺寸，等於又變回「邊滑邊縮」。
    'window.__tabSync=function(anim){if(settling)return;'
    'var i=curIdx();place(i,anim!==false);hl(i);};'
    '}'
    'if(document.readyState!=="loading")start();else addEventListener("DOMContentLoaded",start);'
    '})();</script>'
)
TABTHUMB_RE = re.compile(r'<style id="tabthumbcss">.*?</script>', re.S)


def patch_tabthumb(html):
    """把可拖曳膠囊做成 body 層的獨立覆蓋層（不進分頁列→不破壞毛玻璃）。"""
    if '<nav class="tabbar">' not in html or '</body>' not in html:
        return html, False
    if TABTHUMB in html:
        return html, False
    orig = html
    html = TABTHUMB_RE.sub('', html)
    html = html.replace('</body>', TABTHUMB + '</body>', 1)
    return html, (html != orig)


# --- SPA 換頁（pjax）：只接管四個主分頁 -------------------------------------
# 歷史：這東西做過一次，後來被關掉，理由是「SPA 把 .tabbar 保留在 DOM 跨頁不
# 重建，一旦 iOS backdrop-filter 失效就永不恢復（換頁後霧消失、切回也沒有）」。
#
# 這一版重新打開，但針對那個根因做了處理：
#   1) 每次換頁後對 .tabbar／.topglass／.brandbar 做一次「玻璃重整」——用
#      !important 把 backdrop-filter 暫時設成 none、下一幀再拿掉，強迫 WebKit
#      重建背景層。等同重建元素的效果，但不動 DOM，所以膠囊的滑動動畫不會被
#      打斷（那正是保留分頁列的目的）。
#   2) 重整刻意排在滑動動畫走完之後（GLASSFIX_MS），萬一真的閃一下，也是閃在
#      使用者視線已經移到新內容的時候。
#   3) 只接管同目錄下的四個主分頁。個股頁、ETF、回測、外部連結一律走正常導頁，
#      風險面積壓到最小。
#   4) 任何一步出錯就 location.href 退回整頁重載。
#
# 要停用：把 SPANAV_JS 設成 ''，重跑一次腳本即可（patch 會把已注入的移除）。
GLASSFIX_MS = 400          # 玻璃重整時機；比膠囊收尾（175+180ms）稍晚
SPANAV_JS = (
    '<script id="spanav">(function(){'
    'if(window.__spanav)return;window.__spanav=1;'
    'if(!window.fetch||!window.DOMParser||!history.pushState)return;'
    # 只接管「同一層目錄」下的這四個檔名
    'var TABS={"index.html":1,"stocks.html":1,"perspectives.html":1,"news.html":1};'
    'function dirOf(p){return p.slice(0,p.length-(p.split("/").pop()||"").length);}'
    'function target(href){try{var u=new URL(href,location.href);'
    'if(u.origin!==location.origin)return null;'
    'if(dirOf(u.pathname)!==dirOf(location.pathname))return null;'
    'var f=u.pathname.split("/").pop()||"index.html";'
    'return TABS[f]?u.href:null;}catch(e){return null;}}'
    # 抓回來的文件放記憶體快取；閒置時預抓另外三個分頁
    'var CACHE={};'
    'function getDoc(href){if(CACHE[href])return Promise.resolve(CACHE[href]);'
    'return fetch(href,{credentials:"same-origin"}).then(function(r){'
    'if(!r.ok)throw new Error(r.status);return r.text();}).then(function(t){'
    'var d=new DOMParser().parseFromString(t,"text/html");CACHE[href]=d;return d;});}'
    # 換進來的 <script> 是惰性的，要換成新節點才會執行。
    # 內嵌的那幾支（圖表初始化）在頂層用 const/let 宣告全域變數，直接重跑會撞
    # 「Identifier 'X' has already been declared」→ 把它們串成一支、共用一個
    # 區塊作用域（見下方 runInline），既隔離掉上一頁的全域，彼此之間又還是
    # 看得見對方的 const/let。
    # 不重跑的基礎設施：這些是跨頁常駐的，重跑只會重複綁事件或直接壞掉
    'var SKIP={spanav:1,tabthumb:1,nativemode:1,zoomlock:1,brandbarjs:1};'
    'function rerun(doc){'
    # 外部腳本要連 <head> 一起掃：echarts 的 <script src> 就放在 head，
    # 只掃 body 會漏掉——從「沒有 echarts 的頁」（消息、個股）換到進場頁時，
    # 那顆庫因此永遠不會被載進來，圖表自然畫不出來。
    'var list=[].slice.call(doc.querySelectorAll("script"));'
    'var inline=[],ext=[];'
    'for(var i=0;i<list.length;i++){var s=list[i];'
    'if(s.id&&SKIP[s.id])continue;'
    'if(s.src){ext.push(s.src);continue;}'
    # head 裡的 inline 不重跑（那些是 meta 層級的設定，重跑沒意義）
    'if(!doc.body.contains(s))continue;'
    'if(s.type&&!/javascript/i.test(s.type))continue;'
    # service worker 註冊掛在 window load 上，換頁時那個事件不會再來，跳過
    'if(/serviceWorker/.test(s.textContent))continue;'
    'inline.push(s.textContent);}'
    # 外部腳本：live 文件沒有同一支才補進去（例如從 news 換到進場頁時
    # echarts 還沒被載過），載完再跑 inline
    'var need=[];'
    # 用 document.scripts 逐一比對，避免在字串裡再包一層引號（先前那版
    # querySelector 的巢狀引號被多跳脫了一層，整支 spanav 直接語法錯誤，
    # SPA 等於沒作用、每次換頁都悄悄退回整頁重載）
    'for(var e=0;e<ext.length;e++){var have=false,ss=document.scripts;'
    'for(var z=0;z<ss.length;z++){if(ss[z].src===ext[e]){have=true;break;}}'
    'if(!have)need.push(ext[e]);}'
    'function runInline(){'
    'var prev=document.getElementById("spa-page-js");'
    'if(prev)prev.parentNode.removeChild(prev);'
    'if(!inline.length)return;'
    'var n=document.createElement("script");n.id="spa-page-js";'
    # 原生載入時，每一支 <script> 是獨立執行但「共用同一個全域語彙環境」：
    # 前一支的 const DASH，後一支讀得到。之前為了錯誤隔離把每一支各包一層
    # try{}，等於把那些 const 關進各自的區塊 → 後面那支變成
    # 「ReferenceError: DASH is not defined」而整支中斷。首頁的儀表初始化正好
    # 就在那支後面，所以進場分數的指針畫不出來（容器有、setOption 沒跑到）。
    # 改法：整批共用「同一個」區塊 {…}。段與段之間看得見彼此的 const/let，
    # 而每次換頁都是全新的區塊，也就不會像獨立 <script> 那樣第二次造訪
    # 撞到「Identifier 'X' has already been declared」。
    # 沒有頂層 const/let/class 的段落仍各自包 try{}，保留錯誤隔離；
    # 誤判成「有」只是少一層隔離，不會出錯，所以寧可寬鬆。
    'var LEX=/^[ \\t]*(?:const|let|class)[\\s]/m;'
    'n.text="{"+inline.map(function(t){'
    'return LEX.test(t)?"\\n"+t+"\\n"'
    ':"\\ntry{"+t+"\\n}catch(e){console.error(e);}";}).join("\\n")+"\\n}";'
    'document.body.appendChild(n);}'
    'if(!need.length)return runInline();'
    'var left=need.length,done=function(){if(--left<=0)runInline();};'
    'for(var q=0;q<need.length;q++){var sc=document.createElement("script");'
    'sc.src=need[q];sc.onload=done;sc.onerror=done;document.head.appendChild(sc);}}'
    # 玻璃重整：暫時拿掉 backdrop-filter 再還原，逼 WebKit 重建背景層。
    # maxglass 那組規則帶 !important，所以這裡也必須用 important 才蓋得過。
    'function glassEls(){return document.querySelectorAll(".tabbar,.topglass,.brandbar");}'
    'function restoreGlass(){var e=glassEls();for(var i=0;i<e.length;i++){'
    'e[i].style.removeProperty("backdrop-filter");'
    'e[i].style.removeProperty("-webkit-backdrop-filter");}}'
    'function refreshGlass(){var e=glassEls();for(var i=0;i<e.length;i++){'
    'e[i].style.setProperty("backdrop-filter","none","important");'
    'e[i].style.setProperty("-webkit-backdrop-filter","none","important");}'
    # 還原用 setTimeout 而不是 requestAnimationFrame：rAF 在背景分頁會被節流、
    # 甚至整個不觸發，只要漏掉一次，毛玻璃就「永久」消失——那比原本要修的問題
    # 更糟。再補兩道保險：晚一點再掃一次、以及回到前景時掃一次。
    'setTimeout(restoreGlass,40);setTimeout(restoreGlass,400);}'
    'document.addEventListener("visibilitychange",function(){'
    'if(!document.hidden)restoreGlass();});'
    'var glassTimer=0;'
    # 換頁本體：只換 .wrap，分頁列留著（膠囊動畫才不會被打斷），
    # 再把新內容裡的 script 與兩個全站補丁腳本重跑一次
    # 目標頁 <head> 裡的樣式也要帶過來。只換 .wrap 的話，新頁面專屬的 CSS 完全
    # 沒有進來——實測 SPA 換到個股頁時，K 線容器從 316x170 塌成 150x0
    # （css height 0px），echarts 在 0x0 上什麼都畫不出來，於是「換頁後圖表
    # 不見、重新整理就好」。上一頁補進來的用 data-spa-css 標記，換頁時先撤掉，
    # 免得一頁一頁疊上去互相打架。
    'function css(doc){'
    'var live=document.head;'
    # 沒有 id 的 <style> ＝ 引擎給「那一頁」的樣式，換頁要整組換掉；不換的話會
    # 兩頁疊著打架（實測：換到個股頁時 .card 仍吃到首頁的 display:grid，
    # K 線容器被壓成 150x0）。有 id 的是補丁層的共用基礎建設（twcolor /
    # barglass / tabthumbcss…），跨頁常駐，留著。
    'var old=live.querySelectorAll("style:not([id]),link[data-spa-css]");'
    'for(var i=0;i<old.length;i++)old[i].parentNode.removeChild(old[i]);'
    # 插在第一個「有 id 的補丁樣式」之前，維持原本「引擎樣式在前、補丁在後」的
    # 層疊順序——直接附在最後的話補丁樣式會反過來被蓋掉。
    'var anchor=live.querySelector("style[id]");'
    'var want=doc.head.querySelectorAll(\'style:not([id]),link[rel="stylesheet"]\');'
    'for(var j=0;j<want.length;j++){var n=want[j];'
    'if(n.tagName==="LINK"){var dup=false,ls=live.querySelectorAll(\'link[rel="stylesheet"]\');'
    'for(var k=0;k<ls.length;k++){if(ls[k].href===n.href){dup=true;break;}}'
    'if(dup)continue;var l=document.createElement("link");l.rel="stylesheet";l.href=n.href;'
    'l.setAttribute("data-spa-css","1");'
    'if(anchor)live.insertBefore(l,anchor);else live.appendChild(l);}'
    'else{var s=document.createElement("style");s.textContent=n.textContent;'
    'if(anchor)live.insertBefore(s,anchor);else live.appendChild(s);}}}'
    'function swap(href,doc){'
    'var oldW=document.querySelector(".wrap"),newW=doc.querySelector(".wrap");'
    'if(!oldW||!newW)throw new Error("no wrap");'
    'document.title=doc.title;'
    'css(doc);'
    'oldW.parentNode.replaceChild(document.importNode(newW,true),oldW);'
    # 重跑目標頁 body 裡「所有」頁面級腳本，而不是只有 .wrap 內的那些。
    # 這是圖表換頁後不見的根因：儀表、走勢、K 線的初始化腳本其實放在
    # </div>（.wrap 收尾）之後，只換 .wrap 完全碰不到它們——實測 SPA 換到
    # 個股頁時 [data-k] 容器有 8 個、但 echarts.init 呼叫 0 次、
    # IntersectionObserver 建立 0 個。
    'rerun(doc);'
    # 分頁列不重建，只把 .on 換到新的分頁上（tabthumb 的膠囊照舊跟著跑）
    'var f=(new URL(href)).pathname.split("/").pop()||"index.html";'
    'var tabs=document.querySelectorAll(".tabbar a.tab");'
    'for(var k=0;k<tabs.length;k++){'
    'var tf=(tabs[k].getAttribute("href")||"").split("/").pop()||"index.html";'
    'tabs[k].classList.toggle("on",tf===f);}'
    # 膠囊與琥珀高亮：從分頁列點的那次它已經滑到定位了，這裡是為了上一頁／
    # 頁內連結那種不是從分頁列發起的換頁，不然高亮會留在舊分頁上
    'if(window.__tabSync)window.__tabSync(true);'
    'window.scrollTo(0,0);'
    'clearTimeout(glassTimer);glassTimer=setTimeout(refreshGlass,' + str(GLASSFIX_MS) + ');}'
    'var busy=false;'
    'function go(href,push){if(busy)return;busy=true;'
    'getDoc(href).then(function(doc){'
    'if(push)history.pushState({spa:1},"",href);'
    'swap(href,doc);busy=false;}).catch(function(){location.href=href;});}'
    'window.__spaGo=function(href){var t=target(href);if(t)go(t,true);else location.href=href;};'
    # 一般連結（例如頁內指到其他分頁的按鈕）也接管
    'document.addEventListener("click",function(e){'
    'if(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;'
    'var a=e.target&&e.target.closest?e.target.closest("a[href]"):null;'
    'if(!a||a.target||a.hasAttribute("download"))return;'
    'if(a.classList.contains("tab"))return;'   # 分頁列由 tabthumb 經 __spaGo 處理
    'var t=target(a.getAttribute("href"));'
    'if(!t||t===location.href)return;'
    'e.preventDefault();go(t,true);});'
    'addEventListener("popstate",function(){'
    'var t=target(location.href);if(!t)return;'
    'getDoc(t).then(function(doc){swap(t,doc);}).catch(function(){location.reload();});});'
    # 閒置時把另外三個分頁先抓回來，之後切換就是純記憶體操作
    'var idle=window.requestIdleCallback||function(f){return setTimeout(f,1200);};'
    'idle(function(){var d=dirOf(location.href);'
    'for(var f in TABS){var u=d+f;if(u!==location.href)getDoc(u).catch(function(){});}});'
    '})();</script>'
)
SPANAV_RE = re.compile(r'<script id="spanav">.*?</script>', re.S)


def patch_spanav(html):
    """注入 pjax 換頁（只接管四個主分頁）。移除舊版再重插，冪等。
    SPANAV_JS 設成 '' 就等於停用——已注入的會被移除，站點回到整頁重載。"""
    if '</body>' not in html or '<nav class="tabbar">' not in html:
        return SPANAV_RE.sub('', html), (SPANAV_RE.search(html) is not None)
    if SPANAV_JS and SPANAV_JS in html:
        return html, False
    orig = html
    html = SPANAV_RE.sub('', html)
    if SPANAV_JS:
        html = html.replace('</body>', SPANAV_JS + '</body>', 1)
    return html, (html != orig)


# --- 原生殼模式：?native=1 時隱藏網頁自己的分頁列 --------------------------
# 包在 WKWebView 裡、由 SwiftUI TabView 提供真・SF Symbols 分頁列時，網頁不該
# 再畫一條玻璃 bar（會兩條疊在一起）。一般訪客沒有這個參數，完全不受影響。
# 旗標記在 sessionStorage：站內是整頁重載，點進個股頁時網址不會再帶 native=1，
# 靠 sessionStorage 讓同一個 WebView 內的後續頁面也維持無 bar。
# 注入在 </head> 之前 → 樣式在 bar 畫出來之前就生效，不會閃一下。
NATIVEMODE_JS = (
    '<script id="nativemode">(function(){try{'
    'var on=/[?&]native=1\\b/.test(location.search);'
    'if(on)sessionStorage.setItem("nativeshell","1");'
    'else on=sessionStorage.getItem("nativeshell")==="1";'
    'if(!on)return;'
    'document.documentElement.classList.add("nativeshell");'
    'var st=document.createElement("style");'
    'st.textContent="html.nativeshell .tabbar{display:none!important}"'
    '+"html.nativeshell .wrap{padding-bottom:24px!important}";'
    'document.head.appendChild(st);}catch(e){}})();</script>'
)
NATIVEMODE_RE = re.compile(r'<script id="nativemode">.*?</script>', re.S)


def patch_nativemode(html):
    """?native=1 時隱藏網頁分頁列（給原生殼用）。移除舊版再重插（冪等）。"""
    if '</head>' not in html:
        return html, False
    orig = html
    html = NATIVEMODE_RE.sub('', html)
    html = html.replace('</head>', NATIVEMODE_JS + '</head>', 1)
    return html, (html != orig)


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


# --- 切換分頁的液態轉場（覆寫 View Transition keyframes，縮放+滑動）----------
# 「不要特效」：完全關閉換頁轉場。@view-transition{navigation:none} 覆蓋引擎 base 的
# navigation:auto（同類 at-rule 後定義者勝），跨文件轉場整個不建立→即時切換、bar 不
# 因轉場位移。保險：萬一某環境仍建立轉場，把 root/tabbar 的動畫全部關成即時。
VT_LIQUID = (
    '<style id="vtliquid">'
    '@view-transition{navigation:none}'
    '::view-transition-group(*){animation:none!important}'
    '::view-transition-old(root),::view-transition-new(root)'
    '{animation:none!important;mix-blend-mode:normal!important}'
    '::view-transition-old(tabbar){display:none!important}'
    '::view-transition-new(tabbar){animation:none!important;opacity:1!important}'
    '</style>'
)
VTLIQUID_RE = re.compile(r'<style id="vtliquid">.*?</style>', re.S)


def patch_vtliquid(html):
    """分頁切換轉場（防閃爍：新頁不透明只滑入、舊頁淡出、tabbar 不轉場）。
    有 tabbar 的頁面。移除舊版再重插（冪等、可升級：頁上是舊 crossfade 版會被換掉）。"""
    if '<nav class="tabbar">' not in html or VT_LIQUID in html:
        return html, False
    orig = html
    html = VTLIQUID_RE.sub('', html)
    html = html.replace('<nav class="tabbar">', VT_LIQUID + '<nav class="tabbar">', 1)
    return html, (html != orig)


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

    # 1b2) 固定頂部 logo 欄
    html, bl = patch_brandlogo(html, fname)
    changed = changed or bl

    # 1b2b) 移除 document.write 的 echarts 後備：主載入是 defer，解析當下
    # window.echarts 必為空，這行每次都會同步再載一次 echarts、阻塞首繪。
    # defer 版本身已帶 onerror 後備鏈，直接拿掉。
    _ECW_RE = re.compile(
        r'<script>window\.echarts\|\|document\.write\(.*?\);</script>\n?', re.S)
    new = _ECW_RE.sub('', html)
    if new != html:
        html = new
        changed = True

    # 1b3) 標題統一為「台股進場儀表板」，不提美股（h1 註記與 <title> 一併處理）
    for _o, _n in (
        ('市場進場儀表板 <span style="font-size:14px;color:var(--muted)">台股・美股</span>',
         '台股進場儀表板'),
        ('市場進場儀表板', '台股進場儀表板'),
    ):
        if _o in html:
            html = html.replace(_o, _n)
            changed = True

    # 1c) 頂部狀態列底色對齊頁面（消除色差「分開」）
    html, tcm = patch_themecolor(html)
    changed = changed or tcm

    # 1d) 頂部安全區 liquid glass 玻璃條（根治 PWA 頂部暗帶）
    html, tg = patch_topglass(html)
    changed = changed or tg

    # 1d2) 全站 Liquid Glass 材質（底層極光光暈 + 卡片玻璃化）
    html, lq = patch_liquid(html)
    changed = changed or lq

    # 1d2b) 液態折射＋模糊最高檔（折射不支援時退回 blur 48px）
    html, dg = patch_reglass(html)
    changed = changed or dg

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

    # 1e-8) 個股卡標題「歪掉」修正：h2 是 flex，個股名是裸中文字節（flex item 的
    # min-width＝1 個中文字寬），列被分數(32px)＋代碼撐爆時名字就被壓成一字一行直排。
    # flex-wrap:wrap 讓塞不下時整塊換行、white-space:nowrap 擋字內斷行、score 不縮。
    for _o, _n in (
        ('h2{font-size:18px;margin:0;display:flex;align-items:center;gap:8px}',
         'h2{font-size:18px;margin:0;display:flex;flex-wrap:wrap;align-items:center;'
         'gap:4px 8px;white-space:nowrap;min-width:0}'),
        ('h2 .score{margin-left:auto;font-size:32px;font-weight:800}',
         'h2 .score{margin-left:auto;font-size:32px;font-weight:800;flex-shrink:0}'),
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

    # 5b) K 線一開始就畫，不用捲到才出現（stocks.html）
    html, ke = patch_kchart_eager(html)
    changed = changed or ke

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

    # 12a1) 舊的浮動 ＋ 鈕與右下角放大鏡圓鈕重複，移掉
    html, fb = patch_fab(html)
    changed = changed or fb

    # 12a2) SPA 換頁（pjax）：只接管四個主分頁，換頁後對玻璃做一次重整，
    # 避免上一版「分頁列跨頁不重建、iOS 毛玻璃失效後回不來」的老問題。
    html, sn = patch_spanav(html)
    changed = changed or sn
    html, std = patch_striptabdrag(html)
    changed = changed or std

    # 12a3) 可拖曳膠囊改用 body 層獨立覆蓋層（不進分頁列→毛玻璃不受影響）
    html, tt = patch_tabthumb(html)
    changed = changed or tt

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

    # 17) 原生殼模式：?native=1 隱藏網頁分頁列
    html, nm = patch_nativemode(html)
    changed = changed or nm

    # 18) SW 註冊改成會自己換版（手機 PWA 沒辦法硬重整）。放最後，才會落在
    #     </body> 前、位置穩定，重跑不會漂移。
    html, sr = patch_swreg(html)
    changed = changed or sr

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


# --- SW 註冊：讓 PWA／網頁自己換新版（手機 app 沒辦法「硬重整」）-------------
# 換版這件事真正的主力在 sw.js 那邊（activate 直接把開著的分頁 navigate 掉，
# 見 fix_sw_activate）——那條路連「頁面上根本沒有這支腳本的舊版 HTML」都救得到，
# 這才是打破雞生蛋的關鍵。這裡負責兩件配套：
#   1) 每次回到前景就 update() 檢查一次。PWA 常常一開就是好幾天不關，不主動
#      問的話瀏覽器不一定會去看 sw.js 有沒有換版。
#   2) 收 SW 的 reload 訊息（client.navigate 不支援時的退路），外加
#      controllerchange 延遲重載當最後一道保險。三條路都設了 done 旗標，
#      只會重載一次。第一次安裝不重載（had 記住進頁時有沒有 controller），
#      不然每個新使用者都白白多一次。
SWREG_RE = re.compile(r'<script id="swreg">.*?</script>', re.S)
SWREG_ENGINE = ('<script>if("serviceWorker" in navigator){addEventListener("load",'
                'function(){navigator.serviceWorker.register("sw.js")'
                '.catch(function(){})})}</script>')
SWREG_NEW = (
    '<script id="swreg">(function(){'
    'if(!("serviceWorker" in navigator))return;'
    'var had=!!navigator.serviceWorker.controller,done=false;'
    'function bye(){if(done)return;done=true;location.reload();}'
    'navigator.serviceWorker.addEventListener("message",function(e){'
    'if(e.data&&e.data.swreload)bye();});'
    'navigator.serviceWorker.addEventListener("controllerchange",function(){'
    'if(had)setTimeout(bye,1500);});'
    'function chk(){try{navigator.serviceWorker.getRegistration().then(function(r){'
    'if(r)r.update();}).catch(function(){});}catch(e){}}'
    'addEventListener("load",function(){'
    'navigator.serviceWorker.register("sw.js").then(chk).catch(function(){});});'
    'document.addEventListener("visibilitychange",function(){'
    'if(!document.hidden)chk();});'
    '})();</script>'
)


def patch_swreg(html):
    """SW 註冊換成會自己換版的版本。只動本來就有註冊的頁，不無中生有。"""
    orig = html
    if not SWREG_RE.search(html) and SWREG_ENGINE not in html:
        return html, False
    if '</body>' not in html:              # 沒地方放就別動，免得把註冊弄丟
        return html, False
    html = SWREG_RE.sub('', html)          # 先移除舊版（保持冪等）
    html = html.replace(SWREG_ENGINE, '', 1)
    html = html.replace('</body>', SWREG_NEW + '</body>', 1)
    return html, (html != orig)


# --- SW 抓取策略 -------------------------------------------------------------
# 頁面本身（navigate）＝網路優先，其餘資源＝快取優先＋背景更新。
#
# 為什麼頁面要改回網路優先：純快取優先的話，「打開」看到的永遠是上一次那份
# ——新版只是在背景寫進快取，要等下一次打開才看得到。桌機還能硬重整，手機
# PWA 沒那顆按鈕，體感就是「怎麼改都沒上」。這正是使用者回報的症狀。
# 但不能無腦網路優先（原本就是這樣，才被改掉的）：網路慢或斷線時會空等。
# 所以加 2 秒天花板，逾時就用快取先把畫面撐起來，網路回來了再寫回快取。
# 圖片／JSON／manifest 這些不影響「看到的是不是新版」，維持快取優先＝切頁即開。
SW_FETCH_SWR = (
    'const NETMS = 2000;\n'
    'function fromNet(req) {\n'
    '  return fetch(req).then((r) => {\n'
    '    const cp = r.clone();\n'
    '    caches.open(C).then((c) => c.put(req, cp)).catch(() => {});\n'
    '    return r;\n'
    '  });\n'
    '}\n'
    'function pageFirst(req) {\n'
    '  return new Promise((resolve) => {\n'
    '    let settled = false;\n'
    '    const give = (r) => { if (!settled && r) { settled = true; resolve(r); } };\n'
    '    const fallback = () => caches.match(req)\n'
    '      .then((h) => h || caches.match("./index.html")).then(give);\n'
    '    const timer = setTimeout(fallback, NETMS);\n'
    '    fromNet(req).then((r) => { clearTimeout(timer); give(r); })\n'
    '      .catch(() => { clearTimeout(timer); fallback(); });\n'
    '  });\n'
    '}\n'
    'self.addEventListener("fetch", (e) => {\n'
    '  if (e.request.method !== "GET") return;\n'
    '  if (e.request.mode === "navigate") { e.respondWith(pageFirst(e.request)); return; }\n'
    '  const sameOrigin = new URL(e.request.url).origin === self.location.origin;\n'
    '  e.respondWith(\n'
    '    caches.match(e.request).then((hit) => {\n'
    '      // 跨網域的資源都帶版本號（echarts@5.5.0），內容不會變：命中就直接用，\n'
    '      // 不再回頭抓，省掉每次開頁都重抓 1MB。\n'
    '      if (hit && !sameOrigin) return hit;\n'
    '      // 失敗時「絕對不能」拿 index.html 頂替：那是給導頁用的離線退路，\n'
    '      // 拿去回應 <script> 會讓瀏覽器以為載入成功（拿到一坨 HTML），\n'
    '      // onerror 不觸發、備援 CDN 不會跑、echarts 永遠停在 stub，\n'
    '      // 於是指針和 K 線整片消失，而且沒有任何錯誤訊息。\n'
    '      const net = fromNet(e.request).catch(() => hit || Response.error());\n'
    '      return hit || net;\n'
    '    })\n'
    '  );\n'
    '});\n'
)
SW_FETCH_RE = re.compile(r'(?:const NETMS[\s\S]*?)?self\.addEventListener\("fetch",.*', re.S)

# --- 新版 SW 一活過來就把開著的分頁換掉 --------------------------------------
# skipWaiting + clients.claim 只是「換掉控制者」，畫面不會重畫。client.navigate()
# 才會真的讓那個分頁重新載入——而且是 SW 單方面做的，**不需要頁面上有任何腳本
# 配合**。這點很重要：使用者手機裡快取的那份 HTML 是舊的、沒有 swreg，只能靠
# 這條路救。navigate 不支援時退回 postMessage（新版 HTML 有收）。
# 只有「真的是升級」才動：first install 沒有舊快取可刪，那次不重載，免得每個
# 新使用者一進來就被彈一次。
SW_ACTIVATE_NAV = (
    'function reloadClients() {\n'
    '  self.clients.matchAll({ type: "window" }).then((cs) => cs.forEach((c) => {\n'
    '    try { c.navigate(c.url).catch(() => c.postMessage({ swreload: 1 })); }\n'
    '    catch (err) { try { c.postMessage({ swreload: 1 }); } catch (e2) {} }\n'
    '  })).catch(() => {});\n'
    '}\n'
    'self.addEventListener("activate", (e) => {\n'
    '  e.waitUntil(caches.keys().then((ks) => {\n'
    '    const old = ks.filter((k) => k !== C);\n'
    '    return Promise.all(old.map((k) => caches.delete(k))).then(() => old.length > 0);\n'
    '  }).then((upgraded) => self.clients.claim().then(() => {\n'
    '    // 這裡刻意「不」回傳 promise：navigate 會觸發導頁的 fetch，而 fetch 要等\n'
    '    // activate 結束才會被處理——放進 waitUntil 就是互相等，頁面永遠載不完。\n'
    '    if (upgraded) reloadClients();\n'
    '  })).catch(() => {}));\n'
    '});\n'
)
SW_ACTIVATE_RE = re.compile(
    r'(?:function reloadClients[\s\S]*?\n\}\n)?'
    r'self\.addEventListener\("activate",.*?\n\}\);\n', re.S)


def fix_sw_activate():
    """新版 SW 活過來就把開著的分頁 navigate 掉，不必等使用者自己重整。"""
    try:
        sw = open("sw.js", encoding="utf-8").read()
    except Exception:                      # noqa: BLE001 — 缺檔就跳過
        return False
    if SW_ACTIVATE_NAV in sw or not SW_ACTIVATE_RE.search(sw):
        return False
    new = SW_ACTIVATE_RE.sub(SW_ACTIVATE_NAV, sw, count=1)
    with open("sw.js", "w", encoding="utf-8") as fh:
        fh.write(new)
    return True

# --- SW 預快取要真的去網路拿 -------------------------------------------------
# cache.addAll 走的是預設的 HTTP 快取，Pages 給 HTML 的 max-age 期間內，
# 新 SW 有可能把「瀏覽器快取裡的舊 HTML」原封不動存進新版快取——版本號換了、
# 內容還是舊的，使用者依然看不到更新，而且因為版本已經換過，之後也不會再試。
# 改成逐檔 fetch(..., {cache:"reload"})，強制繞過 HTTP 快取。
# 順便把 echarts 也收進快取。它是帶版本號的網址（@5.5.0），內容不會變，收一次
# 就能永遠即開即用、離線也有圖——不必每次開頁都賭 CDN 通不通。跨網域只能拿到
# opaque 回應，cache.put 收得下，之後餵給 no-cors 的 <script> 也照樣執行。
SW_INSTALL_FRESH = (
    'const CDN = ["https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"];\n'
    'self.addEventListener("install", (e) => {\n'
    '  e.waitUntil(caches.open(C).then((c) => Promise.all(\n'
    '    ASSETS.map((a) => fetch("./" + a, { cache: "reload" }).then((r) => c.put("./" + a, r)))\n'
    '      .concat(CDN.map((u) => fetch(u, { mode: "no-cors" })\n'
    '        .then((r) => c.put(u, r)).catch(() => {})))\n'
    '  )).catch(() => {}).then(() => self.skipWaiting()));\n'
    '});\n'
)
SW_INSTALL_RE = re.compile(
    r'(?:const CDN = \[[^\]]*\];\n)?'
    r'self\.addEventListener\("install",.*?\n\}\);\n', re.S)


def fix_sw_install():
    """預快取改成強制走網路，避免新版 SW 把舊 HTML 存進新版快取。"""
    try:
        sw = open("sw.js", encoding="utf-8").read()
    except Exception:                      # noqa: BLE001 — 缺檔就跳過
        return False
    if SW_INSTALL_FRESH in sw or not SW_INSTALL_RE.search(sw):
        return False
    new = SW_INSTALL_RE.sub(SW_INSTALL_FRESH, sw, count=1)
    with open("sw.js", "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


SW_HEADER = ('/* 市場儀表板 PWA service worker：頁面網路優先（逾時退快取）、'
             '其餘快取優先＋背景更新、離線退回快取。 */')
SW_HEADER_RE = re.compile(r'^/\* 市場儀表板 PWA service worker：[^*]*\*/')


def fix_sw_strategy():
    """頁面走網路優先（2 秒逾時退快取）、其餘快取優先＋背景更新。冪等：已是新版
    就不動；引擎重產 sw.js 蓋回舊策略時，每日執行會自動修回。"""
    try:
        sw = open("sw.js", encoding="utf-8").read()
    except Exception:                      # noqa: BLE001 — 缺檔就跳過
        return False
    if SW_FETCH_SWR in sw or not SW_FETCH_RE.search(sw):
        return False
    new = SW_FETCH_RE.sub(SW_FETCH_SWR, sw, count=1)
    new = SW_HEADER_RE.sub(SW_HEADER, new, count=1)
    with open("sw.js", "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


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
    if fix_sw_strategy():
        touched.append("sw.js(策略)")
    if fix_sw_install():
        touched.append("sw.js(預快取)")
    if fix_sw_activate():
        touched.append("sw.js(換版重載)")
    if fix_sw():                           # 必須最後：雜湊要涵蓋以上全部產出
        touched.append("sw.js")
    print("已補丁：" + (", ".join(touched) if touched else "(無需變更)"))


if __name__ == "__main__":
    main()

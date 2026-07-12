#!/usr/bin/env python3
"""為熱門個股產生 SEO 靜態頁（吃「台積電 進場分數」這類長尾搜尋）。

只做熱門少數、內容豐富的頁，避免 1964 個雷同頁被 Google 當「劣質門口頁」。
每頁資料來自 universe.json；引擎每天更新 universe.json 後由 workflow 重跑本程式。
產出：stock/<代碼>.html、stock/index.html（索引頁）、並重寫 sitemap.xml。
"""
import html as _html
import json
import os
import re
from datetime import date

BASE = "https://stocktracker-tw.github.io/market-dashboard"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "stock")
ETFDIR = os.path.join(ROOT, "etf")
TODAY = date.today().isoformat()

# 站台主要頁面（一併寫進 sitemap）
MAIN_PAGES = [
    ("/", "daily", "1.0"),
    ("/stocks.html", "daily", "0.9"),
    ("/etf/", "daily", "0.8"),
    ("/backtest.html", "weekly", "0.8"),
    ("/perspectives.html", "daily", "0.7"),
    ("/news.html", "daily", "0.6"),
    ("/stock/", "daily", "0.7"),
]

# 熱門 ETF（universe 沒有 ETF 分數；廣基型 ETF≈大盤，用每日大盤分數判斷定額時機。
# 高股息/主題型成分與大盤不同，大盤分數僅供「市場環境」參考）。
# (代碼, 名稱, 類型 broad/dividend, 追蹤/成分說明)
ETF_LIST = [
    ("0050", "元大台灣50", "broad", "臺灣50指數（市值前 50 大，約等於台股大盤）"),
    ("006208", "富邦台50", "broad", "臺灣50指數（與 0050 同指數）"),
    ("00692", "富邦公司治理", "broad", "公司治理 100 指數（廣基大型股）"),
    ("0056", "元大高股息", "dividend", "高股息精選成分股"),
    ("00878", "國泰永續高股息", "dividend", "MSCI 臺灣 ESG 永續高股息"),
    ("00919", "群益台灣精選高息", "dividend", "台灣精選高息指數"),
    ("00929", "復華台灣科技優息", "dividend", "科技類高股息"),
    ("00940", "元大台灣價值高息", "dividend", "價值高息成分"),
    ("00713", "元大台灣高息低波", "dividend", "高息低波動成分"),
]

# 熱門個股（知名大型權值股；非個股的 ETF 不在 universe，會自動略過）
POPULAR = ["2330", "2317", "2454", "2308", "2382", "2303", "2412", "2881", "2882",
           "2891", "2886", "2884", "2885", "2603", "2609", "2615", "2002", "1216",
           "2207", "2357", "2395", "3008", "3034", "2379", "3711", "2474", "6505",
           "2912", "1101", "1301", "1303", "2327", "3231", "2356", "4938", "5871",
           "2880", "2887", "2890", "2892", "2801", "9910", "2105", "2376", "2409",
           "1402"]

ZONES = ["低分", "偏低", "中性", "偏高", "高分"]


def zone(sc):
    return 4 if sc >= 70 else 3 if sc >= 58 else 2 if sc >= 43 else 1 if sc >= 35 else 0


def e(s):
    return _html.escape(str(s), quote=True)


def bar(label, val, desc=""):
    val = max(0, min(100, int(round(val))))
    col = "#34d07f" if val >= 58 else "#f9b43a" if val >= 43 else "#ef5d5d"
    d = f'<div class="d">{e(desc)}</div>' if desc else ""
    return (f'<div class="sub"><div class="sh"><span>{e(label)}</span>'
            f'<b>{val}</b></div><div class="bar"><i style="width:{val}%;'
            f'background:{col}"></i></div>{d}</div>')


def page(x):
    code, name = e(x["c"]), e(x["n"])
    sc = round(float(x["s"]))
    zlabel = ZONES[zone(x["s"])]
    industry = e(x.get("i", "")) or "個股"
    price = x.get("p")
    pstr = f"{price:g}" if isinstance(price, (int, float)) and price else "—"
    summary = e(x.get("b") or x.get("a") or "")
    desc = (f"{x['n']}（{x['c']}）今日進場分數 {sc}（{zlabel}）。"
            f"含環境、籌碼、估值、技術四面向評分與當日數據。每日更新・非投資建議。")
    ann = ""
    if x.get("fg") and x.get("ft"):
        ann = (f'<div class="card"><div class="h">📢 {e(x["fg"])}</div>'
               f'<div class="t">{e(x["ft"])}</div></div>')
    title = f"{x['n']}（{x['c']}）進場分數 {sc} — Stock Tracker"
    canon = f"{BASE}/stock/{code}.html"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>{e(title)}</title>
<link rel="canonical" href="{canon}">
<meta name="description" content="{e(desc)}">
<meta name="robots" content="index,follow">
<link rel="icon" href="../favicon.ico?v=2">
<link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png?v=2">
<link rel="apple-touch-icon" href="../apple-icon-v9.png">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{BASE}/cover.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{{"@type":"Question","name":"{e(x['n'])}（{code}）今天的進場分數是多少？","acceptedAnswer":{{"@type":"Answer","text":"{e(desc)}"}}}}]}}</script>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:22px 18px 60px}}
a{{color:#2478c8}}
.bc{{font-size:13px;color:#5b6d80;margin-bottom:10px}}
h1{{font-size:24px;margin:0 0 2px}}
.meta{{color:#5b6d80;font-size:13px;margin-bottom:18px}}
.hero{{background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:18px 20px;margin-bottom:18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}}
.score{{font-size:52px;font-weight:800;line-height:1}}
.badge{{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:14px;background:#1e2a44}}
.card{{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.09);border-radius:14px;padding:14px 16px;margin-bottom:14px}}
.card .h{{font-weight:700;font-size:14px;margin-bottom:8px}}
.card .t{{font-size:13.5px;color:#cdd6e6}}
.sub{{margin:10px 0}}
.sh{{display:flex;justify-content:space-between;font-size:13.5px;margin-bottom:4px}}
.bar{{height:8px;background:#1e2430;border-radius:6px;overflow:hidden}}
.bar>i{{display:block;height:100%;border-radius:6px}}
.d{{font-size:12px;color:#5b6d80;margin-top:4px}}
.cta{{display:inline-block;margin-top:6px;padding:10px 16px;background:#1f6feb;color:#fff;text-decoration:none;border-radius:10px;font-weight:600}}
.warn{{background:rgba(234,84,85,.12);border:1px solid rgba(234,84,85,.4);color:#ffb3b3;padding:8px 12px;border-radius:8px;font-size:12.5px;margin:18px 0}}
.foot{{margin-top:24px;padding-top:14px;border-top:1px solid #222936;color:#5b6d80;font-size:12px}}
</style></head><body><div class="wrap">
<div class="bc"><a href="../">Stock Tracker</a> ／ <a href="../stocks.html">個股</a> ／ {name}</div>
<h1>{name}（{code}）進場分數</h1>
<div class="meta">{industry}　｜　參考價 {e(pstr)}　｜　更新 {TODAY}</div>

<div class="hero"><div class="score">{sc}</div><div>
<span class="badge">{e(zlabel)}</span>
<div style="font-size:13px;color:#5b6d80;margin-top:8px;max-width:380px">{summary}</div>
</div></div>

<div class="card"><div class="h">四面向評分</div>
{bar("環境面（總經/大盤）", x.get("e", 0))}
{bar("籌碼面（法人/融資）", x.get("ch", 0), x.get("cd", ""))}
{bar("估值面（本益比/殖利率）", x.get("v", 0), x.get("vd", ""))}
{bar("技術面（型態/動能）", x.get("tk", 0), x.get("td", ""))}
</div>
{ann}

<a class="cta" href="../stocks.html">查看全市場 1964 檔 →</a>

<div class="warn">⚠️ 本頁為個人研究與數據彙整，分數僅供參考，<b>不構成任何投資建議</b>，投資前請自行評估風險。</div>

<div class="card"><div class="h">什麼是「進場分數」？</div>
<div class="t">把環境、籌碼、估值、技術四個面向壓成一個 0–100 分：分數高＝數據偏多，
＝恐慌便宜的機會日；分數低＝擁擠過熱，別當最後一棒。<b>這不是預測會漲跌或叫你買賣個股</b>，
而是把市場數據量化成一個好懂的溫度計。完整互動工具與每日大盤分數見
<a href="../">Stock Tracker 首頁</a>。</div></div>

<div class="foot">資料每日更新・非投資建議　｜　<a href="../">Stock Tracker</a></div>
</div></body></html>"""


def hub(rows):
    items = "".join(
        f'<li><a href="{e(r["c"])}.html">{e(r["n"])}（{e(r["c"])}）</a>'
        f'<span class="s">{round(r["s"])}</span></li>' for r in rows)
    desc = "熱門台股的每日進場分數一覽：台積電、鴻海、聯發科等大型權值股的環境/籌碼/估值/技術評分。非投資建議。"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>熱門台股進場分數一覽 — Stock Tracker</title>
<link rel="canonical" href="{BASE}/stock/">
<meta name="description" content="{e(desc)}">
<link rel="icon" href="../favicon.ico?v=2">
<link rel="apple-touch-icon" href="../apple-icon-v9.png">
<meta property="og:title" content="熱門台股進場分數一覽 — Stock Tracker">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{BASE}/stock/">
<meta property="og:image" content="{BASE}/cover.png">
<style>
:root{{color-scheme:dark}}body{{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:22px 18px 60px}}a{{color:#2478c8}}
h1{{font-size:23px}}.meta{{color:#5b6d80;font-size:13px;margin-bottom:16px}}
ul{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
@media(max-width:560px){{ul{{grid-template-columns:1fr}}}}
li{{display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);border-radius:10px;padding:9px 13px}}
li a{{text-decoration:none;font-weight:600}}.s{{font-weight:800;color:#5b6d80}}
.foot{{margin-top:22px;padding-top:14px;border-top:1px solid #222936;color:#5b6d80;font-size:12px}}
</style></head><body><div class="wrap">
<div style="font-size:13px;color:#5b6d80"><a href="../">Stock Tracker</a> ／ 熱門個股</div>
<h1>熱門台股進場分數一覽</h1>
<div class="meta">每日更新・依代碼排序・非投資建議　｜　更新 {TODAY}</div>
<ul>{items}</ul>
<div class="foot">想查全市場 1964 檔？到 <a href="../stocks.html">個股搜尋</a>。非投資建議。</div>
</div></body></html>"""


# --- ETF（用每日大盤分數判斷定期定額時機）---------------------------------
def market_score():
    """從 index.html 讀大盤綜合進場分數（引擎每天更新）。"""
    try:
        s = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        m = re.search(r'"composite":\s*([0-9.]+)', s)
        return round(float(m.group(1))) if m else None
    except Exception:
        return None


def mult_of(sc):
    return 1.5 if sc >= 70 else 1.25 if sc >= 58 else 1.0 if sc >= 43 else 0.75 if sc >= 35 else 0.5


def etf_page(meta, sc):
    code, name, kind, basis = meta
    code, name, basis = e(code), e(name), e(basis)
    broad = kind == "broad"
    zlabel = ZONES[zone(sc)] if sc is not None else "—"
    mult = mult_of(sc) if sc is not None else 1.0
    if broad:
        frame = (f"{name}（{code}）追蹤的指數幾乎等於台股大盤，所以<b>今天的大盤進場分數"
                 f" {sc}（{zlabel}）可直接當這檔的大盤環境溫度計</b>。")
    else:
        frame = (f"{name}（{code}）是高股息／主題型 ETF，成分與大盤不同，"
                 f"以下大盤分數 {sc}（{zlabel}）<b>僅供「市場環境」參考</b>，不代表這檔本身。")
    desc = (f"{name}（{code}）進場溫度：今天台股大盤進場分數 {sc}（{zlabel}）。"
            f"分數高＝環境偏多可多扣、低＝保守。每日更新・非投資建議。")
    title = f"{name}（{code}）定期定額進場時機 — Stock Tracker"
    canon = f"{BASE}/etf/{code}.html"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>{e(title)}</title>
<link rel="canonical" href="{canon}">
<meta name="description" content="{e(desc)}">
<meta name="robots" content="index,follow">
<link rel="icon" href="../favicon.ico?v=2">
<link rel="apple-touch-icon" href="../apple-icon-v9.png">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{BASE}/cover.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{{"@type":"Question","name":"{name}（{code}）現在適合定期定額嗎？","acceptedAnswer":{{"@type":"Answer","text":"{e(desc)}"}}}}]}}</script>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}
body{{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:22px 18px 60px}}a{{color:#2478c8}}
.bc{{font-size:13px;color:#5b6d80;margin-bottom:10px}}
h1{{font-size:23px;margin:0 0 2px}}.meta{{color:#5b6d80;font-size:13px;margin-bottom:18px}}
.hero{{background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:18px 20px;margin-bottom:16px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}}
.score{{font-size:52px;font-weight:800;line-height:1}}
.badge{{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:14px;background:#1e2a44}}
.card{{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.09);border-radius:14px;padding:14px 16px;margin-bottom:14px}}
.card .h{{font-weight:700;font-size:14px;margin-bottom:8px}}.card .t{{font-size:13.5px;color:#cdd6e6}}
input{{width:120px;padding:7px 10px;font-size:14px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-radius:10px;color:#17293a}}
.cta{{display:inline-block;margin-top:4px;padding:10px 16px;background:#1f6feb;color:#fff;text-decoration:none;border-radius:10px;font-weight:600}}
.warn{{background:rgba(234,84,85,.12);border:1px solid rgba(234,84,85,.4);color:#ffb3b3;padding:8px 12px;border-radius:8px;font-size:12.5px;margin:16px 0}}
.foot{{margin-top:24px;padding-top:14px;border-top:1px solid #222936;color:#5b6d80;font-size:12px}}
b{{color:#1d5c9e}}
</style></head><body><div class="wrap">
<div class="bc"><a href="../">Stock Tracker</a> ／ <a href="./">ETF 定期定額</a> ／ {name}</div>
<h1>{name}（{code}）定期定額進場時機</h1>
<div class="meta">追蹤：{basis}　｜　更新 {TODAY}</div>

<div class="hero"><div class="score">{sc if sc is not None else "—"}</div><div>
<span class="badge">大盤環境：{e(zlabel)}</span>
<div style="font-size:13px;color:#cdd6e6;margin-top:8px;max-width:420px">{frame}</div>
</div></div>

<div class="card"><div class="h">💡 這個月該扣多少？</div>
<div>平常每月定額 <input id="b" type="number" inputmode="numeric" placeholder="例 5000"> 元　→　今天建議 <b id="o" style="font-size:16px">—</b></div>
<div style="margin-top:6px;color:#5b6d80;font-size:11.5px">今日倍數 {mult:g}x（分數高多扣、低少扣）。{'' if broad else '高股息 ETF 僅供環境參考。'}</div>
<script>(function(){{var b=document.getElementById("b"),o=document.getElementById("o"),M={mult:g};
try{{var s=localStorage.getItem("etfBase");if(s)b.value=s;}}catch(e){{}}
function f(){{var v=parseFloat(b.value)||0;o.textContent=v?Math.round(v*M).toLocaleString()+" 元":"—";try{{localStorage.setItem("etfBase",b.value);}}catch(e){{}}}}
b.addEventListener("input",f);f();}})();</script></div>

<a class="cta" href="../">看完整大盤分數與指標 →</a>

<div class="warn">⚠️ 進場分數反映台股大盤環境，僅供參考，<b>不構成投資建議、不預測漲跌</b>，投資前請自行評估風險。</div>

<div class="card"><div class="h">怎麼用？</div><div class="t">
定期定額最大的好處是「不用猜時機」。但如果你願意<b>在大盤分數低時多扣一點、高時少扣一點</b>，
長期有機會降低成本、減少在高點重押。這不是叫你停扣或預測漲跌，而是把市場環境量化成一個溫度計。
完整分數與指標見 <a href="../">Stock Tracker 首頁</a>，其他 ETF 見 <a href="./">ETF 一覽</a>。</div></div>

<div class="foot">資料每日更新・非投資建議　｜　<a href="../">Stock Tracker</a></div>
</div></body></html>"""


def etf_hub(sc):
    zlabel = ZONES[zone(sc)] if sc is not None else "—"
    items = "".join(
        f'<li><a href="{e(c)}.html">{e(n)}（{e(c)}）</a>'
        f'<span class="k">{"廣基≈大盤" if k=="broad" else "高股息"}</span></li>'
        for c, n, k, _ in ETF_LIST)
    desc = ("熱門 ETF 定期定額進場時機：用每日台股大盤進場分數判斷 0050、006208、0056、"
            "00878 等該不該多扣或少扣。廣基型 ETF 直接適用，高股息型供環境參考。非投資建議。")
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>ETF 定期定額進場時機（0050、0056…）— Stock Tracker</title>
<link rel="canonical" href="{BASE}/etf/">
<meta name="description" content="{e(desc)}">
<link rel="icon" href="../favicon.ico?v=2">
<link rel="apple-touch-icon" href="../apple-icon-v9.png">
<meta property="og:title" content="ETF 定期定額進場時機 — Stock Tracker">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{BASE}/etf/">
<meta property="og:image" content="{BASE}/cover.png">
<style>
:root{{color-scheme:dark}}body{{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:22px 18px 60px}}a{{color:#2478c8}}
h1{{font-size:23px}}.meta{{color:#5b6d80;font-size:13px;margin-bottom:14px}}
.now{{background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:14px 16px;margin-bottom:16px;font-size:14px}}
ul{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
@media(max-width:560px){{ul{{grid-template-columns:1fr}}}}
li{{display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);border-radius:10px;padding:9px 13px}}
li a{{text-decoration:none;font-weight:600}}.k{{font-size:11px;color:#5b6d80}}
.foot{{margin-top:22px;padding-top:14px;border-top:1px solid #222936;color:#5b6d80;font-size:12px}}
</style></head><body><div class="wrap">
<div style="font-size:13px;color:#5b6d80"><a href="../">Stock Tracker</a> ／ ETF 定期定額</div>
<h1>ETF 定期定額進場時機</h1>
<div class="meta">用每日台股大盤進場分數，判斷熱門 ETF 該多扣還是少扣・更新 {TODAY}</div>
<div class="now">📊 今天台股大盤進場分數 <b style="font-size:18px">{sc if sc is not None else "—"}</b>（{e(zlabel)}）
　—　廣基型 ETF（0050、006208）直接適用；高股息型供市場環境參考。</div>
<ul>{items}</ul>
<div class="foot">⚠️ 非投資建議，不預測漲跌。完整大盤分數見 <a href="../">首頁</a>。</div>
</div></body></html>"""


def write_sitemap(stock_codes, etf_codes):
    urls = []
    for path, freq, pri in MAIN_PAGES:
        urls.append(f"  <url><loc>{BASE}{path}</loc>"
                    f"<changefreq>{freq}</changefreq><priority>{pri}</priority></url>")
    for c in stock_codes:
        urls.append(f"  <url><loc>{BASE}/stock/{c}.html</loc>"
                    f"<lastmod>{TODAY}</lastmod><changefreq>daily</changefreq>"
                    f"<priority>0.6</priority></url>")
    for c in etf_codes:
        urls.append(f"  <url><loc>{BASE}/etf/{c}.html</loc>"
                    f"<lastmod>{TODAY}</lastmod><changefreq>daily</changefreq>"
                    f"<priority>0.6</priority></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(xml)


def main():
    data = json.load(open(os.path.join(ROOT, "universe.json"), encoding="utf-8"))
    by = {x["c"]: x for x in data}
    rows = [by[c] for c in POPULAR if c in by]
    os.makedirs(OUTDIR, exist_ok=True)
    for x in rows:
        with open(os.path.join(OUTDIR, f'{x["c"]}.html'), "w", encoding="utf-8") as f:
            f.write(page(x))
    with open(os.path.join(OUTDIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(hub(rows))

    sc = market_score()
    os.makedirs(ETFDIR, exist_ok=True)
    for meta in ETF_LIST:
        with open(os.path.join(ETFDIR, f"{meta[0]}.html"), "w", encoding="utf-8") as f:
            f.write(etf_page(meta, sc))
    with open(os.path.join(ETFDIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(etf_hub(sc))

    write_sitemap([x["c"] for x in rows], [m[0] for m in ETF_LIST])
    print(f"已產生 {len(rows)} 檔個股頁 + {len(ETF_LIST)} 檔 ETF 頁（大盤分數 {sc}），"
          "並更新 sitemap.xml")


if __name__ == "__main__":
    main()

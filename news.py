# -*- coding: utf-8 -*-
r"""① 本地新聞監控（純 Python，接進每日排程）。

做的事：抓最新財經新聞標題（Google News RSS + 鉅亨網）→ 標出相關個股 →
用「價格反應」量化『是否已反映』（消息出來後該股近期有沒有已經大漲/大跌）。

明確界線：這支**只抓標題、不判斷真偽**。真偽與合理性判讀是『每日 AI 簡報』(②) 的工作，
因為那需要 LLM 逐條交叉查證，純 Python 做不來。本頁僅供快速掃描，非投資建議。
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

import analytics as A
import config as cfg
import sources as src

_S = requests.Session()
_S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

GN = "https://news.google.com/rss/search?q=%s&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
QUERIES = ["台股 大盤", "台積電", "AI 半導體 台股", "美股 那斯達克 標普", "聯準會 Fed 利率 通膨"]
CNYES = "https://news.cnyes.com/rss/v1/news/category/tw_stock"


def _get(url, timeout=20):
    for _ in range(2):
        try:
            r = _S.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
        except Exception:
            pass
    return None


def _parse_rss(content, default_source=None):
    out = []
    try:
        root = ET.fromstring(content)
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            src_name = default_source
            # Google News 把來源放在 title 結尾 " - 媒體"，或 <source>
            s_el = it.find("source")
            if s_el is not None and s_el.text:
                src_name = s_el.text.strip()
            elif " - " in title:
                parts = title.rsplit(" - ", 1)
                title, src_name = parts[0].strip(), parts[1].strip()
            if title:
                out.append({"title": title, "link": link, "source": src_name or "", "pub": pub})
    except Exception:
        pass
    return out


def fetch_headlines(per_query=8, total=28):
    items = []
    for q in QUERIES:
        r = _get(GN % urllib.parse.quote(q + " when:3d"))
        if r:
            items += _parse_rss(r.content)[:per_query]
    r = _get(CNYES)
    if r:
        items += _parse_rss(r.content, default_source="鉅亨網")[:10]
    # 去重（用標題前 18 字）
    seen, uniq = set(), []
    for it in items:
        key = it["title"][:18]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return uniq[:total]


def _name_map(shared):
    """建立 名稱→代碼 / 代碼集合，只取自選股＋題材股＋主要權值，避免亂標。"""
    stocks = (shared.get("valuation") or {}).get("stocks", {}) if shared else {}
    codes = set(cfg.STOCK_WATCHLIST)
    for lst in getattr(cfg, "THEMES", {}).values():
        codes.update(str(c) for c in lst)
    codes.update(["2330", "2317", "2454", "2308", "2382", "3231", "2412", "2881", "0050"])
    name2code = {}
    for c in codes:
        nm = (stocks.get(c) or {}).get("name")
        if nm and len(nm) >= 2:
            name2code[nm] = c
    return name2code, set(stocks.keys())


def _tag(title, name2code, valid_codes):
    tags = []
    for nm, c in name2code.items():
        if nm in title:
            tags.append((c, nm))
    for m in re.findall(r"\d{4}[A-Z]?", title):       # 標題中的四碼，需是真實代碼
        if m in valid_codes and not any(c == m for c, _ in tags):
            nm = ""
            tags.append((m, m))
    # 去重
    out, seen = [], set()
    for c, nm in tags:
        if c not in seen:
            seen.add(c); out.append((c, nm))
    return out[:3]


def _reaction(code):
    h = src.yahoo_history(code + ".TW", rng="1mo") or src.yahoo_history(code + ".TWO", rng="1mo")
    c = A.clean(h["close"]) if h else []
    if len(c) < 6:
        return None
    d1 = c[-1] / c[-2] - 1
    d5 = c[-1] / c[-6] - 1
    if d1 >= 0.035 or d5 >= 0.12:
        label, light = "近期已大漲，利多多已反映（追高留意）", "amber"
    elif d1 <= -0.035 or d5 <= -0.12:
        label, light = "近期已大跌，利空多已反映", "amber"
    else:
        label, light = "尚未明顯反映", "green"
    return {"d1": d1, "d5": d5, "label": label, "light": light}


def assess(shared=None, twii_close=None) -> Optional[Dict]:
    heads = fetch_headlines()
    if not heads:
        return None
    name2code, valid = _name_map(shared)
    # 標記個股
    uniq_codes = []
    for h in heads:
        h["tags"] = _tag(h["title"], name2code, valid)
        for c, _ in h["tags"]:
            if c not in uniq_codes:
                uniq_codes.append(c)
    # 價格反應（限 12 檔）
    react = {}
    for c in uniq_codes[:12]:
        r = _reaction(c)
        if r:
            react[c] = r
    for h in heads:
        h["react"] = [(c, nm, react.get(c)) for c, nm in h["tags"] if react.get(c)]
    # 大盤層級「是否已反映」用工具現有讀數
    twii = A.clean(twii_close) if twii_close else []
    market = None
    if len(twii) >= 200:
        ext = A.dist_from_ma(twii, 200)
        if ext is not None:
            market = ("大盤已處於距 200 日均 %+.0f%% 的延伸狀態，AI 多頭題材大致已反映；"
                      "利空（槓桿/集中）通常尚未反映。" % (ext * 100))
    return {"headlines": heads, "market": market,
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


_CSS = """<style>
body{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:860px;margin:0 auto;padding:26px 20px 70px}
h1{font-size:23px;margin:0 0 2px}.muted{color:#5f7183;font-size:13px}a{color:#5b9cff;text-decoration:none}
h2{font-size:16px;margin:22px 0 10px;padding-left:10px;border-left:3px solid #5b9cff}
.box{background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;padding:12px 16px;margin-bottom:10px}
.nrow{padding:11px 2px;border-bottom:1px solid #222936}
.nt{font-size:15px}.src{color:#5f7183;font-size:12px}
.chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:7px;margin:5px 6px 0 0;background:#1e2a44}
.green{color:#28c76f}.amber{color:#f6a821}.red{color:#ea5455}
.warn{background:rgba(246,168,33,.10);border:1px solid rgba(246,168,33,.35);color:#ffd98a;
  padding:9px 13px;border-radius:9px;font-size:12.5px;margin-bottom:12px}
.brief{background:#141b27;border:1px solid #dbe4ee;border-radius:12px;padding:14px 18px;white-space:pre-wrap;font-size:14px}
</style>"""


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_news_page(data: Dict, briefing_html: str = None) -> str:
    import os
    from dashboard import nav, with_pwa
    parts = ['<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
             '<meta http-equiv="refresh" content="%d">' % getattr(cfg, "REFRESH_SECONDS", 1800),
             '<title>市場消息</title>', _CSS, '</head><body>', nav("news", include_css=True),
             '<div class="wrap">', '<h1>📰 市場消息</h1>',
             '<div class="muted">%s</div>' % _esc(data.get("generated_at", ""))]

    if briefing_html:
        parts.append('<h2>每日 AI 簡報（已多源查證真偽・非投資建議）</h2>')
        parts.append('<div class="brief">%s</div>' % briefing_html)

    parts.append('<h2>自動新聞監控</h2>')
    parts.append('<div class="warn">⚠️ 這區是機器抓的「標題」、<b>沒有判斷真偽</b>——新聞是拿來對照籌碼的，不是拿來當進場理由的；個股標籤旁是用「近期價格反應」'
                 '量化的『是否已反映』。真偽與合理性以上方 AI 簡報為準。非投資建議。</div>')
    if data.get("market"):
        parts.append('<div class="box">🌡️ 大盤：%s</div>' % _esc(data["market"]))
    for h in data["headlines"]:
        parts.append('<div class="nrow">')
        link = h.get("link") or "#"
        parts.append('<div class="nt"><a href="%s" target="_blank" rel="noopener">%s</a> '
                     '<span class="src">%s</span></div>' % (_esc(link), _esc(h["title"]), _esc(h["source"])))
        for c, nm, r in h.get("react", []):
            parts.append('<span class="chip"><b>%s</b> %s ・ 近5日 <span class="%s">%+.1f%%</span> ・ %s</span>'
                         % (_esc(nm or c), _esc(c), r["light"], r["d5"] * 100, _esc(r["label"])))
        parts.append('</div>')
    parts.append('<div class="muted" style="margin-top:16px">新聞來源：Google News、鉅亨網（自動聚合）。'
                 '本頁為研究與決策輔助，非投資建議。</div>')
    parts.append('</div></body></html>')
    html = with_pwa("".join(parts))
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(cfg.OUTPUT_DIR, "news.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return html


def set_news_adjust(delta, reason, confidence="中"):
    """由『已查證的簡報』寫入消息面微調（只反映尚未反映的催化/真偽變化）。"""
    import json, os
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    obj = {"delta": float(delta), "reason": reason, "confidence": confidence,
           "asof": dt.date.today().strftime("%Y-%m-%d")}
    with open(cfg.NEWS_ADJUST_FILE, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return obj


def load_news_adjust():
    import json, os
    if not os.path.exists(cfg.NEWS_ADJUST_FILE):
        return None
    try:
        with open(cfg.NEWS_ADJUST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def effective_news_adjust():
    """回傳 (delta_effective, info)：已套用上限與『時間線性衰退』。簡報沒更新就自動淡出。"""
    if not getattr(cfg, "NEWS_ADJUST_ENABLED", False):
        return 0.0, None
    na = load_news_adjust()
    if not na:
        return 0.0, None
    try:
        asof = dt.datetime.strptime(na["asof"], "%Y-%m-%d").date()
    except Exception:
        return 0.0, na
    age = (dt.date.today() - asof).days
    maxage = getattr(cfg, "NEWS_ADJUST_MAX_AGE_DAYS", 5)
    if age < 0 or age > maxage:
        return 0.0, na
    decay = max(0.0, 1 - age / maxage) if maxage else 1.0
    cap = getattr(cfg, "NEWS_ADJUST_CAP", 8)
    delta = max(-cap, min(cap, na.get("delta", 0))) * decay
    return round(delta, 1), na


def _load_briefing():
    """若 ②（每日 AI 簡報）有寫入 data/briefing.txt 就讀進來顯示。

    簡報是純文字、本身沒有有效期；若 ② 沒跑，舊簡報會一直被當成「今天的」顯示。
    所以這裡用檔案的最後修改時間把關：超過 BRIEFING_MAX_AGE_DAYS（預設 5 天）
    就視為過期、自動不顯示，避免三週前的分析被誤當成最新。
    """
    import os, time
    p = os.path.join(cfg.DATA_DIR, "briefing.txt")
    if not os.path.exists(p):
        return None
    maxage = getattr(cfg, "BRIEFING_MAX_AGE_DAYS", 5)
    try:
        age_days = (time.time() - os.path.getmtime(p)) / 86400.0
        if maxage and age_days > maxage:
            print("  · 簡報 briefing.txt 已 %.1f 天沒更新（>%d 天）→ 自動不顯示"
                  % (age_days, maxage))
            return None
        with open(p, encoding="utf-8") as f:
            return _esc(f.read().strip())
    except Exception:
        return None


# -*- coding: utf-8 -*-
r"""個股版進場分數（台股）。輸入代碼，套用同一套邏輯算出該檔的進場分數。

組成（權重在 config.STOCK_WEIGHTS）：
  • 大盤環境：用儀表板最近一次算出的綜合分數（同個大背景，人人一樣）。
  • 個股趨勢：距 200 日均、RSI、距 52 週高點回檔。
  • 個股籌碼：法人（外資＋投信）近 5 日買超 vs 散戶融資變化（個股版『法人 vs 散戶』）。
  • 個股估值：優先用「跟自身歷史比」的相對估值（每天累積），不足時退用「相對大盤中位數」。

兩種用法：
  py -X utf8 stock.py 2330        # 單一個股，印報告並產生 output/stock-2330.html
  （main.py 會自動把 config.STOCK_WATCHLIST 全部算好＋全市場輕量分，做成 output/stocks.html 個股分頁）

每檔另附『離場訊號』（續抱/警戒/減碼＋停損參考線）：進場看便宜、離場看趨勢轉弱，兩者互補。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import sys
import time

import analytics as A
import config as cfg
import sources as src
import scoring


def _band(score):
    return "green" if score >= cfg.LIGHT_GREEN_MIN else "red" if score < cfg.LIGHT_RED_MAX else "amber"


def _env_score():
    try:
        return json.load(open(cfg.RAW_CACHE, encoding="utf-8")).get("composite")
    except Exception:
        return None


# ------------------------- 個股估值歷史（算相對估值） -------------------------
def _record_val(code, val, date_str):
    if not val or val.get("pb") is None:
        return
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    seen = set()
    rows = []
    if os.path.exists(cfg.HISTORY_STOCK_VAL):
        with open(cfg.HISTORY_STOCK_VAL, encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) >= 2:
                    rows.append(r)
                    seen.add((r[0], r[1]))
    if (date_str, str(code)) in seen:
        return
    rows.append([date_str, str(code),
                 "" if val.get("pb") is None else val["pb"],
                 "" if val.get("pe") is None else val["pe"],
                 "" if val.get("yield") is None else val["yield"]])
    with open(cfg.HISTORY_STOCK_VAL, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


_VALH_CACHE = None


def _load_valh():
    global _VALH_CACHE
    if _VALH_CACHE is not None:
        return _VALH_CACHE
    cache = {}
    if os.path.exists(cfg.HISTORY_STOCK_VAL):
        with open(cfg.HISTORY_STOCK_VAL, encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) < 5:
                    continue
                pbs, ylds = cache.setdefault(r[1], ([], []))
                try:
                    if r[2]:
                        pbs.append(float(r[2]))
                except ValueError:
                    pass
                try:
                    if r[4]:
                        ylds.append(float(r[4]))
                except ValueError:
                    pass
    _VALH_CACHE = cache
    return cache


# ------------- 全市場收盤價滾動快照（給搜尋股輕量技術分；每日累積） -------------
_PRICEHIST = os.path.join(cfg.DATA_DIR, "price_hist_all.csv")


def _record_prices(dayohlc, date_str, keep_days=90):
    """把今日全市場收盤追加到 price_hist_all.csv（date,code,close），同日去重、只留最近 keep_days 個交易日。"""
    if not dayohlc:
        return
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    seen, rows = set(), []
    if os.path.exists(_PRICEHIST):
        with open(_PRICEHIST, encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) >= 3:
                    rows.append(r); seen.add((r[0], r[1]))
    added = 0
    for code, o in dayohlc.items():
        c = o.get("close")
        if c is None:
            continue
        d = o.get("date") or date_str
        if (d, code) in seen:
            continue
        rows.append([d, code, "%.4f" % c]); added += 1
    if not added:
        return
    dates = sorted({r[0] for r in rows})
    keep = set(dates[-keep_days:])
    rows = [r for r in rows if r[0] in keep]
    rows.sort(key=lambda r: (r[1], r[0]))
    with open(_PRICEHIST, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


def _load_price_hist(maxdays=80):
    """{code:[closes...]} 依日期遞增（最近 maxdays 個交易日）。"""
    if not os.path.exists(_PRICEHIST):
        return {}
    by = {}
    with open(_PRICEHIST, encoding="utf-8", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 3:
                continue
            try:
                by.setdefault(r[1], []).append((r[0], float(r[2])))
            except ValueError:
                pass
    out = {}
    for code, seq in by.items():
        seq.sort()
        out[code] = [c for _, c in seq[-maxdays:]]
    return out


def _lite_tech(ohlc, hist_closes):
    """輕量技術分：今日 K 線/收盤位置/漲跌 +（有歷史時）短均線與動能。回傳 (score, disp)。"""
    if not ohlc:
        return (None, "")
    o, h, l, c, chg = (ohlc.get("open"), ohlc.get("high"), ohlc.get("low"),
                       ohlc.get("close"), ohlc.get("change"))
    subs, tags = [], []
    if None not in (o, h, l, c) and h > l:
        rng = h - l
        body = abs(c - o)
        pos = (c - l) / rng
        tags.append("紅K" if c >= o else "黑K")
        subs.append(A.linmap(pos, 0, 1, 38, 68))
        tags.append("收高檔" if pos >= 0.7 else "收低檔" if pos <= 0.3 else "收中段")
        if (min(o, c) - l) / rng >= 0.5 and body / rng <= 0.35:
            tags.append("長下影")
        elif (h - max(o, c)) / rng >= 0.5 and body / rng <= 0.35:
            tags.append("長上影")
    if chg is not None and c is not None:
        prev = c - chg
        if prev > 0:
            chgp = chg / prev * 100
            subs.append(A.piecewise(chgp, [(-6, 30), (-2, 44), (0, 52), (2, 60), (6, 70)]))
            tags.append("%+.1f%%" % chgp)
    closes = list(hist_closes or [])
    if c is not None:
        closes = closes + [c]
    if len(closes) >= 11:
        d20 = A.dist_from_ma(closes, min(20, len(closes) - 1))
        if d20 is not None:
            subs.append(A.piecewise(d20, [(-0.1, 40), (0, 52), (0.1, 64)]))
            tags.append("站上均線" if d20 >= 0 else "跌破均線")
        mom = A.pct_change(closes, min(10, len(closes) - 1))
        if mom is not None:
            subs.append(A.piecewise(mom, [(-0.12, 36), (0, 52), (0.12, 66)]))
    else:
        tags.append("均線資料累積中")
    if not subs:
        return (None, "")
    return (round(A.clamp(sum(subs) / len(subs), 10, 90), 1), "・".join(tags[:5]))


def _val_history(code):
    return _load_valh().get(str(code), ([], []))


# ------------------------- 各面向 -------------------------
def _stock_trend(close, hist=None):
    """個股趨勢綜合分：長期趨勢品質(A) + 便宜/逆勢 + 技術動能(C) + K線型態(B)。
    哲學＝『在健康的長期趨勢裡買拉回』：趨勢健康(順勢)拉高、跌深超賣(逆勢)拉高、
    但趨勢轉弱(空頭排列/死亡交叉)會壓低分數，避免接刀。"""
    parts = []

    # 1) 長期趨勢品質（趨勢結構，順勢；不採 mean-reversion）
    tq_subs = []
    align = A.ma_alignment(close)
    if align is not None:
        tq_subs.append(A.linmap(align, -1, 1, 25, 82))
        parts.append("均線" + ("多頭" if align > 0.3 else "空頭" if align < -0.3 else "糾結"))
    slope = (A.ma_slope(close, 200, 20) if len(close) >= 220 else
             A.ma_slope(close, 120, 20) if len(close) >= 140 else None)
    if slope is not None:
        tq_subs.append(A.piecewise(slope * 1000, [(-1, 28), (0, 52), (1, 80)]))
    kind, _g = A.cross(close, 50, 200, lookback=60)
    tq = (sum(tq_subs) / len(tq_subs)) if tq_subs else None
    if tq is not None and kind == "golden":
        tq = min(95.0, tq + 7); parts.append("黃金交叉")
    elif tq is not None and kind == "death":
        tq = max(5.0, tq - 9); parts.append("死亡交叉")

    # 2) 便宜 / 逆勢（距高點 + RSI + 布林）
    dip_subs = []
    dd = A.drawdown_from_high(close, 252)
    if dd is not None:
        dip_subs.append(A.piecewise(dd, [(-0.40, 92), (-0.25, 82), (-0.15, 72),
                                         (-0.08, 60), (-0.03, 50), (0.0, 42)]))
        parts.append("距高 %+.1f%%" % (dd * 100))
    rsi = A.rsi(close, 14)
    if rsi is not None:
        dip_subs.append(A.piecewise(rsi, [(20, 90), (30, 78), (40, 64), (50, 52),
                                          (60, 42), (70, 30), (80, 20)]))
        parts.append("RSI %.0f" % rsi)
    pb = A.bollinger_pctb(close, 20, 2.0)
    if pb is not None:
        dip_subs.append(A.piecewise(pb, [(-0.2, 86), (0, 78), (0.5, 52), (1.0, 28), (1.2, 20)]))
    dip = (sum(dip_subs) / len(dip_subs)) if dip_subs else None

    # 3) 技術動能(MACD) + K 線型態
    tech_subs = []
    _ml, _sig, hgram = A.macd(close)
    if hgram is not None:
        hn = (hgram / close[-1] * 100) if close[-1] else 0.0
        tech_subs.append(A.piecewise(hn, [(-1, 32), (0, 52), (1, 70)]))
        parts.append("MACD" + ("翻紅" if hgram > 0 else "翻黑"))
    if hist:
        ck = A.candle_read(hist.get("open"), hist.get("high"), hist.get("low"),
                           hist.get("close"), hist.get("volume"))
        if ck:
            cs = 50.0
            if ck["long_lower"]:
                cs += 10; parts.append("長下影止跌")
            if ck["new_low20"]:
                cs += 6
            if ck["long_upper"]:
                cs -= 8
            if ck.get("vol_ratio", 1) >= 1.8 and not ck["bull"]:
                cs -= 10; parts.append("爆量長黑")
            tech_subs.append(A.clamp(cs, 20, 80))
    tech = (sum(tech_subs) / len(tech_subs)) if tech_subs else None

    # 加權混合：趨勢品質 0.4 / 便宜逆勢 0.4 / 技術 0.2（缺項自動剔除）
    blend = []
    if tq is not None:
        blend.append((tq, 0.4))
    if dip is not None:
        blend.append((dip, 0.4))
    if tech is not None:
        blend.append((tech, 0.2))
    if not blend:
        return (None, "")
    score = sum(v * w for v, w in blend) / sum(w for _, w in blend)
    return (round(score, 1), "　".join(parts[:5]))


def _stock_exit(close, net5=0, margin_chg=None):
    """離場訊號（給持有者）：趨勢轉弱/跌破均線/高檔回落/籌碼惡化 → 急迫度 0-100。
    與『進場分數』互補：進場看便宜，離場看風險與趨勢破壞。"""
    if len(close) < 60:
        return None
    price = close[-1]
    ma50 = A.sma(close, 50)
    ma200 = A.sma(close, 200)
    rsi_now = A.rsi(close)
    rsi_prev = A.rsi(close[:-5]) if len(close) > 20 else None
    dist200 = A.dist_from_ma(close, 200)
    hi20 = max(close[-20:])
    dd20 = price / hi20 - 1 if hi20 else 0
    dd52 = A.drawdown_from_high(close, 252) or 0
    score, sig = 0, []
    if ma50 and price < ma50:
        score += 35; sig.append("已跌破 50 日均線")
    elif ma50 and price < ma50 * 1.015:
        score += 15; sig.append("逼近 50 日均線")
    if ma200 and price < ma200:
        score += 18; sig.append("跌破 200 日均線")
    elif ma50 and ma200 and ma50 < ma200:
        score += 8; sig.append("均線空頭排列(50<200)")
    if dist200 is not None and dist200 > 0.15 and dd20 < -0.06:
        score += 15; sig.append("高檔回落（距20日高 %.0f%%）" % (dd20 * 100))
    if rsi_now is not None and rsi_prev is not None and rsi_prev > 70 and rsi_now < rsi_prev - 5:
        score += 12; sig.append("RSI 由超買轉弱（%.0f→%.0f）" % (rsi_prev, rsi_now))
    if dd52 < -0.20:
        score += 15; sig.append("距52週高回檔 %.0f%%" % (dd52 * 100))
    if net5 < 0 and margin_chg is not None and margin_chg > 0:
        score += 10; sig.append("法人賣＋散戶加碼（高檔出貨疑慮）")
    score = int(A.clamp(score, 0, 100))
    status = "減碼/離場" if score >= 55 else "警戒" if score >= 30 else "續抱"
    light = "red" if score >= 55 else "amber" if score >= 30 else "green"
    stop = ("停損/減碼參考線：跌破 50 日均線（約 %.0f）即觸發" % ma50) if ma50 else ""
    if not sig:
        sig = ["趨勢完好，無明顯離場訊號"]
    return {"score": score, "status": status, "light": light, "signals": sig, "stop": stop}


def _stock_chips(net5, avg_vol, margin_prev, margin_today):
    scores, w = [], []
    inst_disp = mar_disp = ""
    margin_chg = None
    if avg_vol and avg_vol > 0:
        ratio = net5 / avg_vol
        scores.append(A.piecewise(ratio, [(-3, 12), (-1, 32), (-0.3, 44), (0, 50),
                                          (0.5, 62), (1.5, 76), (3, 88), (6, 95)]))
        w.append(1.5)
        inst_disp = "法人近5日 %+.0f 張（約 %.1f 日量）" % (net5 / 1000, ratio)
    if margin_prev and margin_prev > 0 and margin_today is not None:
        margin_chg = margin_today / margin_prev - 1
        scores.append(A.clamp(50 - (margin_chg / 0.05) * 35, 15, 85))
        w.append(1.0)
        mar_disp = "融資 %+.1f%%（%s）" % (margin_chg * 100, "散戶加碼" if margin_chg >= 0 else "散戶減碼")
    if not scores:
        return None, "", ""
    score = sum(s * x for s, x in zip(scores, w)) / sum(w)
    verdict = ""
    if net5 > 0 and margin_chg is not None and margin_chg < 0:
        verdict = "法人買超＋散戶減碼 → 聰明錢進、散戶退（偏多背離）"
    elif net5 < 0 and margin_chg is not None and margin_chg > 0:
        verdict = "法人賣超＋散戶加碼 → 散戶接刀（偏空背離）"
    return score, "　".join(x for x in (inst_disp, mar_disp) if x), verdict


def _stock_valuation(val, code, median_pb, median_yield):
    if not val or val.get("pb") is None:
        return None, ""
    pb, yld = val.get("pb"), val.get("yield")
    pbs, ylds = _val_history(code)
    # 1) 自身歷史百分位（最理想；低 PB 百分位＝相對自己便宜）
    if len(pbs) >= cfg.STOCK_VAL_MIN_HISTORY:
        pb_pct = A.percentile_rank(pb, pbs)
        score = 100 - pb_pct
        parts = ["PB %.2f（自身 %.0f 百分位）" % (pb, pb_pct)]
        if yld is not None and len(ylds) >= cfg.STOCK_VAL_MIN_HISTORY:
            y_pct = A.percentile_rank(yld, ylds)
            score = (score + y_pct) / 2
            parts.append("殖利率自身 %.0f 百分位" % y_pct)
        return score, "　".join(parts) + "（vs 自身歷史）"
    # 2) 相對大盤中位數
    if median_pb:
        ratio = pb / median_pb
        score = A.piecewise(ratio, [(0.5, 82), (1, 58), (2, 46), (4, 34), (8, 24), (15, 16)])
        parts = ["PB %.2f（大盤中位 %.1f 倍）" % (pb, ratio)]
        if yld is not None and median_yield:
            yr = yld / median_yield
            score = (score + A.piecewise(yr, [(0.3, 22), (0.7, 40), (1, 55), (1.5, 72), (2.5, 88)])) / 2
            parts.append("殖利率為大盤 %.1f 倍" % yr)
        return score, "　".join(parts) + "（vs 大盤中位數）"
    # 3) 最後退路：絕對門檻
    score = A.piecewise(pb, [(0.8, 90), (1.5, 72), (2.5, 56), (4, 44), (7, 32), (12, 22)])
    return score, "PB %.2f（絕對門檻）" % pb


# ------------------------- 共用資料（一次抓、給所有個股用） -------------------------
def fetch_shared(n_days=None):
    n_days = n_days or cfg.STOCK_INST_DAYS
    net5, got, latest = {}, 0, None
    d, walked = dt.date.today(), 0
    while got < n_days and walked < 20:
        if d.weekday() < 5:
            ds = d.strftime("%Y%m%d")
            t86 = src.twse_t86(ds)
            if t86:
                for code, row in t86.items():
                    net5[code] = net5.get(code, 0) + (row.get("foreign") or 0) + (row.get("invtrust") or 0)
                got += 1
                if latest is None:
                    latest = ds
                time.sleep(0.5)   # 降低 TWSE T86 連續請求被限流的機率
        d -= dt.timedelta(days=1)
        walked += 1
    # 三大法人(T86) 偶發整批回空（限流）→ 用上次成功的快取，避免「推薦 0 檔」
    if net5:
        src._cache_save("net5", {"net5": net5, "latest": latest})
    else:
        cached = src._cache_load("net5") or {}
        net5 = cached.get("net5", {})
        latest = latest or cached.get("latest")
    # 融資餘額(MI_MARGN) 與 三大法人(T86) 公布時間不同：收盤後 T86 較快、融資餘額較慢，
    # 用 T86 的最新日去抓融資常抓到「當日尚未公布」的空集合。改為往回找最近有融資資料的交易日。
    margin = None
    md = dt.datetime.strptime(latest, "%Y%m%d").date() if latest else dt.date.today()
    for _ in range(8):
        if md.weekday() < 5:
            m = src.twse_margin_all(md.strftime("%Y%m%d"))
            if m:
                margin = m
                break
        md -= dt.timedelta(days=1)
    valuation = src.twse_valuation_all()
    # 併入上櫃(OTC)估值，讓搜尋也涵蓋櫃買股（上市股無 market 欄＝視為 tse）
    otc = src.tpex_valuation_all()
    if valuation and otc and otc.get("stocks"):
        valuation["stocks"].update(otc["stocks"])
    elif otc and otc.get("stocks") and not valuation:
        valuation = otc
    industry = src.twse_industry() or {}
    twii = src.yahoo_history("^TWII", rng="1y")
    # 全市場當日 OHLC（上市＋上櫃）→ 累積收盤快照 + 供輕量技術分
    dayohlc = src.twse_stock_day_all() or {}
    for k, v in (src.tpex_stock_day_all() or {}).items():
        dayohlc.setdefault(k, v)
    _record_prices(dayohlc, latest or dt.date.today().strftime("%Y%m%d"))
    pricehist = _load_price_hist()
    announce = src.twse_announcements() or {}
    return {"net5": net5, "margin": margin or {}, "valuation": valuation,
            "industry": industry, "twii_close": A.clean(twii["close"]) if twii else [],
            "dayohlc": dayohlc, "pricehist": pricehist, "announce": announce,
            "latest": latest}


_THEME_MAP = None


def _theme_map():
    global _THEME_MAP
    if _THEME_MAP is None:
        _THEME_MAP = {}
        for theme, codes in getattr(cfg, "THEMES", {}).items():
            for c in codes:
                _THEME_MAP.setdefault(str(c), []).append(theme)
    return _THEME_MAP


def _tags(code, industry_name):
    themes = _theme_map().get(str(code), [])
    has = bool(themes) or (industry_name in getattr(cfg, "HOT_INDUSTRIES", []))
    return industry_name or "", themes, has


def _tag_text(industry, themes):
    bits = []
    if themes:
        bits.append("題材：" + "、".join(themes))
    if industry:
        bits.append("產業：" + industry)
    return "　".join(bits)


# ------------------------- 計算單一個股 -------------------------
def compute(code, env=None, shared=None, record=True):
    base = str(code).strip().upper().split(".")[0]
    suffix = str(code).split(".")[1] if "." in str(code) else None
    cands = (["%s.%s" % (base, suffix)] if suffix else ["%s.TW" % base, "%s.TWO" % base])

    hist = None
    for c in cands:
        hist = src.yahoo_history(c, rng="2y")
        if hist and A.clean(hist["close"]):
            break
    if not hist or not A.clean(hist["close"]):
        return None
    close = A.clean(hist["close"])
    vols = [v for v in A.clean(hist["volume"]) if v > 0]
    avg_vol = sum(vols[-20:]) / 20 if len(vols) >= 20 else (sum(vols) / len(vols) if vols else None)

    if shared is None:
        shared = fetch_shared()
    if env is None:
        env = _env_score()

    val_all = (shared.get("valuation") or {}).get("stocks", {})
    val = val_all.get(base) or src.twse_stock_valuation(base)
    name = (val or {}).get("name") or base
    industry, themes, has_theme = _tags(base, (shared.get("industry") or {}).get(base, ""))
    median_pb = (shared.get("valuation") or {}).get("median_pb")
    median_yield = (shared.get("valuation") or {}).get("median_yield")

    net5 = shared["net5"].get(base, 0)
    mrow = (shared.get("margin") or {}).get(base) or {}
    margin_prev, margin_today = mrow.get("margin_prev"), mrow.get("margin_today")

    if record and val:
        _record_val(base, val, shared.get("latest") or dt.date.today().strftime("%Y%m%d"))

    margin_chg = (margin_today / margin_prev - 1) if (margin_prev and margin_prev > 0
                                                      and margin_today is not None) else None
    trend_s, trend_disp = _stock_trend(close, hist)
    chips_s, chips_disp, chips_verdict = _stock_chips(net5, avg_vol, margin_prev, margin_today)
    val_s, val_disp = _stock_valuation(val, base, median_pb, median_yield)
    exit_sig = _stock_exit(close, net5, margin_chg)

    comps = []
    if env is not None:
        comps.append(("大盤環境", env, cfg.STOCK_WEIGHTS["env"], "（儀表板綜合分數）"))
    if trend_s is not None:
        comps.append(("個股趨勢", trend_s, cfg.STOCK_WEIGHTS["trend"], trend_disp))
    if chips_s is not None:
        comps.append(("個股籌碼", chips_s, cfg.STOCK_WEIGHTS["chips"], chips_disp))
    if val_s is not None:
        comps.append(("個股估值", val_s, cfg.STOCK_WEIGHTS["valuation"], val_disp))
    if not comps:
        return None
    score = round(sum(s * w for _, s, w, _ in comps) / sum(w for _, _, w, _ in comps), 1)
    band, action, mult = scoring._interpret(score)
    # 重大訊息 / 法說會旗標
    ann = (shared.get("announce") or {}).get(base)
    flag, flagtxt = "", ""
    if ann:
        flag = "📢 法說會" if any(a.get("conf") for a in ann) else "⚠ 重訊"
        flagtxt = ann[0].get("subject", "")
    return {"code": base, "name": name, "price": close[-1], "score": score,
            "band": band, "action": action, "multiplier": mult, "light": _band(score),
            "components": comps, "chips_verdict": chips_verdict, "exit": exit_sig,
            "flag": flag, "flagtxt": flagtxt,
            "industry": industry, "themes": themes, "has_theme": has_theme,
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


# ------------------------- 全市場輕量分（給搜尋用，不含趨勢、不抓個股 Yahoo） -------------------------
def compute_lite(code, env, shared):
    val_all = (shared.get("valuation") or {}).get("stocks", {})
    val = val_all.get(code)
    if not val:
        return None
    median_pb = (shared.get("valuation") or {}).get("median_pb")
    median_yield = (shared.get("valuation") or {}).get("median_yield")
    net5 = shared["net5"].get(code, 0)
    mrow = (shared.get("margin") or {}).get(code) or {}
    margin_prev, margin_today = mrow.get("margin_prev"), mrow.get("margin_today")

    # 籌碼輕量版：以融資變化(自身正規化)為主，法人買賣超的方向做微調
    chips = None
    margin_chg = None
    if margin_prev and margin_prev > 0 and margin_today is not None:
        margin_chg = margin_today / margin_prev - 1
        chips = A.clamp(50 - (margin_chg / 0.05) * 35, 15, 85)
    inst_adj = max(-12, min(12, (net5 / 1000) / 50 * 12)) if net5 else 0
    if chips is None and net5:
        chips = A.clamp(50 + inst_adj * 1.4, 20, 80)
    elif chips is not None:
        chips = A.clamp(chips + inst_adj, 10, 92)
    val_s, val_disp = _stock_valuation(val, code, median_pb, median_yield)

    # 輕量技術分（今日 K 線 + 收盤位置 + 漲跌 +（累積後）短均線/動能）
    ohlc = (shared.get("dayohlc") or {}).get(code)
    phist = (shared.get("pricehist") or {}).get(code)
    tech_s, tech_disp = _lite_tech(ohlc, phist)
    # 重大訊息 / 法說會旗標
    ann = (shared.get("announce") or {}).get(code)
    flag, flagtxt = "", ""
    if ann:
        if any(a.get("conf") for a in ann):
            flag = "📢 法說會"
        else:
            flag = "⚠ 重訊"
        flagtxt = ann[0].get("subject", "")

    comps, w = [], []
    if env is not None:
        comps.append(env); w.append(cfg.STOCK_WEIGHTS["env"])
    if chips is not None:
        comps.append(chips); w.append(cfg.STOCK_WEIGHTS["chips"])
    if val_s is not None:
        comps.append(val_s); w.append(cfg.STOCK_WEIGHTS["valuation"])
    if tech_s is not None:
        comps.append(tech_s); w.append(cfg.STOCK_WEIGHTS.get("lite_tech", 12))
    if not comps:
        return None
    score = round(sum(s * x for s, x in zip(comps, w)) / sum(w), 1)
    industry, themes, _ = _tags(code, (shared.get("industry") or {}).get(code, ""))

    market = val.get("market", "tse")
    is_otc = market == "otc"
    # 詳細資訊（給搜尋展開用）
    if is_otc and chips is None:
        cd_parts = ["上櫃股：暫無個股法人/融資資料（櫃買未提供個股級資料）"]
    else:
        cd_parts = ["法人近5日 %+.0f 張" % (net5 / 1000)]
        if margin_chg is not None:
            cd_parts.append("融資 %+.1f%%（%s）" % (margin_chg * 100, "散戶加碼" if margin_chg >= 0 else "散戶減碼"))
    diverg = ""
    if net5 > 0 and margin_chg is not None and margin_chg < 0:
        diverg = "偏多背離（法人買、散戶退）"
    elif net5 < 0 and margin_chg is not None and margin_chg > 0:
        diverg = "偏空背離（法人賣、散戶追）"
    band, action, mult = scoring._interpret(score)
    # 一句話分析（輕量版，非投資建議）
    bits = []
    if val_s is not None:
        bits.append("估值偏低" if val_s >= 60 else ("估值偏高" if val_s <= 40 else "估值中性"))
    if diverg:
        bits.append(diverg)
    elif chips is not None:
        bits.append("籌碼偏多" if chips >= 58 else ("籌碼偏空" if chips <= 42 else "籌碼中性"))
    elif is_otc:
        bits.append("籌碼資料不足")
    if tech_disp:
        bits.append("技術:" + tech_disp.split("・")[0] + ("・" + tech_disp.split("・")[1]
                    if "・" in tech_disp else ""))
    if themes:
        bits.append("題材:" + "/".join(themes))
    if flag:
        bits.append(flag)
    analysis = ("、".join(bits) + "　→ " + action) if bits else action
    return {"code": code, "name": val.get("name") or code, "score": score,
            "band": band, "action": action, "market": market, "analysis": analysis,
            "env": round(env) if env is not None else None,
            "chips": round(chips) if chips is not None else None,
            "val": round(val_s) if val_s is not None else None,
            "tech": round(tech_s) if tech_s is not None else None, "tech_disp": tech_disp,
            "flag": flag, "flagtxt": flagtxt,
            "industry": industry, "themes": themes,
            "price": val.get("close"), "chips_disp": "　".join(cd_parts),
            "val_disp": val_disp, "diverg": diverg}


def recommend(env, shared, universe, n=None):
    """自動選股：從全市場挑『進場分數最高、且法人買超』的中大型股，回傳完整評分(含趨勢/離場)。"""
    n = n or getattr(cfg, "STOCK_TOP_N", 8)
    stocks = (shared.get("valuation") or {}).get("stocks", {})
    margin = shared.get("margin") or {}
    industry = shared.get("industry") or {}
    require_theme = getattr(cfg, "STOCK_TOP_REQUIRE_THEME", True)

    def pool(theme_filter):
        out = []
        for x in (universe or []):
            code = x["code"]
            net5 = shared["net5"].get(code, 0)
            price = (stocks.get(code) or {}).get("close") or 0
            mt = (margin.get(code) or {}).get("margin_today") or 0
            if not (price >= cfg.STOCK_TOP_MIN_PRICE and net5 > 0 and mt >= cfg.STOCK_TOP_MIN_MARGIN):
                continue
            if theme_filter:
                _, _, has = _tags(code, industry.get(code, ""))
                if not has:
                    continue
            out.append((x["score"], code))
        return out

    cand = pool(require_theme)
    if not cand and require_theme:        # 題材篩完沒東西就放寬，避免空清單
        cand = pool(False)
    cand.sort(reverse=True)
    full = []
    for _, code in cand[:max(n * 2, 16)]:
        r = compute(code, env=env, shared=shared)
        if r:
            full.append(r)
        time.sleep(0.15)
    full.sort(key=lambda r: r["score"], reverse=True)
    return full[:n]


def theme_heat(shared, universe, top=3):
    """今日題材熱度：對 config.THEMES 每個題材算成員的平均 20 日動能＋法人合計買超。

    題材表只負責「命名」；熱度完全由當天資料決定——成員平均漲、法人在買
    的題材才會被選股引用。成員在池內不足 2 檔的題材不計（單檔不成題材）。
    回傳 [{"theme","mom","net5","n"}]，依熱度排序取前 top 名（動能 ≤+2% 的不算熱）。
    """
    if not shared or not universe:
        return []
    stocks = (shared.get("valuation") or {}).get("stocks", {})
    net5 = shared.get("net5") or {}
    phist = shared.get("pricehist") or {}
    in_pool = {x["code"] for x in universe}

    def _mom(code):
        closes = list(phist.get(code) or [])
        px = (stocks.get(code) or {}).get("close")
        if px:
            closes = closes + [px]
        if len(closes) < 11:
            return None
        look = min(20, len(closes) - 1)
        return closes[-1] / closes[-1 - look] - 1.0

    out = []
    for theme, codes in getattr(cfg, "THEMES", {}).items():
        members = [str(c) for c in codes if str(c) in in_pool]
        moms = [m for m in (_mom(c) for c in members) if m is not None]
        if len(moms) < 2:
            continue
        avg_mom = sum(moms) / len(moms)
        tot_net = sum((net5.get(c, 0) or 0) for c in members)
        if avg_mom <= 0.02:
            continue                       # 題材成員平均沒在漲就不算熱
        heat = avg_mom * 100 + min(tot_net / 1000 / 5000, 6)   # 動能為主、法人買超封頂加分
        out.append({"theme": theme, "mom": avg_mom, "net5": tot_net,
                    "n": len(moms), "_heat": heat})
    out.sort(key=lambda t: -t["_heat"])
    return out[:top]


def faction_picks(shared, universe, n=3):
    """五派選股（觀點頁用）：同一個股票池，三種選法各取前 n 檔（互不重複）。

    順勢＝20日動能強＋站上月線＋法人在買；籌碼＝法人5日追買最兇（散戶未跟加分）；
    價值＝估值子分最高＋法人有買。被動/總經兩派不選股（那是它們的觀點）。
    回傳 {"trend": [...], "chips": [...], "value": [...]}，每檔 {code,name,why}。
    """
    if not shared or not universe:
        return None
    stocks = (shared.get("valuation") or {}).get("stocks", {})
    net5 = shared.get("net5") or {}
    margin = shared.get("margin") or {}
    phist = shared.get("pricehist") or {}
    min_price = getattr(cfg, "STOCK_TOP_MIN_PRICE", 30)
    rows = {x["code"]: x for x in universe}
    taken = set()

    def _mom(code):
        closes = list(phist.get(code) or [])
        px = (stocks.get(code) or {}).get("close")
        if px:
            closes = closes + [px]
        if len(closes) < 11:
            return None, None
        look = min(20, len(closes) - 1)
        m = closes[-1] / closes[-1 - look] - 1.0
        d20 = A.dist_from_ma(closes, min(20, len(closes) - 1))
        return m, d20

    def _base_ok(code):
        px = (stocks.get(code) or {}).get("close") or 0
        return code not in taken and px >= min_price and (net5.get(code, 0) or 0) > 0

    def _fmt_net(code):
        return "法人5日%+.0f張" % ((net5.get(code, 0) or 0) / 1000)

    out = {}
    # 1) 順勢動能榜——順勢派自己的紀律：別追末端妖股、要有真法人背書。
    #    「跟題材」：熱門題材（theme_heat）成員加熱度分，優先站上風口的動能股。
    hot = theme_heat(shared, universe)
    hot_names = [t["theme"] for t in hot]
    tmap = _theme_map()
    cand = []
    for code, x in rows.items():
        if not _base_ok(code):
            continue
        my_hot = next((t for t in tmap.get(code, []) if t in hot_names), None)
        # 風口題材成員門檻放寬（+5%、200張）：早期還沒噴的也看得到；
        # 非題材股維持嚴門檻（+8%、300張）。妖股上限與月線紀律一律不放。
        net_floor = 200_000 if my_hot else 300_000
        mom_floor = 0.05 if my_hot else 0.08
        if (net5.get(code, 0) or 0) < net_floor:
            continue
        m, d20 = _mom(code)
        if m is None or not (mom_floor <= m <= 0.50) or (d20 is not None and d20 < 0):
            continue
        cand.append((m, code, d20, my_hot))
    cand.sort(reverse=True)
    # 保留名額制：三席至少兩席給熱門題材（有合格者才給，不硬塞）
    hot_cand = [c for c in cand if c[3]]
    picks_rows = list(hot_cand[:min(2, n)])
    for c in cand:
        if len(picks_rows) >= n:
            break
        if c not in picks_rows:
            picks_rows.append(c)
    picks_rows.sort(reverse=True)          # 版面仍按動能高→低呈現
    picks = []
    for m, code, d20, my_hot in picks_rows:
        taken.add(code)
        why = ("🔥%s・" % my_hot) if my_hot else ""
        why += "20日%+.0f%%" % (m * 100)
        if d20 is not None and d20 >= 0:
            why += "・站上月線"
        picks.append({"code": code, "name": rows[code]["name"],
                      "why": why + "・" + _fmt_net(code)})
    out["trend"] = picks
    out["hot_themes"] = [{"theme": t["theme"], "mom": t["mom"], "n": t["n"]} for t in hot]
    # 2) 價值便宜榜
    cand = [(x.get("val") or 0, code) for code, x in rows.items()
            if _base_ok(code) and (x.get("val") or 0) >= 60]   # 真便宜才上榜
    cand.sort(reverse=True)
    picks = []
    for v, code in cand[:n]:
        taken.add(code)
        vd = (rows[code].get("val_disp") or "").split("｜")[0].strip()
        picks.append({"code": code, "name": rows[code]["name"],
                      "why": (vd + "・" if vd else "") + _fmt_net(code)})
    out["value"] = picks
    # 3) 籌碼追買榜（候選最多、放最後）
    cand = []
    for code, x in rows.items():
        if not _base_ok(code):
            continue
        mrow = margin.get(code) or {}
        mp, mt = mrow.get("margin_prev"), mrow.get("margin_today")
        mchg = (mt / mp - 1) if (mp and mp > 0 and mt is not None) else None
        smart = 1 if (mchg is not None and mchg <= 0) else 0   # 法人買、散戶沒跟 → 加分
        cand.append(((net5.get(code, 0) or 0) * (1.3 if smart else 1.0), code, mchg))
    cand.sort(reverse=True)
    picks = []
    for _, code, mchg in cand[:n]:
        taken.add(code)
        why = _fmt_net(code)
        if mchg is not None:
            why += "・融資%+.1f%%（散戶%s）" % (mchg * 100, "減碼" if mchg <= 0 else "加碼")
        picks.append({"code": code, "name": rows[code]["name"], "why": why})
    out["chips"] = picks
    return out if any(out.values()) else None


def build_universe(env, shared):
    stocks = (shared.get("valuation") or {}).get("stocks", {})
    out = []
    for code in stocks:
        # 只收純數字代碼（過濾權證/特殊商品）
        if not (code and code.isdigit() and len(code) == 4):
            continue
        r = compute_lite(code, env, shared)
        if r:
            out.append(r)
    return out


# ------------------------- 輸出 -------------------------
def analyze(code_input):
    print("查詢 %s …" % code_input)
    r = compute(code_input)
    if not r:
        print("✗ 找不到資料（上櫃股請加 .TWO）。")
        return None
    print("\n" + "=" * 56)
    print(" %s（%s）  收盤 %.2f" % (r["name"], r["code"], r["price"]))
    print(" 個股進場分數：%.1f → %s（建議定額 %.2gx）" % (r["score"], r["band"], r["multiplier"]))
    print("=" * 56)
    for label, s, w, disp in r["components"]:
        print(" %-8s %5.1f  (權重 %d%%)  %s" % (label, s, w, disp))
    if r["chips_verdict"]:
        print(" ★ " + r["chips_verdict"])
    ex = r.get("exit")
    if ex:
        print(" 離場訊號：%s（急迫度 %d/100）" % (ex["status"], ex["score"]))
        print("   " + "、".join(ex["signals"]))
        if ex["stop"]:
            print("   " + ex["stop"])
    print(" 進場：%s\n ※ 非投資建議。" % r["action"])
    _write_single_html(r)
    return r


def _card_html(r, esc):
    rows = "".join(
        '<div class="row"><div><b>%s</b> <span class="muted">%d%%</span><br>'
        '<span class="muted" style="font-size:12px">%s</span></div>'
        '<div class="%s" style="font-size:20px;font-weight:700">%.0f</div></div>'
        % (esc(l), w, esc(d), _band(s), s) for l, s, w, d in r["components"])
    verdict = ('<div style="padding:8px 0;color:#2478c8">★ %s</div>' % esc(r["chips_verdict"])) if r["chips_verdict"] else ""
    ex = r.get("exit")
    exit_html = ""
    if ex:
        exit_html = ('<div style="margin-top:8px;padding-top:8px;border-top:1px solid #222936">'
                     '<b>離場訊號：</b><span class="%s" style="font-weight:700">%s</span>'
                     ' <span class="muted">急迫度 %d/100</span>'
                     '<div class="muted" style="font-size:12px">%s</div>'
                     '<div class="muted" style="font-size:12px">%s</div></div>'
                     % (ex["light"], esc(ex["status"]), ex["score"],
                        esc("、".join(ex["signals"])), esc(ex["stop"])))
    tag = _tag_text(r.get("industry", ""), r.get("themes", []))
    tag_html = ('<div style="margin:2px 0 8px"><span style="background:#1e2a44;color:#2478c8;'
                'font-size:11.5px;padding:2px 8px;border-radius:6px">%s</span></div>' % esc(tag)) if tag else ""
    flag_html = ('<div style="margin:2px 0 8px"><span style="background:#3a2f12;color:#f6c764;'
                 'font-size:11.5px;padding:2px 8px;border-radius:6px;border:1px solid #5a4a1e">%s%s</span></div>'
                 % (esc(r.get("flag", "")),
                    (" ｜ " + esc(r["flagtxt"])) if r.get("flagtxt") else "")) if r.get("flag") else ""
    return ('<div class="card"><h2>%s <span class="muted">%s ・ 收 %.2f</span>'
            '<span class="score %s">%.1f</span></h2>'
            '<div class="muted" style="margin:-2px 0 4px">進場 %s ・ 定額 %.2gx</div>%s%s%s%s%s</div>'
            % (esc(r["name"]), esc(r["code"]), r["price"], r["light"], r["score"],
               esc(r["band"]), r["multiplier"], flag_html, tag_html, rows, verdict, exit_html))


_PAGE_CSS = """<style>
body{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:680px;margin:0 auto;padding:26px 20px 70px}
.wrap.wide{max-width:1320px}
h1{font-size:25px;margin:0 0 3px}.muted{color:#5f7183;font-size:13.5px}
.cardgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px;margin-bottom:8px}
@media(max-width:560px){.cardgrid{grid-template-columns:1fr}.wrap{padding:20px 14px 60px}}
.card{background:#ffffff;border:1px solid #dbe4ee;border-radius:16px;padding:18px 22px}
h2{font-size:18px;margin:0;display:flex;align-items:center;gap:8px}
h2 .score{margin-left:auto;font-size:32px;font-weight:800}
.row{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid #222936;font-size:14.5px}
.green{color:#28c76f}.amber{color:#f6a821}.red{color:#ea5455}a{color:#2478c8}
.searchwrap{position:sticky;top:0;z-index:6;background:rgba(245,248,251,.92);padding:12px 0 8px}
input{width:100%;box-sizing:border-box;padding:13px 15px;border-radius:12px;border:1px solid #dbe4ee;
  background:#ffffff;color:#17293a;font-size:16px;outline:none}
input:focus{border-color:#2478c8}
.sitem{border-bottom:1px solid #222936}
.srow{display:flex;align-items:center;gap:14px;padding:11px 2px;cursor:pointer}
.srow:hover{background:#141925}
.srow .nm{flex:1;min-width:0;font-size:15px}.srow .mini{color:#5f7183;font-size:12px}
.srow .sc{font-weight:700;font-size:20px;width:52px;text-align:right}
.srow .ar{color:#6b7686;width:14px;text-align:center}
.sdet{padding:2px 6px 14px;font-size:13.5px}
.sdet .dl{padding:4px 0;color:#3f5468}.sdet .muted{font-size:12.5px}
.sdet .ana{padding:6px 0;color:#e7ecf6;line-height:1.55}
.mk{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;vertical-align:1px;font-weight:600}
.mk.tse{background:rgba(91,156,255,.18);color:#2478c8}
.mk.otc{background:rgba(246,168,33,.18);color:#f6c764}
.green{color:#28c76f}.amber{color:#f6a821}.red{color:#ea5455}
.wladd{display:flex;gap:8px;margin:6px 0 10px}
.wladd input{flex:1;min-width:0;padding:10px 14px;border-radius:12px}
.wladd button{padding:10px 18px;border-radius:12px;border:1px solid #cfdae6;
 background:rgba(36,120,200,.14);color:#17293a;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap}
.wlbtns{display:flex;gap:13px;align-items:center;margin-left:10px}
.wlbtns span{cursor:pointer;color:#8893a6;font-size:14px;user-select:none}
.wlbtns .wlx{color:#ea5455}
.wlstar{cursor:pointer;color:#6b7686;font-size:18px;margin-left:8px;user-select:none}
.wlstar.on{color:#f6c744}
/* 玻璃「＋」浮動鈕：點一下捲到自選輸入框並聚焦（重用 #lglass 液態玻璃濾鏡） */
.fab{position:fixed;right:calc(16px + env(safe-area-inset-right,0px));
 bottom:calc(86px + env(safe-area-inset-bottom,0px));z-index:55;
 width:54px;height:54px;border-radius:50%;border:none;cursor:pointer;padding:0;
 display:flex;align-items:center;justify-content:center;color:#fff;
 background:linear-gradient(180deg, rgba(255,120,205,.34), rgba(255,70,180,.20));
 -webkit-backdrop-filter:url(#lglass) blur(7px) saturate(2);backdrop-filter:url(#lglass) blur(7px) saturate(2);
 box-shadow:0 10px 26px rgba(0,0,0,.5), inset 0 1px .5px rgba(255,255,255,.6), 0 0 0 1px rgba(255,255,255,.18);
 transition:transform .16s, box-shadow .16s;-webkit-tap-highlight-color:transparent}
.fab:active{transform:scale(.9)}
.fab svg{width:26px;height:26px;display:block;filter:drop-shadow(0 2px 8px rgba(224,152,40,.5))}
</style>"""


def _write_single_html(r):
    from dashboard import _esc
    html = ('<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>個股 %s</title>%s</head><body><div class="wrap">'
            '<h1>個股進場分數</h1><div class="muted">%s</div>%s'
            '<div class="muted">非投資建議。<a href="index.html">← 回大盤儀表板</a></div>'
            '</div></body></html>'
            % (_esc(r["name"]), _PAGE_CSS, _esc(r["generated_at"]), _card_html(r, _esc)))
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(cfg.OUTPUT_DIR, "stock-%s.html" % r["code"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(" 報告頁：%s" % path)


_FAB = """
<button class="fab" id="fab" aria-label="加入自選股" title="加入自選股">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
 stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
</button>
<script>
(function(){var f=document.getElementById('fab');if(!f)return;
f.addEventListener('click',function(){
  var i=document.getElementById('wlq');
  if(i){try{i.focus({preventScroll:true});}catch(e){i.focus();}
    i.scrollIntoView({behavior:'smooth',block:'center'});}
});})();
</script>"""

_SEARCH_JS = """
<script>
let U=[];
const DEFAULT_WL=__DEFWL__;
const box=document.getElementById('q'), res=document.getElementById('res'), wlBox=document.getElementById('wl');
const byCode={};
function band(s){return s>=58?'green':s<42?'red':'amber';}
function cell(v){return v==null?'-':v;}
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
function mkt(x){return x.m==='otc'?'<span class="mk otc">上櫃</span>':'<span class="mk tse">上市</span>';}
function detail(x){
  var d='<div class="sdet" style="display:none">';
  if(x.a)d+='<div class="ana"><b>分析：</b>'+esc(x.a)+'</div>';
  d+='<div class="dl">收盤 '+cell(x.p)+'　'+mkt(x)+(x.b?'　<b class="'+band(x.s)+'">'+esc(x.b)+'</b>':'')+(x.d?'　<span style="color:#2478c8">★ '+esc(x.d)+'</span>':'')+'</div>';
  if(x.t||x.i)d+='<div class="muted">'+(x.t?'題材：'+esc(x.t)+'　':'')+(x.i?'產業：'+esc(x.i):'')+'</div>';
  d+='<div class="muted">個股籌碼（'+cell(x.ch)+'）：'+esc(x.cd)+'</div>';
  d+='<div class="muted">個股估值（'+cell(x.v)+'）：'+esc(x.vd)+'</div>';
  if(x.td)d+='<div class="muted">輕量技術（'+cell(x.tk)+'）：'+esc(x.td)+'</div>';
  d+='<div class="muted">大盤環境（'+cell(x.e)+'）：同個大背景，人人一樣</div>';
  if(x.fg)d+='<div class="muted" style="color:#f6c764">'+esc(x.fg)+(x.ft?'：'+esc(x.ft):'')+'</div>';
  d+='<div class="muted" style="margin-top:5px;color:#7c8aa0">輕量分＝環境＋籌碼＋估值＋技術(今日K線/收盤位置/漲跌，均線隨每日累積)；完整趨勢與離場訊號請加進自選股，或本機跑 stock.py '+x.c+(x.m==='otc'?'（上櫃）':'')+'</div>';
  return d+'</div>';
}
function tog(el){var d=el.nextElementSibling;if(!d)return;var open=d.style.display!=='none';d.style.display=open?'none':'block';var a=el.querySelector('.ar');if(a)a.textContent=open?'▸':'▾';}
function rowHTML(x,extra){
  var tag=x.t?' <span style="color:#2478c8">['+esc(x.t)+']</span>':(x.i?' <span class="muted">'+esc(x.i)+'</span>':'');
  var fg=x.fg?' <span style="font-size:11px;color:#f6c764;border:1px solid #5a4a1e;border-radius:5px;padding:0 4px">'+esc(x.fg)+'</span>':'';
  return '<div class="sitem"><div class="srow"><div class="ar">▸</div>'+
    '<div class="nm"><b>'+x.c+'</b> '+mkt(x)+' '+esc(x.n)+tag+fg+
    '<div class="mini">環境 '+cell(x.e)+'　籌碼 '+cell(x.ch)+'　估值 '+cell(x.v)+(x.tk!=null?'　技術 '+cell(x.tk):'')+'</div></div>'+
    (extra||'')+'<div class="sc '+band(x.s)+'">'+x.s.toFixed(1)+'</div></div>'+detail(x)+'</div>';
}
/* ===== 自選清單：存在瀏覽器 localStorage，可自行加入/移除/排序 ===== */
function loadWL(){try{var s=localStorage.getItem('myWL');if(s)return JSON.parse(s);}catch(e){}return DEFAULT_WL.slice();}
var WL=loadWL();
function saveWL(){try{localStorage.setItem('myWL',JSON.stringify(WL));}catch(e){}}
function inWL(c){return WL.indexOf(c)>=0;}
function addWL(c){c=(''+c).trim();if(!c)return;if(inWL(c)){renderWL();return;}if(!byCode[c]){alert('找不到代碼 '+c+'（限台股上市/上櫃）');return;}WL.push(c);saveWL();renderWL();refreshStars();}
function rmWL(c){var i=WL.indexOf(c);if(i>=0){WL.splice(i,1);saveWL();renderWL();refreshStars();}}
function moveWL(c,dir){var i=WL.indexOf(c),j=i+dir;if(i<0||j<0||j>=WL.length)return;var t=WL[i];WL[i]=WL[j];WL[j]=t;saveWL();renderWL();}
function refreshStars(){var ss=res.querySelectorAll('.wlstar');for(var k=0;k<ss.length;k++){var c=ss[k].getAttribute('data-c'),on=inWL(c);ss[k].textContent=on?'★':'☆';ss[k].className='wlstar'+(on?' on':'');}}
function wlRow(c){
  var x=byCode[c];
  var btns='<div class="wlbtns"><span class="wlup" data-c="'+c+'">▲</span><span class="wldn" data-c="'+c+'">▼</span><span class="wlx" data-c="'+c+'">✕</span></div>';
  if(!x)return '<div class="sitem"><div class="srow"><div class="ar"></div><div class="nm"><b>'+esc(c)+'</b> <span class="muted">（查無資料）</span></div>'+btns+'</div></div>';
  return rowHTML(x,btns);
}
function renderWL(){
  if(!WL.length){wlBox.innerHTML='<div class="muted" style="padding:8px 0">自選是空的：在下方搜尋結果按 ☆，或在上面輸入代碼加入。</div>';return;}
  wlBox.innerHTML=WL.map(wlRow).join('');
}
if(wlBox)wlBox.addEventListener('click',function(e){
  var t=e.target,c=t.getAttribute('data-c');
  if(t.classList.contains('wlx')){e.stopPropagation();rmWL(c);return;}
  if(t.classList.contains('wlup')){e.stopPropagation();moveWL(c,-1);return;}
  if(t.classList.contains('wldn')){e.stopPropagation();moveWL(c,1);return;}
  var row=t.closest('.srow');if(row)tog(row);
});
var wlq=document.getElementById('wlq'),wlbtn=document.getElementById('wlbtn');
if(wlbtn)wlbtn.addEventListener('click',function(){addWL(wlq.value);wlq.value='';});
if(wlq)wlq.addEventListener('keydown',function(e){if(e.key==='Enter'){addWL(wlq.value);wlq.value='';}});
if(wlBox)wlBox.innerHTML='<div class="muted" style="padding:8px 0">載入中…</div>';
/* ===== 搜尋 ===== */
function render(list){
  if(!list.length){res.innerHTML='<div class="muted" style="padding:10px 0">查無符合的個股</div>';return;}
  res.innerHTML=list.slice(0,40).map(function(x){
    var star='<span class="wlstar'+(inWL(x.c)?' on':'')+'" data-c="'+x.c+'" title="加入/移出自選">'+(inWL(x.c)?'★':'☆')+'</span>';
    return rowHTML(x,star);
  }).join('')+(list.length>40?'<div class="muted" style="padding:8px 0">…共 '+list.length+' 檔，顯示前 40（縮小範圍看更多）</div>':'');
}
res.addEventListener('click',function(e){
  var t=e.target;
  if(t.classList.contains('wlstar')){e.stopPropagation();var c=t.getAttribute('data-c');if(inWL(c))rmWL(c);else addWL(c);return;}
  var row=t.closest('.srow');if(row)tog(row);
});
box.addEventListener('input',function(){
  const q=box.value.trim();
  if(!q){res.innerHTML='<div class="muted" style="padding:10px 0">輸入代碼或名稱開始搜尋（共 '+U.length+' 檔）…點一下可展開明細</div>';return;}
  const m=U.filter(function(x){return x.c.indexOf(q)===0 || x.n.indexOf(q)>=0;});
  m.sort(function(a,b){return b.s-a.s;});
  render(m);
});
/* ===== 全市場清單外部化：只抓一次 universe.json（SW 快取），個股頁 HTML 大幅瘦身 ===== */
fetch('universe.json').then(function(r){if(!r.ok)throw 0;return r.json();}).then(function(data){
  U=data; for(var i=0;i<U.length;i++)byCode[U[i].c]=U[i];
  if(wlBox)renderWL();
  if(box&&!box.value&&res)res.innerHTML='<div class="muted" style="padding:6px 0 10px">輸入代碼或名稱即時查全市場（共 '+U.length+' 檔・輕量分：環境＋籌碼＋估值＋技術，📢標示近期法說/重訊）</div>';
}).catch(function(){
  if(res)res.innerHTML='<div class="muted" style="padding:10px 0">個股清單載入失敗，請下拉重新整理。</div>';
  if(wlBox)wlBox.innerHTML='<div class="muted" style="padding:8px 0">清單載入失敗，請重新整理。</div>';
});
</script>"""


def _embed_rec_backtest(s, esc):
    """把 rec_tracker 的 summary 渲染成內嵌區塊（不用另外點連結）。"""
    def pct(v):
        return "—" if v is None else ("%+.1f%%" % (v*100))
    def color(v):
        # 台股慣例：上漲(正)=紅、下跌(負)=綠
        return "" if v is None else ("color:#ea5455" if v >= 0 else "color:#28c76f")

    parts = ['<h2 style="font-size:16px;margin:18px 0 8px">📊 推薦回測 '
             '<span class="muted" style="font-weight:400">歷史模擬 + 即時追蹤・非投資建議</span></h2>']

    # 綜合績效（一張大卡，跑贏/跑輸一眼看到）
    n = s.get("n_sim", 0)
    if n:
        avg3 = s.get("avg3"); avg6 = s.get("avg6")
        br3 = s.get("bench3"); br6 = s.get("bench6")
        wr3 = s.get("win_rate3"); wr6 = s.get("win_rate6")
        a3 = (avg3 - br3) if (avg3 is not None and br3 is not None) else None
        a6 = (avg6 - br6) if (avg6 is not None and br6 is not None) else None
        alphas = [x for x in (a3, a6) if x is not None]
        if alphas:
            avg_alpha = sum(alphas) / len(alphas)
            if avg_alpha > 0.01:
                verdict, vc = "整體跑贏大盤 👍", "#ea5455"   # 跑贏(正)=紅
            elif avg_alpha < -0.01:
                verdict, vc = "整體跑輸大盤 👎", "#28c76f"   # 跑輸(負)=綠
            else:
                verdict, vc = "整體與大盤相當", "#f6a821"
        else:
            avg_alpha = None; verdict, vc = "資料不足", "#5f7183"

        def wpct(w):
            return "—" if w is None else ("%.0f%%" % (w * 100))

        parts.append('<div class="card" style="border:1.5px solid %s;margin-bottom:12px">' % vc)
        parts.append('<div style="font-size:13px;color:#5f7183">綜合績效（歷史模擬・Proxy）</div>')
        parts.append('<div style="font-size:26px;font-weight:800;margin:4px 0;color:%s">%s</div>' % (vc, verdict))
        if avg_alpha is not None:
            parts.append('<div style="font-size:15px;font-weight:600;%s">平均超額報酬 %s（推薦股 vs 0050）</div>'
                         % (color(avg_alpha), pct(avg_alpha)))
        parts.append('<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:10px">'
                     '<thead><tr style="color:#5f7183">'
                     '<th style="text-align:left;padding:5px 4px">持有期</th>'
                     '<th style="text-align:right">推薦股平均</th>'
                     '<th style="text-align:right">0050 同期</th>'
                     '<th style="text-align:right">超額</th>'
                     '<th style="text-align:right">勝率</th></tr></thead><tbody>')
        for label, av, br, al, wr in [("3 個月", avg3, br3, a3, wr3), ("6 個月", avg6, br6, a6, wr6)]:
            parts.append('<tr style="border-top:1px solid #222936">'
                         '<td style="padding:5px 4px">%s</td>'
                         '<td style="text-align:right;%s">%s</td>'
                         '<td style="text-align:right;color:#5f7183">%s</td>'
                         '<td style="text-align:right;font-weight:700;%s">%s</td>'
                         '<td style="text-align:right">%s</td></tr>'
                         % (label, color(av), pct(av), pct(br), color(al), pct(al), wpct(wr)))
        parts.append('</tbody></table>')
        parts.append('<div style="font-size:11.5px;color:#7c8aa0;margin-top:8px">⚠️ Proxy 模擬：假設「過去也會推薦同一批股」'
                     '才成立（存倖偏差使結果偏樂觀）；真實準確率以下方「即時追蹤」累積為準。'
                     '台股慣例紅=漲、綠=跌。非投資建議。</div>')
        parts.append('</div>')

    # 個股明細表
    results = s.get("results", [])
    if results:
        # 按 3 個月模擬報酬排序，None 排最後
        results_sorted = sorted(results, key=lambda r: (r.get("ret3m") is None, -(r.get("ret3m") or -99)))
        parts.append('<div class="card" style="margin-bottom:14px"><h2 style="font-size:15px;margin-bottom:8px">'
                     '推薦個股模擬明細（今日推薦的 %d 檔）</h2>' % n)
        parts.append('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">'
                     '<thead><tr style="color:#5f7183;border-bottom:1px solid #dbe4ee">'
                     '<th style="text-align:left;padding:6px 4px">代碼</th>'
                     '<th style="text-align:left">名稱</th>'
                     '<th style="text-align:right">今日分數</th>'
                     '<th style="text-align:right">3M 模擬</th>'
                     '<th style="text-align:right">6M 模擬</th>'
                     '<th style="text-align:left;padding-left:8px">題材</th></tr></thead><tbody>')
        for r in results_sorted:
            v3 = r.get("ret3m"); v6 = r.get("ret6m")
            parts.append('<tr style="border-bottom:1px solid rgba(255,255,255,.05)">'
                         '<td style="padding:6px 4px;font-weight:700">%s</td>'
                         '<td>%s</td>'
                         '<td style="text-align:right">%.1f</td>'
                         '<td style="text-align:right;%s">%s</td>'
                         '<td style="text-align:right;%s">%s</td>'
                         '<td style="color:#5f7183;padding-left:8px">%s</td></tr>'
                         % (esc(r["code"]), esc(r["name"]), r["score"],
                            color(v3), pct(v3), color(v6), pct(v6), esc(r.get("themes",""))))
        parts.append('</tbody></table></div></div>')

    # 即時追蹤
    tracked = s.get("tracked", [])
    n_hist = s.get("n_total_history", 0)
    if tracked:
        parts.append('<div class="card"><h2 style="font-size:15px;margin-bottom:8px">'
                     '即時追蹤（已滿 20 交易日的真實報酬・%d 筆）</h2>' % len(tracked))
        parts.append('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">'
                     '<thead><tr style="color:#5f7183;border-bottom:1px solid #dbe4ee">'
                     '<th style="text-align:left;padding:6px 4px">推薦日</th>'
                     '<th style="text-align:left">代碼</th>'
                     '<th style="text-align:left">名稱</th>'
                     '<th style="text-align:right">分數</th>'
                     '<th style="text-align:right">20日報酬</th>'
                     '<th style="text-align:right">0050同期</th>'
                     '<th style="text-align:right">Alpha</th></tr></thead><tbody>')
        for t in tracked:
            r20 = t.get("ret20") or 0; b20 = t.get("bench20") or 0; alpha = t.get("alpha20") or 0
            parts.append('<tr style="border-bottom:1px solid rgba(255,255,255,.05)">'
                         '<td style="padding:6px 4px;color:#5f7183">%s</td>'
                         '<td style="font-weight:700">%s</td>'
                         '<td>%s</td>'
                         '<td style="text-align:right">%s</td>'
                         '<td style="text-align:right;%s">%+.1f%%</td>'
                         '<td style="text-align:right;color:#5f7183">%+.1f%%</td>'
                         '<td style="text-align:right;%s">%+.1f%%</td></tr>'
                         % (esc(t.get("date","")), esc(t.get("code","")), esc(t.get("name","")),
                            esc(str(t.get("score",""))), color(r20), r20*100,
                            b20*100, color(alpha), alpha*100))
        parts.append('</tbody></table></div></div>')
    elif n_hist > 0:
        parts.append('<div class="card" style="font-size:13px;color:#5f7183">'
                     '⏳ 已累積 %d 筆推薦紀錄；約 4 週後滿 20 個交易日的會在此顯示實際報酬。</div>' % n_hist)
    else:
        parts.append('<div class="card" style="font-size:13px;color:#5f7183">'
                     '⏳ 即時追蹤剛啟動；累積 ~4 週後此區會顯示真實報酬。</div>')

    return "".join(parts)


def render_stocks_page(recommendations, watchlist, universe):
    """產生 output/stocks.html：置頂最推薦潛力股 + 自選股完整卡片 + 全市場搜尋（輕量分）。"""
    from dashboard import _esc, nav, with_pwa
    recommendations = recommendations or []
    watchlist = sorted(watchlist or [], key=lambda r: r["score"], reverse=True)
    gen = (recommendations or watchlist or [{"generated_at": ""}])[0].get("generated_at", "")

    def _hdr(t, sub):
        return ('<h2 style="font-size:16px;margin:18px 0 8px">%s '
                '<span class="muted" style="font-weight:400">%s</span></h2>' % (t, sub))

    def _grid(items):
        return '<div class="cardgrid">' + "".join(_card_html(r, _esc) for r in items) + '</div>'

    uni = [{"c": x["code"], "n": x["name"], "s": x["score"],
            "e": x["env"], "ch": x["chips"], "v": x["val"], "tk": x.get("tech"),
            "td": x.get("tech_disp", ""), "fg": x.get("flag", ""), "ft": x.get("flagtxt", ""),
            "i": x.get("industry", ""), "t": "/".join(x.get("themes", [])),
            "p": x.get("price"), "cd": x.get("chips_disp", ""),
            "vd": x.get("val_disp", ""), "d": x.get("diverg", ""),
            "m": x.get("market", "tse"), "b": x.get("action", ""), "a": x.get("analysis", "")}
           for x in (universe or [])]
    ujson = json.dumps(uni, ensure_ascii=False)
    default_wl = json.dumps([str(c) for c in (getattr(cfg, "STOCK_WATCHLIST", []) or [])])

    sections = ""
    if uni:  # 搜尋欄置頂、且黏在頂端
        sections += ('<div class="searchwrap"><input id="q" placeholder="🔎 搜尋個股代碼或名稱（共 %d 檔，點結果展開明細）" '
                     'autocomplete="off"></div>'
                     '<div id="res"><div class="muted" style="padding:6px 0 10px">'
                     '輸入代碼或名稱即時查全市場（輕量分：環境＋籌碼＋估值＋技術，📢標示近期法說/重訊）</div></div>' % len(uni))
    if recommendations:
        sections += _hdr("🔥 最推薦潛力股", "分數高＋法人真金白銀在買的（非投資建議，賠錢不要找我）")
        sections += _grid(recommendations)

    # 📊 推薦回測（直接內嵌，不用點進去）
    try:
        import rec_tracker
        summary = rec_tracker.load_summary()
    except Exception:
        summary = None
    if summary:
        sections += _embed_rec_backtest(summary, _esc)

    # ⭐ 自選股：改為使用者可自編（存在瀏覽器 localStorage），預設帶入 config.STOCK_WATCHLIST
    sections += _hdr("⭐ 我的自選", "你自己的觀察名單，存在瀏覽器裡（換手機不同步，這是特性不是 bug）")
    sections += ('<div class="wladd"><input id="wlq" placeholder="輸入代碼加入（例 2330）" autocomplete="off">'
                 '<button id="wlbtn">加入</button></div><div id="wl"></div>')

    body = ('<h1>個股進場分數 <span class="muted">推薦 + 自選 + 搜尋</span></h1>'
            '<div class="muted">分數越高＝越值得分批進場（同一套邏輯）・%s</div>%s'
            '<div class="muted" style="margin-top:14px">推薦＝每天從全市場自動挑「進場分數最高＋法人買超」'
            '的中大型股，依本工具邏輯排序，<b>非投資建議</b>。輕量分(搜尋用)＝環境＋籌碼＋估值＋技術(今日K線/收盤位置/漲跌，均線隨每日累積)，📢標示近期法說會/重訊。</div>'
            % (_esc(gen), sections))

    html = ('<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta http-equiv="refresh" content="%d">'
            '<title>個股進場分數</title>%s</head><body>%s<div class="wrap wide">%s</div>%s%s</body></html>'
            % (getattr(cfg, "STOCKS_REFRESH_SECONDS", 3600), _PAGE_CSS, nav("stocks", include_css=True), body,
               _SEARCH_JS.replace("__DEFWL__", default_wl) if uni else "",
               _FAB))
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    # 全市場清單外部化成 universe.json（瀏覽器/SW 快取、只抓一次）→ 個股頁 HTML 從 ~600KB 瘦回 ~40KB
    if uni:
        with open(os.path.join(cfg.OUTPUT_DIR, "universe.json"), "w", encoding="utf-8") as f:
            f.write(ujson)
    path = os.path.join(cfg.OUTPUT_DIR, "stocks.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(with_pwa(html))
    return path


if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("用法：py -X utf8 stock.py <代碼>   例如：py -X utf8 stock.py 2330")
    else:
        analyze(sys.argv[1])

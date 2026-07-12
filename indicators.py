# -*- coding: utf-8 -*-
"""把原始資料轉成一張張「指標卡」。

每張卡都有統一結構，最關鍵的是 `score`：0-100 的**進場機會分數**，
越高代表「現在越適合加碼 / 進場」，越低代表「偏貴 / 過熱 / 該保守」。
所有逆向指標（恐慌、回檔、散戶槓桿）都已轉成同一個方向，越恐慌分數越高。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import analytics as A
import config as cfg


def band(score: float) -> str:
    if score >= cfg.LIGHT_GREEN_MIN:
        return "green"      # 偏向加碼
    if score < cfg.LIGHT_RED_MAX:
        return "red"        # 偏貴/過熱/保守
    return "amber"          # 中性


def _ind(key, name, category, value_display, score, note,
         series=None, weight=1.0, detail=None) -> Dict:
    score = round(float(A.clamp(score, 0, 100)), 1)
    return {
        "key": key, "name": name, "category": category,
        "value_display": value_display, "score": score,
        "light": band(score), "note": note,
        "series": [round(float(x), 4) for x in series] if series else None,
        "weight": weight, "detail": detail,
    }


def _yh_close(yh, key) -> List:
    h = yh.get(key)
    return h["close"] if h else []


def _last(yh, key):
    return A.last(_yh_close(yh, key))


# =====================================================================
# 恐慌與情緒
# =====================================================================
def _vix(yh) -> Optional[Dict]:
    s = A.clean(_yh_close(yh, "vix"))
    if not s:
        return None
    v = s[-1]
    score = A.piecewise(v, [(11, 22), (14, 42), (17, 55), (20, 64),
                            (25, 76), (30, 86), (40, 96), (60, 99)])
    if v < 14:
        note = "市場極度平靜，波動偏低（情緒偏貪婪，逆向偏空）。"
    elif v < 20:
        note = "波動正常，情緒中性。"
    elif v < 30:
        note = "恐慌升溫，開始出現分批加碼價值。"
    else:
        note = "極度恐慌，歷史上常是中長線相對低點。"
    return _ind("vix", "VIX 恐慌指數", "fear", "%.1f" % v, score, note,
                series=s[-120:], weight=1.0)


def _vix_term(yh) -> Optional[Dict]:
    v = A.clean(_yh_close(yh, "vix"))
    v3 = A.clean(_yh_close(yh, "vix3m"))
    if not v or not v3:
        return None
    ratio = v[-1] / v3[-1] if v3[-1] else None
    if ratio is None:
        return None
    score = A.piecewise(ratio, [(0.80, 30), (0.90, 42), (0.95, 52),
                                (1.00, 64), (1.05, 80), (1.15, 92)])
    note = ("期限結構倒掛（近月>遠月）＝急性恐慌、常見於急跌末段。"
            if ratio >= 1 else "正常正價差（contango），市場無立即恐慌。")
    # 取兩條對齊的最後 120 天做比值序列
    n = min(len(v), len(v3), 120)
    series = [v[-n + i] / v3[-n + i] for i in range(n) if v3[-n + i]]
    return _ind("vix_term", "VIX 期限結構（VIX/VIX3M）", "fear",
                "%.3f" % ratio, score, note, series=series, weight=0.8)


def _fear_greed(yh) -> Optional[Dict]:
    """自建『恐懼貪婪指數』取代被封鎖的 CNN，輸出 0-100 貪婪分數。"""
    spx = A.clean(_yh_close(yh, "spx"))
    if not spx:
        return None
    comps = {}
    # 1) 動能：S&P 相對 125 日均線
    ma125 = A.sma(spx, 125)
    if ma125:
        comps["動能"] = A.clamp(50 + ((spx[-1] / ma125 - 1) / 0.10) * 40, 0, 100)
    # 2) 避險需求：股票 vs 長債 20 日報酬差
    r_spx = A.pct_change(spx, 20)
    r_tlt = A.pct_change(_yh_close(yh, "tlt"), 20)
    if r_spx is not None and r_tlt is not None:
        comps["避險需求"] = A.clamp(50 + ((r_spx - r_tlt) / 0.06) * 40, 0, 100)
    # 3) 垃圾債需求：HYG vs IEF 20 日報酬差
    r_hyg = A.pct_change(_yh_close(yh, "hyg"), 20)
    r_ief = A.pct_change(_yh_close(yh, "ief"), 20)
    if r_hyg is not None and r_ief is not None:
        comps["垃圾債需求"] = A.clamp(50 + ((r_hyg - r_ief) / 0.03) * 40, 0, 100)
    # 4) 波動：VIX 兩年百分位（越低越貪婪）
    vix = A.clean(_yh_close(yh, "vix"))
    if vix:
        pct = A.percentile_rank(vix[-1], vix, window=504)
        if pct is not None:
            comps["波動"] = 100 - pct
    if not comps:
        return None
    greed = sum(comps.values()) / len(comps)
    score = 100 - greed   # 進場機會 = 100 - 貪婪
    if greed < 25:
        label = "極度恐懼"
    elif greed < 45:
        label = "恐懼"
    elif greed < 55:
        label = "中性"
    elif greed < 75:
        label = "貪婪"
    else:
        label = "極度貪婪"
    detail = "　".join("%s %d" % (k, round(x)) for k, x in comps.items())
    note = "自建恐懼貪婪指數＝%d（%s）。逆向操作：越恐懼越值得加碼。" % (round(greed), label)
    return _ind("fear_greed", "恐懼貪婪指數（自建）", "fear",
                "%d / 100（%s）" % (round(greed), label), score, note,
                series=None, weight=1.2, detail=detail)


# =====================================================================
# 估值
# =====================================================================
def _tw_valuation(val) -> Optional[Dict]:
    if not val:
        return None
    dy = val.get("median_yield")
    pb = val.get("median_pb")
    if dy is None or pb is None:
        return None
    ys = A.piecewise(dy, [(2.0, 25), (2.5, 38), (3.0, 50), (3.5, 62), (4.0, 74), (5.0, 88)])
    ps = A.piecewise(pb, [(1.2, 88), (1.5, 70), (1.8, 54), (2.1, 40), (2.5, 26), (3.0, 18)])
    score = (ys + ps) / 2
    note = ("以全體上市股票中位數估算：殖利率越高、股價淨值比越低＝越便宜。"
            "目前估值%s。" % ("偏低（便宜）" if score >= 58 else "偏高（貴）" if score < 42 else "中性"))
    if val.get("_cached"):
        note += "（採前次快取）"
    return _ind("tw_val", "台股估值（殖利率/淨值比）", "valuation",
                "殖利率 %.1f%%　PB %.2f" % (dy, pb), score, note, weight=1.0)


def _drawdown(yh, key, name) -> Optional[Dict]:
    s = A.clean(_yh_close(yh, key))
    if len(s) < 30:
        return None
    dd = A.drawdown_from_high(s, 252)
    if dd is None:
        return None
    score = A.piecewise(dd, [(-0.40, 97), (-0.25, 90), (-0.15, 80),
                             (-0.08, 66), (-0.03, 52), (0.0, 40)])
    note = ("距 52 週高點回檔 %.1f%%。" % (dd * 100)) + (
        "貼著歷史高點，這裡進場叫接棒不叫進場。" if dd > -0.03 else
        "回檔有感，想分批的人開始有位置可以站了。" if dd > -0.15 else
        "跌很深。恐慌的人在賣、有紀律的人在列清單。")
    return _ind("dd_" + key, name, "valuation",
                "%.1f%%" % (dd * 100), score, note, series=s[-120:], weight=0.8)


# =====================================================================
# 通膨 / 利率 / 總經
# =====================================================================
def _cpi(cpi) -> Optional[Dict]:
    if not cpi or cpi.get("headline_yoy") is None:
        return None
    yoy = cpi["headline_yoy"]
    core = cpi.get("core_yoy")
    score = A.piecewise(yoy, [(1.5, 80), (2.0, 72), (2.5, 62), (3.0, 52),
                              (3.5, 44), (4.5, 32), (6.0, 20)])
    series_vals = [v for _, v in cpi.get("headline_series", [])]
    # 趨勢調整：通膨下降中加分、上升中扣分
    if len(series_vals) >= 4:
        if series_vals[-1] < series_vals[-4]:
            score += 5
        elif series_vals[-1] > series_vals[-4]:
            score -= 5
    note = ("美國 CPI 年增 %.1f%%（核心 %.1f%%）。通膨回落利於降息與股市；通膨高則壓抑評價。"
            % (yoy, core if core is not None else float("nan")))
    if cpi.get("_cached"):
        note += "（本次來源忙線，採前次快取）"
    disp = "%.1f%%" % yoy + ("（核心 %.1f%%）" % core if core is not None else "")
    return _ind("cpi", "美國通膨 CPI", "macro", disp, score, note,
                series=series_vals[-24:], weight=1.0)


def _yield_curve(ust) -> Optional[Dict]:
    if not ust or ust.get("spread") is None:
        return None
    sp = ust["spread"]
    score = A.piecewise(sp, [(-1.0, 35), (-0.5, 42), (0.0, 50),
                             (0.5, 58), (1.0, 62), (2.0, 58)])
    note = ("美債 10Y-2Y 利差 %+.2f%%。" % sp) + (
        "曲線倒掛，債市在講衰退故事——不用照單全收，但銀彈留厚一點。" if sp < 0 else
        "曲線正常，債市沒在演，這項可以先放著。")
    if ust.get("_cached"):
        note += "（採前次快取）"
    series = [v for _, v in ust.get("spread_series", [])]
    return _ind("ust", "殖利率曲線 10Y-2Y", "macro", "%+.2f%%" % sp, score, note,
                series=series[-120:], weight=0.8)


def _dxy(yh) -> Optional[Dict]:
    s = A.clean(_yh_close(yh, "dxy"))
    if len(s) < 70:
        return None
    chg = A.pct_change(s, 60)
    if chg is None:
        return None
    score = A.clamp(50 - (chg / 0.05) * 30, 20, 80)
    note = ("美元指數 %.1f（近60日 %+.1f%%）。美元走強對台股與新興市場資金面不利，走弱則有利。"
            % (s[-1], chg * 100))
    return _ind("dxy", "美元指數 DXY", "macro",
                "%.1f（60日 %+.1f%%）" % (s[-1], chg * 100), score, note,
                series=s[-120:], weight=0.7)


def _copper_gold(yh) -> Optional[Dict]:
    cu = A.clean(_yh_close(yh, "copper"))
    au = A.clean(_yh_close(yh, "gold"))
    if not cu or not au:
        return None
    n = min(len(cu), len(au))
    ratio_series = [cu[-n + i] / au[-n + i] for i in range(n) if au[-n + i]]
    if len(ratio_series) < 70:
        return None
    ratio = ratio_series[-1]
    chg = A.pct_change(ratio_series, 60)
    score = A.clamp(50 + ((chg or 0) / 0.10) * 25, 30, 70)
    note = ("銅金比 %.4f（近60日 %+.1f%%）。銅金比走升＝市場預期景氣擴張、風險偏好回升。"
            % (ratio, (chg or 0) * 100))
    return _ind("copper_gold", "銅金比（景氣領先）", "macro",
                "%.4f（60日 %+.1f%%）" % (ratio, (chg or 0) * 100), score, note,
                series=ratio_series[-120:], weight=0.5)


def _business_signal(ndc) -> Optional[Dict]:
    if not ndc or ndc.get("score") is None:
        return None
    sc = float(ndc["score"])
    light = ndc.get("light") or ""
    # 分數越高＝景氣越熱＝越不適合追高；藍燈低分＝景氣低迷＝長線買點
    score = A.piecewise(sc, [(9, 90), (16, 80), (22, 62), (31, 48), (37, 32), (45, 20)])
    if "藍" in light:
        desc = "景氣低迷（藍燈），歷史上是中長線相對甜蜜的進場區。"
    elif "綠" in light:
        desc = "景氣穩定（綠燈），中性。"
    elif "紅" in light:
        desc = "景氣熱絡偏過熱（紅燈），追高風險升高、宜保守。"
    else:
        desc = "景氣轉向中（黃燈），留意動能變化。"
    ym = ndc["date"]
    ym_disp = "%s-%s" % (ym[:4], ym[4:]) if len(ym) == 6 else ym
    note = "國發會景氣對策信號 %s 分（%s燈，%s）。%s" % (round(sc), light, ym_disp, desc)
    if ndc.get("_cached"):
        note += "（採前次快取）"
    series = [v for _, v in ndc.get("score_series", [])]
    return _ind("ndc", "景氣對策信號（國發會）", "macro",
                "%s燈・%d 分" % (light, round(sc)), score, note,
                series=series, weight=0.8)


# =====================================================================
# 趨勢 / 動能
# =====================================================================
# =====================================================================
# A・長期趨勢品質（不採 mean-reversion，純看趨勢結構）
# =====================================================================
def _trend_quality(yh, key, name, weight=1.5) -> Optional[Dict]:
    """多均線排列 + 年線斜率 + 站上/跌破年線 + 黃金/死亡交叉。
    分數高＝長期趨勢健康(順勢加碼較安全)、低＝趨勢轉弱(別接刀)。"""
    s = A.clean(_yh_close(yh, key))
    if len(s) < 130:
        return None
    subs, parts = [], []
    align = A.ma_alignment(s)
    if align is not None:
        subs.append(A.linmap(align, -1, 1, 22, 85))
        parts.append("均線" + ("多頭排列" if align > 0.3 else "空頭排列" if align < -0.3 else "糾結"))
    slope = A.ma_slope(s, 200, 20)
    if slope is not None:
        subs.append(A.piecewise(slope * 1000, [(-1, 25), (-0.3, 43), (0, 52), (0.3, 66), (1, 82)]))
        parts.append("年線" + ("上彎" if slope > 5e-5 else "下彎" if slope < -5e-5 else "走平"))
    d200 = A.dist_from_ma(s, 200)
    if d200 is not None:
        subs.append(A.piecewise(d200, [(-0.15, 36), (-0.05, 47), (0, 55), (0.10, 66), (0.25, 60)]))
        parts.append(("站上" if d200 >= 0 else "跌破") + "年線")
    kind, _gago = A.cross(s, 50, 200, lookback=60)
    bonus = 0.0
    if kind == "golden":
        bonus = 8.0
        parts.append("近期黃金交叉")
    elif kind == "death":
        bonus = -10.0
        parts.append("近期死亡交叉")
    if not subs:
        return None
    score = A.clamp(sum(subs) / len(subs) + bonus, 5, 95)
    note = ("長期趨勢品質：%s。趨勢在，你才有資格談加碼；趨勢壞了還凹，就是在幫市場付學費。"
            "此面向不採逆勢，純看趨勢結構。" % "、".join(parts))
    return _ind("tq_" + key, name, "trend", "、".join(parts[:3]) or "—", score, note,
                series=s[-120:], weight=weight)


# =====================================================================
# C・技術面擴充：MACD / 布林 / ATR
# =====================================================================
def _macd_ind(yh, key, name) -> Optional[Dict]:
    s = A.clean(_yh_close(yh, key))
    if len(s) < 40:
        return None
    ml, sig, hist = A.macd(s)
    if hist is None:
        return None
    histn = (hist / s[-1] * 100) if s[-1] else 0.0       # 正規化為價格 %（跨標的可比）
    score = A.piecewise(histn, [(-1.0, 30), (-0.1, 45), (0, 52), (0.1, 60), (1.0, 72)])
    above = (ml is not None and ml >= 0)
    note = ("MACD(12,26,9)：柱狀體%s，MACD 線%s零軸。動能順勢指標。"
            % ("為正(動能轉強)" if hist > 0 else "為負(動能轉弱)", "在" if above else "低於"))
    return _ind("macd_" + key, name, "trend", "柱%s" % ("翻紅" if hist > 0 else "翻黑"),
                score, note, weight=0.6)


def _bollinger(yh, key, name) -> Optional[Dict]:
    s = A.clean(_yh_close(yh, key))
    pb = A.bollinger_pctb(s, 20, 2.0)
    if pb is None:
        return None
    # 逆勢解讀：跌破下軌(%b<0)=超賣=進場機會高；突破上軌(%b>1)=超買=追高風險
    score = A.piecewise(pb, [(-0.2, 86), (0.0, 78), (0.2, 64), (0.5, 52), (0.8, 40), (1.0, 28), (1.2, 20)])
    if pb < 0.1:
        desc = "貼近/跌破下軌＝短線超賣，逆勢分批價值浮現。"
    elif pb > 0.9:
        desc = "貼近/突破上軌＝短線超買，追高風險升高。"
    else:
        desc = "位於通道中段，中性。"
    note = "布林通道 %%b＝%.2f（0=下軌、0.5=中軌、1=上軌）。%s" % (pb, desc)
    return _ind("boll_" + key, name, "trend", "%%b %.2f" % pb, score, note, weight=0.5)


def _volatility(yh, key, name) -> Optional[Dict]:
    h = yh.get(key)
    if not h:
        return None
    if not (h.get("high") and h.get("low") and h.get("close")):
        return None                      # 缺高低價（如舊版回測截斷資料）→ 跳過
    a = A.atr(h.get("high"), h.get("low"), h.get("close"), 14)
    cl = A.last(h.get("close"))
    if a is None or not cl:
        return None
    atr_pct = a / cl * 100
    score = A.piecewise(atr_pct, [(0.5, 46), (1.0, 50), (1.8, 60), (2.6, 70), (4.0, 80)])
    note = ("ATR(14) 波動度約 %.2f%%。市場開始亂甩的時候部位要小；風平浪靜不是壞事，是讓你睡覺的。"
            % atr_pct)
    return _ind("atr_" + key, name, "trend", "ATR %.2f%%" % atr_pct, score, note, weight=0.4)


# =====================================================================
# B・K 線型態（需要 OHLC）
# =====================================================================
def _candle(yh, key, name) -> Optional[Dict]:
    h = yh.get(key)
    if not h:
        return None
    if not (h.get("open") and h.get("high") and h.get("low") and h.get("close")):
        return None                      # 缺 OHLC → 跳過
    ck = A.candle_read(h.get("open"), h.get("high"), h.get("low"), h.get("close"), h.get("volume"))
    if not ck:
        return None
    score = 50.0
    tags = []
    vr = ck.get("vol_ratio", 1.0)
    if ck["long_lower"]:
        score += 10; tags.append("長下影止跌")
    if ck["gap"] <= -0.02:
        score += 8; tags.append("向下跳空(恐慌)")
    if ck["new_low20"]:
        score += 6; tags.append("創20日新低(超賣)")
    if ck["long_upper"]:
        score -= 8; tags.append("長上影壓力")
    if vr >= 1.8 and not ck["bull"]:
        score -= 10; tags.append("爆量長黑(出貨疑慮)")
    if ck["gap"] >= 0.02:
        score -= 6; tags.append("向上跳空(追高)")
    if ck["new_high20"] and vr >= 1.5 and ck["bull"]:
        tags.append("帶量創高(強勢)")
    score = A.clamp(score, 15, 85)
    if not tags:
        tags = ["無明顯型態"]
    note = "K 線型態（昨收→今）：%s。今日為%s。" % ("、".join(tags), "紅K(漲)" if ck["bull"] else "黑K(跌)")
    return _ind("candle_" + key, name, "trend", "、".join(tags[:2]), score, note, weight=0.5)


# =====================================================================
# 籌碼：法人 vs 散戶（核心訴求）
# =====================================================================
def _yi(x):  # 元 → 億
    return None if x is None else x / 1e8


def _margin_yi(x):  # 仟元 → 億
    return None if x is None else x / 1e5


def _hist_window(hist, n):
    return hist[-n:] if len(hist) >= n else hist[:]


def _institutional(hist) -> Optional[Dict]:
    rows = [r for r in hist if r.get("foreign") is not None]
    if not rows:
        return None
    win = _hist_window(rows, 5)
    net5 = sum((r.get("foreign") or 0) + (r.get("invtrust") or 0) for r in win)
    net5_yi = net5 / 1e8
    score = A.clamp(50 + (net5_yi / 2000) * 30, 15, 85)
    series = [(((r.get("foreign") or 0) + (r.get("invtrust") or 0)) / 1e8) for r in rows[-60:]]
    note = ("外資＋投信近 %d 個交易日合計 %+.0f 億。錢不會說謊：法人連續買就是有人知道些什麼，"
            "連續賣的時候也一樣。" % (len(win), net5_yi))
    if len(rows) < 5:
        note += "（歷史累積中，視窗 %d 日）" % len(rows)
    return _ind("inst", "法人買賣超（外資＋投信）", "chips",
                "近5日 %+.0f 億" % net5_yi, score, note, series=series, weight=1.0)


def _margin(hist) -> Optional[Dict]:
    rows = [r for r in hist if r.get("margin_balance") is not None]
    if not rows:
        return None
    bal_yi = rows[-1]["margin_balance"] / 1e5
    chg = None
    if len(rows) >= 2:
        k = min(5, len(rows) - 1)
        prev = rows[-1 - k]["margin_balance"]
        if prev:
            chg = rows[-1]["margin_balance"] / prev - 1
    score = 50 if chg is None else A.clamp(50 - (chg / 0.05) * 35, 15, 85)
    series = [r["margin_balance"] / 1e5 for r in rows[-60:]]
    note = ("融資餘額 %.0f 億" % bal_yi) + (
        "（近%d日 %+.1f%%）。融資衝高＝散戶借錢追行情，歷史上這群人集體興奮的點位都很精準——精準地買在山頂。"
        % (min(5, len(rows) - 1), (chg or 0) * 100) if chg is not None else "（歷史累積中）。")
    disp = "%.0f 億" % bal_yi + ("（近5日 %+.1f%%）" % (chg * 100) if chg is not None else "")
    return _ind("margin", "融資餘額（散戶槓桿）", "chips", disp, score, note,
                series=series, weight=1.0)


def _divergence(hist) -> Optional[Dict]:
    rows_i = [r for r in hist if r.get("foreign") is not None]
    rows_m = [r for r in hist if r.get("margin_balance") is not None]
    if len(rows_i) < 2 or len(rows_m) < 2:
        return None
    win = _hist_window(rows_i, 5)
    net5_yi = sum((r.get("foreign") or 0) + (r.get("invtrust") or 0) for r in win) / 1e8
    k = min(5, len(rows_m) - 1)
    prev = rows_m[-1 - k]["margin_balance"]
    margin_chg = (rows_m[-1]["margin_balance"] / prev - 1) if prev else 0
    inst_z = A.clamp(net5_yi / 2000, -1.5, 1.5)
    retail_z = A.clamp(margin_chg / 0.04, -1.5, 1.5)
    diverg = inst_z - retail_z          # 法人買&散戶退 → 高
    score = A.clamp(50 + (diverg / 3) * 45, 10, 92)
    inst_txt = "買超" if net5_yi >= 0 else "賣超"
    retail_txt = "加碼" if margin_chg >= 0 else "減碼"
    if net5_yi >= 0 and margin_chg < 0:
        regime = "聰明錢進場、散戶退場 → 偏多背離（最佳組合）"
    elif net5_yi < 0 and margin_chg > 0:
        regime = "法人撤、散戶追高 → 偏空背離（最該警惕）"
    elif net5_yi >= 0 and margin_chg >= 0:
        regime = "法人與散戶同向買，多方但需防過熱"
    else:
        regime = "法人與散戶同向退，弱勢整理"
    note = "法人%s＋散戶%s：%s。" % (inst_txt, retail_txt, regime)
    series = [(((r.get("foreign") or 0) + (r.get("invtrust") or 0)) / 1e8) for r in rows_i[-60:]]
    return _ind("diverg", "★ 法人 vs 散戶 背離訊號", "chips",
                "法人%s／散戶%s" % (inst_txt, retail_txt), score, note,
                series=series, weight=1.5,
                detail="法人近5日 %+.0f 億　融資近5日 %+.1f%%" % (net5_yi, margin_chg * 100))


def _volume(turnover, yh) -> Optional[Dict]:
    # 首選：證交所 FMTQIK 有成交『值』（單位億）。但它只回當月，月初資料太少。
    if turnover and turnover.get("rows"):
        vals = [r["value"] for r in turnover["rows"] if r.get("value")]
        if len(vals) >= 5:
            today = vals[-1]
            avg = sum(vals) / len(vals)
            ratio = today / avg if avg else 1
            score = A.clamp(55 - (ratio - 1) * 30, 35, 68)
            note = ("今日成交值 %.0f 億，為近月均量 %.0f%%。爆量＝有人在大進大出，轉折常挑這種日子；"
                    "量縮＝大家都在等，你也可以等。" % (today / 1e8, ratio * 100))
            return _ind("volume", "成交量能", "chips",
                        "%.0f 億（均量 %.0f%%）" % (today / 1e8, ratio * 100), score, note,
                        series=[v / 1e8 for v in vals[-60:]], weight=0.5)
    # 退路：用 Yahoo 台股加權成交量（有完整歷史，月初不會斷檔）。比值即可，單位略過。
    h = yh.get("twii")
    vol = [v for v in A.clean(h["volume"]) if v > 0] if h else []
    if len(vol) >= 21:
        today = vol[-1]
        avg = sum(vol[-20:]) / 20
        ratio = today / avg if avg else 1
        score = A.clamp(55 - (ratio - 1) * 30, 35, 68)
        note = "台股量能為 20 日均量 %.0f%%（爆量常見於轉折、量縮代表觀望）。" % (ratio * 100)
        return _ind("volume", "成交量能", "chips", "為20日均量 %.0f%%" % (ratio * 100), score, note,
                    series=[v / 1e6 for v in vol[-60:]], weight=0.5)
    return None


# =====================================================================
# 組裝
# =====================================================================
def _ptt_sentiment(ptt) -> Optional[Dict]:
    """散戶情緒溫度計（PTT，逆勢）：標的文一面倒看多＝過熱、一面倒看空＝恐慌打折。

    與融資餘額、法人散戶背離同族：反映「散戶在想什麼」，方向反著用。
    樣本 <6 篇不表態；爆文連發會放大原方向（看多爆文=更過熱、看空爆文=恐慌高潮）。
    """
    if not ptt:
        return None
    b, brs = ptt.get("bull", 0), ptt.get("bear", 0)
    n = b + brs
    if n < 6:
        return None
    ratio = b / n * 100.0
    # 逆勢只在「極端」成立：溫和樂觀常伴隨動能延續（人人喊多也確實會再漲一段），
    # 所以 40~72% 是寬平的無訊號區；只有一面倒（>80% 或 <25%）才給方向。
    score = A.piecewise(ratio, [(10, 74), (25, 63), (40, 53), (72, 50), (82, 43), (92, 33)])
    hot = ptt.get("hot", 0)
    if ratio >= 80 and hot >= 3:
        score -= 4                        # 一面倒看多＋全場歡騰 → 買盤枯竭警訊
    elif ratio <= 25 and hot >= 3:
        score += 4                        # 一面倒看空＋恐慌洗版 → 賣壓高潮
    cached = "（快取）" if ptt.get("_cached") else ""
    note = ("PTT Stock 近 %d 篇標的文：看多 %.0f%%、全板爆文 %d 篇。逆勢但只看極端——"
            "溫和樂觀不是訊號（動能常延續）；一面倒看多＋歡騰＝買盤枯竭警訊、"
            "一面倒看空＋恐慌洗版＝歷史上常是分批撿貨區。" % (n, ratio, hot))
    return _ind("ptt", "散戶情緒溫度計（PTT）", "chips",
                "看多 %.0f%%・n=%d%s" % (ratio, n, cached), score, note, weight=0.6)


def compute_all(data: Dict) -> List[Dict]:
    yh = data.get("yh", {})
    cpi = data.get("cpi")
    ust = data.get("ust")
    val = data.get("val")
    turnover = data.get("turnover")
    ndc = data.get("ndc")
    hist = data.get("tw_hist", [])

    candidates = [
        _vix(yh), _vix_term(yh), _fear_greed(yh),
        _tw_valuation(val),
        _drawdown(yh, "spx", "美股距高點回檔（S&P500）"),
        _drawdown(yh, "twii", "台股距高點回檔（加權）"),
        _cpi(cpi), _yield_curve(ust), _dxy(yh), _copper_gold(yh), _business_signal(ndc),
        # A・長期趨勢品質（直接看趨勢結構）
        _trend_quality(yh, "twii", "台股長期趨勢品質"),
        _trend_quality(yh, "spx", "美股長期趨勢品質", weight=1.0),
        # C・技術面擴充
        _macd_ind(yh, "twii", "台股 MACD 動能"),
        _bollinger(yh, "twii", "台股布林通道位置"),
        _volatility(yh, "twii", "台股波動度 ATR"),
        # B・K 線型態
        _candle(yh, "twii", "台股 K 線型態"),
        _institutional(hist), _margin(hist), _divergence(hist),
        _volume(turnover, yh),
        _ptt_sentiment(data.get("ptt")),
    ]
    out = [c for c in candidates if c]
    # 套用 config 的可調權重（找不到就沿用指標自帶的預設）
    for c in out:
        c["weight"] = cfg.INDICATOR_WEIGHTS.get(c["key"], c["weight"])
    return out

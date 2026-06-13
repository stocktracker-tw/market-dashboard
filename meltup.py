# -*- coding: utf-8 -*-
"""AI 噴發 / 泡沫 情境評估。

回答兩個純逆勢分數答不好的問題：
  1) 現在像不像「噴發/泡沫」、有多脆弱？→ 泡沫脆弱度 0–100（越高越像晚期泡沫）
  2) 噴發還在進行，還是已經高檔轉弱？→ 決定該「參與」還是「減碼」

理念：純逆勢會在噴發期叫你太早收手；真噴成泡沫又得先下車。比較穩健的做法是
「趨勢還完好時參與，但設好機械式出場（跌破 50 日線）」。本模組把這個判斷量化。

脆弱度的組成（都用既有行情算，不另外抓資料）：
  • 乖離極端度：台股/美股/費半 距 200 日均的乖離，在自身 2 年分佈的百分位。
  • AI/半導體集中度：費半 SOX 相對 S&P 的領先幅度——領導太窄＝泡沫較脆。
  • 散戶狂熱：融資餘額近期加速度。
  • 量價/波動背離：指數漲、VIX 卻同步走高 或 高收益債不確認＝警訊。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import analytics as A
import config as cfg


def _closes(yh, key):
    h = yh.get(key)
    return A.clean(h["close"]) if h else []


def _dist_series(close, w=200):
    """每個時點『收盤/200日均 − 1』的序列（用來算乖離的歷史百分位）。"""
    if len(close) < w + 10:
        return []
    out, run = [], sum(close[:w])
    for i in range(w, len(close)):
        ma = run / w
        if ma:
            out.append(close[i] / ma - 1)
        run += close[i] - close[i - w]
    return out


def _light_risk(frag: float) -> str:
    # 注意：這裡是「風險燈」，越高越危險 → 紅
    return "red" if frag >= 66 else "amber" if frag >= 40 else "green"


def assess(yh: Dict, tw_hist: Optional[List] = None) -> Optional[Dict]:
    twii = _closes(yh, "twii")
    spx = _closes(yh, "spx")
    sox = _closes(yh, "sox")
    if len(twii) < 220 and len(spx) < 220:
        return None

    comps: List = []        # (label, value_display, frag_contрib 0-100)
    weights: List = []

    # 1) 乖離極端度（取最極端的市場）
    ext_rows = []
    for label, s in (("台股加權", twii), ("S&P500", spx), ("費半SOX", sox)):
        ds = _dist_series(s, 200)
        if not ds:
            continue
        cur = ds[-1]
        pct = A.percentile_rank(cur, ds)
        if pct is not None:
            ext_rows.append((label, cur, pct))
    extreme = max(ext_rows, key=lambda x: x[2]) if ext_rows else None
    if extreme:
        label, cur, pct = extreme
        comps.append(("乖離極端度", "%s 距200日均 %+.0f%%（%.0f 百分位）" % (label, cur * 100, pct), pct))
        weights.append(0.40)

    # 2) AI / 半導體 集中度（SOX 相對 S&P 的 120 日領先）
    if len(sox) > 130 and len(spx) > 130:
        a = A.pct_change(sox, 120)
        b = A.pct_change(spx, 120)
        if a is not None and b is not None:
            lead = a - b
            frag = A.piecewise(lead, [(-0.05, 15), (0.0, 30), (0.10, 55), (0.20, 75), (0.35, 92)])
            comps.append(("AI/半導體集中度", "費半近120日領先 S&P %+.0f%%" % (lead * 100), frag))
            weights.append(0.25)

    # 3) 散戶狂熱（融資餘額近期變化）
    rows = [r for r in (tw_hist or []) if r.get("margin_balance") is not None]
    if len(rows) >= 3:
        k = min(5, len(rows) - 1)
        prev = rows[-1 - k]["margin_balance"]
        chg = (rows[-1]["margin_balance"] / prev - 1) if prev else 0
        frag = A.piecewise(chg, [(-0.03, 15), (0.0, 30), (0.03, 55), (0.06, 78), (0.10, 92)])
        comps.append(("散戶融資狂熱", "融資近%d日 %+.1f%%" % (k, chg * 100), frag))
        weights.append(0.20)

    # 4) 量價/波動 背離（指數漲、VIX 也漲＝警訊；高收益債不確認＝警訊）
    vix = _closes(yh, "vix")
    hyg = _closes(yh, "hyg")
    ief = _closes(yh, "ief")
    r_spx = A.pct_change(spx, 20)
    r_vix = A.pct_change(vix, 20) if vix else None
    warn = 30
    detail = "量價/波動同步，暫無明顯背離"
    if r_spx is not None and r_vix is not None and r_spx > 0 and r_vix > 0.05:
        warn = 75
        detail = "指數與 VIX 同步走高（避險升溫）＝背離警訊"
    elif hyg and ief:
        rh = A.pct_change(hyg, 20)
        ri = A.pct_change(ief, 20)
        if rh is not None and ri is not None and r_spx and r_spx > 0 and (rh - ri) < 0:
            warn = 60
            detail = "股漲但高收益債轉弱，信用面未確認"
    comps.append(("量價/波動確認", detail, warn))
    weights.append(0.15)

    # 綜合脆弱度
    tw = sum(weights)
    fragility = round(sum(c[2] * w for c, w in zip(comps, weights)) / tw, 0) if tw else 50

    # 噴發狀態：用最極端市場的趨勢結構判斷
    ref = twii if len(twii) >= 220 else spx
    ma50 = A.sma(ref, 50)
    ma200 = A.sma(ref, 200)
    price = ref[-1]
    ext_pct = extreme[2] if extreme else 0
    recently_extended = ext_pct >= 80 or (extreme and abs(extreme[1]) >= 0.15)
    trend_up = ma50 is not None and ma200 is not None and price > ma50 and ma50 > ma200
    if recently_extended and trend_up:
        status = "噴發中"
        status_note = "價格大幅延伸但趨勢仍完好——典型噴發。建議『參與但設好出場』，別在趨勢還在時硬空。"
    elif recently_extended and ma50 is not None and price < ma50:
        status = "高檔轉弱"
        status_note = "高檔已跌破 50 日線——噴發可能結束，這才是逆勢系統該真正減碼的時點。"
    else:
        status = "正常"
        status_note = "未處於極端延伸，照常規訊號操作即可。"

    ref_label = "台股加權" if len(twii) >= 220 else "S&P500"
    derisk = ("減碼觀察線：%s 跌破 50 日均線（約 %.0f）即視為噴發結束、啟動減碼。"
              % (ref_label, ma50)) if ma50 else ""

    return {
        "fragility": int(fragility),
        "fragility_light": _light_risk(fragility),
        "status": status,
        "status_note": status_note,
        "components": comps,
        "derisk_text": derisk,
        "floor_active": status == "噴發中",
        "ref_ma50": ma50,
    }

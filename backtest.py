# -*- coding: utf-8 -*-
"""用「截至當天」的資料回算過去 N 個交易日的綜合進場分數，

讓儀表板的『分數走勢圖』第一天就有東西看，也讓你大致看出訊號最近怎麼移動。

近似說明：歷史回算只用到有歷史序列的來源（Yahoo 行情、CPI、殖利率、景氣信號、
台股籌碼累積值）；估值中位數與成交量能沒有歷史快照，回測時略過，故回測分數與
每日實際分數的基準略有差異——看「趨勢」即可，不必逐點對齊。
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from typing import Dict, List, Set, Tuple

import indicators as ind_mod
import scoring


def _truncate_yh(yh: Dict, cutoff_ts: int) -> Dict:
    out = {}
    for k, h in yh.items():
        ts = h.get("timestamps") or []
        idx = bisect_right(ts, cutoff_ts)
        if idx < 5:
            continue
        out[k] = {"timestamps": ts[:idx],
                  "open": (h.get("open") or [])[:idx],
                  "high": (h.get("high") or [])[:idx],
                  "low": (h.get("low") or [])[:idx],
                  "close": (h.get("close") or [])[:idx],
                  "volume": (h.get("volume") or [])[:idx],
                  "meta": h.get("meta", {})}
    return out


def _ndc_light(score: float) -> str:
    if score <= 16:
        return "藍"
    if score <= 22:
        return "黃藍"
    if score <= 31:
        return "綠"
    if score <= 37:
        return "黃紅"
    return "紅"


def _cpi_asof(cpi, ym: str):
    if not cpi:
        return None
    hs = [(m, v) for m, v in cpi.get("headline_series", []) if m <= ym]
    cs = [(m, v) for m, v in cpi.get("core_series", []) if m <= ym]
    if not hs:
        return None
    return {"headline_yoy": hs[-1][1], "core_yoy": cs[-1][1] if cs else None,
            "headline_series": hs, "core_series": cs, "latest_month": hs[-1][0]}


def _ust_asof(ust, diso: str):
    if not ust:
        return None
    ss = [(d, v) for d, v in ust.get("spread_series", []) if str(d)[:10] <= diso]
    if not ss:
        return None
    return {"date": ss[-1][0], "spread": ss[-1][1], "spread_series": ss, "y2": None, "y10": None}


def _ndc_asof(ndc, ymnum: str):
    if not ndc:
        return None
    ss = [(str(m), float(v)) for m, v in ndc.get("score_series", []) if str(m) <= ymnum]
    if not ss:
        return None
    return {"date": ss[-1][0], "score": ss[-1][1], "light": _ndc_light(ss[-1][1]), "score_series": ss}


def compute_backtest(data: Dict, days: int, skip_dates: Set[str]) -> List[Tuple[str, float]]:
    """回傳 [(YYYY-MM-DD, composite)]，已排除今天與 skip_dates 中已存在的日期。"""
    yh = data.get("yh", {})
    ref = yh.get("spx") or yh.get("twii")
    if not ref or not ref.get("timestamps"):
        return []
    ts = ref["timestamps"]
    sel = ts[-(days + 1):-1] if len(ts) > days + 1 else ts[:-1]  # 去掉最後一根(今天=實際分數)
    cpi, ust, ndc = data.get("cpi"), data.get("ust"), data.get("ndc")
    twh = data.get("tw_hist", [])
    out: List[Tuple[str, float]] = []
    for cutoff in sel:
        d = dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).date()
        diso = d.strftime("%Y-%m-%d")
        if diso in skip_dates:
            continue
        dstr, ym, ymnum = d.strftime("%Y%m%d"), d.strftime("%Y-%m"), d.strftime("%Y%m")
        asof = {
            "yh": _truncate_yh(yh, cutoff),
            "cpi": _cpi_asof(cpi, ym),
            "ust": _ust_asof(ust, diso),
            "ndc": _ndc_asof(ndc, ymnum),
            "val": None, "turnover": None,
            "tw_hist": [r for r in twh if r.get("date") and r["date"] <= dstr],
        }
        inds = ind_mod.compute_all(asof)
        if not inds:
            continue
        out.append((diso, scoring.aggregate(inds)["composite"]))
    return out

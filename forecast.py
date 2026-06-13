# -*- coding: utf-8 -*-
r"""歷史條件式預期（base rates）——不是預測未來，是過去的條件機率。

對「目前的市場條件」（這裡用『距 200 日均線的乖離』），拿過去約 10 年的日資料，
找出歷史上處在『相同乖離十分位』的那些日子，它們未來 1/3/6 個月平均怎麼走、
上漲機率多少。用意：讓「現在到底偏多偏空」有客觀的歷史基準，而不只是工具的主觀分數。

⚠️ 過去 ≠ 未來，樣本也有限；這是基準機率，不是保證、更不是投資建議。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import analytics as A
import sources as src

HORIZONS = [("1個月", 21), ("3個月", 63), ("6個月", 126)]
TARGETS = [("台股加權", "^TWII"), ("美股 S&P500", "^GSPC")]


def _ext_and_forward(close, horizon, w=200):
    c = A.clean(close)
    if len(c) < w + horizon + 80:
        return None
    ext, run = [], sum(c[:w])
    for i in range(w, len(c)):
        ma = run / w
        if ma:
            ext.append((i, c[i] / ma - 1))
        run += c[i] - c[i - w]
    if not ext:
        return None
    cur = ext[-1][1]
    rows = [(e, c[i + horizon] / c[i] - 1) for i, e in ext if i + horizon < len(c)]
    return cur, rows


def _decile_stats(cur, rows, n_bins=10):
    if cur is None or len(rows) < 60:
        return None
    exts = sorted(r[0] for r in rows)
    n = len(exts)
    below = sum(1 for e in exts if e <= cur)
    d = min(n_bins - 1, int(below / n * n_bins))
    lo = exts[int(d / n_bins * n)]
    hi = exts[min(n - 1, int((d + 1) / n_bins * n) - 1)]
    bucket = [fwd for e, fwd in rows if lo <= e <= hi]
    if len(bucket) < 10:
        bucket = [fwd for _, fwd in rows]
    mean = sum(bucket) / len(bucket)
    win = sum(1 for x in bucket if x > 0) / len(bucket)
    return {"mean": mean, "win": win, "n": len(bucket), "decile": d + 1}


def assess() -> Optional[List[Dict]]:
    out = []
    for label, sym in TARGETS:
        h = src.yahoo_history(sym, rng="10y")
        if not h:
            continue
        close = h["close"]
        cur_ext, horizons = None, []
        for hl, hz in HORIZONS:
            res = _ext_and_forward(close, hz)
            if not res:
                continue
            cur, rows = res
            cur_ext = cur
            st = _decile_stats(cur, rows)
            if st:
                horizons.append({"label": hl, **st})
        if cur_ext is None or not horizons:
            continue
        three = next((x for x in horizons if x["label"] == "3個月"), horizons[-1])
        m = three["mean"]
        lean = "偏多" if m > 0.02 else "偏空" if m < -0.02 else "中性"
        lean_light = "green" if m > 0.02 else "red" if m < -0.02 else "amber"
        out.append({"label": label, "ext": cur_ext, "decile": horizons[0]["decile"],
                    "horizons": horizons, "lean": lean, "lean_light": lean_light})
    return out or None

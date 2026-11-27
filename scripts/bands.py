"""分數區間的共用讀取點（資料在 repo 根目錄的 bands.json）。

門檻曾經在 gen_stock_pages、patch_site、premarket_score 各寫一份，改了一邊
忘了另一邊（43 vs 45、倍數 1.25 vs 1.5）。現在全部從這裡拿。
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bands.json")
with open(_PATH, encoding="utf-8") as _f:
    _D = json.load(_f)

BANDS = sorted(_D["bands"], key=lambda b: -b["min"])      # 由高到低
CUTS = [b["min"] for b in BANDS if b["min"] > 0]          # 例：[70, 58, 45, 35]
LIGHT_GREEN_MIN = _D["light"]["green_min"]
LIGHT_RED_MAX = _D["light"]["red_max"]


def level(sc):
    """0（最低區）到 len(CUTS)（最高區）。"""
    for i, c in enumerate(CUTS):
        if sc >= c:
            return len(CUTS) - i
    return 0


def band(sc):
    return BANDS[len(CUTS) - level(sc)]


def mult(sc):
    return band(sc)["mult"]


def js_zone():
    """給前端用的同一套門檻：function zone(sc){return sc>=70?4:...:0;}"""
    body = "".join("sc>=%g?%d:" % (c, len(CUTS) - i) for i, c in enumerate(CUTS))
    return "function zone(sc){return %s0;}" % body

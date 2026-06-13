# -*- coding: utf-8 -*-
"""把所有指標卡彙整成一個 0-100 的『綜合進場分數』。

作法：
  1. 各指標在所屬面向(pillar)內依自身 weight 加權平均 → 面向分數。
  2. 面向再依 PILLAR_WEIGHTS 加權平均 → 綜合分數。
  3. 只要某面向沒有任何可用指標，該面向權重會自動從分母剔除（不灌水）。
分數越高＝越適合加碼；並換算成『建議定額倍數』，把被動定期定額變主動。
"""
from __future__ import annotations

import sys
from typing import Dict, List

import config as _cfg
from config import (ACTION_BANDS, LIGHT_GREEN_MIN, LIGHT_RED_MAX,
                    PILLAR_NAMES, PILLAR_WEIGHTS)


def _light(score: float) -> str:
    return "green" if score >= LIGHT_GREEN_MIN else "red" if score < LIGHT_RED_MAX else "amber"


def _weighted(items: List[Dict]) -> float:
    tw = sum(i["weight"] for i in items)
    if tw == 0:
        return 50.0
    return sum(i["score"] * i["weight"] for i in items) / tw


def aggregate(indicators: List[Dict]) -> Dict:
    by_pillar: Dict[str, List[Dict]] = {k: [] for k in PILLAR_WEIGHTS}
    orphans = set()
    for ind in indicators:
        cat = ind["category"]
        if cat not in PILLAR_WEIGHTS:          # 分類拼錯/沒加權重 → 會被靜默漏算，出聲提醒
            orphans.add(cat)
        by_pillar.setdefault(cat, []).append(ind)
    if orphans:
        print("⚠️ scoring：指標分類不在 PILLAR_WEIGHTS，未計入綜合分數：%s"
              % ", ".join(sorted(orphans)), file=sys.stderr)

    pillars = []
    num = 0.0
    den = 0.0
    for key, weight in PILLAR_WEIGHTS.items():
        items = by_pillar.get(key, [])
        if not items:
            continue
        pscore = _weighted(items)
        pillars.append({
            "key": key, "name": PILLAR_NAMES.get(key, key),
            "score": round(pscore, 1), "weight": weight,
            "light": _light(pscore),
            "n": len(items),
        })
        num += pscore * weight
        den += weight

    composite = num / den if den else 50.0
    # 對比旋鈕：分數常被一堆窄區間指標拉回 50。COMPOSITE_CONTRAST>1 會以 50 為中心拉開，
    # 讓「積極加碼/保守」band 更有機會觸發。預設 1.0＝完全不變（需用 forecast.py 回測再調）。
    contrast = getattr(_cfg, "COMPOSITE_CONTRAST", 1.0)
    composite = round(max(0.0, min(100.0, 50 + (composite - 50) * contrast)), 1)
    band, action, multiplier = _interpret(composite)
    return {
        "composite": composite,
        "band": band,
        "action": action,
        "dca_multiplier": multiplier,
        "pillars": pillars,
        "n_indicators": len(indicators),
    }


def _interpret(score: float):
    """依 config.ACTION_BANDS 由高到低比對，回傳 (等級, 建議, 定額倍數)。"""
    for threshold, band_name, action, multiplier in ACTION_BANDS:
        if score >= threshold:
            return (band_name, action, multiplier)
    last = ACTION_BANDS[-1]
    return (last[1], last[2], last[3])

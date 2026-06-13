# -*- coding: utf-8 -*-
"""景氣循環階段判斷（投資時鐘 Investment Clock）。

兩個軸：
  • 成長方向：國發會『領先指標(不含趨勢)』近 3 個月的變化（轉強/轉弱）。
  • 通膨方向：美國 CPI 年增率近 3 個月的變化（升/降）。
兩軸交叉成四個階段，並用『景氣對策信號』燈號標出在循環中的位置：

            通膨↓                 通膨↑
  成長↑   復甦(對股市最有利)     過熱(晚循環,留意轉折)
  成長↓   趨緩/衰退(谷底醞釀買點)  滯脹(對股市最不利)

對定期定額的意義：最甜蜜的長線布局點通常在『成長落底翻揚＋藍燈』；最該保守在『滯脹』。
此面板為情境參考，不直接灌進進場分數。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def _dir3(series: Optional[List[Tuple]]):
    """近 3 個月變化（最後一筆 − 3 個月前）。資料不足回 None。"""
    if not series or len(series) < 4:
        return None
    return series[-1][1] - series[-4][1]


def assess(ndc: Optional[Dict], cpi: Optional[Dict]) -> Optional[Dict]:
    if not ndc:
        return None

    # 成長方向：優先用領先指標，不足時退用景氣對策信號分數
    g = _dir3(ndc.get("leading_series"))
    g_src = "領先指標"
    if g is None:
        g = _dir3(ndc.get("score_series"))
        g_src = "景氣信號分數"
    if g is None:
        return None
    growth_up = g > 0

    # 通膨方向：CPI 年增近 3 個月變化（個百分點）
    infl = _dir3((cpi or {}).get("headline_series"))
    infl_known = infl is not None
    infl_up = bool(infl_known and infl > 0)

    # 四象限
    if growth_up and not infl_up:
        phase, color = "復甦", "green"
        impl = "成長回升、通膨回落——對股市最有利,屬適合分批加碼的階段。"
    elif growth_up and infl_up:
        phase, color = "過熱", "amber"
        impl = "成長與通膨同步走高——晚循環,股市仍可漲但風險升,留意轉折與商品。"
    elif (not growth_up) and infl_up:
        phase, color = "滯脹", "red"
        impl = "成長轉弱、通膨仍高——歷史上對股市最不利,宜保守、留現金。"
    else:
        phase, color = "趨緩/衰退", "amber"
        impl = "成長與通膨同步回落——利債;若落到藍燈谷底區,反而是長線甜蜜布局點。"
    if not infl_known:
        impl += "（通膨資料暫缺,僅以成長方向判斷,參考即可）"

    # 在循環中的位置（用景氣對策信號燈號）
    light = ndc.get("light", "")
    score = ndc.get("score")
    if "藍" in light:
        pos = "谷底區（藍燈・景氣低迷）"
    elif "紅" in light:
        pos = "高峰區（紅燈・景氣熱絡）"
    elif "綠" in light:
        pos = "穩定區（綠燈）"
    else:
        pos = "轉折區（黃燈）"

    components = [
        ("成長方向", "%s近3月 %+.2f → %s" % (g_src, g, "轉強" if growth_up else "轉弱"),
         "green" if growth_up else "red"),
        ("通膨方向", ("CPI年增近3月 %+.1f 個百分點 → %s" % (infl, "上升" if infl_up else "回落"))
         if infl_known else "CPI 資料暫缺", "red" if infl_up else "green"),
        ("景氣位置", "%s燈・%s 分" % (light, score) if score is not None else pos,
         "red" if "紅" in light else "green" if "藍" in light else "amber"),
    ]

    return {
        "phase": phase, "color": color, "position": pos,
        "implication": impl, "components": components,
        "growth_up": growth_up, "infl_up": infl_up,
    }

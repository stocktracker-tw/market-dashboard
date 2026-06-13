# -*- coding: utf-8 -*-
r"""三派投資策略觀點——用三位公開倡導的投資理念『框架』解讀目前數據。

⚠️ 重要：以下是以「公開的投資策略流派」為框架對現況的推演，
   **不是這三位本人的發言、不是他們對個股/大盤的看法、也不是投資建議**。
   重點之一是誠實呈現：三派的哲學彼此矛盾（被動派根本反對擇時），
   所以「正解」取決於你信哪一套。

  • 清流君 → 指數化／被動投資（市場有效、反對擇時、低成本、資產配置、定期定額、長期）。
  • 游庭皓 → 由上而下總經／景氣循環（流動性、利率、信用、債市、循環位置）。
  • 股癌   → 紀律風控／順勢控倉（別追高當散戶、留銀彈、設停損、不 All in 不空手）。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _ind(indicators, namekey):
    for i in indicators or []:
        if namekey in i.get("name", ""):
            return i
    return None


def _debate(comp):
    """三方激烈交鋒（以各自投資流派的立場互嗆，非本人發言）。"""
    ex = [
        # 被動 ↔ 紀律
        ("清X君", "股X", "你那套停損、加減碼，交易成本加擇時失誤長期吃掉的，比你閃掉的回檔還多——主動擇時十年有八年跑輸大盤，這是數據，不是嘴砲。"),
        ("股X", "清X君", "市場長期有效我同意，但 2022 大盤腰斬那段你真抱得住？多少人帳面對折就停損在最低點。先活下來，才有資格談你那個『長期』。"),
        # 被動 ↔ 總經
        ("清X君", "財經X角", "你天天猜 Fed、猜循環位置——到底猜對幾次？總經預測準度跟丟銅板差不多，難得猜對方向的，進場時機又全錯。"),
        ("財經X角", "清X君", "無腦定額在升息抽銀根、流動性枯竭那兩年照樣套到天荒地老。你不是不擇時，是被動承受最爛的時機，還催眠自己沒事。"),
        # 總經 ↔ 紀律
        ("財經X角", "股X", "你盯 50 日線、看籌碼，那全是後照鏡。等價格跌破你的訊號，流動性早就轉向，你永遠慢人家半拍。"),
        ("股X", "財經X角", "總經講得頭頭是道，但真正進出場那一刻靠的是價格與紀律，不是你那張景氣循環圖——圖很漂亮，可惜換不到錢。"),
    ]
    if comp is not None and comp < 42:
        ex.append(("財經X角", "大家", "現在這位置我只有一句：先防禦，別跟流動性收縮硬拚。"))
        ex.append(("股X", "大家", "分數轉弱就該減碼，還在凹單硬拗的，等著被市場抬出場。"))
        ex.append(("清X君", "大家", "你們兩個吵得臉紅脖子粗，我照樣定額買、繼續睡覺，十年後再看誰笑。"))
    elif comp is not None and comp >= 58:
        ex.append(("股X", "大家", "分數轉強可以參與，但我還是那句——留銀彈、別 All in，輪到主流股再上。"))
        ex.append(("財經X角", "大家", "循環沒翻空、流動性還在，可以偏積極；但融資這麼燙，我會死盯信用利差。"))
        ex.append(("清X君", "大家", "轉強轉弱跟我無關，加碼減碼的成本你們自己付，我只負責不間斷地買。"))
    else:
        ex.append(("清X君", "大家", "分數不上不下，你們還在折騰加減碼——我繼續定額，省下的力氣拿去過生活。"))
    return ex


def assess(result: Dict, indicators: List[Dict], regime: Optional[Dict],
           cycle: Optional[Dict], forecast: Optional[List]) -> List[Dict]:
    comp = result.get("composite")
    phase = (cycle or {}).get("phase")
    pos = (cycle or {}).get("position", "")
    status = (regime or {}).get("status")
    frag = (regime or {}).get("fragility")
    margin = _ind(indicators, "融資餘額")
    margin_chasing = bool(margin and margin.get("light") == "red")     # 融資增=散戶追
    trend_p = next((p for p in result.get("pillars", []) if p["key"] == "trend"), {}).get("score", 50)
    fc_tw = next((t for t in (forecast or []) if "台股" in t.get("label", "")), None)
    fc_txt = ""
    if fc_tw:
        h3 = next((h for h in fc_tw["horizons"] if h["label"] == "3個月"), None)
        if h3:
            fc_txt = "（歷史同類乖離→未來3月平均 %+.1f%%、勝率 %.0f%%）" % (h3["mean"] * 100, h3["win"] * 100)

    out = []

    # 1) 清流君：被動指數
    out.append({
        "name": "清X君", "school": "指數化／被動投資",
        "principles": "市場有效・反對擇時・低成本・全球分散・定期定額不間斷・長期持有・定期再平衡",
        "lean": "照表操課（不擇時）", "lean_light": "amber",
        "take": ("在這套框架下，綜合分數 %s、噴發、景氣紅燈……都是雜訊。建議：維持原定定期定額"
                 "（0050／VT 之類）不間斷，把力氣放在**降低成本、股債資產配置與再平衡**，而不是加減碼。"
                 "他會直接質疑這支『擇時』工具的前提——長期而言擇時勝率低於紀律定額。"
                 % (("%.0f" % comp) if comp is not None else "")),
    })

    # 2) 游庭皓：總經/景氣循環
    if phase in ("過熱", "滯脹"):
        lean, light = "偏防禦、重質、控風險", "red"
    elif phase in ("趨緩/衰退",):
        lean, light = "中性偏債、等景氣落底", "amber"
    elif phase == "復甦":
        lean, light = "偏積極（循環向上）", "green"
    else:
        lean, light = "中性、看流動性臉色", "amber"
    out.append({
        "name": "財經X角", "school": "由上而下總經／景氣循環",
        "principles": "景氣循環位置・流動性・利率與債市・信用利差・由上而下",
        "lean": lean, "lean_light": light,
        "take": ("由總經看：景氣循環研判為「%s」(%s)、Fed 全年僅約 1 碼、殖利率曲線與信用是關鍵變數、"
                 "且融資槓桿暴增。這套框架會偏**防禦、重基本面與現金流、緊盯流動性與信用轉折**，"
                 "而非追估值或題材。" % (phase or "—", pos or "—")),
    })

    # 3) 股癌：紀律風控/順勢控倉
    if trend_p >= 50 and (status == "噴發中" or margin_chasing):
        lean, light = "參與但留銀彈、別重壓", "amber"
        take = ("趨勢還偏多、動能在%s，但**散戶融資在追、噴發脆弱度 %s**。這派的紀律：可參與、"
                "但**控制部位、別 All in、留現金等回檔**，**跌破 50 日線就減碼**——重點是別當追高的那隻韭菜。"
                % (fc_txt, frag if frag is not None else "偏高"))
    elif trend_p < 42:
        lean, light = "弱勢、減碼控風險", "red"
        take = "趨勢轉弱，這派會降部位、守紀律、等訊號重新轉強再進。"
    else:
        lean, light = "順勢操作、嚴設停損", "green"
        take = "趨勢健康、籌碼未過熱，這派傾向順勢參與，但一樣嚴設停損、控部位。"
    out.append({
        "name": "股X", "school": "紀律風控／順勢控倉",
        "principles": "順勢但控部位・別追高當散戶・留銀彈・設停損・不 All in 不空手",
        "lean": lean, "lean_light": light, "take": take,
    })

    # 結論（把三方辯論收斂成一段；分歧本身就是訊息）
    band = result.get("band", "")
    cscore = ("%.0f" % comp) if comp is not None else ""
    if comp is None:
        verdict = "資料不足，先別急著動作。"
    elif comp >= 58:
        verdict = "三方裡被動派照買不動、紀律派說可參與但留銀彈、總經派看循環沒翻空也不反對——勉強的共識：可分批，但別重壓、別 All in。"
    elif comp < 42:
        verdict = "總經派與紀律派都喊防禦、別追高；被動派照買不動、把下跌當打折。共識僅止於：別在這裡重壓賭反彈。"
    else:
        verdict = "分數中性，三方沒有壓倒性共識——維持定額節奏、控好部位，別在這時候賭方向。"
    synthesis = ("【結論】三方交鋒收斂：被動派(清X君)叫你『照買別動、擇時長期輸給定額』、"
                 "總經派(財經X角)要你『看景氣與流動性臉色』、紀律派(股X)要你『順勢但留銀彈、跌破就減碼』。\n"
                 "三套邏輯彼此矛盾——被動派根本反對另外兩派擇時——正解取決於你信哪一套。\n"
                 "目前工具分數 %s（%s）。%s\n"
                 "以上皆為策略流派框架推演、非本人發言、非投資建議。"
                 % (cscore, band, verdict))
    return [{"synthesis": synthesis, "debate": _debate(comp)}] + out

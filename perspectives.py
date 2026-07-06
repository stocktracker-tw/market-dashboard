# -*- coding: utf-8 -*-
r"""五派投資觀點——用五種公開投資流派的『框架』解讀當天的實際數據。

⚠️ 重要：以下是以「公開的投資策略流派」為框架對現況的推演，
   **不是任何人的發言、也不是投資建議**。
   重點之一是誠實呈現：五派的哲學彼此矛盾（被動派根本反對擇時），
   所以「正解」取決於你信哪一套。

  • 被動指數派 → 市場有效、反對擇時、低成本、資產配置、定期定額、長期。
  • 總經循環派 → 由上而下：景氣循環位置、流動性、利率、信用、債市。
  • 順勢紀律派 → 順勢控倉：別追高當散戶、留銀彈、設停損、不 All in 不空手。
  • 價值派     → 基本面選股：能力圈、護城河、安全邊際、便宜才買、長期持有。
  • 籌碼派     → 跟著錢走：三大法人、外資期貨未平倉、融資融券、法人散戶背離。

每一派的 take 都從當天引擎算出的指標／支柱／循環／籌碼資料生成，
數據變了說法就變——不是寫死的罐頭文。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _ind(indicators, namekey):
    for i in indicators or []:
        if namekey in i.get("name", ""):
            return i
    return None


def _pillar(result, key, default=50.0):
    return next((p for p in result.get("pillars", []) if p["key"] == key),
                {}).get("score", default)


def _disp(ind):
    """指標的 value_display；沒有就回 '—'。"""
    return (ind or {}).get("value_display") or "—"


def assess(result: Dict, indicators: List[Dict], regime: Optional[Dict],
           cycle: Optional[Dict], forecast: Optional[List],
           taifex: Optional[Dict] = None,
           picks: Optional[Dict] = None) -> List[Dict]:
    comp = result.get("composite")
    phase = (cycle or {}).get("phase")
    pos = (cycle or {}).get("position", "")
    implication = (cycle or {}).get("implication") or ""
    status = (regime or {}).get("status")
    frag = (regime or {}).get("fragility")
    margin = _ind(indicators, "融資餘額")
    margin_chasing = bool(margin and margin.get("light") == "red")     # 融資增=散戶追
    trend_p = _pillar(result, "trend")
    val_p = _pillar(result, "valuation")
    chips_p = _pillar(result, "chips")
    fc_tw = next((t for t in (forecast or []) if "台股" in t.get("label", "")), None)
    fc_txt = ""
    if fc_tw:
        h3 = next((h for h in fc_tw["horizons"] if h["label"] == "3個月"), None)
        if h3:
            fc_txt = "（歷史同類乖離→未來3月平均 %+.1f%%、勝率 %.0f%%）" % (h3["mean"] * 100, h3["win"] * 100)

    out = []

    # 大環境水位（總經派升格為頂部橫幅：它本來就「選階段不選股」）
    if phase in ("過熱", "滯脹"):
        lean, light = "偏防禦、重質、控風險", "red"
    elif phase in ("趨緩/衰退",):
        lean, light = "中性偏債、等景氣落底", "amber"
    elif phase == "復甦":
        lean, light = "偏積極（循環向上）", "green"
    else:
        lean, light = "中性、看流動性臉色", "amber"
    ust = _ind(indicators, "殖利率曲線")
    macro_bits = ["景氣循環研判為「%s」%s"
                  % (phase or "—", ("（%s）" % pos) if pos else "")]
    if ust:
        macro_bits.append("殖利率曲線 %s" % _disp(ust))
    if margin_chasing:
        macro_bits.append("散戶融資槓桿在升溫")
    env_line = {"lean": lean, "light": light,
                "text": ("總經水位：%s。%s" % ("、".join(macro_bits),
                         (implication + "。") if implication else ""))}
    anchor_line = ("被動派的永恆答案：照原定定額買 0050／VT、別擇時——"
                   "本頁所有擇時內容，都該先過得了這一句再說。")

    # 1) 順勢紀律派——lean 跟著趨勢支柱與噴發/融資狀態走
    if trend_p >= 50 and (status == "噴發中" or margin_chasing):
        lean, light = "參與但留銀彈、別重壓", "amber"
        risks = []
        if margin_chasing:
            risks.append("散戶融資在追")
        if status == "噴發中":
            risks.append("噴發脆弱度 %s" % (frag if frag is not None else "偏高"))
        take = ("趨勢還偏多、動能在%s，但**%s**。這派的紀律：可參與、"
                "但**控制部位、別 All in、留現金等回檔**，**跌破 50 日線就減碼**——重點是別當追高的那隻韭菜。"
                % (fc_txt, "、".join(risks)))
    elif trend_p < 42:
        lean, light = "弱勢、減碼控風險", "red"
        take = "趨勢轉弱（趨勢支柱 %.0f 分），這派會降部位、守紀律、等訊號重新轉強再進。" % trend_p
    else:
        lean, light = "順勢操作、嚴設停損", "green"
        take = ("趨勢健康（趨勢支柱 %.0f 分）、籌碼未過熱%s，這派傾向順勢參與，"
                "但一樣嚴設停損、控部位。" % (trend_p, fc_txt))
    out.append({
        "name": "順勢紀律派", "school": "紀律風控／順勢控倉",
        "principles": "順勢但控部位・別追高當散戶・留銀彈・設停損・不 All in 不空手",
        "lean": lean, "lean_light": light, "take": take,
    })

    # 2) 價值派——lean 跟著估值支柱走，內文引用當天的估值與回檔數據
    tw_val = _ind(indicators, "台股估值")
    dd_tw = _ind(indicators, "台股距高點回檔")
    dd_us = _ind(indicators, "美股距高點回檔")
    if val_p >= 58:
        vlean, vlight = "價格出現折扣、分批布局", "green"
        vline = "折扣出現了——這派會開始分批撿便宜，但仍然只買能力圈內、看得懂的好公司。"
    elif val_p < 42:
        vlean, vlight = "估值偏貴、忍住等待", "red"
        vline = "現在是別人貪婪的時候——這派寧可抱著現金等，也不用貴的價格買好公司。"
    else:
        vlean, vlight = "等更好的價格、留現金", "amber"
        vline = "價格不上不下，這派會把清單列好、想買的價位算好，然後耐心等它來。"
    val_bits = []
    if tw_val:
        val_bits.append("台股估值 %s" % _disp(tw_val))
    if dd_tw:
        val_bits.append("台股距高點 %s" % _disp(dd_tw))
    if dd_us:
        val_bits.append("美股距高點 %s" % _disp(dd_us))
    out.append({
        "name": "價值派", "school": "基本面選股／安全邊際",
        "principles": "能力圈內・護城河・安全邊際・逆向布局・耐心等便宜・長期持有・不追高",
        "lean": vlean, "lean_light": vlight,
        "take": ("看的不是時機，是『價格 vs 價值』：%s（估值支柱 %.0f 分）。%s"
                 % ("、".join(val_bits) if val_bits else "估值資料本次缺漏", val_p, vline)),
    })

    # 3) 籌碼派——lean 跟著籌碼支柱走，內文引用法人/融資/台指期未平倉實際數字
    inst = _ind(indicators, "法人買賣超")
    diverg = _ind(indicators, "背離")
    if chips_p >= 58:
        clean, clight = "法人偏多、跟著站多方", "green"
        cline = "錢在進場——這派會跟著主力方向站，但融資若開始過熱就提高警覺。"
    elif chips_p < 42:
        clean, clight = "籌碼轉空、先收手", "red"
        cline = "法人在撤、散戶在接——這派的鐵律：別跟大戶對作，先退出觀望。"
    else:
        clean, clight = "多空拉鋸、看誰先出手", "amber"
        cline = "籌碼面沒有明確方向，這派會等法人連續動作再表態。"
    chips_bits = []
    if inst:
        chips_bits.append("法人 %s" % _disp(inst))
    if margin:
        chips_bits.append("融資 %s" % _disp(margin))
    tx_inst = (taifex or {}).get("foreign_net_oi")
    if tx_inst is not None:
        side = "偏多" if tx_inst > 0 else "偏空" if tx_inst < 0 else "中性"
        tx_date = (taifex or {}).get("date")
        tag = "、%s" % tx_date if tx_date else ""
        chips_bits.append("外資台指期淨未平倉 {:+,} 口（{}{}）".format(int(tx_inst), side, tag))
    tx_pcr = (taifex or {}).get("pcr_oi")
    if tx_pcr is not None:
        chips_bits.append("選擇權 P/C 未平倉比 %.2f" % tx_pcr)
    ptt_sent = _ind(indicators, "散戶情緒")
    if ptt_sent:
        chips_bits.append("PTT 散戶%s" % _disp(ptt_sent))
    div_note = ""
    if diverg and diverg.get("light") == "red":
        div_note = "⚠ 法人與散戶正在背離——歷史上通常法人是對的。"
    out.append({
        "name": "籌碼派", "school": "跟單聰明錢／籌碼流向",
        "principles": "跟主力／法人・三大法人買賣超・台指期未平倉・融資融券・量價配合・不對作大戶",
        "lean": clean, "lean_light": clight,
        "take": ("跟著錢走：%s（籌碼支柱 %.0f 分）。%s%s"
                 % ("、".join(chips_bits) if chips_bits else "籌碼資料本次缺漏",
                    chips_p, div_note, cline)),
    })

    # 各派選股（同一個股票池、三種選法）
    pk = picks or {}
    out[0]["picks"] = pk.get("trend") or None
    out[1]["picks"] = pk.get("value") or None
    out[2]["picks"] = pk.get("chips") or None

    # 元素 0 = 摘要（頁面目前不渲染辯論；欄位保留給其他模組引用）
    band = result.get("band", "")
    cscore = ("%.0f" % comp) if comp is not None else "—"
    synthesis = ("【三派速覽】順勢派%s；價值派%s；籌碼派%s（大環境：%s）。\n"
                 "三套邏輯彼此矛盾，正解取決於你信哪一套；而被動派會說這些全是雜訊。\n"
                 "目前工具分數 %s（%s）。以上皆為策略流派框架推演、非投資建議。"
                 % (out[0]["lean"], out[1]["lean"], out[2]["lean"], env_line["lean"],
                    cscore, band))
    return [{"synthesis": synthesis, "env_line": env_line,
             "anchor_line": anchor_line}] + out

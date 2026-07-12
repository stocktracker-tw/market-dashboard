# -*- coding: utf-8 -*-
"""各資料源的抓取函式。每個函式都自帶重試與容錯，失敗回 None，不讓單一來源拖垮整體。

實測（2026-06，使用者機器）：
  - 可用：Yahoo chart、BLS CPI、US Treasury 殖利率 XML、TWSE rwd(BFI82U/MI_MARGN)、
          TWSE openapi(BWIBBU_d/FMTQIK)、TPEX 三大法人。
  - 不可用：FRED、CNN 恐懼貪婪（自建替代）、stooq（需金鑰）、景氣對策信號（來源皆為 SPA）。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional

import requests

import config as cfg


def _cache_save(name: str, obj):
    try:
        os.makedirs(cfg.DATA_DIR, exist_ok=True)
        with open(os.path.join(cfg.DATA_DIR, "cache_%s.json" % name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def _cache_load(name: str):
    """讀回上次成功抓到的值，並標記為快取（_cached=True）。失敗回 None。"""
    try:
        with open(os.path.join(cfg.DATA_DIR, "cache_%s.json" % name), "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            obj["_cached"] = True
        return obj
    except Exception:
        return None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})


def _get(url: str, *, headers: Optional[dict] = None, timeout: int = 25,
         retries: int = 3, sleep: float = 1.5) -> Optional[requests.Response]:
    """帶重試的 GET。回傳 Response 或 None。"""
    for attempt in range(retries):
        try:
            r = _session.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(sleep)
    return None


# --------------------------------------------------------------------------
# 1) Yahoo Finance：日線歷史
# --------------------------------------------------------------------------
def yahoo_history(symbol: str, rng: str = "2y", interval: str = "1d") -> Optional[Dict]:
    """回傳 {timestamps:[...], close:[...], meta:{...}}。close 可能含 None。"""
    from urllib.parse import quote
    for host in ("query1", "query2"):
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s"
               % (host, quote(symbol, safe=""), rng, interval))
        r = _get(url, retries=2)
        if not r:
            continue
        try:
            res = r.json()["chart"]["result"][0]
            quote_block = res["indicators"]["quote"][0]
            close = quote_block.get("close", []) or []
            adj = res.get("indicators", {}).get("adjclose")
            adjclose = (adj[0].get("adjclose") if adj else None) or close
            return {
                "timestamps": res.get("timestamp", []) or [],
                "open": quote_block.get("open", []) or [],     # K 線型態用（開高低）
                "high": quote_block.get("high", []) or [],
                "low": quote_block.get("low", []) or [],
                "close": close,
                "adjclose": adjclose,   # 還原權值（回測報酬用），無則退回 close
                "volume": quote_block.get("volume", []) or [],
                "meta": res.get("meta", {}),
            }
        except Exception:
            continue
    return None


def yahoo_many(symbol_map: Dict[str, str]) -> Dict[str, Dict]:
    """批次抓多個代碼。symbol_map: {yahoo_symbol: key}。回傳 {key: history}。"""
    out: Dict[str, Dict] = {}
    for sym, key in symbol_map.items():
        h = yahoo_history(sym)
        if h:
            out[key] = h
        time.sleep(0.25)  # 對 Yahoo 客氣一點
    return out


# --------------------------------------------------------------------------
# 2) BLS：美國 CPI（一般 + 核心），回傳年增率
# --------------------------------------------------------------------------
def bls_cpi(start_year: int = 2023, end_year: int = 2026) -> Optional[Dict]:
    """回傳 {headline_yoy, core_yoy, headline_series:[(ym,yoy)...], latest_month}。
    回測需要更長歷史時，傳較早的 start_year（BLS 未註冊上限 10 年/次）。"""
    d = None
    for attempt in range(3):
        try:
            r = _session.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json={"seriesid": ["CUUR0000SA0", "CUUR0000SA0L1E"],
                      "startyear": str(start_year), "endyear": str(end_year)},
                timeout=25,
            )
            dd = r.json()
            if dd.get("status") == "REQUEST_SUCCEEDED":
                d = dd
                break
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1.5)
    if d is None:
        return _cache_load("cpi")
    try:
        series = {s["seriesID"]: s["data"] for s in d["Results"]["series"]}

        def to_levels(rows):
            # rows: [{year, period 'M01'..'M12', value}] 新到舊 → 轉成 {(y,m): val}
            # 注意：BLS 偶有 value='-'（缺值）或 period='M13'（年均），都要跳過。
            lv = {}
            for it in rows:
                p = it.get("period", "")
                if not p.startswith("M") or p == "M13":
                    continue
                v = _num(it.get("value"))
                if v is None:
                    continue
                lv[(int(it["year"]), int(p[1:]))] = v
            return lv

        def yoy_series(lv):
            out = []
            for (y, m), v in sorted(lv.items()):
                prev = lv.get((y - 1, m))
                if prev:
                    out.append(("%04d-%02d" % (y, m), round((v / prev - 1) * 100, 2)))
            return out

        head_lv = to_levels(series.get("CUUR0000SA0", []))
        core_lv = to_levels(series.get("CUUR0000SA0L1E", []))
        head_yoy = yoy_series(head_lv)
        core_yoy = yoy_series(core_lv)
        if not head_yoy:
            return _cache_load("cpi")
        result = {
            "headline_yoy": head_yoy[-1][1],
            "core_yoy": core_yoy[-1][1] if core_yoy else None,
            "headline_series": head_yoy,      # 保留完整序列（回測用；儀表板自行取尾段）
            "core_series": core_yoy,
            "latest_month": head_yoy[-1][0],
        }
        _cache_save("cpi", result)
        return result
    except Exception:
        return _cache_load("cpi")


# --------------------------------------------------------------------------
# 3) US Treasury：每日殖利率曲線（10Y-2Y 利差）
# --------------------------------------------------------------------------
def ust_yield_curve(year: int = 2026) -> Optional[Dict]:
    """回傳 {date, y2, y10, spread, spread_series:[(date,spread)...]}。"""
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=%d" % year)
    r = _get(url)
    if not r:
        return _cache_load("ust")
    try:
        root = ET.fromstring(r.content)
        ns = {"a": "http://www.w3.org/2005/Atom",
              "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
              "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}
        spread_series: List = []
        y2 = y10 = None
        date = None
        for entry in root.findall("a:entry", ns):
            props = entry.find(".//m:properties", ns)
            if props is None:
                continue
            vals = {c.tag.split("}")[-1]: c.text for c in props}
            try:
                v2 = float(vals.get("BC_2YEAR"))
                v10 = float(vals.get("BC_10YEAR"))
            except (TypeError, ValueError):
                continue
            d = (vals.get("NEW_DATE") or "")[:10]
            spread_series.append((d, round(v10 - v2, 2)))
            y2, y10, date = v2, v10, d
        if y2 is None:
            return _cache_load("ust")
        result = {"date": date, "y2": y2, "y10": y10,
                  "spread": round(y10 - y2, 2), "spread_series": spread_series}
        _cache_save("ust", result)
        return result
    except Exception:
        return _cache_load("ust")


def ust_yield_curve_multi(years_back: int = 10, this_year: int = 2026) -> Optional[Dict]:
    """合併多年的 10Y-2Y 利差（回測用）。回傳同 ust_yield_curve 的結構但 spread_series 跨多年。"""
    merged = {}
    for y in range(this_year - years_back + 1, this_year + 1):
        one = ust_yield_curve(y)
        if not one:
            continue
        for d, v in one.get("spread_series", []):
            merged[d] = v
    if not merged:
        return _cache_load("ust")
    series = sorted(merged.items())
    return {"date": series[-1][0], "spread": series[-1][1],
            "spread_series": series, "y2": None, "y10": None}


# --------------------------------------------------------------------------
# 4) TWSE 上市：三大法人買賣超（需 Referer，否則回 hints 錯誤）
# --------------------------------------------------------------------------
_TWSE_REFERER = {"Referer": "https://www.twse.com.tw/zh/"}


def _num(s) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def twse_institutional(date_yyyymmdd: str) -> Optional[Dict]:
    """三大法人買賣超（單位：元）。回傳 {date, foreign, invtrust, dealer, total}。"""
    url = ("https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=%s&type=day&response=json"
           % date_yyyymmdd)
    r = _get(url, headers=_TWSE_REFERER)
    if not r:
        return None
    try:
        d = r.json()
        if d.get("stat") != "OK" or not d.get("data"):
            return None
        foreign = invtrust = dealer = total = None
        dealer_self = dealer_hedge = None
        for row in d["data"]:
            name = row[0]
            net = _num(row[3])
            if "外資及陸資(不含外資自營商)" in name or name.startswith("外資及陸資"):
                if foreign is None:
                    foreign = net
            elif name == "投信":
                invtrust = net
            elif "自營商(自行買賣)" in name:
                dealer_self = net
            elif "自營商(避險)" in name:
                dealer_hedge = net
            elif name == "合計":
                total = net
        if dealer_self is not None or dealer_hedge is not None:
            dealer = (dealer_self or 0) + (dealer_hedge or 0)
        return {"date": date_yyyymmdd, "foreign": foreign,
                "invtrust": invtrust, "dealer": dealer, "total": total}
    except Exception:
        return None


def twse_margin(date_yyyymmdd: str) -> Optional[Dict]:
    """融資融券（MI_MARGN）。回傳 {date, margin_balance(融資餘額,仟元),
    margin_prev, short_balance(融券張數), margin_buy, margin_sell}。"""
    url = ("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=%s&selectType=MS&response=json"
           % date_yyyymmdd)
    r = _get(url, headers=_TWSE_REFERER)
    if not r:
        return None
    try:
        d = r.json()
        if d.get("stat") != "OK" or not d.get("tables"):
            return None
        table = d["tables"][0]
        out = {"date": date_yyyymmdd}
        for row in table.get("data", []):
            item = row[0]
            if "融資金額" in item:   # 仟元
                out["margin_buy"] = _num(row[1])
                out["margin_sell"] = _num(row[2])
                out["margin_prev"] = _num(row[4])
                out["margin_balance"] = _num(row[5])
            elif "融券(交易單位)" in item:  # 張
                out["short_balance"] = _num(row[5])
        return out if "margin_balance" in out else None
    except Exception:
        return None


def twse_t86(date_yyyymmdd: str) -> Optional[Dict]:
    """個股三大法人買賣超（T86）。回傳 {code: {foreign, invtrust, dealer, total}}（單位：股）。"""
    url = ("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALL&response=json"
           % date_yyyymmdd)
    r = _get(url, headers=_TWSE_REFERER)
    if not r:
        return None
    try:
        d = r.json()
        if d.get("stat") != "OK" or not d.get("data"):
            return None
        out = {}
        for row in d["data"]:
            code = str(row[0]).strip()
            out[code] = {"foreign": _num(row[4]), "invtrust": _num(row[10]),
                         "dealer": _num(row[11]), "total": _num(row[18])}
        return out
    except Exception:
        return None


def twse_margin_all(date_yyyymmdd: str) -> Optional[Dict]:
    """個股融資融券彙總（MI_MARGN selectType=ALL 的第二張表）。
    回傳 {code: {margin_prev, margin_today}}（融資餘額，單位：張）。"""
    url = ("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=%s&selectType=ALL&response=json"
           % date_yyyymmdd)
    r = _get(url, headers=_TWSE_REFERER)
    if not r:
        return None
    try:
        tables = r.json().get("tables") or []
        if len(tables) < 2:
            return None
        out = {}
        for row in tables[1].get("data", []):
            code = str(row[0]).strip()
            out[code] = {"margin_prev": _num(row[5]), "margin_today": _num(row[6])}
        return out
    except Exception:
        return None


def twse_stock_valuation(code: str) -> Optional[Dict]:
    """單一個股估值（從 BWIBBU_d 濾出）。回傳 {name, close, pe, pb, yield}。"""
    r = _get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d")
    if not r:
        return None
    try:
        for it in r.json():
            if it.get("Code") == code:
                return {"name": it.get("Name"), "close": _num(it.get("ClosePrice")),
                        "pe": _num(it.get("PEratio")), "pb": _num(it.get("PBratio")),
                        "yield": _num(it.get("DividendYield"))}
        return None
    except Exception:
        return None


def twse_valuation_all() -> Optional[Dict]:
    """一次取回全部上市個股估值（給個股清單用）。
    回傳 {stocks: {code:{name,close,pe,pb,yield}}, median_pb, median_yield}。"""
    r = _get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d")
    if not r:
        return None
    try:
        out, pbs, ylds = {}, [], []
        for it in r.json():
            code = it.get("Code")
            pb = _num(it.get("PBratio")); yld = _num(it.get("DividendYield")); pe = _num(it.get("PEratio"))
            out[code] = {"name": it.get("Name"), "close": _num(it.get("ClosePrice")),
                         "pe": pe, "pb": pb, "yield": yld}
            if pb and pb > 0:
                pbs.append(pb)
            if yld and yld > 0:
                ylds.append(yld)

        def med(xs):
            if not xs:
                return None
            xs = sorted(xs); n = len(xs)
            return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

        return {"stocks": out, "median_pb": med(pbs), "median_yield": med(ylds)}
    except Exception:
        return None


def tpex_valuation_all() -> Optional[Dict]:
    """一次取回全部上櫃(OTC)個股估值，結構同 twse_valuation_all：
    {stocks:{code:{name,close,pe,pb,yield,market:'otc'}}, median_pb, median_yield}。
    估值 ← tpex_mainboard_peratio_analysis（PE/PB/殖利率），收盤價 ← tpex_mainboard_daily_close_quotes。"""
    rp = _get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis")
    if not rp:
        return _cache_load("tpexval")
    try:
        closes = {}
        rc = _get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
        if rc:
            for it in rc.json():
                c = it.get("SecuritiesCompanyCode")
                if c:
                    closes[c] = _num(it.get("Close"))
        out, pbs, ylds = {}, [], []
        for it in rp.json():
            code = it.get("SecuritiesCompanyCode")
            if not (code and code.isdigit() and len(code) == 4):
                continue
            pb = _num(it.get("PriceBookRatio")); yld = _num(it.get("YieldRatio")); pe = _num(it.get("PriceEarningRatio"))
            out[code] = {"name": it.get("CompanyName"), "close": closes.get(code),
                         "pe": pe, "pb": pb, "yield": yld, "market": "otc"}
            if pb and pb > 0:
                pbs.append(pb)
            if yld and yld > 0:
                ylds.append(yld)

        def med(xs):
            if not xs:
                return None
            xs = sorted(xs); n = len(xs)
            return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

        if not out:
            return _cache_load("tpexval")
        result = {"stocks": out, "median_pb": med(pbs), "median_yield": med(ylds)}
        _cache_save("tpexval", result)
        return result
    except Exception:
        return _cache_load("tpexval")


_INDUSTRY_NAMES = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠",
    "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊", "26": "光電", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證",
}


def twse_industry() -> Optional[Dict]:
    """上市公司產業別。回傳 {code: 產業名稱}。"""
    r = _get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L")
    if not r:
        return None
    try:
        out = {}
        for it in r.json():
            code = it.get("公司代號")
            if code:
                out[code] = _INDUSTRY_NAMES.get(it.get("產業別"), it.get("產業別") or "")
        return out
    except Exception:
        return None


def twse_valuation() -> Optional[Dict]:
    """上市個股 本益比/殖利率/股價淨值比（BWIBBU_d）。聚合成大盤中位數估值。"""
    r = _get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d")
    if not r:
        return _cache_load("twval")
    try:
        rows = r.json()
        yields, pbs, pes = [], [], []
        date = None
        for it in rows:
            date = it.get("Date") or date
            dy = _num(it.get("DividendYield"))
            pb = _num(it.get("PBratio"))
            pe = _num(it.get("PEratio"))
            if dy is not None and dy > 0:
                yields.append(dy)
            if pb is not None and pb > 0:
                pbs.append(pb)
            if pe is not None and pe > 0:
                pes.append(pe)

        def median(xs):
            if not xs:
                return None
            xs = sorted(xs)
            n = len(xs)
            return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

        if not yields or not pbs:
            return _cache_load("twval")
        result = {"date": date, "median_yield": round(median(yields), 2),
                  "median_pb": round(median(pbs), 2),
                  "median_pe": round(median(pes), 2) if pes else None,
                  "n": len(pbs)}
        _cache_save("twval", result)
        return result
    except Exception:
        return _cache_load("twval")


def twse_turnover() -> Optional[Dict]:
    """近月大盤成交統計（FMTQIK），回傳近 20 日的 {date, taiex, value, volume} 列表。"""
    r = _get("https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK")
    if not r:
        return None
    try:
        rows = r.json()
        out = []
        for it in rows:
            out.append({
                "date": it.get("Date"),                 # ROC 格式 1150529
                "taiex": _num(it.get("TAIEX")),
                "value": _num(it.get("TradeValue")),     # 成交金額(元)
                "volume": _num(it.get("TradeVolume")),
            })
        return {"rows": out} if out else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# 5) TPEX 櫃買：三大法人
# --------------------------------------------------------------------------
def ndc_business_signal() -> Optional[Dict]:
    """國發會『景氣對策信號』（dataset 6099）。分數 9-45、燈號 藍/黃藍/綠/黃紅/紅。
    下載網址每月更新，故先向 data.gov API 取得當前 ZIP 連結再下載。
    回傳 {date(YYYYMM), score, light, score_series:[(ym,score)...]}。"""
    meta = _get("https://data.gov.tw/api/v2/rest/dataset/6099")
    if not meta:
        return _cache_load("ndc")
    try:
        dists = meta.json().get("result", {}).get("distribution", [])
        zurl = next((d.get("resourceDownloadUrl") for d in dists
                     if (d.get("resourceFormat") or "").upper() == "ZIP" and d.get("resourceDownloadUrl")), None)
        if not zurl:
            return _cache_load("ndc")
        rz = _get(zurl, timeout=45)
        if not rz:
            return _cache_load("ndc")
        z = zipfile.ZipFile(io.BytesIO(rz.content))
        name = next((n for n in z.namelist() if "景氣指標與燈號" in n and not n.startswith("schema")), None)
        if not name:
            return _cache_load("ndc")
        rows = list(csv.reader(io.StringIO(z.read(name).decode("utf-8-sig"))))
        header = rows[0]
        i_date = 0
        i_score = header.index("景氣對策信號綜合分數")
        i_light = header.index("景氣對策信號")
        i_lead = header.index("領先指標不含趨勢指數") if "領先指標不含趨勢指數" in header else None
        i_coin = header.index("同時指標不含趨勢指數") if "同時指標不含趨勢指數" in header else None
        series, lead_series, coin_series, light = [], [], [], None
        for r in rows[1:]:
            if len(r) <= i_light:
                continue
            sc = _num(r[i_score])
            if sc is None:
                continue
            ym = r[i_date]
            series.append((ym, sc))
            light = r[i_light]
            if i_lead is not None:
                lv = _num(r[i_lead])
                if lv is not None:
                    lead_series.append((ym, lv))
            if i_coin is not None:
                cv = _num(r[i_coin])
                if cv is not None:
                    coin_series.append((ym, cv))
        if not series:
            return _cache_load("ndc")
        result = {"date": series[-1][0], "score": series[-1][1],
                  "light": light, "score_series": series[-36:],
                  "leading_series": lead_series[-36:], "coincident_series": coin_series[-36:]}
        _cache_save("ndc", result)
        return result
    except Exception:
        return _cache_load("ndc")


def tpex_institutional() -> Optional[Dict]:
    """櫃買三大法人。回傳 {date, foreign, invtrust, dealer, total}（單位：元）。"""
    r = _get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary")
    if not r:
        return None
    try:
        rows = r.json()
        out = {"foreign": None, "invtrust": None, "dealer": None, "total": None, "date": None}
        for it in rows:
            out["date"] = it.get("Date") or out["date"]
            inv = (it.get("Investor") or "").strip()
            net = _num(it.get("Net"))
            if inv.startswith("外資及陸資合計") or inv == "外資及陸資合計":
                out["foreign"] = net
            elif inv == "投信":
                out["invtrust"] = net
            elif inv == "自營商合計":
                out["dealer"] = net
            elif inv.startswith("三大法人"):
                out["total"] = net
        return out if out["foreign"] is not None else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# 全市場當日 OHLC（給搜尋股的輕量技術分用）＋ 重大訊息/法說會旗標
# --------------------------------------------------------------------------
def _rocdate(s) -> str:
    """民國日期(115/06/02 或 1150602) → 西元 YYYYMMDD。"""
    s = str(s or "").strip().replace("/", "")
    if len(s) >= 7 and s.isdigit():
        return "%04d%s" % (int(s[:3]) + 1911, s[3:7])
    return s


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def twse_stock_day_all() -> Dict:
    """全上市個股當日 OHLCV。{code:{open,high,low,close,vol,change,date}}（cache: stockdayall）。"""
    r = _get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    out = {}
    if r:
        try:
            for it in r.json():
                c = str(it.get("Code") or "").strip()
                if not (len(c) == 4 and c.isdigit()):
                    continue
                out[c] = {"open": _f(it.get("OpeningPrice")), "high": _f(it.get("HighestPrice")),
                          "low": _f(it.get("LowestPrice")), "close": _f(it.get("ClosingPrice")),
                          "vol": _f(it.get("TradeVolume")), "change": _f(it.get("Change")),
                          "date": _rocdate(it.get("Date"))}
        except Exception:
            out = {}
    if out:
        _cache_save("stockdayall", out)
    else:
        out = _cache_load("stockdayall") or {}
    return out


def tpex_stock_day_all() -> Dict:
    """全上櫃個股當日 OHLC。{code:{open,high,low,close,change,date}}（cache: tpexdayall）。"""
    r = _get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
    out = {}
    if r:
        try:
            for it in r.json():
                c = str(it.get("SecuritiesCompanyCode") or "").strip()
                if not (len(c) == 4 and c.isdigit()):
                    continue
                out[c] = {"open": _f(it.get("Open")), "high": _f(it.get("High")),
                          "low": _f(it.get("Low")), "close": _f(it.get("Close")),
                          "change": _f(it.get("Change")), "date": _rocdate(it.get("Date"))}
        except Exception:
            out = {}
    if out:
        _cache_save("tpexdayall", out)
    else:
        out = _cache_load("tpexdayall") or {}
    return out


def twse_announcements() -> Dict:
    """近期重大訊息（含法說會）t187ap04_L。{code:[{date,subject,conf}]}（cache: announce）。"""
    r = _get("https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
    out = {}
    if r:
        try:
            for it in r.json():
                c = str(it.get("公司代號") or "").strip()
                if not (len(c) == 4 and c.isdigit()):
                    continue
                subj = (it.get("主旨 ") or it.get("主旨") or "").strip()
                date = _rocdate(it.get("事實發生日") or it.get("發言日期") or "")
                conf = ("法人說明會" in subj) or ("法說" in subj)
                out.setdefault(c, []).append({"date": date, "subject": subj[:46], "conf": conf})
        except Exception:
            out = {}
    if out:
        _cache_save("announce", out)
    else:
        out = _cache_load("announce") or {}
    return out


# ---------------- 台指期籌碼（TAIFEX OpenAPI） ----------------
def _row_key(row, *needles):
    """在 dict 的 key 裡找同時包含所有 needle 的第一個 key（不分大小寫）。"""
    for k in row:
        kl = str(k).lower()
        if all(n.lower() in kl for n in needles):
            return k
    return None


def _row_num(v):
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def taifex_chips():
    """台指期籌碼：外資臺股期貨(TX)淨未平倉口數 + 選擇權 P/C 未平倉比。

    來源 TAIFEX OpenAPI（回 JSON）。欄位用關鍵字比對抗欄名差異；任何一段失敗
    就跳過該段。全部失敗 → 回上次快取（cache_taifex.json），再沒有 → None。
    回傳 {"date", "foreign_net_oi", "pcr_oi"}（欄位缺漏就沒有該 key）。
    """
    base = "https://openapi.taifex.com.tw/v1/"
    out = {}
    r = _get(base + "MarketDataOfMajorInstitutionalTradersDetails"
                    "OfFuturesContractsBytheDate", timeout=30)
    if r is not None:
        try:
            rows = r.json()
            ck = _row_key(rows[0], "contract") or _row_key(rows[0], "商品") or ""
            ik = (_row_key(rows[0], "item") or _row_key(rows[0], "身份")
                  or _row_key(rows[0], "institution") or "")
            dk = _row_key(rows[0], "date") or _row_key(rows[0], "日期") or "Date"
            tx = [x for x in rows
                  if "臺股期貨" in str(x.get(ck, "")) or
                  str(x.get(ck, "")).strip().upper() in ("TX", "TXF")]
            if tx:
                latest = max(str(x.get(dk, "")) for x in tx)
                for x in tx:
                    if str(x.get(dk)) != latest or "外資" not in str(x.get(ik, "")):
                        continue
                    nk = (_row_key(x, "net", "openinterest") or
                          _row_key(x, "net", "oi") or _row_key(x, "淨", "未平倉"))
                    v = _row_num(x.get(nk)) if nk else None
                    if v is not None:
                        out["foreign_net_oi"] = int(v)
                        out["date"] = latest
        except Exception:
            pass
    r = _get(base + "PutCallRatio", timeout=30)
    if r is not None:
        try:
            rows = r.json()
            dk = _row_key(rows[0], "date") or _row_key(rows[0], "日期") or "Date"
            row = max((x for x in rows if x.get(dk)), key=lambda x: str(x.get(dk)))
            ok = (_row_key(row, "oi", "ratio") or _row_key(row, "未平倉", "比")
                  or _row_key(row, "putcalloi"))
            v = _row_num(row.get(ok)) if ok else None
            if v is not None:
                out["pcr_oi"] = round(v / 100, 2) if v > 10 else v   # % → 比值
        except Exception:
            pass
    if out:
        # 與舊快取合併再存：部分成功（例如只抓到 PCR）不可洗掉先前的外資未平倉
        old = _cache_load("taifex") or {}
        old.pop("_cached", None)
        old.update(out)
        _cache_save("taifex", old)
        return old
    return _cache_load("taifex")


# ---------------- PTT Stock 散戶情緒（逆勢指標原料） ----------------
def ptt_stock_sentiment(pages: int = 10):
    """PTT Stock 板近幾頁的 [標的] 文多空比＋爆文數（散戶情緒溫度計的原料）。

    只抓公開網頁版、每天約 10 個 GET（頁間 0.3s 禮貌間隔）。實測 [標的] 文
    密度不高（4 頁常常只有 2~3 篇有方向），掃 10 頁才穩定湊滿樣本門檻。
    標題同時含多與空（如「多轉空」）視為模糊、
    不計入。全抓失敗 → 回上次快取（cache_ptt.json），再沒有 → None。
    回傳 {"bull", "bear", "hot", "total", "date"}。
    """
    base = "https://www.ptt.cc"
    url = base + "/bbs/Stock/index.html"
    bull = bear = hot = total = 0
    ok = False
    for _ in range(max(1, pages)):
        r = _get(url, headers={"Cookie": "over18=1"})
        if r is None:
            break
        html = r.text
        ok = True
        for ent in re.findall(r'<div class="r-ent">(.*?)<div class="meta">', html, re.S):
            m = re.search(r'class="title">\s*<a[^>]*>([^<]+)</a>', ent)
            if not m:                              # 刪文沒有連結
                continue
            title = m.group(1)
            total += 1
            nrec = re.search(r'class="nrec">(?:<span[^>]*>)?([^<]*)', ent)
            if nrec and (nrec.group(1) or "").strip() == "爆":
                hot += 1
            if "[標的]" in title:
                has_bull, has_bear = ("多" in title), ("空" in title)
                if has_bull and not has_bear:
                    bull += 1
                elif has_bear and not has_bull:
                    bear += 1
        pm = re.search(r'href="(/bbs/Stock/index\d+\.html)">&lsaquo; 上頁', html)
        if not pm:
            break
        url = base + pm.group(1)
        time.sleep(0.3)                            # 禮貌間隔，避免對 PTT 造成負擔
    if ok and (bull + bear) > 0:
        out = {"bull": bull, "bear": bear, "hot": hot, "total": total,
               "date": time.strftime("%Y-%m-%d")}
        _cache_save("ptt", out)
        return out
    return _cache_load("ptt")


# ---------------- Podcast 最新一集（消息頁導流盒） ----------------
def podcast_latest():
    """抓 config.PODCAST_RSS 的最新一集：{title, date, link}。

    只取標題與連結（導流、不搬運內容）。失敗回快取，再沒有回 None。
    """
    url = getattr(cfg, "PODCAST_RSS", "")
    if not url:
        return None
    r = _get(url, timeout=25)
    if r is not None:
        try:
            root = ET.fromstring(r.content)
            item = root.find("./channel/item")
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                out = {"title": title, "link": link, "date": pub[:16]}
                _cache_save("podcast", out)
                return out
        except Exception:                      # noqa: BLE001 — 解析失敗走快取
            pass
    return _cache_load("podcast")


# ---------------- Threads 關鍵字聲量 ----------------
def threads_pulse(keywords):
    """Threads 公開貼文關鍵字聲量：每個關鍵字近期貼文數（單頁上限 25，25 代表 25+）。

    token 讀 config.THREADS_TOKEN_FILE，缺檔靜默跳過；權限不足（缺
    threads_keyword_search）印一次提示。只數則數、不儲存任何貼文內容。
    失敗回快取，再沒有回 None。
    """
    tok = None
    try:
        path = getattr(cfg, "THREADS_TOKEN_FILE", "")
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
    except OSError:
        pass
    if not tok:
        return None
    out = {}
    for kw in list(keywords or [])[:4]:                    # 控制配額
        r = _get("https://graph.threads.net/v1.0/keyword_search"
                 "?q=%s&search_type=RECENT&fields=id&access_token=%s"
                 % (requests.utils.quote(kw), tok), timeout=25, retries=1)
        if r is None:
            continue
        try:
            j = r.json()
            if "error" in j:
                msg = str(j["error"].get("message", ""))[:120]
                print("  [Threads] %s：%s%s" % (kw, msg,
                      "（token 缺 threads_keyword_search 權限？）" if "permission" in msg.lower() else ""))
                continue
            out[kw] = len(j.get("data") or [])
        except Exception:                                  # noqa: BLE001
            continue
        time.sleep(0.4)
    if out:
        _cache_save("threads_pulse", out)
        return out
    return _cache_load("threads_pulse")

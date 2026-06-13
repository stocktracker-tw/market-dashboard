# -*- coding: utf-8 -*-
"""探針3：尋找 FRED / CNN 的替代來源 + 確認會用到的 Yahoo 代碼。"""
import json
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})


def test(name, url, timeout=25, kind="text", post=None):
    try:
        if post is not None:
            r = S.post(url, json=post, timeout=timeout)
        else:
            r = S.get(url, timeout=timeout)
        extra = ""
        if kind == "json":
            try:
                d = r.json()
                if isinstance(d, dict):
                    extra = " keys=" + ",".join(list(d.keys())[:8])
                else:
                    extra = " list=%d" % len(d)
            except Exception as e:
                extra = " JSON-FAIL " + str(e)[:40]
        head = r.text[:130].replace("\n", " ")
        print("[%s] %-28s %s b=%d%s" % ("OK " if r.ok else "FAIL", name, r.status_code, len(r.content), extra))
        print("       ", head)
        return r.ok
    except Exception as e:
        print("[FAIL] %-28s %s" % (name, str(e)[:80]))
        return False


print("### 美國通膨/總經 替代來源 ###")
# BLS public API (CPI series, no key for v1 limited)
test("BLS CPI v2(post)", "https://api.bls.gov/publicAPI/v2/timeseries/data/",
     kind="json", post={"seriesid": ["CUUR0000SA0"], "startyear": "2023", "endyear": "2026"})
test("BLS CPI v1(get)", "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0", kind="json")
# US Treasury daily yield curve (XML feed, all tenors incl 2Y)
test("UST yield XML", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026")
# US Treasury fiscaldata
test("UST fiscaldata", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/avg_interest_rates?page%5Bsize%5D=1", kind="json")
# DBnomics (mirrors FRED)
test("DBnomics CPIAUCSL", "https://api.db.nomics.world/v22/series/FRED/CPIAUCSL?observations=1", kind="json")
test("DBnomics M2SL", "https://api.db.nomics.world/v22/series/FRED/M2SL?observations=1", kind="json")
# stooq (Yahoo backup, CSV)
test("stooq ^spx", "https://stooq.com/q/d/l/?s=%5Espx&i=d")
test("stooq cpiyoy?", "https://stooq.com/q/d/l/?s=cpiyoy.m&i=m")

print("### 台灣 通膨/景氣 ###")
# 政府資料開放平台 - 景氣對策信號分數 (dataset id 6488 等)
test("data.gov 景氣信號", "https://data.gov.tw/api/v2/rest/dataset/6488", kind="json")
# 主計總處 CPI - 透過 NStat / 政府開放資料
test("NDC 景氣指標 json", "https://index.ndc.gov.tw/n/json/data/eco/1", kind="json")

print("### 確認會用到的 Yahoo 代碼 ###")
for sym, label in [
    ("%5ESOX", "費城半導體 SOX"), ("%5EIRX", "13週國庫券殖利率(3M)"),
    ("%5EVXN", "納指波動 VXN"), ("DX-Y.NYB", "美元指數 DXY"),
    ("GC=F", "黃金"), ("HG=F", "銅"), ("CL=F", "原油"),
    ("HYG", "高收益債ETF"), ("TIP", "抗通膨債ETF"), ("IEF", "7-10年公債ETF"),
    ("TWD=X", "美元兌台幣"), ("0050.TW", "元大台灣50"),
]:
    test("Yahoo " + label, "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5d&interval=1d" % sym, kind="json")

print("done")

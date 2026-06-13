# -*- coding: utf-8 -*-
"""探針2：用 requests（自帶 certifi）重測 SSL 失敗與逾時的來源。"""
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})


def test(name, url, timeout=30, kind="text"):
    try:
        r = S.get(url, timeout=timeout)
        head = r.text[:140].replace("\n", " ")
        extra = ""
        if kind == "json":
            try:
                d = r.json()
                extra = " keys=" + ",".join(list(d.keys())[:6]) if isinstance(d, dict) else " list=%d" % len(d)
            except Exception as e:
                extra = " JSON-FAIL " + str(e)[:50]
        print("[%s] %-26s status=%s bytes=%d%s" % ("OK " if r.ok else "FAIL", name, r.status_code, len(r.content), extra))
        print("        head:", head)
        return r.ok
    except Exception as e:
        print("[FAIL] %-26s %s" % (name, str(e)[:90]))
        return False


# FRED via requests
test("FRED CPI", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL")
test("FRED 10Y-2Y", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y")
# alt FRED host
test("FRED API alt", "https://api.stlouisfed.org/fred/series?series_id=CPIAUCSL")

# CNN
test("CNN FearGreed", "https://production.dataviz.cnn.com/index/fearandgreed/graphdata", kind="json")

# TWSE openapi
test("TWSE BFI82U(openapi)", "https://openapi.twse.com.tw/v1/fund/BFI82U", kind="json")
test("TWSE MI_MARGN(openapi)", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", kind="json")
test("TWSE BWIBBU(openapi)", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d", kind="json")
# TWSE rwd history
test("TWSE rwd BFI82U", "https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=20260529&type=day&response=json", kind="json")
test("TWSE rwd MI_MARGN", "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260529&selectType=MS&response=json", kind="json")
# TPEX 櫃買
test("TPEX openapi 三大法人", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary", kind="json")
print("done")

# -*- coding: utf-8 -*-
"""探針：測試各免費資料源在本機是否可用。只跑一次，用來決定要蓋哪些指標。"""
import json
import sys
import urllib.request
import urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def get(url, headers=None, timeout=20):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def test(name, url, headers=None, kind="text", expect=None):
    try:
        status, body = get(url, headers=headers)
        n = len(body)
        head = body[:120].decode("utf-8", "replace").replace("\n", " ")
        ok = status == 200 and n > 0
        extra = ""
        if kind == "json":
            try:
                data = json.loads(body)
                extra = " JSON-OK keys=" + ",".join(list(data.keys())[:6]) if isinstance(data, dict) else " JSON-OK list len=%d" % len(data)
            except Exception as e:
                ok = False
                extra = " JSON-FAIL " + str(e)[:60]
        print("[%s] %-22s status=%s bytes=%d%s\n        head: %s" % ("OK " if ok else "FAIL", name, status, n, extra, head))
        return ok
    except urllib.error.HTTPError as e:
        print("[FAIL] %-22s HTTPError %s" % (name, e.code))
    except Exception as e:
        print("[FAIL] %-22s %s" % (name, str(e)[:80]))
    return False


print("=" * 70)
print("Python", sys.version)
print("=" * 70)

# 1. FRED (no key, csv)
test("FRED CPI csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL")
test("FRED 10Y-2Y", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y")

# 2. Yahoo chart
test("Yahoo ^VIX q1", "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1y&interval=1d", kind="json")
test("Yahoo ^TWII q1", "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=1y&interval=1d", kind="json")
test("Yahoo ^GSPC q2", "https://query2.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1y&interval=1d", kind="json")

# 3. CNN Fear & Greed
test("CNN FearGreed", "https://production.dataviz.cnn.com/index/fearandgreed/graphdata",
     headers={"Accept": "application/json"}, kind="json")

# 4. TWSE openapi (latest snapshot)
test("TWSE 三大法人 BFI82U", "https://openapi.twse.com.tw/v1/fund/BFI82U", kind="json")
test("TWSE 融資融券 margin", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", kind="json")
test("TWSE 大盤估值 BWIBBU", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d", kind="json")
test("TWSE 成交統計 FMTQIK", "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK", kind="json")

# 5. TWSE rwd (history by date)
test("TWSE rwd BFI82U", "https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=20260529&type=day&response=json", kind="json")
test("TWSE rwd MI_MARGN", "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260529&selectType=MS&response=json", kind="json")

print("=" * 70)
print("done")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓台灣期交所(TAIFEX)台指期籌碼，寫到 repo 根目錄的 taifex.json。

只用標準函式庫（urllib），優先打 TAIFEX OpenAPI（回 JSON，比 Big5 CSV 穩）：
  • 選擇權 Put/Call Ratio（未平倉比）→ 市場多空情緒
  • 三大法人「臺股期貨(TX)」淨未平倉口數、外資淨未平倉 → 籌碼多空

設計重點（因為開發環境連不到外網，真正執行在 GitHub Actions）：
  - 欄位用「關鍵字比對」抓，盡量抗 API 欄名差異。
  - 任何一段抓失敗就跳過該段，並保留 taifex.json 既有的上次good值，
    絕不把整份資料洗成空（patch_site 端也會「資料無效就不顯示卡片」）。
  - 大量 print 診斷，方便從 Actions log 校正。
"""
import json
import os
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "taifex.json")
TZ = timezone(timedelta(hours=8))  # 台北時間

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OPENAPI = "https://openapi.taifex.com.tw/v1/"

# 三大法人期貨端點：名稱不完全確定，依序嘗試，哪個回得出「臺股期貨」就用哪個。
INST_ENDPOINTS = [
    "MarketDataOfMajorInstitutionsByFuturesContractsDate",
    "MarketDataOfMajorInstitutionsTradersFutures",
    "MarketDataOfMajorInstitutionsByGeneralFuturesContracts",
]
PCR_ENDPOINT = "PutCallRatio"


def get_json(url, timeout=30):
    """GET 並解析 JSON；失敗回 None（印出原因）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8-sig", "replace")
        data = json.loads(raw)
        print(f"  [OK] {url}  ({len(raw)} bytes, "
              f"{len(data) if isinstance(data, list) else 'obj'} rows)")
        return data
    except Exception as e:  # noqa: BLE001 — 任何錯都當抓失敗
        print(f"  [FAIL] {url}  -> {type(e).__name__}: {e}")
        return None


def to_num(v):
    """把 '12,345' / '1.23' / '' 轉成 float；不行回 None。"""
    if v is None:
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_key(row, *needles):
    """在 dict 的 key 裡找包含所有 needle 的第一個 key（不分大小寫）。"""
    for k in row:
        kl = str(k).lower()
        if all(n.lower() in kl for n in needles):
            return k
    return None


def fetch_pcr():
    """選擇權 Put/Call 未平倉比（最新一日）。"""
    print("· PCR（選擇權 Put/Call）")
    data = get_json(OPENAPI + PCR_ENDPOINT)
    if not isinstance(data, list) or not data:
        return None
    # 找日期最大的那筆
    dkey = find_key(data[0], "date") or "Date"
    rows = [r for r in data if r.get(dkey)]
    if not rows:
        return None
    row = max(rows, key=lambda r: str(r.get(dkey)))
    oi_key = (find_key(row, "oi", "ratio") or find_key(row, "未平倉", "比")
              or find_key(row, "putcalloi"))
    vol_key = (find_key(row, "volume", "ratio") or find_key(row, "成交", "比")
               or find_key(row, "putcallvolume"))
    pcr_oi = to_num(row.get(oi_key)) if oi_key else None
    pcr_vol = to_num(row.get(vol_key)) if vol_key else None
    # TAIFEX 回的是「比率%」(例 189.66 = put/call 未平倉比 1.90)，>10 視為百分比轉成比值
    if pcr_oi is not None and pcr_oi > 10:
        pcr_oi = round(pcr_oi / 100, 2)
    if pcr_vol is not None and pcr_vol > 10:
        pcr_vol = round(pcr_vol / 100, 2)
    print(f"    date={row.get(dkey)} pcr_oi={pcr_oi} pcr_vol={pcr_vol} "
          f"(oi_key={oi_key})")
    if pcr_oi is None and pcr_vol is None:
        print(f"    [警告] 抓不到比率欄位，row keys={list(row.keys())}")
        return None
    return {"date": str(row.get(dkey)), "pcr_oi": pcr_oi, "pcr_vol": pcr_vol}


def fetch_inst():
    """三大法人臺股期貨(TX)淨未平倉：三大法人合計 + 外資。"""
    print("· 三大法人臺股期貨未平倉")
    data = None
    for ep in INST_ENDPOINTS:
        data = get_json(OPENAPI + ep)
        if isinstance(data, list) and data:
            print(f"    使用端點：{ep}")
            break
    if not isinstance(data, list) or not data:
        return None
    sample = data[0]
    ckey = (find_key(sample, "contract") or find_key(sample, "商品")
            or find_key(sample, "name"))
    ikey = (find_key(sample, "institution") or find_key(sample, "身份")
            or find_key(sample, "identity") or find_key(sample, "investors"))
    dkey = find_key(sample, "date") or "Date"
    net_key = (find_key(sample, "net", "oi") or find_key(sample, "淨", "未平倉")
               or find_key(sample, "openinterest", "net"))
    if not (ckey and net_key):
        print(f"    [警告] 找不到 商品/淨未平倉 欄位；keys={list(sample.keys())}")
        return None
    # 只留臺股期貨（TX，排除小型/微型臺指 MTX/TMF；用名稱含「臺股期貨」判斷）
    def is_tx(r):
        nm = str(r.get(ckey, ""))
        return ("臺股期貨" in nm) or nm.strip().upper() in ("TX", "TXF")
    tx = [r for r in data if is_tx(r)]
    if not tx:
        # 後援：包含「臺指」但不含「小型/微型」
        tx = [r for r in data if "臺指" in str(r.get(ckey, ""))
              and "小型" not in str(r.get(ckey, ""))
              and "微型" not in str(r.get(ckey, ""))]
    if not tx:
        print(f"    [警告] 找不到臺股期貨資料；商品樣本="
              f"{sorted({str(r.get(ckey)) for r in data})[:8]}")
        return None
    latest_date = max(str(r.get(dkey)) for r in tx if r.get(dkey))
    tx = [r for r in tx if str(r.get(dkey)) == latest_date]
    total_net = 0.0
    foreign_net = None
    for r in tx:
        n = to_num(r.get(net_key))
        if n is None:
            continue
        total_net += n
        ident = str(r.get(ikey, "")) if ikey else ""
        if ("外資" in ident) or ("foreign" in ident.lower()):
            foreign_net = n
    print(f"    date={latest_date} 三大法人淨未平倉={total_net:.0f} "
          f"外資淨未平倉={foreign_net}")
    return {"date": latest_date, "inst_net_oi": round(total_net),
            "foreign_net_oi": round(foreign_net) if foreign_net is not None
            else None}


SWAGGER_URLS = [
    "https://openapi.taifex.com.tw/swagger/v1/swagger.json",
    "https://openapi.taifex.com.tw/swagger.json",
    "https://openapi.taifex.com.tw/openapi.json",
    "https://openapi.taifex.com.tw/v1/swagger.json",
]


def discover():
    """抓 OpenAPI 的 swagger 目錄，印出所有端點路徑（找正確的三大法人端點用）。"""
    print("· 探索 OpenAPI 端點清單（找三大法人正確端點）")
    for u in SWAGGER_URLS:
        d = get_json(u)
        if isinstance(d, dict) and isinstance(d.get("paths"), dict):
            paths = sorted(d["paths"].keys())
            print(f"    共 {len(paths)} 個端點：")
            for p in paths:
                print("      ", p)
            return
    print("    （swagger 目錄抓不到）")


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def main():
    print(f"=== fetch_taifex @ {datetime.now(TZ):%Y-%m-%d %H:%M} 台北 ===")
    out = load_existing()
    out.setdefault("_source", "TAIFEX OpenAPI")

    pcr = fetch_pcr()
    if pcr:
        out["pcr"] = pcr
    inst = fetch_inst()
    if inst:
        out["inst"] = inst
    else:
        discover()  # 三大法人抓不到 → 印出端點清單，方便校正

    out["updated"] = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    got = [k for k in ("pcr", "inst") if out.get(k)]
    print(f"--- 取得：{got or '（無，保留上次資料）'} ---")
    if not got and "pcr" not in load_existing() and "inst" not in load_existing():
        # 從沒成功過也沒舊資料 → 不寫空檔，讓 patch 端略過
        print("沒有任何資料且無歷史，跳過寫檔。")
        return 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已寫入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

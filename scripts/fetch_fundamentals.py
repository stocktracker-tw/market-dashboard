#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓個股的成交量、營收成長、董監持股，寫到 repo 根目錄的 fundamentals.json。

universe.json（引擎產出）只有環境／籌碼／估值／技術四項，這三樣完全沒有：
  • 交易量  → 成交金額、成交股數（流動性；分數再高買不進去也沒用）
  • 潛力    → 月營收年增率、累計營收年增率（成長性）
  • 經理人持有 → 董監事持股比例（內部人有沒有把身家押在上面）

設計重點與 fetch_taifex.py 相同：開發環境連不到台灣的財經站台（沙箱擋掉
openapi.twse.com.tw），真正執行在 GitHub Actions。所以：
  - 端點「用關鍵字從 swagger 目錄挑」，不寫死猜來的路徑。
  - 欄位也用關鍵字比對，抗欄名差異。
  - 任何一段失敗就跳過該段，保留 fundamentals.json 既有的上次好資料，
    絕不把整份洗成空。
  - 大量 print：第一次跑完要能從 Actions log 讀出真正的端點與欄名，
    再回頭把 CANDIDATES 收斂。在那之前這份資料「不上站」，
    patch_site 不讀它——先確認資料是對的，再談要不要進分數。
"""
import json
import os
import re
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "fundamentals.json")
TZ = timezone(timedelta(hours=8))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://openapi.twse.com.tw/v1"
SWAGGER = [
    "https://openapi.twse.com.tw/swagger/v1/swagger.json",
    "https://openapi.twse.com.tw/swagger.json",
]

# 每一項要找的端點：(名稱, 路徑/摘要要命中的關鍵字, 已知的優先路徑)
# 優先路徑是「若目錄裡有就直接用」，沒有才退回關鍵字搜尋——兩條路都留著，
# 因為我沒辦法在本機驗證這些路徑到底存不存在。
WANT = [
    ("volume", ["STOCK_DAY_ALL", "每日收盤行情", "daily trading", "個股日成交"],
     "/exchangeReport/STOCK_DAY_ALL"),
    ("revenue", ["t187ap05", "月營業收入", "營業收入彙總", "monthly revenue"],
     "/opendata/t187ap05_L"),
    ("insider", ["董事", "監察人", "持股", "shareholding", "t187ap11"],
     None),
]

# 欄位關鍵字：抓到第一個命中的鍵就用它
FIELDS = {
    "code": ["公司代號", "證券代號", "股票代號", "Code"],
    "amount": ["成交金額", "TradeValue", "成交值"],
    "shares": ["成交股數", "TradeVolume", "成交量"],
    "yoy": ["營業收入-去年同月增減(%)", "去年同月增減", "營收年增", "YoY"],
    "cum_yoy": ["累計營業收入-前期比較增減(%)", "累計營業收入", "前期比較增減", "累計增減"],
    "hold": ["持股比例", "持股比率", "全體董事持股", "董監持股", "Shareholding"],
}


def get_json(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            raw = r.read().decode("utf-8-sig", "replace")
        data = json.loads(raw)
        n = len(data) if isinstance(data, list) else "obj"
        print(f"  [OK]   {url}  ({len(raw)} bytes, {n} rows)")
        return data
    except Exception as e:                  # noqa: BLE001 — 任何錯都當抓失敗
        print(f"  [FAIL] {url}  -> {type(e).__name__}: {e}")
        return None


def to_num(v):
    if v is None:
        return None
    s = re.sub(r"[,%\s]", "", str(v))
    if s in ("", "-", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick(row, names):
    """從 row 裡找第一個「鍵名含有任一關鍵字」的值。"""
    for want in names:
        for k in row:
            if want.lower() in str(k).lower():
                return row[k]
    return None


def catalogue():
    """抓 swagger 目錄並整份印出來——第一次跑完要靠這段校正端點名稱。"""
    for u in SWAGGER:
        d = get_json(u)
        if not isinstance(d, dict):
            continue
        paths = d.get("paths") or {}
        print(f"  目錄共 {len(paths)} 個端點：")
        out = {}
        for p, spec in sorted(paths.items()):
            try:
                summary = (spec.get("get") or {}).get("summary") or ""
            except Exception:               # noqa: BLE001
                summary = ""
            out[p] = summary
            print(f"    {p}  —  {summary}")
        return out
    return {}


def resolve(cat, keys, prefer):
    """從目錄挑端點：優先用已知路徑，否則關鍵字比對路徑或摘要。"""
    if prefer and (not cat or prefer in cat):
        return prefer
    for p, summary in (cat or {}).items():
        hay = (p + " " + summary).lower()
        if any(k.lower() in hay for k in keys):
            return p
    return prefer                            # 目錄拿不到就死馬當活馬醫


def collect(cat, name, keys, prefer):
    path = resolve(cat, keys, prefer)
    if not path:
        print(f"  [SKIP] {name}：目錄裡找不到對應端點")
        return None, None
    url = BASE + path if path.startswith("/") else BASE + "/" + path
    rows = get_json(url)
    if not isinstance(rows, list) or not rows:
        return None, path
    print(f"  {name} 用的端點：{path}")
    print(f"  {name} 第一列的欄位：{list(rows[0].keys())}")
    print(f"  {name} 第一列樣本：{json.dumps(rows[0], ensure_ascii=False)[:400]}")
    return rows, path


def main():
    print("== 抓個股基本面（成交量／營收成長／董監持股）==")
    print("-- swagger 目錄 --")
    cat = catalogue()

    data, used = {}, {}
    for name, keys, prefer in WANT:
        print(f"-- {name} --")
        rows, path = collect(cat, name, keys, prefer)
        used[name] = path
        if not rows:
            continue
        hit = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            code = str(pick(r, FIELDS["code"]) or "").strip()
            if not re.fullmatch(r"\d{4,6}", code):
                continue
            slot = data.setdefault(code, {})
            if name == "volume":
                for key, names in (("amt", "amount"), ("shr", "shares")):
                    v = to_num(pick(r, FIELDS[names]))
                    if v is not None:
                        slot[key] = v
            elif name == "revenue":
                for key, names in (("yoy", "yoy"), ("cyoy", "cum_yoy")):
                    v = to_num(pick(r, FIELDS[names]))
                    if v is not None:
                        slot[key] = v
            elif name == "insider":
                v = to_num(pick(r, FIELDS["hold"]))
                if v is not None:
                    slot["hold"] = v
            hit += 1
        print(f"  {name}：解析到 {hit} 檔")

    # 覆蓋率沒到最低標就當這一段沒抓到，保留上次的好資料（絕不洗成空）
    cover = {k: sum(1 for v in data.values() if k in v)
             for k in ("amt", "shr", "yoy", "cyoy", "hold")}
    print(f"-- 覆蓋率 -- {cover}")

    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:                    # noqa: BLE001
            prev = {}
    prev_rows = prev.get("rows") or {}
    for code, slot in prev_rows.items():
        keep = {k: v for k, v in slot.items() if cover.get(k, 0) < 200}
        if keep:
            data.setdefault(code, {}).update(
                {k: v for k, v in keep.items() if k not in data.get(code, {})})

    out = {
        "_source": "TWSE OpenAPI",
        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "endpoints": used,
        "coverage": cover,
        "rows": data,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"寫出 {OUT}：{len(data)} 檔")
    # 抽樣印幾檔知名股，方便從 log 直接看資料合不合理
    for c in ("2330", "2317", "2454", "2412"):
        print(f"  {c}: {json.dumps(data.get(c, {}), ensure_ascii=False)}")


if __name__ == "__main__":
    main()

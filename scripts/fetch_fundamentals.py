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

# 加總超過在外流通股數代表有重複計算（法人董事與其代表人可能各列一次），
# 這兩檔拿來看原始結構：2412 中華電第一次算出 317%，2330 台積電 6.63% 看起來對。
DEBUG_CODES = {"2412", "2330"}
DEBUG_ROWS = {}
# 每家公司「每個持有人只算一次」：{公司代號: {姓名: 該人最大持股}}
INSIDER = {}

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
    # 第一次跑用關鍵字挑，「持股」誤中 /fund/MI_QFIIS_cat（外資持股比率，
    # 產業別 36 列），解析到 0 檔。目錄裡正確的是 t187ap11_L。
    ("insider", ["t187ap11", "董監事持股餘額"], "/opendata/t187ap11_L"),
    # 董監持股要換算成比例才有可比性，需要在外流通股數
    ("shares_out", ["t187ap03_L", "上市公司基本資料"], "/opendata/t187ap03_L"),
]

# 欄位關鍵字：抓到第一個命中的鍵就用它
FIELDS = {
    "code": ["公司代號", "證券代號", "股票代號", "Code"],
    "amount": ["成交金額", "TradeValue", "成交值"],
    "shares": ["成交股數", "TradeVolume", "成交量"],
    "yoy": ["營業收入-去年同月增減(%)", "去年同月增減", "營收年增", "YoY"],
    "cum_yoy": ["累計營業收入-前期比較增減(%)", "累計營業收入", "前期比較增減", "累計增減"],
    # t187ap11_L 是「每位董監一列」的明細，要自己按公司加總
    "hold": ["目前持股", "持有股數", "現持股數", "持股張數", "股份"],
    "outstanding": ["已發行普通股數", "發行股數", "普通股股數", "實收資本額"],
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
                # 明細是一位董監一列，但法人董事的持股會在「每一位法人代表人」
                # 旁邊重複列一次。實測中華電：交通部 2,737,718,976 股出現 9 次，
                # 直接加總得到 246 億股，是在外流通 77.6 億股的 3.2 倍。
                # 所以按「姓名」去重，同一個持有人只算一次（取最大值）。
                v = to_num(pick(r, FIELDS["hold"]))
                who = str(pick(r, ["姓名"]) or "").strip()
                if v is not None and who:
                    seen = INSIDER.setdefault(code, {})
                    if v > seen.get(who, -1):
                        seen[who] = v
                if code in DEBUG_CODES:
                    DEBUG_ROWS.setdefault(code, []).append(
                        (str(pick(r, ["職稱"]) or ""), str(pick(r, ["姓名"]) or ""), v))
            elif name == "shares_out":
                v = to_num(pick(r, FIELDS["outstanding"]))
                if v is not None:
                    slot["out_sh"] = v
            hit += 1
        print(f"  {name}：解析到 {hit} 檔")

    # 董監持股換算成佔在外流通股數的比例（兩邊都有才算，單位不合就會很離譜，
    # 所以下面會印出來讓人看；合理範圍大約 0~80%）
    # 去重後才加總
    for code, seen in INSIDER.items():
        data.setdefault(code, {})["hold_sh"] = sum(seen.values())

    over = 0
    for slot in data.values():
        h, o = slot.get("hold_sh"), slot.get("out_sh")
        if h and o and o > 0:
            pct = h / o * 100
            # 持股不可能超過在外流通股數。超過就是重複計算，寧可留白也不寫錯的
            if 0 <= pct <= 100:
                slot["hold"] = round(pct, 2)
            else:
                over += 1
    print(f"-- 董監持股 -- 比例超出 0~100 而捨棄的：{over} 檔")

    # 覆蓋率沒到最低標就當這一段沒抓到，保留上次的好資料（絕不洗成空）
    cover = {k: sum(1 for v in data.values() if k in v)
             for k in ("amt", "shr", "yoy", "cyoy", "hold_sh", "out_sh", "hold")}
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
    for c, rows_ in DEBUG_ROWS.items():
        raw = sum(v or 0 for _, _, v in rows_)
        ded = sum(INSIDER.get(c, {}).values())
        out = data.get(c, {}).get("out_sh", 0) or 1
        print(f"  [debug] {c} 共 {len(rows_)} 列 / 去重後 {len(INSIDER.get(c, {}))} 人　"
              f"去重前 {raw:,.0f}（{raw / out * 100:.1f}%）→ "
              f"去重後 {ded:,.0f}（{ded / out * 100:.1f}%）")
    holds = sorted(v["hold"] for v in data.values() if "hold" in v)
    if holds:
        print(f"  董監持股% 分布：最小 {holds[0]:.2f}　中位 "
              f"{holds[len(holds) // 2]:.2f}　最大 {holds[-1]:.2f}"
              f"（合理應落在 0~80，超出代表單位對不上）")


if __name__ == "__main__":
    main()

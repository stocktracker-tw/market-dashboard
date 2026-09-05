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
# 1336 台翰是上櫃、董監持股算出來 291%（超過 100 被擋掉的 323 檔之一）。
# 上市那批用同樣的手法找出「法人董事在每位代表人旁邊各列一次」，這次看上櫃。
DEBUG_CODES = {"2412", "2330", "1336"}
FIELDNAMES = {}                 # 各來源第一列的欄位名，留到最後才印， 免得被 swagger 目錄洗掉
DEBUG_ROWS = {}
# 每家公司「每個持有人只算一次」：{公司代號: {姓名: 該人最大持股}}
INSIDER = {}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "fundamentals.json")


def universe_codes():
    """只收站台真的會顯示的代號。櫃買端點一天回 10963 列（含 ETF、特別股…），
    TWSE 的 _P 端點又含興櫃／未上市公發公司——全收的話檔案會從 1254 筆漲到
    12081 筆，多出來的一萬筆全是沒有任何數值的空殼，白白灌大要下載的檔案。"""
    try:
        with open(os.path.join(ROOT, "universe.json"), encoding="utf-8") as f:
            return {r["c"] for r in json.load(f) if r.get("c")}
    except Exception:                        # noqa: BLE001 — 讀不到就不設限
        return None


CODES = None
TZ = timezone(timedelta(hours=8))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://openapi.twse.com.tw/v1"
SWAGGER = [
    "https://openapi.twse.com.tw/swagger/v1/swagger.json",
    "https://openapi.twse.com.tw/swagger.json",
]
# 上櫃（otc）佔 universe 的 886/1967 檔，TWSE 的 _L 端點完全不涵蓋，
# 第一版跑出來 otc 覆蓋率是 0%。兩條補法：
#   1. TWSE 自己的 _P 端點是「公開發行公司」，可能含上櫃 → 先試，成本近乎零
#   2. 成交量只能找櫃買中心（TPEX）自己的 OpenAPI
TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"
TPEX_SWAGGER = [
    "https://www.tpex.org.tw/openapi/swagger.json",
    "https://www.tpex.org.tw/openapi/v1/swagger.json",
    "https://www.tpex.org.tw/openapi/swagger/v1/swagger.json",
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

# 補上櫃用：同一個 TWSE API 的「公開發行公司」版本。已經有值的不覆蓋，
# 只填空缺——上市的數字以 _L 為準。
WANT_FILL = [
    ("revenue", ["t187ap05_P", "公開發行公司每月營業收入"], "/opendata/t187ap05_P"),
    ("insider", ["t187ap11_P", "公發公司董監事持股"], "/opendata/t187ap11_P"),
    ("shares_out", ["t187ap03_P", "公開發行公司基本資料"], "/opendata/t187ap03_P"),
]

# 上櫃每日成交：只有櫃買中心有。端點名稱同樣用關鍵字從它的目錄挑。
WANT_TPEX = [
    ("volume", ["daily_close_quotes", "mainboard", "每日收盤行情", "上櫃股票"],
     "/tpex_mainboard_daily_close_quotes"),
    # 上櫃的月營收與董監持股在 TWSE 的 _P 端點裡沒有（實測 otc 0/886），
    # 這裡試櫃買自己有沒有。關鍵字收緊：上一次「持股」兩個字誤中「外資及陸資
    # 投資類股持股比率表」，白跑一輪。找不到就跳過，不會亂抓一個來充數。
    ("revenue", ["monthly_revenue", "月營業收入", "月營收"], None),
    ("insider", ["董監事持股", "internal_holding", "內部人持股"], None),
    # 上一輪漏了這條：董監股數抓到了 886/886，卻沒有在外流通股數可以換算成
    # 比例，所以 otc 的 hold 還是 0/886。營收那條解出來是 mopsfin_t187ap05_O，
    # 基本資料照同一個命名應該是 _t187ap03_O。
    ("shares_out", ["mopsfin_t187ap03_O", "公司基本資料", "基本資料"], None),
]

# 欄位關鍵字：抓到第一個命中的鍵就用它
FIELDS = {
    "code": ["公司代號", "證券代號", "股票代號", "Code"],
    # 櫃買的欄名跟證交所不一樣（TransactionAmount / TradingShares），
    # 第一次跑因此抓到 10523 檔卻一個數字都沒填，只留下滿地空殼。
    "amount": ["成交金額", "TradeValue", "成交值", "TransactionAmount"],
    "shares": ["成交股數", "TradeVolume", "成交量", "TradingShares"],
    "yoy": ["營業收入-去年同月增減(%)", "去年同月增減", "營收年增", "YoY"],
    "cum_yoy": ["累計營業收入-前期比較增減(%)", "累計營業收入", "前期比較增減", "累計增減"],
    # t187ap11_L 是「每位董監一列」的明細，要自己按公司加總
    "hold": ["目前持股", "持有股數", "現持股數", "持股張數", "股份"],
    "outstanding": ["已發行普通股數", "發行股數", "普通股股數", "實收資本額"],
    "capital": ["Capitals"],                # 櫃買行情表自帶的資本額
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


def catalogue(urls=None, quiet=False):
    """抓 swagger 目錄並印出來——要靠這段校正端點名稱。"""
    for u in (urls or SWAGGER):
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
            if not quiet:
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


def collect(cat, name, keys, prefer, base=BASE):
    path = resolve(cat, keys, prefer)
    if not path:
        print(f"  [SKIP] {name}：目錄裡找不到對應端點")
        return None, None
    url = base + path if path.startswith("/") else base + "/" + path
    rows = get_json(url)
    if not isinstance(rows, list) or not rows:
        return None, path
    print(f"  {name} 用的端點：{path}")
    FIELDNAMES[name + (" @" + path)] = list(rows[0].keys())
    print(f"  {name} 第一列的欄位：{list(rows[0].keys())}")
    print(f"  {name} 第一列樣本：{json.dumps(rows[0], ensure_ascii=False)[:400]}")
    return rows, path


def _put(slot, key, v, fill_only):
    """fill_only 時只補空缺——上市的數字以 _L 端點為準，公發版只拿來補上櫃。"""
    if v is not None and not (fill_only and key in slot):
        slot[key] = v


def _ingest_rows(name, rows, data, fill_only=False):
    """把一組資料列塞進 data，回傳解析到的檔數。"""
    hit = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = str(pick(r, FIELDS["code"]) or "").strip()
        if not re.fullmatch(r"\d{4,6}", code):
            continue
        if CODES is not None and code not in CODES:
            continue
        slot = data.setdefault(code, {})
        if name == "volume":
            for key, names in (("amt", "amount"), ("shr", "shares")):
                _put(slot, key, to_num(pick(r, FIELDS[names])), fill_only)
            # 櫃買行情表自帶資本額，留著當在外流通股數的備援（見下面 main()）
            _put(slot, "cap", to_num(pick(r, FIELDS["capital"])), fill_only)
        elif name == "revenue":
            for key, names in (("yoy", "yoy"), ("cyoy", "cum_yoy")):
                _put(slot, key, to_num(pick(r, FIELDS[names])), fill_only)
        elif name == "insider":
            # 明細是一位董監一列，但法人董事的持股會在「每一位法人代表人」
            # 旁邊重複列一次。實測中華電：交通部 2,737,718,976 股出現 9 次，
            # 直接加總得到 246 億股，是在外流通 77.6 億股的 3.2 倍。
            # 所以按「姓名」去重，同一個持有人只算一次（取最大值）。
            # fill_only 時已經有這家公司就跳過，免得兩份名單混在一起
            if fill_only and code in INSIDER:
                hit += 1
                continue
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
            _put(slot, "out_sh", to_num(pick(r, FIELDS["outstanding"])), fill_only)
        hit += 1
    return hit


def main():
    global CODES
    CODES = universe_codes()
    print("== 抓個股基本面（成交量／營收成長／董監持股）==")
    print(f"只收 universe 裡的 {len(CODES) if CODES else '（全部）'} 個代號")
    print("-- swagger 目錄 --")
    cat = catalogue()

    data, used = {}, {}

    def ingest(want, cat_, base, tag, fill_only=False):
        """把一組端點的資料塞進 data。fill_only＝只補空缺，不覆蓋既有值。"""
        for name, keys, prefer in want:
            print(f"-- {name}{tag} --")
            rows, path = collect(cat_, name, keys, prefer, base)
            used[name + tag] = path
            if not rows:
                continue
            hit = _ingest_rows(name, rows, data, fill_only)
            print(f"  {name}{tag}：解析到 {hit} 檔")

    ingest(WANT, cat, BASE, "")
    print("-- 補上櫃：TWSE 公開發行公司版端點 --")
    ingest(WANT_FILL, cat, BASE, "(公發)", fill_only=True)
    print("-- 補上櫃：櫃買中心 OpenAPI --")
    tcat = catalogue(TPEX_SWAGGER, quiet=False)
    ingest(WANT_TPEX, tcat, TPEX_BASE, "(櫃買)", fill_only=True)

    # 董監持股換算成佔在外流通股數的比例（兩邊都有才算，單位不合就會很離譜，
    # 所以下面會印出來讓人看；合理範圍大約 0~80%）
    # 去重後才加總
    for code, seen in INSIDER.items():
        data.setdefault(code, {})["hold_sh"] = sum(seen.values())

    # 還是沒有在外流通股數的，用資本額 ÷ 面額 10 回推（台股絕大多數面額 10 元）。
    # 面額不是 10 的會算錯，但下面 0~100% 的合理性檢查會把它擋掉。
    derived = 0
    for slot in data.values():
        if not slot.get("out_sh") and slot.get("cap"):
            slot["out_sh"] = slot["cap"] / 10.0
            derived += 1
    if derived:
        print(f"-- 在外流通股數 -- 用資本額÷10 回推的：{derived} 檔")

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
    # 按市場別分開看——上櫃佔 universe 的 45%，補了沒有要一眼看得出來
    try:
        with open(os.path.join(ROOT, "universe.json"), encoding="utf-8") as uf:
            mkt = {r["c"]: r.get("m") for r in json.load(uf)}
        for m in ("tse", "otc"):
            codes = [c for c, v in mkt.items() if v == m]
            line = "　".join(
                "%s %d/%d(%.0f%%)" % (k, n, len(codes), 100.0 * n / max(1, len(codes)))
                for k in ("amt", "yoy", "hold")
                for n in [sum(1 for c in codes if k in data.get(c, {}))])
            print(f"-- 覆蓋率({m}) -- {line}")
    except Exception as e:                  # noqa: BLE001 — 只是診斷輸出
        print(f"-- 覆蓋率(分市場) -- 算不出來：{e}")
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

    # 一個數值都沒有的空殼不要寫進檔案
    data = {c: v for c, v in data.items() if v}

    out = {
        "_source": "TWSE + TPEX OpenAPI",
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
    print("-- 各來源的欄位名（再印一次，方便從 log 尾巴看）--")
    for k, v in FIELDNAMES.items():
        print(f"  {k}: {v}")
    if "1336" in DEBUG_ROWS:
        print("-- 上櫃 1336 的董監明細（前 18 列）--")
        for job, who, v in DEBUG_ROWS["1336"][:18]:
            print(f"    {str(job):<22} {str(who):<22} "
                  + (f"{v:>14,.0f}" if v is not None else "          (無)"))
        uniq = INSIDER.get("1336", {})
        print(f"    共 {len(DEBUG_ROWS['1336'])} 列 / 去重後 {len(uniq)} 人，"
              f"加總 {sum(uniq.values()):,.0f}，"
              f"在外流通 {data.get('1336', {}).get('out_sh', 0):,.0f}")
    holds = sorted(v["hold"] for v in data.values() if "hold" in v)
    if holds:
        print(f"  董監持股% 分布：最小 {holds[0]:.2f}　中位 "
              f"{holds[len(holds) // 2]:.2f}　最大 {holds[-1]:.2f}"
              f"（合理應落在 0~80，超出代表單位對不上）")


if __name__ == "__main__":
    main()

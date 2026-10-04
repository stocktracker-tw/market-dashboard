#!/usr/bin/env python3
"""全市場「退場分數」：給持有者看的，趨勢轉弱／跌破均線／高檔回落／籌碼惡化的程度。

公式逐字搬自引擎 stock.py 的 _stock_exit（推薦卡上的「離場訊號 急迫度」），
所以同一檔股票在這裡和推薦卡上算出來的分數一致。0–100，越高代表轉弱訊號越多。

為什麼在 Actions 算、不在引擎算：自選清單存在使用者手機的 localStorage，伺服器
不知道誰持有哪一檔，只能全市場都算。引擎在 PC 上只留約 90 個交易日的全市場收盤，
算不出 200 日均線與 52 週高點；這裡自己維護一年份的收盤：
  • 歷史檔放在 Actions 快取（.cache/px_hist.json），不進 git；
  • 每天用交易所開放資料（TWSE STOCK_DAY_ALL、TPEx 上櫃日收盤，引擎同一組端點）補當天；
  • 歷史不夠 200 天的股票用 Yahoo 日線一次補近兩年（只留 300 天）（快取掉了也會自己補回來，有時間上限，
    補不完下次接著補）。
籌碼那一項（法人近 5 日賣超＋散戶融資增加）直接讀引擎產出的 universe.json。

輸出 exit.json（給 stocks.html 用）：
  {"asof": "YYYYMMDD", "rows": {"2330": [分數, 50日均, 旗標, 距20日高%, 距52週高%,
                                         5日前RSI, 現在RSI, 歷史天數], ...}}
旗標每一位代表一個訊號，文字在頁面上組，免得 JSON 裡塞 2000 份中文句子。

抓不到任何新資料時不改寫 exit.json（保留上一份），絕不讓頁面開天窗。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, ".cache", "px_hist.json")
OUT = os.path.join(ROOT, "exit.json")
UNIVERSE = os.path.join(ROOT, "universe.json")
KEEP = 300                 # 保留的交易日數（200 日均線＋52 週高點要 252，多留一點給 RSI 收斂）
MIN_DAYS = 60              # 引擎同一門檻：不足 60 天不給分
FULL_DAYS = 252            # 少於這個天數的股票會被排進 Yahoo 回補
UA = {"User-Agent": "Mozilla/5.0 (stocktracker-tw exit scores)"}

# 旗標（頁面依此組文字；順序與引擎訊號一致）
F_BELOW50, F_NEAR50, F_BELOW200, F_BEAR, F_HIGHFALL, F_RSIFADE, F_DD52, F_CHIPS = (
    1, 2, 4, 8, 16, 32, 64, 128)


# ---------------- 與引擎 analytics.py 相同的計算（逐字搬過來） ----------------
def clean(series):
    out = []
    for v in series:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:
            continue
        out.append(f)
    return out


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def sma(series, window):
    c = clean(series)
    if len(c) < window or window <= 0:
        return None
    return sum(c[-window:]) / window


def rsi(series, window=14):
    c = clean(series)
    if len(c) < window + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, window + 1):
        d = c[i] - c[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / window
    avg_loss = losses / window
    for i in range(window + 1, len(c)):
        d = c[i] - c[i - 1]
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def drawdown_from_high(series, window=252):
    c = clean(series)
    if len(c) < 2:
        return None
    win = c[-window:] if window else c
    peak = max(win)
    if peak == 0:
        return None
    return c[-1] / peak - 1.0


def dist_from_ma(series, window):
    c = clean(series)
    ma = sma(c, window)
    if ma is None or ma == 0 or not c:
        return None
    return c[-1] / ma - 1.0


def exit_score(close, net5=0, margin_chg=None):
    """引擎 stock._stock_exit 的同一套規則；多回傳旗標與數字給頁面組文字。"""
    if len(close) < MIN_DAYS:
        return None
    price = close[-1]
    ma50 = sma(close, 50)
    ma200 = sma(close, 200)
    rsi_now = rsi(close)
    rsi_prev = rsi(close[:-5]) if len(close) > 20 else None
    dist200 = dist_from_ma(close, 200)
    hi20 = max(close[-20:])
    dd20 = price / hi20 - 1 if hi20 else 0
    dd52 = drawdown_from_high(close, 252) or 0
    score, flags = 0, 0
    if ma50 and price < ma50:
        score += 35; flags |= F_BELOW50
    elif ma50 and price < ma50 * 1.015:
        score += 15; flags |= F_NEAR50
    if ma200 and price < ma200:
        score += 18; flags |= F_BELOW200
    elif ma50 and ma200 and ma50 < ma200:
        score += 8; flags |= F_BEAR
    if dist200 is not None and dist200 > 0.15 and dd20 < -0.06:
        score += 15; flags |= F_HIGHFALL
    if rsi_now is not None and rsi_prev is not None and rsi_prev > 70 and rsi_now < rsi_prev - 5:
        score += 12; flags |= F_RSIFADE
    if dd52 < -0.20:
        score += 15; flags |= F_DD52
    if net5 < 0 and margin_chg is not None and margin_chg > 0:
        score += 10; flags |= F_CHIPS
    score = int(clamp(score, 0, 100))
    return {"score": score, "flags": flags, "ma50": ma50, "dd20": dd20, "dd52": dd52,
            "rsi_prev": rsi_prev, "rsi_now": rsi_now}


# ---------------- 資料 ----------------
def fetch_json(url, timeout=30, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                       # noqa: BLE001 — 重試後交給呼叫端
            err = e
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    raise err


def num(x):
    try:
        v = float(str(x).replace(",", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def rocdate(s):
    s = str(s or "").strip().replace("/", "")
    if len(s) >= 7 and s.isdigit():
        return "%04d%s" % (int(s[:3]) + 1911, s[3:7])
    return s if len(s) == 8 and s.isdigit() else ""


def today_twse():
    """{code: (YYYYMMDD, close)}：上市（STOCK_DAY_ALL，與引擎同端點）。"""
    out = {}
    for it in fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"):
        c, px, d = str(it.get("Code") or "").strip(), num(it.get("ClosingPrice")), rocdate(it.get("Date"))
        if len(c) == 4 and c.isdigit() and px and d:
            out[c] = (d, px)
    return out


def today_tpex():
    """{code: (YYYYMMDD, close)}：上櫃（與引擎同端點）。"""
    out = {}
    for it in fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"):
        c, px, d = (str(it.get("SecuritiesCompanyCode") or "").strip(), num(it.get("Close")),
                    rocdate(it.get("Date")))
        if len(c) == 4 and c.isdigit() and px and d:
            out[c] = (d, px)
    return out


def yahoo_year(code, market):
    """[(YYYYMMDD, close), ...]，近兩年日線。上市 .TW、上櫃 .TWO，抓不到換另一個後綴試。"""
    sufs = (".TWO", ".TW") if market == "otc" else (".TW", ".TWO")
    for suf in sufs:
        for host in ("query1", "query2"):
            url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s%s?range=2y&interval=1d"
                   % (host, code, suf))
            try:
                res = fetch_json(url, timeout=20, retries=1)["chart"]["result"][0]
                ts = res.get("timestamp") or []
                cl = (res["indicators"]["quote"][0].get("close") or [])
                rows = []
                for t, c in zip(ts, cl, strict=False):
                    if c is None or c != c or c <= 0:
                        continue
                    # 台股收盤時間換算成台北日期（UTC+8）
                    d = datetime.fromtimestamp(t + 8 * 3600, tz=timezone.utc).strftime("%Y%m%d")
                    rows.append((d, round(float(c), 4)))
                if rows:
                    return rows
            except Exception:                        # noqa: BLE001 — 換下一個 host／後綴
                continue
    return []


def merge(hist, code, rows):
    """把 [(date, close)] 併進 hist[code]，同日以新的為準，依日期排序、只留 KEEP 天。"""
    cur = dict(hist.get(code) or [])
    for d, c in rows:
        cur[d] = c
    hist[code] = sorted(cur.items())[-KEEP:]


def parse_chips(cd):
    """從 universe 的 cd 欄（引擎產出）取法人近 5 日買賣超方向與融資變化。
    例：「法人近5日 -1234 張　融資 +1.2%（散戶加碼）」。取不到就回 (0, None)＝不計這項。"""
    net5, mchg = 0, None
    m = re.search(r"法人近5日\s*([+-]?\d+(?:\.\d+)?)\s*張", cd or "")
    if m:
        net5 = float(m.group(1))
    m = re.search(r"融資\s*([+-]?\d+(?:\.\d+)?)%", cd or "")
    if m:
        mchg = float(m.group(1)) / 100
    return net5, mchg


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                # noqa: BLE001
        return default


def build(universe, hist):
    """{code: row}，只收 universe 裡有、歷史夠 60 天的。"""
    rows, asof = {}, ""
    for x in universe:
        code = x.get("c")
        seq = hist.get(code) or []
        if len(seq) < MIN_DAYS:
            continue
        net5, mchg = parse_chips(x.get("cd"))
        r = exit_score([c for _, c in seq], net5, mchg)
        if not r:
            continue
        asof = max(asof, seq[-1][0])
        rnd = lambda v, k=1: None if v is None else round(v, k)   # noqa: E731
        rows[code] = [r["score"], rnd(r["ma50"], 2), r["flags"], rnd(r["dd20"] * 100),
                      rnd(r["dd52"] * 100), rnd(r["rsi_prev"]), rnd(r["rsi_now"]), len(seq)]
    return rows, asof


def main():
    dry = "--dry-run" in sys.argv
    budget = float(os.environ.get("EXIT_BACKFILL_SECONDS", "1500"))
    universe = load(UNIVERSE, [])
    if not universe:
        print("::warning::讀不到 universe.json，略過")
        return 0
    hist = load(HIST, {})
    print("歷史快取：%d 檔" % len(hist))

    # 1) 今天的收盤（兩個市場各一次請求）
    got, days = 0, {}
    for name, fn in (("上市", today_twse), ("上櫃", today_tpex)):
        try:
            day = fn()
        except Exception as e:                       # noqa: BLE001
            print("::warning::%s當日收盤抓不到：%s" % (name, str(e)[:120]))
            continue
        days.update(day)
        for code, (d, px) in day.items():
            merge(hist, code, [(d, px)])
        got += len(day)
        print("%s當日收盤：%d 檔（%s）" % (name, len(day), next(iter(day.values()))[0] if day else "-"))

    # 2) 歷史不夠的、或落後最新交易日的用 Yahoo 補；有時間上限，補不完下次接著補。
    #    「落後」那條是給某個市場的當日資料抓失敗時用的：實測 TPEx 開放資料（4.6 MB）
    #    在 Actions 上會被中途切斷，沒有這條的話上櫃股的分數會一直停在舊的那天。
    newest = max((d for d, _ in days.values()), default="")
    def behind(code):
        seq = hist.get(code) or []
        return len(seq) < FULL_DAYS or (newest and seq[-1][0] < newest)
    need = [x for x in universe if behind(x["c"])]
    t0, filled, failed = time.time(), 0, 0
    for x in need:
        if time.time() - t0 > budget:
            break
        rows = yahoo_year(x["c"], x.get("m"))
        if rows:
            merge(hist, x["c"], rows)
            filled += 1
        else:
            failed += 1
        time.sleep(0.2)
    # Yahoo 的最後一根可能跟交易所同一天：以交易所的正式收盤為準
    for code, (d, px) in days.items():
        merge(hist, code, [(d, px)])
    left = len(need) - filled - failed
    print("Yahoo 回補：需要 %d 檔、補到 %d、失敗 %d、時間到沒輪到 %d（%.0f 秒）"
          % (len(need), filled, failed, left, time.time() - t0))

    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, separators=(",", ":"))

    rows, asof = build(universe, hist)
    full = sum(1 for r in rows.values() if r[7] >= FULL_DAYS)
    dist = [0, 0, 0]
    for r in rows.values():
        dist[0 if r[0] < 30 else 1 if r[0] < 55 else 2] += 1
    print("退場分數：%d／%d 檔（滿一年歷史 %d 檔），資料日 %s；<30：%d、30–54：%d、≥55：%d"
          % (len(rows), len(universe), full, asof or "-", *dist))
    for code in ("2330", "2317", "2454"):
        if code in rows:
            print("  %s → %s" % (code, rows[code]))

    if not rows:
        print("::warning::一檔都算不出來，保留上一份 exit.json")
        return 0
    if not got and not filled:
        print("::warning::今天沒有任何新資料，保留上一份 exit.json")
        return 0
    data = {"asof": asof, "rows": rows}
    old = load(OUT, None)
    if old == data:
        print("exit.json 無變更")
        return 0
    if dry:
        print("（dry-run：不寫 exit.json）")
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print("已寫入 exit.json（%d KB）" % (os.path.getsize(OUT) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""純 Python 計算工具（不依賴 numpy/pandas），給指標模組使用。

所有函式都對「含 None、長度不足」的真實資料保持容錯：算不出來就回傳 None，
讓上層指標自己決定要不要顯示。
"""
from __future__ import annotations

from typing import List, Optional, Sequence


def clean(series: Sequence[Optional[float]]) -> List[float]:
    """去掉 None / NaN，保留順序。"""
    out: List[float] = []
    for v in series:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        out.append(f)
    return out


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def last(series: Sequence[Optional[float]]) -> Optional[float]:
    c = clean(series)
    return c[-1] if c else None


def sma(series: Sequence[Optional[float]], window: int) -> Optional[float]:
    c = clean(series)
    if len(c) < window or window <= 0:
        return None
    return sum(c[-window:]) / window


def ema(series: Sequence[Optional[float]], window: int) -> Optional[float]:
    c = clean(series)
    if len(c) < window or window <= 0:
        return None
    k = 2.0 / (window + 1)
    e = sum(c[:window]) / window  # seed with SMA
    for v in c[window:]:
        e = v * k + e * (1 - k)
    return e


def rsi(series: Sequence[Optional[float]], window: int = 14) -> Optional[float]:
    """Wilder's RSI。回傳 0-100。"""
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


def pct_change(series: Sequence[Optional[float]], periods: int) -> Optional[float]:
    """最後一筆相對 `periods` 期前的變動率（小數，0.05 = +5%）。"""
    c = clean(series)
    if len(c) <= periods or periods <= 0:
        return None
    prev = c[-1 - periods]
    if prev == 0:
        return None
    return c[-1] / prev - 1.0


def zscore(series: Sequence[Optional[float]], window: Optional[int] = None) -> Optional[float]:
    c = clean(series)
    if window:
        c = c[-window:]
    n = len(c)
    if n < 5:
        return None
    mean = sum(c) / n
    var = sum((x - mean) ** 2 for x in c) / n
    sd = var ** 0.5
    if sd == 0:
        return 0.0
    return (c[-1] - mean) / sd


def percentile_rank(value: Optional[float], series: Sequence[Optional[float]],
                    window: Optional[int] = None) -> Optional[float]:
    """value 在 series 中的百分位（0-100）。100 = 比歷史所有值都高。"""
    if value is None:
        return None
    c = clean(series)
    if window:
        c = c[-window:]
    if len(c) < 10:
        return None
    below = sum(1 for x in c if x <= value)
    return 100.0 * below / len(c)


def drawdown_from_high(series: Sequence[Optional[float]], window: int = 252) -> Optional[float]:
    """距區間最高點的回檔幅度（負數小數，-0.12 = 從高點跌 12%）。"""
    c = clean(series)
    if len(c) < 2:
        return None
    win = c[-window:] if window else c
    peak = max(win)
    if peak == 0:
        return None
    return c[-1] / peak - 1.0


def dist_from_ma(series: Sequence[Optional[float]], window: int) -> Optional[float]:
    """現價相對 N 日均線的乖離（小數，0.08 = 高於均線 8%）。"""
    c = clean(series)
    ma = sma(c, window)
    if ma is None or ma == 0 or not c:
        return None
    return c[-1] / ma - 1.0


def linmap(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """線性映射並夾在 [y0,y1]（自動處理 y0>y1 的反向映射）。"""
    if x1 == x0:
        return (y0 + y1) / 2
    t = (x - x0) / (x1 - x0)
    t = clamp(t, 0.0, 1.0)
    return y0 + t * (y1 - y0)


def piecewise(x: float, points: Sequence[Sequence[float]]) -> float:
    """以 (x, y) 控制點做分段線性內插。points 需依 x 遞增排序。

    例：piecewise(vix, [(12,25),(20,60),(35,95)])
    """
    pts = list(points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        if x <= x1:
            return linmap(x, x0, x1, y0, y1)
    return pts[-1][1]


# =====================================================================
# 趨勢結構 / 技術指標（給 A 長期趨勢、C 技術面用）
# =====================================================================
def sma_series(series: Sequence[Optional[float]], window: int) -> List[float]:
    """逐日 SMA 序列（長度 = len(clean) - window + 1）。資料不足回 []。"""
    c = clean(series)
    if len(c) < window or window <= 0:
        return []
    out = []
    s = sum(c[:window])
    out.append(s / window)
    for i in range(window, len(c)):
        s += c[i] - c[i - window]
        out.append(s / window)
    return out


def ema_series(series: Sequence[Optional[float]], window: int) -> List[float]:
    """逐日 EMA 序列（seed 用 SMA）。資料不足回 []。"""
    c = clean(series)
    if len(c) < window or window <= 0:
        return []
    k = 2.0 / (window + 1)
    e = sum(c[:window]) / window
    out = [e]
    for v in c[window:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def ma_slope(series: Sequence[Optional[float]], window: int, lookback: int = 20) -> Optional[float]:
    """N 日均線最近 lookback 日的斜率，正規化成『每日 % 變化』。
    回傳小數（0.001 = 均線每日上彎 0.1%）。資料不足回 None。"""
    ms = sma_series(series, window)
    if len(ms) <= lookback:
        return None
    old = ms[-1 - lookback]
    if old == 0:
        return None
    return (ms[-1] / old - 1.0) / lookback


def ma_alignment(series: Sequence[Optional[float]],
                 windows: Sequence[int] = (20, 60, 120, 240)) -> Optional[float]:
    """多均線排列分數，回傳 -1~+1。+1 = 完美多頭排列(短>中>長)，-1 = 完美空頭。
    以相鄰均線對的順序比例計算；資料長度不足的均線會被略過。"""
    mas = []
    for w in windows:
        m = sma(series, w)
        if m is not None:
            mas.append(m)
    if len(mas) < 2:
        return None
    bull = bear = 0
    for i in range(len(mas) - 1):
        if mas[i] > mas[i + 1]:
            bull += 1
        elif mas[i] < mas[i + 1]:
            bear += 1
    tot = len(mas) - 1
    return (bull - bear) / tot


def cross(series: Sequence[Optional[float]], fast_w: int, slow_w: int,
          lookback: int = 20) -> tuple:
    """偵測黃金/死亡交叉。回傳 (kind, days_ago)，kind ∈ {'golden','death',None}。"""
    f = sma_series(series, fast_w)
    s = sma_series(series, slow_w)
    if not f or not s:
        return (None, None)
    n = min(len(f), len(s))
    f = f[-n:]
    s = s[-n:]
    diff = [f[i] - s[i] for i in range(n)]
    look = min(lookback, n - 1)
    for back in range(1, look + 1):
        a = diff[-1 - back]
        b = diff[-back]
        if a <= 0 < b:
            return ("golden", back)
        if a >= 0 > b:
            return ("death", back)
    return (None, None)


def macd(series: Sequence[Optional[float]], fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple:
    """回傳 (macd_line, signal_line, hist) 最後值；資料不足回 (None,None,None)。"""
    ef = ema_series(series, fast)
    es = ema_series(series, slow)
    if not ef or not es:
        return (None, None, None)
    n = min(len(ef), len(es))
    macd_line = [ef[-n + i] - es[-n + i] for i in range(n)]
    if len(macd_line) < signal:
        return (macd_line[-1], None, None)
    sig_series = ema_series(macd_line, signal)
    if not sig_series:
        return (macd_line[-1], None, None)
    sig = sig_series[-1]
    return (macd_line[-1], sig, macd_line[-1] - sig)


def bollinger_pctb(series: Sequence[Optional[float]], window: int = 20,
                   k: float = 2.0) -> Optional[float]:
    """%b：價格在布林通道的位置。0=下軌、0.5=中軌、1=上軌、>1 突破上軌、<0 跌破下軌。"""
    c = clean(series)
    if len(c) < window:
        return None
    win = c[-window:]
    mean = sum(win) / window
    var = sum((x - mean) ** 2 for x in win) / window
    sd = var ** 0.5
    if sd == 0:
        return 0.5
    upper = mean + k * sd
    lower = mean - k * sd
    return (c[-1] - lower) / (upper - lower)


def _ohlc_rows(open_=None, high=None, low=None, close=None, volume=None) -> List[dict]:
    """把平行的 OHLCV 序列依索引對齊成 rows，丟掉任一欄為 None/NaN 的列。"""
    seqs = [("o", open_), ("h", high), ("l", low), ("c", close), ("v", volume)]
    present = [s for _, s in seqs if s is not None]
    if not present:
        return []
    n = min(len(s) for s in present)
    rows = []
    for i in range(n):
        row = {}
        ok = True
        for name, seq in seqs:
            if seq is None:
                continue
            val = seq[i] if i < len(seq) else None
            if val is None or (isinstance(val, float) and val != val):
                ok = False
                break
            row[name] = float(val)
        if ok:
            rows.append(row)
    return rows


def atr(high, low, close, window: int = 14) -> Optional[float]:
    """平均真實波幅（與價格同單位）。需要對齊的 high/low/close。"""
    rows = _ohlc_rows(high=high, low=low, close=close)
    if len(rows) < window + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["h"], rows[i]["l"], rows[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < window:
        return None
    a = sum(trs[:window]) / window
    for tr in trs[window:]:
        a = (a * (window - 1) + tr) / window
    return a


def candle_read(open_, high, low, close, volume=None) -> Optional[dict]:
    """讀最新一根 K 棒的型態特徵（紅黑、影線、跳空、爆量、創新高低）。"""
    rows = _ohlc_rows(open_=open_, high=high, low=low, close=close, volume=volume)
    if len(rows) < 2:
        return None
    cur, prev = rows[-1], rows[-2]
    o, h, l, c = cur["o"], cur["h"], cur["l"], cur["c"]
    rng = h - l
    body = abs(c - o)
    up_sh = h - max(o, c)
    lo_sh = min(o, c) - l
    out = {
        "bull": c >= o,
        "body_ratio": (body / rng) if rng else 0.0,
        "upper_ratio": (up_sh / rng) if rng else 0.0,
        "lower_ratio": (lo_sh / rng) if rng else 0.0,
        "gap": (o / prev["c"] - 1.0) if prev["c"] else 0.0,
        "chg": (c / prev["c"] - 1.0) if prev["c"] else 0.0,
    }
    if volume is not None and len(rows) >= 21 and "v" in cur:
        vols = [r["v"] for r in rows[-21:-1] if "v" in r]
        avg = sum(vols) / len(vols) if vols else 0
        out["vol_ratio"] = (cur["v"] / avg) if avg else 1.0
    closes = [r["c"] for r in rows]
    out["new_high20"] = c >= max(closes[-20:]) if len(closes) >= 20 else False
    out["new_low20"] = c <= min(closes[-20:]) if len(closes) >= 20 else False
    out["long_lower"] = out["lower_ratio"] >= 0.5 and out["body_ratio"] <= 0.35
    out["long_upper"] = out["upper_ratio"] >= 0.5 and out["body_ratio"] <= 0.35
    return out

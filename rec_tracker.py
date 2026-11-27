# -*- coding: utf-8 -*-
"""
個股推薦追蹤 & 歷史模擬回測。

① save_today(recs) ─ 每次 main.py 跑完把推薦股存進 data/rec_history.csv
② update_returns()  ─ 對已存的推薦補填「N 日後報酬」
③ simulate_history(shared, env, universe) ─ 用 Yahoo 歷史資料模擬過去 1 年
   若當時分數偏高(以今日 lite 分為 proxy)能拿多少報酬
④ render_page(...)  ─ 輸出 output/rec_backtest.html
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import time
from typing import Dict, List, Optional

import analytics as A
import config as cfg
import sources as src

REC_CSV = os.path.join(cfg.DATA_DIR, "rec_history.csv")
REC_SUMMARY_JSON = os.path.join(cfg.DATA_DIR, "rec_summary.json")
BENCH = "0050.TW"          # 基準：元大台灣50
HORIZONS = [10, 20, 60]   # 追蹤 N 個交易日後的報酬（約 2 週、1 個月、3 個月）
FIELDNAMES = ["date", "code", "name", "score", "close", "themes",
              "ret10", "ret20", "ret60",
              "bench10", "bench20", "bench60",
              "mom20", "m6_1", "vol", "rk"]   # 入榜原因（2026-11 起記錄，供日後診斷）


# ─────────────── ① 存今日推薦 ───────────────
def _fmt(v):
    return "%.4f" % v if isinstance(v, (int, float)) else ""


def save_today(recs: List[Dict]) -> int:
    """把今日推薦存入 CSV（已存過同日就跳過）。回傳新增筆數。"""
    if not recs:
        return 0
    if dt.date.today().weekday() >= 5:
        return 0   # 週末資料仍是週五的，存了只會灌重複樣本
    today = dt.date.today().isoformat()
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    existing = set()
    if os.path.exists(REC_CSV):
        with open(REC_CSV, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            old_rows = list(rd)
            header = rd.fieldnames or []
        for row in old_rows:
            if row.get("date") == today:
                existing.add(row.get("code"))
        if header and header != FIELDNAMES:   # 欄位升級：整檔改寫成新表頭，舊列新欄留空
            with open(REC_CSV, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                w.writeheader()
                w.writerows(old_rows)
    new_rows = [r for r in recs if r["code"] not in existing]
    if not new_rows:
        return 0
    write_header = not os.path.exists(REC_CSV) or os.path.getsize(REC_CSV) == 0
    with open(REC_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in new_rows:
            w.writerow({"date": today, "code": r["code"], "name": r.get("name", ""),
                        "score": round(r.get("score", 0), 1),
                        "close": r.get("price") or r.get("close") or "",
                        "themes": "/".join(r.get("themes", []) or []),
                        "ret10": "", "ret20": "", "ret60": "",
                        "bench10": "", "bench20": "", "bench60": "",
                        "mom20": _fmt(r.get("mom20")), "m6_1": _fmt(r.get("m6_1")),
                        "vol": _fmt(r.get("vol")), "rk": _fmt(r.get("_rk"))})
    return len(new_rows)


# ─────────────── ② 補填報酬 ───────────────
# 同一次執行內的 Yahoo 歷史快取：同一檔被推薦多天時只抓一次
_SERIES_CACHE: Dict[str, List] = {}


def _series(symbols: List[str]) -> List:
    """回傳 [(date, price), ...]（依序 symbols 試到有資料為止）。
    日期與價格成對過濾 None，避免 A.clean 單獨刪值造成日期錯位。
    價格優先用還原權值 adjclose（報酬含除息），無則退回 close。"""
    key = symbols[0]
    if key in _SERIES_CACHE:
        return _SERIES_CACHE[key]
    out: List = []
    for sym in symbols:
        h = src.yahoo_history(sym, rng="1y")
        time.sleep(0.2)  # 只在真的打 Yahoo 時才等
        if not h:
            continue
        ts = h.get("timestamps") or []
        px = h.get("adjclose") or h.get("close") or []
        for t, v in zip(ts, px):
            if v is None or v != v or not t:
                continue
            try:
                out.append((dt.date.fromtimestamp(t), float(v)))
            except Exception:
                continue
        if out:
            break
    _SERIES_CACHE[key] = out
    return out


def _ret_after(series: List, start_date: dt.date, n_days: int) -> Optional[float]:
    """start_date 當天（或之後第一個交易日）買進、第 n_days 個交易日後的報酬。
    交易日還不夠 n_days 時回傳 None（之後再補），不拿半途價格充數。"""
    idx_start = next((i for i, (d, _) in enumerate(series) if d >= start_date), None)
    if idx_start is None or idx_start + n_days >= len(series):
        return None
    p0 = series[idx_start][1]
    pe = series[idx_start + n_days][1]
    return (pe - p0) / p0 if p0 else None


def _price_after(code: str, start_date: str, n_days: int) -> Optional[float]:
    """（相容舊介面）code 在 start_date 後第 n_days 個交易日的報酬。"""
    try:
        start = dt.date.fromisoformat(start_date)
    except Exception:
        return None
    return _ret_after(_series([code + ".TW", code + ".TWO"]), start, n_days)


def update_returns() -> int:
    """補填 rec_history.csv 中尚未計算報酬的列。回傳更新筆數。"""
    if not os.path.exists(REC_CSV):
        return 0
    with open(REC_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    updated = 0
    today = dt.date.today()

    for row in rows:
        d_str = row.get("date", "")
        code = row.get("code", "")
        if not d_str or not code:
            continue
        try:
            rec_date = dt.date.fromisoformat(d_str)
        except Exception:
            continue
        # 只處理「已過 n 個交易日（粗估 n*1.4 日曆天）且還沒填」的欄位
        due = [n for n in HORIZONS
               if (not row.get("ret%d" % n) or not row.get("bench%d" % n))
               and (today - rec_date).days >= n * 1.4]
        if not due:
            continue
        changed = False
        for n in due:
            key, bkey = "ret%d" % n, "bench%d" % n
            if not row.get(key):
                ret = _ret_after(_series([code + ".TW", code + ".TWO"]), rec_date, n)
                if ret is not None:
                    row[key] = "%.4f" % ret
                    changed = True
            if not row.get(bkey):
                br = _ret_after(_series([BENCH]), rec_date, n)
                if br is not None:
                    row[bkey] = "%.4f" % br
                    changed = True
        if changed:
            updated += 1

    if updated:
        with open(REC_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return updated


# ─────────────── ③ 歷史模擬 ───────────────
def simulate_history(universe: List[Dict], n_sim: int = 30) -> Dict:
    """
    歷史模擬：對今日 universe 裡分數最高的 n_sim 檔，
    用 Yahoo 1y 資料模擬「若在 3 個月前 / 6 個月前 買進，今日報酬多少」。
    這是 proxy 模擬（今日分數 ≠ 過去分數），誠實標注偏差說明。
    """
    if not universe:
        return {}
    bench_closes = [p for _, p in _series([BENCH])]

    def bench_ret_from(n_ago_days):
        if not bench_closes or len(bench_closes) < n_ago_days:
            return None
        idx = max(0, len(bench_closes) - n_ago_days)
        p0, pe = bench_closes[idx], bench_closes[-1]
        return (pe - p0) / p0 if p0 else None

    # 直接模擬傳進來的清單（推薦股），不再用 universe 前 N 名
    top = sorted(universe, key=lambda x: x.get("score", 0), reverse=True)[:n_sim]

    results = []
    for x in top:
        code = x["code"]
        closes = [p for _, p in _series([code + ".TW", code + ".TWO"])]
        if len(closes) < 10:
            continue
        row = {"code": code, "name": x.get("name", code),
               "score_today": x["score"], "themes": "/".join(x.get("themes") or []),
               "price_now": closes[-1] if closes else None}
        for label, n_ago in [("3個月前", 65), ("6個月前", 130)]:
            if len(closes) < n_ago:
                row[label] = None
                continue
            p0 = closes[max(0, len(closes) - n_ago)]
            pe = closes[-1]
            ret = (pe - p0) / p0 if p0 else None
            row[label] = ret
        results.append(row)

    br3 = bench_ret_from(65)
    br6 = bench_ret_from(130)
    wins3 = [r for r in results if r.get("3個月前") is not None]
    wins6 = [r for r in results if r.get("6個月前") is not None]
    return {"results": results, "bench3": br3, "bench6": br6,
            "avg3": (sum(r["3個月前"] for r in wins3) / len(wins3)) if wins3 else None,
            "avg6": (sum(r["6個月前"] for r in wins6) / len(wins6)) if wins6 else None,
            "win_rate3": (sum(1 for r in wins3 if (r.get("3個月前") or 0) > 0) / len(wins3)) if wins3 else None,
            "win_rate6": (sum(1 for r in wins6 if (r.get("6個月前") or 0) > 0) / len(wins6)) if wins6 else None,
            "n": len(results)}


# ─────────────── ④ 渲染 ───────────────
def render_page(sim: Dict, history_rows: List[Dict] = None, generated_at: str = "") -> str:
    from dashboard import _esc, nav, with_pwa
    from config import REFRESH_SECONDS

    def pct(v):
        if v is None:
            return "—"
        return ("%+.1f%%" % (v * 100))

    def color(v):
        if v is None:
            return ""
        return "color:#28c76f" if v >= 0 else "color:#ea5455"

    parts = ['<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">',
             '<meta http-equiv="refresh" content="%d">' % REFRESH_SECONDS,
             '<title>個股推薦回測</title></head><body>',
             nav("stocks", include_css=True),
             '<div class="wrap">',
             '<h1>📊 個股推薦回測 <span style="font-size:14px;color:var(--muted)">歷史模擬 + 即時追蹤</span></h1>',
             '<div class="muted">%s ・ 非投資建議</div>' % _esc(generated_at)]

    # 模擬摘要
    n = sim.get("n", 0)
    avg3 = sim.get("avg3"); avg6 = sim.get("avg6")
    wr3 = sim.get("win_rate3"); wr6 = sim.get("win_rate6")
    br3 = sim.get("bench3"); br6 = sim.get("bench6")
    if n:
        parts.append('<div class="section-title">歷史模擬摘要（Proxy）</div>')
        parts.append('<div class="warn" style="font-size:13px;margin-bottom:10px">⚠️ 以今日分數為 Proxy 模擬——今日高分股若「過去就高分」才算數；'
                     '實際過去分數可能不同（存倖偏差），請把這份視為「方向性參考」而非精確回測。</div>')
        parts.append('<div class="grid">')
        for label, avg, wr, br in [("模擬3個月持有", avg3, wr3, br3), ("模擬6個月持有", avg6, wr6, br6)]:
            parts.append('<div class="card"><div class="top"><div class="name">%s</div></div>' % label)
            parts.append('<div class="val" style="%s;font-size:22px">平均報酬 %s</div>' % (color(avg), pct(avg)))
            parts.append('<div class="detail">勝率 %s</div>' % (("%.0f%%" % (wr * 100)) if wr is not None else "—"))
            parts.append('<div class="detail">0050 同期 <span style="%s">%s</span></div>' % (color(br), pct(br)))
            if avg is not None and br is not None:
                alpha = avg - br
                parts.append('<div class="detail" style="%s">超額報酬(Alpha) %s</div>' % (color(alpha), pct(alpha)))
            parts.append('</div>')
        parts.append('</div>')

    # 個股明細表
    results = sim.get("results", [])
    if results:
        parts.append('<div class="section-title">個股模擬明細（今日分數≥52 的前 %d 檔）</div>' % n)
        parts.append('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">')
        parts.append('<tr style="color:var(--muted);border-bottom:1px solid var(--line)">'
                     '<th style="text-align:left;padding:6px 4px">代碼</th>'
                     '<th style="text-align:left">名稱</th>'
                     '<th style="text-align:right">今日分數</th>'
                     '<th style="text-align:right">3個月前買進</th>'
                     '<th style="text-align:right">6個月前買進</th>'
                     '<th style="text-align:left">題材</th></tr>')
        for r in sorted(results, key=lambda x: (x.get("3個月前") or -99), reverse=True):
            v3 = r.get("3個月前"); v6 = r.get("6個月前")
            parts.append('<tr style="border-bottom:1px solid rgba(255,255,255,.05)">'
                         '<td style="padding:6px 4px;font-weight:700">%s</td>'
                         '<td>%s</td>'
                         '<td style="text-align:right">%.1f</td>'
                         '<td style="text-align:right;%s">%s</td>'
                         '<td style="text-align:right;%s">%s</td>'
                         '<td style="color:var(--muted)">%s</td></tr>'
                         % (_esc(r["code"]), _esc(r["name"]), r["score_today"],
                            color(v3), pct(v3), color(v6), pct(v6),
                            _esc(r.get("themes", ""))))
        parts.append('</table></div>')

    # 即時追蹤（已存的歷史）
    filled = [row for row in (history_rows or []) if row.get("ret20")]
    if filled:
        parts.append('<div class="section-title">即時追蹤（已滿 20 個交易日的紀錄）</div>')
        parts.append('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">')
        parts.append('<tr style="color:var(--muted);border-bottom:1px solid var(--line)">'
                     '<th style="text-align:left;padding:6px 4px">推薦日</th>'
                     '<th style="text-align:left">代碼</th>'
                     '<th style="text-align:left">名稱</th>'
                     '<th style="text-align:right">分數</th>'
                     '<th style="text-align:right">20日報酬</th>'
                     '<th style="text-align:right">0050同期</th>'
                     '<th style="text-align:right">Alpha</th></tr>')
        for row in sorted(filled, key=lambda x: x.get("date",""), reverse=True)[:40]:
            r20 = float(row.get("ret20") or 0); b20 = float(row.get("bench20") or 0)
            alpha = r20 - b20
            parts.append('<tr style="border-bottom:1px solid rgba(255,255,255,.05)">'
                         '<td style="padding:6px 4px;color:var(--muted)">%s</td>'
                         '<td style="font-weight:700">%s</td>'
                         '<td>%s</td>'
                         '<td style="text-align:right">%s</td>'
                         '<td style="text-align:right;%s">%+.1f%%</td>'
                         '<td style="text-align:right;color:var(--muted)">%+.1f%%</td>'
                         '<td style="text-align:right;%s">%+.1f%%</td></tr>'
                         % (row.get("date",""), _esc(row.get("code","")), _esc(row.get("name","")),
                            row.get("score",""), color(r20), r20*100,
                            b20*100, color(alpha), alpha*100))
        parts.append('</table></div>')
    elif not filled:
        parts.append('<div class="card" style="grid-template-columns:1fr"><div class="note" style="grid-column:1/3">'
                     '⏳ 即時追蹤剛啟動（今天第一筆）。約 4 週後，滿 20 個交易日的推薦就會在這裡顯示實際報酬。'
                     '</div></div>')

    parts.append('<div class="muted" style="margin-top:16px">歷史模擬使用 Yahoo Finance 近 1 年收盤資料；'
                 '今日分數為 Proxy（實際過去分數可能不同），存倖偏差使模擬報酬偏樂觀。非投資建議。</div>')
    parts.append('</div></body></html>')
    html = with_pwa("".join(parts))
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(cfg.OUTPUT_DIR, "rec_backtest.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return "rec_backtest.html"


def load_history() -> List[Dict]:
    if not os.path.exists(REC_CSV):
        return []
    with open(REC_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_summary(sim: Dict, history_rows: List[Dict]) -> None:
    """把模擬 + 即時追蹤結果存成 JSON，供 stocks.html 直接內嵌。"""
    import json as _json
    filled20 = []
    for row in history_rows:
        if row.get("ret20"):
            try:
                r20 = float(row["ret20"]); b20 = float(row.get("bench20") or 0)
                filled20.append({"date": row.get("date",""), "code": row.get("code",""),
                                 "name": row.get("name",""), "score": row.get("score",""),
                                 "ret20": r20, "bench20": b20, "alpha20": r20-b20})
            except Exception:
                continue
    # 排序：最新在前
    filled20.sort(key=lambda x: x.get("date",""), reverse=True)
    obj = {
        "n_sim": sim.get("n", 0),
        "avg3": sim.get("avg3"), "avg6": sim.get("avg6"),
        "win_rate3": sim.get("win_rate3"), "win_rate6": sim.get("win_rate6"),
        "bench3": sim.get("bench3"), "bench6": sim.get("bench6"),
        "results": [{"code": r["code"], "name": r["name"],
                     "score": r["score_today"], "ret3m": r.get("3個月前"),
                     "ret6m": r.get("6個月前"), "themes": r.get("themes","")}
                    for r in (sim.get("results") or [])],
        "tracked": filled20[:30],
        "n_total_history": len(history_rows),
    }
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    with open(REC_SUMMARY_JSON, "w", encoding="utf-8") as f:
        _json.dump(obj, f, ensure_ascii=False)


def load_summary() -> Optional[Dict]:
    import json as _json
    if not os.path.exists(REC_SUMMARY_JSON):
        return None
    try:
        with open(REC_SUMMARY_JSON, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None

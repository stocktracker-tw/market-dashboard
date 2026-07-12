# -*- coding: utf-8 -*-
r"""策略回測：照「綜合分數倍數」加碼的主動定期定額，真的贏過固定定期定額嗎？

做法：每月投一筆。固定定額每月投 base；主動定額每月投 base × 當月分數對應的倍數
（0.25x~2x）。在 0050.TW 與 SPY 上各跑一次，並用三種哲學立場（逆勢/趨勢中性/順勢）
分別計算分數，看立場怎麼影響結果。比較貨幣加權報酬率(IRR)、每元最終價值、最大回撤。

⚠️ 誠實的限制（請務必連同結果一起看）：
  • 籌碼（法人/融資）歷史只有 ~20 天，回測的「分數」**不含籌碼面**，只用恐慌/估值/趨勢/總經。
  • 估值中位數、成交量能也無歷史快照，同樣排除。
  • 景氣對策信號是月資料、CPI 是月資料 → 對當月有輕微 look-ahead（用當月值）。
  • 結論高度 regime-dependent：過去十年台股大多為多頭，逆勢策略先天吃虧；
    這恰恰是這套工具「均值回歸 > 動能」哲學的已知弱點，不是程式 bug。
  • 這是研究與邏輯驗證，不是投資建議。

用法：  py -X utf8 strategy_backtest.py        # 產生 output/backtest.html
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

import config as cfg
import sources as src
import indicators as ind_mod
import scoring
import backtest as bt

MONTHS = 84          # 回測月數（約 7 年；受資料長度限制會自動縮短）
BASE = 10000.0       # 每月基準投入金額

SIG_SYMBOLS = {       # 算分數要用的訊號代碼（價格序列有多年歷史）
    "^VIX": "vix", "^VIX3M": "vix3m", "^GSPC": "spx", "^TWII": "twii",
    "TLT": "tlt", "HYG": "hyg", "IEF": "ief",
    "DX-Y.NYB": "dxy", "GC=F": "gold", "HG=F": "copper",
}
ASSETS = [("0050.TW", "台股 0050"), ("SPY", "美股 SPY")]


def log(m):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), m), flush=True)


# ---------------- 資料 ----------------
def fetch_all():
    log("抓取長期行情（10年）…")
    sig = {}
    for sym, key in SIG_SYMBOLS.items():
        h = src.yahoo_history(sym, rng="10y")
        if h:
            sig[key] = h
    assets = {}
    for sym, _ in ASSETS:
        h = src.yahoo_history(sym, rng="10y")
        if h:
            assets[sym] = h
    log("抓取長期 CPI / 殖利率 / 景氣信號…")
    yr = dt.date.today().year
    cpi = src.bls_cpi(start_year=yr - 10, end_year=yr)
    ust = src.ust_yield_curve_multi(years_back=10, this_year=yr)
    ndc = src.ndc_business_signal()
    return sig, assets, cpi, ust, ndc


def monthly_map(history, use_adj=True):
    """每月第一個交易日 → (epoch, date, price)。"""
    ts = history.get("timestamps") or []
    px = history.get("adjclose" if use_adj else "close") or []
    m = {}
    for t, p in zip(ts, px):
        if p is None:
            continue
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
        key = (d.year, d.month)
        if key not in m:
            m[key] = (t, d, float(p))
    return m


# ---------------- 模擬 ----------------
def irr_monthly(cfs):
    """貨幣加權報酬率（年化）。cfs 為每月現金流，最後一期已含期末市值。"""
    def npv(r):
        return sum(cf / ((1 + r) ** i) for i, cf in enumerate(cfs))
    lo, hi = -0.95, 1.0
    flo, fhi = npv(lo), npv(hi)
    if flo == 0:
        return (1 + lo) ** 12 - 1
    if flo * fhi > 0:
        return None
    mid = lo
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-6:
            break
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (1 + mid) ** 12 - 1


def simulate(keys, price_map, mult_for):
    units = invested = 0.0
    cfs, val_path, inv_path, labels = [], [], [], []
    for key in keys:
        _, d, p = price_map[key]
        amt = BASE * mult_for(key)
        invested += amt
        units += amt / p
        cfs.append(-amt)
        val_path.append(units * p)
        inv_path.append(invested)
        labels.append("%04d-%02d" % key)
    final = units * price_map[keys[-1]][2]
    cfs2 = cfs[:]
    cfs2[-1] += final
    irr = irr_monthly(cfs2)
    peak, mdd = -1e9, 0.0
    for v in val_path:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return {
        "invested": invested, "final": final, "units": units,
        "ret": final / invested - 1 if invested else 0,
        "irr": irr, "maxdd": mdd, "avgcost": invested / units if units else 0,
        "labels": labels,
        "efficiency": [v / iv if iv else 1 for v, iv in zip(val_path, inv_path)],
    }


def run():
    sig, assets, cpi, ust, ndc = fetch_all()
    if "SPY" not in assets or "0050.TW" not in assets:
        log("資產行情抓取失敗，無法回測。")
        return
    spy_map = monthly_map(assets["SPY"])
    tw_map = monthly_map(assets["0050.TW"])
    master = sorted(spy_map)[-MONTHS:]
    log("回測區間：%s ~ %s（%d 個月）" % (master[0], master[-1], len(master)))

    # 逐月分數 → 倍數（bias 機制已移除：三立場曲線本就因死指標權重歸零而完全重合）
    log("逐月計算分數…")
    score_mult = {}
    pillar_hist = {}     # (year,month) -> {pillar_key: score, "composite": comp}
    ind_hist = {}        # ind_key -> {(year,month): score}（指標成績單用）
    ind_names = {}
    for key in master:
        epoch, d, _ = spy_map[key]
        asof = {
            "yh": bt._truncate_yh(sig, epoch),
            "cpi": bt._cpi_asof(cpi, d.strftime("%Y-%m")),
            "ust": bt._ust_asof(ust, d.strftime("%Y-%m-%d")),
            "ndc": bt._ndc_asof(ndc, d.strftime("%Y%m")),
            "val": None, "turnover": None, "tw_hist": [],
        }
        inds = ind_mod.compute_all(asof)
        agg = scoring.aggregate(inds) if inds else None
        comp = agg["composite"] if agg else 50.0
        score_mult[key] = scoring._interpret(comp)[2]
        if agg:
            ph = {p["key"]: p["score"] for p in agg["pillars"]}
            ph["composite"] = comp
            pillar_hist[key] = ph
            for i0 in inds:
                ind_hist.setdefault(i0["key"], {})[key] = i0["score"]
                ind_names[i0["key"]] = i0["name"]

    # 各資產 × 策略 模擬
    results = {}
    for sym, label in ASSETS:
        amap = tw_map if sym == "0050.TW" else spy_map
        keys = [k for k in master if k in amap]
        if len(keys) < 12:
            continue
        rows = {"固定定額": simulate(keys, amap, lambda k: 1.0),
                "主動": simulate(keys, amap, lambda k: score_mult[k])}
        results[sym] = {"label": label, "rows": rows, "keys": keys}

    try:
        validation = score_validation(sig)
    except Exception as e:                     # noqa: BLE001 — 體檢失敗不擋回測報告
        validation = None
        log("分數有效性體檢略過：%s" % str(e)[:120])
    try:
        ic_html = pillar_ic_card(pillar_hist, sig)
    except Exception as e:                     # noqa: BLE001 — IC 失敗不擋回測報告
        ic_html = None
        log("支柱 IC 計算略過：%s" % str(e)[:120])
    try:
        report_html = indicator_report_card(ind_hist, ind_names, sig)
    except Exception as e:                     # noqa: BLE001 — 成績單失敗不擋回測報告
        report_html = None
        log("指標成績單略過：%s" % str(e)[:120])
    validation = (validation or "") + (ic_html or "") + (report_html or "")
    render_html(results, master, validation or None)
    print_summary(results)

    if getattr(cfg, "PUBLISH_ENABLED", False):
        try:
            import publish
            publish.publish_backtest()
            log("已發佈回測報告到 GitHub Pages：%sbacktest.html" % publish.pages_url())
        except Exception as e:
            log("回測報告發佈失敗（不影響本機檔案）：%s" % str(e)[:140])


def print_summary(results):
    for sym, blk in results.items():
        print("\n=== %s（%s）===" % (blk["label"], sym))
        print("%-14s %12s %12s %8s %8s %8s" % ("策略", "投入總額", "最終價值", "報酬%", "年化IRR", "最大回撤"))
        for name, r in blk["rows"].items():
            irr = "—" if r["irr"] is None else "%.1f%%" % (r["irr"] * 100)
            print("%-14s %12.0f %12.0f %7.1f%% %8s %7.1f%%" %
                  (name, r["invested"], r["final"], r["ret"] * 100, irr, r["maxdd"] * 100))


# ---------------- 分數有效性驗證 ----------------
def score_validation(sig):
    """「分數 vs 台股加權未來 20 個交易日報酬」分組統計 → 回傳 HTML 區塊（或 None）。

    用 history_score.csv 的 raw 分數（週末列因對不到交易日自然剔除），按分數五分位
    分組，看高分組的未來報酬是否真的優於低分組——這是整套系統最核心的體檢。
    """
    import csv
    scores = {}
    try:
        with open(cfg.HISTORY_SCORE, encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) >= 2:
                    try:
                        scores[r[0]] = float(r[1])
                    except ValueError:
                        pass
    except OSError:
        return None
    twii = sig.get("twii") or {}
    ts = twii.get("timestamps") or []
    px = twii.get("adjclose") or twii.get("close") or []
    daily = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().strftime("%Y-%m-%d"),
              float(p)) for t, p in zip(ts, px) if p]
    idx = {d: i for i, (d, _) in enumerate(daily)}
    H = 20
    obs = []                                   # (score, fwd_return)
    for dstr, sc in scores.items():
        i = idx.get(dstr)
        if i is None or i + H >= len(daily):
            continue
        obs.append((sc, daily[i + H][1] / daily[i][1] - 1.0))
    if len(obs) < 30:
        return None                            # 樣本太少，寧可不顯示
    obs.sort(key=lambda x: x[0])
    n = len(obs)
    q = max(1, n // 5)
    groups = [obs[i * q: (i + 1) * q if i < 4 else n] for i in range(5)]
    rows = []
    for g in groups:
        if not g:
            continue
        avg = sum(r for _, r in g) / len(g) * 100
        rows.append(("%.0f–%.0f" % (g[0][0], g[-1][0]), len(g), avg))
    overall = sum(r for _, r in obs) / n * 100
    mx = max(abs(a) for _, _, a in rows) or 1.0
    parts = ['<div class="card"><h2>🎯 分數有效性體檢：分數高的日子，之後真的比較會漲嗎？</h2>',
             '<div style="font-size:12.5px;color:#5f7183;margin-bottom:10px">'
             '把每天的 raw 分數按高低分五組，看各組「未來 %d 個交易日」台股加權的平均報酬。'
             '若分數有效，越高的組報酬應越好。全樣本平均 %+.1f%%（n=%d）。</div>' % (H, overall, n)]
    for label, cnt, avg in rows:
        w = abs(avg) / mx * 100
        color = "#ea5455" if avg >= 0 else "#28c76f"
        parts.append(
            '<div style="display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12.5px">'
            '<span style="flex:none;width:86px;color:#5f7183">分數 %s</span>'
            '<span style="flex:none;width:52px;color:#8795a3">n=%d</span>'
            '<span style="flex:1;height:14px;position:relative">'
            '<span style="position:absolute;left:0;top:0;bottom:0;width:%.0f%%;'
            'background:%s;border-radius:4px;opacity:.75"></span></span>'
            '<b style="flex:none;width:64px;text-align:right;color:%s">%+.2f%%</b></div>'
            % (label, cnt, w, color, color, avg))
    parts.append('<div style="font-size:11.5px;color:#8795a3;margin-top:8px">'
                 '注意：分數歷史仍在累積（前 60 日為回測補值、含輕微後見之明）；'
                 '樣本涵蓋期間短、屬同一市場環境，統計僅供方向參考。</div></div>')
    return "".join(parts)


# ---------------- 支柱預測力（IC） ----------------
def _rank(xs):
    """平均秩（處理同分）。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    """Spearman 等級相關（-1..1）。樣本太少或無變異回 None。"""
    if len(xs) < 12 or len(set(xs)) < 3 or len(set(ys)) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    dy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / (dx * dy) if dx and dy else None


def pillar_ic_card(pillar_hist, sig):
    """各支柱月度分數 vs 台股加權未來 1／3 個月報酬的 Spearman IC → HTML 卡。

    回答「哪根支柱真的會預測、哪根是安慰劑」。歷史重算的限制一併標註：
    籌碼支柱歷史上只剩量能一項、估值支柱只剩距高點回檔（法人/融資/本益比
    無 10 年史料），這兩根的 IC 只代表其可回測的子集。
    """
    if not pillar_hist:
        return None
    tmap = monthly_map(sig.get("twii") or {})
    keys = [k for k in sorted(pillar_hist) if k in tmap]
    if len(keys) < 15:
        return None
    def _midx(k):
        return k[0] * 12 + k[1]
    fwd = {1: {}, 3: {}}
    for i, k in enumerate(keys):
        for h in (1, 3):
            if i + h < len(keys) and _midx(keys[i + h]) - _midx(k) == h:
                fwd[h][k] = tmap[keys[i + h]][2] / tmap[k][2] - 1.0
    from config import PILLAR_NAMES
    caveat = {"chips": "※", "valuation": "※", "macro": "†"}
    rows = []
    pillar_keys = [pk for pk in list(PILLAR_NAMES) if any(pk in v for v in pillar_hist.values())]
    for pk in pillar_keys + ["composite"]:
        nm = "綜合分數" if pk == "composite" else PILLAR_NAMES.get(pk, pk)
        cells = []
        for h in (1, 3):
            pairs = [(pillar_hist[k][pk], fwd[h][k]) for k in keys
                     if pk in pillar_hist[k] and k in fwd[h]]
            ic = _spearman([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
            cells.append((ic, len(pairs)))
        rows.append((nm + caveat.get(pk, ""), pk == "composite", cells))
    parts = ['<div class="card"><h2>🧭 支柱預測力（IC）：哪根柱子真的會預測？</h2>',
             '<div style="font-size:12.5px;color:#5f7183;margin-bottom:10px">'
             '把每月各支柱分數與台股加權「之後 1／3 個月」報酬做等級相關（Spearman IC，'
             '-1〜+1，越正代表分數越高之後越漲）。單一時間序列樣本 n≈80，'
             '雜訊帶約 ±0.11（1σ≈1/√n）——<b>|IC| 要 ≳ 0.2 才算明顯跳出雜訊</b>；'
             '接近 0 ＝該支柱對未來報酬沒有辨識力。</div>']
    for nm, is_comp, cells in rows:
        bar_cells = []
        for ic, n in cells:
            if ic is None:
                bar_cells.append('<span style="flex:1;color:#8795a3;font-size:12px">樣本不足</span>')
                continue
            w = min(100, abs(ic) * 250)
            color = "#ea5455" if ic >= 0 else "#28c76f"
            bar_cells.append(
                '<span style="flex:1;display:flex;align-items:center;gap:6px">'
                '<span style="flex:1;height:12px;position:relative">'
                '<span style="position:absolute;left:0;top:0;bottom:0;width:%.0f%%;'
                'background:%s;border-radius:4px;opacity:.75"></span></span>'
                '<b style="flex:none;width:56px;text-align:right;color:%s">%+.2f</b>'
                '<span style="flex:none;color:#8795a3;font-size:11px">n=%d</span></span>'
                % (w, color, color, ic, n))
        weight = ';font-weight:700' if is_comp else ''
        parts.append('<div style="display:flex;align-items:center;gap:12px;margin:6px 0;font-size:12.5px">'
                     '<span style="flex:none;width:120px;color:#3f5468%s">%s</span>%s</div>'
                     % (weight, nm, "".join(bar_cells)))
    parts.append('<div style="display:flex;gap:12px;margin:2px 0 0;font-size:11px;color:#8795a3">'
                 '<span style="width:120px;flex:none"></span>'
                 '<span style="flex:1">↑ 未來 1 個月</span><span style="flex:1">↑ 未來 3 個月</span></div>')
    parts.append('<div style="font-size:11.5px;color:#8795a3;margin-top:8px">'
                 '※ 籌碼／估值支柱缺 10 年史料（無法人/融資/本益比），歷史重算只含其可回測子集'
                 '（量能、距高點回檔），IC 僅代表該子集。'
                 '† 總經支柱以「當月」CPI/景氣信號計分，實務上這些數據下月才公布，'
                 '含輕微 look-ahead、IC 略偏樂觀。月資料、單一市場環境，僅供方向參考。</div>')
    parts.append('</div>')
    return "".join(parts)


def indicator_report_card(ind_hist, ind_names, sig):
    """📋 指標成績單：每個（可歷史重算的）指標的月度 IC → 排序列表。

    這是「讓數據決定去留」的裁判：|IC| 長期趨近 0 的指標是刪除候選。
    僅涵蓋回測算得出來的指標（法人/融資/PTT 等無 10 年史料者不在此列，
    其去留由每日累積的 history 與體檢卡另行判斷）。
    """
    if not ind_hist:
        return None
    tmap = monthly_map(sig.get("twii") or {})
    def _midx(k):
        return k[0] * 12 + k[1]
    rows = []
    for ikey, hist in ind_hist.items():
        keys = [k for k in sorted(hist) if k in tmap]
        if len(keys) < 15:
            continue
        pairs = []
        for i, k in enumerate(keys):
            if i + 3 < len(keys) and _midx(keys[i + 3]) - _midx(k) == 3:
                pairs.append((hist[k], tmap[keys[i + 3]][2] / tmap[k][2] - 1.0))
        ic = _spearman([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
        if ic is not None:
            rows.append((ic, len(pairs), ikey))
    if not rows:
        return None
    rows.sort(key=lambda r: -abs(r[0]))
    parts = ['<div class="card"><h2>📋 指標成績單：誰在做事、誰在划水？</h2>',
             '<div style="font-size:12.5px;color:#5f7183;margin-bottom:10px">'
             '各指標月度分數 vs 台股加權未來 3 個月報酬的 Spearman IC，按辨識力排序。'
             '雜訊帶約 ±0.11——<b>長期趴在雜訊帶裡的指標是刪除候選</b>（讓數據決定去留，'
             '而不是捨不得）。僅列可歷史重算的指標；正 IC＝分數高之後漲。</div>']
    mx = max(abs(r[0]) for r in rows) or 1.0
    for ic, n, ikey in rows:
        color = "#ea5455" if ic >= 0 else "#28c76f"
        noise = ' <span style="color:#8795a3;font-size:10.5px">趴在雜訊帶</span>' if abs(ic) < 0.11 else ""
        parts.append(
            '<div style="display:flex;align-items:center;gap:10px;margin:4px 0;font-size:12px">'
            '<span style="flex:none;width:190px;color:#3f5468">%s%s</span>'
            '<span style="flex:1;height:11px;position:relative">'
            '<span style="position:absolute;left:0;top:0;bottom:0;width:%.0f%%;'
            'background:%s;border-radius:4px;opacity:.7"></span></span>'
            '<b style="flex:none;width:52px;text-align:right;color:%s">%+.2f</b>'
            '<span style="flex:none;width:40px;color:#8795a3;font-size:10.5px">n=%d</span></div>'
            % (ind_names.get(ikey, ikey), noise, abs(ic) / mx * 100, color, color, ic, n))
    parts.append('<div style="font-size:11.5px;color:#8795a3;margin-top:8px">'
                 '注意：單一時間序列、月資料、同一市場環境；總經類含輕微 look-ahead。'
                 '刪指標前先看它是否在別的環境有價值（如恐慌類平時無用、崩盤時救命）。</div></div>')
    return "".join(parts)


# ---------------- HTML ----------------
def render_html(results, master, validation=None):
    C = {"green": "#28c76f", "amber": "#f6a821", "red": "#ea5455", "accent": "#2478c8"}
    chart_data = {}
    parts = []
    parts.append("""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>策略回測：主動 vs 固定定期定額</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body{margin:0;background:#f5f8fb;color:#17293a;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:980px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:22px;margin:0 0 4px}.sub{color:#5f7183;font-size:13px;margin-bottom:18px}
a{color:#2478c8}
.card{background:#ffffff;border:1px solid #dbe4ee;border-radius:14px;padding:16px 18px;margin-bottom:18px}
h2{font-size:17px;margin:0 0 10px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #222936}
th:first-child,td:first-child{text-align:left}
thead th{color:#5f7183;font-weight:600}
.best{color:#28c76f;font-weight:700}
.chart{height:420px;margin-top:16px}
.note{background:rgba(246,168,33,.10);border:1px solid rgba(246,168,33,.35);color:#ffd98a;
  padding:10px 14px;border-radius:10px;font-size:12.5px;margin-bottom:18px}
.foot{margin-top:24px;padding-top:14px;border-top:1px solid #dbe4ee;color:#5f7183;font-size:12px}
</style></head><body>""")
    from dashboard import nav
    parts.append(nav("index", include_css=True))   # 回測＝大盤子頁，分頁列高亮「大盤」
    parts.append('<div class="wrap">')
    parts.append('<h1>策略回測：主動 vs 固定定期定額</h1>')
    parts.append('<div class="sub">每月投一筆；主動＝每月投入 × 當月分數倍數(0.25–2x)。'
                 '區間 %s ~ %s。</div>' % (master[0], master[-1]))
    parts.append('<div class="note">⚠️ 重要限制：此回測的「分數」<b>不含籌碼面</b>（法人/融資歷史太短），'
                 '只用恐慌/估值/趨勢/總經；CPI 與景氣信號為月資料有輕微 look-ahead。'
                 '結論高度 regime-dependent：過去十年大多頭環境對逆勢策略先天不利。'
                 '主動倍數依 raw 分數的 ACTION_BANDS 計算；線上顯示另有「歷史百分位校準」層，'
                 '本回測未重現該層。本頁為邏輯驗證、<b>非投資建議</b>。</div>')
    if validation:
        parts.append(validation)

    for sym, blk in results.items():
        parts.append('<div class="card"><h2>%s <span style="color:#5f7183;font-size:13px">%s</span></h2>'
                     % (blk["label"], sym))
        # 找出 IRR 最佳列
        best_irr = max((r["irr"] for r in blk["rows"].values() if r["irr"] is not None), default=None)
        parts.append('<table><thead><tr><th>策略</th><th>投入總額</th><th>最終價值</th>'
                     '<th>報酬%</th><th>年化IRR</th><th>最大回撤</th></tr></thead><tbody>')
        for name, r in blk["rows"].items():
            irr_txt = "—" if r["irr"] is None else "%.1f%%" % (r["irr"] * 100)
            cls = ' class="best"' if (r["irr"] is not None and r["irr"] == best_irr) else ""
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%+.1f%%</td><td%s>%s</td><td>%.1f%%</td></tr>"
                         % (name, _money(r["invested"]), _money(r["final"]), r["ret"] * 100,
                            cls, irr_txt, r["maxdd"] * 100))
        parts.append("</tbody></table>")
        parts.append('<div class="chart" id="ch-%s"></div>' % _safe(sym))
        parts.append('<div style="font-size:11.5px;color:#5f7183;margin-top:4px">'
                     '上圖＝每元投入的帳戶價值（帳戶市值÷已投入金額，兩條都從 1.0 出發，越高＝每塊錢越有效率）。</div>')
        parts.append("</div>")
        chart_data[sym] = {
            "labels": blk["rows"]["固定定額"]["labels"],
            "fixed": [round(x, 3) for x in blk["rows"]["固定定額"]["efficiency"]],
            "active": [round(x, 3) for x in blk["rows"]["主動"]["efficiency"]],
        }

    parts.append('<div class="foot">資料來源：Yahoo Finance（還原權值）、BLS、美國財政部、國發會。'
                 '每月基準投入 %.0f；倍數來自 config.ACTION_BANDS。'
                 '本頁為研究與決策輔助，不構成投資建議。</div>' % BASE)

    parts.append('<script>const CH=%s;const C=%s;' % (json.dumps(chart_data, ensure_ascii=False), json.dumps(C)))
    parts.append("""
Object.keys(CH).forEach(function(sym){
  var id='ch-'+sym.replace(/[^A-Za-z0-9]/g,'_');
  var el=document.getElementById(id); if(!el)return;
  var d=CH[sym]; var c=echarts.init(el);
  c.setOption({grid:{left:44,right:12,top:18,bottom:24},
    legend:{data:['固定定額','主動'],textStyle:{color:'#3f5468'},top:0},
    tooltip:{trigger:'axis'},
    xAxis:{type:'category',data:d.labels,axisLabel:{color:'#7a8a99',fontSize:10}},
    yAxis:{type:'value',scale:true,axisLabel:{color:'#7a8a99',fontSize:10}},
    series:[{name:'固定定額',type:'line',data:d.fixed,smooth:true,symbol:'none',lineStyle:{color:'#5f7183',width:2}},
            {name:'主動',type:'line',data:d.active,smooth:true,symbol:'none',lineStyle:{color:C.accent,width:2}}]});
  window.addEventListener('resize',function(){c.resize();});
});
</script></div></body></html>""")

    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(cfg.OUTPUT_DIR, "backtest.html")
    from dashboard import with_pwa
    with open(path, "w", encoding="utf-8") as f:
        f.write(with_pwa("".join(parts)))
    log("回測報告：%s" % path)

    # 存精簡 JSON 供大盤頁直接內嵌
    def _fmtym(d):
        return "%04d-%02d" % (d[0], d[1]) if isinstance(d, (list, tuple)) else str(d)
    summary = {"period": "%s ~ %s" % (_fmtym(master[0]), _fmtym(master[-1])), "symbols": {}}
    for sym, blk in results.items():
        rows_out = {}
        for name, r in blk["rows"].items():
            rows_out[name] = {"irr": round(r["irr"]*100, 1) if r["irr"] is not None else None,
                              "ret": round(r["ret"]*100, 1),
                              "maxdd": round(r["maxdd"]*100, 1)}
        summary["symbols"][sym] = {
            "label": blk["label"],
            "rows": rows_out,
            "chart": chart_data.get(sym, {}),
        }
    import json as _json
    with open(os.path.join(cfg.DATA_DIR, "backtest_summary.json"), "w", encoding="utf-8") as f:
        _json.dump(summary, f, ensure_ascii=False)
    log("回測摘要已存：data/backtest_summary.json")


def _money(x):
    return "{:,.0f}".format(x)


def _safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s)


if __name__ == "__main__":
    run()

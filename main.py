# -*- coding: utf-8 -*-
"""市場進場儀表板 — 主程式。

流程：抓資料 → 回補/更新台股籌碼歷史 → 計算各指標 → 綜合分數 → 產生 HTML → 記錄歷史。
用法：  py -X utf8 main.py          # 抓資料並產生 output/dashboard.html
        py -X utf8 main.py --open   # 產生後自動用瀏覽器開啟
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import sys
import time

# Windows 終端機用 UTF-8 輸出，避免中文變亂碼
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

import subprocess

import config as cfg
import sources as src
import indicators as ind_mod
import scoring
import dashboard
import backtest
import meltup
import cycle as cycle_mod
import forecast as forecast_mod

TW_FIELDS = ["date", "foreign", "invtrust", "dealer", "total", "margin_balance", "short_balance"]


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


# ----------------------------- 台股籌碼歷史 -----------------------------
def load_tw_history():
    rows = {}
    if not os.path.exists(cfg.HISTORY_TW):
        return rows
    with open(cfg.HISTORY_TW, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d = r.get("date")
            if not d:
                continue
            rows[d] = {k: (float(r[k]) if r.get(k) not in (None, "", "None") else None)
                       for k in TW_FIELDS if k != "date"}
            rows[d]["date"] = d
    return rows


def save_tw_history(rows):
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    with open(cfg.HISTORY_TW, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TW_FIELDS)
        w.writeheader()
        for d in sorted(rows):
            row = rows[d]
            w.writerow({k: row.get(k) for k in TW_FIELDS})


def update_tw_history():
    """從今天往回走，補齊最近 N 個交易日的三大法人＋融資（已存在的日期直接沿用）。"""
    rows = load_tw_history()
    need = cfg.BACKFILL_TRADING_DAYS
    have_before = len(rows)
    collected = 0
    walked = 0
    d = dt.date.today()
    fetched = 0
    while collected < need and walked < 45:
        ds = d.strftime("%Y%m%d")
        if d.weekday() < 5:  # 一~五
            if ds in rows:
                collected += 1
            else:
                inst = src.twse_institutional(ds)
                if inst:
                    marg = src.twse_margin(ds) or {}
                    rows[ds] = {
                        "date": ds,
                        "foreign": inst.get("foreign"),
                        "invtrust": inst.get("invtrust"),
                        "dealer": inst.get("dealer"),
                        "total": inst.get("total"),
                        "margin_balance": marg.get("margin_balance"),
                        "short_balance": marg.get("short_balance"),
                    }
                    collected += 1
                    fetched += 1
                    time.sleep(0.35)
                # 取不到 = 假日，略過
        d -= dt.timedelta(days=1)
        walked += 1
    save_tw_history(rows)
    if have_before == 0:
        log("台股籌碼歷史首次建立：回補 %d 個交易日" % len(rows))
    elif fetched:
        log("台股籌碼歷史更新：新增 %d 日（共 %d 日）" % (fetched, len(rows)))
    else:
        log("台股籌碼歷史已是最新（共 %d 日）" % len(rows))
    return [rows[k] for k in sorted(rows)]


# ----------------------------- 綜合分數歷史 -----------------------------
def append_score_history(score, seeds=None):
    """寫入今天的實際分數；seeds=[(date,score)] 為回測值，僅填補尚不存在的日期。"""
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    today = dt.date.today().strftime("%Y-%m-%d")
    hist = {}
    if os.path.exists(cfg.HISTORY_SCORE):
        with open(cfg.HISTORY_SCORE, "r", encoding="utf-8", newline="") as f:
            for r in csv.reader(f):
                if len(r) >= 2:
                    hist[r[0]] = r[1]
    for d, s in (seeds or []):
        if d not in hist:            # 不覆蓋已有的實際分數
            hist[d] = "%.1f" % s
    hist[today] = "%.1f" % score     # 今天一律用實際分數
    with open(cfg.HISTORY_SCORE, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for d in sorted(hist):
            w.writerow([d, hist[d]])
    return [[d, float(hist[d])] for d in sorted(hist)][-120:]


# ----------------------------- 分數變動歸因 -----------------------------
def pillar_attribution(result):
    """記錄每日支柱分數到 data/history_pillars.csv，回傳今天 vs 上一交易日的變動歸因。

    綜合分 = Σ(支柱分×權重)/Σ權重 → 兩日之差可拆回各支柱貢獻
    （以今天的權重集合近似；支柱增減時略有誤差，可接受）。
    回傳 {"prev_date", "delta", "parts": [(支柱名, 貢獻分), …]}；無昨日資料回 None。
    歸因一律用 raw 支柱分（校準只動顯示的綜合分，不動支柱）。
    """
    path = os.path.join(cfg.DATA_DIR, "history_pillars.csv")
    today = dt.date.today().strftime("%Y-%m-%d")
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            rows = [r for r in csv.reader(f) if len(r) >= 4]
    prev_dates = sorted({r[0] for r in rows if r[0] < today})
    prev = ({r[1]: float(r[2]) for r in rows if r[0] == prev_dates[-1]}
            if prev_dates else {})
    rows = [r for r in rows if r[0] != today]        # 同日重跑 → 覆蓋今天
    for p in result["pillars"]:
        rows.append([today, p["key"], "%.2f" % p["score"], "%g" % p["weight"]])
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(sorted(rows))
    if not prev:
        return None
    den = sum(p["weight"] for p in result["pillars"]) or 1.0
    contribs = [(p["name"], (p["score"] - prev[p["key"]]) * p["weight"] / den)
                for p in result["pillars"] if p["key"] in prev]
    if not contribs:
        return None
    delta = round(sum(c for _, c in contribs), 1)
    parts = sorted(((n, round(c, 1)) for n, c in contribs if abs(c) >= 0.05),
                   key=lambda x: -abs(x[1]))[:3]
    return {"prev_date": prev_dates[-1], "delta": delta, "parts": parts}


# ----------------------------- 主流程 -----------------------------
def self_update():
    """開跑前自動同步 engine-src；有更新就以新程式碼重新啟動自己（僅一次）。

    設計：
    - --ff-only：本機有髒改動就放棄更新、照常用現有版本跑（絕不卡住排程）。
    - 更新成功且 HEAD 有變 → 以子行程重跑自己並沿用參數，防迴圈用環境變數擋第二次。
    - 任何失敗都只印一行、不擋主流程。可用 ST_NO_SELFUPDATE=1 完全停用。
    """
    if os.environ.get("ST_NO_SELFUPDATE"):
        return False
    base = os.path.dirname(os.path.abspath(__file__))
    remote = getattr(cfg, "ENGINE_GIT_REMOTE", "dash")
    def _git(*args, timeout=120):
        return subprocess.run(["git", "-C", base] + list(args),
                              capture_output=True, text=True, timeout=timeout)
    try:
        before = _git("rev-parse", "HEAD", timeout=30).stdout.strip()
        r = _git("pull", "--ff-only", remote, "engine-src")
        after = _git("rev-parse", "HEAD", timeout=30).stdout.strip()
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            log("自動更新略過（%s）——照常用現有版本跑" % (tail[-1][:120] if tail else "git 非零返回"))
            return False
        if before and after and before != after:
            log("引擎已自動更新 %s → %s，以新版重新啟動…" % (before[:7], after[:7]))
            env = dict(os.environ)
            env["ST_NO_SELFUPDATE"] = "1"
            child = subprocess.run([sys.executable, "-X", "utf8",
                                    os.path.abspath(__file__)] + sys.argv[1:], env=env)
            sys.exit(child.returncode)
        log("引擎已是最新（%s）" % (after[:7] or "?"))
    except Exception as e:                         # noqa: BLE001 — 自動更新永不擋主流程
        log("自動更新略過：%s" % str(e)[:120])
    return False


def run(open_browser=False):
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    failed = []

    log("抓取 Yahoo Finance 行情（%d 檔）…" % len(cfg.YAHOO_SYMBOLS))
    yh = src.yahoo_many(cfg.YAHOO_SYMBOLS)
    missing = [k for k in cfg.YAHOO_SYMBOLS.values() if k not in yh]
    if missing:
        failed.append("Yahoo(%s)" % ",".join(missing))
    log("Yahoo 取得 %d/%d 檔" % (len(yh), len(cfg.YAHOO_SYMBOLS)))

    log("抓取美國 CPI（BLS）…")
    cpi = src.bls_cpi()
    if not cpi:
        failed.append("美國CPI")

    log("抓取美債殖利率曲線…")
    ust = src.ust_yield_curve(dt.date.today().year) or src.ust_yield_curve(dt.date.today().year - 1)
    if not ust:
        failed.append("殖利率曲線")

    log("抓取台股估值/成交量/櫃買籌碼…")
    val = src.twse_valuation()
    if not val:
        failed.append("台股估值")
    turnover = src.twse_turnover()
    if not turnover:
        failed.append("台股成交量")

    log("抓取國發會景氣對策信號…")
    ndc = src.ndc_business_signal()
    if not ndc:
        failed.append("景氣對策信號")

    log("更新台股三大法人/融資歷史…")
    tw_hist = update_tw_history()

    log("抓取 PTT 散戶情緒…")
    try:
        ptt = src.ptt_stock_sentiment()
    except Exception:                              # noqa: BLE001 — 情緒指標非必要
        ptt = None
    if ptt:
        log("PTT 標的文多空：看多 %d、看空 %d、爆文 %d" %
            (ptt.get("bull", 0), ptt.get("bear", 0), ptt.get("hot", 0)))
    else:
        log("PTT 情緒抓不到（本次略過，該指標自動退出加權）")

    data = {"yh": yh, "cpi": cpi, "ust": ust, "val": val,
            "turnover": turnover, "ndc": ndc, "tw_hist": tw_hist, "ptt": ptt}

    log("計算指標與綜合分數…")
    indicators = ind_mod.compute_all(data)
    result = scoring.aggregate(indicators)

    # 顯示層校準：raw → 歷史百分位（history_score.csv 永遠存 raw，見下方 append）
    result["composite_raw"] = result["composite"]
    _cal, _caln = scoring.calibrate(result["composite_raw"])
    if _cal is not None:
        _b, _a, _m = scoring._interpret(_cal)
        result.update({"composite": _cal, "calibrated": True, "calib_n": _caln,
                       "band": _b, "action": _a, "dca_multiplier": _m})
        log("百分位校準：raw %.1f → %.1f（對照近 %d 日分佈）"
            % (result["composite_raw"], _cal, _caln))

    # 今日 vs 上一交易日支柱變化 → 分數變動歸因（寫入 data/history_pillars.csv）
    try:
        result["attribution"] = pillar_attribution(result)
    except Exception as e:
        log("變動歸因略過：%s" % str(e)[:120])

    # 消息面微調（B：由查證簡報輸出，小幅、有上限、會衰退；只反映尚未反映的催化/真偽）
    try:
        import news as _news
        ndelta, nainfo = _news.effective_news_adjust()
    except Exception:
        ndelta, nainfo = 0.0, None
    if ndelta:
        base = result["composite"]
        adj = round(max(0.0, min(100.0, base + ndelta)), 1)
        b, a, m = scoring._interpret(adj)
        result.update({"composite_base": base, "composite": adj, "news_delta": ndelta,
                       "news_reason": (nainfo or {}).get("reason"),
                       "band": b, "action": a, "dca_multiplier": m})
        log("消息面微調 %+.1f → 綜合分數 %.1f（%s）" % (ndelta, adj, b))

    # 景氣循環（投資時鐘）
    cyc = cycle_mod.assess(ndc, cpi)

    # 歷史條件式預期（base rates）
    try:
        fc = forecast_mod.assess()
    except Exception as e:
        fc = None
        log("歷史預期計算失敗：%s" % str(e)[:120])

    # AI 噴發 / 泡沫 情境
    regime = meltup.assess(yh, tw_hist)
    meltup_aware = getattr(cfg, "MELTUP_AWARE", False)
    if regime and meltup_aware and regime.get("floor_active"):
        floor = getattr(cfg, "MELTUP_FLOOR", 1.0)
        if result["dca_multiplier"] < floor:
            result["dca_multiplier"] = floor
            result["action"] += "（噴發感知：趨勢完好，維持參與，以跌破 50 日線為減碼訊號）"
        log("噴發感知啟用：偵測到『噴發中』，定額倍數下限 %.2gx" % floor)

    # 回測：填補過去 N 個交易日的分數（只補尚不存在的日期），讓走勢圖立刻有資料
    existing = set()
    if os.path.exists(cfg.HISTORY_SCORE):
        with open(cfg.HISTORY_SCORE, "r", encoding="utf-8", newline="") as f:
            existing = {r[0] for r in csv.reader(f) if r}
    seeds = []
    today_iso = dt.date.today().strftime("%Y-%m-%d")
    if len(existing) < cfg.BACKTEST_DAYS:
        seeds = backtest.compute_backtest(data, cfg.BACKTEST_DAYS, existing | {today_iso})
        if seeds:
            log("回測補入過去 %d 日分數" % len(seeds))
    score_history = append_score_history(
        result.get("composite_raw", result.get("composite_base", result["composite"])), seeds)
    # 走勢圖與 hero 同一把尺：校準開啟時，把 raw 走勢也映射成歷史百分位
    if result.get("calibrated"):
        _ref = scoring.load_raw_history()
        score_history = [[d, round(scoring.percentile_of(v, _ref), 1)]
                         for d, v in score_history]

    # 自選股清單 → 個股分頁（output/stocks.html）
    shared = None
    if getattr(cfg, "STOCK_WATCHLIST", None):
        try:
            import stock
            shared = stock.fetch_shared()
            sres = [stock.compute(c, env=result["composite"], shared=shared) for c in cfg.STOCK_WATCHLIST]
            sres = [r for r in sres if r]
            universe = stock.build_universe(result["composite"], shared)
            recs = stock.recommend(result["composite"], shared, universe)
            if sres or universe or recs:
                stock.render_stocks_page(recs, sres, universe)
                top = "、".join("%s %.0f" % (r["code"], r["score"]) for r in recs[:5])
                log("個股分頁：推薦 %d 檔（%s）、自選 %d、可搜尋 %d"
                    % (len(recs), top, len(sres), len(universe)))
        except Exception as e:
            log("個股分頁失敗（不影響大盤儀表板）：%s" % str(e)[:140])

    # 市場消息監控（①：抓標題＋是否已反映；不判真偽）
    try:
        import news
        nd = news.assess(shared=shared, twii_close=(yh.get("twii") or {}).get("close"))
        if nd:
            news.render_news_page(nd, briefing_html=news._load_briefing())
            log("市場消息：%d 則標題" % len(nd["headlines"]))
    except Exception as e:
        log("市場消息失敗（不影響大盤儀表板）：%s" % str(e)[:140])

    # 五派選股（觀點頁「這派今天會看」；個股區失敗就略過）
    faction_pk = None
    try:
        if shared is not None:
            faction_pk = stock.faction_picks(shared, universe)
    except Exception as e:                         # noqa: BLE001 — 選股失敗不擋觀點
        log("五派選股略過：%s" % str(e)[:120])

    # 五派投資策略觀點（含台指期籌碼；抓不到就用快取/略過）
    try:
        tx_chips = src.taifex_chips()
        if tx_chips:
            log("台指期籌碼：外資淨未平倉 %s 口" % tx_chips.get("foreign_net_oi", "—"))
    except Exception:
        tx_chips = None
    try:
        import perspectives
        persp = perspectives.assess(result, indicators, regime, cyc, fc,
                                    taifex=tx_chips, picks=faction_pk)
    except Exception as e:
        persp = None
        log("五派觀點計算失敗：%s" % str(e)[:120])

    meta = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources_failed": failed,
        "meltup_aware": meltup_aware and bool(regime and regime.get("floor_active")),
    }
    html = dashboard.render(result, indicators, score_history, meta,
                            regime=regime, cycle=cyc, forecast=fc, perspectives=persp)
    with open(cfg.OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    # 獨立的「🗣️ 觀點」分頁（三方辯論 + 結論）
    try:
        if persp:
            dashboard.render_perspectives_page(persp, meta)
    except Exception as e:
        log("觀點分頁產生略過：%s" % str(e)[:120])

    # 除錯快取
    try:
        with open(cfg.RAW_CACHE, "w", encoding="utf-8") as f:
            json.dump({"composite": result["composite"], "band": result["band"],
                       "pillars": result["pillars"],
                       "indicators": [{"name": i["name"], "score": i["score"],
                                       "value": i["value_display"]} for i in indicators]},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    log("完成：綜合進場分數 %.1f（%s）・%d 項指標" %
        (result["composite"], result["band"], result["n_indicators"]))
    if failed:
        log("（略過的來源：%s）" % "、".join(failed))
    log("儀表板：%s" % cfg.OUTPUT_HTML)

    # 個股推薦追蹤 & 歷史模擬回測（結果存成 JSON，由 stocks.html 直接內嵌）
    try:
        import rec_tracker
        if recs:
            saved = rec_tracker.save_today(recs)
            if saved:
                log("推薦紀錄：存入 %d 筆 → data/rec_history.csv" % saved)
        updated = rec_tracker.update_returns()
        if updated:
            log("推薦追蹤：補填 %d 筆報酬" % updated)
        if recs:
            log("推薦個股歷史模擬中（%d 檔）…" % len(recs))
            sim = rec_tracker.simulate_history(recs, n_sim=max(len(recs), 8))
            hist = rec_tracker.load_history()
            rec_tracker.save_summary(sim, hist)
            log("個股回測摘要已存：data/rec_summary.json（將內嵌於個股頁）")
            # 重跑個股頁讓內嵌生效
            if shared is not None and recs:
                try:
                    import stock
                    stock.render_stocks_page(recs, sres, universe)
                    log("個股頁已重新產生（含回測內嵌）")
                except Exception as ee:
                    log("個股頁重產失敗：%s" % str(ee)[:120])
    except Exception as e:
        log("個股推薦回測略過：%s" % str(e)[:160])

    # 每日 Threads 貼文（複製貼上用）
    try:
        import threads
        threads.render_threads_page()
        log("Threads 貼文已產生：output/threads.html")
    except Exception as e:
        log("Threads 貼文產生略過：%s" % str(e)[:120])

    # 發佈到 GitHub Pages（設定好才會啟用；失敗不影響本機儀表板）
    if getattr(cfg, "PUBLISH_ENABLED", False):
        try:
            import publish
            log("發佈到 GitHub Pages：%s" % publish.publish_site())
        except Exception as e:
            log("發佈失敗（本機儀表板不受影響）：%s" % str(e)[:160])

    if open_browser:
        try:
            os.startfile(cfg.OUTPUT_HTML)  # Windows
        except Exception:
            import webbrowser
            webbrowser.open("file://" + cfg.OUTPUT_HTML.replace("\\", "/"))
    return result


if __name__ == "__main__":
    self_update()                          # 先自我更新（有新版會重啟自己）
    run(open_browser=("--open" in sys.argv))

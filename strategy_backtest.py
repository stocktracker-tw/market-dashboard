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
BIASES = [("逆勢", 1.0), ("趨勢中性", 0.5), ("順勢", 0.0)]

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

    # 各立場逐月分數 → 倍數
    log("逐月計算分數（三種立場）…")
    orig = getattr(cfg, "MEAN_REVERSION_BIAS", 1.0)
    score_mult = {b: {} for _, b in BIASES}
    for _, b in BIASES:
        cfg.MEAN_REVERSION_BIAS = b
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
            comp = scoring.aggregate(inds)["composite"] if inds else 50.0
            score_mult[b][key] = scoring._interpret(comp)[2]
    cfg.MEAN_REVERSION_BIAS = orig

    # 各資產 × 策略 模擬
    results = {}
    for sym, label in ASSETS:
        amap = tw_map if sym == "0050.TW" else spy_map
        keys = [k for k in master if k in amap]
        if len(keys) < 12:
            continue
        rows = {"固定定額": simulate(keys, amap, lambda k: 1.0)}
        for bname, b in BIASES:
            rows["主動・" + bname] = simulate(keys, amap, lambda k, b=b: score_mult[b][k])
        results[sym] = {"label": label, "rows": rows, "keys": keys}

    render_html(results, master)
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


# ---------------- HTML ----------------
def render_html(results, master):
    C = {"green": "#28c76f", "amber": "#f6a821", "red": "#ea5455", "accent": "#5b9cff"}
    chart_data = {}
    parts = []
    parts.append("""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>策略回測：主動 vs 固定定期定額</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body{margin:0;background:#0e1116;color:#e7ebf3;font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:980px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:22px;margin:0 0 4px}.sub{color:#94a0b4;font-size:13px;margin-bottom:18px}
a{color:#5b9cff}
.card{background:#171b24;border:1px solid #2a3142;border-radius:14px;padding:16px 18px;margin-bottom:18px}
h2{font-size:17px;margin:0 0 10px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #222936}
th:first-child,td:first-child{text-align:left}
thead th{color:#94a0b4;font-weight:600}
.best{color:#28c76f;font-weight:700}
.chart{height:420px;margin-top:16px}
.note{background:rgba(246,168,33,.10);border:1px solid rgba(246,168,33,.35);color:#ffd98a;
  padding:10px 14px;border-radius:10px;font-size:12.5px;margin-bottom:18px}
.foot{margin-top:24px;padding-top:14px;border-top:1px solid #2a3142;color:#94a0b4;font-size:12px}
</style></head><body>""")
    from dashboard import nav
    parts.append(nav("index", include_css=True))   # 回測＝大盤子頁，分頁列高亮「大盤」
    parts.append('<div class="wrap">')
    parts.append('<h1>策略回測：主動 vs 固定定期定額</h1>')
    parts.append('<div class="sub">每月投一筆；主動＝每月投入 × 當月分數倍數(0.25–2x)。'
                 '區間 %s ~ %s。</div>' % (master[0], master[-1]))
    parts.append('<div class="note">⚠️ 重要限制：此回測的「分數」<b>不含籌碼面</b>（法人/融資歷史太短），'
                 '只用恐慌/估值/趨勢/總經；CPI 與景氣信號為月資料有輕微 look-ahead。'
                 '結論高度 regime-dependent：過去十年大多頭環境對逆勢策略先天不利。本頁為邏輯驗證、'
                 '<b>非投資建議</b>。</div>')

    for sym, blk in results.items():
        parts.append('<div class="card"><h2>%s <span style="color:#94a0b4;font-size:13px">%s</span></h2>'
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
        parts.append('<div style="font-size:11.5px;color:#94a0b4;margin-top:4px">'
                     '上圖＝每元投入的帳戶價值（帳戶市值÷已投入金額，兩條都從 1.0 出發，越高＝每塊錢越有效率）。</div>')
        parts.append("</div>")
        chart_data[sym] = {
            "labels": blk["rows"]["固定定額"]["labels"],
            "fixed": [round(x, 3) for x in blk["rows"]["固定定額"]["efficiency"]],
            "active": [round(x, 3) for x in blk["rows"]["主動・逆勢"]["efficiency"]],
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
    legend:{data:['固定定額','主動・逆勢'],textStyle:{color:'#cdd5e3'},top:0},
    tooltip:{trigger:'axis'},
    xAxis:{type:'category',data:d.labels,axisLabel:{color:'#8590a3',fontSize:10}},
    yAxis:{type:'value',scale:true,axisLabel:{color:'#8590a3',fontSize:10}},
    series:[{name:'固定定額',type:'line',data:d.fixed,smooth:true,symbol:'none',lineStyle:{color:'#94a0b4',width:2}},
            {name:'主動・逆勢',type:'line',data:d.active,smooth:true,symbol:'none',lineStyle:{color:C.accent,width:2}}]});
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

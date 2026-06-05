#!/usr/bin/env python3
"""盤前預估分數：用美股隔夜（台積電 ADR / 費半 / 標普）估算今天大盤偏多偏空。

不碰外部評分引擎——讀 index.html 裡引擎已算好的「昨收 composite」，自己抓
隔夜行情、算出盤前預估分數，再把一個「盤前預估・非正式」的徽章注入 index.html。
收盤後引擎重生頁面會蓋掉它，隔天早上的排程再算一次（見 PREMARKET_SCORE.md）。

用法:
    python scripts/premarket_score.py            # 抓行情、算分、寫回 index.html
    python scripts/premarket_score.py --dry-run  # 只印出，不改檔
    python scripts/premarket_score.py --self-test # 不連網，用假資料測算法/注入

行情來源：先試 Yahoo，失敗改用 Stooq（資料中心 IP 較不會被擋）。
全部抓不到時：不動 index.html（寧可不顯示，也不顯示壞掉的數字）。
"""
import csv
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

# 領先指標（台指夜盤 Yahoo/Stooq 抓不到，採 PREMARKET_SCORE.md 的 fallback 配置）
# 每個指標給 Yahoo 與 Stooq 兩種代號；SEMI 用 SOXX ETF 當費半的可靠代理。
INSTRUMENTS = {
    "ADR":  {"weight": 0.60, "name": "ADR",  "yahoo": "TSM",   "stooq": "tsm.us"},
    "SEMI": {"weight": 0.25, "name": "費半", "yahoo": "^SOX",  "stooq": "soxx.us"},
    "SPX":  {"weight": 0.15, "name": "標普", "yahoo": "^GSPC", "stooq": "^spx"},
}
K = 3.0          # 敏感度：隔夜每 +1% ≈ +3 分
DELTA_CAP = 12   # 偏移上下限，避免暴衝

PREMARKET_RE = re.compile(r'<div id="premarket".*?</div>', re.S)
# 主分數區塊：<h2>進場分數 NN</h2><p>……</p>
VERDICT_RE = re.compile(r'(<h2>進場分數\s*\d+</h2><p>.*?</p>)', re.S)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()


def _pct(prev, last):
    if prev in (None, 0) or last is None:
        raise ValueError("收盤資料不足")
    return (last - prev) / prev * 100.0


def fetch_yahoo(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(sym) + "?range=5d&interval=1d")
    closes = json.loads(_get(url))["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    closes = [c for c in closes if c is not None]
    return _pct(closes[-2], closes[-1])


def fetch_stooq(sym):
    url = "https://stooq.com/q/d/l/?s=" + urllib.parse.quote(sym) + "&i=d"
    rows = list(csv.DictReader(io.StringIO(_get(url))))
    closes = [float(r["Close"]) for r in rows if r.get("Close") not in (None, "", "N/D")]
    return _pct(closes[-2], closes[-1])


def fetch_change_pct(inst):
    """先 Yahoo 後 Stooq，回傳最近一個交易日收盤漲跌 %。"""
    errs = []
    for src, sym in (("yahoo", inst["yahoo"]), ("stooq", inst["stooq"])):
        try:
            return (fetch_yahoo if src == "yahoo" else fetch_stooq)(sym)
        except Exception as e:
            errs.append(f"{src}:{e}")
    raise RuntimeError("；".join(errs))


def read_composite(html):
    """從 index.html 取引擎算好的昨收 composite。"""
    m = re.search(r'"composite":\s*([0-9.]+)', html)
    if not m:
        raise SystemExit("index.html 找不到 composite")
    return float(m.group(1))


def band_phrase(score):
    """分數 → 盤前一句話（與 SCORING_LABELS.md 區間一致）。"""
    if score >= 80: return "積極加碼區，數據明顯偏多"
    if score >= 65: return "加碼區，偏多逢回分批"
    if score >= 55: return "中性偏多，維持定額略可加"
    if score >= 45: return "中性區，維持原本節奏"
    if score >= 35: return "中性偏空，維持定額別追高"
    if score >= 20: return "減碼觀望區，偏謹慎留銀彈"
    return "保守防禦區，風險偏高先保守"


def compute(composite, changes):
    """changes: {canon_key: pct}。回傳 (premarket_score, delta, basis_str)。"""
    have = [k for k in INSTRUMENTS if k in changes]
    wsum = sum(INSTRUMENTS[k]["weight"] for k in have)
    ovn = sum(INSTRUMENTS[k]["weight"] * changes[k] for k in have)
    if wsum > 0:  # 缺指標時把權重正規化回總和，避免低估
        ovn = ovn / wsum * sum(i["weight"] for i in INSTRUMENTS.values())
    delta = max(-DELTA_CAP, min(DELTA_CAP, ovn * K))
    score = int(round(max(0, min(100, composite + delta))))
    basis = " / ".join(f"{INSTRUMENTS[k]['name']} {changes[k]:+.1f}%" for k in have)
    return score, round(delta, 1), basis


def badge_html(score, basis):
    phrase = band_phrase(score)
    return (
        '<div id="premarket" style="margin:8px 0 2px;padding:7px 11px;'
        'border-radius:10px;background:rgba(120,140,170,.14);'
        'border:1px solid rgba(140,160,190,.28);font-size:12.5px;'
        'line-height:1.5;color:#c4d0e0">'
        f'📡 盤前預估 <b>{score}</b>・非正式 — {phrase}。<br>'
        f'<span style="color:#9fb0c4">依昨晚美股估算（{basis}），'
        '收盤後更新正式分數。</span></div>'
    )


def inject(html, badge):
    """移除舊的盤前徽章（冪等），把新的接在主分數段落後。"""
    html = PREMARKET_RE.sub('', html)
    if not VERDICT_RE.search(html):
        raise SystemExit("index.html 找不到主分數區塊，無法注入盤前徽章")
    return VERDICT_RE.sub(lambda m: m.group(1) + badge, html, count=1)


def main():
    dry = "--dry-run" in sys.argv
    if "--self-test" in sys.argv:
        html = open(INDEX, encoding="utf-8").read()
        comp = read_composite(html)
        changes = {"ADR": -2.24, "SEMI": -2.0, "SPX": -0.6}  # 假資料：昨晚美股收黑
        score, delta, basis = compute(comp, changes)
        out = inject(html, badge_html(score, basis))
        assert out.count('id="premarket"') == 1, "注入應只有一個徽章"
        out2 = inject(out, badge_html(score, basis))   # 冪等
        assert out2.count('id="premarket"') == 1, "重跑不應重複注入"
        print(f"[self-test] composite={comp} → 盤前 {score}（delta {delta}）｜{basis}")
        print("[self-test] 注入冪等 OK")
        return

    html = open(INDEX, encoding="utf-8").read()
    composite = read_composite(html)
    changes = {}
    for key, inst in INSTRUMENTS.items():
        try:
            changes[key] = fetch_change_pct(inst)
        except Exception as e:
            print(f"⚠️ 抓 {inst['name']} 失敗：{e}", file=sys.stderr)
    if not changes:
        print("⚠️ 沒抓到任何隔夜行情，保持原樣不動 index.html。", file=sys.stderr)
        return
    score, delta, basis = compute(composite, changes)
    print(f"昨收 composite={composite} → 盤前預估 {score}（delta {delta:+}）｜{basis}")
    if dry:
        print(badge_html(score, basis))
        print("\n[dry-run] 沒有改檔。")
        return
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(inject(html, badge_html(score, basis)))
    print("已寫入 index.html ✓")


if __name__ == "__main__":
    main()

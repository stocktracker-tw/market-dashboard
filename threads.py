# -*- coding: utf-8 -*-
"""每日 Threads 貼文產生器：讀 data/raw_latest.json 產生「今日進場分數」貼文 +
輪播一則常青貼文，輸出 output/threads.html（手機開 → 一鍵複製 → 貼到 Threads）。非投資建議。"""
import datetime as dt
import json
import os

import config as cfg

URL = "https://stocktracker-tw.github.io/market-dashboard/"

POOL = [
    "散戶最愛在新聞一片看好、綠燈全亮時 all in，\n但那常是法人開始偷偷減碼的時候。\n"
    "我把「法人買超 vs 散戶融資」做成背離訊號，就是要抓這個。\n👉 " + URL + "\n#台股 #籌碼面",

    "只看一個指標會被騙。我同時看三層：\n🎯 進場分數（便不便宜）\n🔥 噴發脆弱度（有沒有過熱）\n"
    "🧭 景氣位置（循環哪一格）\n三個一起看，才不會在高點還傻傻加碼。\n👉 " + URL,

    "你進場前最常看哪個？\nA 技術線型　B 法人籌碼　C 估值本益比　D 純無腦定期定額\n留言告訴我 👇",

    "「主動定額」真的贏「無腦定期定額」嗎？\n我拿 0050、SPY 跑了回測，不喊單、只看數據。\n👉 "
    + URL + "backtest.html\n#定期定額 #回測",

    "我受不了每次想加碼都在猜「現在是不是高點」，\n所以自己做了一個工具：把恐慌、估值、籌碼、景氣循環…\n"
    "幾十項指標壓成一個 0–100 分數。台股美股、每天更新、免費。\n👉 " + URL,
]


def _raw():
    p = os.path.join(getattr(cfg, "DATA_DIR", "data"), "raw_latest.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_daily_post():
    d = _raw()
    score = d.get("composite")
    band = d.get("band") or ""
    if score is None:
        return None
    s = round(score)
    if score >= 58:
        take = "分數偏高，偏向可較積極地分批佈局。"
    elif score < 42:
        take = "分數偏低，偏謹慎：別追高，留點銀彈等更好的價位。"
    else:
        take = "中性，維持原本的定期定額節奏即可。"
    return ("📊 今日台股進場分數 %d（%s）\n\n%s\n\n越高＝越適合分批加碼；越低＝越該保守。\n"
            "完整數據 👉 %s\n⚠️ 非投資建議\n#台股 #進場時機 #定期定額" % (s, band, take, URL))


_CSS = """<style>
body{margin:0;background:#0a0a16;color:#eef1f8;font-family:"Microsoft JhengHei",system-ui;line-height:1.6;
 background-image:radial-gradient(900px 500px at 50% -8%,rgba(255,46,136,.20),transparent 60%)}
.wrap{max-width:620px;margin:0 auto;padding:24px 18px 70px}
h1{font-size:21px;margin:.2em 0}.muted{color:#9aa4be;font-size:13px}
.card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:18px;padding:16px;margin:14px 0}
.post{white-space:pre-wrap;font-size:15px;color:#f1f4fb}
.row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
button,a.btn{padding:11px 18px;border-radius:999px;font-weight:700;font-size:14px;border:1px solid transparent;cursor:pointer;text-decoration:none;display:inline-block}
.cp{background:linear-gradient(95deg,#ff2e88,#ff4fb6);color:#fff}
.go{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.14);color:#eef1f8}
h2{font-size:15px;margin:22px 0 4px;color:#ffd0e8}
</style>"""


def render_threads_page():
    daily = build_daily_post()
    idx = dt.date.today().toordinal() % len(POOL)
    extra = POOL[idx]
    gen = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def block(title, pid, text):
        return ('<h2>%s</h2><div class="card"><div class="post" id="%s">%s</div>'
                '<div class="row"><button class="cp" onclick="cp(\'%s\',this)">📋 複製</button>'
                '<a class="go" href="https://www.threads.net/" target="_blank">去 Threads 發 →</a></div></div>'
                % (title, pid, esc(text), pid))

    parts = ['<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">',
             '<title>今日 Threads 貼文</title>', _CSS, '</head><body><div class="wrap">',
             '<h1>📱 今日 Threads 貼文</h1>',
             '<div class="muted">每天資料更新後自動產生・%s ・複製貼上即可</div>' % esc(gen)]
    if daily:
        parts.append(block("① 今日進場分數（建議每天發）", "p1", daily))
    parts.append(block("② 今日輪播貼文（常青內容）", "p2", extra))
    parts.append('<div class="muted" style="margin-top:18px">小技巧：晚上 8–10 點發觸及最好；'
                 '把這頁加到主畫面，每天點一下複製就好。非投資建議。</div>')
    parts.append('<script>function cp(id,b){var t=document.getElementById(id).innerText;'
                 'navigator.clipboard.writeText(t).then(function(){var o=b.textContent;b.textContent="已複製 ✓";'
                 'setTimeout(function(){b.textContent=o;},1500);});}</script>')
    parts.append('</div></body></html>')
    html = "".join(parts)
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(cfg.OUTPUT_DIR, "threads.html"), "w", encoding="utf-8") as f:
        f.write(html)
    if daily:
        with open(os.path.join(getattr(cfg, "DATA_DIR", "data"), "threads_today.txt"), "w", encoding="utf-8") as f:
            f.write(daily + "\n\n---\n\n" + extra + "\n")
    return "threads.html"


if __name__ == "__main__":
    print(build_daily_post())
    print("wrote", render_threads_page())

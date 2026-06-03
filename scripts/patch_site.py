#!/usr/bin/env python3
"""外部 Bot 每天重產 HTML 後，自動補回瀏覽器分頁需要的東西：
  1) <link rel="icon">  → 子路徑網站不寫這行，分頁就會顯示預設地球
  2) 品牌前綴標題        → 「Stock Tracker — 原本頁名」
  3) 評分分界一致性      → 中性（正常定額）下界固定為 43（避免 Bot 退回 45 時，
                          43–44 分被標成「減碼」、和內文「中性」打架）

設計成「冪等」：已經補過的檔案再跑一次不會有任何變動，
所以這支腳本只有在 Bot 把修改洗掉時才會真的產生 diff。
"""
import glob
import re

# 分頁圖示（帶 ?v= 以繞過頑固的 favicon 快取）
FAVICON = ('<link rel="icon" href="favicon.ico?v=1">'
           '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png?v=1">')
BRAND = "Stock Tracker"

APPLE_RE = re.compile(r'<link rel="apple-touch-icon"[^>]*>')
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.S)

# --- 評分一致性 -----------------------------------------------------------
# 中性（正常定額）下界。Bot 若退回舊的 45，43–44 分會被標成「減碼」與內文打架。
NEUTRAL_LOW = 43
# 圖例分界正規化：把舊的 45 分界字樣改回 43（沒有就不動）
LEGEND_FIXES = [
    (">35–45 減碼<", ">35–43 減碼<"),
    (">45–58 正常定額<", ">43–58 正常定額<"),
]
# 中性段的精準輸出（只在 43–44 被標錯時才套用）
NEUTRAL_BADGE = ('<span class="badge" style="background:var(--amber);'
                 'color:#0e1116">中性（正常定額）</span>')
NEUTRAL_VERDICT = "中性，維持原本的定期定額節奏即可。"
COMPOSITE_RE = re.compile(r'"composite":\s*([0-9.]+)')
# 徽章 + 分數 h2 + 評語 三件一組
VERDICT_RE = re.compile(
    r'<span class="badge" style="background:[^"]*;color:#0e1116">[^<]*</span>'
    r'(<h2>進場分數 [0-9.]+</h2>)'
    r'<p>[^<]*</p>'
)


# --- 直覺化 UX --------------------------------------------------------------
# 「這個分數怎麼用」說明盒（原生 <details>，免 JS；以 id="howto" 判斷是否已注入）
HOWTO_BOX = (
    '<details id="howto" style="margin:0 0 22px;background:linear-gradient('
    '180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));border:1px solid '
    'rgba(255,255,255,.1);border-radius:16px;padding:14px 16px">'
    '<summary style="cursor:pointer;font-weight:700;font-size:14px">'
    '❓ 這個分數是什麼？我該怎麼用？</summary>'
    '<div style="font-size:13px;color:#aab4c6;margin-top:10px;line-height:1.7">'
    '我把下面這些指標壓成一個 0–100 分：<br>'
    '· <b style="color:#34d07f">分數高</b>＝數據偏多，這個月定期定額可以<b>比平常多扣一點</b><br>'
    '· <b style="color:#ef5d5d">分數低</b>＝偏空，<b>少扣、留點銀彈</b>等更好的價位<br>'
    '· <b>43–58＝中性</b>，維持原本節奏就好<br>'
    '重點：這<b>不是</b>叫你買哪一支股票，而是幫你決定「這個月該<b>積極還是保守</b>」。'
    '⚠️ 非投資建議</div></details>'
)
SCORE_H2_RE = re.compile(r'(<h2>進場分數 )(\d+(?:\.\d+)?)(</h2>)')
UX_TEXT_FIXES = [
    # 副標白話化
    ("綜合進場分數越高＝越適合分批加碼（較主動的定期定額）",
     "分數越高＝越適合多扣一點（定期定額積極些）；越低＝越該少扣、保守"),
    # 倍數區術語白話化
    ("已含<b>消息面微調", "已參考<b>今日新聞情緒微調"),
]


def patch_ux(html):
    """讓儀表板更直覺：說明盒、分數顯示整數、用詞白話化。"""
    changed = False

    # #1 說明盒：注入在五大支柱之前（已注入則略過）
    if 'id="howto"' not in html and '<div class="pillars">' in html:
        html = html.replace('<div class="pillars">',
                            HOWTO_BOX + '<div class="pillars">', 1)
        changed = True

    # #2 分數顯示整數：標題 h2 與儀表板 gauge 都四捨五入
    def round_h2(m):
        return m.group(1) + str(int(float(m.group(2)) + 0.5)) + m.group(3)
    new = SCORE_H2_RE.sub(round_h2, html, count=1)
    if new != html:
        html = new
        changed = True
    if "value:DASH.composite}" in html:
        html = html.replace("value:DASH.composite}",
                            "value:Math.round(DASH.composite)}")
        changed = True

    # #3 用詞白話化
    for old, new in UX_TEXT_FIXES:
        if old in html:
            html = html.replace(old, new)
            changed = True

    return html, changed


def patch_scoring(html):
    """只處理會因『45 vs 43 分界』而標錯的唯一區間，其餘一律不碰 Bot 輸出。"""
    changed = False

    # A) 圖例分界一律正規化成 43
    for old, new in LEGEND_FIXES:
        if old in html:
            html = html.replace(old, new)
            changed = True

    # B) 只有當分數落在 43–44（會因分界不同而標錯）且徽章不是中性時，才修正
    m = COMPOSITE_RE.search(html)
    if m:
        score = float(m.group(1))
        if NEUTRAL_LOW <= score < 45:
            vm = VERDICT_RE.search(html)
            if vm and "中性（正常定額）" not in vm.group(0):
                fixed = NEUTRAL_BADGE + vm.group(1) + f"<p>{NEUTRAL_VERDICT}</p>"
                html = html[:vm.start()] + fixed + html[vm.end():]
                changed = True

    return html, changed


# --- Tab Bar 重排 + 改名 ----------------------------------------------------
# 招牌「進場分數」放第一格：大盤(進場) → 個股 → 觀點 → 消息
TAB_ORDER = ["index.html", "stocks.html", "perspectives.html", "news.html"]
NAV_RE = re.compile(r'(<nav class="tabbar">)(.*?)(</nav>)', re.S)
ANCHOR_RE = re.compile(
    r'<a class="tab[^"]*" href="((?:index|stocks|perspectives|news)\.html)">.*?</a>')
TAB_RENAME = ('<span class="ic">📊</span><span>大盤</span>',
              '<span class="ic">📊</span><span>進場</span>')
OLD_ORDER_JS = 'order=["news.html","index.html","perspectives.html","stocks.html"]'
NEW_ORDER_JS = 'order=["index.html","stocks.html","perspectives.html","news.html"]'
OLD_CURIDX = ('if(f==="news.html")return 0;if(f==="perspectives.html")return 2;'
              'if(f==="stocks.html")return 3;return 1;')
NEW_CURIDX = ('if(f==="stocks.html")return 1;if(f==="perspectives.html")return 2;'
              'if(f==="news.html")return 3;return 0;')


def _reorder_nav(m):
    inner = m.group(2)
    by_href = {am.group(1): am.group(0) for am in ANCHOR_RE.finditer(inner)}
    if set(by_href) != set(TAB_ORDER):  # 結構不符就保險不動
        return m.group(0)
    return m.group(1) + "".join(by_href[h] for h in TAB_ORDER) + m.group(3)


def patch_tabbar(html):
    """把招牌大盤移到第一格、改名「進場」，並同步拖曳 JS 的順序與 curIdx。"""
    if '<nav class="tabbar">' not in html:
        return html, False
    orig = html
    html = NAV_RE.sub(_reorder_nav, html, count=1)   # 1) 重排
    html = html.replace(*TAB_RENAME)                  # 2) 大盤→進場
    html = html.replace(OLD_ORDER_JS, NEW_ORDER_JS)   # 3) 拖曳順序陣列
    html = html.replace(OLD_CURIDX, NEW_CURIDX)       # 4) curIdx 對應
    return html, (html != orig)


def patch(html):
    changed = False

    # 1) favicon：沒有就補在 apple-touch-icon 連結前面
    if 'rel="icon" href="favicon' not in html:
        m = APPLE_RE.search(html)
        if m:
            html = html[:m.start()] + FAVICON + html[m.start():]
            changed = True

    # 2) 標題加品牌前綴（已加過則略過）
    def repl(m):
        t = m.group(1).strip()
        if not t or t.startswith(BRAND):
            return m.group(0)
        return f"<title>{BRAND} — {t}</title>"

    new = TITLE_RE.sub(repl, html, count=1)
    if new != html:
        html = new
        changed = True

    # 3) 評分一致性 + 直覺化 UX（只有含評語區塊的儀表板頁才處理）
    if 'class="verdict"' in html:
        html, sc = patch_scoring(html)
        changed = changed or sc
        html, ux = patch_ux(html)
        changed = changed or ux

    # 4) Tab Bar 重排 + 改名（所有有導覽列的頁面）
    html, tb = patch_tabbar(html)
    changed = changed or tb

    return html, changed


def main():
    touched = []
    for f in sorted(glob.glob("*.html")):
        s = open(f, encoding="utf-8").read()
        # 只處理使用者頁面（有 apple-touch-icon 的那幾頁）
        if APPLE_RE.search(s) is None:
            continue
        new, changed = patch(s)
        if changed:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            touched.append(f)
    print("已補丁：" + (", ".join(touched) if touched else "(無需變更)"))


if __name__ == "__main__":
    main()

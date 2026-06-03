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

    # 3) 評分一致性（只有含評語區塊的頁面才處理）
    if 'class="verdict"' in html:
        html, sc = patch_scoring(html)
        changed = changed or sc

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

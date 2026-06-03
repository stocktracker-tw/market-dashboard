#!/usr/bin/env python3
"""外部 Bot 每天重產 HTML 後，自動補回瀏覽器分頁需要的東西：
  1) <link rel="icon">  → 子路徑網站不寫這行，分頁就會顯示預設地球
  2) 品牌前綴標題        → 「Stock Tracker — 原本頁名」

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

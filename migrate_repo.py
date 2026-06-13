# -*- coding: utf-8 -*-
"""乾淨搬家：建新 repo（空白歷史）→ 用 bot 身分推送網站 → 開 Pages → 驗證後刪舊 repo。
新 repo = config.GITHUB_REPO（stocktracker-tw.github.io，根目錄站台）。一次性。"""
import time

import requests

import config as cfg
import publish

H = publish._headers()
OWNER = cfg.GITHUB_USER            # stocktracker-tw
NEW = cfg.GITHUB_REPO              # stocktracker-tw.github.io
OLD_OWNER, OLD_REPO = "stocktracker-tw", "market-dashboard"

FILES = ["stocks.html", "news.html", "backtest.html", "landing.html",
         "manifest.webmanifest", "sw.js",
         "icon-512.png", "icon-192.png", "icon-180.png", "apple-icon-v9.png", "glassmap.png",
         "cover.png", "promo_sq.png", "post_pillars.png", "post_layers.png"]


def main():
    # 1) 建立新 repo（不能建就中止，不做任何破壞）
    r = requests.post("https://api.github.com/user/repos", headers=H,
                      json={"name": NEW, "private": False, "auto_init": False,
                            "description": "Stock Tracker — 台股美股進場時機儀表板"}, timeout=30)
    if r.status_code == 201:
        print("created repo:", NEW)
    else:
        g = requests.get("https://api.github.com/repos/%s/%s" % (OWNER, NEW), headers=H, timeout=20)
        if g.status_code == 200:
            print("repo already exists, continue:", NEW)
        else:
            print("CREATE FAILED:", r.status_code, (r.json() or {}).get("message"))
            print(">> 權杖沒有建立 repo 的權限。請在 GitHub 手動建一個 Public repo 叫", NEW, "再重跑我。")
            return
    time.sleep(2)

    # 2) 推送（publish 會用 config 的新 repo + bot committer，無 gmail）
    ok = []
    try:
        publish.publish_html(); ok.append("index.html")
    except Exception as e:
        print("index.html ERR", e)
    for fn in FILES:
        try:
            if publish.publish_extra(fn, "init " + fn):
                ok.append(fn)
        except Exception as e:
            print(fn, "ERR", e)
    print("pushed %d files" % len(ok))

    # 3) 開 Pages
    try:
        print("enable pages:", publish.enable_pages())
    except Exception as e:
        print("pages note:", e)

    # 4) 驗證新 repo 有 index（不自動刪舊 repo —— 刪 repo 由你本人操作）
    chk = requests.get("https://api.github.com/repos/%s/%s/contents/index.html" % (OWNER, NEW),
                       headers=H, timeout=20)
    print("verify index in new repo:", chk.status_code, "(200=ok)")
    print("NEW URL: https://%s/" % NEW)
    print("landing: https://%s/landing.html" % NEW)
    print(">> 舊 repo 的 gmail 歷史仍在 %s/%s —— 請你到該 repo Settings → Delete this repository 親手刪除。"
          % (OLD_OWNER, OLD_REPO))


if __name__ == "__main__":
    main()

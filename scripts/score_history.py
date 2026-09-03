#!/usr/bin/env python3
"""維護大盤分數的每日歷史，給「贏過歷史上 N%」那句話當依據。

背景：那句話原本的 N 就是分數本身——連續 21 天兩個數字完全相同。分數是四大
支柱的加權合成、再用固定門檻查表（見 SCORING_LABELS.md），不是歷史排名，
所以那句話是在宣稱一個從來沒算過的統計事實。

這支負責把「真的算得出來」的資料備齊：
  --backfill  一次性：走 index.html 的 git 歷史，把每天的分數挖出來
  （不帶參數）每天：把今天的分數併進 score_history.json

引擎那邊沒有對外的分數序列，backtest 頁自己也寫「樣本涵蓋期間短」(n≈80~101)，
所以能拿到的就是這個 repo 自己的 commit 歷史。天數會隨時間長，文案也會跟著
把樣本數寫出來，不會假裝那是很長的歷史。
"""
import json
import os
import re
import subprocess
import sys

OUT = "score_history.json"
SCORE_RE = re.compile(r"今天大盤\s*(\d+)\s*分")


def load():
    try:
        d = json.load(open(OUT, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:                                          # noqa: BLE001
        return {}


def save(d):
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(d.items())), fh, ensure_ascii=False, indent=0)
        fh.write("\n")


def score_of(html):
    m = SCORE_RE.search(html or "")
    return int(m.group(1)) if m else None


def backfill():
    log = subprocess.run(
        ["git", "log", "--format=%H %ad", "--date=short", "--", "index.html"],
        capture_output=True, text=True).stdout
    hist = load()
    added = 0
    # git log 由新到舊；同一天有多個 commit 時，先看到的是當天最後一次，用它
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, date = line.split()
        if date in hist:
            continue
        html = subprocess.run(["git", "show", "%s:index.html" % sha],
                              capture_output=True, text=True).stdout
        s = score_of(html)
        if s is not None:
            hist[date] = s
            added += 1
    save(hist)
    print("回填：新增 %d 天，目前共 %d 天" % (added, len(hist)))
    return 0


def today():
    if not os.path.exists("index.html"):
        print("::warning::沒有 index.html，跳過")
        return 0
    s = score_of(open("index.html", encoding="utf-8").read())
    if s is None:
        print("::warning::index.html 裡找不到大盤分數，跳過")
        return 0
    date = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short"],
                          capture_output=True, text=True).stdout.strip()
    if not date:
        print("::warning::拿不到日期，跳過")
        return 0
    hist = load()
    if hist.get(date) == s:
        print("分數歷史：%s 已是 %d，無變更" % (date, s))
        return 0
    hist[date] = s
    save(hist)
    print("分數歷史：%s = %d（共 %d 天）" % (date, s, len(hist)))
    return 0


if __name__ == "__main__":
    sys.exit(backfill() if "--backfill" in sys.argv[1:] else today())

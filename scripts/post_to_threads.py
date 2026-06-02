#!/usr/bin/env python3
"""自動發文到 Threads（Meta 官方 Threads API）。

用法:
    python scripts/post_to_threads.py morning   # 發「今日進場分數」
    python scripts/post_to_threads.py evening   # 發 金句 或 互動（依日期交替）
    python scripts/post_to_threads.py --dry-run morning   # 只印出內容，不真的發

需要的環境變數（GitHub Secrets）:
    THREADS_USER_ID        你的 Threads 數字 user id
    THREADS_ACCESS_TOKEN   長效 access token

發文流程是 Threads API 的兩步驟：
    1) 建立 media container  -> 拿到 creation_id
    2) publish 該 container  -> 正式發出
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone, timedelta

API = "https://graph.threads.net/v1.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREADS_HTML = os.path.join(ROOT, "threads.html")

# 與 threads.html 的池保持一致 ----------------------------------------------
QUOTES = [
    "進場時機不是「猜對最低點」，\n是「在數據站在你這邊的時候，下手重一點；\n數據對你不利的時候，手輕一點」。\n\n如此而已。\n⚠️ 非投資建議",
    "別人恐懼我貪婪這句話，問題在——\n你怎麼知道現在「夠恐懼」了？\n\n恐懼是可以量化的。\nVIX、融資餘額、騰落線、估值分位…全部壓成一個數字。\n⚠️ 非投資建議",
    "定期定額不是「不用看時機」，\n是「就算看錯時機也不會死」。\n\n但如果你願意在低分時多扣一點、高分時少扣一點，\n長期報酬會差很多。\n⚠️ 非投資建議",
    "散戶最容易賠錢的時刻，不是崩盤，\n是「指數創高、新聞一片樂觀、身邊每個人都在賺」的時候。\n\n學會看法人跟散戶在做相反的事，比看 K 線有用太多。\n⚠️ 非投資建議",
    "噴發很爽，但越急的噴出、回檔通常越兇。\n\n會漲不稀奇，知道「現在這波是健康還是上頭」才值錢。\n⚠️ 非投資建議",
    "市場不會獎勵勤勞，只會獎勵紀律。\n\n每天看盤十小時，不如有一套「該貪婪還是該怕」的判斷標準，\n然後乖乖照做。\n⚠️ 非投資建議",
]
POLLS = [
    "今天進場分數偏低。\n\nA）我會分批進，便宜才有肉\nB）我先觀望，等轉強再說\nC）我定期定額，根本不看分數\n\n你是哪一派？留言告訴我 👇",
    "一個問題：\n如果有個數字每天告訴你「現在該貪婪還是該怕」，\n你會每天看嗎？還是覺得這種東西不可靠？\n\n想聽真心話 👇",
    "你進場前，最常用哪個訊號做決定？\n\n① 技術線型　② 外資買賣超\n③ 本益比估值　④ 純感覺 / 新聞\n\n留言投一票 👇",
    "承認一下：你上次追高被套，是因為？\n\nA）新聞太樂觀忍不住\nB）看別人賺紅了眼\nC）以為這次不一樣\n\n我先承認我三個都中過 👇",
]


def taipei_today():
    """以台北時間決定『今天』，避免 UTC 跨日選錯內容。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def day_of_year(d):
    return d.timetuple().tm_yday


def score_post():
    """從 bot 每天更新的 threads.html 取出 ① 今日進場分數 的真實內容。"""
    with open(THREADS_HTML, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'<div class="post" id="p1">(.*?)</div>', html, re.S)
    if not m:
        raise SystemExit("找不到 threads.html 裡的進場分數區塊（id=p1）")
    text = m.group(1)
    # 還原 HTML，保留換行
    text = text.replace("<br>", "\n").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    return text.strip()


def evening_post(d):
    """偶數日發金句、奇數日發互動，並依日期在池中輪播。"""
    doy = day_of_year(d)
    if doy % 2 == 0:
        return QUOTES[doy % len(QUOTES)]
    return POLLS[doy % len(POLLS)]


def build_text(slot, d):
    if slot == "morning":
        return score_post()
    if slot == "evening":
        return evening_post(d)
    raise SystemExit(f"未知的 slot: {slot}（要 morning 或 evening）")


def _post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def publish(text):
    uid = os.environ["THREADS_USER_ID"]
    token = os.environ["THREADS_ACCESS_TOKEN"]
    created = _post(f"{API}/{uid}/threads", {
        "media_type": "TEXT",
        "text": text,
        "access_token": token,
    })
    creation_id = created["id"]
    # Threads 建議建立 container 後稍等再 publish
    time.sleep(5)
    result = _post(f"{API}/{uid}/threads_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })
    return result


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    slot = args[0] if args else "morning"
    d = taipei_today()
    text = build_text(slot, d)
    print(f"=== slot={slot}  date={d}  chars={len(text)} ===")
    print(text)
    if dry:
        print("\n[dry-run] 沒有真的發文。")
        return
    res = publish(text)
    print("\n已發文 ✓", json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()

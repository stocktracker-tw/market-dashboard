#!/usr/bin/env python3
"""抓股癌最新一集的節目簡介，寫成 gooaye.json 給 patch_site.py 用。

為什麼是「節目簡介」而不是逐字稿：股癌沒有公開逐字稿，要真的總結內容就得
下載音訊跑語音辨識，每集十幾分鐘的運算、而且把整集內容重製到公開網站有
版權疑慮。節目簡介是主持人自己寫的、可公開引用，成本也只有一次 HTTP。

失敗就原地不動（保留上一份 gooaye.json），絕不讓網站因為抓不到而開天窗。
"""
import html as htmllib
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# 節目 id 取自站上既有的 SoundOn 播放器連結
PODCAST_ID = "954689a5-3096-43a4-a80b-7810b219cef3"
# SoundOn 的 feed 網址型式沒有官方文件保證，多試幾種，第一個解析得出來的就用
FEEDS = [
    "https://feeds.soundon.fm/podcasts/%s.xml" % PODCAST_ID,
    "https://api.soundon.fm/v2/podcasts/%s/feed.xml" % PODCAST_ID,
    "https://player.soundon.fm/rss/%s" % PODCAST_ID,
]
OUT = "gooaye.json"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t　]+")
# 這個節目的簡介結構是「幾行本集重點」＋「一整段業配」。實測 EP693 的簡介
# 只有第一行在講內容，剩下全是烤肉組的品項與售價——照單全收會變成把廣告
# 貼到自己站上。所以碰到業配起點就整段截斷，而不是逐行過濾。
CUT = re.compile(
    r"(本集節目由|本集由|節目由.{0,12}贊助|贊助播出|贊助商|合作邀約|"
    r"業配|廣告|折扣碼|優惠碼|限定優惠|限時優惠|團購|"
    r"原價|特價|售價|下單|購買連結|使用代碼)", re.I)
# 截斷之後還可能有零星的通路樣板
NOISE = re.compile(
    r"(小額贊助|贊助|支持本節目|開啟小鈴鐺|訂閱|追蹤我|加入會員|"
    r"留言告訴我|Powered by|SoundOn|https?://|\$\s?\d|\d+\s?(kg|人份))", re.I)


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "stocktracker-tw/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def text_of(item, *tags):
    for t in tags:
        el = item.find(t)
        if el is not None and (el.text or "").strip():
            return el.text
    return ""


def clean(raw):
    """節目簡介可能是 HTML 也可能是純文字，統一成乾淨的行陣列。"""
    s = htmllib.unescape(raw or "")
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s, flags=re.I)
    s = TAG_RE.sub("", s)
    s = htmllib.unescape(s)
    lines = []
    for ln in s.splitlines():
        ln = WS_RE.sub(" ", ln).strip()
        if not ln:
            continue
        if CUT.search(ln):         # 業配開始了，後面整段不要
            break
        if NOISE.search(ln):
            continue
        if len(ln) < 4:            # 「---」「1.」這種殘留分隔符
            continue
        lines.append(ln)
        if len(lines) >= 6:        # 頁面上放不下更多，也不該整段搬過去
            break
    return lines


def main():
    last_err = None
    for url in FEEDS:
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:                      # noqa: BLE001 — 任何失敗都換下一個
            last_err = "%s → %s" % (url, e)
            continue
        item = root.find("./channel/item")
        if item is None:
            last_err = "%s → feed 裡沒有 item" % url
            continue
        title = (text_of(item, "title") or "").strip()
        link = (text_of(item, "link") or "").strip()
        pub = (text_of(item, "pubDate") or "").strip()
        body = text_of(item, CONTENT_NS, "description", ITUNES_NS)
        lines = clean(body)
        if not title:
            last_err = "%s → 最新一集沒有標題" % url
            continue
        m = re.search(r"EP\s*(\d+)", title, re.I)
        data = {
            "episode": ("EP" + m.group(1)) if m else "",
            "title": title,
            "url": link,
            "published": pub,
            "summary": lines,
            "source": url,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        old = None
        if os.path.exists(OUT):
            try:
                old = json.load(open(OUT, encoding="utf-8"))
            except Exception:                        # noqa: BLE001
                old = None
        # fetched_at 每次都會變，拿它比對會每天都產生 commit；比內容就好
        if old and {k: old.get(k) for k in ("episode", "title", "url", "published", "summary")} == \
                   {k: data[k] for k in ("episode", "title", "url", "published", "summary")}:
            print("股癌：%s 無變更" % (data["episode"] or title))
            return 0
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print("股癌：已更新 %s（%d 行簡介）" % (data["episode"] or title, len(lines)))
        return 0
    print("::warning::抓不到股癌 feed，沿用既有 %s。最後一個錯誤：%s" % (OUT, last_err))
    return 0


if __name__ == "__main__":
    sys.exit(main())

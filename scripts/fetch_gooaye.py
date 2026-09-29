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
# 「去聽」連結改到 Spotify。節目 id 取自 Spotify 上的「Gooaye 股癌」
# （open.spotify.com/show/<id>）。RSS 裡沒有 Spotify 的集數 id，要另外找。
SPOTIFY_SHOW = "1zWxx5pKk0XBEzMupVC7UZ"
SPOTIFY_SHOW_URL = "https://open.spotify.com/show/%s" % SPOTIFY_SHOW
SPOTIFY_EMBED = "https://open.spotify.com/embed/show/%s" % SPOTIFY_SHOW
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
EPISODE_URI_RE = re.compile(r"^spotify:episode:([A-Za-z0-9]{22})$")
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


def latest_item():
    """回傳 (item, feed_url)。"""
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
        return item, url
    raise RuntimeError(last_err or "沒有可用的 feed")


def guid_of(item):
    g = item.find("guid")
    if g is not None and (g.text or "").strip():
        return g.text.strip()
    return (text_of(item, "link") or "").strip()


def _walk(o):
    """把 JSON 裡的每一個 dict 都走過一遍。"""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def same_episode(title, cand):
    """是不是同一集：標題有 EP 編號就比編號（EP70 不會配到 EP700），
    沒有編號（特別集）就比整個標題。"""
    m = re.search(r"EP\s*(\d+)", title, re.I)
    if m:
        return re.search(r"EP\s*0*%s(?!\d)" % m.group(1), cand, re.I) is not None
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()   # noqa: E731
    return bool(norm(title)) and norm(title) == norm(cand)


def spotify_episode_url(title, page=None):
    """在 Spotify 上找這一集的網址；找不到回傳 None。

    沒有 Spotify API 金鑰可用，所以讀它公開的嵌入播放器頁：頁面裡的
    __NEXT_DATA__ 帶著節目的集數清單。這不是有文件保證的介面，所以不依賴
    固定路徑——走遍整份 JSON，找「同一個物件裡有 spotify:episode: 的 uri、
    而且標題是同一集」的那一個。版面怎麼搬都找得到，除非 Spotify 把欄位本身
    拿掉；真的找不到就交給呼叫端退回節目頁。page 參數是給測試餵假資料用的。"""
    try:
        if page is None:
            page = fetch(SPOTIFY_EMBED).decode("utf-8", "replace")
        m = NEXT_RE.search(page)
        if not m:
            return None
        data = json.loads(m.group(1))
    except Exception:                                   # noqa: BLE001 — 抓不到就交給退路
        return None
    for d in _walk(data):
        uri, name = d.get("uri"), d.get("title") or d.get("name")
        if not isinstance(uri, str) or not isinstance(name, str):
            continue
        mm = EPISODE_URI_RE.match(uri)
        if mm and same_episode(title, name):
            return "https://open.spotify.com/episode/" + mm.group(1)
    return None


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
        old = None
        if os.path.exists(OUT):
            try:
                old = json.load(open(OUT, encoding="utf-8"))
            except Exception:                        # noqa: BLE001
                old = None
        guid = guid_of(item)
        # Spotify 連結：先找這一集的網址。這次找不到、但上一次已經找到同一集的
        # （例如 Spotify 暫時連不上），沿用上一次的，不要降級成節目頁；都沒有才
        # 用節目頁——永遠是 Spotify 上存在的頁面，不會是死連結。Spotify 收錄
        # 新的一集常比 RSS 晚一點，這時先落到節目頁（最新一集就在最上面），
        # 下一輪（main 一天會更新好幾次）找到了就換成單集網址。
        sp = spotify_episode_url(title)
        if not sp and old and old.get("guid") == guid and \
                "/episode/" in (old.get("spotify_url") or ""):
            sp = old["spotify_url"]
        if not sp:
            print("::warning::Spotify 上還找不到「%s」，先連到股癌節目頁" % title)
            sp = SPOTIFY_SHOW_URL
        data = {
            "episode": ("EP" + m.group(1)) if m else "",
            "title": title,
            "url": link,
            "spotify_url": sp,
            "published": pub,
            "summary": lines,
            "source": url,
            "source_kind": "notes",
            "guid": guid,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        # fetched_at 每次都會變，拿它比對會每天都產生 commit；比內容就好。
        # spotify_url 要算進來：同一集從「節目頁」升級成「單集網址」也得寫檔。
        keys = ("episode", "title", "url", "spotify_url", "published", "summary")
        if old and {k: old.get(k) for k in keys} == {k: data[k] for k in keys}:
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

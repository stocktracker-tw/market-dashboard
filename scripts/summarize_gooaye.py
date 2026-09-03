#!/usr/bin/env python3
"""下載股癌最新一集的音訊，語音辨識成逐字稿，再請 Claude 摘要成幾行重點。

為什麼要這一支：節目的 RSS 簡介只有一行預告加一整段業配，內容不在裡面
（見 fetch_gooaye.py 的註解）。要真的知道「這集在講什麼」只能聽。

三個原則：
  1. 只發表摘要，逐字稿一律不進版控、跑完就刪。轉錄是為了理解，不是重製。
  2. 一集只做一次：gooaye.json 記 guid，同一集第二次執行直接跳過。
  3. 任何一步失敗都保留既有的 gooaye.json，網站退回節目簡介那版，不開天窗。

摘要後端預設是 Ollama（GOOAYE_LLM=ollama，不需要金鑰）；設成 anthropic 則走
Claude API 並需要 ANTHROPIC_API_KEY。後端不可用就整支跳過（不是錯誤）。
"""
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_gooaye as feed                                   # noqa: E402

OUT = "gooaye.json"
# 摘要用哪個 LLM：ollama（預設，不用金鑰）或 anthropic
BACKEND = os.environ.get("GOOAYE_LLM", "ollama").strip().lower()
MODEL = os.environ.get("GOOAYE_MODEL", "claude-opus-5")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("GOOAYE_OLLAMA_MODEL", "qwen2.5:7b")
# Ollama 預設 context 只有 2048~4096，一集兩萬多字會被無聲截掉大半，一定要設。
OLLAMA_CTX = int(os.environ.get("GOOAYE_OLLAMA_CTX", "32768"))
WHISPER_SIZE = os.environ.get("GOOAYE_WHISPER", "small")
# 逐字稿上限（字元）。一集約 2~2.7 萬字。走 Ollama 時要留在 context 裡面，
# 中文對 qwen 約 1~1.3 字/token，28k 字約 2.2 萬 token，塞得進 32k。
MAX_TRANSCRIPT = 28_000 if BACKEND == "ollama" else 120_000

SYSTEM = (
    "你在幫一個台股資訊網站整理 podcast 重點。使用者要的是「這集講了哪些有用的事」，"
    "不是逐字稿、不是宣傳文案、也不是主持人的日常閒聊。"
    "這個節目的開場與段落之間有大量閒扯，那些一律不算內容。"
)
PROMPT = """以下是一集 podcast 的語音辨識逐字稿（可能有辨識錯誤）。

請整理成最多 6 條重點，條件：

要寫的：市場與產業的判斷、對個股或題材的看法、數據與事件的解讀、
操作或風險上的提醒——也就是聽完之後真正有資訊量的部分。

一律不要寫（這個節目這類內容佔比很高，請確實濾掉）：
- 開場寒暄、天氣、吃喝、旅遊、身體狀況、家人朋友、遊戲、追劇等生活閒聊
- 業配、贊助、產品推銷、折扣、通路
- 聽眾來信互動、抽獎、社群徵求、節目宣傳
- 純粹的情緒發洩或玩笑，沒有帶出判斷的部分

格式：
- 每條 40 字以內，直述句，不要用「主持人認為」開頭堆疊
- 用繁體中文
- 只輸出重點本身，一行一條，不要編號、不要標題、不要前言後語
- 寧可少寫也不要湊數：只有 2 條有內容就只寫 2 條
- 如果整集幾乎都是閒聊或業配、沒有可寫的內容，只輸出一行：NO_CONTENT

逐字稿：
---
%s
---"""


def existing():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "stocktracker-tw/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return os.path.getsize(dest)


def _whisper_model():
    """有 GPU 就用 GPU。裝置寫死會讓這支只能在一種機器上跑——本機有顯卡、
    GitHub runner 沒有，兩邊都要能動，所以先試 cuda、失敗退回 CPU。"""
    from faster_whisper import WhisperModel
    want = os.environ.get("GOOAYE_WHISPER_DEVICE", "auto")
    if want in ("auto", "cuda"):
        try:
            m = WhisperModel(WHISPER_SIZE, device="cuda", compute_type="float16")
            print("Whisper：%s on cuda/float16" % WHISPER_SIZE)
            return m
        except Exception as e:                                 # noqa: BLE001
            if want == "cuda":
                raise
            print("沒有可用的 GPU（%s），改用 CPU" % str(e).split("\n")[0][:120])
    m = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    print("Whisper：%s on cpu/int8" % WHISPER_SIZE)
    return m


def transcribe(path):
    model = _whisper_model()
    segments, _info = model.transcribe(path, language="zh", vad_filter=True)
    out = []
    total = 0
    for seg in segments:
        t = (seg.text or "").strip()
        if not t:
            continue
        out.append(t)
        total += len(t)
        if total >= MAX_TRANSCRIPT:
            break
    return "".join(out)


def _summarize_ollama(transcript):
    """本機/runner 上的 Ollama。不需要金鑰，代價是 CPU 上比較慢、品質看模型。"""
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": OLLAMA_CTX},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT % transcript},
        ],
    }).encode()
    req = urllib.request.Request(
        OLLAMA_HOST + "/api/chat", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        data = json.loads(r.read())
    return (data.get("message") or {}).get("content", "")


def _summarize_anthropic(transcript):
    import anthropic
    client = anthropic.Anthropic()          # 讀 ANTHROPIC_API_KEY
    kwargs = dict(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT % transcript}],
    )
    # 逐字稿很長，一律用串流避免 HTTP timeout。
    # fallbacks 讓政策性拒絕時自動改由後備模型接手；這個 beta 我沒辦法在本機
    # 驗證，所以被拒就退回沒有 fallback 的標準呼叫。
    try:
        with client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default", **kwargs) as st:
            msg = st.get_final_message()
    except Exception as e:                                     # noqa: BLE001
        print("::warning::帶 fallbacks 的呼叫失敗（%s），改用標準呼叫" % e)
        with client.messages.stream(**kwargs) as st:
            msg = st.get_final_message()

    if getattr(msg, "stop_reason", None) == "refusal":
        print("::warning::模型拒絕這則請求，保留節目簡介版")
        return ""
    return "".join(b.text for b in msg.content if b.type == "text")


def summarize(transcript):
    text = (_summarize_ollama(transcript) if BACKEND == "ollama"
            else _summarize_anthropic(transcript))
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"^\s*[-*・‧]\s*|^\s*\d+[.)、]\s*", "", ln).strip()
        if ln and ln != "NO_CONTENT":
            lines.append(ln)
    return lines[:6]


def backend_ready():
    """摘要後端能不能用。不能用就整支跳過，網站沿用節目簡介版。"""
    if BACKEND == "anthropic":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True
        print("::warning::GOOAYE_LLM=anthropic 但沒有 ANTHROPIC_API_KEY，跳過")
        return False
    if BACKEND != "ollama":
        print("::warning::不認得的 GOOAYE_LLM=%s（只支援 ollama / anthropic），跳過" % BACKEND)
        return False
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=10) as r:
            tags = json.loads(r.read())
    except Exception as e:                                     # noqa: BLE001
        print("::warning::連不到 Ollama（%s：%s），跳過" % (OLLAMA_HOST, e))
        return False
    have = [m.get("name", "") for m in (tags.get("models") or [])]
    # Ollama 的 tag 可能帶 :latest，比對前綴就好
    if not any(n == OLLAMA_MODEL or n.startswith(OLLAMA_MODEL.split(":")[0] + ":")
               for n in have):
        print("::warning::Ollama 沒有模型 %s（現有：%s），跳過"
              % (OLLAMA_MODEL, ", ".join(have) or "無"))
        return False
    return True


def main():
    if not backend_ready():
        return 0
    try:
        item, feed_url = feed.latest_item()
    except Exception as e:                                     # noqa: BLE001
        print("::warning::抓不到 feed（%s），保留既有 %s" % (e, OUT))
        return 0

    guid = feed.guid_of(item)
    old = existing()
    if old and old.get("source_kind") == "whisper" and old.get("guid") == guid:
        print("股癌：%s 已經有逐字稿摘要，跳過" % (old.get("episode") or guid))
        return 0

    audio = feed.audio_url(item)
    if not audio:
        print("::warning::feed 裡沒有 enclosure 音訊網址，保留既有 %s" % OUT)
        return 0

    title = (feed.text_of(item, "title") or "").strip()
    m = re.search(r"EP\s*(\d+)", title, re.I)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        size = download(audio, tmp.name)
        print("音訊下載完成：%.1f MB" % (size / 1e6))
        transcript = transcribe(tmp.name)
        print("逐字稿長度：%d 字" % len(transcript))
        if len(transcript) < 500:
            print("::warning::逐字稿太短（可能辨識失敗），保留既有 %s" % OUT)
            return 0
        lines = summarize(transcript)
    except Exception as e:                                     # noqa: BLE001
        print("::warning::語音辨識/摘要失敗（%s），保留既有 %s" % (e, OUT))
        return 0
    finally:
        # 逐字稿與音訊都不留：只發表摘要
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    if not lines:
        print("::warning::沒有產出重點，保留既有 %s" % OUT)
        return 0

    data = {
        "episode": ("EP" + m.group(1)) if m else "",
        "title": title,
        "url": (feed.text_of(item, "link") or "").strip(),
        "published": (feed.text_of(item, "pubDate") or "").strip(),
        "summary": lines,
        "source": feed_url,
        "source_kind": "whisper",
        "guid": guid,
        "model": MODEL,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("股癌：%s 已產生 %d 條重點（%s）" % (data["episode"] or title, len(lines), MODEL))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
r"""把 output/dashboard.html 發佈到 GitHub Pages，讓你在外面用手機也能看。

設計：資料仍在你的 PC 上抓（台股來源都正常），只把產生好的網頁透過 GitHub REST API
上傳成 repo 根目錄的 index.html。用 API 而非 git push，是為了讓每天的排程能無人值守、
不會跳出瀏覽器登入視窗。

一次性設定（詳見 README）：
  1. 申請 GitHub 帳號，建立一個 repo（名稱填到 config.GITHUB_REPO）。
  2. 建立 fine-grained 權杖，對該 repo 開 Contents=Read/write、Pages=Read/write，
     把權杖字串貼進 data\github_token.txt。
  3. config.py 填 GITHUB_USER、設 PUBLISH_ENABLED=True。
  4. 執行一次：  py -X utf8 publish.py setup
之後每天排程跑 main.py 時就會自動更新雲端頁面。

用法：
  py -X utf8 publish.py          # 只發佈（main.py 會自動呼叫）
  py -X utf8 publish.py setup    # 首次：開 Pages + 首次發佈 + 印出網址
"""
from __future__ import annotations

import base64
import os
import sys

import requests

import config as cfg

API = "https://api.github.com"


def _token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok and os.path.exists(cfg.GITHUB_TOKEN_FILE):
        with open(cfg.GITHUB_TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = f.read().strip()
    if not tok:
        raise RuntimeError("找不到 GitHub 權杖：請把權杖貼進 %s（或設環境變數 GITHUB_TOKEN）"
                           % cfg.GITHUB_TOKEN_FILE)
    return tok


def _headers():
    return {"Authorization": "Bearer " + _token(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _repo() -> str:
    if not cfg.GITHUB_USER or not cfg.GITHUB_REPO:
        raise RuntimeError("請先在 config.py 填好 GITHUB_USER 與 GITHUB_REPO")
    return "%s/%s" % (cfg.GITHUB_USER, cfg.GITHUB_REPO)


def _put_file(path_in_repo: str, content_bytes: bytes, message: str) -> bool:
    url = "%s/repos/%s/contents/%s" % (API, _repo(), path_in_repo)
    # 先取得現有檔案的 sha（更新時需要）
    sha = None
    g = requests.get(url, headers=_headers(), params={"ref": cfg.GITHUB_BRANCH}, timeout=25)
    if g.status_code == 200:
        sha = g.json().get("sha")
    body = {"message": message,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": cfg.GITHUB_BRANCH}
    # 指定中性 committer/author，避免 GitHub 用帳號 email（會寫進公開 commit 歷史）
    ident = {"name": getattr(cfg, "GIT_COMMIT_NAME", "Stock Tracker Bot"),
             "email": getattr(cfg, "GIT_COMMIT_EMAIL", "noreply@stocktracker.app")}
    body["committer"] = ident
    body["author"] = ident
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=_headers(), json=body, timeout=30)
    if r.status_code in (200, 201):
        return True
    if r.status_code == 401:
        raise RuntimeError("GitHub 權杖失效或已過期，請重新產生並更新 %s（權限：Contents 讀寫）"
                           % cfg.GITHUB_TOKEN_FILE)
    raise RuntimeError("上傳 %s 失敗：HTTP %s %s" % (path_in_repo, r.status_code, r.text[:200]))


def publish_html() -> str:
    """把 dashboard.html 上傳成 index.html，回傳 Pages 網址。"""
    with open(cfg.OUTPUT_HTML, "rb") as f:
        html = f.read()
    _put_file("index.html", html, "update dashboard")
    return pages_url()


def publish_backtest() -> bool:
    """若有 backtest.html 就一併上傳（回測報告頁）。"""
    p = os.path.join(cfg.OUTPUT_DIR, "backtest.html")
    if not os.path.exists(p):
        return False
    with open(p, "rb") as f:
        _put_file("backtest.html", f.read(), "update backtest")
    return True


def publish_extra(filename: str, message: str) -> bool:
    """若 output/<filename> 存在就一併上傳。"""
    p = os.path.join(cfg.OUTPUT_DIR, filename)
    if not os.path.exists(p):
        return False
    with open(p, "rb") as f:
        _put_file(filename, f.read(), message)
    return True


def publish_site() -> str:
    """上傳儀表板 + （若有）回測報告 + 個股分頁。"""
    url = publish_html()
    for fn, msg in (("backtest.html", "update backtest"), ("stocks.html", "update stocks"),
                    ("universe.json", "update universe"),
                    ("news.html", "update news"), ("threads.html", "update threads"),
                    ("perspectives.html", "update perspectives"),
                    ("rec_backtest.html", "update rec_backtest")):
        try:
            publish_extra(fn, msg)
        except Exception:
            pass
    return url


def pages_url() -> str:
    # 優先用 API 回報的 html_url，取不到就用慣例網址
    try:
        r = requests.get("%s/repos/%s/pages" % (API, _repo()), headers=_headers(), timeout=20)
        if r.status_code == 200 and r.json().get("html_url"):
            return r.json()["html_url"]
    except Exception:
        pass
    return "https://%s.github.io/%s/" % (cfg.GITHUB_USER, cfg.GITHUB_REPO)


def enable_pages() -> bool:
    """嘗試開啟 GitHub Pages（從 main 分支根目錄）。已開啟或無權限都不致命。"""
    url = "%s/repos/%s/pages" % (API, _repo())
    r = requests.post(url, headers=_headers(),
                      json={"source": {"branch": cfg.GITHUB_BRANCH, "path": "/"}}, timeout=25)
    if r.status_code in (201, 202):
        print("已自動開啟 GitHub Pages。")
        return True
    if r.status_code in (409, 422):
        print("GitHub Pages 已是開啟狀態。")
        return True
    print("※ 無法自動開啟 Pages（HTTP %s）。請到 repo 的 Settings → Pages，"
          "Source 選『Deploy from a branch』、分支選 %s、資料夾選 / (root) 後 Save。"
          % (r.status_code, cfg.GITHUB_BRANCH))
    return False


def setup():
    print("發佈首次設定中…")
    print("1) 上傳 index.html …")
    publish_html()
    print("2) 開啟 Pages …")
    enable_pages()
    print("")
    print("完成！手機/外網請開（首次建置約需 1～2 分鐘）：")
    print("   " + pages_url())


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup()
    else:
        print("已發佈：" + publish_site())

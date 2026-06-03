#!/usr/bin/env python3
"""自動續期 Threads 長效 access token，並寫回 GitHub Secret。

Threads 的長效 token 約 60 天到期，但可在到期前用同一個 token 換一張新的
（再延 60 天）。只要每隔幾天跑一次，就永遠不會過期。

流程：
    1) 呼叫 refresh_access_token 端點 -> 拿到新 token
    2) 用 GitHub API 把新 token 加密後寫回 THREADS_ACCESS_TOKEN secret

需要的環境變數：
    THREADS_ACCESS_TOKEN   目前的長效 token（要被續期的）
    GH_PAT                 一個有「Secrets 寫入」權限的 GitHub Token（見教學 E 段）
    GITHUB_REPOSITORY      owner/repo（GitHub Actions 會自動帶入）

相依套件：requests, pynacl  （workflow 會自動 pip install）
"""
import os
import sys
import base64
import requests
from nacl import encoding, public

THREADS_API = "https://graph.threads.net"
GH_API = "https://api.github.com"
SECRET_NAME = "THREADS_ACCESS_TOKEN"


def refresh_token(old_token):
    r = requests.get(
        f"{THREADS_API}/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": old_token},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    new_token = data["access_token"]
    expires_in = data.get("expires_in", 0)
    print(f"拿到新 token，有效期約 {expires_in // 86400} 天")
    return new_token


def update_secret(repo, pat, new_token):
    h = {"Authorization": f"Bearer {pat}",
         "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    # 取得 repo 的公鑰，用來加密 secret
    k = requests.get(f"{GH_API}/repos/{repo}/actions/secrets/public-key", headers=h, timeout=30)
    k.raise_for_status()
    pk = k.json()
    sealed = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder))
    encrypted = base64.b64encode(sealed.encrypt(new_token.encode())).decode()
    # 寫回 secret
    u = requests.put(
        f"{GH_API}/repos/{repo}/actions/secrets/{SECRET_NAME}",
        headers=h,
        json={"encrypted_value": encrypted, "key_id": pk["key_id"]},
        timeout=30,
    )
    u.raise_for_status()
    print(f"已更新 GitHub Secret {SECRET_NAME}（HTTP {u.status_code}）")


def main():
    dry = "--dry-run" in sys.argv
    old = os.environ["THREADS_ACCESS_TOKEN"]
    new = refresh_token(old)
    if dry:
        print("[dry-run] 已成功續期，但不寫回 secret。")
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    pat = os.environ["GH_PAT"]
    update_secret(repo, pat, new)
    print("Token 續期完成 ✓")


if __name__ == "__main__":
    main()

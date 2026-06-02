# Threads 自動發文 — 設定教學

每天自動發兩篇到你的 Threads：
- **08:30**（台灣時間）→ ① 今日進場分數（從 `threads.html` 抓當天真實分數）
- **21:00**（台灣時間）→ ③ 金句 或 ④ 互動（依日期交替）

程式：`scripts/post_to_threads.py`　／　排程：`.github/workflows/threads-autopost.yml`

你只需要做一次設定：**拿到 Threads API 的 token，貼進 GitHub Secrets**。下面一步步帶你做。

---

## A. 申請 Threads API token（約 15 分鐘，一次性）

> Threads 自動發文只能透過 Meta 官方 Threads API，沒有別的合法途徑。需要一個 Meta 開發者帳號（免費）。

### 1. 建立 Meta App
1. 到 https://developers.facebook.com/ → 用你的 FB 帳號登入 → 同意成為開發者。
2. 右上「我的應用程式」→「**建立應用程式**」。
3. 用途選「**Other / 其他**」→ 類型選「**Business**」→ 命名（例如 `stocktracker-threads`）→ 建立。

### 2. 加入 Threads 產品
1. 進到 App 後台 → 左側「**新增產品**」→ 找到 **Threads API** → 設定。
2. 在 Threads 設定頁，把這組 **重新導向 URI**（Redirect Callback URL）填上：
   `https://stocktracker-tw.github.io/market-dashboard/`
   （之後只是換 token 用，內容不重要，但格式要是 https。）

### 3. 把你的 Threads 帳號加為測試者
1. App 後台 →「**應用程式角色 / Roles**」→「**Threads Testers**」→ 加入你自己的 Threads 帳號。
2. 到 https://www.threads.net/ → 設定 → 帳號 → 邀請 → **接受** 測試者邀請。
   （沒接受的話拿到的 token 會發不出文。）

### 4. 取得短效 token，再換成長效 token
1. App 後台 → Threads API → 「**Generate access token / 使用者權杖產生器**」，
   勾選權限：`threads_basic`、`threads_content_publish`（發文必備）。
2. 產生後會得到一段 **短效 token（約 1 小時）**。先複製下來。
3. 用瀏覽器開這個網址換成 **長效 token（約 60 天）**，把三個 `<...>` 換成你的值：
   ```
   https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=<APP_SECRET>&access_token=<短效TOKEN>
   ```
   - `<APP_SECRET>`：App 後台 →「應用程式設定 → 基本資料」裡的「應用程式密鑰」。
   - 回傳的 JSON 裡 `access_token` 就是**長效 token**，複製起來。

### 5. 取得你的 user id
用瀏覽器開（換成你的長效 token）：
```
https://graph.threads.net/v1.0/me?fields=id,username&access_token=<長效TOKEN>
```
回傳的 `id`（一串數字）就是你的 **THREADS_USER_ID**。

---

## B. 把憑證放進 GitHub Secrets

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**，新增兩個：

| Name | Value |
|------|-------|
| `THREADS_USER_ID` | 上面 A-5 拿到的數字 id |
| `THREADS_ACCESS_TOKEN` | 上面 A-4 的長效 token |

> ⚠️ token 不要貼進程式碼或 commit。只放 Secrets。

---

## C. 測試

1. repo → **Actions** 分頁 → 「Threads 自動發文」→ **Run workflow**。
2. 先選 `slot = morning`、`dry_run = true` 跑一次 → 看 log 確認內容正確（不會真的發）。
3. 再 `dry_run = false` 跑一次 → 去你的 Threads 看有沒有成功發出。
4. 成功後就會照排程每天 08:30 / 21:00 自動發。

本機也可預覽：
```bash
python3 scripts/post_to_threads.py --dry-run morning
python3 scripts/post_to_threads.py --dry-run evening
```

---

## D. 維護注意事項

- **長效 token 約 60 天到期**，到期前需重新整理。可之後再加一個排程定期呼叫
  `refresh_access_token` 自動續期；要的話再跟我說，我幫你加。
- 早上那篇分數是從 `threads.html` 即時抓的，所以**請確保 bot 的每日更新排在 08:30 之前**完成，才不會發到昨天的分數。
- 想改時間：編輯 workflow 裡的 `cron`（記得是 UTC，台灣要 -8 小時）。
- 想改內容：金句/互動的文案在 `scripts/post_to_threads.py` 的 `QUOTES` / `POLLS`。
- ⚠️ 所有貼文皆含「非投資建議」，不喊明牌。

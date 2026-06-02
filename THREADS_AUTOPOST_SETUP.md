# Threads 自動發文 — 完整設定教學

設定一次，之後每天自動發兩篇到你的 Threads，**token 也會自動續期、永不過期**：

- **08:30**（台灣時間）→ ① 今日進場分數（從 `threads.html` 抓當天真實分數）
- **21:00**（台灣時間）→ ③ 金句 或 ④ 互動（依日期交替）

| 檔案 | 作用 |
|------|------|
| `scripts/post_to_threads.py` | 發文 |
| `scripts/refresh_threads_token.py` | 自動續期 token |
| `.github/workflows/threads-autopost.yml` | 排程發文 08:30 / 21:00 |
| `.github/workflows/threads-token-refresh.yml` | 每週一自動續期 token |

> ⏱️ 全部設定約 20 分鐘，而且**只要做這一次**。照著做不會錯。

---

## 總覽：你最後會在 GitHub Secrets 放 3 個值

做完整個教學，你的 repo Secrets 會有這三個（先有印象，下面會一步步拿到）：

| Secret 名稱 | 是什麼 | 來自 |
|------|------|------|
| `THREADS_USER_ID` | 你的 Threads 數字 ID | C 段 |
| `THREADS_ACCESS_TOKEN` | 發文用的長效 token | C 段（之後自動續期） |
| `GH_PAT` | 讓系統能自動更新 token 的 GitHub 權杖 | E 段 |

---

## A. 建立 Meta App（約 5 分鐘）

> 自動發文只能透過 Meta 官方 Threads API，沒有第三方捷徑。需要一個免費的 Meta 開發者帳號。

1. 開 **https://developers.facebook.com/** → 右上角用你的 Facebook 帳號登入。
   - 第一次會要你「**註冊成為開發人員**」→ 同意條款 → 驗證手機/Email。
2. 右上「**我的應用程式 (My Apps)**」→「**建立應用程式 (Create App)**」。
3. 出現「您希望您的應用程式執行什麼操作？」：
   - 選「**Access the Threads API**」（如果有這個選項，直接選它最快）。
   - 若沒有，就選「**其他 (Other)**」→ 下一步 → 類型選「**商業 (Business)**」。
4. 填應用程式名稱，例如 `stocktracker-threads` → 填聯絡 Email → **建立應用程式**。
   - 可能會要你輸入 FB 密碼確認。

完成後你會進到這個 App 的後台。

---

## B. 加入 Threads API 產品並設定（約 5 分鐘）

1. App 後台左側選單找「**新增產品 (Add Product)**」→ 找到 **Threads API** → 點「**設定 (Set up)**」。
   - 若步驟 A-3 已選 Threads，這步可能已自動完成，直接看左側有沒有「Threads API」。
2. 進入 Threads 的「**Settings / 使用案例**」設定頁，找到 **Redirect Callback URLs**（重新導向網址），填入：
   ```
   https://stocktracker-tw.github.io/market-dashboard/
   ```
   - 這只是換 token 時的形式要求，內容不重要，但**一定要是 https 開頭**。儲存。
3. **把自己加為測試者**（這步很容易漏，漏了會發不出文）：
   - App 後台 →「**應用程式角色 (App roles) → 角色 (Roles)**」→ 找到 **Threads Testers** → 「新增使用者」→ 輸入你的 **Threads 帳號名稱** → 送出邀請。
   - 然後打開 Threads App 或 https://www.threads.net/ → 右下「**個人檔案 → 設定 → 邀請 / Invites**」（或直接看通知）→ **接受**這個測試者邀請。
   - ✅ 確認你的帳號狀態是「**已接受 (Accepted)**」才算成功。

---

## C. 取得 token 和 user id（約 5 分鐘）

### C-1. 產生短效 token
1. App 後台 → 左側 **Threads API → 使用 Threads API**（或「Generate access token」按鈕）。
2. 會列出權限勾選框，**務必勾這兩個**：
   - `threads_basic`
   - `threads_content_publish` ← 沒勾這個就不能發文
3. 點「**Generate access token / 產生權杖**」→ 跳出視窗要你用 Threads 帳號授權 → 同意。
4. 得到一段**短效 token**（約 1 小時有效）。先複製貼到記事本，等下要用。

### C-2. 換成長效 token（約 60 天）
拿你的 **App 密鑰**：App 後台 →「**應用程式設定 → 基本資料 (Basic)**」→「**應用程式密鑰 (App secret)**」→ 點「顯示」複製。

把下面網址的兩個 `<...>` 換成你的值，貼到瀏覽器網址列按 Enter：
```
https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=<APP密鑰>&access_token=<C-1的短效token>
```
回傳會像這樣：
```json
{"access_token":"THAAB...很長一串...","token_type":"bearer","expires_in":5183944}
```
這串 `access_token` 就是**長效 token**（`expires_in` 約 60 天）。複製起來 → 這就是 `THREADS_ACCESS_TOKEN`。

### C-3. 取得你的 user id
把長效 token 填進這個網址，貼到瀏覽器：
```
https://graph.threads.net/v1.0/me?fields=id,username&access_token=<長效token>
```
回傳：
```json
{"id":"1234567890123456","username":"你的帳號"}
```
那串數字 `id` 就是 `THREADS_USER_ID`。

---

## D. 放進 GitHub Secrets（先放這兩個）

repo → **Settings → Secrets and variables → Actions** → 右上「**New repository secret**」，分別新增：

| Name | Value |
|------|-------|
| `THREADS_USER_ID` | C-3 的數字 id |
| `THREADS_ACCESS_TOKEN` | C-2 的長效 token |

> ⚠️ token 等於你的發文權限，絕對不要貼進程式碼或公開出去。只放在 Secrets。

此時就**已經可以發文了**（先跳到 F 段測試）。但 token 60 天會過期，所以再做 E 段讓它自動續期。

---

## E. 設定 token 自動續期（讓它永不過期，約 5 分鐘）

自動續期需要一個能「**寫入 repo Secrets**」的 GitHub 權杖（`GITHUB_TOKEN` 預設沒有這個權限，所以要自己建一個）。

### E-1. 建立 Fine-grained Personal Access Token
1. 開 **https://github.com/settings/personal-access-tokens/new** （Settings → Developer settings → Fine-grained tokens → Generate new token）。
2. 設定：
   - **Token name**：`threads-secret-updater`
   - **Expiration**：選最長（或 1 year，到期再換）
   - **Resource owner**：選 `stocktracker-tw`
   - **Repository access**：選「**Only select repositories**」→ 勾 `market-dashboard`
   - **Permissions → Repository permissions** → 找到「**Secrets**」→ 設為「**Read and write**」
3. 「**Generate token**」→ 複製那串 `github_pat_...`（只會顯示一次）。

### E-2. 把它放進 Secrets
repo → Settings → Secrets → New repository secret：

| Name | Value |
|------|-------|
| `GH_PAT` | E-1 的 `github_pat_...` |

設定好後，`.github/workflows/threads-token-refresh.yml` 會**每週一**自動跑一次，把 `THREADS_ACCESS_TOKEN` 換成新的（每次再延 60 天），所以永遠不會過期。

> 唯一要記得的：`GH_PAT` 本身若設了到期日，到期前要再換一張（建議行事曆提醒）。

---

## F. 測試（確認真的會動）

1. repo → **Actions** 分頁 → 左側「**Threads 自動發文**」→ 右側「**Run workflow**」。
2. 第一次：`slot = morning`、`dry_run = true` → Run。展開 log 看「發文」步驟，確認貼文內容正確（**不會真的發**）。
3. 再跑一次：`dry_run = false` → 去你的 Threads 確認有發出來。
4. 測續期：Actions →「**Threads Token 自動續期**」→ Run workflow → `dry_run = true`，log 看到「拿到新 token」就代表續期可用。
5. 全部 OK 後就放著，它會自己照排程跑。

本機也能預覽文案（不需 token）：
```bash
python3 scripts/post_to_threads.py --dry-run morning
python3 scripts/post_to_threads.py --dry-run evening
```

---

## G. 常見卡關

| 症狀 | 原因 / 解法 |
|------|------|
| 發文回 `(#10) ...permission` 或 `190 invalid token` | 沒勾 `threads_content_publish`，或測試者邀請沒「接受」。回 B-3 / C-1。 |
| `me` 查不到 / token 立刻失效 | 用到的是短效 token 且已過 1 小時，重做 C-1。 |
| 早上發到昨天的分數 | bot 還沒更新 `threads.html`。確保 daily bot 排在 **08:30 之前**完成。 |
| 續期 workflow 報 `403` 更新 secret 失敗 | `GH_PAT` 沒給 Secrets「Read and write」權限，或沒勾到這個 repo。回 E-1。 |
| 想改發文時間 | 改 workflow 裡的 `cron`（UTC，台灣時間要 −8 小時）。 |
| 想改文案 | 金句/互動在 `scripts/post_to_threads.py` 的 `QUOTES` / `POLLS`（記得同步 `threads.html` 的池）。 |

⚠️ 所有貼文皆含「非投資建議」字樣，不喊明牌、不報目標價。

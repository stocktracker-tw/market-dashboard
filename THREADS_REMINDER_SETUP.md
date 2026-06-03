# Threads 每日提醒 — 超簡單設定（半自動）

每天系統會自動把「今天該發的貼文」**推播到你手機**：
- **早上 08:30** → 今日進場分數
- **晚上 21:00** → 金句 或 互動

你只要：**看到通知 → 點一下 → 按「複製」→ 貼到 Threads 發出**。
（每天總共約 30 秒）

> 不用 Meta App、不用 token、不用審核、不用填任何 GitHub Secret。

---

## 設定（一次，約 3 分鐘）

### 1. 手機安裝 ntfy App（免費）
- iPhone：App Store 搜尋「**ntfy**」安裝。
- Android：Play 商店搜尋「**ntfy**」安裝（或 F-Droid）。

### 2. 訂閱你的頻道
1. 打開 ntfy App → 右下「**＋**」訂閱新主題（Subscribe to topic）。
2. 主題名稱輸入：
   ```
   stocktracker-tw-threads-reminder
   ```
3. 完成。以後通知就會進這裡。

> 想換成只有你知道的頻道名稱（比較不會被別人看到貼文）：
> 在 App 訂閱你自己取的名字，再到 repo → **Settings → Secrets and variables → Actions → Variables** 新增一個變數 `NTFY_TOPIC` = 你取的名字即可。貼文本來就是要公開發到 Threads，所以這步可有可無。

### 3. 測試一下
- repo → **Actions** 分頁 → 左側「**Threads 每日提醒（半自動）**」→「**Run workflow**」→ 選 `morning` → Run。
- 幾秒後手機應該會跳出通知。點通知 → 打開 `threads.html` → 按「📋 複製」→ 到 Threads 貼上。

成功後就放著，每天 08:30 / 21:00 自動提醒你。

---

## 每天的動作

1. 手機收到通知（標題會寫「早上・進場分數」或「晚上・金句/互動」）。
2. 點通知 → 自動打開複製頁。
3. 按該篇的「📋 複製」。
4. 切到 Threads → 貼上 → 發。

---

## 想調整

| 想做的事 | 怎麼做 |
|------|------|
| 改提醒時間 | 編輯 `.github/workflows/threads-daily-reminder.yml` 的 `cron`（UTC，台灣 −8 小時）|
| 改文案 | `scripts/post_to_threads.py` 的 `QUOTES` / `POLLS` |
| 換頻道名稱 | 見上面步驟 2 的說明 |
| 哪天想完全自動發（不用手點）| 再回頭做 `THREADS_AUTOPOST_SETUP.md` 的 Meta API 設定，把那兩個 workflow 的排程取消註解即可 |

⚠️ 所有貼文皆含「非投資建議」，不喊明牌。

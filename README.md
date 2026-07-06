# Stock Tracker 引擎（engine-src）

每天在本機 PC 跑的評分引擎。抓資料 → 算 0–100 進場分數 → 產生整站頁面 →
用 GitHub API 推上 `stocktracker-tw/market-dashboard`（main），Pages 對外服務。
推上去之後 GitHub Action 會跑 `scripts/patch_site.py` 做最後保險（見網站 repo 的
ARCHITECTURE.md）——**引擎輸出的頁面設計上就是最終版**，補丁層只是安全網。

## 每日流程（run_daily.ps1 → main.py）

1. **抓資料**（`sources.py`）：Yahoo 行情、BLS CPI、美債殖利率、TWSE 估值/量能/
   三大法人/融資、國發會景氣信號、TAIFEX 台指期籌碼（`taifex_chips`）、
   PTT 散戶情緒（`ptt_stock_sentiment`）。抓不到的來源自動跳過並重配權重。
2. **算指標**（`indicators.py`）→ 每項 0–100 ＋ 說明。
3. **合成分數**（`scoring.py`）：指標→五支柱→加權平均＝raw composite。
4. **顯示層校準**（`main.py`）：raw → 歷史百分位（`COMPOSITE_CALIBRATION`，
   `history_score.csv` 永遠存 raw、避免自我參照）。
5. **變動歸因**（`main.pillar_attribution`）：今天 vs 上一交易日的支柱貢獻拆解。
6. **個股**（`stock.py`）：全市場輕量分（universe）、自選股、推薦、
   `faction_picks`（三派選股：順勢動能／價值便宜／籌碼追買）。
7. **觀點**（`perspectives.py`）：三派卡（順勢/價值/籌碼，picks 掛卡上）＋
   總經「大環境水位」橫幅＋被動派錨點句。問答面板來自 `ask_panel.py`
   （與網站 repo 的 patch_site.py 逐字節同步，改版要兩邊一起）。
8. **消息**（`news.py`）：RSS 標題＋個股價格反應；`briefing.txt` 超過
   `BRIEFING_MAX_AGE_DAYS` 自動不顯示。
9. **渲染**（`dashboard.py`）＋ **發佈**（`publish.py`，GitHub API 逐檔上傳）。

另有 `strategy_backtest.py`（run_daily 第 15 行會跑）：主動 vs 定額回測、
分數有效性體檢、支柱 IC、指標成績單 → `backtest.html`。

## 調參地圖（config.py）

| 想改什麼 | 旋鈕 |
|---|---|
| 支柱權重 | `PILLAR_WEIGHTS` |
| 單一指標權重（0=停用） | `INDICATOR_WEIGHTS` |
| 分級門檻/定額倍數 | `ACTION_BANDS`（35/45/58/70） |
| 百分位校準開關/門檻 | `COMPOSITE_CALIBRATION`、`CALIBRATION_MIN_DAYS` |
| 簡報過期天數 | `BRIEFING_MAX_AGE_DAYS` |
| 推薦門檻 | `STOCK_TOP_*` |

**刪不刪指標，看回測頁的「📋 指標成績單」**：長期趴在雜訊帶（|IC|<0.11）
的是刪除候選——把它的 `INDICATOR_WEIGHTS` 設 0 即可，不用改程式。

## 資料檔（data/，不進 git）

`history_score.csv`（raw 分數史）、`history_pillars.csv`（支柱史，歸因用）、
`history_tw.csv`（籌碼史）、`cache_*.json`（taifex/ptt/net5 等斷網快取）、
`github_token.txt`（**絕不可外流**）、`briefing.txt`（每日 AI 簡報，選用）。

## 與網站 repo 的同步

- 引擎改版：commit 到 `engine-src` → PC 上 `git pull dash engine-src`。
- 頁面樣式的字節正本在網站 repo 的 `scripts/patch_site.py`；
  `ask_panel.py` 是它的引擎側拷貝，兩邊要一起改（bump `data-v`）。

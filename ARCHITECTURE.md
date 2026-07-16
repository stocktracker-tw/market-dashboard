# 系統地圖（market-dashboard）

一句話：**引擎在你 PC 上每天產生整站頁面推上來，這個 repo 負責對外服務＋最後保險。**

```
你的 PC（C:\Users\hjack\Documents\Stock Tracker，源碼在 engine-src 分支）
  └─ run_daily.ps1（排程）
      ├─ main.py         抓資料→算分→校準→歸因→個股→三派觀點→消息→發佈
      └─ strategy_backtest.py  回測＋體檢＋支柱IC＋指標成績單
            │  （publish.py 用 GitHub API 逐檔上傳到 main）
            ▼
本 repo（main）─ push 觸發 ─▶ .github/workflows/site-patch.yml
                              └─ scripts/patch_site.py（冪等補丁＋sw 快取版本）
                              └─ scripts/gen_stock_pages.py（stock/ 個股 SEO 頁）
其他排程：taifex.yml（台指期資料）、盤前分數、Threads
            ▼
GitHub Pages ─▶ 手機 PWA（sw.js 內容雜湊自動換版）
```

## 兩層式頁面的鐵律

引擎輸出的頁面**設計上就是最終版**；`patch_site.py` 是安全網，只在頁面
「不是最終版」時才動手。每個補丁都有冪等守門（style/script id、註解標記、
字串守衛），**重跑永遠收斂**——改補丁時必須維持這件事（測法見下）。

字節正本在 patch_site.py；引擎的 `ask_panel.py`（觀點問答面板）是它的拷貝，
改版要兩邊同步並 bump `data-v`（目前 ask17）。

## 檔案速查

| 檔案 | 是什麼 | 誰在改 |
|---|---|---|
| index.html 等根目錄頁 | 引擎每日重生 | 引擎（勿手改） |
| stock/*、etf/* | SEO 導流頁 | gen_stock_pages.py（Action） |
| scripts/patch_site.py | 補丁層＋fix_sw | 手改（正本） |
| sw.js | PWA 快取；版本＝內容雜湊、清單由 fix_sw 正規化 | fix_sw 自動 |
| taifex.json | 台指期籌碼 | taifex.yml（每日） |
| universe.json | 全市場輕量分 | 引擎（patch 端 minify） |
| data/rec_*、backtest_summary.json | 回測/推薦資料 | 引擎 |

## 分頁列（tabbar）的 iOS 地雷——踩過三次，別再踩

底部分頁列的毛玻璃（backdrop-filter）在 iOS WebKit 上很脆，以下每一條都是
實機驗證過的血淚，動分頁列前先讀：

1. **元素自身不能有 `transform`**——有就整條玻璃靜默失效變不透明白塊
   （頂欄 brandbar 用 `left:0;right:0;margin:auto` 置中所以一直正常）。
   分頁列置中同樣用 margin:auto，**不准用 translateX(-50%)**。
2. **列內不能有會被提升成合成層的子元素**——舊拖曳膠囊（transform 過場＋
   拖曳時 backdrop-filter）就是這樣把玻璃弄壞的。現行 `.tabcap` 膠囊
   只用 left/top/width/height 過場，無 transform、無 backdrop、無 will-change。
3. **不能用 SPA 換頁**——SPA 讓分頁列跨頁不重建，玻璃一旦失效就永不恢復
   （症狀：初始有霧、換頁後消失、切回也沒有）。現行為整頁重載，
   `patch_spanav` 反而是負責「移除」殘留 spanav 的。
4. 換頁轉場全關（`@view-transition{navigation:none}`）——使用者要求不要特效，
   而且 view-transition-name 也會破壞 backdrop。

玻璃樣式本體：底色 `rgba(245,248,251,.75)` 與頂欄同值，模糊由 `maxglass`
共用規則統一（.tabbar 與 .brandbar 同一張清單）——改一邊必動另一邊。

## 常見狀況 → 處置

- **手機看到舊版**：等背景更新或下拉重整；sw 版本是內容雜湊，push 後必換。
- **PC pull 被擋（untracked/local changes）**：`git stash` 或
  `git checkout -- <檔>` 後再 `git pull dash engine-src`。
- **頁面出現重複區塊/樣式跑掉**：跑 `python scripts/patch_site.py` 兩次，
  第二次必須「無需變更」；不是就代表某補丁失去冪等，比對該補丁的守門標記。
- **分數看起來怪**：先看首頁小字「原始加權分」與「歸因行」，
  再看回測頁三張卡（體檢／支柱IC／指標成績單）。
- **市場消息舊**：簡報超過 5 天會自動隱藏；RSS 標題每天更新。

## 改東西前先想

1. 視覺/文案 → 儘量改**引擎模板**（dashboard.py 等），補丁只當安全網。
2. 指標去留 → 看回測頁「指標成績單」，把 `INDICATOR_WEIGHTS` 設 0 即可。
3. 動 patch_site → 改完務必：`python scripts/patch_site.py` 兩次
   ＋ 抽查頁面標記數（askpanel/liquidglass/scorecolor 各 ≤1）。

引擎側詳情見 engine-src 分支的 README.md。

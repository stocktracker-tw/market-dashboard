# 分數區間對照表

**唯一來源是 repo 根目錄的 `bands.json`**（個股頁、ETF 頁、自選股提醒、頂欄圓點、盤前分數都讀它），
必須與引擎 `engine-src` 的 `config.ACTION_BANDS` 一致；`tests/test_bands.py` 會在每個 PR 上比對。
這份文件只是方便人看的抄本，數字以 `bands.json` 為準。

0–100，越高越適合加碼（「遍地黃金」＝數據站在買方）。

| 分數 | 區間 | 定額倍數（回測用） |
|---|---|---|
| 70–100 | 遍地黃金區 | 2x |
| 58–69 | 機會偏多區 | 1.5x |
| 45–57 | 中性區 | 1x |
| 35–44 | 偏熱謹慎區 | 0.5x |
| 0–34 | 過熱危險區 | 0.25x |

紅綠燈（個股各面向分數條）：≥ 58 綠、< 42 紅、其餘黃（引擎 `LIGHT_GREEN_MIN` / `LIGHT_RED_MAX`）。

## 改門檻的步驟

1. 改引擎 `config.ACTION_BANDS`（PC 上）並推到 `engine-src`
2. 同步改 `bands.json`，開 PR；CI 的 `test_bands_match_engine` 會確認兩邊一致
3. 合併後 site-patch 會自動重產個股／ETF 頁並改寫自選股提醒

⚠️ 所有對外文案維持「非投資建議」基調，不喊明牌、不報目標價。

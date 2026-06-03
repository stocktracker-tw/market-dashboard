# 用 PWABuilder 把網站包成 iOS App（上架 App Store）

你的網站已經是完整的 PWA，可以用 [PWABuilder](https://www.pwabuilder.com/)（微軟的免費工具）
打包成 iOS 專案再送 App Store。這份是完整步驟。

## 0. 前置（都已就緒 ✅）
- HTTPS：GitHub Pages 自帶 ✅
- `manifest.webmanifest`：已補上 `id`、`categories`、512 圖示等 PWABuilder 建議欄位 ✅
- Service worker（`sw.js`）：已註冊 ✅
- 圖示 192 / 512：齊全 ✅

## 1. 產生 iOS 專案（在 PWABuilder 網站，免 Mac）
1. 開 https://www.pwabuilder.com/
2. 貼上網址：`https://stocktracker-tw.github.io/market-dashboard/`
3. 按 **Start** → 它會幫你的 PWA 評分、列出可改進項目。
4. 找到 **iOS** 卡片 → **Generate Package** → 下載 zip（裡面是一個 Xcode 專案）。

## 2. 建置 + 簽章 + 送審（這步 iOS 一定要 Mac）
> ⚠️ iOS 不像 Android 能直接拿到成品檔；PWABuilder 給的是 **Xcode 專案**，
> 仍需在 **Mac + Xcode** 開啟、簽章、上傳。沒有 Mac → 可租用雲端 Mac（如 MacinCloud）。

1. 申請 **Apple Developer Program**（**US$99／年**）：https://developer.apple.com/programs/
2. 在 Mac 用 **Xcode** 開剛下載的專案。
3. 設定 **Bundle Identifier**（例：`tw.stocktracker.app`）與你的開發者 **Team**。
4. **Product → Archive** → 上傳到 **App Store Connect**。
5. 在 App Store Connect 填：App 名稱、描述、分類（財經）、截圖、隱私說明 → **送審**。

## 3. ⚠️ 過審重點：Guideline 4.2「最低功能性」
Apple 常打回「只是把網站包起來、沒有原生功能」的 App。提高過審機率：
- **加原生推播通知**：把每日進場分數提醒做成 App 推播（目前是 ntfy）—— 真實價值 + 過審理由。
- 強調離線可用（service worker 已有快取）。
- App 描述清楚說明用途與「非投資建議」。
- 一定要附「非投資建議」「資料來源」等說明，財經類審查較敏感。

## 4. 費用 / 需求總覽
| 項目 | 需求 |
|------|------|
| Apple Developer | US$99／年（必付） |
| Mac + Xcode | 建置／簽章／送審必要（或租雲端 Mac） |
| 審查時間 | 通常 1–3 天，可能來回 |

## 建議
先用 Safari「加入主畫面」免費即時體驗；確定要 App Store 曝光時，再走本流程，
並優先把「每日推播」做成原生功能，過審最穩。

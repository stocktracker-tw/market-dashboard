# 變現 / 商業化筆記

這份是「怎麼開始盈利」的紀錄與素材。重點：**台灣收費提供個股買賣建議需投顧執照**，
所以一律走「教育 / 數據工具 / 觀點 / 導流」，每篇都保留「非投資建議」。

---

## 1. Threads 個人簡介（bio）

主力採用「痛點型」（已選定）：

```
不知道現在該不該進場？
每天幫你算一個 0–100 的台股進場分數，
高=適合分批、低=保守觀望。
📊 數據驅動・非投資建議
```

- Threads 簡介上限 150 字；連結放獨立的「連結」欄位，不佔字數。
- 連結欄填：`https://stocktracker-tw.github.io/market-dashboard/`
- 顯示名稱建議：`台股進場分數` / `每天一個進場訊號`
- 之後想走專業變現時，可換成「專業權威型」。

---

## 2. 站上贊助 / 券商連結區塊

已加在 `index.html` 頁尾上方（玻璃卡片，三格）。

⚠️ **`index.html` 由外部引擎每天重產，這段會被覆蓋。** 要永久顯示，請把下面這段
一併加進引擎產生 `index.html` 的模板（插在 `<div class="foot">` 之前），
並把三個 `#REPLACE_...` 換成你的真實連結。

### 待填連結
| 佔位符 | 換成 |
|--------|------|
| `#REPLACE_BROKER_REF` | 券商開戶推薦連結（永豐／富邦／國泰等的專屬推薦碼） |
| `#REPLACE_BOOKS_AFFILIATE` | 書籍聯盟連結（博客來 AP／momo 聯盟） |
| `#REPLACE_KOFI` | 贊助連結（ko-fi／綠界贊助） |

### HTML（貼進引擎模板）
```html
<div class="section-title">支持這個專案 💛</div>
<div class="sponsor">
  <a class="spon-card" href="#REPLACE_BROKER_REF" target="_blank" rel="noopener sponsored">
    <div class="se">🏦</div><div class="st">開證券戶</div>
    <div class="sd">用推薦連結開戶，支持本站持續免費更新</div>
  </a>
  <a class="spon-card" href="#REPLACE_BOOKS_AFFILIATE" target="_blank" rel="noopener sponsored">
    <div class="se">📚</div><div class="st">投資書單</div>
    <div class="sd">我正在讀的財經好書（聯盟連結）</div>
  </a>
  <a class="spon-card" href="#REPLACE_KOFI" target="_blank" rel="noopener">
    <div class="se">☕</div><div class="st">請我喝杯咖啡</div>
    <div class="sd">覺得有用？小額贊助讓專案走更久</div>
  </a>
</div>
<p class="spon-note">以上為推薦／聯盟連結，透過它開戶或購買，本站可能獲得回饋，
不影響你的權益與價格；內容僅為個人分享，非投資建議。</p>
```

### CSS（已加在 `index.html` 第一個 `<style>`，引擎模板也需同步）
```css
.sponsor{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:760px){.sponsor{grid-template-columns:1fr}}
.spon-card{display:block;text-decoration:none;color:var(--text);
  background:linear-gradient(180deg,rgba(255,255,255,.085),rgba(255,255,255,.028));
  -webkit-backdrop-filter:blur(30px) saturate(1.9);backdrop-filter:blur(30px) saturate(1.9);
  border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:16px 18px;
  transition:transform .15s,box-shadow .15s}
.spon-card:hover{transform:translateY(-2px);box-shadow:0 14px 36px rgba(0,0,0,.45)}
.spon-card .se{font-size:22px}
.spon-card .st{font-weight:700;font-size:15px;margin:4px 0 3px}
.spon-card .sd{font-size:12.5px;color:var(--muted)}
.spon-note{font-size:11.5px;color:var(--muted);margin-top:10px;opacity:.85}
```

---

## 3. 變現路線（分階段）

| 階段 | 粉絲數 | 做什麼 |
|------|--------|--------|
| 一 | 0–1,000 | 只養信任：一天一篇、回留言。先別變現 |
| 二 | 1,000–5,000 | 券商開戶推薦、書籍聯盟、贊助連結（零成本、合法） |
| 三 | 5,000–10,000 | 付費電子報／會員（更深數據、週報）、付費社群 |
| 四 | 10,000+ | 業配、線上課程、儀表板付費 SaaS（警示推播、進階指標） |

**這週可做：** ① 設好 bio ② 申請 1 個券商推薦連結填進站上 ③ 持續發、看數據。

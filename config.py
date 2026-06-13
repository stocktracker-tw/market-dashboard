# -*- coding: utf-8 -*-
"""集中設定：要抓的代碼、各指標權重、檔案路徑。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
HISTORY_TW = os.path.join(DATA_DIR, "history_tw.csv")   # 台股籌碼每日累積
HISTORY_STOCK_VAL = os.path.join(DATA_DIR, "history_stock_val.csv")  # 個股估值每日累積（算相對估值用）
NEWS_ADJUST_FILE = os.path.join(DATA_DIR, "news_adjust.json")  # 消息面微調（由查證簡報寫入）
HISTORY_SCORE = os.path.join(DATA_DIR, "history_score.csv")  # 綜合分數每日累積
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "dashboard.html")
RAW_CACHE = os.path.join(DATA_DIR, "raw_latest.json")   # 最近一次抓到的原始資料（除錯用）

# Yahoo Finance 代碼 → 內部 key。range=2y 足夠算 MA200 / RSI / 52週高 / 百分位。
YAHOO_SYMBOLS = {
    "^TWII": "twii",        # 台股加權指數
    "0050.TW": "t0050",     # 元大台灣50
    "^GSPC": "spx",         # S&P 500
    "^IXIC": "nasdaq",      # 那斯達克
    "^DJI": "dji",          # 道瓊
    "^SOX": "sox",          # 費城半導體
    "^VIX": "vix",          # 標普恐慌指數
    "^VIX3M": "vix3m",      # 3個月期 VIX（看期限結構）
    "^VXN": "vxn",          # 那斯達克波動率
    "^TNX": "us10y",        # 美國10年期公債殖利率
    "^IRX": "us3m",         # 美國13週(3M)國庫券殖利率
    "DX-Y.NYB": "dxy",      # 美元指數
    "GC=F": "gold",         # 黃金期貨
    "HG=F": "copper",       # 銅期貨
    "CL=F": "oil",          # 原油期貨
    "HYG": "hyg",           # 高收益債 ETF
    "IEF": "ief",           # 7-10年美債 ETF
    "TLT": "tlt",           # 20年+美債 ETF
    "TIP": "tip",           # 抗通膨債 ETF
    "TWD=X": "usdtwd",      # 美元兌台幣
}

PILLAR_NAMES = {
    "fear": "恐慌與情緒",
    "valuation": "估值水位",
    "macro": "通膨利率總經",
    "trend": "趨勢・技術面",
    "chips": "籌碼（法人vs散戶）",
}

# ======================================================================
# ★★★ 可調設定區：想調整訊號靈敏度／權重，改這裡就好 ★★★
# ======================================================================

# 1) 五大面向權重（總和不必=100，會自動正規化；缺資料的面向自動剔除）。
#    籌碼與恐慌加重，貼近「法人vs散戶 + 逆向進場」的訴求。
PILLAR_WEIGHTS = {
    "fear": 22,        # 恐慌與情緒（逆向）
    "valuation": 20,   # 估值（便宜=機會）
    "macro": 14,       # 通膨 / 利率 / 總經 / 景氣
    "trend": 24,       # 趨勢動能 + 技術面（長期趨勢品質/MACD/布林/K線/ATR）
    "chips": 20,       # 籌碼：法人 vs 散戶
}

# 2) 各指標在「所屬面向內」的相對權重（key 對應 indicators.py 的指標 key）。
#    想讓某指標更有份量就調高、想忽略就設 0。
INDICATOR_WEIGHTS = {
    # 恐慌
    "vix": 1.0, "vix_term": 0.8, "fear_greed": 1.2,
    # 估值
    "tw_val": 1.0, "dd_spx": 0.8, "dd_twii": 0.8,
    # 總經
    "cpi": 1.0, "ust": 0.8, "dxy": 0.7, "copper_gold": 0.5, "ndc": 0.8,
    # 趨勢・技術面（trend_*/rel 在 bias=0.5 時≈中性，降權；改由趨勢品質/技術指標主導）
    "trend_spx": 0.0, "trend_twii": 0.0, "rel": 0.0,
    "tq_twii": 1.6, "tq_spx": 1.0,                 # A・長期趨勢品質（主導）
    "macd_twii": 0.6, "boll_twii": 0.5, "atr_twii": 0.4,   # C・技術面
    "candle_twii": 0.5,                            # B・K 線型態
    # 籌碼
    "inst": 1.0, "margin": 1.0, "diverg": 1.5, "volume": 0.5,
}

# 3) 紅綠燈門檻：進場機會分數 >= GREEN 亮綠（偏多/加碼）、< RED 亮紅（偏空/保守）、中間黃燈。
LIGHT_GREEN_MIN = 58
LIGHT_RED_MAX = 42

# 4) 綜合分數 → 等級 / 建議 / 定額倍數。由高到低比對（分數 >= 門檻就採用）。
#    倍數＝相對你平常每月定額金額的建議比例，純示意可自行改。
ACTION_BANDS = [
    (70, "積極加碼區", "多項逆向指標同時偏低，歷史上屬相對甜蜜的分批進場區。", 2.0),
    (58, "加碼區",     "情緒/估值偏向有利，建議高於平常的定額金額分批投入。", 1.5),
    (45, "正常定額區", "訊號中性，維持原本的定期定額節奏即可。", 1.0),
    (35, "減碼觀望區", "偏貴或過熱，建議降低投入、保留銀彈等更好的價位。", 0.5),
    (0,  "保守防禦區", "多項指標顯示追高/過熱風險，宜暫緩加碼、嚴守紀律。", 0.25),
]

# 5) 台股籌碼回補天數（首次執行往回抓幾個交易日，建立背離訊號視窗）。
BACKFILL_TRADING_DAYS = 20

# 5b) 哲學旋鈕：趨勢面要「逆勢」還是「順勢」。
#     1.0 = 純逆勢（超賣/低於均線=加碼機會，目前的預設）
#     0.5 = 趨勢面不表態（趨勢 pillar 不再左右分數）
#     0.0 = 純動能/順勢（強勢上漲=機會、超賣=避開接刀）
#     只影響趨勢面（美股/台股趨勢、相對強弱）；恐慌與估值仍維持逆勢。
#     註：經 forecast.py 歷史檢驗，台股在強勢動能時純逆勢會看錯方向，故預設改 0.5（趨勢中性、
#     不再因上漲而扣分）。想更順勢可調 0、想回原本純逆勢調 1.0。
MEAN_REVERSION_BIAS = 0.5

# 6) 綜合分數歷史回測天數（backtest.py 會回算最近 N 個交易日的分數，讓走勢圖立刻有東西看）。
BACKTEST_DAYS = 60

# 7) 手機/區網瀏覽：serve.ps1 用的埠號，與儀表板自動重新整理秒數（meta refresh）。
SERVE_PORT = 8011
REFRESH_SECONDS = 1800

# 8) 在外面看：發佈到 GitHub Pages（PC 每天跑完自動上傳，手機隨時隨地可看）。
#    設定步驟見 README「在外面看（雲端發佈）」。權杖存在 data\github_token.txt（切勿外流/上傳）。
PUBLISH_ENABLED = True            # GitHub 設好後改成 True，main.py 跑完就會自動發佈
GITHUB_USER = "stocktracker-tw"  # 你的 GitHub 帳號（已改名，舊名 hjack19981006-prog 自動重導）
GITHUB_REPO = "market-dashboard"  # 網址 = stocktracker-tw.github.io/market-dashboard/
GITHUB_BRANCH = "main"
GITHUB_TOKEN_FILE = os.path.join(DATA_DIR, "github_token.txt")
# 用中性 bot 身分發 commit，避免把個人 email 寫進公開 repo 歷史
GIT_COMMIT_NAME = "Stock Tracker Bot"
GIT_COMMIT_EMAIL = "noreply@stocktracker.app"

# 9) AI 噴發 / 泡沫 情境（meltup.py）。
#    預設只在儀表板加一塊「噴發/泡沫」警示面板，不動你的進場分數。
#    MELTUP_AWARE=True 時：偵測到「噴發中（趨勢完好）」就把定額倍數設下限（不砍到底、
#    不錯過行情），改以「跌破 50 日線」作為減碼訊號——也就是『參與但設好停損』。
MELTUP_AWARE = True                # 預設開：偵測到「噴發中(趨勢完好)」就維持參與、以跌破50日線為減碼訊號
MELTUP_FLOOR = 1.0                 # 噴發期的定額倍數下限（MELTUP_AWARE=True 時生效）

# 消息面微調（B案）：由「已查證的簡報」輸出一個小幅、有上限、會隨時間衰退的分數微調。
#   只反映「價格尚未反映的新催化 / 敘事真偽惡化」，避免與已反映的量化指標重複計算。
#   簡報沒更新時會自動淡出到 0（不會殘留舊消息）。
NEWS_ADJUST_ENABLED = True
NEWS_ADJUST_CAP = 8                # 微調上限（±分）
NEWS_ADJUST_MAX_AGE_DAYS = 5       # 超過天數線性衰退到 0

# 10) 個股版進場分數（stock.py）：四個面向的權重（缺資料自動重新分配）。
STOCK_WEIGHTS = {
    "env": 25,        # 大盤環境（用儀表板的綜合分數當背景）
    "trend": 25,      # 個股趨勢（均線/RSI/回檔；自選/推薦股完整版用）
    "chips": 30,      # 個股籌碼（法人買超 vs 散戶融資）
    "valuation": 20,  # 個股估值（PE/PB/殖利率；產業差異大，權重較低）
    "lite_tech": 12,  # 搜尋輕量技術分（今日K線/收盤位置/漲跌＋累積後短均線）
}
STOCK_INST_DAYS = 5                # 個股法人買賣超累計的交易日數

# 自選股清單：每天排程會一起算好、做成儀表板的「個股」分頁。空 list = 不產生個股頁。
STOCK_WATCHLIST = ["2330", "0050", "2317", "2454", "2308"]
STOCK_VAL_MIN_HISTORY = 15         # 個股估值改用「自身歷史百分位」所需的最少累積天數

# 置頂「最推薦潛力股」：每天從全市場自動挑進場分數最高的中大型股，置頂在個股頁。
STOCK_TOP_N = 8                    # 推薦檔數
STOCK_TOP_MIN_PRICE = 15          # 篩選：股價下限（避開雞蛋水餃股）
STOCK_TOP_MIN_MARGIN = 2000       # 篩選：融資餘額下限（張，確保有流動性/信用交易）

# 題材：推薦要「有題材」才入選（避開沒故事的價值陷阱）。
STOCK_TOP_REQUIRE_THEME = True
# 「有題材」的產業別（客觀、全市場；可自行增刪）。偏成長/電子/熱門循環。
HOT_INDUSTRIES = ["半導體", "電腦及週邊", "光電", "通信網路", "電子零組件", "其他電子",
                  "電機機械", "綠能環保", "數位雲端", "生技醫療", "資訊服務"]
# 細題材標籤（顯示用＋也算「有題材」）。為範例清單，請依當下熱點自行增修。
THEMES = {
    "AI伺服器": ["2317", "2382", "3231", "2376", "6669", "3711", "2356"],
    "散熱": ["3017", "3324", "6230"],
    "重電": ["1503", "1504", "1513", "1514", "1519"],
    "軍工航太": ["2634", "2645"],
    "PCB/載板": ["3037", "8046", "6269", "3189"],
    "記憶體": ["2408", "2344", "3260"],
    "網通/衛星": ["2345", "6285", "3163", "2419"],
    "機器人/自動化": ["2049", "1590"],
    "矽光子/CPO": ["4979", "3450", "6526"],
}

# -*- coding: utf-8 -*-
"""產生粉專貼文圖（1080x1080）：post_pillars（進場分數五大支柱）、post_layers（三層判讀）。"""
import os
from PIL import Image, ImageDraw

import config as cfg
from make_cover import neon_bg, font

S = 1080


def post_pillars():
    base = neon_bg(S, S)
    d = ImageDraw.Draw(base, "RGBA")
    d.text((70, 60), "一個分數", font=font(82), fill=(245, 248, 255))
    d.text((74, 166), "五大支柱加權算出來", font=font(46), fill=(255, 140, 205))
    rows = [("恐慌指數", "25%", (255, 92, 112)),
            ("估值", "20%", (246, 168, 33)),
            ("總經（CPI・利率）", "15%", (55, 200, 255)),
            ("趨勢", "20%", (80, 220, 140)),
            ("籌碼 法人 vs 散戶", "20%", (255, 92, 190))]
    y = 280
    for name, wt, col in rows:
        d.rounded_rectangle((70, y, 1010, y + 92), radius=20, fill=(10, 10, 26, 150),
                            outline=(255, 255, 255, 36), width=2)
        d.ellipse((102, y + 34, 126, y + 58), fill=col + (255,))
        d.text((152, y + 22), name, font=font(40), fill=(238, 242, 250))
        d.text((905, y + 22), wt, font=font(40), fill=col + (255,))
        y += 104
    d.text((70, y + 18), "= 0–100 進場分數", font=font(52), fill=(255, 255, 255))
    d.text((74, y + 92), "分數越高 → 越適合分批加碼", font=font(30, False), fill=(202, 210, 226))
    d.text((74, 990), "Stock Tracker ・ ⚠ 非投資建議", font=font(26, False), fill=(150, 160, 185))
    base.convert("RGB").save(os.path.join(cfg.OUTPUT_DIR, "post_pillars.png"))


def post_layers():
    base = neon_bg(S, S)
    d = ImageDraw.Draw(base, "RGBA")
    d.text((70, 60), "別被單一指標騙了", font=font(62), fill=(245, 248, 255))
    d.text((74, 150), "Stock Tracker 三層獨立判讀", font=font(40), fill=(255, 140, 205))
    items = [("進場分數", "現在便不便宜、值不值得加碼", (55, 200, 255)),
             ("噴發脆弱度", "多頭有沒有過熱、何時轉弱", (255, 92, 190)),
             ("景氣位置", "整體經濟在循環的哪一段", (80, 220, 140))]
    y = 270
    for title, desc, col in items:
        d.rounded_rectangle((70, y, 1010, y + 182), radius=24, fill=(10, 10, 26, 165),
                            outline=col + (150,), width=2)
        d.rounded_rectangle((70, y + 26, 84, y + 156), radius=6, fill=col + (255,))
        d.text((124, y + 38), title, font=font(50), fill=(245, 248, 255))
        d.text((126, y + 114), desc, font=font(32, False), fill=(206, 214, 229))
        y += 212
    d.text((74, 938), "用數據抓進場時機 ｜ 台股美股 ｜ 每日更新", font=font(30, False), fill=(202, 210, 226))
    d.text((74, 1000), "⚠ 研究輔助，非投資建議", font=font(24, False), fill=(150, 160, 185))
    base.convert("RGB").save(os.path.join(cfg.OUTPUT_DIR, "post_layers.png"))


if __name__ == "__main__":
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    post_pillars(); post_layers()
    print("wrote output/post_pillars.png + output/post_layers.png")

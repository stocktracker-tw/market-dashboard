# -*- coding: utf-8 -*-
"""產生粉專封面橫幅 output/cover.png（FB 1640x624）＋ IG 方形宣傳 output/promo_sq.png（1080x1080）。"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config as cfg


def font(size, bold=True):
    cands = ([r"C:\Windows\Fonts\msjhbd.ttc"] if bold else []) + [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\simhei.ttf"]
    for p in cands:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def neon_bg(W, H):
    ys, xs = np.mgrid[0:H, 0:W]
    bg = np.zeros((H, W, 3), float); bg[:] = [10, 10, 22]

    def glow(cx, cy, r, col, amt):
        w = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2.0 * r * r)))
        for c in range(3):
            bg[:, :, c] = bg[:, :, c] * (1 - amt * w) + col[c] * (amt * w)
    glow(W * 0.55, H * 0.08, max(W, H) * 0.34, [255, 46, 136], .5)
    glow(W * 0.85, H * 0.5, max(W, H) * 0.28, [120, 40, 255], .33)
    glow(W * 0.15, H * 0.92, max(W, H) * 0.30, [55, 180, 255], .18)
    return Image.fromarray(np.clip(bg, 0, 255).astype("uint8"), "RGB").convert("RGBA")


def place_bull_right(base, bull_path, size, x):
    bull = Image.open(bull_path).convert("RGB").resize((size, size), Image.LANCZOS).convert("RGBA")
    fade = Image.new("L", (size, size), 255)
    px = fade.load()
    for xx in range(size):
        a = 255 if xx > 250 else int(255 * max(0, (xx - 30) / 220))
        for yy in range(size):
            px[xx, yy] = a
    bull.putalpha(fade)
    base.alpha_composite(bull, (x, (base.size[1] - size) // 2))


def left_darken(base, frac):
    W, H = base.size
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    lim = int(W * frac)
    for x in range(lim):
        a = int(160 * max(0, (1 - x / lim)))
        od.line([(x, 0), (x, H)], fill=(8, 8, 18, a))
    return Image.alpha_composite(base, ov)


def cover():
    W, H = 1640, 624
    base = neon_bg(W, H)
    place_bull_right(base, "output/bullcy_0.png", H, W - H)
    base = left_darken(base, 0.62)
    d = ImageDraw.Draw(base)
    d.text((92, 150), "Stock Tracker", font=font(88), fill=(245, 248, 255))
    d.text((96, 268), "用數據抓進場時機", font=font(48), fill=(255, 140, 205))
    d.text((96, 342), "台股・美股 ｜ 0–100 進場分數 ｜ 每日自動更新", font=font(30, False), fill=(202, 210, 226))
    d.text((96, 474), "⚠ 研究與決策輔助，非投資建議", font=font(24, False), fill=(150, 160, 185))
    base.convert("RGB").save(os.path.join(cfg.OUTPUT_DIR, "cover.png"))


def promo_sq():
    S = 1080
    base = neon_bg(S, S)
    place_bull_right(base, "output/bullcy_0.png", int(S * 0.72), int(S * 0.30))
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    for y in range(int(S * 0.55), S):
        a = int(170 * (y - S * 0.55) / (S * 0.45))
        od.line([(0, y), (S, y)], fill=(8, 8, 18, a))
    base = Image.alpha_composite(base, ov)
    d = ImageDraw.Draw(base)
    d.text((70, 70), "Stock Tracker", font=font(74), fill=(245, 248, 255))
    d.text((74, 170), "用數據抓進場時機", font=font(46), fill=(255, 140, 205))
    d.text((74, 250), "幾十項指標 → 一個 0–100 進場分數", font=font(30, False), fill=(205, 213, 228))
    d.text((74, 905), "台股・美股 ｜ 上市＋上櫃 ｜ 每日自動更新", font=font(28, False), fill=(200, 208, 225))
    d.text((74, 965), "⚠ 非投資建議", font=font(24, False), fill=(150, 160, 185))
    base.convert("RGB").save(os.path.join(cfg.OUTPUT_DIR, "promo_sq.png"))


if __name__ == "__main__":
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    cover(); promo_sq()
    print("wrote output/cover.png (1640x624) + output/promo_sq.png (1080x1080)")

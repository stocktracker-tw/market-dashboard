# -*- coding: utf-8 -*-
"""程式手繪『霓虹牛頭 + 紅色上升箭頭』App 圖示（向量風，無任何 K 棒）。
紅紫底、台灣紅=漲(箭頭紅)、青/洋紅霓虹牛。輸出 output/cand_bull_drawn.png 預覽。"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import config as cfg

SS = 1024
CYAN = (40, 226, 255)
MAG = (255, 64, 200)
RED = (255, 48, 82)
WHITE = (240, 252, 255)


def redpurple_bg():
    gx, gy = np.meshgrid(np.linspace(0, 1, SS), np.linspace(0, 1, SS))
    t = (gx + gy) / 2
    tl = np.array([66, 14, 104], float)
    br = np.array([120, 16, 58], float)
    bg = tl[None, None] + (br - tl)[None, None] * t[..., None]
    cx = cy = SS * 0.5
    d2 = (np.arange(SS)[None, :] - cx) ** 2 + (np.arange(SS)[:, None] - cy) ** 2
    w = np.exp(-d2 / (2 * (SS * 0.32) ** 2))
    glow = np.array([150, 30, 112], float)
    bg = bg * (1 - 0.45 * w[..., None]) + glow[None, None] * (0.45 * w[..., None])
    return Image.fromarray(np.clip(bg, 0, 255).astype("uint8"), "RGB").convert("RGBA")


def mirror(pts):
    return [(SS - x, y) for (x, y) in pts]


def stroke(d, pts, width, color, closed=False):
    p = list(pts) + ([pts[0]] if closed else [])
    d.line(p, fill=color + (255,), width=width, joint="curve")
    r = width // 2
    for x, y in p:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color + (255,))


def draw_neon(layer):
    d = ImageDraw.Draw(layer)
    # 紅色上升箭頭（在牛後方）
    shaft = [(250, 812), (470, 612), (590, 660), (792, 300)]
    stroke(d, shaft, 40, RED)
    stroke(d, [(792, 300), (672, 322)], 40, RED)      # 箭頭兩翼
    stroke(d, [(792, 300), (734, 416)], 40, RED)
    # 牛臉輪廓（正面、對稱）
    face = [(512, 730), (560, 708), (606, 668), (650, 596), (672, 506), (650, 430),
            (572, 392), (512, 386), (452, 392), (374, 430), (352, 506), (376, 596),
            (420, 668), (466, 708)]
    stroke(d, face, 24, CYAN, closed=True)
    # 牛角
    rhorn = [(648, 432), (712, 398), (760, 342), (778, 268), (758, 210)]
    stroke(d, rhorn, 26, CYAN)
    stroke(d, mirror(rhorn), 26, CYAN)
    d.ellipse([758 - 9, 210 - 9, 758 + 9, 210 + 9], fill=WHITE + (255,))
    d.ellipse([SS - 758 - 9, 210 - 9, SS - 758 + 9, 210 + 9], fill=WHITE + (255,))
    # 耳朵
    stroke(d, [(672, 470), (726, 486), (690, 524)], 16, CYAN, closed=True)
    stroke(d, mirror([(672, 470), (726, 486), (690, 524)]), 16, CYAN, closed=True)
    # 臉部低多邊形折線
    stroke(d, [(512, 398), (512, 636)], 12, CYAN)
    stroke(d, [(512, 486), (648, 506)], 12, CYAN)
    stroke(d, mirror([(512, 486), (648, 506)]), 12, CYAN)
    stroke(d, [(512, 566), (624, 600)], 12, CYAN)
    stroke(d, mirror([(512, 566), (624, 600)]), 12, CYAN)
    # 眼睛（洋紅發光）
    for ex in (452, 572):
        d.ellipse([ex - 22, 520 - 14, ex + 22, 520 + 14], fill=MAG + (255,))
    # 鼻吻
    stroke(d, [(470, 650), (512, 666), (554, 650)], 14, MAG)
    for nx in (488, 536):
        d.ellipse([nx - 8, 690 - 6, nx + 8, 690 + 6], fill=MAG + (255,))


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    base = redpurple_bg()
    neon = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    draw_neon(neon)
    base = Image.alpha_composite(base, neon.filter(ImageFilter.GaussianBlur(26)))
    base = Image.alpha_composite(base, neon.filter(ImageFilter.GaussianBlur(10)))
    base = Image.alpha_composite(base, neon)
    base.convert("RGB").resize((512, 512), Image.LANCZOS).save(
        os.path.join(cfg.OUTPUT_DIR, "cand_bull_drawn.png"))
    print("wrote output/cand_bull_drawn.png")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""最終 App 圖示：ComfyUI 霓虹牛(bull_gen_1) 稍微縮小，後方放一條清楚可見的
『紅色鋸齒上升線(有高有低)＋箭頭』(台灣紅=漲)。牛剪影去背後疊在最上層，鋸齒線大部分露出。"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

import config as cfg

SRC = "output/bull_gen_1.png"
RED = (255, 46, 70)


def stroke(d, pts, w, col):
    d.line(pts, fill=col + (255,), width=w, joint="curve")
    r = w // 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))


def redpurple_bg(N):
    gx, gy = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
    t = (gx + gy) / 2
    tl = np.array([32, 11, 40], float)
    br = np.array([66, 12, 42], float)
    bg = tl[None, None] + (br - tl)[None, None] * t[..., None]
    cx, cy = N * 0.52, N * 0.46
    d2 = (np.arange(N)[None, :] - cx) ** 2 + (np.arange(N)[:, None] - cy) ** 2
    w = np.exp(-d2 / (2 * (N * 0.34) ** 2))
    glow = np.array([116, 26, 80], float)
    bg = bg * (1 - 0.6 * w[..., None]) + glow[None, None] * (0.6 * w[..., None])
    return Image.fromarray(np.clip(bg, 0, 255).astype("uint8"), "RGB").convert("RGBA")


def bull_cutout(N):
    a = np.asarray(Image.open(SRC).convert("RGB"), float)
    val = a.max(axis=2)
    # 用較高門檻(只取明亮霓虹線)定義剪影，排除原圖那圈洋紅柔光（避免疊出暗盤）
    bright = val > 130
    sil = ndimage.binary_fill_holes(bright)           # 亮邊框住的內部facet→填實；肚下開口不填
    sil = ndimage.gaussian_filter(sil.astype(float), sigma=1.5)
    halo = np.clip((val - 150) / 100.0, 0, 1)
    alpha = np.clip(np.maximum(sil, halo), 0, 1)
    return Image.fromarray(np.dstack([a, alpha * 255]).astype("uint8"), "RGBA")


def main():
    base_src = Image.open(SRC).convert("RGB")
    N = base_src.size[0]
    s = N / 1024.0

    def P(x, y):
        return (x * s, y * s)

    base = redpurple_bg(N)

    # 紅色鋸齒上升線（角到角、振幅大→高低明顯）＋箭頭
    w = int(38 * s)
    arrow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    da = ImageDraw.Draw(arrow)
    zig = [(54, 902), (182, 720), (300, 804), (432, 560), (560, 664),
           (700, 440), (806, 556), (866, 392), (916, 160)]
    stroke(da, [P(x, y) for x, y in zig], w, RED)
    # 對稱箭頭：以最後一段方向為軸，左右各旋 34° 畫等長翼
    ax, ay = zig[-2]
    tx, ty = zig[-1]
    dx, dy = tx - ax, ty - ay
    L = math.hypot(dx, dy)
    bx, by = -dx / L, -dy / L                              # 由箭尖往回的單位向量
    ca, sa = math.cos(math.radians(34)), math.sin(math.radians(34))
    blen = 150
    e1 = (tx + (bx * ca - by * sa) * blen, ty + (bx * sa + by * ca) * blen)
    e2 = (tx + (bx * ca + by * sa) * blen, ty + (-bx * sa + by * ca) * blen)
    stroke(da, [P(tx, ty), P(*e1)], w, RED)
    stroke(da, [P(tx, ty), P(*e2)], w, RED)
    blank = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    glow = Image.alpha_composite(blank, arrow.filter(ImageFilter.GaussianBlur(int(26 * s))))
    glow = Image.alpha_composite(glow, arrow.filter(ImageFilter.GaussianBlur(int(9 * s))))
    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, arrow)

    # 牛去背、縮小、稍微左上偏移，疊在最上層（露出後方鋸齒線）
    bull = bull_cutout(N)
    scale = 0.82
    bw = int(N * scale)
    small = bull.resize((bw, bw), Image.LANCZOS)
    ox, oy = int((N - bw) * 0.40), int((N - bw) * 0.22)
    placed = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    placed.paste(small, (ox, oy), small)
    base = Image.alpha_composite(base, placed.filter(ImageFilter.GaussianBlur(int(15 * s))))  # 乾淨霓虹光暈
    base = Image.alpha_composite(base, placed)

    img = base.convert("RGB")
    img.save("app_icon_master.png")
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "cand_bull_final.png"))
    print("wrote app_icon_master.png (%dpx) + output/cand_bull_final.png" % N)


if __name__ == "__main__":
    main()

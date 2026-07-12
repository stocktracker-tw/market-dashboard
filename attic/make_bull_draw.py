# -*- coding: utf-8 -*-
"""在乾淨的 ComfyUI 牛(bull_gen_1)後方，手繪一支『霓虹紅色單向鋸齒上升箭頭』。
重點：保留牛的原始背景(不重建、不去背)＋箭頭做成發光霓虹管(外暈+亮芯)，疊在牛後方→自然不像貼上。"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

import config as cfg

SRC = "output/bull_gen_1.png"
RED = (255, 46, 70)
CORE = (255, 178, 188)


def stroke(d, pts, wd, col):
    d.line(pts, fill=col + (255,), width=wd, joint="curve")
    r = wd // 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))


def main():
    base = Image.open(SRC).convert("RGB")
    N = base.size[0]
    s = N / 1024.0
    a = np.asarray(base, float)
    val = a.max(axis=2)

    # 牛剪影（只取明亮霓虹，門檻高於洋紅柔光）→ 箭頭只畫在牛後方背景
    sil = ndimage.binary_fill_holes(val > 120)
    sil = ndimage.gaussian_filter(sil.astype(float), sigma=3)
    halo = np.clip((val - 150) / 100.0, 0, 1)
    a_bull = np.clip(np.maximum(sil, halo), 0, 1)
    bg_mask = 1.0 - a_bull

    def P(x, y):
        return (x * s, y * s)

    # 鋸齒上升線（有高低、整體往右上、單一單箭頭）
    zig = [(70, 902), (200, 754), (312, 842), (446, 628), (568, 744),
           (708, 510), (826, 614), (912, 352), (958, 166)]
    w = int(34 * s)
    arrow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    da = ImageDraw.Draw(arrow)
    stroke(da, [P(x, y) for x, y in zig], w, RED)
    ax, ay = zig[-2]
    tx, ty = zig[-1]
    dx, dy = tx - ax, ty - ay
    L = math.hypot(dx, dy)
    bx, by = -dx / L, -dy / L
    ca, sa = math.cos(math.radians(33)), math.sin(math.radians(33))
    bl = 150
    e1 = (tx + (bx * ca - by * sa) * bl, ty + (bx * sa + by * ca) * bl)
    e2 = (tx + (bx * ca + by * sa) * bl, ty + (-bx * sa + by * ca) * bl)
    stroke(da, [P(tx, ty), P(*e1)], w, RED)
    stroke(da, [P(tx, ty), P(*e2)], w, RED)

    # 亮芯（霓虹管中心更白亮）
    core = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    dc = ImageDraw.Draw(core)
    cw = int(12 * s)
    stroke(dc, [P(x, y) for x, y in zig], cw, CORE)
    stroke(dc, [P(tx, ty), P(*e1)], cw, CORE)
    stroke(dc, [P(tx, ty), P(*e2)], cw, CORE)

    blank = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    layer = Image.alpha_composite(blank, arrow.filter(ImageFilter.GaussianBlur(int(30 * s))))   # 外暈
    layer = Image.alpha_composite(layer, arrow.filter(ImageFilter.GaussianBlur(int(11 * s))))   # 內暈
    layer = Image.alpha_composite(layer, arrow)
    layer = Image.alpha_composite(layer, core)

    la = np.asarray(layer, float)
    a_ar = la[:, :, 3] / 255.0
    rgb = la[:, :, :3]
    wgt = (a_ar * bg_mask)[..., None]
    out = a * (1 - wgt) + rgb * wgt

    img = Image.fromarray(np.clip(out, 0, 255).astype("uint8"), "RGB")
    img.save("app_icon_master.png")
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "cand_bull_draw.png"))
    print("wrote app_icon_master.png + output/cand_bull_draw.png")


if __name__ == "__main__":
    main()

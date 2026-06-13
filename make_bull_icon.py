# -*- coding: utf-8 -*-
"""把使用者的霓虹牛主視覺做成 App 圖示：保留霓虹原色，黑底換成『紅紫』漸層。
產生 app_icon_master.png（給 make_icon.py 用）+ 預覽 output/cand_bull_rp.png。一次性。"""
import os

import numpy as np
from PIL import Image, ImageDraw

import config as cfg

# 燭台群落在「箭頭下方、牛右側」的楔形區。把這塊的霓虹塗掉（變黑→之後顯示背景）即可移除 K 棒。
CANDLE_POLY = [(0.40, 1.00), (0.47, 0.67), (0.70, 0.42), (0.92, 0.25), (1.00, 0.25), (1.00, 1.00)]

SRCJPG = "56605b9d-6312-4783-b674-744d00b9574e.jpg"


def crop_master():
    im = Image.open(SRCJPG).convert("RGB")
    W, H = im.size
    side, cx = H, 540
    left = max(0, min(W - side, int(cx - side / 2)))   # 排除右下浮水印
    return im.crop((left, 0, left + side, side))


def redpurple_bg(N):
    gx, gy = np.meshgrid(np.linspace(0, 1, N), np.linspace(0, 1, N))
    t = (gx + gy) / 2
    tl = np.array([60, 12, 96], float)     # 左上：紫
    br = np.array([128, 16, 60], float)    # 右下：紅
    bg = tl[None, None] + (br - tl)[None, None] * t[..., None]
    cx = cy = N * 0.5
    d2 = (np.arange(N)[None, :] - cx) ** 2 + (np.arange(N)[:, None] - cy) ** 2
    w = np.exp(-d2 / (2 * (N * 0.30) ** 2))                # 中央洋紅輝光
    glow = np.array([158, 34, 118], float)
    bg = bg * (1 - 0.5 * w[..., None]) + glow[None, None] * (0.5 * w[..., None])
    return bg


def taiwanize(arr):
    """台灣慣例：紅=漲、綠=跌。把圖中的純綠↔純紅互換（上升箭頭→紅），
    青色/洋紅的牛本體（B 高）不受影響。"""
    R, G, B = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    green = (G > R + 24) & (G > B + 24)   # 純綠（青色 B 高，被排除）
    red = (R > G + 24) & (R > B + 24)     # 純紅（洋紅 B 高，被排除）
    mask = green | red
    out = arr.copy()
    out[:, :, 0] = np.where(mask, G, R)   # 交換 R/G → 綠↔紅
    out[:, :, 1] = np.where(mask, R, G)
    return out


def remove_candles(arr):
    N = arr.shape[0]
    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).polygon([(x * N, y * N) for x, y in CANDLE_POLY], fill=255)
    out = arr.copy()
    out[np.asarray(m) > 0] = 0.0   # 該楔形塗黑＝移除 K 棒（黑底之後換成背景）
    return out


def compose(boost=2.0):
    crop = crop_master()
    N = crop.size[0]
    bull = taiwanize(remove_candles(np.asarray(crop, float)))
    val = bull.max(axis=2)                                  # 用亮度(最大通道)當 alpha，換色不影響強度
    alpha = np.clip(val / 255.0 * boost, 0, 1)[..., None]   # 霓虹處 alpha→1（原色），黑底→0（顯示背景）
    out = redpurple_bg(N) * (1 - alpha) + bull * alpha
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"), "RGB")


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    img = compose()
    img.save("app_icon_master.png")
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "cand_bull_rp.png"))
    print("wrote app_icon_master.png (%dpx) + preview output/cand_bull_rp.png" % img.size[0])


if __name__ == "__main__":
    main()

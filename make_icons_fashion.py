# -*- coding: utf-8 -*-
"""第二批「時尚」App 圖示候選（E/F/G/H）+ 預覽頁 output/icons2.html。
風格：極光漸層、霧面玻璃字標、光澤蠟燭、霓虹環。挑選後寫進 make_icon.py。一次性。"""
import math
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import config as cfg

SS = 1024


def load_font(size):
    for p in (r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msjh.ttc",
              r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def lin_grad(c0, c1, vertical=True):
    t = np.linspace(0, 1, SS)
    tt = t.reshape(-1, 1).repeat(SS, 1) if vertical else t.reshape(1, -1).repeat(SS, 0)
    c0 = np.array(c0, float); c1 = np.array(c1, float)
    return c0.reshape(1, 1, 3) + (c1 - c0).reshape(1, 1, 3) * tt[..., None]


def to_img(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB").convert("RGBA")


def soft(layer, blur):
    return layer.filter(ImageFilter.GaussianBlur(blur))


def round_mask(box, rad):
    m = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=rad, fill=255)
    return m


def clip(layer, mask):
    return Image.composite(layer, Image.new("RGBA", (SS, SS), (0, 0, 0, 0)), mask)


# ---------- E. 極光漸層 + 細線上升 ----------
def cand_aurora():
    img = np.ones((SS, SS, 3)) * np.array([18, 16, 44], float)
    ys, xs = np.mgrid[0:SS, 0:SS]
    stops = [(250, 250, 430, (124, 70, 255)), (820, 300, 450, (40, 160, 255)),
             (300, 820, 470, (0, 210, 200)), (790, 820, 430, (255, 70, 165)),
             (512, 500, 360, (120, 90, 255))]
    for cx, cy, r, col in stops:
        w = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2.0 * r * r)))
        col = np.array(col, float)
        for c in range(3):
            img[:, :, c] = img[:, :, c] * (1 - w) + col[c] * w
    base = to_img(img)
    pts = [(208, 726), (380, 604), (520, 658), (664, 466), (824, 352)]
    gl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    for i in range(len(pts) - 1):
        gd.line([pts[i], pts[i + 1]], fill=(255, 255, 255, 255), width=18)
    base = Image.alpha_composite(base, soft(gl, 24))
    d = ImageDraw.Draw(base)
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=(255, 255, 255, 255), width=13)
    for p in pts:
        d.ellipse([p[0] - 11, p[1] - 11, p[0] + 11, p[1] + 11], fill=(255, 255, 255, 255))
    ex, ey = pts[-1]
    d.ellipse([ex - 24, ey - 24, ex + 24, ey + 24], fill=(255, 255, 255, 255))
    return base.convert("RGB")


# ---------- F. 霧面玻璃字標「進」 ----------
def cand_glass_word():
    arr = lin_grad((48, 40, 152), (150, 46, 138)) * 0.6 + lin_grad((48, 40, 152), (40, 150, 220), False) * 0.4
    base = to_img(arr)
    box, rad = [200, 200, 824, 824], 158
    m = round_mask(box, rad)
    panel = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(box, radius=rad, fill=(255, 255, 255, 40))
    pd.rounded_rectangle(box, radius=rad, outline=(255, 255, 255, 150), width=4)
    base = Image.alpha_composite(base, panel)
    gloss = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rounded_rectangle([box[0], box[1], box[2], (box[1] + box[3]) // 2],
                                            radius=rad, fill=(255, 255, 255, 46))
    base = Image.alpha_composite(base, clip(soft(gloss, 34), m))
    d = ImageDraw.Draw(base)
    f = load_font(330)
    txt = "進"
    bb = d.textbbox((0, 0), txt, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x, y = cx - tw / 2 - bb[0], cy - th / 2 - bb[1]
    sh = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 4, y + 9), txt, font=f, fill=(0, 0, 40, 120))
    base = Image.alpha_composite(base, soft(sh, 13))
    ImageDraw.Draw(base).text((x, y), txt, font=f, fill=(251, 252, 255, 255))
    return base.convert("RGB")


# ---------- G. 光澤漸層蠟燭 ----------
def cand_candles():
    base = to_img(lin_grad((16, 40, 64), (9, 14, 38)))
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([180, -220, 844, 430], fill=(40, 205, 165, 70))
    base = Image.alpha_composite(base, soft(glow, 130))
    bars = [(322, 632, 812), (512, 486, 812), (702, 352, 812)]
    bw = 96
    mask = Image.new("L", (SS, SS), 0)
    mm = ImageDraw.Draw(mask)
    for cx, top, bot in bars:
        mm.rounded_rectangle([cx - bw / 2, top, cx + bw / 2, bot], radius=46, fill=255)
    grad = to_img(lin_grad((64, 232, 184), (44, 150, 255)))
    barfill = clip(grad, mask)
    shadow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    shadow.paste((0, 0, 30, 150), (0, 0), mask)
    shadow = soft(ImageChops.offset(shadow, 10, 20), 22)
    base = Image.alpha_composite(base, shadow)
    base = Image.alpha_composite(base, barfill)
    hl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    for cx, top, bot in bars:
        hd.rounded_rectangle([cx - bw / 2 + 12, top + 12, cx - bw / 2 + 34, bot - 14], radius=12, fill=(255, 255, 255, 95))
    base = Image.alpha_composite(base, clip(soft(hl, 6), mask))
    d = ImageDraw.Draw(base)
    for cx, top, bot in bars:
        d.line([(cx, top - 72), (cx, top + 12)], fill=(224, 246, 255, 255), width=10)
        d.ellipse([cx - 6, top - 84, cx + 6, top - 72], fill=(224, 246, 255, 255))
    return base.convert("RGB")


# ---------- H. 霓虹環 + 端點光點 ----------
def cand_neon():
    base = to_img(lin_grad((12, 13, 28), (6, 7, 16)))
    g = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([190, 190, 834, 834], fill=(46, 44, 130, 95))
    base = Image.alpha_composite(base, soft(g, 130))
    cx, cy, R, w = 512, 512, 300, 30
    bbox = [cx - R, cy - R, cx + R, cy + R]
    arc = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc)
    a0, a1, N = 140, 400, 84
    for i in range(N):
        t = i / (N - 1)
        aa = a0 + (a1 - a0) * t
        col = (int(0 + 255 * t), int(230 + (60 - 230) * t), int(255 + (180 - 255) * t), 255)
        ad.arc(bbox, aa, aa + (a1 - a0) / N + 1.6, fill=col, width=w)
    glowarc = soft(arc, 28)
    base = Image.alpha_composite(base, glowarc)
    base = Image.alpha_composite(base, glowarc)
    base = Image.alpha_composite(base, arc)
    rad = math.radians(a1)
    ex, ey = cx + math.cos(rad) * R, cy + math.sin(rad) * R
    dot = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse([ex - 28, ey - 28, ex + 28, ey + 28], fill=(255, 120, 205, 255))
    base = Image.alpha_composite(base, soft(dot, 18))
    ImageDraw.Draw(base).ellipse([ex - 16, ey - 16, ex + 16, ey + 16], fill=(255, 255, 255, 255))
    return base.convert("RGB")


CANDS = [("e", "極光 Aurora", cand_aurora),
         ("f", "玻璃字標 Glass 進", cand_glass_word),
         ("g", "光澤蠟燭 Candles", cand_candles),
         ("h", "霓虹環 Neon", cand_neon)]


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    for k, _, fn in CANDS:
        fn().resize((512, 512), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "cand_%s.png" % k))
    cards = "".join(
        '<figure><img src="cand_%s.png" alt=""><figcaption>%s · %s</figcaption></figure>' % (k, k.upper(), nm)
        for k, nm, _ in CANDS)
    html = (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<title>時尚 App 圖示候選</title><style>'
        'body{margin:0;background:#0a1430;color:#eaf0fb;font-family:"Microsoft JhengHei",system-ui;'
        'text-align:center;padding:26px 18px 60px}h1{font-size:20px;margin:.2em 0}'
        '.muted{color:#9fb0cc;font-size:13px}'
        '.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:540px;margin:20px auto}'
        'figure{margin:0}img{width:100%;max-width:200px;border-radius:44px;box-shadow:0 14px 34px rgba(0,0,0,.55)}'
        'figcaption{margin-top:9px;font-size:14px;color:#b6c3da}</style></head><body>'
        '<h1>時尚版 App 圖示候選</h1>'
        '<div class="muted">圓角是 iOS 主畫面實際呈現。挑一個告訴我 E／F／G／H。</div>'
        '<div class="grid">' + cards + '</div></body></html>')
    with open(os.path.join(cfg.OUTPUT_DIR, "icons2.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote cand_e..h.png + icons2.html")


if __name__ == "__main__":
    main()

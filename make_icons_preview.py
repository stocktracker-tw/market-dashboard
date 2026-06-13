# -*- coding: utf-8 -*-
"""產生 4 款 App 圖示候選 + 預覽頁 output/icons.html，讓使用者挑選。
選定後再由 make_icon.py / apply 寫成正式 icon-512/192/180.png。一次性工具。"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config as cfg

SS = 1024  # 超取樣，最後縮到 512 抗鋸齒


def vgrad(top, bot, diag=False):
    if diag:
        gx, gy = np.meshgrid(np.linspace(0, 1, SS), np.linspace(0, 1, SS))
        tt = (gx + gy) / 2
    else:
        tt = np.repeat(np.linspace(0, 1, SS).reshape(-1, 1), SS, axis=1)
    top = np.array(top, float); bot = np.array(bot, float)
    arr = (top.reshape(1, 1, 3) + (bot - top).reshape(1, 1, 3) * tt[..., None]).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def soft(layer, blur):
    return layer.filter(ImageFilter.GaussianBlur(blur))


def load_font(size):
    for p in (r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msjh.ttc",
              r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def grad_arc(d, bbox, a0, a1, w, c0, c1, n=64):
    for i in range(n):
        t = i / (n - 1)
        aa = a0 + (a1 - a0) * t
        col = tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3)) + (255,)
        d.arc(bbox, aa, aa + (a1 - a0) / n + 1.6, fill=col, width=w)


def cap(d, cx, cy, R, ang, w, col):
    rad = math.radians(ang)
    ex, ey = cx + math.cos(rad) * R, cy + math.sin(rad) * R
    d.ellipse([ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2], fill=col)
    return ex, ey


def cand_gauge():
    base = vgrad((30, 66, 156), (8, 15, 42))
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([SS * .1, -SS * .2, SS * .9, SS * .55], fill=(80, 140, 255, 70))
    base = Image.alpha_composite(base, soft(glow, 120))
    cx, cy, R, w = 512, 545, 300, 66
    bbox = [cx - R, cy - R, cx + R, cy + R]
    tr = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(tr).arc(bbox, 135, 45, fill=(255, 255, 255, 50), width=w)  # 軌道（缺口在下）
    base = Image.alpha_composite(base, tr)
    d = ImageDraw.Draw(base)
    grad_arc(d, bbox, 135, 324, w, (92, 150, 255), (44, 208, 142))   # 進度 70%
    cap(d, cx, cy, R, 135, w, (92, 150, 255, 255))
    ex, ey = cap(d, cx, cy, R, 324, w, (44, 208, 142, 255))
    g2 = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(g2).ellipse([ex - 80, ey - 80, ex + 80, ey + 80], fill=(60, 235, 150, 210))
    base = Image.alpha_composite(base, soft(g2, 46))
    return base.convert("RGB")


def cand_chart():
    base = vgrad((24, 44, 132), (74, 26, 122), diag=True)
    pts = [(170, 700), (330, 600), (470, 655), (620, 470), (770, 520), (885, 320)]
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i in range(len(pts) - 1):
        gd.line([pts[i], pts[i + 1]], fill=(90, 210, 255, 255), width=34)
    base = Image.alpha_composite(base, soft(glow, 30))
    af = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(af).polygon(pts + [(885, 840), (170, 840)], fill=(90, 200, 255, 50))
    base = Image.alpha_composite(base, af)
    d = ImageDraw.Draw(base)
    for i in range(len(pts) - 1):
        t = i / (len(pts) - 2)
        col = (int(90 + (50 - 90) * t), int(200 + (222 - 200) * t), int(255 + (150 - 255) * t), 255)
        d.line([pts[i], pts[i + 1]], fill=col, width=34)
        d.ellipse([pts[i][0] - 17, pts[i][1] - 17, pts[i][0] + 17, pts[i][1] + 17], fill=col)
    ax, ay = pts[-1]
    d.ellipse([ax - 19, ay - 19, ax + 19, ay + 19], fill=(50, 224, 150, 255))
    d.polygon([(ax + 96, ay - 96), (ax + 18, ay - 70), (ax + 70, ay - 18)], fill=(50, 224, 150, 255))
    return base.convert("RGB")


def cand_arrow():
    base = vgrad((10, 32, 96), (22, 86, 168), diag=True)
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([SS * .12, -SS * .15, SS * .88, SS * .5], fill=(90, 160, 255, 70))
    base = Image.alpha_composite(base, soft(glow, 110))
    cx, cy, R, w = 512, 512, 300, 58
    bbox = [cx - R, cy - R, cx + R, cy + R]
    tr = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(tr).arc(bbox, 130, 50, fill=(255, 255, 255, 50), width=w)
    base = Image.alpha_composite(base, tr)
    d = ImageDraw.Draw(base)
    grad_arc(d, bbox, 130, 354, w, (70, 160, 255), (52, 214, 150))
    cap(d, cx, cy, R, 130, w, (70, 160, 255, 255))
    cap(d, cx, cy, R, 354, w, (52, 214, 150, 255))
    col = (242, 248, 255)
    d.line([(cx, cy + 130), (cx, cy - 116)], fill=col, width=48)
    d.line([(cx, cy - 134), (cx - 96, cy - 38)], fill=col, width=48)
    d.line([(cx, cy - 134), (cx + 96, cy - 38)], fill=col, width=48)
    for p in [(cx, cy + 130), (cx, cy - 124), (cx - 96, cy - 38), (cx + 96, cy - 38)]:
        d.ellipse([p[0] - 24, p[1] - 24, p[0] + 24, p[1] + 24], fill=col)
    return base.convert("RGB")


def cand_word():
    base = vgrad((38, 48, 152), (120, 40, 150), diag=True)
    gl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gl).ellipse([SS * .1, -SS * .25, SS * .9, SS * .5], fill=(150, 170, 255, 55))
    base = Image.alpha_composite(base, soft(gl, 120))
    d = ImageDraw.Draw(base)
    f = load_font(540)
    txt = "進"
    bb = d.textbbox((0, 0), txt, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = (SS - tw) / 2 - bb[0]
    y = (SS - th) / 2 - bb[1] - 16
    sh = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 6, y + 18), txt, font=f, fill=(0, 0, 30, 130))
    base = Image.alpha_composite(base, soft(sh, 20))
    ImageDraw.Draw(base).text((x, y), txt, font=f, fill=(246, 249, 255, 255))
    return base.convert("RGB")


CANDS = [("a", "儀表 Gauge", cand_gauge),
         ("b", "上升線 Chart", cand_chart),
         ("c", "上升箭頭 Arrow", cand_arrow),
         ("d", "進字 Wordmark", cand_word)]


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
        '<title>App 圖示候選</title><style>'
        'body{margin:0;background:#0a1430;color:#eaf0fb;font-family:"Microsoft JhengHei",system-ui;'
        'text-align:center;padding:26px 18px 60px}h1{font-size:20px;margin:.2em 0}'
        '.muted{color:#9fb0cc;font-size:13px}'
        '.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:540px;margin:20px auto}'
        'figure{margin:0}img{width:100%;max-width:200px;border-radius:44px;box-shadow:0 14px 34px rgba(0,0,0,.55)}'
        'figcaption{margin-top:9px;font-size:14px;color:#b6c3da}</style></head><body>'
        '<h1>App 圖示候選</h1>'
        '<div class="muted">圓角是 iOS 主畫面實際呈現的樣子。挑一個告訴我 A／B／C／D，我就套成正式圖示。</div>'
        '<div class="grid">' + cards + '</div></body></html>')
    with open(os.path.join(cfg.OUTPUT_DIR, "icons.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote cand_a..d.png + icons.html")


if __name__ == "__main__":
    main()

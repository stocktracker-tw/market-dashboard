# -*- coding: utf-8 -*-
"""霓虹玻璃 App 圖示候選（M/N）+ 預覽頁 output/icons4.html。
霧面玻璃卡片 + 霓虹發光（環 / 進字）。挑選後寫進 make_icon.py。一次性。"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

import config as cfg
from make_icons_fashion import SS, clip, lin_grad, load_font, round_mask, soft, to_img

BOX, RAD = [176, 176, 848, 848], 172


def glass_panel(base):
    """把中央區域做成霧面玻璃：背景模糊 + 白色薄膜 + 邊緣高光 + 上緣柔光。"""
    m = round_mask(BOX, RAD)
    base = Image.composite(base.filter(ImageFilter.GaussianBlur(22)), base, m)
    tint = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(tint).rounded_rectangle(BOX, radius=RAD, fill=(255, 255, 255, 30))
    return Image.alpha_composite(base, tint), m


def glass_edge(base, m):
    gloss = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rounded_rectangle([BOX[0], BOX[1], BOX[2], (BOX[1] + BOX[3]) // 2],
                                            radius=RAD, fill=(255, 255, 255, 26))
    base = Image.alpha_composite(base, clip(soft(gloss, 30), m))
    edge = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(BOX, radius=RAD, outline=(255, 255, 255, 160), width=4)
    return Image.alpha_composite(base, edge)


# ---------- M. 霓虹玻璃・環 ----------
def cand_neon_glass_ring():
    base = to_img(lin_grad((16, 18, 42), (8, 9, 20)))
    g = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([170, 170, 854, 854], fill=(54, 42, 130, 95))
    base = Image.alpha_composite(base, soft(g, 150))
    base, m = glass_panel(base)
    cx, cy, R, w = 512, 512, 248, 26
    bbox = [cx - R, cy - R, cx + R, cy + R]
    arc = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc)
    a0, a1, N = 140, 400, 84
    for i in range(N):
        t = i / (N - 1)
        aa = a0 + (a1 - a0) * t
        col = (int(0 + 255 * t), int(230 + (60 - 230) * t), int(255 + (180 - 255) * t), 255)
        ad.arc(bbox, aa, aa + (a1 - a0) / N + 1.6, fill=col, width=w)
    glow = soft(arc, 30)
    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, arc)
    rad = math.radians(a1)
    ex, ey = cx + math.cos(rad) * R, cy + math.sin(rad) * R
    dot = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse([ex - 24, ey - 24, ex + 24, ey + 24], fill=(255, 120, 205, 255))
    base = Image.alpha_composite(base, soft(dot, 16))
    ImageDraw.Draw(base).ellipse([ex - 13, ey - 13, ex + 13, ey + 13], fill=(255, 255, 255, 255))
    base = glass_edge(base, m)
    return base.convert("RGB")


# ---------- N. 霓虹玻璃・進字 ----------
def cand_neon_glass_word():
    base = to_img(lin_grad((20, 18, 48), (9, 10, 22)))
    g = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([170, 150, 854, 760], fill=(60, 44, 140, 95))
    base = Image.alpha_composite(base, soft(g, 150))
    base, m = glass_panel(base)
    f = load_font(330)
    txt = "進"
    tmp = ImageDraw.Draw(base)
    bb = tmp.textbbox((0, 0), txt, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x, y = (SS - tw) / 2 - bb[0], (SS - th) / 2 - bb[1] - 8
    gl = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gl).text((x, y), txt, font=f, fill=(0, 232, 255, 255))
    gl = soft(gl, 28)
    base = Image.alpha_composite(base, gl)
    base = Image.alpha_composite(base, gl)
    gl2 = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gl2).text((x, y), txt, font=f, fill=(255, 60, 185, 255))
    base = Image.alpha_composite(base, soft(gl2, 15))
    ImageDraw.Draw(base).text((x, y), txt, font=f, fill=(246, 252, 255, 255))
    base = glass_edge(base, m)
    return base.convert("RGB")


CANDS = [("m", "霓虹玻璃・環 Neon-Glass Ring", cand_neon_glass_ring),
         ("n", "霓虹玻璃・進 Neon-Glass 進", cand_neon_glass_word)]


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
        '<title>霓虹玻璃 App 圖示</title><style>'
        'body{margin:0;background:#0a1430;color:#eaf0fb;font-family:"Microsoft JhengHei",system-ui;'
        'text-align:center;padding:26px 18px 60px}h1{font-size:20px;margin:.2em 0}'
        '.muted{color:#9fb0cc;font-size:13px}'
        '.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:540px;margin:20px auto}'
        'figure{margin:0}img{width:100%;max-width:200px;border-radius:44px;box-shadow:0 14px 34px rgba(0,0,0,.55)}'
        'figcaption{margin-top:9px;font-size:13px;color:#b6c3da}</style></head><body>'
        '<h1>霓虹玻璃 App 圖示候選</h1>'
        '<div class="muted">霧面玻璃卡片 + 霓虹發光。挑一個告訴我 M／N，或要更亮/更暗/換色。</div>'
        '<div class="grid">' + cards + '</div></body></html>')
    with open(os.path.join(cfg.OUTPUT_DIR, "icons4.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote cand_m,n.png + icons4.html")


if __name__ == "__main__":
    main()

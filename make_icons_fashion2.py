# -*- coding: utf-8 -*-
"""第三批 App 圖示候選（I/J/K/L）+ 預覽頁 output/icons3.html。
風格：光澤 3D 箭頭、全像虹彩環、漸層山峰、鉻金屬字標。挑選後寫進 make_icon.py。一次性。"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import config as cfg
from make_icons_fashion import SS, clip, lin_grad, load_font, soft, to_img


# ---------- I. 光澤 3D 上升箭頭 ----------
def cand_arrow3():
    base = to_img(lin_grad((62, 30, 142), (22, 15, 58)))
    cx, cy, w = 512, 522, 124
    mask = Image.new("L", (SS, SS), 0)
    md = ImageDraw.Draw(mask)
    md.line([(cx, cy + 208), (cx, cy - 150)], fill=255, width=w)
    md.line([(cx, cy - 196), (cx - 182, cy - 16)], fill=255, width=w)
    md.line([(cx, cy - 196), (cx + 182, cy - 16)], fill=255, width=w)
    for p in [(cx, cy + 208), (cx, cy - 196), (cx - 182, cy - 16), (cx + 182, cy - 16)]:
        md.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=255)
    fill = to_img(lin_grad((0, 226, 255), (255, 80, 180)))
    base = Image.alpha_composite(base, soft(clip(fill, mask), 36))   # neon glow
    base = Image.alpha_composite(base, clip(fill, mask))             # crisp arrow
    gloss = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).rectangle([0, 0, SS, cy - 40], fill=(255, 255, 255, 78))
    base = Image.alpha_composite(base, clip(soft(gloss, 22), mask))
    return base.convert("RGB")


# ---------- J. 全像虹彩環 (holographic) ----------
def cand_holo():
    base = to_img(lin_grad((14, 14, 26), (8, 8, 16)))
    ys, xs = np.mgrid[0:SS, 0:SS]
    ph = 2 * np.pi * ((xs + ys) / 430.0)
    holo = np.dstack([0.5 + 0.5 * np.sin(ph), 0.5 + 0.5 * np.sin(ph + 2.094),
                      0.5 + 0.5 * np.sin(ph + 4.188)]) * 255
    holoimg = to_img(holo)
    cx, cy, Ro, Ri = 512, 512, 302, 198
    mask = Image.new("L", (SS, SS), 0)
    dm = ImageDraw.Draw(mask)
    dm.ellipse([cx - Ro, cy - Ro, cx + Ro, cy + Ro], fill=255)
    dm.ellipse([cx - Ri, cy - Ri, cx + Ri, cy + Ri], fill=0)
    base = Image.alpha_composite(base, soft(clip(holoimg, mask), 32))
    base = Image.alpha_composite(base, clip(holoimg, mask))
    sheen = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse([cx - Ro, cy - Ro, cx + Ro, cy - Ro + 230], fill=(255, 255, 255, 70))
    base = Image.alpha_composite(base, clip(soft(sheen, 24), mask))
    return base.convert("RGB")


# ---------- K. 漸層山峰 (summit) ----------
def cand_peaks():
    base = to_img(lin_grad((26, 28, 58), (12, 12, 28)))
    glow = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([300, 120, 724, 520], fill=(80, 120, 255, 70))
    base = Image.alpha_composite(base, soft(glow, 120))
    mback = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mback).polygon([(322, 726), (566, 318), (812, 726)], fill=255)
    mfront = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mfront).polygon([(196, 768), (432, 432), (664, 768)], fill=255)
    base = Image.alpha_composite(base, clip(to_img(lin_grad((92, 122, 255), (38, 58, 158))), mback))
    base = Image.alpha_composite(base, clip(to_img(lin_grad((0, 222, 200), (20, 118, 255))), mfront))
    cap = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(cap).polygon([(566, 318), (516, 402), (616, 402)], fill=(245, 250, 255, 235))
    base = Image.alpha_composite(base, cap)
    return base.convert("RGB")


# ---------- L. 鉻金屬字標「進」 ----------
def cand_chrome_word():
    base = to_img(lin_grad((22, 26, 44), (8, 10, 20)))
    ys, _ = np.mgrid[0:SS, 0:SS]
    v = 0.5 + 0.5 * np.sin(ys / 64.0)
    metal = to_img(np.dstack([148 + 95 * v, 168 + 82 * v, 212 + 42 * v]))
    f = load_font(360)
    txt = "進"
    mask = Image.new("L", (SS, SS), 0)
    md = ImageDraw.Draw(mask)
    bb = md.textbbox((0, 0), txt, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x, y = (SS - tw) / 2 - bb[0], (SS - th) / 2 - bb[1] - 12
    md.text((x, y), txt, font=f, fill=255)
    sh = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 6, y + 13), txt, font=f, fill=(0, 0, 0, 150))
    base = Image.alpha_composite(base, soft(sh, 14))
    base = Image.alpha_composite(base, clip(metal, mask))
    hi = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(hi).text((x, y), txt, font=f, fill=(255, 255, 255, 60))
    base = Image.alpha_composite(base, clip(hi, mask.point(lambda p: 255 if p else 0)))
    return base.convert("RGB")


CANDS = [("i", "光澤箭頭 Arrow", cand_arrow3),
         ("j", "虹彩環 Holo", cand_holo),
         ("k", "山峰 Summit", cand_peaks),
         ("l", "鉻金屬 進", cand_chrome_word)]


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
        '<title>時尚 App 圖示候選 3</title><style>'
        'body{margin:0;background:#0a1430;color:#eaf0fb;font-family:"Microsoft JhengHei",system-ui;'
        'text-align:center;padding:26px 18px 60px}h1{font-size:20px;margin:.2em 0}'
        '.muted{color:#9fb0cc;font-size:13px}'
        '.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:540px;margin:20px auto}'
        'figure{margin:0}img{width:100%;max-width:200px;border-radius:44px;box-shadow:0 14px 34px rgba(0,0,0,.55)}'
        'figcaption{margin-top:9px;font-size:14px;color:#b6c3da}</style></head><body>'
        '<h1>時尚版 App 圖示候選（第三批）</h1>'
        '<div class="muted">圓角是 iOS 主畫面實際呈現。挑一個告訴我 I／J／K／L。</div>'
        '<div class="grid">' + cards + '</div></body></html>')
    with open(os.path.join(cfg.OUTPUT_DIR, "icons3.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote cand_i..l.png + icons3.html")


if __name__ == "__main__":
    main()

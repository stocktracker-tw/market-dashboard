# -*- coding: utf-8 -*-
"""產生 App 圖示 —— 使用霓虹牛主視覺（紅紫底）app_icon_master.png。
輸出 icon-512/192/180.png + apple-icon-v3.png（新檔名＝強制 iOS 重抓）。一次性。
主檔由 make_bull_icon.py 產生（霓虹原色 + 黑底換紅紫、去浮水印）。"""
import os

from PIL import Image

import config as cfg

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon_master.png")


def main():
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    master = Image.open(SRC).convert("RGB")
    if master.size != (512, 512):
        master = master.resize((512, 512), Image.LANCZOS)
    master.save(os.path.join(cfg.OUTPUT_DIR, "icon-512.png"))
    master.resize((192, 192), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "icon-192.png"))
    master.resize((180, 180), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "icon-180.png"))
    master.resize((180, 180), Image.LANCZOS).save(os.path.join(cfg.OUTPUT_DIR, "apple-icon-v9.png"))
    print("bull icons (cyber bull head, ComfyUI) written to output/")


if __name__ == "__main__":
    main()

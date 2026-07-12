# -*- coding: utf-8 -*-
"""產生「邊緣折射位移圖」(liquid glass)：中心不動、邊緣像鏡片把背景往外彎曲。
R=水平位移、G=垂直位移(128=不動)。給 SVG feImage + feDisplacementMap 用。一次性。"""
import os
import numpy as np
from PIL import Image

import config as cfg

N = 420
xs = np.linspace(-1, 1, N)
gx, gy = np.meshgrid(xs, xs)

# 圓角矩形 SDF（內部為負）
r = 0.20                      # 角圓度
qx = np.abs(gx) - (1 - r)
qy = np.abs(gy) - (1 - r)
mqx = np.maximum(qx, 0.0)
mqy = np.maximum(qy, 0.0)
sdf = np.sqrt(mqx ** 2 + mqy ** 2) + np.minimum(np.maximum(qx, qy), 0.0) - r

edge = -sdf                   # 內部為正、邊界為 0
bw = 0.30                     # 折射帶寬（外側 30%）
t = np.clip(edge / bw, 0, 1)  # 0=邊界, 1=內部平面
mag = (1 - t) ** 1.5          # 位移強度：邊界最大、平滑歸零

# 外法線方向 = sdf 梯度（指向外/最近邊）
grow, gcol = np.gradient(sdf)
nx, ny = gcol, grow
nl = np.sqrt(nx ** 2 + ny ** 2) + 1e-6
nx, ny = nx / nl, ny / nl

dx = nx * mag
dy = ny * mag
R = np.clip(128 + dx * 127, 0, 255)
G = np.clip(128 + dy * 127, 0, 255)
B = np.full_like(R, 128.0)
A = np.full_like(R, 255.0)
img = np.dstack([R, G, B, A]).astype(np.uint8)

os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
Image.fromarray(img, "RGBA").save(os.path.join(cfg.OUTPUT_DIR, "glassmap.png"))
print("glassmap.png", img.shape, "center(should be ~128):", int(R[N // 2, N // 2]), int(G[N // 2, N // 2]))

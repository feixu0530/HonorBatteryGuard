# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""生成 HonorBatteryGuard.exe 的应用图标（电池 + 70% 上限标记）。"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "dev" / "HonorBatteryGuard.ico"
ACCENT = (79, 70, 229, 255)      # #4F46E5 靛蓝
WHITE = (255, 255, 255, 255)
LIGHT = (199, 210, 254, 255)

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角方形底
d.rounded_rectangle((16, 16, S - 16, S - 16), radius=104, fill=ACCENT)

# 电池外壳（横向）
bx0, by0, bx1, by1 = 92, 168, 392, 344
d.rounded_rectangle((bx0, by0, bx1, by1), radius=28, outline=WHITE, width=18)
# 正极凸起
d.rounded_rectangle((bx1 + 4, 226, bx1 + 34, 286), radius=12, fill=WHITE)

# 内部底衬
ix0, iy0, ix1, iy1 = bx0 + 30, by0 + 30, bx1 - 30, by1 - 30
d.rounded_rectangle((ix0, iy0, ix1, iy1), radius=12, fill=(255, 255, 255, 45))

# 70% 电量填充（从底部到 70% 高度）
fill_top = iy1 - int((iy1 - iy0) * 0.70)
d.rounded_rectangle((ix0 + 8, fill_top, ix1 - 8, iy1 - 8), radius=8, fill=WHITE)

# 上限标记线（70% 处）
d.line((bx0 - 18, fill_top, bx1 + 46, fill_top), fill=LIGHT, width=10)
d.ellipse((bx0 - 30, fill_top - 12, bx0 - 6, fill_top + 12), fill=LIGHT)

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                   (64, 64), (128, 128), (256, 256)])
print(f"icon written: {OUT} ({OUT.stat().st_size} bytes)")

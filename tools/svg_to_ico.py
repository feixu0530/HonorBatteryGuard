# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""用 reference/电池.svg 渲染应用图标，输出 dev/HonorBatteryGuard.ico 与 .png。

渲染链：svglib 解析 SVG -> reportlab 生成 PDF -> pypdfium2 光栅化 -> PIL 合成圆角底。
全部为纯 Python wheel，不依赖系统 cairo / 浏览器。失败时回退到 PIL 手绘近似图。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "reference" / "电池.svg"
OUT_ICO = ROOT / "dev" / "HonorBatteryGuard.ico"
OUT_PNG = ROOT / "dev" / "HonorBatteryGuard.png"
TMP = ROOT / "temp"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def render_svg() -> Image.Image | None:
    if not SVG.exists():
        return None
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
        import pypdfium2 as pdfium

        TMP.mkdir(exist_ok=True)
        pdf_path = TMP / "icon_render.pdf"
        drawing = svg2rlg(str(SVG))
        if drawing is None:
            return None
        renderPDF.drawToFile(drawing, str(pdf_path))
        doc = pdfium.PdfDocument(str(pdf_path))
        bitmap = doc[0].render(scale=4)
        img = bitmap.to_pil().convert("RGBA")
        print(f"SVG 渲染成功（{img.size}，svglib -> PDF -> pdfium）")
        return img
    except Exception as e:
        print("SVG 渲染失败：", e)
        return None


def fallback_draw() -> Image.Image:
    """SVG 不可渲染时的近似图：白色圆角底 + 黑框电池 + 绿色三格电量。"""
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=108, fill=(255, 255, 255, 255))
    bx0, by0, bx1, by1 = 132, 168, 380, 452
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=18, fill=(24, 24, 27, 255))
    d.rounded_rectangle((bx0 + 16, by0 + 16, bx1 - 16, by1 - 16), radius=6,
                        fill=(255, 255, 255, 255))
    d.rounded_rectangle((214, 128, 298, 176), radius=10, fill=(24, 24, 27, 255))
    g = (4, 207, 0, 255)
    for i in range(3):
        top = by0 + 26 + i * 88
        d.rounded_rectangle((bx0 + 26, top, bx1 - 26, top + 72), radius=4, fill=g)
    print("已使用 PIL 近似图（未找到 Edge 或渲染失败）")
    return img


def main():
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    raw = render_svg()
    if raw is None:
        img = fallback_draw()
    else:
        # 白色圆角底 + 居中的用户 SVG，四角透明，适配桌面/任务栏小尺寸
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, 511, 511), radius=108, fill=(255, 255, 255, 255))
        art = raw.resize((448, 448), Image.LANCZOS)
        img.alpha_composite(art, (32, 32))
    img.save(OUT_PNG)
    img.save(OUT_ICO, format="ICO", sizes=SIZES)
    print(f"写出 {OUT_ICO} ({OUT_ICO.stat().st_size} bytes)")
    print(f"写出 {OUT_PNG} ({OUT_PNG.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

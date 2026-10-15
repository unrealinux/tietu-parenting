"""把生成的插画压成 3:4 贴图卡，并在底部叠标题文字。

用法：
    python scripts/overlay_text.py --image in.png --out out.jpg \
        --text "生娃前 VS 生娃后" --sub "最狠的不是作息"

为什么不用 make_tietu_images.py：那个是纯文字卡渲染器（PIL 画字），
这个是把 AI 插画当底图再叠字，两条路互不影响。
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440           # 3:4，和纯文字卡一致
SCRIM_RATIO = 0.42          # 底部黑色渐隐高度占比

# 导出参数：质量 85 + 渐进式 + 4:2:2 色度采样。
# 配合这一套图（平涂贴纸/插画）肉眼无差，体积比 quality=92 小约 25–35%。
JPEG_OPTS = dict(quality=85, optimize=True, progressive=True, subsampling=1)


def _save(img: Image.Image, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, "JPEG", **JPEG_OPTS)
    return path


FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑粗体，压在复杂背景上更清楚
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]
SUB_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _cover(img: Image.Image) -> Image.Image:
    """等比缩放后居中裁切成 3:4，不拉伸变形。"""
    src_ratio = img.width / img.height
    dst_ratio = W / H
    if src_ratio > dst_ratio:               # 图太宽，按高对齐裁左右
        new_h = H
        new_w = int(H * src_ratio)
    else:                                   # 图太高，按宽对齐裁上下
        new_w = W
        new_h = int(W / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    return img.crop((left, top, left + W, top + H))


PUNCT_HEAD = "，。！？、；：）】」』…·%"


def _wrap(text: str, per_line: int) -> list[str]:
    """按字数折行，且不让标点落在行首（逗号挂在上一行末尾）。

    文本里的 \n 是硬换行，优先尊重（例如时间戳单独一行）。
    """
    out: list[str] = []
    for seg in text.split("\n"):
        if not seg:
            continue
        cur = ""
        for ch in seg:
            if cur and len(cur) >= per_line and ch not in PUNCT_HEAD:
                out.append(cur)
                cur = ""
            cur += ch
        if cur:
            out.append(cur)
    return out or [text]


MAX_TEXT_W = int(W * 0.94)

_ALL_SIZES = (108, 100, 92, 84, 76, 68, 60, 52)


def _fit_main(text: str, sizes: tuple[int, ...] | None = None,
              max_lines: int = 3) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """选字号：字数越多字号越小，行数不超过 max_lines，末行至少 3 字。

    避免两种丑图：末行只剩一两个字；大字压满整张插画。
    """
    if sizes is None:
        n = max((len(s) for s in text.split("\n")), default=0)
        cap = 108 if n <= 12 else 84 if n <= 18 else 72 if n <= 26 else 60
        sizes = tuple(s for s in _ALL_SIZES if s <= cap)
    for size in sizes:
        f = _font(FONT_CANDIDATES, size)
        per = max(4, int(MAX_TEXT_W // f.size))
        lines = _wrap(text, per)
        if len(lines) <= max_lines and (len(lines) == 1 or len(lines[-1]) >= 3):
            return f, lines
    f = _font(FONT_CANDIDATES, sizes[-1])
    return f, _wrap(text, max(4, int(MAX_TEXT_W // f.size)))


def _draw_scrim(img: Image.Image, top: int) -> None:
    """从 top 到底部叠一层由透明到半黑的渐变，保证文字可读。"""
    scrim = Image.new("L", (1, H - top), 0)
    px = scrim.load()
    for y in range(H - top):
        px[0, y] = int(215 * min(1.0, (y / (H - top)) ** 0.75))
    black = Image.new("RGB", (W, H - top), (0, 0, 0))
    img.paste(black, (0, top), scrim.resize((W, H - top)))


def overlay(image_path: str, out_path: str, text: str, sub: str = "",
            per_line: int = 9, scrim: bool = True, dark_text: bool = False,
            main_sizes: tuple[int, ...] | None = None,
            max_main_lines: int = 3) -> str:
    """底图 + 底部叠字。

    scrim=False   不画背景压暗渐变（适合纯白底的简笔画，叠黑字）
    dark_text=True 黑字白描边（white background 风格专用）
    main_sizes / max_main_lines  控制主文案字号与行数（白底留白区窄时限制成一行）
    """
    img = _cover(Image.open(image_path).convert("RGB"))

    f_main, main_lines = _fit_main(text, sizes=main_sizes, max_lines=max_main_lines)
    line_h = int(f_main.size * 1.32)

    sub_lines = _wrap(sub, 16) if sub else []
    f_sub = _font(SUB_FONT_CANDIDATES, 44)
    sub_h = int(44 * 1.6) * len(sub_lines) + (34 if sub_lines else 0)

    block_h = line_h * len(main_lines) + sub_h
    bottom_pad = 150
    top_y = H - bottom_pad - block_h

    if scrim:
        _draw_scrim(img, int(top_y - 90))
    d = ImageDraw.Draw(img)

    main_fill = (34, 30, 27) if dark_text else (255, 255, 255)
    main_stroke = (255, 255, 255) if dark_text else (20, 16, 12)
    sub_fill = (110, 104, 96) if dark_text else (240, 234, 224)
    sub_stroke = (255, 255, 255) if dark_text else (20, 16, 12)

    y = top_y
    for ln in main_lines:
        w = d.textlength(ln, font=f_main)
        d.text(((W - w) / 2, y), ln, fill=main_fill, font=f_main,
               stroke_width=5, stroke_fill=main_stroke)
        y += line_h
    for ln in sub_lines:
        w = d.textlength(ln, font=f_sub)
        d.text(((W - w) / 2, y), ln, fill=sub_fill, font=f_sub,
               stroke_width=3, stroke_fill=sub_stroke)
        y += int(44 * 1.6)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    _save(img, out_path)
    return out_path


def _draw_top_scrim(img: Image.Image, bottom: int) -> None:
    """从上往下的渐隐，给顶部文案用。"""
    h = bottom
    scrim = Image.new("L", (1, h), 0)
    px = scrim.load()
    for y in range(h):
        px[0, y] = int(215 * min(1.0, (1 - y / h) ** 0.75))
    black = Image.new("RGB", (W, h), (0, 0, 0))
    img.paste(black, (0, 0), scrim.resize((W, h)))


def overlay_pair(image_path: str, out_path: str, top: str, bottom: str) -> str:
    """对比卡：上半句在上方（白字），下半句在下方（淡字），中间留出画面。"""
    img = _cover(Image.open(image_path).convert("RGB"))

    f_top, top_lines = _fit_main(top, sizes=(88, 80, 72, 64))
    f_bot, bot_lines = _fit_main(bottom, sizes=(80, 72, 64))
    top_h = int(f_top.size * 1.3) * len(top_lines)
    bot_h = int(f_bot.size * 1.3) * len(bot_lines)

    pad = 120
    _draw_top_scrim(img, pad + top_h + 90)
    _draw_scrim(img, H - pad - bot_h - 90)
    d = ImageDraw.Draw(img)

    y = pad
    for ln in top_lines:
        w = d.textlength(ln, font=f_top)
        d.text(((W - w) / 2, y), ln, fill=(255, 255, 255), font=f_top,
               stroke_width=5, stroke_fill=(20, 16, 12))
        y += int(f_top.size * 1.3)

    y = H - pad - bot_h
    for ln in bot_lines:
        w = d.textlength(ln, font=f_bot)
        d.text(((W - w) / 2, y), ln, fill=(246, 232, 216), font=f_bot,
               stroke_width=4, stroke_fill=(20, 16, 12))
        y += int(f_bot.size * 1.3)

    _save(img, out_path)
    return out_path


def overlay_card(image_path: str, out_path: str, card: dict) -> str:
    """按卡片结构自动选叠字方式，三种卡都支持。"""
    if card.get("a") and card.get("b"):
        return overlay_pair(image_path, out_path, card["a"], card["b"])
    if card.get("lines"):
        return overlay(image_path, out_path, card.get("label", ""),
                       " · ".join(card["lines"][:3]))
    return overlay(image_path, out_path, card["text"], card.get("sub", ""))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="插画底图叠标题文字，输出 3:4 贴图卡")
    ap.add_argument("--image", required=True, help="底图（Agnes 生成的 png）")
    ap.add_argument("--out", required=True, help="输出 jpg")
    ap.add_argument("--text", required=True, help="主标题")
    ap.add_argument("--sub", default="", help="副标题")
    ap.add_argument("--per-line", type=int, default=9, help="主标题每行字数")
    args = ap.parse_args()

    path = overlay(args.image, args.out, args.text, args.sub, args.per_line)
    print(f"已生成 {path}（{W}x{H}）")


if __name__ == "__main__":
    main()

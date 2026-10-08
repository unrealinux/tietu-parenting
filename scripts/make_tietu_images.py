"""把贴图号文案渲染成 1–3 张有递进关系的图片（3:4）。

用法：
    python scripts/make_tietu_images.py posts/tietu_002_week1-vs-year3.json

输入 JSON 结构（cards 保持 1–3 张，手册硬规则）：
    {
      "slug": "week1-vs-year3",
      "title": "草稿标题",
      "content": "发布文案",
      "cards": [
        {"label": "入职第一周", "lines": ["代码能跑就行", "主动参加会议"]},   # 清单卡
        {"a": "第一周：认真写注释", "b": "第三年：// 别动，能跑"},          # 对比卡
        {"text": "你是第几年？", "sub": "评论区留一句"}                      # 单句卡
      ]
    }

递进自检（写内容时必须过这一关）：
    遮住其中一张，如果整条内容完全不受影响 → 这张只是装饰，删掉。
"""
import json
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440  # 3:4
MARGIN = 110
BG = (250, 247, 240)          # 米白纸
INK = (38, 34, 30)            # 墨色
SUB_INK = (120, 112, 102)     # 副文案灰
RULE = (210, 202, 190)        # 细分割线

FONT_CANDIDATES = [
    "C:/Windows/Fonts/simkai.ttf",    # 楷体，最接近手写
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(text: str, per_line: int) -> list[str]:
    """中文按字数折行。"""
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= per_line:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines


def _center(d: ImageDraw.ImageDraw, text: str, y: int, font, fill) -> None:
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, fill, font=font)


def _draw_label_card(d: ImageDraw.ImageDraw, card: dict) -> None:
    """清单卡：标签 + 最多 3 行短句，行间细分隔线。"""
    lines = card["lines"][:3]
    f_label, f_line = _font(46), _font(70)
    unit = int(70 * 1.5)
    total = unit * len(lines) + (130 if card.get("label") else 0)
    y = (H - total) // 2

    if card.get("label"):
        _center(d, card["label"], y, f_label, SUB_INK)
        y += 130

    for i, ln in enumerate(lines):
        _center(d, ln, y, f_line, INK)
        y += unit
        if i < len(lines) - 1:
            d.line([(W // 2 - 45, y - 30), (W // 2 + 45, y - 30)], fill=RULE, width=2)


def _draw_pair_card(d: ImageDraw.ImageDraw, card: dict) -> None:
    """对比卡：上行墨色，中间一道短线，下行灰色。"""
    f_pair = _font(76)
    unit = int(76 * 1.45)
    la = _wrap(card["a"], 12)
    lb = _wrap(card["b"], 12)
    y = (H - (unit * (len(la) + len(lb)) + 150)) // 2

    for ln in la:
        _center(d, ln, y, f_pair, INK)
        y += unit
    y += 60
    d.line([(W // 2 - 90, y), (W // 2 + 90, y)], fill=SUB_INK, width=3)
    y += 90
    for ln in lb:
        _center(d, ln, y, f_pair, SUB_INK)
        y += unit


def _draw_text_card(d: ImageDraw.ImageDraw, card: dict) -> None:
    """单句卡：主文案 + 可选小字副文案。"""
    text = card["text"].strip()
    sub = (card.get("sub") or "").strip()

    size = 108 if len(text) <= 12 else 88 if len(text) <= 20 else 70
    f_main = _font(size)
    lines = _wrap(text, per_line=max(6, W // size - 2))
    line_h = int(size * 1.5)

    f_sub = _font(40)
    sub_lines = _wrap(sub, per_line=20) if sub else []
    sub_h = int(40 * 1.7) * len(sub_lines)

    y = (H - line_h * len(lines) - (sub_h + 70 if sub_lines else 0)) // 2
    for ln in lines:
        _center(d, ln, y, f_main, INK)
        y += line_h

    if sub_lines:
        y += 70
        for ln in sub_lines:
            _center(d, ln, y, f_sub, SUB_INK)
            y += int(40 * 1.7)


def render_cards(post: dict, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(20260901)
    cards = post["cards"][:3]
    paths = []

    for i, card in enumerate(cards, start=1):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)

        # 纸感：几团极淡的污渍
        for _ in range(4):
            x, y = rng.randint(0, W), rng.randint(0, H)
            r = rng.randint(90, 220)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(244, 240, 231))

        if card.get("lines"):
            _draw_label_card(d, card)
        elif card.get("a") and card.get("b"):
            _draw_pair_card(d, card)
        else:
            _draw_text_card(d, card)

        d.text((MARGIN // 2, H - 70), f"{i}/{len(cards)}", SUB_INK, font=_font(28))

        img = img.rotate(rng.uniform(-0.6, 0.6), resample=Image.BICUBIC, fillcolor=BG)
        path = os.path.join(out_dir, f"{i:02d}.jpg")
        img.save(path, quality=85, optimize=True, progressive=True, subsampling=1)
        paths.append(path)

    return paths


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("用法: python scripts/make_tietu_images.py <post.json>")
        sys.exit(1)

    post_path = sys.argv[1]
    with open(post_path, encoding="utf-8") as f:
        post = json.load(f)

    if len(post["cards"]) > 3:
        print(f"[手册校验] 规定 1-3 张图，JSON 里写了 {len(post['cards'])} 张，只取前 3 张。")
    out_dir = os.path.join("output", "tietu", post.get("slug", "post"))
    paths = render_cards(post, out_dir)
    print(f"已生成 {len(paths)} 张图 → {out_dir}")
    for p in paths:
        print(" ", p)


if __name__ == "__main__":
    main()

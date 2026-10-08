"""连续图片故事 → 服务号图文消息素材（漫画风格）。

用法：
    python scripts/make_comic_story.py posts/story_001_solo-24h.json
    python scripts/make_comic_story.py posts/story_001_solo-24h.json --force

产出（output/story/<slug>/）：
    01.jpg … NN.jpg   正文插图，按顺序插入文章
    cover.jpg         封面（2.35:1，不带文字，微信会自己显示标题）
    文章-<slug>.md     标题 / 摘要 / 正文 / 图片顺序，手动发布时照抄

风格由 STYLE 常量控制（默认日式搞笑卡通）。角色设定固定，保证多张有系列感。
"""
import argparse
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from make_anime_images import STYLE as _UNUSED  # noqa: F401  仅为保证依赖顺序
from make_anime_images import _generate_base  # noqa: E402
from overlay_text import overlay  # noqa: E402

OUT_ROOT = os.path.join(ROOT, "output", "story")

# 搞笑卡通风格：比贴图卡的插画风更夸张、更亮，适合连续叙事
STYLE = (
    "极简手绘贴纸风（简笔画漫画），粗黑线条勾边，纯白背景，"
    "平涂上色，无阴影、无渐变、无纹理。马卡龙柔和配色（浅绿、粉红、棕色、米白）。"
    "人物是超简 Q 版：圆头，点状眼睛，小小的一字嘴，脸颊腮红，"
    "圆滚滚的小手和小短腿，造型可爱好笑。"
    "道具只用简单几何形状表示（例如被子是一个圆角矩形）。"
    "固定角色：一个棕发妈妈（珊瑚粉上衣）和一个光头小婴儿（浅绿连体衣），"
    "同一角色、同一画风贯穿全部画面。"
    "整张图只画一个场景，不要上下分格、不要左右拼图、不要边框。"
    "大量留白，主体居中偏上，画面底部留出约四分之一的空白。"
    "画面中不要出现任何文字、字幕、台词气泡、水印、logo。"
)

COVER_W, COVER_H = 900, 383       # 微信封面推荐 2.35:1


def _make_cover(story: dict, out_dir: str, force: bool = False) -> str:
    """封面：写了 cover_scene 就专门生一张横图，否则裁第一格。"""
    out_path = os.path.join(out_dir, "cover.jpg")
    scene = (story.get("cover_scene") or "").strip()
    if scene:
        base = os.path.join(out_dir, "_base_cover.png")
        print("  封面：生成横版底图…")
        _generate_base(STYLE + scene, base, force=force, ar="21:9")
        src = Image.open(base).convert("RGB")
    else:
        src = Image.open(os.path.join(out_dir, "_base_01.png")).convert("RGB")

    ratio = COVER_W / COVER_H
    if src.width / src.height > ratio:
        new_h, new_w = COVER_H, int(COVER_H * src.width / src.height)
    else:
        new_w, new_h = COVER_W, int(COVER_W * src.height / src.width)
    src = src.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - COVER_W) // 2, (new_h - COVER_H) // 2
    src.crop((left, top, left + COVER_W, top + COVER_H)).save(
        out_path, "JPEG", quality=88, optimize=True, progressive=True, subsampling=1)
    return out_path


def _write_article(story: dict, out_dir: str, image_names: list[str]) -> str:
    """生成手动发布用的文章底稿。"""
    slug = story["slug"]
    path = os.path.join(out_dir, f"文章-{slug}.md")
    lines = [
        f"# {story['title']}",
        "",
        f"**摘要（digest）**：{story.get('digest', '')}",
        f"**封面**：`cover.jpg`",
        "",
        "---",
        "",
        "## 正文（微信编辑器里按顺序插入图片）",
        "",
        story.get("intro", ""),
        "",
    ]
    for i, sc in enumerate(story["scenes"], start=1):
        lines += [f"【插图 {i}：{image_names[i - 1]}】", ""]
    lines += [story.get("outro", ""), "", "---", "", "## 发布前自检", "",
              "1. 标题、封面、正文是同一个主题，封面一眼能看懂",
              "2. 图片顺序 01→0N 没有错位，没有重复图或错字",
              "3. 正文没有重复图上的台词",
              "4. 结尾问题用户能立刻回答",
              ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def render_story(story: dict, out_dir: str, force: bool = False) -> tuple[list[str], str]:
    os.makedirs(out_dir, exist_ok=True)
    scenes = story["scenes"]
    images = []

    for i, sc in enumerate(scenes, start=1):
        base = os.path.join(out_dir, f"_base_{i:02d}.png")
        print(f"  第 {i}/{len(scenes)} 格：生成底图…")
        _generate_base(STYLE + sc["scene"], base, force=force)
        out = os.path.join(out_dir, f"{i:02d}.jpg")
        overlay(base, out, sc["line"], per_line=10, scrim=False, dark_text=True)
        images.append(out)
        print(f"  第 {i} 格：已叠台词 → {os.path.relpath(out, ROOT)}")

    cover = _make_cover(story, out_dir, force=force)
    print(f"  封面 → {os.path.relpath(cover, ROOT)}")
    return images, cover


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="连续图片故事（漫画风）")
    ap.add_argument("story", help="story JSON 路径")
    ap.add_argument("--force", action="store_true", help="忽略底图缓存重新生成")
    ap.add_argument("--out", help="输出目录")
    args = ap.parse_args()

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)

    slug = story.get("slug", "story")
    out_dir = args.out or os.path.join(OUT_ROOT, slug)
    print(f"=== {story['title']}（{len(story['scenes'])} 格）===")
    images, _ = render_story(story, out_dir, force=args.force)
    article = _write_article(story, out_dir, [os.path.basename(p) for p in images])
    print(f"\n完成 {len(images)} 格 + 封面 → {os.path.relpath(out_dir, ROOT)}")
    print(f"文章底稿 → {os.path.relpath(article, ROOT)}")


if __name__ == "__main__":
    main()

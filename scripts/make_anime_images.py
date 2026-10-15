"""动漫插画贴图卡：Agnes 生成底图 → 叠对比文字 → 3:4 成品。

用法：
    python scripts/make_anime_images.py posts/tietu_004_baby-before-after.json
    python scripts/make_anime_images.py <post.json> --force     # 忽略缓存重生成

底图由 baoyu-image-gen 技能调用 Agnes（agnes-image-2.1-flash）生成，
每张约 25 秒，单条 3 张约 75 秒。已生成的底图会缓存，重跑只重新叠字。

post JSON 里每张卡加一个 "scene" 字段描述画面（中文，越具体越好）：
    {"a": "生娃前：周末睡到自然醒", "b": "生娃后：周末醒得比闹钟早",
     "scene": "清晨六点卧室，年轻妈妈被婴儿的小手拍醒，头发乱，床头闹钟指着六点"}

红线：scene 里不要写真人明星、受版权保护的动漫角色、可识别身份的真实孩子。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from overlay_text import overlay, overlay_card  # noqa: E402

BAOYU_SCRIPT = os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "baoyu-image-gen", "scripts", "main.ts"
)
PROVIDER = "agnes"
AR = "3:4"


def _load_env() -> None:
    """把项目 .env 里的钥匙读进 os.environ（不覆盖已有环境变量）。

    baoyu-image-gen 子进程靠环境变量拿 AGNES_API_KEY；
    而 tietu_queue 里出图这一步跑在 publisher 之前，.env 还没被加载。
    """
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v

# 全系列共用的画风前缀：固定角色设定 + 固定色调，保证 3 张有系列感
STYLE = (
    "日系动漫插画风格，赛璐璐上色，柔和暖色调，线条干净，浅景深，"
    "画面留白充足，情绪细腻。"
    "固定角色设定：亚洲年轻妈妈，深棕色马尾，米白色家居服，素颜带黑眼圈；"
    "同一角色贯穿全系列，同一画风同一色调。"
    "画面中不要出现任何文字、字幕、水印、logo。"
)

# 搞笑卡通：和 output/story/ 同一套（make_comic_story 直接复用这里的字符串，改一处两边同步）
COMIC_STYLE = (
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

STYLES = {"anime": STYLE, "comic": COMIC_STYLE}


def _has_bun() -> bool:
    return shutil.which("bun") is not None


def _generate_base(prompt: str, out_png: str, force: bool = False, ar: str | None = None) -> str:
    """调 baoyu-image-gen 生成底图，已存在则直接用缓存。"""
    if os.path.exists(out_png) and not force:
        print(f"  [缓存] {os.path.basename(out_png)}")
        return out_png

    if not _has_bun():
        raise RuntimeError("找不到 bun，装一个：https://bun.sh（或 brew install oven-sh/bun/bun）")
    if not os.path.exists(BAOYU_SCRIPT):
        raise RuntimeError(f"找不到 baoyu-image-gen 脚本：{BAOYU_SCRIPT}")
    _load_env()
    if not os.environ.get("AGNES_API_KEY"):
        raise RuntimeError("缺 AGNES_API_KEY，先填进项目 .env")

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    cmd = ["bun", BAOYU_SCRIPT, "--prompt", prompt, "--image", out_png,
           "--provider", PROVIDER, "--ar", ar or AR]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0 or not os.path.exists(out_png):
        tail = (proc.stderr or proc.stdout or "")[-600:]
        raise RuntimeError(f"生成失败：{tail}")
    return out_png


def _comic_text(card: dict) -> tuple[str, str]:
    """comic 画风：白底 + 底部留白，压黑字（不画压暗渐变），主句大、副句小。"""
    if card.get("a") and card.get("b"):
        return card["a"], card["b"]
    if card.get("lines"):
        return card.get("label", ""), " · ".join(card["lines"][:3])
    return card.get("text", ""), card.get("sub", "")


def render_anime_cards(post: dict, out_dir: str, force: bool = False,
                       style: str = "anime") -> list[str]:
    preset = STYLES.get(style, STYLES["anime"])
    cards = post["cards"][:3]
    os.makedirs(out_dir, exist_ok=True)
    paths = []

    for i, card in enumerate(cards, start=1):
        scene = (card.get("scene") or "").strip()
        if not scene:
            # 没写场景就退化成用卡片文字当提示，效果一般，但不会中断流程
            scene = card.get("a") or card.get("text") or card.get("label") or ""
            print(f"  [提示] 第 {i} 张没写 scene，用文案当提示，画面可能不贴题")

        base = os.path.join(out_dir, f"_base_{i:02d}.png")
        print(f"  第 {i} 张：生成底图…")
        _generate_base(preset + scene, base, force=force)

        out = os.path.join(out_dir, f"{i:02d}.jpg")
        if style == "comic":
            main, sub = _comic_text(card)
            # 白底留白区只够一行主文案：12 字的 a/b 必须降到 84px 才不折行，
            # 折成两行会把文字块顶进插画里（黑字压深色背景看不清）
            overlay(base, out, main, sub, scrim=False, dark_text=True,
                    main_sizes=(108, 100, 92, 84), max_main_lines=1)
        else:
            overlay_card(base, out, card)
        print(f"  第 {i} 张：已叠字 → {os.path.relpath(out, ROOT)}")
        paths.append(out)

    return paths


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="动漫插画贴图卡渲染")
    ap.add_argument("post", help="post JSON 路径")
    ap.add_argument("--force", action="store_true", help="忽略底图缓存，重新生成")
    ap.add_argument("--style", choices=sorted(STYLES), default="anime",
                    help="anime=日系插画（默认）；comic=极简搞笑贴纸（白底黑字）")
    ap.add_argument("--out", help="输出目录（默认 output/tietu/<slug>/<style>）")
    args = ap.parse_args()

    with open(args.post, encoding="utf-8") as f:
        post = json.load(f)

    slug = post.get("slug", "post")
    out_dir = args.out or os.path.join(ROOT, "output", "tietu", slug, args.style)
    if len(post["cards"]) > 3:
        print(f"[手册校验] 规定 1-3 张，JSON 里写了 {len(post['cards'])} 张，只取前 3 张。")

    print(f"=== {slug}（{args.style}）===")
    paths = render_anime_cards(post, out_dir, force=args.force, style=args.style)
    print(f"完成 {len(paths)} 张 → {os.path.relpath(out_dir, ROOT)}")


if __name__ == "__main__":
    main()

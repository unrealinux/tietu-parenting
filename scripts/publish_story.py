"""把图片故事发成服务号图文草稿（走 API，只建草稿，不群发）。

前提：账号已开通素材 + 草稿箱接口权限（未认证账号会报 48001，脚本会直接说清）。

用法：
    # 只检查本地素材和将要提交的内容，不联网（先跑这个）
    python scripts/publish_story.py posts/story_001_solo-24h.json --dry-run

    # 真建草稿（会真实写入素材库 + 草稿箱）
    python scripts/publish_story.py posts/story_001_solo-24h.json --commit

    # 定时任务用：自动挑第一篇还没草稿的 story，图不全就先出图
    python scripts/publish_story.py --next --commit

产物来自 make_comic_story.py：output/story/<slug>/01.jpg…NN.jpg + cover.jpg
已建的 slug 记在 output/story/_state.json，重复跑不会重复建草稿。
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT_ROOT = os.path.join(ROOT, "output", "story")
STATE_PATH = os.path.join(OUT_ROOT, "_state.json")
AUTHOR = "育儿观察"


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    os.makedirs(OUT_ROOT, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _online_titles() -> set[str]:
    """线上草稿箱 + 已发布列表的标题，用来防止重复建草稿。"""
    from publisher import WeChatPublisher

    p = WeChatPublisher()
    titles: set[str] = set()
    for offset in (0, 20, 40):
        titles |= {(t or "").strip() for t, _ in p.list_drafts(offset, 20)}
        titles |= {(t or "").strip() for t, *_ in p.list_published(offset, 20)}
    return titles


def _pick_next(state: dict, taken: set[str]) -> tuple[str, dict] | tuple[None, None]:
    """按文件名顺序取第一篇「本地没记过、线上也没有」的 story。"""
    for path in sorted(glob.glob(os.path.join(ROOT, "posts", "story_*.json"))):
        with open(path, encoding="utf-8") as f:
            story = json.load(f)
        if story.get("slug") in state or (story.get("title") or "").strip() in taken:
            continue
        return path, story
    return None, None


def _collect(out_dir: str) -> tuple[list[str], str]:
    """按 01,02,… 顺序取正文图，并找封面。"""
    images = sorted(
        p for p in glob.glob(os.path.join(out_dir, "*.jpg"))
        if re.fullmatch(r"\d{2}\.jpg", os.path.basename(p))
    )
    cover = os.path.join(out_dir, "cover.jpg")
    return images, cover


def _build_html(story: dict, image_urls: list[str]) -> str:
    """正文 HTML：引言 + 每张图一段 + 结尾问句。微信编辑器认 <img>。"""
    parts = [f"<p>{story.get('intro', '')}</p>"]
    for url in image_urls:
        parts.append(f'<p><img src="{url}" style="width:100%"></p>')
    parts.append(f"<p>{story.get('outro', '')}</p>")
    return "\n".join(parts)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="图片故事 → 服务号图文草稿")
    ap.add_argument("story", nargs="?", help="story JSON 路径")
    ap.add_argument("--next", action="store_true",
                    help="自动挑第一篇还没草稿的 story（定时任务用）")
    ap.add_argument("--dry-run", action="store_true", help="只本地自检，不联网")
    ap.add_argument("--commit", action="store_true", help="真建草稿（写入线上账号）")
    ap.add_argument("--images", help="指定图片目录（默认 output/story/<slug>）")
    args = ap.parse_args()

    state = _load_state()
    if args.next:
        path, story = _pick_next(state, _online_titles())
        if not path:
            print("没有待建草稿的 story（全部已有草稿或已发布）。")
            return
        print(f"本轮选中的 story：{os.path.relpath(path, ROOT)}")
    else:
        if not args.story:
            ap.error("需要 story 路径，或加 --next 自动挑")
        path = args.story
        with open(path, encoding="utf-8") as f:
            story = json.load(f)

    slug = story.get("slug", "story")
    out_dir = args.images or os.path.join(OUT_ROOT, slug)
    images, cover = _collect(out_dir)

    if args.next and (len(images) < 2 or not os.path.exists(cover)):
        print("图片不全，先生成…")
        from make_comic_story import render_story

        render_story(story, out_dir)
        images, cover = _collect(out_dir)

    print(f"=== {story['title']} ===")
    print(f"目录   : {os.path.relpath(out_dir, ROOT)}")
    print(f"正文图 : {len(images)} 张 {[os.path.basename(p) for p in images]}")
    print(f"封面   : {'有' if os.path.exists(cover) else '缺失'} {os.path.basename(cover)}")

    errors = []
    if len(images) < 2:
        errors.append(f"正文图只有 {len(images)} 张，故事至少要有 2 格")
    if not os.path.exists(cover):
        errors.append("缺 cover.jpg，图文消息必须有封面")
    if len(story.get("title", "")) > 64:
        errors.append(f"标题 {len(story['title'])} 字 > 64")
    if not story.get("intro") or not story.get("outro"):
        errors.append("缺 intro 或 outro，正文会不完整")
    if errors:
        for e in errors:
            print(f"  [拒绝] {e}")
        sys.exit(1)

    print(f"标题   : {story['title']}")
    print(f"摘要   : {story.get('digest', '')}")

    if args.dry_run or not args.commit:
        html = _build_html(story, [f"<待上传：{os.path.basename(p)}>" for p in images])
        print("\n--- 正文 HTML（本地预览，图片还没上传）---")
        print(html)
        print("\n本地检查通过。真建草稿加 --commit（会写入线上账号）。")
        return

    from publisher import WeChatPublisher

    p = WeChatPublisher()
    print(f"\n目标账号 app_id: {p.app_id[:6]}***{p.app_id[-4:]}")

    ok, msg = p.probe_publish_permission()
    if not ok:
        print(f"[停止] 账号权限不足：{msg}")
        print("       素材和草稿箱接口都要认证后才开通，当前发不了。")
        sys.exit(2)

    # draft/add 不幂等：重跑一次就多一条同标题草稿，先查草稿箱
    existing = p.find_draft_by_title(story["title"])
    if existing:
        print(f"[跳过] 草稿箱已有同标题草稿 media_id={existing}（要重建先删掉那条）")
        return

    print("上传封面（永久素材）…")
    thumb_id = p._upload_media(cover, "image") if hasattr(p, "_upload_media") else None
    if not thumb_id:
        print("[失败] 封面上传失败，草稿中止")
        sys.exit(1)

    urls = []
    for i, path in enumerate(images, start=1):
        print(f"上传正文图 {i}/{len(images)} …")
        url = p._upload_article_image(path)
        if not url:
            print(f"[失败] 正文图上传失败：{path}")
            sys.exit(1)
        urls.append(url)

    media_id = p.create_draft(
        title=story["title"],
        content=_build_html(story, urls),
        author=AUTHOR,
        digest=story.get("digest", ""),
        cover_media_id=thumb_id,
    )
    if media_id:
        state[slug] = {
            "status": "drafted",
            "media_id": media_id,
            "title": story["title"],
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_state(state)
        print(f"OK 草稿已建 media_id={media_id}")
        print("去公众号后台「草稿箱」核对后手动发表。")
    else:
        print("失败：见上方日志")
        sys.exit(1)


if __name__ == "__main__":
    main()

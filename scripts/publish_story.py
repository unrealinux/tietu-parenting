"""把图片故事发成服务号图文草稿（走 API，只建草稿，不群发）。

前提：账号已开通素材 + 草稿箱接口权限（未认证账号会报 48001，脚本会直接说清）。

用法：
    # 只检查本地素材和将要提交的内容，不联网（先跑这个）
    python scripts/publish_story.py posts/story_001_solo-24h.json --dry-run

    # 真建草稿（会真实写入素材库 + 草稿箱）
    python scripts/publish_story.py posts/story_001_solo-24h.json --commit

产物来自 make_comic_story.py：output/story/<slug>/01.jpg…NN.jpg + cover.jpg
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
STATE_PATH = os.path.join(OUT_ROOT, "_queue.json")
POSTS_GLOB = os.path.join(ROOT, "posts", "story_*.json")
AUTHOR = "育儿观察"


def _collect(out_dir: str) -> tuple[list[str], str]:
    """按 01,02,… 顺序取正文图，并找封面。"""
    images = sorted(
        p for p in glob.glob(os.path.join(out_dir, "*.jpg"))
        if re.fullmatch(r"\d{2}\.jpg", os.path.basename(p))
    )
    cover = os.path.join(out_dir, "cover.jpg")
    return images, cover


def _read_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _online_titles() -> set[str]:
    """线上草稿箱 + 已发布列表的标题，用来防止重复建草稿（本地状态丢了也不重复）。"""
    from publisher import WeChatPublisher

    p = WeChatPublisher()
    titles: set[str] = set()
    for offset in (0, 20, 40):
        titles |= {(t or "").strip() for t, _ in p.list_drafts(offset, 20)}
        titles |= {(t or "").strip() for t, *_ in p.list_published(offset, 20)}
    return titles


def _next_story(state: dict, taken: set[str] | None = None) -> str | None:
    """按文件名顺序取第一篇「本地没记过、线上也没有」的 story。"""
    taken = taken or set()
    for path in sorted(glob.glob(POSTS_GLOB)):
        with open(path, encoding="utf-8") as f:
            story = json.load(f)
        slug = story.get("slug") or os.path.splitext(os.path.basename(path))[0]
        rec = state.get(slug) or {}
        if rec.get("media_id") or rec.get("skip"):
            continue
        if (story.get("title") or "").strip() in taken:
            continue
        return path
    return None


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
    ap.add_argument("--dry-run", action="store_true", help="只本地自检，不联网")
    ap.add_argument("--commit", action="store_true", help="真建草稿（写入线上账号）")
    ap.add_argument("--next", action="store_true", help="自动选第一篇未建草稿的故事")
    ap.add_argument("--force", action="store_true", help="已建草稿也重新建（会产生重复草稿）")
    ap.add_argument("--render", action="store_true", help="缺正文图/封面时先调用 make_comic_story 生成")
    ap.add_argument("--images", help="指定图片目录（默认 output/story/<slug>）")
    args = ap.parse_args()

    state = _read_state()
    if args.next:
        if args.story:
            ap.error("story 和 --next 只能二选一")
        args.story = _next_story(state, _online_titles())
        if not args.story:
            print("所有 story_*.json 都已建草稿或已标记不重发")
            return
    elif not args.story:
        ap.error("需要 story 路径或 --next")

    with open(args.story, encoding="utf-8") as f:
        story = json.load(f)

    slug = story.get("slug", "story")
    rec = state.get(slug, {})
    if args.commit and rec.get("skip") and not args.force:
        print(f"[跳过] {slug} 标记为不重发：{rec.get('skip_reason', '')}")
        return
    if args.commit and rec.get("media_id") and not args.force:
        print(f"[跳过] {slug} 已建草稿 media_id={rec['media_id']}（要重建加 --force）")
        return
    out_dir = args.images or os.path.join(OUT_ROOT, slug)
    images, cover = _collect(out_dir)
    if args.render and not args.images:
        if args.dry_run:
            print("dry-run：跳过 --render，只检查现有图片")
        elif len(images) < 2 or not os.path.exists(cover):
            from make_comic_story import render_story
            print("缺图，先生成正文图/封面…")
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

    # draft/add 不幂等：重跑一次就多一条同标题草稿，先查草稿箱（本地状态丢了也能兜住）
    if not args.force:
        existing = p.find_draft_by_title(story["title"])
        if existing:
            print(f"[跳过] 草稿箱已有同标题草稿 media_id={existing}（要重建先删掉那条）")
            return

    media_id = p.create_draft(
        title=story["title"],
        content=_build_html(story, urls),
        author=AUTHOR,
        digest=story.get("digest", ""),
        cover_media_id=thumb_id,
    )
    if media_id:
        print(f"OK 草稿已建 media_id={media_id}")
        state[slug] = {
            "status": "drafted",
            "media_id": media_id,
            "title": story["title"],
            "file": os.path.basename(args.story),
            "drafted_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_state(state)
        print("去公众号后台「草稿箱」核对后手动发表。")
    else:
        print("失败：见上方日志")
        sys.exit(1)


if __name__ == "__main__":
    main()

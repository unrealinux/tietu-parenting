"""贴图号一键：出图 → 传永久素材 → 建草稿（不群发）。

用法：
    # 出图 + 建草稿
    python scripts/publish_tietu.py posts/tietu_001_gilfoyle.json

    # 只出图，不碰线上账号（推荐先跑这个看效果）
    python scripts/publish_tietu.py posts/tietu_001_gilfoyle.json --images-only

    # 建草稿但用已有图片目录
    python scripts/publish_tietu.py posts/tietu_001_gilfoyle.json --images output/tietu/gilfoyle

红线：本脚本会真实写入当前 WECHAT_APP_ID 指向账号的素材库和草稿箱。
运行前确认该 app_id 就是你的贴图号，不是别的号。
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from make_tietu_images import render_cards  # noqa: E402


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("post", help="post JSON 路径")
    ap.add_argument("--images-only", action="store_true", help="只生成图片，不建草稿")
    ap.add_argument("--images", help="使用指定图片目录（跳过出图）")
    ap.add_argument("--no-comment", action="store_true", help="关闭留言")
    ap.add_argument("--allow-many", action="store_true",
                    help="超过 3 张图时跳过手册校验（手册规定 1-3 张）")
    args = ap.parse_args()

    post = _load(args.post)
    slug = post.get("slug", "post")
    out_dir = args.images or os.path.join("output", "tietu", slug)

    if args.images:
        image_paths = sorted(glob.glob(os.path.join(out_dir, "*.jpg")) +
                             glob.glob(os.path.join(out_dir, "*.png")))
        print(f"复用已有图片 {len(image_paths)} 张 → {out_dir}")
    else:
        image_paths = render_cards(post, out_dir)
        print(f"已生成 {len(image_paths)} 张图 → {out_dir}")

    if not image_paths:
        print("没有图片，退出")
        sys.exit(1)

    # 手册硬规则：1-3 张图，首图最清楚，后面的图必须补充新信息
    if len(image_paths) > 3:
        print(f"[手册校验] 规定 1-3 张图，当前 {len(image_paths)} 张。")
        print("  首图负责让人一眼看懂；后一张必须补充新场景/新细节/新证据/新对比/新选择。")
        print("  自检：遮住其中一张，如果整条内容完全不受影响，这张只是装饰，应该删掉。")
        if not args.allow_many:
            print("  确认要发这么多就加 --allow-many。")
            sys.exit(2)

    if args.images_only:
        print("--images-only：未建草稿。看图确认后去掉该参数再跑一次。")
        return

    from publisher import WeChatPublisher  # noqa: E402

    publisher = WeChatPublisher()
    print(f"目标账号 app_id: {publisher.app_id[:6]}***{publisher.app_id[-4:] if publisher.app_id else ''}")
    print(f"标题: {post['title']}")

    media_id = publisher.create_image_draft(
        title=post["title"],
        content=post["content"],
        image_paths=image_paths,
        need_open_comment=0 if args.no_comment else 1,
    )
    if media_id:
        print(f"OK 草稿已建：media_id={media_id}")
        print("去公众号后台「草稿箱」查看，确认无误后手动群发。")
    else:
        print("失败：看上面的错误日志。errcode 40007 = media_id 无效，41001 = 缺 access_token，"
              "40164 = IP 不在白名单，45003 = 标题或正文超长。")
        sys.exit(1)


if __name__ == "__main__":
    main()

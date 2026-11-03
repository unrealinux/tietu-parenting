"""手动记单篇数据：后台看到阅读/留言/点赞，一条命令记下来。

用法：
    python scripts/log_stats.py carry-vs-weight --read 1280 --comment 12 --like 33
    python scripts/log_stats.py --list            # 看哪些条还没记

结果写到 output/stats/articles.json（键 = slug），和 import_stats.py 写的是同一个文件。
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "output", "stats", "articles.json")


def all_posts() -> dict[str, str]:
    """slug → title"""
    out = {}
    for path in glob.glob(os.path.join(ROOT, "posts", "*.json")):
        with open(path, encoding="utf-8") as f:
            post = json.load(f)
        out[post["slug"]] = post["title"]
    return out


def load() -> dict:
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="手动记单篇数据")
    ap.add_argument("slug", nargs="?", help="post 的 slug")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--comment", type=int, default=0)
    ap.add_argument("--like", type=int, default=0)
    ap.add_argument("--list", action="store_true", help="列出还没记数据的 slug")
    args = ap.parse_args()

    posts = all_posts()
    data = load()

    if args.list:
        missing = [f"{s}  {t[:24]}" for s, t in sorted(posts.items()) if s not in data]
        print(f"已记录 {len(data)} 篇，未记录 {len(missing)} 篇：")
        for line in missing:
            print("  " + line)
        return

    if not args.slug:
        ap.error("需要 slug，或加 --list")
    if args.slug not in posts:
        raise SystemExit(f"posts 里没有 slug={args.slug}，先跑 --list 看有哪些")

    data[args.slug] = {
        "title": posts[args.slug],
        "read": args.read,
        "comment": args.comment,
        "like": args.like,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已记 {args.slug}：阅读 {args.read} · 评论 {args.comment} · 点赞 {args.like}")


if __name__ == "__main__":
    main()

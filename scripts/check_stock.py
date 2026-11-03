"""存稿库存检查：定时任务跑完后调用，低于阈值就退出码 1（计划任务会显示失败，提醒补货）。

用法：
    python scripts/check_stock.py            # 默认要求 ≥2 批（6 贴图 + 2 story）
    python scripts/check_stock.py --groups 3
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import tietu_queue as q  # noqa: E402

STORY_STATE = os.path.join(ROOT, "output", "story", "_state.json")


def pending_tietu() -> list[str]:
    state = q.load_state()
    out = []
    for path in q.discover():
        with open(path, encoding="utf-8") as f:
            slug = json.load(f)["slug"]
        if state.get(slug, {}).get("status") in ("drafted", "published", "legacy"):
            continue
        out.append(slug)
    return out


def pending_story() -> list[str]:
    state = {}
    if os.path.exists(STORY_STATE):
        with open(STORY_STATE, encoding="utf-8") as f:
            state = json.load(f)
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "posts", "story_*.json"))):
        with open(path, encoding="utf-8") as f:
            slug = json.load(f)["slug"]
        if slug not in state:
            out.append(slug)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="存稿库存检查")
    ap.add_argument("--groups", type=int, default=2, help="最少要够几批（1 批 = 3 贴图 + 1 story）")
    args = ap.parse_args()

    t, s = pending_tietu(), pending_story()
    groups = min(len(t), len(s))  # 1 批 = 1 贴图 + 1 story
    print(f"存稿：贴图 {len(t)} 篇 · story {len(s)} 篇 ≈ {groups} 批（每批 1+1，要求 ≥{args.groups} 批）")
    if groups < args.groups:
        print(f"[WARN] 存稿不够 {args.groups} 批，下一轮会空转。补 {args.groups - groups} 篇贴图 + {args.groups - groups} 篇 story。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

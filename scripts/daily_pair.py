"""每天两次的一轮：建一篇贴图草稿 + 一篇图文草稿，不发布。

默认贴图用 comic 画风；没有 Agnes 环境时加 --style text。
两篇各自独立执行：一篇失败不影响另一篇。

用法：
    python scripts/daily_pair.py --dry-run      # 只出图/自检，不建草稿
    python scripts/daily_pair.py                # 真建两条草稿
    python scripts/daily_pair.py --tietu-only
    python scripts/daily_pair.py --story-only
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
TIETU = os.path.join(HERE, "tietu_queue.py")
STORY = os.path.join(HERE, "publish_story.py")


def _run(cmd: list[str]) -> int:
    print(f"\n=== {' '.join(cmd)} ===", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="一轮：一篇贴图草稿 + 一篇图文草稿")
    ap.add_argument("--style", choices=["text", "anime", "comic"], default="comic",
                    help="贴图画风（默认 comic）")
    ap.add_argument("--dry-run", action="store_true", help="只出图/自检，不写线上")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--tietu-only", action="store_true", help="只建贴图草稿")
    group.add_argument("--story-only", action="store_true", help="只建图文草稿")
    args = ap.parse_args()

    codes = []
    if not args.story_only:
        cmd = [PY, TIETU, "--style", args.style, "--limit", "1"]
        if not args.dry_run:
            cmd.append("--commit")
        codes.append(_run(cmd))

    if not args.tietu_only:
        cmd = [PY, STORY, "--next"]
        if not args.dry_run:
            cmd.append("--render")
        cmd.append("--dry-run" if args.dry_run else "--commit")
        codes.append(_run(cmd))

    return 0 if all(code == 0 for code in codes) else 1


if __name__ == "__main__":
    sys.exit(main())

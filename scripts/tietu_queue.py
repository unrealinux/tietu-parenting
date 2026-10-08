"""贴图号草稿流水线：批量出图 → 校验 → （可选）建草稿 → 状态跟踪 → 草稿箱复核。

设计依据：`E:/Project/贴图号-SOP.md`
    - SOP 手册硬规则：1-3 张图、首图定生死、后一张必须补充新信息
    - SOP 6.发布：草稿由人复核后再手动群发，脚本永不自动群发

安全默认：
    不带 --commit 时**只出图 + 校验**，不连微信、不写线上。必须先看这一轮结果。

用法：
    # 1) 默认：扫描 posts/，出图 + 校验（不联网）
    python scripts/tietu_queue.py

    # 2) 看队列状态
    python scripts/tietu_queue.py status

    # 3) 真建草稿（会真实写入素材库 + 草稿箱，需确认 app_id）
    python scripts/tietu_queue.py --commit

    # 只跑某一个
    python scripts/tietu_queue.py --slug gilfoyle --commit

    # 4) 拉草稿箱，对照本地队列看哪些已经建好
    python scripts/tietu_queue.py list

    # 4b) 推荐：commit 前先 sync，把线上草稿回填本地，避免重复建
    python scripts/tietu_queue.py sync

    # 5) 删草稿（强操作，需二次确认）
    python scripts/tietu_queue.py prune --slug gilfoyle --yes
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from make_tietu_images import render_cards  # noqa: E402

POSTS_DIR = os.path.join(ROOT, "posts")
OUT_DIR = os.path.join(ROOT, "output", "tietu")
STATE_PATH = os.path.join(OUT_DIR, "_queue.json")
MEDIA_CACHE_PATH = os.path.join(OUT_DIR, "_media_cache.json")

TITLE_LIMIT = 64          # 微信硬限制
CONTENT_WARN = 2000       # 图片消息文案建议上限（SOP：短文案）
IMAGE_MIN, IMAGE_MAX = 1, 3   # SOP 手册硬规则


# ---------- 状态文件 ----------

def _read_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> dict:
    return _read_json(STATE_PATH)


def save_state(state: dict) -> None:
    _write_json(STATE_PATH, state)


# ---------- 校验（SOP 手册硬规则） ----------

def validate(post: dict, allow_many: bool = False) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。errors 非空则该条拒绝执行。"""
    errors, warnings = [], []

    for field in ("slug", "title", "content", "cards"):
        if not post.get(field):
            errors.append(f"缺字段 {field}")

    title = post.get("title", "")
    if len(title) > TITLE_LIMIT:
        errors.append(f"标题 {len(title)} 字 > 微信上限 {TITLE_LIMIT}")

    content = post.get("content", "")
    if len(content) > CONTENT_WARN:
        warnings.append(f"文案 {len(content)} 字，图片消息建议 ≤{CONTENT_WARN}（SOP：短文案）")

    cards = post.get("cards") or []
    if not (IMAGE_MIN <= len(cards) <= IMAGE_MAX):
        msg = f"卡片 {len(cards)} 张，SOP 硬规则为 {IMAGE_MIN}-{IMAGE_MAX} 张"
        if len(cards) > IMAGE_MAX and allow_many:
            warnings.append(msg + "（已加 --allow-many，渲染只取前 3 张）")
        elif len(cards) > IMAGE_MAX:
            errors.append(msg + "（确认要超量就加 --allow-many）")
        else:
            errors.append(msg)

    for i, c in enumerate(cards, 1):
        kind = "lines" if c.get("lines") else "pair" if (c.get("a") and c.get("b")) else "text" if c.get("text") else None
        if kind is None:
            errors.append(f"第 {i} 张卡片结构非法，需 lines / a+b / text 之一")
        if kind == "lines" and len(c["lines"]) > 3:
            warnings.append(f"第 {i} 张列了 {len(c['lines'])} 行，渲染只取前 3 行")
        if kind == "pair":
            for k in ("a", "b"):
                if len(c[k]) > 24:
                    warnings.append(f"第 {i} 张对比卡 {k} 侧 {len(c[k])} 字，会折行偏挤")

    # 递进自检提示（SOP：遮住一张内容不受影响 = 该删）
    # 只在「全是单句卡」时报——这才是最容易变成装饰图的写法
    if len(cards) > 1 and all(c.get("text") for c in cards):
        warnings.append("全是单句卡，确认每张都补充了新信息（SOP 递进自检）")

    return errors, warnings


# ---------- 主流程 ----------

def discover(slug: str | None = None) -> list[str]:
    files = sorted(glob.glob(os.path.join(POSTS_DIR, "tietu_*.json")))
    if slug:
        files = [f for f in files if slug in os.path.basename(f)]
    return files


def cmd_run(args) -> int:
    state = load_state()
    files = discover(args.slug)
    if not files:
        print("没找到 posts/tietu_*.json")
        return 1

    ok = skip = failed = 0
    publisher = None

    for path in files:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            post = json.load(f)
        slug = post.get("slug") or os.path.splitext(name)[0]

        print(f"\n=== {slug} ({name}) ===")
        errors, warnings = validate(post, allow_many=args.allow_many)
        for w in warnings:
            print(f"  [警告] {w}")
        if errors:
            for e in errors:
                print(f"  [拒绝] {e}")
            state[slug] = {"status": "invalid", "errors": errors, "file": name}
            failed += 1
            continue

        rec = state.get(slug, {})
        if args.commit and rec.get("status") == "drafted" and rec.get("media_id"):
            print(f"  [跳过] 已建草稿 media_id={rec['media_id']}（改内容请先 status 里清掉或换 slug）")
            skip += 1
            continue

        out_dir = os.path.join(OUT_DIR, slug)
        if getattr(args, "style", "text") == "anime":
            from make_anime_images import render_anime_cards
            image_paths = render_anime_cards(post, os.path.join(out_dir, "anime"),
                                             force=getattr(args, "force", False))
        else:
            image_paths = render_cards(post, out_dir)
        print(f"  已出图 {len(image_paths)} 张 → {os.path.relpath(out_dir, ROOT)}")

        rec.update({
            "status": "rendered",
            "file": name,
            "title": post["title"],
            "images": [os.path.relpath(p, ROOT) for p in image_paths],
            "rendered_at": datetime.now().isoformat(timespec="seconds"),
        })
        state[slug] = rec

        if not args.commit:
            ok += 1
            continue

        if publisher is None:
            from publisher import WeChatPublisher
            publisher = WeChatPublisher()
            print(f"  目标账号 app_id: {publisher.app_id[:6]}***{publisher.app_id[-4:]}")

        media_id = publisher.create_image_draft(
            title=post["title"],
            content=post["content"],
            image_paths=image_paths,
            need_open_comment=0 if args.no_comment else 1,
        )
        if media_id:
            rec["status"] = "drafted"
            rec["media_id"] = media_id
            rec["drafted_at"] = datetime.now().isoformat(timespec="seconds")
            print(f"  [OK] 草稿已建 media_id={media_id}")
            ok += 1
        else:
            rec["status"] = "draft_failed"
            print("  [失败] 见上方错误日志（40007 media_id 无效 / 40164 IP 白名单 / 45003 超长）")
            failed += 1
        save_state(state)

    save_state(state)
    print(f"\n本轮：成功 {ok} · 跳过 {skip} · 失败 {failed}")
    if not args.commit:
        print("未建草稿。确认图片无误后加 --commit 再跑一次。")
    return 0 if failed == 0 else 1


def cmd_sync(args) -> int:
    """按标题把线上草稿 media_id 回填到本地队列，避免重复建草稿。"""
    from publisher import WeChatPublisher
    p = WeChatPublisher()

    remote: list[tuple[str, str]] = []
    offset = 0
    while offset < 200:
        batch = p.list_drafts(offset=offset, count=20)
        if not batch:
            break
        remote.extend(batch)
        offset += 20

    by_title = {t.strip(): m for t, m in remote}
    state = load_state()
    matched = 0
    for slug, rec in state.items():
        if rec.get("media_id"):
            continue
        title = (rec.get("title") or "").strip()
        if title in by_title:
            rec["status"] = "drafted"
            rec["media_id"] = by_title[title]
            rec["synced_from"] = "draftbox"
            print(f"  回填 {slug} ← {rec['media_id'][:24]}")
            matched += 1
    save_state(state)

    print(f"线上草稿 {len(remote)} 条，按标题回填 {matched} 条")
    local_titles = {(r.get("title") or "").strip() for r in state.values()}
    unknown = [t for t, _ in remote if t not in local_titles]
    if unknown:
        print("线上有、本地队列没有的草稿（可能是其它流程建的）：")
        for t in unknown:
            print(f"  - {t}")
    return 0


def cmd_status(args) -> int:
    state = load_state()
    if not state:
        print("队列为空，先跑一次 python scripts/tietu_queue.py")
        return 0
    print(f"{'slug':<22}{'状态':<14}{'草稿 media_id':<30}标题")
    for slug, rec in sorted(state.items()):
        mid = rec.get("media_id", "")
        print(f"{slug:<22}{rec.get('status',''):<14}{mid[:28]:<30}{(rec.get('title') or '')[:30]}")
    n = {s: sum(1 for r in state.values() if r.get("status") == s) for s in {r.get("status") for r in state.values()}}
    print("\n汇总：" + " · ".join(f"{k} {v}" for k, v in sorted(n.items()) if k))
    return 0


def cmd_perm(args) -> int:
    """只读探测发布权限，不发任何东西。"""
    from publisher import WeChatPublisher
    p = WeChatPublisher()
    if not p.app_id or "填" in p.app_id:
        print("未配置 WECHAT_APP_ID，先把新服务号信息填进 .env")
        return 1
    print(f"账号 app_id: {p.app_id[:6]}***{p.app_id[-4:]}")
    ok, msg = p.probe_publish_permission()
    print(("[OK] " if ok else "[无权限] ") + msg)
    if ok:
        items = p.list_published(count=5)
        if items:
            print("最近已发布：")
            for title, aid, ts in items[:5]:
                print(f"  {title[:36]:<38}{aid}")
    return 0 if ok else 1


def cmd_publish(args) -> int:
    """发布草稿（走「发布」接口，不占群发次数、不推通知）。

    不带 --yes 只列出会发什么，不连微信。
    """
    state = load_state()
    targets = {s: r for s, r in state.items() if r.get("media_id")}
    if args.slug:
        targets = {s: r for s, r in targets.items() if args.slug in s}
    if not targets:
        print("没有可发布的条目（先跑 run --commit 建草稿）")
        return 1

    for slug, rec in targets.items():
        print(f"  {slug:<22}{rec.get('title', '')[:34]:<36}media_id={rec['media_id'][:20]}")

    if not args.yes:
        print(f"\n以上 {len(targets)} 条将被发布（不可撤销，会进公众号主页 + 推荐流）。")
        print("确认后加 --yes 再跑。")
        return 1

    from publisher import WeChatPublisher
    p = WeChatPublisher()
    print(f"\n目标账号 app_id: {p.app_id[:6]}***{p.app_id[-4:]}")
    ok = failed = 0
    for slug, rec in targets.items():
        publish_id = p.publish_draft(rec["media_id"])
        if publish_id:
            rec["status"] = "published"
            rec["publish_id"] = publish_id
            rec["published_at"] = datetime.now().isoformat(timespec="seconds")
            print(f"  [OK] {slug} 已发布 publish_id={publish_id}")
            ok += 1
        else:
            rec["status"] = "publish_failed"
            print(f"  [失败] {slug} 见上方错误日志（48001 无权限 / 40164 IP 白名单）")
            failed += 1
        save_state(state)
    print(f"\n本轮：发布 {ok} · 失败 {failed}")
    if ok:
        print("发布是异步的，用 status 看本地记录，或 list --published 看线上。")
    return 0 if failed == 0 else 1


def cmd_mark(args) -> int:
    """手动记录状态（微信后台定时发布、手动发布后回填本地用）。

    publish / perm 走 API，这个命令不用凭证，纯记本地账。
    """
    if not args.slug:
        print("mark 必须指定 --slug")
        return 1
    state = load_state()
    hits = [s for s in state if args.slug in s]
    if not hits:
        print(f"队列里没有含「{args.slug}」的条目，先跑 status 看有哪些")
        return 1

    when = args.at or datetime.now().strftime("%Y-%m-%d %H:%M")
    for slug in hits:
        rec = state[slug]
        rec["status"] = args.status
        rec["marked_at"] = when
        if args.note:
            rec["note"] = args.note
        print(f"  {slug:<22}{args.status:<12}{when}")
    save_state(state)
    print("\n已记录（本地账，未动线上）")
    return 0


def cmd_list(args) -> int:
    from publisher import WeChatPublisher
    p = WeChatPublisher()
    if getattr(args, "published", False):
        items = p.list_published(offset=0, count=args.count)
        if not items:
            print("拉不到已发布列表（无权限或没发过）")
            return 1
        state = load_state()
        print(f"线上已发布 {len(items)} 条：")
        for title, aid, ts in items:
            when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"
            owner = next((s for s, r in state.items() if r.get("publish_id") == aid), "")
            mark = f"  ← 本地 {owner}" if owner else ""
            print(f"  {when}  {title[:34]:<36}{aid}{mark}")
        return 0

    drafts = p.list_drafts(offset=0, count=args.count)
    state = load_state()
    remote_ids = {mid for _, mid in drafts}
    print(f"线上草稿箱 {len(drafts)} 条：")
    for title, mid in drafts:
        owner = next((s for s, r in state.items() if r.get("media_id") == mid), "")
        mark = f"  ← 本地 {owner}" if owner else ""
        print(f"  {title[:40]:<42}{mid[:26]}{mark}")
    local_only = [s for s, r in state.items()
                  if r.get("status") == "drafted" and r.get("media_id") not in remote_ids]
    if local_only:
        print(f"\n本地记录为 drafted 但线上已不存在（可能已手动发布或删除）：{', '.join(local_only)}")
    return 0


def cmd_prune(args) -> int:
    if not args.slug:
        print("prune 必须指定 --slug")
        return 1
    state = load_state()
    rec = state.get(args.slug)
    if not rec or not rec.get("media_id"):
        print(f"{args.slug} 没有记录 media_id，无法删除")
        return 1
    mid = rec["media_id"]
    print(f"将删除线上草稿：{rec.get('title')}\n  media_id={mid}")
    if not args.yes:
        print("确认后加 --yes 再跑（此操作不可撤销）")
        return 1
    from publisher import WeChatPublisher
    ok = WeChatPublisher().delete_draft(mid)
    if ok:
        rec["status"] = "pruned"
        rec["pruned_at"] = datetime.now().isoformat(timespec="seconds")
        rec.pop("media_id", None)
        save_state(state)
        print("已删除")
    else:
        print("删除失败，见日志")
    return 0 if ok else 1


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="贴图号草稿流水线")
    ap.add_argument("action", nargs="?", default="run",
                    choices=["run", "status", "list", "prune", "sync", "publish", "perm", "mark"])
    ap.add_argument("--status", default="scheduled",
                    help="mark 时写什么状态（scheduled / published / deleted …）")
    ap.add_argument("--at", help="mark 的时间，如 2026-10-02 08:00（默认现在）")
    ap.add_argument("--note", help="mark 的备注")
    ap.add_argument("--slug", help="只处理 slug 含该字符串的条目")
    ap.add_argument("--commit", action="store_true", help="真的建草稿（默认只出图+校验）")
    ap.add_argument("--no-comment", action="store_true", help="关闭留言")
    ap.add_argument("--allow-many", action="store_true",
                    help="允许超过 3 张卡（跳过 SOP 手册校验，渲染仍只取前 3 张）")
    ap.add_argument("--style", choices=["text", "anime"], default="text",
                    help="text=纯文字卡（默认）；anime=Agnes 动漫插画底图+叠字")
    ap.add_argument("--force", action="store_true", help="anime 风格下忽略底图缓存重生成")
    ap.add_argument("--count", type=int, default=20, help="list 拉取条数")
    ap.add_argument("--published", action="store_true", help="list 时改看「已发布」而不是草稿箱")
    ap.add_argument("--yes", action="store_true", help="prune / publish 二次确认")
    args = ap.parse_args()

    handlers = {"run": cmd_run, "status": cmd_status, "list": cmd_list,
                "prune": cmd_prune, "sync": cmd_sync,
                "publish": cmd_publish, "perm": cmd_perm, "mark": cmd_mark}
    sys.exit(handlers[args.action](args))


if __name__ == "__main__":
    main()

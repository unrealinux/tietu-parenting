"""补素材：用 Agnes 文本模型生成新选题 JSON，落到 posts/，给 daily_pair 消费。

为什么要有它：posts/ 里的 JSON 是手写的，跑完就没料。cron 里放在 daily_pair 之前，
池子见底时自动补一条图文 + 一条贴图。

用法：
    python scripts/gen_topics.py --dry-run    # 只生成并打印，不写文件
    python scripts/gen_topics.py              # 池子 < 4 条时才生成，写 posts/
    python scripts/gen_topics.py --force      # 不管池子剩多少，都补一条

失败即退出码非 0（cron 日志里能看见）。模型胡写的字段校验不过就整条丢掉，绝不写半成品。
"""
import argparse
import glob
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from make_anime_images import _load_env  # noqa: E402

POSTS_DIR = os.path.join(ROOT, "posts")
TIETU_STATE = os.path.join(ROOT, "output", "tietu", "_queue.json")
STORY_STATE = os.path.join(ROOT, "output", "story", "_queue.json")


TIETU_RULES = """硬规则：
1. 1-3 张图，2-3 张最佳；首图一眼看懂主题。
2. 组图必须递进：后一张补充新场景/新细节/新对比，遮住任何一张内容就不完整。
3. 正文（content）补图上没说的细节，不重复图上的字；结尾一个用户能立刻回答的问题。
4. 选题能写成一句话：具体人群 + 高频场景 + 可重复素材 + 明确互动。
5. 红线：不搬原图原文，不写恐吓、擦边、夸大标题；不出现真人明星、版权角色、可识别身份的真实孩子。
6. 讲一个妈妈的真实一天，允许自嘲和吐槽，不煽情，不说教，不用"宝妈""姐妹们"这类套话。
7. scene 只用中文，不夹英文单词，不写文字/水印/logo。
8. 不写孩子受伤、生病、吃地上的食物这类情节，也不把危险动作当笑点。"""

STORY_RULES = """硬规则：
1. 一条故事 4-6 格，按时间或事件顺序推进，最后一格情绪落地（不一定搞笑）。
2. 每格 line 两行以内，先时间/动作再一句反差；scene 写中文画面描述，越具体越好。
3. intro 交代背景不剧透结尾，outro 一句收住 + 一个用户能回答的问题。
4. 标题 20 字以内，摘要 digest 一句话，具体到细节，不要"泪目""破防"这类词。
5. 红线同贴图：不搬他人经历，不写恐吓、擦边、夸大；不出现真人明星、版权角色、可识别身份的孩子。
6. scene 只用中文，不夹英文单词，不写文字/水印/logo。
7. 不写孩子受伤、生病、吃地上的食物这类情节，也不把危险动作当笑点。"""

TIETU_SCHEMA = """只输出 JSON，不要 markdown 代码块、不要解释：
{
  "slug": "英文小写带连字符，能看懂主题",
  "title": "20 字以内",
  "content": "80-150 字，结尾一个问题",
  "cards": [
    {"a": "主句 12 字内", "b": "副句 16 字内", "scene": "中文画面描述"},
    {"a": "…", "b": "…", "scene": "…"},
    {"text": "总结句", "sub": "副句", "scene": "…"}
  ]
}"""

STORY_SCHEMA = """只输出 JSON，不要 markdown 代码块、不要解释：
{
  "slug": "英文小写带连字符",
  "title": "20 字以内",
  "digest": "一句话摘要",
  "intro": "2-3 句背景",
  "outro": "一句收尾 + 一个问题",
  "scenes": [{"line": "时间\\n一句话", "scene": "中文画面描述"}],
  "cover_scene": "横向构图的一句话画面描述"
}"""


DEFAULT_MODEL = "deepseek-flash"   # 实测比 agnes-2.5-flash 写得好，约 10-13 秒/条
PI_AUTH = os.path.join(os.path.expanduser("~"), ".pi", "agent", "auth.json")


def _deepseek_key() -> str:
    """DEEPSEEK_API_KEY 优先，没有就用本机 pi 已登录的凭证（不复制密钥进 .env）。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    try:
        with open(PI_AUTH, encoding="utf-8") as f:
            return json.load(f).get("deepseek", {}).get("key", "")
    except (OSError, ValueError):
        return ""


def _chat(system: str, user: str) -> str:
    # TEXT_* 环境变量可整体换供应方；不设时 deepseek 走官方端点，其余走 Agnes
    model = os.environ.get("TEXT_MODEL") or os.environ.get("AGNES_TEXT_MODEL") or DEFAULT_MODEL
    if model.startswith("deepseek"):
        base = os.environ.get("TEXT_BASE_URL") or "https://api.deepseek.com/v1"
        key = os.environ.get("TEXT_API_KEY") or _deepseek_key()
    else:
        base = (os.environ.get("TEXT_BASE_URL") or
                os.environ.get("AGNES_API_URL", "").split("/images/")[0] or
                "https://api.agnes-ai.cn/v1")
        key = os.environ.get("TEXT_API_KEY") or os.environ.get("AGNES_API_KEY", "")
    if not key:
        raise RuntimeError(f"缺 {model} 的 key：TEXT_API_KEY / DEEPSEEK_API_KEY / AGNES_API_KEY 都没拿到")
    body = json.dumps({
        "model": model,
        "temperature": 0.9,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("没有 JSON")
    return json.loads(text[start:end + 1])


def _slug_ok(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", slug or ""))


def _check_tietu(d: dict) -> list[str]:
    errs = []
    if not _slug_ok(d.get("slug", "")):
        errs.append("slug 不是英文连字符格式")
    if not 4 <= len(d.get("title", "")) <= 20:
        errs.append(f"title 长度 {len(d.get('title', ''))} 不在 4-20")
    if not 40 <= len(d.get("content", "")) <= 300:
        errs.append("content 长度不在 40-300")
    cards = d.get("cards") or []
    if not 2 <= len(cards) <= 3:
        errs.append(f"cards 有 {len(cards)} 张，要 2-3")
    for i, c in enumerate(cards, 1):
        if not c.get("scene"):
            errs.append(f"第 {i} 张缺 scene")
        if not (c.get("text") or c.get("a")):
            errs.append(f"第 {i} 张既没 text 也没 a")
    return errs


def _check_story(d: dict) -> list[str]:
    errs = []
    if not _slug_ok(d.get("slug", "")):
        errs.append("slug 不是英文连字符格式")
    if not 4 <= len(d.get("title", "")) <= 20:
        errs.append(f"title 长度 {len(d.get('title', ''))} 不在 4-20")
    for k in ("digest", "intro", "outro", "cover_scene"):
        if not d.get(k):
            errs.append(f"缺 {k}")
    scenes = d.get("scenes") or []
    if not 4 <= len(scenes) <= 6:
        errs.append(f"scenes 有 {len(scenes)} 格，要 4-6")
    for i, s in enumerate(scenes, 1):
        if not s.get("line") or not s.get("scene"):
            errs.append(f"第 {i} 格缺 line 或 scene")
    return errs


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _posts(kind: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(POSTS_DIR, f"{kind}_*.json"))):
        with open(p, encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def _unused(kind: str) -> int:
    state = _load(TIETU_STATE if kind == "tietu" else STORY_STATE)
    return sum(1 for p in _posts(kind) if p.get("slug") not in state)


def _next_path(kind: str, slug: str) -> str:
    nums = [int(m.group(1)) for p in glob.glob(os.path.join(POSTS_DIR, f"{kind}_*.json"))
            if (m := re.match(rf"{kind}_(\d+)_", os.path.basename(p)))]
    return os.path.join(POSTS_DIR, f"{kind}_{max(nums, default=0) + 1:03d}_{slug}.json")


def _generate(kind: str, taken: set[str], attempts: int = 2) -> dict:
    samples = _posts(kind)[-2:]
    known = [f"{p['slug']}｜{p['title']}" for p in _posts(kind)] + sorted(taken)
    rules, schema = (TIETU_RULES, TIETU_SCHEMA) if kind == "tietu" else (STORY_RULES, STORY_SCHEMA)
    system = (
        "你在给一个育儿公众号写素材，作者是一个每天带娃的妈妈，写自己的真实日常："
        "具体、克制、有点自嘲，不说教不煽情。\n\n" + rules
    )
    user = (
        "这是已经写过的选题，不要重复它们的角度和句式：\n" + "\n".join(known) +
        "\n\n风格样本（照这个口气写，不要照抄内容）：\n" +
        "\n\n".join(json.dumps(s, ensure_ascii=False, indent=2) for s in samples) +
        "\n\n现在写一条全新的。\n\n" + schema
    )
    last = ""
    for _ in range(attempts):
        try:
            d = _parse(_chat(system, user))
        except Exception as e:  # 网络/JSON 解析失败都重试一次
            last = f"调用失败：{e}"
            continue
        if d.get("slug") in taken:
            last = f"slug {d.get('slug')} 撞车"
            continue
        errs = (_check_tietu if kind == "tietu" else _check_story)(d)
        if errs:
            last = "；".join(errs)
            continue
        return d
    raise RuntimeError(f"{kind} 生成失败：{last}")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成新选题，补 posts/ 素材池")
    ap.add_argument("--kind", choices=["tietu", "story", "both"], default="both")
    ap.add_argument("--min-pool", type=int, default=4, help="未用素材少于这个数才生成")
    ap.add_argument("--force", action="store_true", help="不管池子剩多少都生成")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    _load_env()

    kinds = ["tietu", "story"] if args.kind == "both" else [args.kind]
    taken = {p["slug"] for k in ("tietu", "story") for p in _posts(k)}
    bad = 0
    for kind in kinds:
        left = _unused(kind)
        if left >= args.min_pool and not args.force:
            print(f"[跳过] {kind} 池子还剩 {left} 条（>= {args.min_pool}），不用生成")
            continue
        try:
            d = _generate(kind, taken)
        except Exception as e:
            print(f"[失败] {e}")
            bad += 1
            continue
        taken.add(d["slug"])
        path = _next_path(kind, d["slug"])
        print(f"[新素材] {kind} 池子剩 {left} 条 → {os.path.basename(path)}")
        print(json.dumps(d, ensure_ascii=False, indent=2))
        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            print(f"已写入 {os.path.relpath(path, ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

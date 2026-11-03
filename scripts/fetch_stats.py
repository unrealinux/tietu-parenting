"""拉公众号数据：粉丝增减（getusersummary）并与本地发布记录对齐。

说明：微信的图文单篇数据接口（getarticlesummary / getarticletotal）已下线（47009），
目前 API 只能拿到账号级数据。单篇阅读/评论需要后台「内容分析」页面导出。

用法：
    python scripts/fetch_stats.py            # 最近 7 天
    python scripts/fetch_stats.py --days 3
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import requests  # noqa: E402

from publisher import WeChatPublisher  # noqa: E402

OUT = os.path.join(ROOT, "output", "stats")
PATH = os.path.join(OUT, "user_summary.json")


def fetch(days: int) -> list[dict]:
    p = WeChatPublisher()
    token = p.get_access_token()
    if not token:
        raise SystemExit("拿不到 access_token（网络 / IP 白名单）")
    end = date.today() - timedelta(days=1)          # 当天数据未结算
    begin = end - timedelta(days=days - 1)
    r = requests.post(
        "https://api.weixin.qq.com/datacube/getusersummary",
        params={"access_token": token},
        json={"begin_date": str(begin), "end_date": str(end)},
        timeout=30,
        proxies=p.proxies if p.use_proxy else {},
    )
    r.encoding = "utf-8"
    data = r.json()
    if data.get("errcode"):
        raise SystemExit(f"接口报错：{data.get('errcode')} {data.get('errmsg')}")
    return data.get("list") or []


def published_by_day() -> dict[str, list[str]]:
    """本地发布记录按日期分组（贴图 + story）。"""
    out: dict[str, list[str]] = {}
    for path, key in ((os.path.join(ROOT, "output", "tietu", "_queue.json"), "tietu"),
                      (os.path.join(ROOT, "output", "story", "_state.json"), "story")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        for rec in state.values():
            day = (rec.get("published_at") or "").split(" ")[0]
            if day:
                out.setdefault(day, []).append(f"{rec.get('title', '')[:16]}({key})")
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="拉粉丝增减数据")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    rows = fetch(args.days)
    os.makedirs(OUT, exist_ok=True)
    old = {}
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            old = json.load(f)
    for row in rows:
        old[row["ref_date"]] = row
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(old.items())), f, ensure_ascii=False, indent=2)

    pub = published_by_day()
    print(f"{'日期':<12}{'新增':>5}{'取关':>5}   当天发布")
    for row in rows:
        day = row["ref_date"]
        print(f"{day:<12}{row.get('new_user', 0):>5}{row.get('cancel_user', 0):>5}   {'、'.join(pub.get(day, [])) or '-'}")
    print(f"\n已合并写入 {os.path.relpath(PATH, ROOT)}")


if __name__ == "__main__":
    main()

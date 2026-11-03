"""读公众号后台「内容分析」导出的 Excel/CSV，把单篇阅读/评论回填到本地。

背景：微信把单篇数据 API 下线了（47009），只能从后台导表。

用法：
    python scripts/import_stats.py 导出文件.xlsx
    python scripts/import_stats.py 导出文件.csv --sheet 0

字段靠表头关键词识别（标题/阅读/评论/点赞/分享/发表时间），不依赖固定列顺序。
结果写到 output/stats/articles.json，并按阅读量排序打印。
"""
import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "output", "stats", "articles.json")

# 表头关键词 → 内部字段，按顺序匹配第一个命中的列
FIELDS = [
    ("title", ("标题", "内容标题")),
    ("date", ("发表时间", "发布时间", "时间")),
    ("read", ("阅读人数", "阅读次数", "阅读量")),
    ("comment", ("留言", "评论")),
    ("like", ("点赞", "赞")),
    ("share", ("分享", "转发")),
    ("fav", ("在看", "收藏")),
]


def _rows_xlsx(path: str, sheet: int) -> list[list]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[sheet]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _rows_csv(path: str) -> list[list]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.reader(f)]


def _map_columns(header: list) -> dict:
    idx = {}
    cells = [str(c or "").strip() for c in header]
    for field, keys in FIELDS:
        for i, cell in enumerate(cells):
            if any(k in cell for k in keys):
                idx[field] = i
                break
    return idx


def _num(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="导入后台统计导出表")
    ap.add_argument("path", help="xlsx 或 csv")
    ap.add_argument("--sheet", type=int, default=0, help="xlsx 的工作表序号")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        raise SystemExit(f"找不到文件：{args.path}")
    rows = _rows_xlsx(args.path, args.sheet) if args.path.lower().endswith((".xlsx", ".xlsm")) else _rows_csv(args.path)
    if not rows:
        raise SystemExit("表是空的")

    header_i = next((i for i, r in enumerate(rows) if any("标题" in str(c or "") for c in r)), 0)
    cols = _map_columns(rows[header_i])
    if "title" not in cols or "read" not in cols:
        raise SystemExit(f"表头里找不到标题/阅读列，识别到：{cols}；表头原文：{rows[header_i]}")

    records = []
    for r in rows[header_i + 1:]:
        title = str(r[cols["title"]] or "").strip()
        if not title or title == "None":
            continue
        rec = {"title": title}
        for field in ("read", "comment", "like", "share", "fav"):
            if field in cols:
                rec[field] = _num(r[cols[field]])
        if "date" in cols:
            rec["date"] = str(r[cols["date"]] or "")[:19]
        records.append(rec)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    for rec in records:
        data[rec["title"]] = rec
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"导入 {len(records)} 条 → {os.path.relpath(OUT, ROOT)}\n")
    top = sorted(records, key=lambda r: r.get("read", 0), reverse=True)
    print(f"{'阅读':>6}{'评论':>6}  标题")
    for rec in top:
        print(f"{rec.get('read', 0):>6}{rec.get('comment', 0):>6}  {rec['title'][:30]}")


if __name__ == "__main__":
    main()

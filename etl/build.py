"""縦持ちCSVと market.json を出力する (P1)。

    python -m etl.build

data/raw -> parse -> normalize ->
    data/processed/{items,origins,others}.csv
    data/processed/merge_candidates.csv, report.md
    web/public/data/market.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from .common import CATEGORY_ORDER, PROCESSED_DIR, RAW_DIR, WEB_DATA_DIR
from .normalize import (
    Aliases, load_aliases, merge_candidates, normalize_rows, write_merge_candidates,
)
from .parse import Issue, OtherRow, ParseResult, Row, list_months, parse_all

ROW_FIELDS = [
    "year_month", "division", "category", "name", "key", "rank", "qty", "qty_unit",
    "qty_ratio", "amt", "amt_ratio", "related", "source_url",
]
OTHER_FIELDS = ["year_month", "category", "kind", "qty", "amt", "qty_ratio", "amt_ratio"]

CATEGORY_RANK = {c: i for i, (c, _) in enumerate(CATEGORY_ORDER)}
CATEGORY_DIVISION = dict(CATEGORY_ORDER)


def _sort_key(r) -> tuple:
    return (r.year_month, CATEGORY_RANK.get(r.category, 99), getattr(r, "rank", 0))


def write_rows(rows: list[Row], path: Path) -> None:
    # csv.writer に素の値を渡し、引用符のエスケープは任せる（手動で " を付けない）
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ROW_FIELDS)
        for r in sorted(rows, key=_sort_key):
            w.writerow([
                r.year_month, r.division, r.category, r.name, r.key, r.rank, r.qty,
                r.qty_unit, r.qty_ratio, r.amt, r.amt_ratio,
                json.dumps(r.related, ensure_ascii=False), r.source_url,
            ])


def write_others(others: list[OtherRow], path: Path) -> None:
    def cell(v):
        return "" if v is None else v

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(OTHER_FIELDS)
        for o in sorted(others, key=lambda o: (o.year_month, CATEGORY_RANK.get(o.category, 99), o.kind)):
            w.writerow([o.year_month, o.category, o.kind, cell(o.qty), cell(o.amt),
                        cell(o.qty_ratio), cell(o.amt_ratio)])


def build_market_json(
    rows: list[Row], issues: list[Issue], months: list[str], generated: str,
) -> dict:
    idx = {ym: i for i, ym in enumerate(months)}
    n = len(months)

    categories = []
    for cat, div in CATEGORY_ORDER:
        crow = [r for r in rows if r.category == cat]
        if not crow:
            continue
        units = {r.qty_unit for r in crow}
        if len(units) != 1:
            raise ValueError(f"{cat}: 数量の単位が混在 {units}")
        categories.append({
            "name": cat, "division": div, "qty_unit": units.pop(),
            "first_month": min(r.year_month for r in crow),
        })

    # 取り込めなかった（欠測の）月: 部門・種別単位で、その部門の全大品目が対象
    missing: dict[str, dict[str, list[str]]] = {"items": {}, "origins": {}}
    for i in issues:
        if not i.excluded:
            continue
        kind = "items" if i.file.endswith("11") else "origins"
        div = i.file[0]
        for cat, d in CATEGORY_ORDER:
            if d == div:
                ms = missing[kind].setdefault(cat, [])
                if i.year_month not in ms:
                    ms.append(i.year_month)
    for kind in missing:
        for ms in missing[kind].values():
            ms.sort()

    def collect(kind: str, related_key: str) -> dict:
        per: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            if r.kind != kind:
                continue
            e = per[r.category].setdefault(
                r.key,
                {"name": r.name, "qty": [None] * n, "amt": [None] * n, related_key: [None] * n},
            )
            i = idx[r.year_month]
            e["qty"][i], e["amt"][i], e[related_key][i] = r.qty, r.amt, r.related
        out: dict[str, dict] = {}
        for cat, _ in CATEGORY_ORDER:
            if cat not in per:
                continue
            ents = sorted(per[cat].values(), key=lambda e: -sum(v for v in e["qty"] if v is not None))
            out[cat] = {}
            for e in ents:
                if e["name"] in out[cat]:
                    raise ValueError(f"{cat}: 表示名が重複 {e['name']!r}")
                out[cat][e["name"]] = {k: v for k, v in e.items() if k != "name"}
        return out

    return {
        "meta": {
            "generated": generated, "months": months, "categories": categories,
            "missing": missing,
        },
        "items": collect("items", "origins"),
        "origins": collect("origins", "items"),
    }


def format_report(res: ParseResult, aliases: Aliases, cands: list[dict], months: list[str]) -> str:
    L = ["# 整形レポート", ""]
    L.append(f"- 月数: {len(months)}（{months[0]} 〜 {months[-1]}）")
    L.append(f"- 縦持ち行数: {len(res.rows)}（その他行: {len(res.others)}）")
    L.append(f"- 文字コード: { {e: sum(1 for v in res.encodings.values() if v == e) for e in set(res.encodings.values())} }")
    L.append(f"- 統合候補: {len(cands)} 件（うち同月に共存しない: {sum(c['never_together'] for c in cands)} 件）")
    L += ["", f"## 元データの例外（{len(res.issues)} 件）", ""]
    for i in sorted(res.issues, key=lambda i: (i.code, i.year_month, i.file)):
        mark = "欠測" if i.excluded else "吸収"
        L.append(f"- [{i.code}/{mark}] {i.year_month} {i.file}: {i.message}")
    return "\n".join(L) + "\n"


def build(
    raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR,
    web_data_dir: Path = WEB_DATA_DIR, generated: str | None = None,
) -> dict:
    aliases = load_aliases()
    res = parse_all(aliases.category, raw_dir)
    rows = normalize_rows(res.rows, aliases)
    months = list_months(raw_dir)

    processed_dir.mkdir(parents=True, exist_ok=True)
    web_data_dir.mkdir(parents=True, exist_ok=True)
    write_rows([r for r in rows if r.kind == "items"], processed_dir / "items.csv")
    write_rows([r for r in rows if r.kind == "origins"], processed_dir / "origins.csv")
    write_others(res.others, processed_dir / "others.csv")

    cands = merge_candidates(rows)
    write_merge_candidates(cands, processed_dir / "merge_candidates.csv")
    (processed_dir / "report.md").write_text(format_report(res, aliases, cands, months), encoding="utf-8")

    market = build_market_json(rows, res.issues, months, generated or date.today().isoformat())
    (web_data_dir / "market.json").write_text(
        json.dumps(market, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"rows": len(rows), "others": len(res.others), "months": len(months),
            "issues": len(res.issues), "candidates": len(cands)}


def main() -> int:
    s = build()
    print(", ".join(f"{k}={v}" for k, v in s.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""data/raw のCSV -> 縦持ち (P1)。

元データの不具合・揺れは例外にせず、可能な限り吸収して ``Issue`` として記録する。
想定外（列名の基本名が違う、年月が合わない、数値が読めない等）は ``ParseError``。
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import (
    DEFAULT_UNITS, EXPECTED_CATEGORIES, EXPECTED_HEADERS, KIND_LABEL, MAX_RANK,
    RAW_DIR, decode_csv, norm_text,
)

SPLIT_RE = re.compile(r"[、・]")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class ParseError(Exception):
    """想定外の構造。月次ジョブを失敗させる。"""


@dataclass
class Row:
    year_month: str
    division: str
    kind: str  # "items" | "origins"
    category: str
    name: str
    key: str
    rank: int
    qty: int | float
    qty_unit: str
    qty_ratio: float
    amt: int | float
    amt_ratio: float
    related: list[str]
    source_url: str = ""


@dataclass
class OtherRow:
    year_month: str
    division: str
    category: str
    kind: str
    qty: int | float | None
    amt: int | float | None
    qty_ratio: float | None
    amt_ratio: float | None


@dataclass
class Issue:
    code: str
    year_month: str
    file: str  # 例: "R11"
    message: str
    excluded: bool = False  # True: そのデータは取り込まれていない（欠測）
    category: str = ""


@dataclass
class ParseResult:
    rows: list[Row] = field(default_factory=list)
    others: list[OtherRow] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    encodings: dict[str, str] = field(default_factory=dict)  # "2023-01/T11" -> encoding


def base_name(h: str) -> str:
    """列名から末尾の［…］注記を除く。"""
    return re.sub(r"［.*?］$", "", h.strip())


def parse_num(s: str, *, what: str, required: bool = True) -> int | float | None:
    v = s.strip().replace(",", "")
    if v == "":
        if required:
            raise ParseError(f"{what}: 空欄")
        return None
    if not NUM_RE.fullmatch(v):
        raise ParseError(f"{what}: 数値として読めない {s!r}")
    return float(v) if "." in v else int(v)


def split_related(s: str) -> list[str]:
    return [p.strip() for p in SPLIT_RE.split(s) if p.strip()]


def parse_csv_text(
    text: str,
    *,
    kind: str,  # "11" | "12"
    division: str,
    year_month: str,
    category_aliases: dict[str, dict[str, str]] | None = None,
    source_url: str = "",
    file_label: str | None = None,
    max_rank: int = MAX_RANK,
) -> tuple[list[Row], list[OtherRow], list[Issue]]:
    label = file_label or f"{division}{kind}"
    kind_name = KIND_LABEL[kind]
    aliases = (category_aliases or {}).get(division, {})
    expected_cats = EXPECTED_CATEGORIES[division]
    issues: list[Issue] = []

    def issue(code: str, msg: str, *, excluded: bool = False, category: str = "") -> None:
        issues.append(Issue(code, year_month, label, msg, excluded, category))

    table = list(csv.reader(io.StringIO(text)))
    if not table:
        raise ParseError(f"{year_month} {label}: 空のファイル")
    header = table[0]
    expected = [base_name(h) for h in EXPECTED_HEADERS[kind]]
    if [base_name(h) for h in header] != expected:
        raise ParseError(f"{year_month} {label}: ヘッダーが想定外 {header}")
    col = {name: i for i, name in enumerate(expected)}
    name_col = col["品目"] if kind == "11" else col["原産地"]
    related_col = col["主要産地"] if kind == "11" else col["主要品目"]

    # 単位は列名から。無ければ部門で補う
    unit = None
    for h in header:
        m = re.fullmatch(r"数量合計［(.+)］", h.strip())
        if m:
            unit = norm_text(m.group(1))  # ㎏ -> kg
    if unit is None:
        unit = DEFAULT_UNITS[division]
        issue("UNIT_ASSUMED", f"列名に単位が無いため {unit} と仮定")

    seen_ym: set[str] = set()
    cur_cat: str | None = None
    rows: list[Row] = []
    others: list[OtherRow] = []
    excluded_cats: dict[str, int] = {}
    truncated: dict[str, int] = {}
    alias_used: set[str] = set()

    for lineno, r in enumerate(table[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        r = r + [""] * (len(header) - len(r))
        if r[col["大品目"]].strip():
            cur_cat = r[col["大品目"]].strip()
        if cur_cat is None:
            raise ParseError(f"{year_month} {label} L{lineno}: 大品目が空のまま行が始まる")
        y, mo = r[col["年"]].strip(), r[col["月"]].strip()
        if y and mo:
            seen_ym.add(f"{int(y):04d}-{int(mo):02d}")

        raw_cat = cur_cat
        cat = aliases.get(raw_cat, raw_cat)
        if cat != raw_cat:
            alias_used.add(f"{raw_cat}->{cat}")
        if cat not in expected_cats:
            excluded_cats[raw_cat] = excluded_cats.get(raw_cat, 0) + 1
            continue

        what = f"{year_month} {label} L{lineno}"
        rank_s = r[col["順位"]].strip()
        qty_s, qr_s = r[col["数量合計"]], r[col["数量合計比率"]]
        amt_s, ar_s = r[col["金額合計"]], r[col["金額合計比率"]]

        if not rank_s.isdigit():
            # 「その他」行。順位列が空、または「その他」が列ずれで入っていることもある
            others.append(OtherRow(
                year_month, division, cat, kind_name,
                parse_num(qty_s, what=f"{what} 数量", required=False),
                parse_num(amt_s, what=f"{what} 金額", required=False),
                parse_num(qr_s, what=f"{what} 数量比率", required=False),
                parse_num(ar_s, what=f"{what} 金額比率", required=False),
            ))
            continue

        rank = int(rank_s)
        if rank > max_rank:
            truncated[cat] = truncated.get(cat, 0) + 1
            continue
        name = r[name_col].strip()
        if not name:
            raise ParseError(f"{what}: 名前が空")
        rows.append(Row(
            year_month=year_month, division=division, kind=kind_name, category=cat,
            name=name, key=norm_text(name), rank=rank,
            qty=parse_num(qty_s, what=f"{what} 数量"), qty_unit=unit,
            qty_ratio=parse_num(qr_s, what=f"{what} 数量比率"),
            amt=parse_num(amt_s, what=f"{what} 金額"),
            amt_ratio=parse_num(ar_s, what=f"{what} 金額比率"),
            related=split_related(r[related_col]), source_url=source_url,
        ))

    if seen_ym != {year_month}:
        raise ParseError(
            f"{year_month} {label}: CSV内の年月 {sorted(seen_ym)} が一覧の月と一致しない"
        )

    for raw_cat, n in excluded_cats.items():
        issue("EXCLUDED_CATEGORY",
              f"大品目 {raw_cat!r} は部門 {division} の想定外（{n} 行を取り込まない）",
              excluded=True, category=raw_cat)
    for a in sorted(alias_used):
        issue("CATEGORY_ALIAS", f"大品目の別名を適用: {a}")
    for cat, n in truncated.items():
        issue("RANK_TRUNCATED", f"{cat}: 順位 {max_rank} 位超の {n} 行を除外", category=cat)

    # 順位の整合: 取り込んだ行は 1..n の連番であること
    by_cat: dict[str, list[int]] = {}
    for x in rows:
        by_cat.setdefault(x.category, []).append(x.rank)
    for cat, ranks in by_cat.items():
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ParseError(f"{year_month} {label}: {cat} の順位が連番でない {sorted(ranks)}")
        if len(ranks) < max_rank:
            issue("FEWER_THAN_20", f"{cat}: 順位行が {len(ranks)} 行", category=cat)
    o_by_cat: dict[str, int] = {}
    for o in others:
        o_by_cat[o.category] = o_by_cat.get(o.category, 0) + 1
    for cat in by_cat:
        n = o_by_cat.get(cat, 0)
        if n == 0:
            issue("NO_OTHER_ROW", f"{cat}: 「その他」行が無い", category=cat)
        elif n > 1:
            issue("MULTIPLE_OTHER_ROWS", f"{cat}: 「その他」行が {n} 行", category=cat)
    return rows, others, issues


def parse_month(
    ym: str, category_aliases: dict[str, dict[str, str]] | None = None,
    raw_dir: Path = RAW_DIR,
) -> ParseResult:
    mdir = raw_dir / ym.replace("-", "")
    manifest = json.loads((mdir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "ok" or manifest["year_month"] != ym:
        raise ParseError(f"{ym}: manifest が不正")
    res = ParseResult()
    for division, slot in manifest["divisions"].items():
        for key, t in slot.items():
            kind = "11" if key == "items" else "12"
            label = f"{division}{kind}"
            data = (mdir / t["saved"]).read_bytes()
            text, enc = decode_csv(data)
            res.encodings[f"{ym}/{label}"] = enc
            if enc != "utf-8-sig":
                res.issues.append(Issue("ENCODING_FALLBACK", ym, label, f"{enc} で読み込み"))
            rows, others, issues = parse_csv_text(
                text, kind=kind, division=division, year_month=ym,
                category_aliases=category_aliases, source_url=t["url"], file_label=label,
            )
            res.rows += rows
            res.others += others
            res.issues += issues
    return res


def list_months(raw_dir: Path = RAW_DIR) -> list[str]:
    """一覧（index.json）に載っている月。"""
    index = json.loads((raw_dir / "index.json").read_text(encoding="utf-8"))
    return sorted(e["year_month"] for e in index)


def parse_all(
    category_aliases: dict[str, dict[str, str]] | None = None, raw_dir: Path = RAW_DIR,
) -> ParseResult:
    total = ParseResult()
    for ym in list_months(raw_dir):
        r = parse_month(ym, category_aliases, raw_dir)
        total.rows += r.rows
        total.others += r.others
        total.issues += r.issues
        total.encodings.update(r.encodings)
    return total

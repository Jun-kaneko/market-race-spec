"""名寄せ・表示名・統合候補 (P1)。"""
from __future__ import annotations

import csv
import difflib
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from .common import ALIASES_PATH, norm_text
from .parse import ParseError, Row


@dataclass
class Aliases:
    category: dict[str, dict[str, str]]  # division -> {元: 先}
    name: dict[str, dict[str, dict[str, str]]]  # kind -> category -> {旧名: 新名}


def load_aliases(path: Path = ALIASES_PATH) -> Aliases:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cat = {
        str(div): {str(k): str(v) for k, v in (m or {}).items()}
        for div, m in (data.get("category_aliases") or {}).items()
    }
    name_raw = data.get("name_aliases") or {}
    name: dict[str, dict[str, dict[str, str]]] = {}
    for kind in ("items", "origins"):
        name[kind] = {
            str(c): {norm_text(str(k)): str(v) for k, v in (m or {}).items()}
            for c, m in (name_raw.get(kind) or {}).items()
        }
    return Aliases(cat, name)


def normalize_rows(rows: list[Row], aliases: Aliases) -> list[Row]:
    """名寄せ辞書を適用し、キーが同じ行の表記を揃える。

    - キー = NFKC＋空白除去。辞書に旧名があれば新名のキーに置き換える。
    - 同じ月・大品目・種別でキーが重複したら ParseError（人が決める）。
    - 表示名は、そのキーが最後に現れた月の表記に統一する。
    """
    out: list[Row] = []
    for r in rows:
        rule = aliases.name.get(r.kind, {}).get(r.category, {})
        new = rule.get(r.key)
        out.append(replace(r, name=new, key=norm_text(new)) if new else r)

    seen: dict[tuple, Row] = {}
    for r in out:
        k = (r.year_month, r.kind, r.category, r.key)
        if k in seen:
            raise ParseError(
                f"{r.year_month} {r.category} {r.kind}: キー重複 "
                f"{seen[k].name!r} と {r.name!r}（aliases.yml の統合ルールを見直す）"
            )
        seen[k] = r

    latest: dict[tuple, tuple[str, str]] = {}  # (kind, cat, key) -> (ym, name)
    for r in out:
        k = (r.kind, r.category, r.key)
        if k not in latest or r.year_month >= latest[k][0]:
            latest[k] = (r.year_month, r.name)
    return [replace(r, name=latest[(r.kind, r.category, r.key)][1]) for r in out]


def merge_candidates(rows: list[Row]) -> list[dict]:
    """統合候補（同じ大品目・種別の中で名前が似ているペア）を返す。

    never_together=True は同じ月に両方現れたことが無いペアで、改名・分類変更の可能性が高い。
    """
    months: dict[tuple, set[str]] = defaultdict(set)
    names: dict[tuple, str] = {}
    for r in rows:
        k = (r.kind, r.category, r.key)
        months[k].add(r.year_month)
        names[k] = r.name

    groups: dict[tuple, list[str]] = defaultdict(list)
    for kind, cat, key in months:
        groups[(kind, cat)].append(key)

    out: list[dict] = []
    for (kind, cat), keys in sorted(groups.items()):
        keys.sort()
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                reason = _similar(a, b)
                if not reason:
                    continue
                ma, mb = months[(kind, cat, a)], months[(kind, cat, b)]
                out.append({
                    "kind": kind, "category": cat,
                    "name_a": names[(kind, cat, a)], "name_b": names[(kind, cat, b)],
                    "reason": reason,
                    "months_a": len(ma), "months_b": len(mb),
                    "months_both": len(ma & mb),
                    "never_together": not (ma & mb),
                })
    return out


def _similar(a: str, b: str) -> str:
    short, long_ = sorted((a, b), key=len)
    if short == "その他":  # 「その他〜」は無数にあり、ノイズになるだけ
        return ""
    if len(short) >= 2 and short in long_:
        return "部分一致"
    if len(short) >= 3 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8:
        return "文字列が類似"
    return ""


def write_merge_candidates(cands: list[dict], path: Path) -> None:
    fields = ["kind", "category", "name_a", "name_b", "reason",
              "months_a", "months_b", "months_both", "never_together"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(cands)

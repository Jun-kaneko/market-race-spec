"""data/raw の実データに対する検証（SPEC 7.1 の自動チェックと 7.2 のフィクスチャ）。

元データに既知の不具合があるため、許容する例外は EXPECTED_ISSUES に明示する。
ここに無い例外が新しい月で出たらテストが落ちる（月次ジョブの失敗＝人が確認する合図）。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict

import pytest

from etl.build import build
from etl.common import RAW_DIR

pytestmark = pytest.mark.skipif(not (RAW_DIR / "index.json").exists(), reason="data/raw が無い")

# (code, year_month, file) -> 許容する理由
EXPECTED_ISSUES = {
    ("EXCLUDED_CATEGORY", "2024-05", "R11"): "R11 のリンク先が T11 と同一内容（青果の品目別が欠測）",
    ("CATEGORY_ALIAS", "2024-06", "R11"): "大品目が「果物」",
    ("CATEGORY_ALIAS", "2024-07", "T11"): "大品目が 1/2/3",
    ("UNIT_ASSUMED", "2024-03", "R12"): "列名に単位なし",
    ("UNIT_ASSUMED", "2024-03", "T12"): "列名に単位なし",
    ("UNIT_ASSUMED", "2024-04", "T12"): "列名に単位なし",
    ("UNIT_ASSUMED", "2024-06", "T11"): "列名に単位なし",
    ("UNIT_ASSUMED", "2025-07", "T12"): "列名に単位なし",
    ("RANK_TRUNCATED", "2024-06", "T12"): "全件掲載（71〜80位まで）",
    ("NO_OTHER_ROW", "2024-06", "T12"): "「その他」行なし",
    **{
        ("FEWER_THAN_20", ym, "V12"): "花きの産地は鉢物類が 20 未満"
        for ym in ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
                   "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    },
}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from etl.normalize import load_aliases, normalize_rows
    from etl.parse import list_months, parse_all

    aliases = load_aliases()
    res = parse_all(aliases.category)
    rows = normalize_rows(res.rows, aliases)
    out = tmp_path_factory.mktemp("out")
    summary = build(processed_dir=out / "processed", web_data_dir=out / "web", generated="2026-10-15")
    return {
        "res": res, "rows": rows, "months": list_months(), "out": out, "summary": summary,
        "market": json.loads((out / "web" / "market.json").read_text(encoding="utf-8")),
    }


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_issues_are_all_known(built):
    got = {(i.code, i.year_month, i.file) for i in built["res"].issues}
    assert got - set(EXPECTED_ISSUES) == set(), "未知の例外（元データの変化）"
    assert set(EXPECTED_ISSUES) - got == set(), "許容リストに古い項目（元データが修正された?）"


# --- 7.1-1 各（月×大品目）で順位 1..20 が各 1 行、「その他」が 1 行
def test_rank_and_other_rows(built):
    ranked = defaultdict(list)
    for r in built["rows"]:
        ranked[(r.year_month, r.kind, r.category)].append(r.rank)
    others = defaultdict(int)
    for o in built["res"].others:
        others[(o.year_month, o.kind, o.category)] += 1
    fewer = {(i.year_month, i.file, i.category) for i in built["res"].issues if i.code == "FEWER_THAN_20"}
    no_other = {(i.year_month, i.file, i.category) for i in built["res"].issues if i.code == "NO_OTHER_ROW"}
    for (ym, kind, cat), ranks in ranked.items():
        file_ = ("V" if cat in ("切花類", "鉢物類") else "R" if cat in ("野菜", "果実") else "T") + (
            "11" if kind == "items" else "12")
        if (ym, file_, cat) in fewer:
            assert sorted(ranks) == list(range(1, len(ranks) + 1)) and len(ranks) < 20
        else:
            assert sorted(ranks) == list(range(1, 21)), (ym, kind, cat)
        n_other = others[(ym, kind, cat)]
        assert n_other == (0 if (ym, file_, cat) in no_other else 1), (ym, kind, cat, n_other)


# 数量比率の合計が 100% から外れる既知の元データ不具合（比率列が他の列と整合しない。qty/amt は使える）
RATIO_EXCEPTIONS = {("2025-02", "origins", "野菜")}


# --- 7.1-2 数量比率の合計（20 位まで + その他）が約 100%
def test_qty_ratio_sums_to_100(built):
    sums = defaultdict(float)
    for r in built["rows"]:
        sums[(r.year_month, r.kind, r.category)] += r.qty_ratio
    others = {(o.year_month, o.kind, o.category): o for o in built["res"].others}
    checked = 0
    for k, s in sums.items():
        o = others.get(k)
        if o is None or o.qty_ratio is None:
            continue
        ok = abs(s + o.qty_ratio - 100) <= 0.5 + 1e-9
        assert ok != (k in RATIO_EXCEPTIONS), (k, s, o.qty_ratio)
        checked += 1
    assert checked > 400


# --- 7.1-3 取得月数が一覧のリンク数と一致
def test_month_count_matches_index(built):
    index = json.loads((RAW_DIR / "index.json").read_text(encoding="utf-8"))
    assert len(built["months"]) == len(index)
    assert built["summary"]["months"] == len(index)
    assert len(built["market"]["meta"]["months"]) == len(index)
    assert {r.year_month for r in built["rows"]} <= set(built["months"])
    # 青果・水産は全月にある
    for div in ("R", "T"):
        assert {r.year_month for r in built["rows"] if r.division == div} >= set(built["months"]) - {"2024-05"}


# --- 7.1-4 全行で qty・amt が数値として読める
def test_qty_amt_numeric_in_csv(built):
    for name in ("items.csv", "origins.csv"):
        rows = read_csv(built["out"] / "processed" / name)
        assert len(rows) > 4000
        for r in rows:
            float(r["qty"]), float(r["amt"]), float(r["qty_ratio"]), float(r["amt_ratio"])
            assert 1 <= int(r["rank"]) <= 20


# --- 7.1-5 year_month が一覧の月と一致（URL 由来の年月は使わない）
def test_year_month_comes_from_csv_not_url(built):
    index = {e["year_month"]: e for e in json.loads((RAW_DIR / "index.json").read_text(encoding="utf-8"))}
    # URL に年月が入っていない 2024-08 / URL の年月がずれている 2024-11
    assert "202408" not in index["2024-08"]["page_url"]
    assert "202411" not in index["2024-11"]["page_url"]
    for ym in ("2024-08", "2024-11"):
        assert any(r.year_month == ym for r in built["rows"])
    assert not any(r.year_month == "2024-12" and "ichiba202412geppou" in r.source_url for r in built["rows"])


# --- 7.2 検証用フィクスチャ
FIXTURES = [
    ("2023-01", "items", "生鮮水産物", "たら", 1, 176398, 81610660),
    ("2026-08", "items", "生鮮水産物", "まぐろ", 1, 85968, 299078069),
    ("2023-01", "items", "野菜", "キャベツ", 1, 451829, 43405905),
    ("2026-08", "items", "野菜", "たまねぎ", 1, 431751, 50933973),
    ("2026-08", "items", "切花類", "コギク", 1, 577450, 32978225),
    ("2023-01", "origins", "生鮮水産物", "北海道", 1, 170546, 100323786),
    ("2026-08", "origins", "生鮮水産物", "青森", 1, 76228, 83817311),
]


@pytest.mark.parametrize("ym,kind,cat,name,rank,qty,amt", FIXTURES)
def test_fixtures(built, ym, kind, cat, name, rank, qty, amt):
    rows = read_csv(built["out"] / "processed" / f"{kind}.csv")
    hit = [r for r in rows if (r["year_month"], r["category"], r["name"]) == (ym, cat, name)]
    assert len(hit) == 1
    assert (int(hit[0]["rank"]), int(hit[0]["qty"]), int(hit[0]["amt"])) == (rank, qty, amt)
    # market.json 側とも一致
    m = built["market"]
    i = m["meta"]["months"].index(ym)
    assert m[kind][cat][name]["qty"][i] == qty and m[kind][cat][name]["amt"][i] == amt


def test_fixture_units(built):
    units = {c["name"]: c["qty_unit"] for c in built["market"]["meta"]["categories"]}
    assert units["切花類"] == "本/鉢" and units["鉢物類"] == "本/鉢"
    assert units["生鮮水産物"] == units["野菜"] == "kg"


# --- market.json の構造
def test_market_json_shape(built):
    m = built["market"]
    n = len(m["meta"]["months"])
    assert n == 44
    assert [c["name"] for c in m["meta"]["categories"]] == [
        "生鮮水産物", "冷凍水産物", "塩干・加工品その他", "野菜", "果実", "切花類", "鉢物類"]
    for kind, rel in (("items", "origins"), ("origins", "items")):
        for cat, names in m[kind].items():
            for name, e in names.items():
                assert len(e["qty"]) == len(e["amt"]) == len(e[rel]) == n
                for q, a, r in zip(e["qty"], e["amt"], e[rel]):
                    assert (q is None) == (a is None) == (r is None)  # 圏外は null で揃う
                    assert q != 0
    # 花きは 2025-11 より前は全て null
    first = m["meta"]["months"].index("2025-11")
    for name, e in m["items"]["切花類"].items():
        assert all(v is None for v in e["qty"][:first])
    # 欠測月は null で、missing に記録される
    assert m["meta"]["missing"]["items"] == {"野菜": ["2024-05"], "果実": ["2024-05"]}
    i = m["meta"]["months"].index("2024-05")
    assert all(e["qty"][i] is None for e in m["items"]["野菜"].values())
    assert any(e["qty"][i] is not None for e in m["origins"]["野菜"].values())  # 産地別は有る


def test_each_month_has_top20_per_category(built):
    m = built["market"]
    for cat, names in m["items"].items():
        div_missing = set(m["meta"]["missing"]["items"].get(cat, []))
        first = next(c["first_month"] for c in m["meta"]["categories"] if c["name"] == cat)
        for i, ym in enumerate(m["meta"]["months"]):
            cnt = sum(1 for e in names.values() if e["qty"][i] is not None)
            if ym in div_missing or ym < first:
                assert cnt == 0, (cat, ym)
            else:
                assert cnt == 20, (cat, ym, cnt)

"""parse / normalize / build の単体テスト（合成データ。ネットワーク・data/raw 不要）。"""
from __future__ import annotations

import csv
import io

import pytest

from etl.build import build_market_json, write_rows
from etl.normalize import Aliases, merge_candidates, normalize_rows
from etl.parse import ParseError, Row, parse_csv_text, split_related

H11 = "大品目,年［西暦］,月,品目,順位,数量合計［㎏］,数量合計比率［％］,金額合計［円］,金額合計比率［％］,主要産地"
H12 = "大品目,年［西暦］,月,順位,原産地,数量合計［㎏］,数量合計比率［％］,金額合計［円］,金額合計比率［％］,主要品目"


def parse(text, kind="11", division="T", ym="2024-01", **kw):
    return parse_csv_text(text, kind=kind, division=division, year_month=ym, **kw)


def mkrow(ym, name, qty=1, cat="生鮮水産物", kind="items", related=None, rank=1):
    from etl.common import norm_text
    return Row(ym, "T", kind, cat, name, norm_text(name), rank, qty, "kg", 1.0, qty * 10, 1.0,
               related or [])


def test_basic_items_and_other_row():
    text = "\n".join([
        H11,
        "生鮮水産物,2024,1,まぐろ,1,100,50,1000,60,台湾、静岡",
        "生鮮水産物,2024,1,ぶり,2,50,25,500,30,北海道・青森",
        ",,,その他,,50,25,500,10,",
    ])
    rows, others, issues = parse(text)
    assert [(r.name, r.rank, r.qty, r.qty_unit) for r in rows] == [("まぐろ", 1, 100, "kg"), ("ぶり", 2, 50, "kg")]
    assert rows[0].related == ["台湾", "静岡"]  # 区切りは 、 と ・ の両方
    assert rows[1].related == ["北海道", "青森"]
    assert len(others) == 1 and others[0].category == "生鮮水産物" and others[0].qty == 50
    assert {i.code for i in issues} == {"FEWER_THAN_20"}


def test_other_row_misaligned_rank_column():
    # 2024-08 R12 型: 順位の列に「その他」が入っている
    text = "\n".join([
        H12,
        "野菜,2024,1,1,北海道,100,50,1000,60,たまねぎ",
        ",,,その他,,22964,0.7,17853080,2.0,",
    ])
    rows, others, _ = parse(text, kind="12", division="R")
    assert len(rows) == 1 and len(others) == 1
    assert others[0].qty == 22964 and others[0].kind == "origins"


def test_other_row_with_empty_ratio_and_filled_columns():
    # 2023-11 型: 「その他」行にも大品目・年月が入る / 2024-12 型: 比率が空
    text = "\n".join([
        H11,
        "野菜,2024,1,キャベツ,1,100,50,1000,60,新潟",
        "野菜,2024,1,その他,,33088,1.5,20189153,,",
    ])
    rows, others, _ = parse(text, division="R")
    assert len(rows) == 1
    assert others[0].amt_ratio is None and others[0].qty_ratio == 1.5


def test_unit_missing_uses_division_default():
    text = "\n".join([
        "大品目,年,月,品目,順位,数量合計,数量合計比率,金額合計,金額合計比率,主要産地",
        "切花類,2024,1,コギク,1,577450,50,32978225,60,",
    ])
    rows, _, issues = parse(text, division="V")
    assert rows[0].qty_unit == "本/鉢"
    assert "UNIT_ASSUMED" in {i.code for i in issues}


def test_unit_read_from_header():
    text = H11.replace("［㎏］", "［本/鉢］").replace("品目", "品目") + "\n切花類,2024,1,コギク,1,5,50,3,60,\n"
    rows, _, _ = parse(text, division="V")
    assert rows[0].qty_unit == "本/鉢"
    rows, _, _ = parse(H11 + "\n生鮮水産物,2024,1,まぐろ,1,5,50,3,60,\n")
    assert rows[0].qty_unit == "kg"  # ㎏ -> kg


def test_rank_over_20_is_truncated():
    lines = [H11] + [f"生鮮水産物,2024,1,品{i},{i},{100 - i},1,10,1," for i in range(1, 26)]
    rows, others, issues = parse("\n".join(lines))
    assert [r.rank for r in rows] == list(range(1, 21))
    codes = {i.code for i in issues}
    assert {"RANK_TRUNCATED", "NO_OTHER_ROW"} <= codes


def test_category_alias_and_unexpected_category_excluded():
    text = "\n".join([
        H11,
        "果物,2024,1,もも,1,100,50,1000,60,山梨",
        "冷凍水産物,2024,1,さば,1,100,50,1000,60,",
    ])
    rows, _, issues = parse(text, division="R", category_aliases={"R": {"果物": "果実"}})
    assert [(r.category, r.name) for r in rows] == [("果実", "もも")]
    by = {i.code: i for i in issues}
    assert by["EXCLUDED_CATEGORY"].excluded and by["EXCLUDED_CATEGORY"].category == "冷凍水産物"
    assert "CATEGORY_ALIAS" in by


def test_year_month_mismatch_raises():
    with pytest.raises(ParseError, match="年月"):
        parse(H11 + "\n生鮮水産物,2024,2,まぐろ,1,5,50,3,60,\n", ym="2024-01")


def test_header_mismatch_raises():
    with pytest.raises(ParseError, match="ヘッダー"):
        parse(H12 + "\n生鮮水産物,2024,1,1,青森,5,50,3,60,\n", kind="11")


@pytest.mark.parametrize("bad", ["abc", ""])
def test_non_numeric_qty_raises(bad):
    with pytest.raises(ParseError):
        parse(H11 + f"\n生鮮水産物,2024,1,まぐろ,1,{bad},50,3,60,\n")


def test_rank_gap_raises():
    text = H11 + "\n生鮮水産物,2024,1,a,1,5,5,3,6,\n生鮮水産物,2024,1,b,3,5,5,3,6,\n"
    with pytest.raises(ParseError, match="連番"):
        parse(text)


def test_split_related():
    assert split_related("北海道、青森・ 新潟") == ["北海道", "青森", "新潟"]
    assert split_related("") == []


def test_normalize_nfkc_merge_and_latest_display_name():
    rows = [mkrow("2023-01", "ＳＰキク"), mkrow("2023-02", "SPキク"), mkrow("2023-03", "ＳＰキク")]
    out = normalize_rows(rows, Aliases({}, {"items": {}, "origins": {}}))
    assert len({r.key for r in out}) == 1
    assert {r.name for r in out} == {"ＳＰキク"}  # 最新月の表記


def test_normalize_does_not_merge_distinct_names():
    rows = [mkrow("2023-01", "その他ぶり"), mkrow("2023-01", "その他ぶり類", rank=2)]
    out = normalize_rows(rows, Aliases({}, {"items": {}, "origins": {}}))
    assert len({r.key for r in out}) == 2


def test_normalize_same_month_key_collision_raises():
    rows = [mkrow("2023-01", "ＳＰキク"), mkrow("2023-01", "SPキク", rank=2)]
    with pytest.raises(ParseError, match="キー重複"):
        normalize_rows(rows, Aliases({}, {"items": {}, "origins": {}}))


def test_normalize_name_alias():
    aliases = Aliases({}, {"items": {"生鮮水産物": {"いなだ": "ぶり"}}, "origins": {}})
    rows = [mkrow("2023-01", "いなだ"), mkrow("2023-02", "ぶり")]
    out = normalize_rows(rows, aliases)
    assert {r.name for r in out} == {"ぶり"} and len({r.key for r in out}) == 1


def test_merge_candidates_flags_similar_names():
    rows = [mkrow("2023-01", "その他ぶり"), mkrow("2023-02", "その他ぶり類")]
    c = merge_candidates(rows)
    assert len(c) == 1 and c[0]["never_together"] is True
    assert merge_candidates([mkrow("2023-01", "まぐろ"), mkrow("2023-01", "さけ", rank=2)]) == []


def test_build_market_json_nulls_and_missing():
    from etl.parse import Issue

    months = ["2024-01", "2024-02", "2024-03"]
    rows = [
        mkrow("2024-01", "まぐろ", 10, related=["台湾"]),
        mkrow("2024-03", "まぐろ", 30, related=["静岡"]),
        mkrow("2024-01", "ぶり", 5, rank=2),
    ]
    issues = [Issue("EXCLUDED_CATEGORY", "2024-02", "R11", "x", excluded=True)]
    m = build_market_json(rows, issues, months, "2026-10-15")
    tuna = m["items"]["生鮮水産物"]["まぐろ"]
    assert tuna["qty"] == [10, None, 30]  # 圏外は null（0ではない）
    assert tuna["origins"] == [["台湾"], None, ["静岡"]]
    assert m["meta"]["months"] == months
    assert m["meta"]["categories"][0] == {
        "name": "生鮮水産物", "division": "T", "qty_unit": "kg", "first_month": "2024-01"}
    assert m["meta"]["missing"]["items"] == {"野菜": ["2024-02"], "果実": ["2024-02"]}
    assert list(m["items"]["生鮮水産物"]) == ["まぐろ", "ぶり"]  # 数量合計の降順


def test_csv_quote_is_escaped_exactly_once(tmp_path):
    """名前に " を含んでも二重エスケープされない（生テキストで確認）。"""
    p = tmp_path / "items.csv"
    write_rows([mkrow("2024-01", 'A"B')], p)
    raw = p.read_text(encoding="utf-8")
    assert ',"A""B",' in raw
    assert '"""A""B"""' not in raw
    assert list(csv.DictReader(io.StringIO(raw)))[0]["name"] == 'A"B'

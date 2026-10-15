"""ETL 共通の定数・ユーティリティ。"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

INDEX_URL = (
    "https://www.city.niigata.lg.jp/shisei/seisaku/it/open-data/"
    "opendata-keizai/od-ichibageppou/index.html"
)
USER_AGENT = "market-race-etl/0.1 (Niigata wholesale market open-data visualizer)"

# 部門見出し -> 部門コード
DIVISIONS = {"青果部": "R", "水産物部": "T", "花き部": "V"}

# リンク文言（NFKC・空白除去後に部分一致）-> 表の種別コード
TABLE_KINDS = {
    "品目別取扱高順位表": "11",
    "産地別取扱高順位表": "12",
}

ITEMS_HEADER = [
    "大品目", "年［西暦］", "月", "品目", "順位", "数量合計［単位］",
    "数量合計比率［％］", "金額合計［円］", "金額合計比率［％］", "主要産地",
]
ORIGINS_HEADER = [
    "大品目", "年［西暦］", "月", "順位", "原産地", "数量合計［単位］",
    "数量合計比率［％］", "金額合計［円］", "金額合計比率［％］", "主要品目",
]
EXPECTED_HEADERS = {"11": ITEMS_HEADER, "12": ORIGINS_HEADER}

EXPECTED_CATEGORIES = {
    "R": {"野菜", "果実"},
    "T": {"生鮮水産物", "冷凍水産物", "塩干・加工品その他"},
    "V": {"切花類", "鉢物類"},
}

# 照合用の副次チェック。ファイル名は年代で揺れるので "_" と "-" の両方を許す
FILENAME_RE = re.compile(r"(\d{6})[_-]?([RTV])(\d{2})", re.IGNORECASE)


def norm_text(s: str) -> str:
    """NFKC 正規化して空白を全て除去する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def decode_csv(data: bytes) -> tuple[str, str]:
    """(text, encoding) を返す。utf-8-sig を試し、失敗したら cp932。"""
    try:
        return data.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return data.decode("cp932"), "cp932"


# ---- P1 で追加 ----

CONFIG_DIR = ROOT / "etl" / "config"
ALIASES_PATH = CONFIG_DIR / "aliases.yml"
WEB_DATA_DIR = ROOT / "web" / "public" / "data"

MAX_RANK = 20

# 列名に単位が無い月のフォールバック（部門ごと）
DEFAULT_UNITS = {"R": "kg", "T": "kg", "V": "本/鉢"}

# 大品目の表示順（部門コードも対応づける）
CATEGORY_ORDER = [
    ("生鮮水産物", "T"), ("冷凍水産物", "T"), ("塩干・加工品その他", "T"),
    ("野菜", "R"), ("果実", "R"),
    ("切花類", "V"), ("鉢物類", "V"),
]

KIND_LABEL = {"11": "items", "12": "origins"}

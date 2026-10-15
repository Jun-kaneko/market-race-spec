# market-race-spec

新潟市中央卸売市場の月報オープンデータから、品目別・産地別の取扱量の月次推移をバーチャートレースで見せる静的サイト。

- 公開サイト: https://jun-kaneko.github.io/market-race-spec/
- 仕様: [docs/SPEC.md](docs/SPEC.md) / 設計: [docs/DESIGN.md](docs/DESIGN.md) / 引き継ぎ・運用: [docs/HANDOVER.md](docs/HANDOVER.md)

## 開発

```bash
# ETL（リポジトリルートで）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m etl.build && pytest

# フロント
cd web && npm install && npm run dev
```

データは新潟市中央卸売市場月報（新潟市、CC BY 2.1 日本）を改変して利用しています。本サイトは新潟市が作成・保証したものではありません。

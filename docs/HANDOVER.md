# 引き継ぎメモ

最終更新: 2026-10-15（会社 Ubuntu 環境で P0 完了時点）

## 1. 現在地

| フェーズ | 状態 |
|---|---|
| P0 取得と調査 | 完了 |
| P1 ETL（parse / normalize / build / テスト） | 未着手 |
| P2 以降（フロント・演出・公開・月次更新） | 未着手 |

P0 の成果物:

- `etl/fetch.py`: 一覧ページ → 月ページ → CSV 取得、レポート出力
- `etl/common.py`: パス・定数・NFKC 正規化・文字コードフォールバック
- `data/raw/YYYYMM/{R,T,V}{11,12}.csv` と `manifest.json`（44 か月、196 ファイル）
- `data/raw/index.json`、`data/raw/report.md`、`data/raw/report.json`

仕様の全文は [SPEC.md](SPEC.md)、設計メモは [DESIGN.md](DESIGN.md) を参照。

## 2. 開発環境の移行（Ubuntu -> macOS）

### 2.1 セットアップ（macOS）

```bash
git clone <このリポジトリ> market && cd market
python3 -m venv .venv          # Python 3.12 推奨（Ubuntu 側は 3.12.3）
source .venv/bin/activate
pip install -r requirements.txt
```

- `.venv/` はコミットしない（OS 依存のため）。Mac では必ず作り直す。
- Node は P2 から必要（Vite + TypeScript）。`brew install node` で導入し、バージョンは LTS を使う。

### 2.2 取得済みデータの持ち越し

`data/raw/`（243 ファイル、約 1.6MB）は現状 **未コミット**（`.gitignore` にも入れていない）。
Mac で使う方法は次のどちらか。

1. **`data/raw/` をコミットして共有する（推奨）**。サイズが小さく、
   元サイトの月ページ構造が将来変わっても再現できる。仕様 9 章の GitHub Actions でもキャッシュとして使える。
2. コミットせず、Mac 側で `python -m etl.fetch` を実行して取り直す（約 5 分。1 秒間隔で約 250 リクエスト）。

どちらにするかは未決定。コミットは行っていない。

### 2.3 OS 差異の注意点

- **CA ストア**: `etl/fetch.py` は `/etc/ssl/certs/ca-certificates.crt` が存在すれば
  `session.verify` に使う。これは Ubuntu 社内環境で certifi だと
  「self-signed certificate in certificate chain」になったための対処。
  macOS ではこのパスが無いので certifi が使われる。自宅環境で SSL エラーが出る場合は
  環境変数 `REQUESTS_CA_BUNDLE` で CA バンドルを指定する（指定があればそちらが優先される）。
  証明書検証の無効化はしないこと。
- **文字コード**: CSV は全て `utf-8-sig` で読めた。ファイル名は日本語を含まないので OS 差は出ない。
- **改行**: Git の `core.autocrlf` を変えないこと。CSV は取得したバイト列をそのまま保存している。
- **Python スクリプトの実行**: リポジトリルートから `python -m etl.fetch` の形で実行する
  （`etl/` はパッケージ。`python etl/fetch.py` は相対 import で失敗する）。

## 3. P0 の調査結果（要点）

詳細は `data/raw/report.md`（`python -m etl.fetch --report-only` で再生成できる）。

- 一覧のリンクは 2023-01〜2026-08 の 44 件。欠損月なし。年月は一覧のリンク文言から取得
  （月ページ URL は不規則。例: 2024-08 は `odichiba20240904.html`、2024-11 は `ichiba202412geppou.html`）。
- 全 44 か月で青果部（R）・水産物部（T）あり。**花き部（V）は 2025-11 開始**（10 か月分）。
- CSV は全 196 ファイルが `utf-8-sig` で読めた（cp932 フォールバックは未使用）。
- CSV ファイル名は 25 か月で `YYYYMM_?[RTV]NN` に一致しない。リンク文言と部門見出しで特定しているので問題なし。

### 元データの不具合（P1 で対処が必要）

| 月 / ファイル | 内容 | 対処方針（案） |
|---|---|---|
| 2024-05 R11 | リンク先が T11 と同一内容（水産物）。青果の品目別が欠損 | 取り込まず、欠測月として扱う。扱いは要決定（8 章） |
| 2024-06 R11 | 大品目が「果実」ではなく「果物」 | `aliases.yml` で `果物 -> 果実`（大品目の別名） |
| 2024-07 T11 | 大品目が `1`/`2`/`3`。並び順から 生鮮/冷凍/塩干 と推定 | 内容（品目）を確認のうえ別名で対応。推定である点を明記 |
| 2024-06 T12 | 順位が 71〜80 位まであり、「その他」行なし（全件掲載） | 順位 1〜20 のみ採用。「その他」は作らない |
| 2024-08 R12 | 「その他」行が列ずれ（順位の列に「その他」、原産地は空） | 順位が数字でない行を「その他」扱いにする |
| 2025-11〜2026-08 V12 | 鉢物類の産地は 9〜13 行のみ（20 行未満） | 検査 7.1-1 は花きの産地表で 20 行未満を許容 |
| 2024-03 R12/T12, 2024-04 T12, 2024-06 T11, 2025-07 T12 | 列名に単位なし、年が `年`（`年［西暦］`ではない） | R/T は kg と仮定。列名の注記有無を無視して照合 |

## 4. 次にやること（P1）

1. `etl/parse.py`: CSV -> 縦持ち。SPEC 4.4 と上表の不具合を反映
   - 大品目はキャリーフォワード、「その他」は別保持（`others.csv`）
   - 数量単位は列名から取得。無ければ部門から補う（R/T=kg、V=本/鉢）
   - 主要産地/主要品目は `・` と `、` の両方で分割
   - 順位が 21 位以上の行は捨てる
2. `etl/normalize.py` と `etl/config/aliases.yml`（初期は大品目の別名のみ）
3. `etl/build.py`: `data/processed/{items,origins,others}.csv` と `web/public/data/market.json`
4. `tests/`: SPEC 7.1 の自動チェックと 7.2 のフィクスチャ（上の不具合を考慮して条件を調整）
5. 統合候補（NFKC で一致しない類似名）の一覧出力

## 5. 実行コマンド早見表

```bash
python -m etl.fetch                      # 未取得の月だけ取得 + レポート
python -m etl.fetch --force              # 全月再取得
python -m etl.fetch --months 2023-01,2026-08
python -m etl.fetch --report-only        # 取得せずレポート再生成
pytest                                   # P1 以降
```

## 6. 取得時のルール（守ること）

- リクエスト間隔は 1 秒以上（コード側で `max(interval, 1.0)`）。User-Agent に `market-race-etl` を含める。
- 取得済みの月は再取得しない（`manifest.json` が `ok` で CSV が揃っていればスキップ）。
- 失敗した月が 1 件でもあれば終了コード 1（月次ジョブでの通知用）。

## 7. 注意（ハマりどころ）

- `replace` 系の自動編集で、正規表現文字列や `$` を含む行が壊れた事例があった。
  編集後は `python -m py_compile etl/*.py` で確認する。
- 長時間の取得をバックグラウンドで走らせる場合は `nohup ... < /dev/null &` と `disown`、`PYTHONUNBUFFERED=1` を併用する。

## 8. 未決事項

- 2024-05 の青果品目別が欠損する件: フロントで「null（圏外）」と区別して欠測扱いにするか、手作業で補うか。
- `data/raw/` をコミットするか（2.2 参照）。
- 2024-07 T11 の大品目 `1/2/3` の対応づけ（推定）の最終確認。
- 列名に単位が無い月の単位を kg と仮定してよいか（値の桁で妥当性を確認する）。
- 花き部の開始月前（〜2025-10）の扱い: 切花類・鉢物類のレースは 2025-11 以降のみ。UI で期間を明示する。
- コミットはまだ行っていない（`.gitignore`、`etl/`、`requirements.txt`、`docs/` が未追跡）。

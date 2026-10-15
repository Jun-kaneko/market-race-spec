# 引き継ぎメモ

最終更新: 2026-10-15（会社 Ubuntu 環境で P1 完了時点）

## 1. 現在地

| フェーズ | 状態 |
|---|---|
| P0 取得と調査 | 完了 |
| P1 ETL（parse / normalize / build / テスト） | 完了（36 テスト通過） |
| P2 フロント MVP（`web/`） | 完了（ブラウザで動作確認済み） |
| P3 演出（キャプション・ツールチップ・色） | 完了（キャプションは実データで出力確認、画面表示は要目視） |
| P4 公開と月次更新（`.github/workflows/deploy.yml`） | 完了。https://jun-kaneko.github.io/market-race-spec/ で公開中（2026-10-15 に push・手動実行ともに成功） |

P0 の成果物:

- `etl/fetch.py`: 一覧ページ → 月ページ → CSV 取得、レポート出力
- `etl/common.py`: パス・定数・NFKC 正規化・文字コードフォールバック
- `data/raw/YYYYMM/{R,T,V}{11,12}.csv` と `manifest.json`（44 か月、196 ファイル）
- `data/raw/index.json`、`data/raw/report.md`、`data/raw/report.json`

P1 の成果物:

- `etl/parse.py`: CSV -> 縦持ち。元データの不具合は `Issue` として記録しつつ吸収
- `etl/normalize.py`: 名寄せ（NFKC 自動統合 + `aliases.yml`）、統合候補の抽出
- `etl/config/aliases.yml`: 大品目の別名（果物->果実、1/2/3->水産3区分）。品目の統合ルールは空
- `etl/build.py`: `data/processed/{items,origins,others}.csv`、`merge_candidates.csv`、`report.md`、`web/public/data/market.json`
- `tests/test_etl_unit.py`（合成データ）、`tests/test_data.py`（実データ。SPEC 7.1 / 7.2）

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

`data/raw/`（243 ファイル、約 1.6MB）は **コミット・push 済み**（コミット `eee9fe9`）。
clone すればそのまま使える。サイズが小さく、元サイトの月ページ構造が将来変わっても再現できる。
仕様 9 章の GitHub Actions でもキャッシュとして使える。

取り直したい場合は Mac 側で `python -m etl.fetch --force` を実行する（約 5 分。1 秒間隔で約 250 リクエスト）。

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

### 元データの不具合（P1 で対処済み）

| 月 / ファイル | 内容 | 対処方針（案） |
|---|---|---|
| 2024-05 R11 | リンク先が T11 と同一内容（水産物）。青果の品目別が欠損 | 取り込まない。`market.json` の `meta.missing` に記録し、値は null |
| 2024-06 R11 | 大品目が「果実」ではなく「果物」 | `aliases.yml` の `category_aliases` で吸収 |
| 2024-07 T11 | 大品目が `1`/`2`/`3` | `category_aliases` で 生鮮/冷凍/塩干 に対応づけ（前月の品目との重なりで確認済み） |
| 2024-06 T12 | 順位が 71〜80 位まであり、「その他」行なし（全件掲載） | 順位 1〜20 のみ採用。「その他」は無し |
| 2024-08 R12 | 「その他」行が列ずれ（順位の列に「その他」、原産地は空） | 順位が数字でない行を「その他」扱い |
| 2025-11〜2026-08 V12 | 鉢物類の産地は 9〜13 行のみ（20 行未満） | 許容（テストの許容リストに明記） |
| 2024-03 R12/T12, 2024-04 T12, 2024-06 T11, 2025-07 T12 | 列名に単位なし、年が `年`（`年［西暦］`ではない） | R/T は kg と仮定（前後の月と数量の桁が同じことを確認済み）。列名の注記有無は無視して照合 |
| 2025-02 R12（野菜） | 数量比率の合計が 102.6%（比率列が他列と整合しない）。qty/amt 自体は問題なし | 7.1-2 の例外として明記。比率はフロントで使わない |
| 2025-02 R12/T12 ほか数か所 | 金額比率の合計が 100% から外れる（SPEC は数量比率のみ検査） | 検査対象外 |

## 4. 次にやること

P2 の実装状況（`web/`、Vite + TypeScript + ECharts 5）:

- 実装済み: バーチャートレース、大品目・軸・指標・TOP10/20、再生/一時停止/最初から、スライダー、速度、月表示、基本ツールチップ、金額モード注記、クレジット
- 起動: `cd web && npm install && npm run dev`（ビルドは `npm run build`）
- 欠測月は**フレームを飛ばす**（値 0 にしない）。花きは 2025-11 以降のフレームのみ。いずれも画面に注記

P3 の実装:

- `web/src/captions.ts`: 自動キャプション（1位交代 > 急増(3倍以上、表示中の TOP N のみ) > TOP10 新規入り、最大2件）。欠測月を挟む場合は「前月」ではなく比較月を明示
- ツールチップ: 順位と前月（連続でなければ「前回」）の順位を表示。色は項目名ハッシュで固定（P2 から）
- 季節表示（`web/src/season.ts`）: 月ごとのモチーフ（絵文字）と季節ラベルを月表示の横に出し、グラフ背景を季節色で薄く切り替える。絵文字は OS で見た目が変わる。気に入れば SVG に差し替える余地あり
- 集計の切替（月次／累計、**既定は累計**）: `valueTable`（`web/src/data.ts`）で累計テーブルを作る。累計は「TOP20 に入った月」の合計なので実際より少なく出る品目がある（画面に注記）。累計では「急増」キャプションを出さず、1位交代と TOP10 入りのみ。欠測月・花き開始前は累計に入らない
- キャプションのテストは未作成（Node の `tsx` で実データ出力を目視した）

次: 2026-11-20 の月次ジョブ（cron）が初めて自動で動く。9 月分の月報が公開されていれば取り込まれる。結果を確認すること。

### `market.json` を使うときの注意

- 配列は `meta.months` と同じ長さ（44）。TOP20 圏外・データ無しは `null`（0 ではない）。
- `meta.categories[].first_month`: 花き（切花類・鉢物類）は `2025-11`。それ以前は全て null。
- `meta.missing.items`: 欠測の月（現状 野菜・果実の `2024-05`）。圏外ではなくデータが取れていない月。
  レースでは値 0 に落とさず、その月を飛ばす／注記するなど扱いを決める（未決）。
- 品目名の並びは期間中の数量合計の降順。表示名は最新月の表記。
- `統合候補`: `data/processed/merge_candidates.csv`（43 件、同月に共存しない 10 件は改名・分類移動の可能性）。
  採用するものは `aliases.yml` の `name_aliases` に書く（今は未採用）。

## 5. 実行コマンド早見表

```bash
python -m etl.fetch                      # 未取得の月だけ取得 + レポート
python -m etl.fetch --force              # 全月再取得
python -m etl.fetch --months 2023-01,2026-08
python -m etl.fetch --report-only        # 取得せずレポート再生成
python -m etl.build                      # data/raw -> processed CSV + market.json（1 秒程度）
pytest                                   # 36 テスト。実データ検証は data/raw が必要
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

- 欠測月（2024-05 の青果品目別）: 現状はフレームを飛ばす仮実装。手作業で補う案もあり。
- 品目の統合ルール（`name_aliases`）を採用するか。統合候補を人が確認して決める。
- 花き部の開始月前（〜2025-10）の扱い: 切花類・鉢物類のレースは 2025-11 以降のみ。UI で期間を明示する。
- ~~月次ジョブで `data/raw/` をリポジトリに保持するか~~ → **保持する**（約 1.6MB と小さく、元サイトの構造変更後も再現できるため。月次ジョブが新しい月だけコミットする）。

## 8.1 検討して見送ったこと

- **産地×品目の組み合わせレース**（例:「新潟のキャベツ」「新潟のはくさい」）: 見送り（2026-10-15 決定）。
  元データの月報 CSV に産地×品目の数量・金額が無いため。品目別表（`*11`）は品目ごとの数量に「主要産地」の産地名だけ、
  産地別表（`*12`）は産地ごとの数量に「主要品目」の品目名だけを持ち、内訳の数量は載っていない。
  按分による推計は根拠が乏しいので採らない。代替案（産地フィルタ、主要産地への登場の表示）も採用しなかった。
  再検討する場合は、日別取扱高（`09`）・県内県外対比（`10`）など別 CSV に産地×品目の粒度があるかを先に確認する。

## 9. 月次更新での注意

- `tests/test_data.py` の `EXPECTED_ISSUES` に無い元データの例外が出るとテストが落ちる。
  新しい月で構造が変わった合図なので、内容を確認して `parse.py` / `aliases.yml` / 許容リストを更新する。

### 9.1 公開（GitHub Pages）と月次ジョブ

仕組みの解説は [DEPLOY.md](DEPLOY.md) を参照。

`.github/workflows/deploy.yml`（update-and-deploy）:

- **起動**: 毎月 20 日 10:00 JST（cron）、手動（workflow_dispatch）、`web/** etl/** tests/** data/raw/**` を変える main への push。
- **流れ**: `etl.fetch`（push 時は省略）→ `etl.build` → `pytest` → 新しい月があれば `data/` と `web/public/data/` を main にコミット → `npm ci && npm run build` → Pages へデプロイ。
- **失敗時**: テストが落ちる（元データの構造変更）とデプロイしない。取得だけ失敗した場合は、公開済みデータでデプロイを続けたうえで最後の `alert` ジョブでワークフローを失敗させ、通知する。
- 新しい月が無い場合は、データのコミットはせずに再デプロイだけ行う（`report.md` や `market.json` の生成日だけの差分は無視する）。

**初回の準備（手作業。2026-10-15 に実施済み）**

1. 変更を push する（`git push origin main`）。
2. GitHub のリポジトリ設定 → Pages → Source を **GitHub Actions** にする。
3. Actions タブから `update-and-deploy` を手動実行し、デプロイ結果の URL を確認する。
4. 社内 Ubuntu とは別に、GitHub のランナーでは CA ストアは標準のもの（`/etc/ssl/certs/ca-certificates.crt`）が使われる。SSL エラーが出たら `REQUESTS_CA_BUNDLE` を確認する。

**確認済み**: push 契機と手動実行の両方が成功し、サイトとデータ（44 か月）が公開されている。**未確認**: cron による定期実行と、新しい月が実際に取り込まれる経路（新しい月が出るまで確認できない）。

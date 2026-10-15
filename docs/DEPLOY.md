# デプロイの仕組み（GitHub Actions + GitHub Pages）

このプロジェクトが、どの設定で GitHub Actions から自動デプロイされ、公開されているかをまとめる。
運用手順（初回の準備、月次更新の注意）は [HANDOVER.md](HANDOVER.md) の 9 章を参照。

- 公開 URL: https://jun-kaneko.github.io/market-race-spec/
- ワークフロー: [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)（名前: `update-and-deploy`）

## 1. 全体像

GitHub Actions は、リポジトリ内のワークフロー定義（YAML）に書かれた手順を、GitHub が用意した一時的なサーバー（ランナー）で実行する仕組み。
このプロジェクトでは、その最後でビルドしたサイトを GitHub Pages に渡して公開している。

```
push / 毎月20日 / 手動
        ↓
 GitHub が Ubuntu ランナーを起動
        ↓
 build: コード取得 → データ取得・変換 → テスト → サイトをビルド（web/dist）
        ↓ 成果物（artifact）として保存
 deploy: GitHub Pages に配置
        ↓
 https://jun-kaneko.github.io/market-race-spec/
```

## 2. 設定したもの（3 か所）

### 2.1 ワークフローファイル（リポジトリ内）

`.github/workflows/deploy.yml`。このパスに置くと GitHub がワークフローとして自動で認識する。

| 設定 | 役割 |
|---|---|
| `on:` | いつ動くか。`schedule`（cron）、`workflow_dispatch`（手動）、`push`（main への変更） |
| `permissions:` | ワークフローに与える権限。`contents: write`（データをコミットで戻す）、`pages: write` と `id-token: write`（Pages へデプロイ） |
| `concurrency:` | 同時実行を 1 つにまとめる（`group: pages`）。デプロイが重ならないようにする |
| `jobs:` | 実行する仕事の単位。`build`、`deploy`、`alert` |
| `uses: actions/...` | 公式の部品を呼び出す（checkout、setup-python、setup-node、upload-pages-artifact、deploy-pages） |
| `run:` | 実際のコマンド（`python -m etl.build`、`pytest`、`npm run build` など） |
| `environment: github-pages` | Pages 用の配備先。デプロイ結果の URL が表示される |

公開を担うのは次の 2 つの組。

1. `build` ジョブ末尾の `actions/upload-pages-artifact`（`web/dist` を成果物として保存）
2. `deploy` ジョブの `actions/deploy-pages`（保存した成果物を Pages に公開）

### 2.2 リポジトリの Pages 設定（GitHub の画面）

Settings → Pages → **Source: GitHub Actions**。ファイルではなく GitHub 側の設定。

「ブランチの内容を公開する」方式ではなく「Actions が作った成果物を公開する」方式に切り替える設定で、
これをしていないと `deploy-pages` が失敗する。

### 2.3 公開物に合わせたビルド設定（プロジェクト内）

- `web/vite.config.ts` の `base: './'`: 公開 URL がサブパス（`/market-race-spec/`）になるため、ファイルを相対パスで参照する。
- `web/package-lock.json` をコミット: ランナーで `npm ci` により、手元と同じ版を再現する。
- `data/raw/` をコミット: ランナーが毎回、全期間を取り直さずに済み、元サイトの構造が変わっても再現できる。

## 3. 権限と認証

- トークンや鍵を自分で用意する必要はない。ワークフローには GitHub が一時的な `GITHUB_TOKEN` を自動で渡す。
- `permissions:` で、そのトークンに何を許可するかを宣言する。許可していない操作はできない。
- `GITHUB_TOKEN` による push は、別のワークフローを起動しない。月次ジョブがデータをコミットしても、無限ループにはならない。

## 4. 起動条件

| 契機 | 内容 | 取得（`etl.fetch`） |
|---|---|---|
| `schedule` | 毎月 20 日 10:00 JST（UTC 01:00） | 実行する |
| `workflow_dispatch` | Actions タブからの手動実行 | 実行する |
| `push` | main への push。対象は `web/** etl/** tests/** data/raw/** requirements.txt` とワークフロー自身 | 省略する（コミット済みデータで再ビルド） |

docs だけの変更は対象外で、デプロイは走らない。

## 5. このプロジェクト固有の工夫

- **取得失敗でも公開は続ける**: `etl.fetch` が失敗しても、公開済みデータでデプロイは続行する。最後の `alert` ジョブがワークフローを失敗させて通知する。
- **テストが落ちたら公開しない**: `pytest` が落ちる（元データの構造変更の合図）とデプロイせずに止まり、壊れたサイトを公開しない。
- **新しい月があるときだけコミット**: `data/raw/<YYYYMM>/` と `index.json` に差分があるときだけ、`data/` と `web/public/data/` を main にコミットする。
  `report.md` や `market.json` の生成日だけの差分では履歴を汚さない。

## 6. 他のプロジェクトで使う場合の最小構成

1. 静的サイトをビルドできる状態にする（`npm run build` で `dist/` ができる）。
2. `.github/workflows/` に、次の流れのワークフローを置く。
   - コードを取得する（`checkout`）。
   - ビルドする。
   - `upload-pages-artifact` で成果物を保存する。
   - `deploy-pages` で公開する。
3. `permissions` に `pages: write` と `id-token: write` を入れる。
4. Settings → Pages で Source を **GitHub Actions** にする。
5. push するか、Actions タブから実行する。

## 7. 手動実行の操作

1. リポジトリの **Actions** タブを開く。
2. 左の一覧から **update-and-deploy** を選ぶ。
3. 右上の **Run workflow** を押し、ブランチ `main` のまま緑の **Run workflow** を押す。
4. 実行をクリックして `deploy` ジョブが緑になれば成功。デプロイ URL が表示される。

つまずきやすい点:

- **Run workflow が出ない**: ワークフローのファイルが push されていない、または左で `update-and-deploy` を選んでいない。
- **deploy が失敗する**: Settings → Pages の Source が GitHub Actions になっていない場合がほとんど。
- **build が失敗する**: ログで止まった手順を確認する。`pytest` なら元データの構造変更の可能性がある（HANDOVER.md 9 章）。

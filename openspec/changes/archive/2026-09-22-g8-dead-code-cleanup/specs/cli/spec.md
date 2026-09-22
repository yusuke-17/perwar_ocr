## Purpose

利用者がツールを起動する入口（統合コマンド `prewar` とそのサブコマンド）と、環境確認（`prewar check`）の振る舞いを定める。
入口を1つに保ち、環境確認が「OCR と口語化に本当に必要なもの」だけで合否を判断することを保証する。

## ADDED Requirements

### Requirement: 統合コマンドへの一本化
システムは起動コマンドとして `prewar` だけを提供しなければならない（SHALL）。
OCR・撮りため・検索・索引更新・統計・後処理・差分表示・データ整理・環境確認は、すべて `prewar` のサブコマンドまたは引数なしの対話メニューから実行できなければならない（MUST）。
旧コマンド `prewar-ocr` と `prewar-library` は提供してはならない（MUST NOT）。

#### Scenario: 統合コマンドで OCR を実行する
- **WHEN** 利用者が `uv run prewar ocr input/画像.png` を実行する
- **THEN** 旧字体・カタカナ仮名遣いの公文書画像が OCR・正規化・口語化され、ライブラリに1件の記録として保存される

#### Scenario: 統合コマンドで検索する
- **WHEN** 利用者が `uv run prewar search 震災被害 NOT 大阪府下` を実行する
- **THEN** 「震災被害」を含み「大阪府下」を含まない記録が一覧表示される

#### Scenario: 旧コマンドは存在しない
- **WHEN** 依存を同期した環境で利用者が `uv run prewar-ocr` または `uv run prewar-library` を実行する
- **THEN** コマンドが見つからない旨のエラーになり、OCR や検索は実行されない

#### Scenario: 引数なしで対話メニューを開く
- **WHEN** 利用者が引数なしで `uv run prewar` を実行する
- **THEN** OCR・撮りため・検索・口語体変換・差分表示・データ整理・環境確認を選べるメニューが表示される

### Requirement: 検索構文のヘルプ
システムは `prewar search --help` で検索構文の説明を表示しなければならない（SHALL）。
説明には AND（空白区切り）・OR・NOT による除外・`原文:` / `口語:` / `題名:` による対象の限定・各語に3文字以上が必要であることを含めなければならない（MUST）。

#### Scenario: 検索のヘルプを見る
- **WHEN** 利用者が `uv run prewar search --help` を実行する
- **THEN** AND・OR・NOT・対象の限定の書き方と使用例、および各語は正規化後3文字以上必要という注意が表示される

### Requirement: 環境確認の合否判定
システムは `prewar check` で、OCR と口語化に必須の項目だけを確認して合否を判定しなければならない（SHALL）。
必須の項目は Python のバージョン、必須の依存パッケージ、Ollama への接続、GLM-OCR モデルの有無とする。
すべての必須項目が満たされたときに終了コード 0、1つでも満たされないときに終了コード 1 で終わらなければならない（MUST）。

#### Scenario: 必須項目がすべて揃っている
- **WHEN** Python 3.13 以上で、必須パッケージが入っており、Ollama が起動し GLM-OCR モデルが取得済みの環境で `prewar check` を実行する
- **THEN** 各項目が合格と表示され、終了コード 0 で終わる

#### Scenario: Ollama に接続できない
- **WHEN** Ollama が起動していない環境で `prewar check` を実行する
- **THEN** Ollama 接続が不合格と表示され、GLM-OCR モデルの確認はスキップされ、終了コード 1 で終わる

### Requirement: 任意機能の未導入を失敗扱いしない
システムは、OCR と口語化に使われない任意の機能（Surya OCR）が未導入であっても、環境確認を不合格にしてはならない（MUST NOT）。
任意の機能は導入済みか未導入かを表示し、未導入の場合は導入方法を案内しなければならない（SHALL）。

#### Scenario: Surya OCR が未導入
- **WHEN** 必須項目がすべて揃い、Surya OCR を導入していない環境で `prewar check` を実行する
- **THEN** Surya OCR は「未導入（任意）」と導入方法付きで表示され、終了コード 0 で終わる

#### Scenario: Surya OCR が導入済み
- **WHEN** 必須項目がすべて揃い、Surya OCR を追加導入した環境で `prewar check` を実行する
- **THEN** Surya OCR は導入済みと表示され、終了コード 0 で終わる

### Requirement: 確認する依存パッケージの範囲
システムは環境確認で、OCR・画像前処理・正規化・口語化・対話メニュー・進捗表示に実際に使うパッケージを確認しなければならない（SHALL）。
処理に使わないパッケージの有無で不合格にしてはならない（MUST NOT）。

#### Scenario: 使っていないパッケージが無い
- **WHEN** 必須パッケージはすべて入っているが、処理に使わない画像ライブラリ（Pillow）が入っていない環境で `prewar check` を実行する
- **THEN** 依存パッケージの確認は合格と表示される

#### Scenario: 必須パッケージが欠けている
- **WHEN** 全角正規化に使うパッケージ（jaconv）が入っていない環境で `prewar check` を実行する
- **THEN** そのパッケージが不合格として導入方法付きで表示され、終了コード 1 で終わる

### Requirement: 完全ローカル動作の維持
環境確認は、手元で動く Ollama 以外の外部サービスへ通信してはならない（MUST NOT）。
GLM-OCR の簡易テストで送る内容は固定の確認用文字列に限り、input/ output/ library/ の資料を送ってはならない（MUST NOT）。

#### Scenario: 簡易テストの送信内容
- **WHEN** `prewar check` が GLM-OCR の簡易テストを行う
- **THEN** 手元の Ollama にだけ固定の確認用文字列が送られ、資料の画像や本文は送られない

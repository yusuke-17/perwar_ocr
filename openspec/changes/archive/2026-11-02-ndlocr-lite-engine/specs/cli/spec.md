## MODIFIED Requirements

### Requirement: 環境確認の合否判定
システムは `prewar check` で、OCR と口語化に必須の項目だけを確認して合否を判定しなければならない（SHALL）。
必須の項目は Python のバージョン、必須の依存パッケージ、Ollama への接続（口語化に使う）、選ばれた OCR エンジンの導入とする。
選ばれたエンジンが NDLOCR-Lite なら NDLOCR-Lite の導入（版も表示する）を、Ollama のモデルなら GLM-OCR などそのモデルの有無を必須とし、
選ばれていないエンジンは導入済みか未導入かを表示するだけで合否に数えてはならない（MUST NOT）。
すべての必須項目が満たされたときに終了コード 0、1つでも満たされないときに終了コード 1 で終わらなければならない（MUST）。

#### Scenario: 必須項目がすべて揃っている
- **WHEN** Python 3.13 以上で、必須パッケージが入っており、Ollama が起動し、既定のエンジンの NDLOCR-Lite が導入済みの環境で `prewar check` を実行する
- **THEN** 各項目が合格と表示され、NDLOCR-Lite の版が表示され、終了コード 0 で終わる

#### Scenario: Ollama に接続できない
- **WHEN** Ollama が起動していない環境で `prewar check` を実行する
- **THEN** Ollama 接続が不合格と表示され、GLM-OCR モデルの確認はスキップされ、終了コード 1 で終わる

#### Scenario: 既定のエンジンが導入されていない
- **WHEN** NDLOCR-Lite を導入しておらず、GLM-OCR は取得済みの環境で、既定のエンジンのまま `prewar check` を実行する
- **THEN** NDLOCR-Lite が不合格と導入方法つきで表示され、GLM-OCR は導入済みと表示され、終了コード 1 で終わる

#### Scenario: GLM-OCR を選んでいるときは NDLOCR-Lite を求めない
- **WHEN** 設定ファイルで OCR エンジンを `glm-ocr` にし、NDLOCR-Lite を導入していない環境で `prewar check` を実行する
- **THEN** NDLOCR-Lite は「未導入」と表示されるだけで、GLM-OCR モデルが取得済みなら終了コード 0 で終わる

### Requirement: 確認する依存パッケージの範囲
システムは環境確認で、OCR（NDLOCR-Lite の実行を含む）・画像前処理・正規化・口語化・対話メニュー・進捗表示に実際に使うパッケージを確認しなければならない（SHALL）。
処理に使わないパッケージの有無で不合格にしてはならない（MUST NOT）。

#### Scenario: 使っていないパッケージが無い
- **WHEN** 必須パッケージはすべて入っているが、NDLOCR-Lite の公式の依存のうち画像の OCR に使わない PDF ライブラリ（reportlab）が入っていない環境で `prewar check` を実行する
- **THEN** 依存パッケージの確認は合格と表示される

#### Scenario: 必須パッケージが欠けている
- **WHEN** 全角正規化に使うパッケージ（jaconv）が入っていない環境で `prewar check` を実行する
- **THEN** そのパッケージが不合格として導入方法付きで表示され、終了コード 1 で終わる

#### Scenario: NDLOCR-Lite の実行に要るパッケージが欠けている
- **WHEN** NDLOCR-Lite の推論に使うパッケージ（onnxruntime）が入っていない環境で `prewar check` を実行する
- **THEN** そのパッケージが不合格として導入方法付きで表示され、終了コード 1 で終わる

## REMOVED Requirements

### Requirement: 任意機能の未導入を失敗扱いしない
**Reason**: 唯一の任意機能だった Surya OCR の追加依存（`uv sync --extra surya`）を削除した。比較調査で縦書きに弱く依存が重いとして見送り済み（`survey/ocr-engine-comparison-2026-10.md`）で、処理からは使われておらず、
Pillow を 11 未満に固定するため NDLOCR-Lite に要る Pillow と同じロックファイルで解決できなかった（Python 3.14 では Pillow 10.4.0 の配布物が無い）。
**Migration**: 選ばれていない OCR エンジンを合否に数えない扱いは「環境確認の合否判定」に移した。Surya OCR を使いたい場合は別の仮想環境に入れる。

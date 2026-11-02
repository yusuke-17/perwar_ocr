## Why

現在の OCR エンジン GLM-OCR（Ollama 上の 0.9B VLM）は、本プロジェクトの資料（縦書き・旧字体・カタカナ文語）で全ページ同じ内容を繰り返す。
G12 で切り落としと上限を入れて 1 枚 55 秒 → 14 秒にしたが、反復検知で毎回丸ごと失われるページ（10 枚中 1 枚）は救えず、
カタカナ「ニ」→漢数字「二」、旧字体→新字体、似た字の取り違えといった系統的な誤読も残っている。
国立国会図書館が 2026-02-24 に公開した NDLOCR-Lite（CPU で動く ONNX 版、CC BY 4.0）を手元の 10 枚で試したところ、
**10 枚 9 秒・失敗 0 枚**で、GLM-OCR が 0 字だったページも画像と照合して誤り 4 か所（422 字中）で読めた（`survey/ndlocr-lite-survey.md`）。
完全ローカル・NVIDIA GPU なしという絶対条件も満たすため、メインエンジンを切り替える。
公式の配布物は依存を `==` で固定しており（numpy 2.2.2 など）プロジェクトの numpy 2.4.2 以上と衝突するが、固定を外して
プロジェクトと同じ依存で動かしても 10 枚の結果が完全に一致したので、仮想環境を分けずに組み込む（`survey/ocr-engine-comparison-2026-10.md`）。

## What Changes

- **OCR エンジンを選べるようにし、既定を NDLOCR-Lite にする**: 既存の OCR モデル名の設定（`[models] ocr`）と `--model` で
  `ndlocr-lite`（既定）か Ollama のモデル名（`glm-ocr` など）を選ぶ。GLM-OCR の経路と G12 の反復対策はそのまま残す
- **NDLOCR-Lite のソースを取り込み、プロジェクトの環境で直接動かす**: git submodule で `vendor/ndlocr-lite` に置いて
  v1.3.1 に固定し、公式の `==` 固定は使わずに実行に要る 6 つの依存（onnxruntime・Pillow・PyYAML・lxml・networkx・tqdm）を足す。
  モデルは 1 回だけ読み込み、1 枚約 0.4 秒で読む（公式のパッケージは配布設定の不具合で、インストールすると起動しないため、ソースのまま使う）。
  未導入（ソース未取得・依存不足）と認識中のエラーはページの失敗として分類する
- **NDLOCR-Lite の出力を本文に整える**: 半角空白を除き、縦書きの列（1 列＝1 行）を文としてつなぐ。
  見出しや段落の終わり（短い列）では改行を残す（題名は本文の最初の行から取るため）
- **認識の信頼度が低い行を警告する**: 行ごとの信頼度が閾値（既定 0.7）未満の行があるページは、ページ名と行数を画面に出し、
  記録のメタ情報に残す（起きたときだけ）
- **NDLOCR-Lite には画像前処理をかけない**: 手元の比較で、前処理後の画像は信頼度が下がり、1 枚は 37 字欠けたため。
  前処理（A1）は GLM-OCR を選んだときだけ適用する
- **Surya OCR の追加依存を削除する**（実装中に追加）: `surya-ocr` が Pillow を 11 未満に固定するため、NDLOCR-Lite に要る Pillow と
  同じロックファイルで解決できない（Python 3.14 では Pillow 10.4.0 の配布物が無く、ソースのビルドも失敗する）。Surya は処理から使われておらず、
  比較調査で見送り済み（`survey/ocr-engine-comparison-2026-10.md`）。`uv sync --extra surya`・`prewar check` の Surya の項目・関連する要件を外す
- **環境確認（`prewar check`）を選んだエンジンに合わせる**: NDLOCR-Lite が既定のときは NDLOCR-Lite の導入と版を必須項目にし、
  GLM-OCR モデルは任意項目にする。Ollama 接続は口語化に要るので引き続き必須

**BREAKING**（利用者から見える挙動の変化）: 既定の OCR 結果が変わる（字の読み・改行の位置・空白）。
GLM-OCR を使い続けるには `[models] ocr = "glm-ocr"` か `--model glm-ocr` を指定する。
NDLOCR-Lite のソースを取得していない環境（`git submodule update --init` をしていない）では、既定のまま OCR すると
取得方法つきのエラーになる。`library/` の既存記録には影響しない。

スコープ外:
- 複数エンジンの結果を突き合わせる・低信頼度の行だけ GLM-OCR で読み直す併用（A2 の続きとして別変更）
- 同じ字の重複（「禪禪」型の誤り）の自動修正（正しい重ね字と区別できないため。警告と差分表示で受ける）
- 手書き資料・くずし字への対応（NDLOCR-Lite の手書きは実験的水準、くずし字は対象外）
- NDLOCR-Lite の PDF 入力・GUI、上流のパッケージ化の不具合の修正

## Capabilities

### New Capabilities

- `ocr-engine`: OCR エンジンの選択、NDLOCR-Lite の呼び出しと失敗の分類、NDLOCR-Lite の出力の整形（空白・列の連結）、
  低信頼度行の警告、エンジンごとの画像前処理の適用範囲

### Modified Capabilities

- `ocr-pipeline`: 「OCR 出力の反復の切り落とし」「OCR の生成トークン数の上限」を Ollama 経由のエンジン（GLM-OCR）に限定する。
  「完全ローカル動作の維持」に、NDLOCR-Lite も手元で動かすこと・自動テストが NDLOCR-Lite なしで通ることを加える
- `cli`: 「環境確認の合否判定」の必須項目を、選ばれた OCR エンジンに合わせて変える（NDLOCR-Lite の導入と版／GLM-OCR モデル）。
  「確認する依存パッケージの範囲」に NDLOCR-Lite の実行に要るパッケージを加える（Pillow は使うパッケージになる）。
  Surya OCR のための「任意機能の未導入を失敗扱いしない」を削除する

## Impact

- コード
  - 新規 `utils/ndlocr_client.py`: NDLOCR-Lite の読み込み（モデルは 1 回）と呼び出し、行の整形（純粋関数）、
    `OllamaOCRClient` と同じ `ocr()` / `model` の形で `OCRResult` を返す
  - `scripts/ocr_vision_llm.py`: エンジンに応じたクライアントの生成、NDLOCR-Lite 用の失敗分類、前処理の適用条件、低信頼度の警告表示
  - `utils/ollama_client.py`: `OCRResult` に低信頼度行の情報を追加（既定値つき）
  - `utils/library_writer.py`: メタ情報に低信頼度行の記録（あるときだけ）
  - `utils/config.py` / `config.toml`: `[models] ocr` の既定を `ndlocr-lite` に、`[ndlocr]` セクション（ソースの場所・信頼度の閾値）
  - `scripts/setup_check.py`: エンジンに応じた必須項目、確認する依存パッケージに 5 つを追加
  - 新規 `.gitmodules` と `vendor/ndlocr-lite`（submodule、タグ 1.3.1 に固定）
- 仕様: `openspec/specs/ocr-engine/spec.md`（新規）、`openspec/specs/ocr-pipeline/spec.md`、`openspec/specs/cli/spec.md`
- テスト: 整形の純粋関数（実機の JSON 形を模したもの）、偽のバックエンドによる呼び出しと失敗分類、エンジンの切り替え、環境確認。
  自動テストは NDLOCR-Lite も Ollama も無しで通す。ソースを取得済みの環境でだけ、合成画像で上流との結合を確かめるテストを足す
- ドキュメント: `README.md`（submodule の取得手順・エンジンの切り替え・CC BY 4.0 と DINOv3 ライセンスの出典表示）、`CLAUDE.md`（技術スタック）、`PROGRESS.md`、
  `plan/improvement-ideas.md`
- 依存: `pyproject.toml` に `onnxruntime>=1.23.2`・`pillow`・`pyyaml`・`lxml`・`networkx`・`tqdm` を追加（どれも版の固定なし。
  numpy 2.4.2・onnxruntime 1.31.0 で解決と動作を確認済み）。NDLOCR-Lite 自体はパッケージとして入れない。
  `[project.optional-dependencies]` の `surya` を削除
- 外部送信: なし。NDLOCR-Lite はモデル同梱で実行時に通信しない（コードを確認済み）。submodule の取得時に GitHub から取得するのみ

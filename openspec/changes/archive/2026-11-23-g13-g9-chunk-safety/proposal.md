# Proposal

## Why

口語化の 1 チャンク（既定 2,000 字）は、入力と出力を合わせて Ollama のコンテキスト長（この環境の既定 `num_ctx` = 4096）の 92% を使っている（`survey/batch-slow-failure-survey.md` 2-3）。
LLM が少し長めに訳しただけで上限に達する。そのとき Ollama はエラーを出さず `done_reason=length` で生成を止め、コードはその結果を成功として採用するので、**チャンクの末尾の訳が黙って欠ける**（G13）。

また、G4 で Ollama の呼び出しに 300 秒のタイムアウトが付いた。しかし口語化は、どのチャンクで失敗しても最後のチャンクまで試し続ける。
そのため、Ollama が途中で固まると「300 秒 × 残りのチャンク数」待つことになる（50 チャンクなら約 4 時間。G9）。
どちらも同じファイル（`utils/text_modernizer.py`）の同じループの問題で、「静かに壊れる」G 系の残りとしてまとめて止める。

## What Changes

- **溢れの検知（G13）**: 口語化した 1 チャンクの応答が生成の上限で止まった（`done_reason` が `length`）とき、その結果を採用しない
- **半分に分けて変換し直す（G13）**: 溢れたチャンクを、原文に字を足さない既存の分け方で 2 つに分け、それぞれを変換し直してつなぐ。分けた半分がまた溢れたら、そのチャンクは**変換に失敗したチャンクと同じ扱い**にする（原文のまま残し、画面に理由を出し、`meta.json` の `failed_chunks` に数える）。途中までの訳を採用することはしない
- **コンテキスト長の明示（G13）**: 口語化の生成パラメータ `[llm]` に `num_ctx` を明示するかどうかを、実機で速度とメモリを測ってから決める（既定を 8192 にする方向）。Ollama の既定値は VRAM の量や Ollama の版で変わるため、環境が変わったときに挙動が黙って変わらないようにする
- **連続失敗の打ち切り（G9）**: 新しい設定 `chunk.abort_after_consecutive_failures`（既定 3、0 で無効）。続けてこの数のチャンクが失敗したら、残りのチャンクを LLM に送らずに原文のまま残して口語化を終える。OCR 側の `batch.abort_after_consecutive_failures` と同じ考え方
  - チャンクの中身が原因の失敗（お手本の混入・反復検知・溢れ）は数えない。次のチャンクは成功しうるため（OCR 側で反復を数えないのと同じ）
  - 打ち切りで処理しなかったチャンクも `failed_chunks` に数える。`meta.json` の形は変えない
- **反復検知のメッセージの修正**: `OllamaRepeatError` の文言が「OCRエンジンが…」に固定されていて、口語化で起きたときに誤解を招く。どちらで起きても正しく読める文言にする

## Capabilities

### New Capabilities

（なし）

### Modified Capabilities

- `text-modernization`: 要件を 2 つ追加する。「生成の上限で途切れた断片を分けて変換し直す」と「連続して失敗したら残りを変換せずに打ち切る」

## Impact

- `utils/text_modernizer.py`: LLM の応答から `done_reason` を受け取る、溢れたチャンクを半分に分けて変換し直す、溢れの例外、連続失敗の数え方と打ち切り
- `utils/ollama_client.py`: `OllamaRepeatError` の文言（OCR と口語化の両方で読める形に）
- `utils/config.py`: `_DEFAULTS` の `chunk` に `abort_after_consecutive_failures` を追加。実験の結果しだいで `llm` に `num_ctx` を追加
- `config.toml`: `[chunk]` と `[llm]` のコメントに説明を追加（値は書かない）
- `README.md`: 「途中で失敗・中断したとき」の口語化の項
- テスト: `tests/fakes.py` の `ScriptedChatModernizer` が `done_reason` も返せるようにし、`tests/test_text_modernizer.py`・`tests/test_modernize_resilience.py` で検証する。Ollama は不要
- `prewar ocr` と `prewar fix` の両方に効く（どちらも `modernize_detailed()` を通るため）。呼び出し側・`library_writer.py`・`meta.json` の形は変えない。終了コードは既存の「失敗チャンクがあれば 2」のまま
- 依存の追加なし。検索索引の版は上げない
- 処理時間: 溢れたチャンクだけ LLM の呼び出しが増える（めったに起きない）。Ollama が固まったときの待ち時間は最大で「300 秒 × 3」に収まる

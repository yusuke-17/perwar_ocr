## Context

動機と実測値は `proposal.md` と `survey/batch-slow-failure-survey.md` を参照。設計に効く事実だけを挙げる。

- OCR 呼び出しは `utils/ollama_client.py` の `OllamaOCRClient._call_ollama` の 1 箇所に集約されており、
  生成パラメータは `config.toml` の `[ocr]` セクションがそのまま `options=` に渡る（G4）。
- ページ失敗の分類は `scripts/ocr_vision_llm.py` の `_OCR_ERROR_KINDS`（例外クラス → 理由コード・表示名の表）で行い、
  `_ocr_pages` が連続失敗を数えて `batch.abort_after_consecutive_failures` で打ち切る（G2）。
- Ollama の反復検知は `ollama.ResponseError`（HTTP 500、本文 `prediction aborted, token repeat limit reached`）として
  届く。`ollama_errors()` は「not found」以外の `ResponseError` をそのまま再送出し、現状は理由 `unknown` になる。
- ollama-python の非ストリーミング応答には `done_reason`（`"stop"` / `"length"`）と `eval_count` が含まれる。
  `num_predict` 到達時は `done_reason == "length"` になる（実測）。
- glm-ocr の GGUF は終端トークン（`<|endoftext|>`、`<|user|>`）が正しく登録されている。反復は Ollama 側の
  メタデータ不備ではなく、この資料に対するモデルの挙動なので、クライアント側で受け止めるしかない。
- 実測（`input/1.png`〜`10.png`）: 実内容は 212〜408 字で、必ず出力の冒頭にまとまる。反復は「文字のある同じ行」が
  再び現れる形で始まる。`num_predict=700` で 1 枚 7〜10 秒、反復検知の 500 は 10 枚中 2 枚。

## Goals / Non-Goals

**Goals:**
- 1 ページの OCR 所要時間を、内容量に見合う長さ（10 秒前後）に戻す
- 反復による失敗で成功しうるページを落とさず、バッチを誤って打ち切らない
- 切り落とし・上限到達・再試行のすべてを画面とメタ情報で後から追えるようにする（「静かに壊れない」）
- Ollama の反復検知の仕様がまた変わっても、分類と再試行の部分だけ直せば済む構造にする

**Non-Goals:**
- 口語化側のチャンクや `num_ctx` の調整（別の改善案 G13）
- OCR プロンプトや前処理の変更による反復の抑止（実測で効かない）
- 反復の「原因」をモデル側で直すこと（別エンジン併用 A2 の領域）
- `library/` の既存記録に遡って反復を切り落とすこと（現在 0 件。必要になれば `prewar fix` 側の別変更）

## Decisions

### D1. 反復の切り落としは「同じ行の 2 回目」で切る（純粋関数、`utils/ollama_client.py`）

- 判定単位は行。前後の空白を除いた文字のある行を集合に入れ、既出の行が現れた位置で切る。空行は判定に使わない。
- 置き場所は `OllamaOCRClient.ocr()` の直後ではなく、`_call_ollama` の結果に対して `ocr()` が適用する。
  `OCRResult` に `trimmed_chars: int`（切り落とした字数、0 なら無し）と `hit_limit: bool`（上限到達）を追加し、
  呼び出し側（`_run_ocr_page`）は結果を見て警告を出すだけにする。
- 代替案（見送り）:
  - n-gram やトークン列での反復検知: 実測の反復は行単位で揃っており、行の集合で十分。複雑にしない。
  - 「同じ行が k 回以上」で切る: 2 回目で切っても実内容は失われない（実測）。k を増やすと反復が長く残る。
  - 切り落とさずに警告だけ: 口語化のチャンク数と few-shot 例文の混入が直らない。
- 「同上」のような正当な繰り返しを誤って切る可能性は仕様の Scenario で明示し、警告と `ocr_raw` の記録で受ける
  （D4）。本プロジェクトの資料は文語の長文が主で、同じ行が正当に 2 回現れる頻度は低いと判断した。

### D2. `num_predict` は `[ocr]` セクションの通常の生成パラメータとして持つ（既定 1024）

- `_DEFAULTS["ocr"]["num_predict"] = 1024`。`ocr_options()` は 0 以下なら `num_predict` を外して渡す
  （Ollama の `-1` は「無制限」、`-2` は「コンテキストを埋める」で、0 の意味が曖昧なため、本プロジェクトでは
  「0 で無制限」を timeout と同じ流儀に揃え、渡さないことで無制限にする）。
- 1024 の根拠: 実測の最長ページ 410 字（≒ 450 トークン）の 2 倍以上。1 枚 10〜14 秒。
  本文が長い資料で上限に当たっても、D3 の警告で気づける。
- `config.toml` のコメント「num_predict は書かないこと。長いページの後半が無言で欠ける」は、
  「上限に達すると警告が出る。長いページで警告が出たら値を増やす」に書き換える。
- 代替案（見送り）: `num_ctx` を広げる → 反復が倍長く続くだけ（実測 117 秒）。`stop` 文字列 → 効かない（実測）。

### D3. 上限到達は `done_reason == "length"` で検知し、失敗ではなく警告にする

- `_call_ollama` が `response.done_reason` を返し、`OCRResult.hit_limit` に入れる。
- `_run_ocr_page` は `hit_limit` なら「⚠ 生成上限（N トークン）に達しました。後半が欠けている可能性があります。
  `[ocr] num_predict` を増やすと改善することがあります」を表示する。反復で切り落とされたページでは
  反復の警告も同時に出るので、「反復で止まった」と「本当に長い」を利用者が区別できる
  （切り落とし無し＋上限到達 ＝ 本当に長いページ）。
- 代替案（見送り）: 上限到達を失敗にして再試行 → 反復ページは何度やっても上限に当たるので無駄。

### D4. メタ情報の記録形式

- `meta.json` の `ocr` セクションに `repetition_trimmed: {"<index>": <chars>, ...}` を、切り落としが 1 件でもあるときだけ出す
  （キーは 1 始まりのページ番号の文字列。JSON のキーは文字列のため）。全ページ 0 なら出さない（既存の
  「正常時はキーを出さない」流儀に合わせる）。
- 上限到達は `ocr.hit_limit_pages: [<index>, ...]` を同様に「あるときだけ」出す。
- `ocr_raw.txt` には**切り落とした後**のテキストを保存する。切り落とし前の全文は保存しない。
  理由: 反復部分は資料の情報を含まず、検索索引（G5 は `ocr_raw.txt` を正規化して索引する）を汚すだけ。
  「文字を消さない」原則との関係は、メタ情報に字数を残して「消したこと」を追えるようにすることで満たす。
- `MetaPageFailure.reason` の候補に `"repeat"` を追加し、コメントの一覧も更新する。

### D5. 反復エラーの分類は `ollama_errors()` で例外に翻訳する

- `utils/ollama_client.py` に `OllamaRepeatError(Exception)` を追加。`ollama_errors()` の `except ollama.ResponseError` で、
  メッセージに `"repeat"` を含み status 500 のものをこの例外に翻訳する（Ollama の文言は
  `prediction aborted, token repeat limit reached`。将来文言が変わったら判定文字列だけ直す）。
- `_OCR_ERROR_KINDS` に `(OllamaRepeatError, "repeat", "反復による打ち切り")` を追加。
- 口語化側（`text_modernizer.py`）も同じ `ollama_errors()` を通るので、qwen が反復したときも
  `OllamaRepeatError` になり、既存の `keep_original`（原文のまま採用）に乗る。口語化側の再試行は本変更では行わない。

### D6. 再試行はシードを変えて `OllamaOCRClient.ocr()` の中で行う

- `_DEFAULTS["ocr"]["retry_on_repeat"] = 1`。`ocr_options()` が `options=` に渡すキーからは除外する
  （`[ocr]` は「Ollama の options として意味のあるキー以外を足さない」規約なので、`retry_on_repeat` は
  `ocr_options()` が取り出して捨て、`ocr_retry_count()` のような別の読み出し口から取る。`config.toml` の
  コメントで「このキーだけは生成パラメータではない」と明記する）。
- 再試行時は `seed` を `seed + 試行回数` にして渡す（`seed` 未指定なら試行回数をそのまま使う）。
  temperature=0 でもシードが変わると反復の形が変わり、反復検知を抜けることを期待する。
  **効果は未計測**なので、実装時に `input/3.png` / `5.png`（実測で 500 になった 2 枚）で確かめ、
  効かなければ既定を 0 に下げて仕様の「既定値は 1」を改める（tasks 6.2）。
- 再試行の有無・回数は `OCRResult` に `attempts: int` として残し、メタ情報には出さない（成功したページの再試行回数は
  運用上の価値が低く、meta.json を増やさない）。画面には「反復で打ち切られたため再試行します（2/2）」を出す。
- 連続失敗カウントからの除外: `_ocr_pages` で `page.reason == "repeat"` のときは `consecutive` を増やさない
  （リセットもしない。反復失敗 → 接続失敗 ×3 の並びで打ち切られる挙動は維持する）。
- 代替案（見送り）: `_ocr_pages` 側で再試行する → 再試行の都度 `_run_ocr_page` のスピナーと表示が二重になる。
  クライアント内で閉じる方が `OCRResult.elapsed_seconds` に再試行分の時間も自然に含まれる。

### D7. `prewar check` の Ollama バージョン表示

- `list_client()` と同じ短い timeout で `/api/version` を呼ぶ（ollama-python の `Client` には専用メソッドが無いため、
  `Client._request_raw("GET", "/api/version")` か `httpx` で直接叩く。既存の `list_timeout()` を流用）。
- 取得できなければ「不明」と表示し、合否には影響させない。

### D8. テストの方針

- 反復の切り落としは純粋関数として `tests/test_ollama_options.py`（または新設 `tests/test_ocr_repetition.py`）で
  仕様の 4 Scenario をそのまま表にして確認する。
- 上限到達・再試行・分類は `tests/fakes.py` の偽クライアントに `done_reason` と「n 回目まで `OllamaRepeatError`」の
  振る舞いを足して `tests/test_ocr_batch.py` で確認する。
- 実機確認（tasks 6.x）は `input/1.png`〜`10.png` で行い、1 枚あたりの所要時間と失敗数を survey の表と比べる。

## Risks / Trade-offs

- [正当な繰り返し行を切り落とす] → 仕様で明示し、警告とメタ情報の字数で気づけるようにする。頻度が問題になれば
  「同じ行が k 回連続」など条件を厳しくする（D1 の k は後から変えられる構造にしておく）
- [`num_predict` 既定 1024 で本当に長いページの後半が欠ける] → 上限到達の警告（D3）と `[ocr] num_predict` の
  増やし方を README に書く。切り落とし無し＋上限到達の組み合わせで「本当に長い」と判別できる
- [シード変更の再試行が効かない] → tasks 6.2 で実測し、効かなければ既定 0。その場合でも分類と「打ち切りに数えない」は
  単独で価値がある（誤った打ち切りを防ぐ）
- [Ollama の反復検知の文言・ステータスが将来変わる] → 判定は `ollama_errors()` の 1 箇所。`prewar check` のバージョン表示で
  変化に気づける
- [口語化側で `OllamaRepeatError` が増えても再試行しない] → 既存の `keep_original` で本文は欠けない。反復入りの
  入力が減れば発生自体が減る見込み

## Migration Plan

- 設定の追加のみで、既存の `config.toml` はそのまま動く（`num_predict` 1024・`retry_on_repeat` 1 が既定で効く）。
- 従来挙動に戻すには `[ocr] num_predict = 0`、`retry_on_repeat = 0` を書く。切り落としを止める設定は設けない
  （止める理由が無く、設定を増やさない）。必要になれば `ocr.trim_repetition` を後から足せる。
- `meta.json` に新しいキーが増えるのは「あるときだけ」なので、検索索引（`library_search`）の署名や
  スキーマ版には影響しない。

## Open Questions

- 反復の切り落としを `prewar fix`（既存テキストの後処理）にも載せるか。現在 `library/` が 0 件なので急がないが、
  載せるなら `ocr_raw.txt` を書き換えることになり、G6 の mtime 署名で再索引が走る点を確認してから決める。

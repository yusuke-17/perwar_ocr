# Tasks

## 1. 前提の確認（実機の実験。コードは変えない）

- [x] 1.1 qwen3.5:9b が生成の上限で止まり `done_reason=length` を返すことを確かめる（design D1 の前提）。使い捨てのスクリプトを scratchpad に置き、`TextModernizer._build_messages` と同じメッセージで、手元の資料の 2,000 字のチャンクを `num_ctx` を小さく（例: 2,600）して変換する。`done_reason` が `length` になり、出力が途中で途切れていること（context shift で生成が続いていないこと）を確認する。`length` が返らなければ、ここで止めて design D1・D2 を見直す
- [x] 1.2 `num_ctx` の 4096 と 8192 を比べる（design D5）。同じチャンクをそれぞれ 3 回変換し、2 回目以降の時間と `ollama ps` のメモリを記録する。遅くなるのが 1 割以内でメモリに余裕があれば 8192 を既定にすると決め、design D5 と Open Questions に結果と決定を書き込む
- [x] 1.3 1.1・1.2 の確かめ方と結果（数値だけ。資料の本文は書かない）を `survey/batch-slow-failure-survey.md` の 2-3 の後ろに追記する。Ollama が更新されたときに繰り返せるよう、Ollama の版と手順を書く。使い捨てのスクリプトと出力は消す

## 2. 溢れの検知と半分に分けた変換し直し（`utils/text_modernizer.py`・`tests/fakes.py`）

- [x] 2.1 `_chat()` が本文と `done_reason` を返すようにし、`tests/fakes.py` の `ScriptedChatModernizer` の応答の列に「文字列（`stop` とみなす）」「(文字列, done_reason)」「例外（投げる）」を書けるようにする（design D7）。既存の `tests/test_text_modernizer.py`・`tests/test_modernize_resilience.py`・`tests/test_ocr_pipeline.py` が無修正で通ることを確認する
- [x] 2.2 断片を 2 つに分ける純粋関数 `_split_in_half` を実装する（design D2: 真ん中にいちばん近い「。」の直後、無ければ「、」か改行、それも無ければ字数の真ん中）。`tests/test_text_modernizer.py` で、2 つをつなぐと元と一字も違わないこと、旧字体・カタカナ文語の文で「。」の直後で切れること、「。」で終わらない文や句読点の無い文でも字を足さずに 2 つになることを確認する
- [x] 2.3 `ChunkOverflowError` を足し、`_modernize_chunk` を design D2 の流れにする（溢れの判定を混入の判定より先に行う・分けるのは 1 回だけ・片方でも溢れたら断片全体を失敗にする・分けた半分にも混入の判定と変換し直しをかける）。画面に「分けて変換し直す」行を出す。`ScriptedChatModernizer` で、仕様の Scenario「分けて変換し直すと収まる」（途中で途切れた最初の訳が入らない・半分ずつの訳が改行 1 つでつながる・`failures` が空・`_chat` が 3 回）、「分けても途切れる」（原文のまま・`failures` が 1 件で理由に生成の上限）、「分けても原文に字を足さない」、「中止の方針」（`on_error="abort"` で例外が伝わる）を確認する。お手本なしで変換し直した結果が溢れたときも分けることを確認する
- [x] 2.4 1.2 の決定に従い、8192 にするなら `_DEFAULTS["llm"]` に `num_ctx` を足し、`CONFIG.get("llm")` に入ることを確認する。どちらの場合も `config.toml` の `[llm]` のコメントに `num_ctx` の説明（Ollama の既定は環境で変わる・消すと Ollama の既定に戻る）と、`[chunk]` の `size` に「大きくしすぎると入力が `num_ctx` を超え、お手本が黙って落ちる」注意を足す（値は書かない）
- [x] 2.5 `README.md` の「途中で失敗・中断したとき」の口語体変換の項に、訳が生成の上限で途切れたら半分に分けて変換し直し、それでも途切れたらそのチャンクを原文のまま残すことを書く

## 3. 連続失敗の打ち切り（`utils/text_modernizer.py`・`utils/config.py`・`config.toml`）

- [x] 3.1 `_DEFAULTS["chunk"]` に `abort_after_consecutive_failures = 3` を足し、`TextModernizer` の引数で差し替えられるようにする。`config.toml` の `[chunk]` のコメントに説明を足す（値は書かない。0 で無効）。`CONFIG.get("chunk.abort_after_consecutive_failures")` が 3 を返すことを確認する
- [x] 3.2 `modernize_detailed()` のループに連続失敗の数え方と打ち切りを入れる（design D3: `FewShotLeakError`・`OllamaRepeatError`・`ChunkOverflowError` は数えず戻しもしない、成功で 0 に戻す。design D4: 残りは原文のまま・断片ごとに `ChunkFailure` を足す・画面には打ち切りの行を 1 行・`aborted` は立てない）。`tests/test_modernize_resilience.py` で、仕様の 5 つの Scenario（固まって続けて失敗する・成功を挟めば打ち切らない・中身が原因の失敗は数えない・数えない失敗を挟んでも連続は続く・打ち切りを無効にする）を、LLM に送った回数と `failures` の数で確認する。既存の失敗耐性のテスト（全チャンク失敗など）が無修正で通ることを確認する
- [x] 3.3 `tests/test_ocr_pipeline.py` の既存の口語化の経路で、打ち切ったときに `meta.json` の `failed_chunks` が「失敗＋未処理」の数になり、`error` のキーが足されず、終了コードが 2 になることを確認する
- [x] 3.4 `README.md` の「途中で失敗・中断したとき」に、口語化でも連続 3 回失敗したら残りのチャンクを原文のまま残して打ち切ること（`chunk.abort_after_consecutive_failures` で変更可・0 で無効）、反復・溢れ・お手本の混入は数えないことを書く。書いた設定名と既定値が `_DEFAULTS` と一致することを確認する

## 4. 反復検知の文言（`utils/ollama_client.py`）

- [x] 4.1 `OllamaRepeatError` の文言を、主語をモデルにしてモデル名を入れた形にする（design D6）。`tests/test_ollama_options.py` の反復の分類のテストが通り、OCR 側の `reason: "repeat"` の分類が変わらないことを確認する。文言にモデル名が入ることをテストで確認する

## 5. 全体の確認

- [x] 5.1 `uv run pytest tests/ pkg/` が全件通ることを確認する（Ollama と NDLOCR-Lite が無くても通ること）
- [x] 5.2 `input/1.png`〜`10.png` をフォルダ指定で 1 件の記録として処理し（試験用の `--library-root`）、口語化が従来どおり最後まで終わること・溢れの行が出ないこと（出たら分けて変換し直した結果を目で確かめる）・1 チャンクあたりの時間が 1.2 の計測と大きく違わないことを確認する
- [x] 5.3 同じ処理を口語化の途中で Ollama.app を終了させて行い、連続 3 回失敗した時点で打ち切りの行が出て残りのチャンクが LLM に送られないこと、記録が保存され `meta.json` の `failed_chunks` が「失敗＋未処理」の数になり、終了コードが 2 になることを確認する。5.2・5.3 の試験用の記録は確認後に消す
- [x] 5.4 `PROGRESS.md` の「直近の作業」と、`plan/improvement-ideas.md` の G13・G9 を実装済みに更新する

## 6. レビュー指摘の修正（2026-11-23 の `/code-review`）

- [x] 6.1 `_DEFAULTS["llm"]` に `num_predict = 3072` を足し、`llm_options()` で `num_ctx`・`num_predict` を `int()` に直し、0 以下なら渡さないようにする。`ocr_options()` の `num_predict` も `int()` に直す（design D5）。`config.toml` の `[llm]` にコメントを足す。`tests/test_ollama_options.py` で、既定で 3072 が渡ること・0 以下なら渡らないこと・文字列の `"8192"` が整数で渡ることを確認する
- [x] 6.2 分けた 2 つの訳のつなぎ方を「切れ目に改行があったときだけ改行 1 つ、それ以外は何も挟まない」にし、空白だけの半分は LLM に送らずそのまま残す（design D2）。`tests/test_text_modernizer.py` で、「。」で切ったときに改行が入らないこと・改行で切ったときは改行 1 つになること・空白だけの半分が送られないことを確認する
- [x] 6.3 お手本なしで変換し直した訳が溢れたら、半分もお手本なしで送り判定しないようにする（design D2）。`ScriptedChatModernizer` で、そのときの送信が 4 回で、3・4 回目にお手本が無いことを確認する
- [x] 6.4 `num_predict` を小さく（例: 200）して実際のチャンクを qwen3.5:9b に送り、`done_reason=length` で止まることを実機で確かめる（使い捨てのスクリプトは scratchpad に置き、確認後に消す。数値だけを `survey/batch-slow-failure-survey.md` 2-4 に追記する）
- [x] 6.5 `uv run pytest tests/ pkg/` が全件通ることを確認し、`PROGRESS.md` の「直近の作業」にレビュー指摘の修正を書き足す

## Workflow follow-up

- レビューを受けてコミットし、PR で `main` にマージする
- `/opsx:archive` で `text-modernization` の追加要件を本体の仕様に統合する

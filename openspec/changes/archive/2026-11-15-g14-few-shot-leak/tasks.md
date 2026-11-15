# Tasks

## 1. 混入の判定（`utils/text_modernizer.py`）

- [x] 1.1 `LeakMarker`（`output_terms`・`source_terms` を持つ dataclass）と、`FEW_SHOT_EXAMPLES` の各例の `"leak_markers"` を design D1 の表どおりに足す。`_build_messages` が組み立てるメッセージが変更前と同じ（`input` / `output` だけを使う）ことを `tests/test_text_modernizer.py` で確認する
- [x] 1.2 原文のチャンクと変換結果を受け取り、混入と判定した目印の組（無ければ `None`）を返す純粋関数を実装する（design D1: 出力側の語がすべて結果にあり、原文側の語が 1 つも原文に無ければ混入）。`tests/test_text_modernizer.py` で、仕様の Scenario「原文が実際に引用している」（原文「其ノ流祖ハ常陸國ノ人ニシテ…」と結果「常陸国」で混入としない）と「一般的な言い回しが片方だけ出る」（原文「租税ヲ納ムルハ國民ノ義務ナリ。」と結果「税金を納める義務」だけで混入としない）、2026-11-03 に実際に混入した「その流派の開祖は常陸国の出身で…」を混入と判定することを確認する
- [x] 1.3 design D4 の整合のテストを足す。各お手本が目印を 1 組以上持つこと、その `output` を無関係なカタカナ文語の原文（「陸軍省ハ左記ノ通リ通牒ス。」）の結果とみなすと混入になること、その `input` を原文とみなすと混入にならないことを、全お手本についてパラメータ化して確認する

## 2. お手本なしでの変換し直しと原文のまま残す処理（`utils/text_modernizer.py`・`utils/config.py`・`config.toml`）

- [x] 2.1 `_DEFAULTS["chunk"]` に `retry_without_examples = True` を足し、`config.toml` の `[chunk]` のコメントに `on_error` と `retry_without_examples` の説明を足す（値は書かない）。`CONFIG.get("chunk.retry_without_examples")` が True を返すことを確認する（当初は回数の設定 `retry_on_leak` だったが、レビューを受けて真偽値に改めた。design D2）
- [x] 2.2 `FewShotLeakError` を足し、`_build_messages` にお手本を外す指定を足す。`_modernize_chunk` を「お手本つきで `_chat` を呼び、混入していたら画面に 1 行出して、お手本なしのメッセージで 1 回変換し直した結果を判定せずに返す。`retry_without_examples` が False なら判定に使った語を含むメッセージで `FewShotLeakError` を投げる」形にする（design D2・D3）。`TextModernizer` の引数で差し替えられるようにする。`tests/fakes.py` の `ScriptedChatModernizer`（応答の列を返し、送ったメッセージを記録する）で、仕様の Scenario「お手本つきの結果に混入する」（2 回目のメッセージにお手本が無い・その結果が入る・`failures` が空・`_chat` が 2 回）と「引用が断片の境目で切れている」（お手本なしの結果は判定せずに採用）を確認する。混入が無いチャンクのメッセージが変更前と同じ（お手本つき・1 回）であることも確認する
- [x] 2.3 `tests/test_modernize_resilience.py` と `tests/test_text_modernizer.py` で、仕様の Scenario「変換し直さない」（その断片が旧字体・カタカナの原文のまま残り、ほかの断片は変換され、`failures` が 1 件でメッセージにお手本の混入と書かれる）と「中止の方針」（`on_error="abort"` で `FewShotLeakError` が呼び出し元に伝わる）を確認する。あわせて、変換し直しの途中の `KeyboardInterrupt` が既存の中断処理（`aborted=True`、残りは原文）に届くことと、既存の失敗耐性のテストが無修正で通ることを確認する
- [x] 2.4 `tests/test_ocr_pipeline.py` の既存の口語化の経路で、変換し直さない設定で混入したチャンクが `meta.json` の `failed_chunks` に数えられ、お手本なしで変換し直したときは `meta.json` の `modernize` にキーが増えないことを確認する（仕様の 2 つの要件の `meta.json` の部分）
- [x] 2.5 `README.md` の「途中で失敗・中断したとき」の口語体変換の項に、お手本の混入を見つけたらお手本なしで変換し直すこと、`config.toml` の `chunk.retry_without_examples = false` ならそのチャンクを原文のまま残すことを書く。書いた設定名と既定値が `_DEFAULTS` と一致することを確認する

## 3. 全体の確認

- [x] 3.1 `uv run pytest tests/ pkg/` が全件通ることを確認する（Ollama と NDLOCR-Lite が無くても通ること）
- [x] 3.2 `input/1.png`〜`10.png` をフォルダ指定で 1 件の記録として処理し（試験用の `--library-root`）、これを 3 回繰り返す。各回で、画面の混入の検出の行と、お手本なしの変換で混入が消えたか、`meta.json` に `failed_chunks` が無いかを確認する。2 つ目のチャンクの訳の冒頭にお手本の例 2 の訳（「その流派の創始者は常陸国の出身で…」の形）が付いていないことを目で確かめ、`modern.txt` の「常陸」「心影流」の数が 1 つ目のチャンクの原文にある数（各 2・1）を超えないことを `grep -o` で確認する（資料の本文はリポジトリに書かない）
- [x] 3.3 `PROGRESS.md` の「直近の作業」と、`plan/improvement-ideas.md` の G14 を実装済みに更新する。3.2 の結果を踏まえ、お手本の例 2 を資料と重ならない話題に差し替えて最初の変換の混入を減らす案を改善案として残す

## Workflow follow-up

- レビューを受けてコミットし、PR で `main` にマージする
- `/opsx:archive` で `text-modernization` の追加要件を本体の仕様に統合する

## 1. テストの下準備（挙動不変）

- [x] 1.1 `tests/fakes.py` を新設し、`tests/test_ocr_batch.py` の `_FakeClient` と `_StubModernizer` を移設する（公開名は先頭の `_` を外す）。`test_ocr_batch.py` は `from fakes import ...` に置き換え、`uv run pytest tests/ pkg/ -q` と `uv run pytest tests/test_ocr_batch.py -q` の両方で既存テストが全件通ることを確認する
- [x] 1.2 `tests/fakes.py` に、入力の先頭に `口語:` を付けて `ModernizeResult` を返す口語化フェイクを追加する（動作は 2.2 以降のテストで保存された口語化テキストに `口語:` が付くことで確認される）
- [x] 1.3 `scripts/ocr_vision_llm.py` の `process_single` / `process_batch` / `process_folder` にキーワード専用引数 `client=None, modernizer=None` を追加し、`None` のときだけ本番の実体を作る。`process_folder` は受け取った値を下位へ渡す。既存テストが全件通ることを確認する

## 2. 特性テスト（現行コードに対して書く）

- [x] 2.1 `tests/test_ocr_pipeline.py` を新設し、`scripts.cli._defaults_for(ocr_vision_llm.add_arguments)` を元に `no_preprocess=True`・`library_root`・`output` を `tmp_path` 配下へ上書きする引数生成ヘルパーと、空バイトの画像を置くヘルパーを用意する
- [x] 2.2 1枚処理のテストを書き通す: 成功で終了コード 0・元画像1ファイル／OCR 生テキスト／口語化テキスト／メタ情報が作られメタに `pages` が無い、OCR 失敗で 1・記録なし
- [x] 2.3 1枚処理のオプションのテストを書き通す: 保存省略で記録も旧形式出力も無い、正規化省略でメタの正規化項目が無効かつ本文に旧字体（「關東」）が残る、正規化ありで「関東」になる、口語化省略で 0・メタの口語化が無効・口語化テキストが正規化テキスト、旧形式出力で `{stem}_modern.txt`
- [x] 2.4 1枚処理の口語化失敗のテストを書き通す: 口語化フェイクが例外を投げると終了コード 2、口語化テキストが正規化テキスト、メタに失敗理由
- [x] 2.5 複数枚処理のテストを書き通す: 3枚成功で 0・連番の元画像・OCR 所要時間が合計、2枚目失敗で 2・成功2枚が元の順に連番保存・メタに総数 3／成功 2、全失敗で 1・記録なし、旧形式出力で `{先頭}-{末尾}_modern.txt`
- [x] 2.6 フォルダ処理のテストを書き通す: 画像なしで 1、既定は全画像で1記録、画像ごとの別記録で全成功 0／1枚失敗 2（記録2件・失敗画像名が表示される）／全失敗 1
- [x] 2.7 同じ入力の1枚処理が作るメタ情報から作成日時など時刻の項目を除いた辞書を、期待値としてテスト内に固定する（リファクタ前後の同一性の基準）

## 3. 統合CLIのテスト

- [x] 3.1 `tests/test_cli.py` を新設し、`build_parser()` で ocr / shoot / search / index / stat / fix / diff / clean / check の各サブコマンドを解析したとき `func` が期待する関数を指すことをテストで確認する
- [x] 3.2 `_defaults_for(ocr_vision_llm.add_arguments)` の結果が、OCR 処理で参照する全属性（`no_preprocess`, `binarize`, `no_normalize`, `no_modernize`, `no_save`, `legacy_output`, `library_root`, `output`, `model`, `prompt`, `on_page_error`, `separate`, `no_run`）を持つことをテストで確認する
- [x] 3.3 `--on-page-error` と `--binarize` が不正値を拒否し、正しい値を受け付けることをテストで確認する
- [x] 3.4 `_run_shoot` が `args.image` を `"shoot"` にして OCR 処理へ渡すことをテストで確認する（`monkeypatch` で `ocr_vision_llm.run` を受け取った引数を記録する関数に差し替える）
- [x] 3.5 ここまでの全テストが通る状態でコミットする（`uv run pytest tests/ pkg/ -q` 全件成功）

## 4. パイプラインの一本化

- [x] 4.1 `process_batch` の本体を、正規化段階・口語化結果の表示・記録の組み立て（純粋関数）・保存・終了コード判定（純粋関数）に分割する。2 と 3 のテストが無修正で全件通ることを確認する
- [x] 4.2 `_save_legacy`（1枚用）を削除して `_save_legacy_batch` を `_save_legacy` に改名し、2.3 と 2.5 の旧形式出力テストが無修正で通ることを確認する
- [x] 4.3 `process_single` の本体を `process_batch(args, [image_path], client=client, modernizer=modernizer)` への委譲に置き換える。2 のテスト（2.7 の期待値比較を含む）が無修正で全件通ることを確認する
- [x] 4.4 「処理モード: 複数画像」の見出しを2枚以上のときだけ表示するようにし、1枚処理の出力に含まれないことを `capsys` のテストで確認する
- [x] 4.5 1枚処理の OCR 失敗時に、失敗した画像名と再試行のコマンド例が表示されることを `capsys` のテストで確認する
- [x] 4.6 記録の組み立てと終了コード判定の純粋関数に単体テストを追加する（組み立て: OCR メタの合計・先頭ページのモデル名・正規化フラグ・失敗ページの受け渡し／判定: 失敗なし 0、失敗ページあり 2、口語化エラー 2、失敗チャンク 2）
- [x] 4.7 `process_single` と `process_batch` から正規化〜保存の重複記述が消えたことを差分で確認し、全テストが通る状態でコミットする

## 5. 実機確認とドキュメント

- [x] 5.1 Ollama 起動状態で `uv run prewar ocr <画像1枚>`、`uv run prewar ocr <フォルダ>/`、`uv run prewar ocr <フォルダ>/ --separate` を実行し、終了コードと library の記録がリファクタ前と同じ構成であることを確認する
- [x] 5.2 Ollama 停止状態で `uv run prewar ocr <画像1枚>` を実行し、終了コード 1 と失敗のまとめ・再試行の案内が表示されることを確認する
- [x] 5.3 `plan/improvement-ideas.md` の G7 と E1 を完了扱いにし（古い行番号と「テストは皆無」の記述を修正）、優先順位リストを更新する
- [x] 5.4 `PROGRESS.md` の直近の作業・履歴表・テスト件数・次の候補を更新する
- [x] 5.5 `openspec validate unify-ocr-pipeline --strict` が通ることを確認する

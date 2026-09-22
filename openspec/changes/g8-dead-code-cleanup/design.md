## Context

動機は proposal.md の Why、削除対象の根拠（grep 結果・行番号・サイズ実測）は `survey/g8-dead-code-survey.md` を参照。

設計に効く現状は次のとおり。

- 統合CLI `scripts/cli.py` は各スクリプトの `add_arguments` と `run` / `cmd_*` を直接呼んでいる。旧コマンド専用なのは各スクリプトの `parse_args` / `main` / `__main__` ブロックと、`library.py` の `add_arguments`・`run` だけ。
- `prewar check` は `scripts/setup_check.py` の `main()` が5項目を順に確認し、全項目の真偽をそのまま合否に使う。Surya の確認は `from surya.recognition import ...` で torch ごと読み込むため数秒かかる。
- 設定は `_DEFAULTS` に `config.toml` を deep merge する方式で、未知のキーは黙って無視される。
- `uv sync` は既定で lock に無いパッケージを `.venv` から取り除く（exact sync）。

## Goals / Non-Goals

**Goals:**
- OCR・正規化・口語化・保存・検索の出力を一切変えずに、不要物を取り除く
- 通常の `uv sync` で torch 等が入らない状態にする
- 旧コマンドを消しても、旧ヘルプにしか無かった情報（検索構文）を失わない

**Non-Goals:**
- `chunk.overlap` を実装してチャンク間に文脈を渡すこと（削除を選ぶ。理由は D5）
- `raw_response` の中身（トークン数・所要時間）を meta.json に保存する新機能
- Surya を使った OCR 経路の実装（A2 の範囲）
- `survey/` 配下の過去レポートの書き換え（日付付きの調査記録として残す）
- `pkg/senzen_word/` のコード変更（README の修正のみ）

## Decisions

### D1. Surya は削除せず extra `surya` に移す
`[project.optional-dependencies]` に `surya = ["surya-ocr>=0.17.1"]` を置き、必要な人だけ `uv sync --extra surya` で入れる。

- 代替案「完全に削除」: A2（複数エンジン比較）で使う予定が残っているため見送る。
- 代替案「`[dependency-groups]` に入れる」: dependency-groups は開発用ツール（pytest 等）の置き場で、実行時機能の置き場としては意味がずれるため見送る。
- 依存の変更は `uv remove requests pillow surya-ocr` と `uv add --optional surya "surya-ocr>=0.17.1"` で行い、他パッケージのロック済みバージョンを動かさない。

### D2. Surya の確認は import せず有無だけ見る
`importlib.util.find_spec("surya")` で導入の有無だけを判定する。torch を読み込まないので `prewar check` が速くなり、未使用 import の警告も消える。
結果は「導入済み」か「未導入（任意）＋ `uv sync --extra surya` の案内」の2通りにする。従来の「import 時の警告」分岐は無くなる。

`main()` の集計は必須項目と任意項目を分け、終了コードは必須項目だけで決める。サマリー表示では任意項目を「✓ / −（未導入・任意）」で出し、✗ は使わない。

- 代替案「Surya の項目ごと消す」: 導入したのに入っていない、を確かめる手段が無くなるため見送る。

### D3. 依存パッケージ確認の一覧を実使用に合わせる
確認対象を、コードが実際に import する必須依存にそろえる。

| import 名 | パッケージ名 | 用途 |
|---|---|---|
| ollama | ollama | OCR・口語化 |
| httpx | httpx | タイムアウト例外の捕捉 |
| cv2 | opencv-python-headless | 画像前処理 |
| numpy | numpy | 画像前処理 |
| jaconv | jaconv | 全角正規化 |
| senzen_word | senzen-word | 旧字体・仮名変換 |
| questionary | questionary | 対話メニュー |
| rich | rich | 進捗表示 |

Pillow は外す。欠けていたときの案内は `uv add` ではなく `uv sync` にする（宣言済みの依存が入っていないだけなので、追加ではなく同期が正しい対処）。

### D4. 旧コマンドの削除範囲
- `pyproject.toml` の `[project.scripts]` から `prewar-ocr` と `prewar-library` を消し、`prewar` だけを残す。
- `ocr_vision_llm.py`・`library.py`・`postprocess.py` から `parse_args` / `main` / `if __name__ == "__main__"` を消す。`library.py` の `add_arguments`（サブパーサ構築）と `run`（command 分岐）も消す。
- `setup_check.py` の `main()` は対話メニューが呼ぶので残し、`if __name__` ブロックだけ消す。`cli.py` 自身の `__main__` ブロックは残す。
- 各スクリプト冒頭の docstring と `cli.py` のコメントにある旧コマンドの使用例は、`prewar` のサブコマンドに書き換える。

### D5. `chunk.overlap` は実装せず削除する
`_split_text` は文の境界で切って chunk_size まで詰める方式で、文の途中で切れることが無い。重なりを実装すると、同じ文が2つのチャンクで口語化されて出力が重複し、重複を取り除く突き合わせ処理が新たに必要になる。効果に対して複雑さとリスクが大きい。

`_DEFAULTS`・`config.toml` のコメント・`TextModernizer.__init__` の引数と属性・`DEFAULT_CHUNK_OVERLAP` を消す。利用者の `config.toml` に `overlap = 200` が残っていても、未知のキーとして無視されるだけで、今と同じく何も起きない。

### D6. 検索構文のヘルプは `library.py` に定数として置く
旧 `prewar-library` の epilog にあった検索構文の説明と使用例を `library.py` の定数（例: `SEARCH_HELP_EPILOG`）に移し、`cli.py` の `search` サブパーサが `epilog` と `RawDescriptionHelpFormatter` で使う。使用例は `prewar search ...` の形に直す。

- 代替案「`cli.py` に直接書く」: 検索構文の知識は検索側のモジュールに寄せておく方が、構文を変えたときに直し漏れが起きにくい。

### D7. テスト専用コードの削除とテストの扱い
- `OllamaOCRClient.is_available()` を消し、呼び出し元が無くなる `_check_model_available` の `force` 引数も消す。`test_is_available_always_asks` は削除する。モデル確認を1回に抑えるメモの挙動は、既存の「2回 OCR しても一覧取得は1回」のテストで引き続き守られる。
- `ModernizeResult.ok` を消し、`test_empty_body_returns_as_is` の `result.ok is True` は `result.failures == []` と `result.aborted is False` の確認に置き換える。
- `OCRResult.raw_response` を消し、`_call_ollama` は本文の文字列だけを返すようにする。

### D8. 新しい振る舞いを守るテスト
- 環境確認: 各 `check_*` を monkeypatch で差し替え、「Surya 未導入でも必須が揃えば 0」「必須が1つ欠けたら 1」「Pillow を確認対象に含まない」を確かめる。Ollama には接続しない。
- 起動コマンド: `pyproject.toml` を tomllib で読み、`[project.scripts]` が `prewar` だけであることを確かめる。
- 検索ヘルプ: `cli.build_parser()` の `search` のヘルプ文字列に OR・NOT・`原文:`・3文字の注意が含まれることを確かめる。

### D9. ドキュメント修正の方針
- 実態と食い違う数値・パス・説明は、実物を実行・計測して得た値に直す（senzen_word の字数とパターン数、`convert` の例の実行結果など）。
- archive 済みの変更への参照は `openspec/changes/archive/<日付>-<名前>/` に直す。
- `plan/implementation_plan.md` は冒頭に「OpenSpec 導入前の初期計画。現状の構成とは異なる」旨の注記だけを入れ、本文は残す。
- `plan/improvement-ideas.md` と `PROGRESS.md` の G8 は完了扱いに更新する。

## Risks / Trade-offs

- [旧コマンドを使うシェル履歴や手元のメモが動かなくなる] → README に置き換え表（`prewar-ocr` → `prewar ocr`、`prewar-library find` → `prewar search` など）を一度だけ載せる。
- [既存の `.venv` から surya と torch が消え、Surya を試していた場合に使えなくなる] → `prewar check` が未導入時に `uv sync --extra surya` を案内する。現状 Surya を使う処理は無いので実害は無い。
- [Pillow を外すと、見えない場所で PIL を使っていた場合に壊れる] → 削除後に全テストと `uv run prewar check` を実行して確認する。調査では直接 import 0件、推移依存も surya 経由のみ。
- [`uv remove` / `uv add` で lock の他パッケージが更新される] → 変更後に `git diff uv.lock` で、消えたパッケージ以外のバージョンが動いていないことを確認する。
- [ドキュメント修正は範囲が広く、書き換えで新たな誤りを入れる] → 数値は実測値だけを書き、コマンド例はすべて実行して確かめる。

## Migration Plan

1. 依存を変更して `uv sync` を実行する。`.venv` から surya と重量級の推移依存が消える。
2. コードとテストを変更し、`uv run pytest tests/ pkg/` を全件通す。
3. `uv run prewar check` と `uv run prewar search --help` を実行して振る舞いを確認する。
4. ドキュメントを更新する。

戻す場合は該当コミットを `git revert` して `uv sync` を実行すれば元の依存に戻る。

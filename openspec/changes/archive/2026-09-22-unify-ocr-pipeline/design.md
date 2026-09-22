## Context

動機は proposal.md の「Why」を参照。ここでは設計に効く現状だけを書く。

`scripts/ocr_vision_llm.py` の処理の入口は次の3つで、いずれも `run()` から呼ばれる。

| 関数 | 呼び出し元 | 中身 |
|---|---|---|
| `process_single(args, path)` | `run()` の2箇所、`process_folder` の `--separate` 分岐 | 前処理 → `_run_ocr_page` → 正規化 → `_run_modernize` → 記録生成 → 保存 |
| `process_batch(args, paths)` | `run()`、`process_folder` の既定分岐 | 前処理 → `_ocr_pages` → 結合 → 正規化 → `_run_modernize` → 記録生成 → 保存 → 失敗まとめ |
| `process_folder(args, folder)` | `run()`、`cmd_shoot` | 画像を並べて上の2つに振り分け |

調査（`survey/g7-e1-pipeline-refactor-survey.md`）で確認済みの事実:

- `save_document`（`utils/library_writer.py`）は「元画像が1枚か複数か」と「失敗ページの有無」だけで
  ファイル名とメタ情報の `pages` セクションを出し分ける。したがって1枚を `process_batch` に
  流しても、保存物は `process_single` と同一になる
- `_save_legacy_batch` は先頭と末尾の画像名が同じとき `{stem}_modern.txt` を出すので、
  1枚用の `_save_legacy` と同じ結果になる
- `process_single` の Ctrl+C（OCR中）は return 1。`process_batch` では1ページ目で中断すると
  成功0件になり return 1。終了コードは一致する
- `TextModernizer()` と `OllamaOCRClient` はコンストラクタでは Ollama に接続しない
  （接続は `ocr()` / `modernize_detailed()` の初回）
- `tests/` に `__init__.py` は無く、pytest の既定（rootdir 基準・prepend）で動いている

## Goals / Non-Goals

**Goals:**
- 1枚・複数枚の処理経路を1本にし、正規化〜保存〜終了コードの記述を1箇所にする
- 経路を繋ぐ層を Ollama なしでテストできるようにする
- リファクタ前に書いたテストを**無修正のまま**リファクタ後も通す

**Non-Goals:**
- `process_folder` の `--separate` ループの構造変更（1枚ずつ独立記録にする意味が残るため）
- 画面表示の文言の全面統一（段階ラベル `[1/3]` と `[正規化]` の揺れなどは許容）
- `run()` の対話モード分岐のテスト

## Decisions

### D1. 1枚処理は複数枚処理への委譲にする（入口は残す）
`process_single(args, path)` の本体を `process_batch(args, [path], ...)` の呼び出しにする。

- 採用理由: 入口を消すと `--separate` ループが `process_batch(args, [image])` と書くことになり、
  「1枚ずつ別記録」という意図が読み取りにくい。呼び出し元は3箇所だけなので薄い委譲で残す
- 却下案: 両者の共通部分だけをヘルパー化して2本の経路を残す → 分岐（OCR の呼び方、
  メタの集計、失敗まとめ）が残り続け、反映漏れの構造が解消しない

### D2. 差し替えはキーワード専用引数で注入する
`process_single` / `process_batch` / `process_folder` に `*, client=None, modernizer=None` を追加し、
`None` のときだけ本番の実体を作る。

```python
def process_batch(args, image_paths, *, client=None, modernizer=None) -> int:
    client = client or _create_ocr_client(args)
    modernizer = modernizer or TextModernizer()
```

- 採用理由: プロジェクトの決めごと（`unittest.mock` を使わず手書きフェイクで書く）に合う。
  既存の `_ocr_pages(client, ...)` / `_run_modernize(modernizer, ...)` が既に引数で受け取っており、
  その流儀を一段上まで広げるだけで済む
- 却下案: `monkeypatch` でモジュール内の生成関数を差し替える → テストが実装の内部名に依存し、
  リファクタで名前を変えると特性テストが壊れる（「無修正で通す」目標に反する）
- 型注釈はフェイクも受け入れられるよう、ダックタイピング前提で本番クラス名を書く
  （既存 `_ocr_pages` の注釈と同じ扱い）

### D3. 複数枚処理を小さな単位に分割する
`process_batch` の本体を次の単位に分け、上から順に呼ぶだけにする。

| 単位 | 性質 | 備考 |
|---|---|---|
| 正規化段階（`--no-normalize` 判定と結果表示） | print のみの副作用 | |
| 口語化結果の表示 | print のみ | 口語化本体は既存 `_run_modernize` |
| 記録の組み立て | **純粋関数** | OCR メタの集計（先頭ページのモデル名、所要時間の合計）、正規化フラグ、失敗ページ |
| 保存（ライブラリ＋旧形式） | ファイル I/O | |
| 終了コード判定 | **純粋関数** | 失敗ページ・口語化エラー・失敗チャンクのいずれかで 2 |

- 純粋関数の2つは単体テストを追加する。仕様の「終了コード」「1枚と複数枚で同一形式」の要件を
  最も直接に守る箇所であるため
- 関数名は実装時に既存の命名（`_run_*`, `_print_*`）に揃えて決める

### D4. 旧形式保存は1本に
`_save_legacy`（1枚用）を削除し、`_save_legacy_batch` を `_save_legacy` に改名して一本化する。
1枚時のファイル名は変わらない（Context 参照）。

### D5. 1枚時の表示の整理
委譲により1枚処理でも「処理モード: 複数画像（1枚）」が出てしまうため、この見出しは
2枚以上のときだけ出す。失敗のまとめ（`_print_failure_summary`）は1枚でも出す
（仕様「失敗時のまとめと再試行の案内」）。

### D6. テストの構成
- `tests/fakes.py` を新設し、`tests/test_ocr_batch.py` の `_FakeClient` / `_StubModernizer` を移す。
  加えて、入力に目印を付けて返す口語化フェイク（例: `口語:` を前置した本文と `chunk_total=1`）を足し、
  保存された口語化テキストが「口語化を通ったか／正規化テキストのままか」を判定できるようにする
- import は `from fakes import FakeClient`。`tests/` に `__init__.py` が無く、pytest の既定動作で
  `tests/` が import パスに入るため（`pkg/senzen_word/tests` 側に同名モジュールが無いことも確認する）
- テスト用の `args` は `scripts.cli._defaults_for(ocr_vision_llm.add_arguments)` で作る。
  本番と同じ既定値で埋まるため、引数の取りこぼしがテストで検出される
- 画像は `tmp_path` に空バイトのファイルを置く（保存時に実体コピーされるため実体が必要。
  フェイククライアントは中身を読まない）。前処理は `no_preprocess=True` で切る
  （前処理のフォールバックは既存テストで担保済み）
- 表示の検証は pytest 標準の `capsys` を使う

### D7. 作業順序: 特性テスト → リファクタ
1. フェイク共有化と注入点の追加（挙動不変）
2. 現行コードに対してパイプラインと CLI のテストを書き、すべて通す
3. リファクタ（D1, D3〜D5）
4. 手順2のテストを**無修正で**再実行して通ることを確認し、そのあと新しい挙動
   （1枚失敗時のまとめ）と純粋関数の単体テストを追加する

手順2 では「1枚失敗時にまとめが出ない」ことをテストしない（手順3で意図して変える挙動のため）。

## Risks / Trade-offs

- [特性テストが表示の細部に依存してリファクタで壊れる] → 表示の検証は仕様に書いた要素
  （失敗画像名、再試行コマンド例、保存できなかった画像名）の包含確認に限り、行単位の一致は見ない
- [1枚処理の表示が変わる（段階ラベル、OCR の見出し）] → 仕様の対象外とし、proposal に明記済み。
  スクリプトで出力を解析している利用者は終了コードとメタ情報を使う前提
- [注入引数の追加で本番経路に分岐が増える] → `None` のときに本番実体を作るだけの1行に留める
- [`from fakes import` がテスト実行方法によって解決できない] → 手順1で `uv run pytest tests/ pkg/`
  と個別ファイル指定の両方で通ることを確認する。解決できない場合は `tests/conftest.py` で
  `sys.path` を補う

## Migration Plan

利用者側の移行は不要。保存物・メタ情報・終了コード・CLI 引数は変わらない。
問題があればコミット単位で戻せるよう、上記 D7 の手順ごとにコミットを分ける。

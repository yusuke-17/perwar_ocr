# G7/E1 調査レポート: OCRパイプラインの重複解消とCLIテスト整備

調査日: 2026-09-21
対象: `scripts/ocr_vision_llm.py`（916行）、`scripts/cli.py`（270行）、`tests/`
位置づけ: `/opsx:propose` の参照材料。設計の確定はここでは行わない。

---

## 1. 結論（先に要点）

- **G7 の重複は健在**。`process_single`（568-663行）と `process_batch`（666-786行）で
  「正規化 → 口語化 → レコード生成 → 保存 → 終了コード」の約70行がコピペ状態。
- **E1 の前提「scripts/utils 側のテストは皆無」は古い**。現在 `tests/` に13ファイル・307件
  （`uv run pytest tests/ pkg/`）があり、`_ocr_pages` / `_run_modernize` / `_preprocess_images` /
  `save_document` は単体テスト済み。**欠けているのは「それらを繋ぐ層」**
  （`process_single` / `process_batch` / `process_folder` / `run`）と `cli.py` 全体。
- **改修の本質**: `process_single` を「1枚だけの `process_batch`」に畳み込む。
  1枚でも複数枚でも `meta.json` の出力は同一になることが確認できたため、動作を変えずに統合できる。
- **順序**: E1（特性テスト）→ G7（リファクタ）。先にテストで「今の挙動」を固定し、
  リファクタ後も同じテストが通ることで「壊していない」を証明する。

---

## 2. 現状の重複の内訳（行番号は 2026-09-21 時点）

| 処理 | process_single | process_batch | 差分 |
|---|---|---|---|
| 一時ディレクトリ + 前処理 | 575-577 | 677-680 | なし（引数がリストか単体か） |
| OCR実行 | 583-600 `_run_ocr_page` 直呼び | 683-703 `_ocr_pages` | single は Ctrl+C を自前で捕まえ return 1 |
| 正規化＋結果表示 | 603-616 | 719-733 | ラベルのみ（`[2/3]` vs `[正規化]`） |
| 口語化＋結果表示 | 619-629 | 736-746 | **完全に同一** |
| DocumentRecord 生成 | 633-652 | 752-774 | ocr_meta の集計（単体 vs 合計）、page_failures 等の有無 |
| 保存＋旧形式出力 | 653-658 `_save_legacy` | 775-780 `_save_legacy_batch` | `_save_legacy_batch` は先頭=末尾のとき単体と同じ名前を出す → **single 版は不要** |
| 終了コード | 661-663 | 784-786 | batch は `outcome.failures` も見る |

「1枚を `process_batch` に流したら結果が変わるか」を確認した結果:

- `source.png` か `source_01.png` かは `save_document` が `len(source_paths)` で決める → 同じ
- `pages` セクションは `page_failures` が空なら出さない（`library_writer.py:266`）→ 同じ
- `elapsed_seconds` は1件の合計＝その値 → 同じ
- 失敗時: single は無言で return 1、batch は `_print_failure_summary` を出す → **表示だけ差が出る**（許容範囲。むしろ再試行の案内が出て親切になる）

つまり **meta.json とファイル構成は変わらず、コンソール表示だけが少し変わる**。

---

## 3. G7 の改修案

### 3-1. 構造

```
process_single(args, path)        → return process_batch(args, [path])  の薄い委譲に
process_batch(args, image_paths)  → 唯一の経路。内部を以下のヘルパーに分割
```

抽出するヘルパー（テスト可能な単位に切る）:

| 関数 | 役割 | 純粋関数か |
|---|---|---|
| `_normalize_step(args, text) -> str` | `--no-normalize` 判定と表示 | 副作用は print のみ |
| `_build_record(...) -> DocumentRecord` | ocr_meta の集計・normalization フラグ・page_failures を詰める | **純粋**（最重要のテスト対象） |
| `_save_outputs(args, record, modern, ok_sources) -> Path` | `save_document` + `--legacy-output` | ファイルI/O |
| `_exit_code(outcome, modern_meta) -> int` | 0 / 1 / 2 の判定 | **純粋** |
| `_save_legacy` を削除し `_save_legacy_batch` に一本化 | 既に単体ケースを扱える | — |

### 3-2. テストのための注入点

`TextModernizer()` が関数内で直接生成されているため、Ollama なしで動かすには差し替え口が要る。
既存の `_create_ocr_client(args)` と対にして、**キーワード引数で注入**する形が
プロジェクトの決めごと（`unittest.mock` を使わない）と相性がよい:

```python
def process_batch(
    args, image_paths, *,
    client: OllamaOCRClient | None = None,
    modernizer: TextModernizer | None = None,
) -> int:
    client = client or _create_ocr_client(args)
    modernizer = modernizer or TextModernizer()
```

`tests/test_ocr_batch.py` にある `_FakeClient` / `_StubModernizer` をそのまま流用できる
（`tests/conftest.py` か `tests/fakes.py` へ移して共有する）。

### 3-3. 呼び出し元への影響

`process_single` の呼び出し元は `run()`（891, 902行）と `process_folder --separate`（825行）のみ。
`cli.py` は `ocr_vision_llm.run` と `add_arguments` しか触らない → **cli.py の変更は不要**。

---

## 4. E1 の改修案（新規テストの具体）

### 4-1. `tests/test_ocr_pipeline.py`（パイプライン結合層）

前提: `tmp_path` に空の画像ファイルを置く（`save_document` が `shutil.copy2` するので実体が必要。
中身は `_FakeClient` が読まないため空でよい）。`args` は `cli._defaults_for(ocr_vision_llm.add_arguments)`
で作り、`no_preprocess=True` / `library_root=tmp_path` を上書きする。

| # | ケース | 期待 |
|---|---|---|
| 1 | 1枚成功 | 終了 0、`source.png` / `ocr_raw.txt` / `modern.txt` / `meta.json` が出来る |
| 2 | 1枚OCR失敗 | 終了 1、library に何も出来ない |
| 3 | 3枚中1枚失敗 | 終了 2、`source_01/02.png`、meta に `pages` セクション |
| 4 | `--no-save` | 何も書かれず終了 0 |
| 5 | `--no-normalize` / `--no-modernize` | meta の `normalization` / `modernize.enabled` が反映 |
| 6 | `--legacy-output` 1枚・複数枚 | `output/{stem}_modern.txt` / `{first}-{last}_modern.txt` |
| 7 | 口語化が例外 | 終了 2、`modern.txt` は正規化テキスト |
| 8 | `process_folder --separate` 混在 | 全成功 0 / 一部 2 / 全失敗 1 |
| 9 | `process_folder` 空フォルダ | 終了 1 |
| 10 | `run(args)` の振り分け | ファイル→single、フォルダ→folder |

**#1〜#7 は先に現行コードに対して書く（特性テスト）。** G7 で統合したあと同じテストが通れば
「1枚経路の挙動が保たれた」証明になる。

### 4-2. `tests/test_cli.py`（統合CLI）

| # | ケース | 狙い |
|---|---|---|
| 1 | `build_parser().parse_args([sub, ...])` を全サブコマンド分 | `func` が正しい関数を指す |
| 2 | `_defaults_for(add_arguments)` の Namespace が `run` の参照する属性を全部持つ | `AttributeError` の回帰防止（cli.py:150 のコメントが警戒している事故そのもの） |
| 3 | `_run_shoot` が `args.image = "shoot"` を立てる | 委譲の正しさ |
| 4 | `prewar ocr --on-page-error abort` などフラグの通過 | argparse の choices |

対話メニュー（questionary）はテストしない。`run(args)` 以降が守られていれば十分。

### 4-3. スコープ外（別の変更として扱う）

`postprocess.run` / `clean.run` / `diff_viewer.run` の結合テスト。E1 の「CLI側」に含まれるが、
G7 の安全網という目的からは外れるため、今回は `ocr_vision_llm` + `cli.py` に絞る。

---

## 5. 規模感と順番

| 順 | 作業 | 目安 |
|---|---|---|
| 1 | `_FakeClient` / `_StubModernizer` を共有化 | 小 |
| 2 | `test_ocr_pipeline.py` の特性テスト（現行コードに対して） | 中（10〜15件） |
| 3 | `process_batch` に注入点とヘルパー抽出 | 中 |
| 4 | `process_single` を委譲に置換、`_save_legacy` 削除 | 小（約90行減） |
| 5 | `test_cli.py` | 小（8〜10件） |
| 6 | `plan/improvement-ideas.md` の G7/E1 行（行番号・「皆無」の記述）と `PROGRESS.md` のテスト件数を更新 | 小 |

判断に迷う規模なので **OpenSpec に載せる**（`/opsx:propose`）。変更名の案: `unify-ocr-pipeline`。

---

## 6. 決めておきたい論点（propose 時に確認）

1. 1枚失敗時に `_print_failure_summary` を出すか（batch と揃えて出す、が推奨）
2. 注入方法: キーワード引数（推奨）か、`_create_modernizer()` を用意して `monkeypatch` するか
3. `process_single` を残すか（呼び出し元2箇所のため残して委譲、が推奨。`--separate` の可読性維持）

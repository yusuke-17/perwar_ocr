# G2 設計: バッチ1枚失敗で全件破棄 → 部分成功を保存する

対象: `scripts/ocr_vision_llm.py` / `utils/library_writer.py` / `utils/config.py`
関連: D4「再開」の手前の堅牢性、G7「process_single/batch 重複解消」の下地

---

## ✅ 実装完了（2026-08-11）

本設計に加えて、下記の「スコープ外」項目もすべて実装した。

| 実装したもの | 場所 |
|---|---|
| ページ失敗のスキップ・継続（G2本体） | `ocr_vision_llm.py` `_ocr_pages` / `_run_ocr_page` / `BatchOcrOutcome` |
| 連続失敗フェイルファスト（既定3回） | `_ocr_pages(abort_after=...)` / `config` `batch.abort_after_consecutive_failures` |
| 口語化のチャンク単位耐性（G2b） | `text_modernizer.py` `modernize_detailed` / `ModernizeResult` / `ChunkFailure` |
| 口語化が丸ごと失敗しても保存（G2b） | `ocr_vision_llm.py` `_run_modernize`（`process_single`/`process_batch` 共用） |
| Ctrl+C でも成功分を保存（G2c） | `_ocr_pages` / `modernize_detailed` / `process_folder` |
| `--separate` の継続化 | `process_folder` |
| `prewar fix` のファイル単位耐性 | `postprocess.py` `run()` |
| **前処理のページ単位フォールバック**（設計時は未認識） | `_preprocess_images`。1枚失敗で全ページの前処理を捨てていたのを、失敗ページだけ元画像に落とす形へ |
| 終了コード 0/2/1 の規約 | 各 `run()` / docstring / README |
| テスト 26件追加（既存34件と合わせ60件） | `tests/test_ocr_batch.py` / `tests/test_modernize_resilience.py` |

設計から変えた点:
- `MetaPageFailure` は当初 `MetaModernize` と別扱いだったが、口語化の失敗も
  `MetaModernize` に `error` / `failed_chunks` / `chunk_total` を足して同じ流儀で記録した。
- `--separate` の戻り値は「保存できなかった件数」で判定する。`process_single` が返す 2
  （部分成功＝記録は保存済み）は失敗に数えない。

E2E確認済み（実Ollama・glm-ocr / qwen3.5:9b）:
壊れた画像を混ぜた3枚フォルダ → 成功2枚が保存・`pages.skipped` に1件・終了コード2。
全滅フォルダ → 3枚目で打ち切り・保存なし・終了コード1。
`prewar fix` に不正エンコードのファイルを混在 → 他ファイルは変換完了・終了コード2。

---

## 1. 何が壊れているか（現状）

| 箇所 | 現状のコード | 被害 |
|------|--------------|------|
| `ocr_vision_llm.py:452-455` `process_batch` | `result is None` で即 `return 1` | 10枚中10枚目で失敗 → **成功済み9枚のOCR結果が消える**。1枚数十秒〜数分なので損害大 |
| `ocr_vision_llm.py:566-568` `process_folder --separate` | `code != 0` で `return code` | 3枚目で失敗すると**4枚目以降が未処理のまま終了**（1〜2枚目は保存済み） |
| `ocr_vision_llm.py:284-295` `_run_ocr` | 全例外を `None` に潰す | 失敗理由が呼び出し側に伝わらず、「接続断で全滅」と「1枚だけ壊れ画像」を区別できない |
| `ocr_vision_llm.py:383-397` 口語体変換 | `modernize()` を try で囲っていない | LLMが落ちると**OCR済み全ページが保存前に例外で消える**（G2と同種。§7 で扱う） |

共通の原因は「**成功した中間成果物を、最後の save まで到達しないと1バイトも残さない**」設計。

---

## 2. 設計方針（4つ）

1. **ページ失敗は記録して継続**。成功分だけで下流（結合 → 正規化 → 口語化 → 保存）へ進む。
2. **全滅なら保存しない**。空の記録をライブラリに作らない。
3. **部分成功は終了コード 2**（新設）。「見かけ上成功」を作らず、スクリプトからも区別できる。
4. **失われたページを構造化して meta.json に残す**。あとで D4（再開）がそのまま入力にできる。

---

## 3. 終了コードの規約（新設）

| コード | 意味 | 例 |
|--------|------|-----|
| `0` | 全ページ成功・保存済み | 通常 |
| `2` | 一部ページ失敗、**成功分は保存済み** | 10枚中9枚保存 |
| `1` | 保存物なし | 全ページ失敗 / 入力なし / 引数エラー |

`scripts/cli.py` は戻り値をそのまま `sys.exit()` に流すため（`cli.py:261,265`）、追加実装は不要。
`--help` と各 docstring に上表を明記する。

---

## 4. データ構造

失敗の記録は既存の `MetaXxx` 系と同じ流儀で **`utils/library_writer.py` 側に置く**
（スクリプト側で別 dataclass を作ると二重定義になるため）。

```python
# utils/library_writer.py
@dataclass
class MetaPageFailure:
    """meta.json の pages.skipped に入る1件（OCRに失敗したページ）"""

    index: int      # 元の並びでの1始まりページ番号
    source: str     # 元画像のファイル名
    reason: str     # "image" | "connection" | "model" | "unknown" | "interrupted"
    message: str    # 例外メッセージ（人間向け）


@dataclass
class DocumentRecord:
    ...
    # 既存フィールドは変更なし。末尾に追加するので既存呼び出しはそのまま動く。
    page_failures: list[MetaPageFailure] = field(default_factory=list)
    pages_total: int = 0        # 0 なら len(source_paths) を使う
```

OCR収集ループの戻り値はスクリプト側のローカル型でよい。

```python
# scripts/ocr_vision_llm.py
@dataclass
class BatchOcrOutcome:
    results: list[OCRResult]          # 成功ページのみ（元の順序を保つ）
    ok_indices: list[int]             # 成功ページの 0 始まり添字（画像の対応付け用）
    failures: list[MetaPageFailure]
    aborted: bool                     # 連続失敗フェイルファストで打ち切ったか
```

`ok_indices` が要になる。`source_paths` と `preprocessed_paths` を**同じ添字で絞り込む**ことで、
`source_01.png … source_09.png` と `ocr_raw.txt` のページ順がズレないことを保証する。

---

## 5. 実装スケッチ

### 5-1. 失敗理由の分類（`_run_ocr` を置き換え）

現状の4連 except を1本にまとめ、理由コードを返せるようにする。`process_single` からも使うので、
G7（重複解消）の下地にもなる。

```python
_OCR_ERROR_KINDS: list[tuple[type[Exception], str, str]] = [
    (ImageFileError,           "image",      "画像エラー"),
    (OllamaConnectionError,    "connection", "Ollama接続エラー"),
    (OllamaModelNotFoundError, "model",      "モデルエラー"),
]


def _run_ocr_page(
    client: OllamaOCRClient, target: Path, source: Path, index: int
) -> OCRResult | MetaPageFailure:
    """1ページOCR。失敗しても例外を投げず MetaPageFailure を返す。

    KeyboardInterrupt は BaseException なので意図的に捕まえない
    （中断の扱いは _ocr_pages 側で行う）。
    """
    try:
        with spinner(f"  OCR推論中: {source.name} ..."):
            result = client.ocr(target)
    except Exception as e:
        for exc_type, reason, label in _OCR_ERROR_KINDS:
            if isinstance(e, exc_type):
                break
        else:
            reason, label = "unknown", "予期しないエラー"
        print(f"\n  ✗ {label}: {e}")
        return MetaPageFailure(index=index, source=source.name, reason=reason, message=str(e))

    print(f"  完了（{result.elapsed_seconds:.2f}秒）")
    return result
```

### 5-2. 継続収集ループ（本体）

```python
def _ocr_pages(
    client: OllamaOCRClient,
    image_paths: list[Path],
    ocr_targets: list[Path],
    *,
    on_page_error: str,          # "skip" | "abort"
    abort_after: int,            # 連続失敗の上限。0 で無効
) -> BatchOcrOutcome:
    """全ページをOCRし、失敗ページはスキップして成功分を集める。"""
    total = len(image_paths)
    results, ok_indices, failures = [], [], []
    consecutive = 0
    aborted = False

    for i, (source, target) in enumerate(zip(image_paths, ocr_targets)):
        print(f"\n[OCR {i + 1}/{total}] {source.name}")
        outcome = _run_ocr_page(client, target, source, index=i + 1)

        if isinstance(outcome, OCRResult):
            results.append(outcome)
            ok_indices.append(i)
            consecutive = 0
            continue

        failures.append(outcome)
        consecutive += 1

        # 従来挙動（abort）を選んだ場合、および
        # Ollama 停止などで全ページ分の待ち時間を捨てないためのフェイルファスト
        if on_page_error == "abort" or (abort_after and consecutive >= abort_after):
            残り = total - (i + 1)
            if 残り:
                print(f"\n⚠ 連続 {consecutive} 件失敗したため中断します（未処理 {残り}枚）")
            aborted = True
            break

    return BatchOcrOutcome(results, ok_indices, failures, aborted)
```

**フェイルファストを入れる理由**: Ollama が落ちていると全ページが等しく失敗する。
50枚のセッションで50回タイムアウトを待つのは無意味なので、連続3回（既定）で打ち切る。
このとき**すでに成功したページは捨てず保存する**（`aborted` は表示を変えるだけ）。

### 5-3. `process_batch` の差し替え

```python
        outcome = _ocr_pages(client, image_paths, ocr_targets,
                             on_page_error=..., abort_after=...)

        if not outcome.results:
            print(f"\n✗ 全 {total} 枚のOCRに失敗しました。保存するものがありません。")
            _print_failure_summary(outcome, total)
            return 1

        # 成功ページだけで以降を組み立てる（画像とテキストの対応を保つ）
        ok_sources = [image_paths[i] for i in outcome.ok_indices]
        ok_pre = [pre_paths[i] for i in outcome.ok_indices] if pre_paths else None
        ocr_raw_combined = "\n\n".join(r.text for r in outcome.results)

        # …正規化・口語化は現行どおり…

        record = DocumentRecord(
            source_paths=ok_sources,          # ← 失敗ページの画像はコピーしない
            preprocessed_paths=ok_pre,
            ...
            page_failures=outcome.failures,
            pages_total=total,
        )
        doc_dir = save_document(record, library_root=Path(args.library_root))

        _print_failure_summary(outcome, total)
        return 2 if outcome.failures else 0
```

### 5-4. 失敗サマリの表示

処理の最後にまとめて出す（途中のログは流れて見えなくなるため）。

```
============================================================
⚠ 10枚中 9枚を保存、1枚をスキップしました
  [10] p010.png — Ollama接続エラー: Connection refused
再試行するには:
  uv run prewar ocr input/session_20260811_1200/p010.png
============================================================
```

### 5-5. `--separate` の継続化

```python
    if args.separate:
        codes = []
        for i, image in enumerate(images, start=1):
            print(f"\n===== {i}/{len(images)}: {image.name} =====")
            codes.append(process_single(args, image))    # ← 失敗しても止めない

        failed = [img.name for img, c in zip(images, codes) if c != 0]
        if not failed:
            return 0
        print(f"\n⚠ {len(images)}件中 {len(failed)}件が失敗: {', '.join(failed)}")
        return 1 if len(failed) == len(images) else 2
```

---

## 6. meta.json への記録

`preprocess` セクションと同じ流儀で、**失敗が1件以上あるときだけ** `pages` を書く
（失敗ゼロのときは現行 meta.json とバイト一致 → 既存ライブラリに差分が出ない）。

```json
"pages": {
  "total": 10,
  "succeeded": 9,
  "skipped": [
    {
      "index": 10,
      "source": "p010.png",
      "reason": "connection",
      "message": "Ollama に接続できません: Connection refused"
    }
  ]
}
```

`SCHEMA_VERSION` は **1 のまま据え置く**。既存キーの意味を変えず追加のみのため後方互換で、
バージョンを上げると既存ライブラリの再インデックス判定（G6）に無用な影響が出る。

---

## 7. 設定と CLI フラグ

`utils/config.py` の `_DEFAULTS` に追加（`config.toml` は差分のみなので触らない）:

```python
    "batch": {
        "on_page_error": "skip",                # "skip"（既定・新挙動）| "abort"（従来挙動）
        "abort_after_consecutive_failures": 3,  # 連続失敗でのフェイルファスト。0 で無効
    },
```

一時上書き用に `--on-page-error {skip,abort}` を `add_arguments()` へ追加。
既定を `skip` にするのは「データを失わない側」が安全側だから。従来挙動が要る人だけ `abort`。

---

## 8. スコープ外／別案として提示

以下は G2 と同じ「成果物が消える」問題だが、判断が要るので分離する。**採否をりょうに確認したい2点**:

### G2b: 口語化（LLM）失敗でもOCR結果を守る（コスト小・効き大）
今は `modernizer.modernize()` が例外を投げると、OCR済み全ページが保存前に落ちる。
→ try で囲み、失敗時は正規化テキストをそのまま `modern.txt` にして保存、
`meta.modernize` に `{"enabled": false, "error": "..."}` を残す。OCRのやり直しを不要にする。

### G2c: Ctrl+C でも成功分を保存（コスト小）
撮りため大量処理の途中で中断したくなる場面は多い。`_ocr_pages` で `KeyboardInterrupt` を捕まえ、
`aborted=True` ＋ `reason="interrupted"` として成功分を保存してから抜ける。

**やらないこと**: 失敗ページの自動リトライ・再開（D4 の担当）。今回は「記録を残す」までに留める。

---

## 9. テスト（`tests/test_ocr_batch.py` 新規）

`_ocr_pages` は Ollama も LLM も触らないため、スタブクライアントで純粋にテストできる。

| # | 内容 | 期待 |
|---|------|------|
| 1 | 10枚中10枚目で `OllamaConnectionError` | `len(results)==9` / `ok_indices==[0..8]` / `failures` 1件 |
| 2 | 3枚目だけ `ImageFileError` | `ok_indices==[0,1,3,4]`、`reason=="image"` |
| 3 | 全枚失敗 | `results==[]` → `process_batch` が 1 を返す |
| 4 | 連続3枚失敗（`abort_after=3`） | `aborted is True`、クライアント呼び出し回数が打ち切り位置で止まる |
| 5 | `on_page_error="abort"` | 1枚目失敗で即打ち切り（従来挙動の維持） |
| 6 | `save_document(page_failures=[...])` | meta.json に `pages` が入る。空リストならキーごと出ない |
| 7 | 部分成功時の `source_paths` | 失敗ページの画像がライブラリにコピーされていない／連番とテキスト順が一致 |

既存 `tests/test_text_modernizer.py` と同じ流儀（pytest・日本語 docstring）で書く。

---

## 10. 実装順（1コミット＝1ステップ）

1. `library_writer`: `MetaPageFailure` / `DocumentRecord.page_failures` / meta 書き出し ＋ テスト6
2. `ocr_vision_llm`: `_run_ocr_page`（理由分類）— `process_single` もこれ経由に切り替え
3. `_ocr_pages` 追加 ＋ テスト1〜5
4. `process_batch` 差し替え・サマリ表示 ＋ テスト7
5. `--separate` の継続化
6. `config.py` / `--on-page-error` / docstring・README の終了コード表
7. `plan/improvement-ideas.md` の G2 を実装済みに更新

各ステップ単体でテストが通る状態を保つ（途中で止めても壊れない）。

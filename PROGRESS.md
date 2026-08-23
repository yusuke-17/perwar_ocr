# 開発進捗記録

戦前日本語OCRツールの作業ログ。会話が長引いて記憶が飛んでも、
このファイルを読めば「今どこまで出来ていて、次に何をするか」が分かる状態を保つ。

最終更新: 2026-08-11（G2 完了）

---

## 1. 現在地

基幹パイプラインは完成済みで、実運用しながら弱点を潰していく段階。

```
画像 → 前処理 → GLM-OCR → senzen_word正規化 → qwen3.5口語化 → library保存 → FTS5全文検索
```

- 完全ローカル実行（外部送信ゼロ）を達成
- 統合CLI `prewar` に全機能を集約（引数なしで対話メニュー）
- テスト: 本体60件 + senzen_word 65件 = **125件**（`uv run pytest tests/ pkg/`）

いま取り組んでいるのは `plan/improvement-ideas.md` の **G系（コード品質・堅牢性）**。
「エラーにならず結果だけ静かに欠ける」バグを優先的に潰している。

---

## 2. 直近の作業（2026-08-11）: G2 失敗耐性

**問題**: 「最後の `save_document()` に到達しないと中間成果物が1バイトも残らない」構造で、
1枚（1チャンク）の失敗が数十分ぶんの処理結果を丸ごと消していた。

**やったこと**（設計と詳細は `plan/g2-batch-failure-tolerance.md`）

| 対応 | 実装場所 |
|---|---|
| ページ失敗をスキップして継続、成功分だけで保存 | `scripts/ocr_vision_llm.py` `_ocr_pages` / `BatchOcrOutcome` |
| 失敗理由の分類（image/connection/model/unknown/interrupted） | 同 `_run_ocr_page` / `_OCR_ERROR_KINDS` |
| 連続3回失敗でフェイルファスト（Ollama停止時に全ページ待たない） | 同 `_ocr_pages(abort_after=...)` |
| 口語化のチャンク単位耐性（失敗チャンクは原文のまま採用） | `utils/text_modernizer.py` `modernize_detailed` |
| 口語化が丸ごと失敗しても正規化テキストで保存 | `scripts/ocr_vision_llm.py` `_run_modernize` |
| Ctrl+C でも成功分を保存 | OCRループ / チャンクループ / `--separate` ループ |
| 前処理の**ページ単位**フォールバック（1枚失敗で全ページ分を捨てていた） | 同 `_preprocess_images` |
| `prewar fix` のファイル単位耐性 | `scripts/postprocess.py` `run()` |
| 終了コード規約 0/2/1 の新設 | 各 `run()` / README |

**終了コード**: `0`=全成功 / `2`=一部欠けたが保存済み / `1`=保存物なし

**meta.json の追加キー**（問題があったときだけ出る。正常時は従来と同形）
```json
"pages": { "total": 10, "succeeded": 9, "aborted": false,
           "skipped": [{"index":10,"source":"p010.png","reason":"connection","message":"..."}] },
"modernize": { "enabled": true, "model": "qwen3.5:9b", "failed_chunks": 2, "chunk_total": 37 }
```

**実機確認済み**（glm-ocr / qwen3.5:9b）: 壊れ画像混在 → 成功分保存・exit 2 ／
全滅 → 3枚目で打ち切り・exit 1 ／ `prewar fix` 不正エンコード混在 → 他は変換完了・exit 2

---

## 3. 実装済み機能の履歴

| 時期 | 内容 | 関連 |
|---|---|---|
| 2026-02-08〜14 | プロジェクト開始、uv へ移行、GLM-OCR 採用、開発環境構築 | — |
| 2026-02-15〜23 | 口語体変換の追加、OCR誤読修正、カタカナ助詞・助動詞の対応 | — |
| 2026-03 | 口語化モデルを qwen3.5:9b に、一括変換対応、**senzen_word を独立パッケージ化** | `pkg/senzen_word/` |
| 2026-04〜05 | 対話式CLI・エントリポイント整備、複数選択、フォルダ整理、検索機能 | `scripts/cli.py` |
| 2026-06 | 改善案リスト作成 → C1（検索クエリ正規化）/ B1（設定外部化）/ D1（変換diff可視化）/ A1（画像前処理）/ D2（進捗バー） | `config.toml`, `utils/image_preprocessor.py` |
| 2026-07-04 | **G1**（句読点なし長文のチャンク未分割 → 後半欠落を根絶） | `utils/text_modernizer.py` |
| 2026-08-11 | **G2**（失敗耐性・部分成功の保存・中断耐性） | 上記セクション2 |
| 2026-08-16 | **G4**（OCRの temperature=0 で再現性確保・全Ollama呼び出しに300秒timeout） | `utils/ollama_client.py`, `config.toml` |
| 2026-08-16 | **G3**（変体仮名変換をパイプラインに接続。あわせて**壊れていた変換テーブルを修復**） | `utils/text_normalizer.py`, `pkg/senzen_word/` |

---

## 4. 次にやる候補

`plan/improvement-ideas.md` の優先順位に従う。

1. **G5 検索インデックスが口語化後テキストのみ / G6 差分更新が meta.json の mtime のみ** ← 次の候補
2. G7 `process_single`/`process_batch` の重複解消（G2で `_run_ocr_page` / `_run_modernize` を
   共用化したので下地はできている）＋ E1 CLIテスト整備
3. G9 口語化チャンクのフェイルファスト（G4で顕在化。無応答が続くと 300秒×チャンク数 待つ）
4. 本丸: F1 チャット要約（ローカルRAG）→ F2 セマンティック検索 → F3 出典付き回答

### 保留メモ
- glm-ocr が画像によって同じ行を延々と繰り返す出力をすることがある（モデル側のループ）。
  G4 実装時に同一画像で条件を変えて計測した結果:

  | 条件 | 出力文字数 | ユニーク行数 | 反復 |
  |---|---|---|---|
  | options無し（G4以前の挙動） | 3714 | 5 | あり |
  | temperature=0.0, seed=0（現在の既定） | 3714 | 5 | あり |
  | temperature=0.0, repeat_penalty=1.05 | 3689 | 5 | あり |
  | temperature=0.3, seed=0 | 3690 | 5 | あり |

  → **temperature の設定では直らず、G4 で悪化もしていない**（G4以前と同一の出力）。
  `repeat_penalty` も効かない。`num_predict` での上限設定は長いページの後半が
  無言で欠けるので不可。対策は生成パラメータではなく
  「OCR出力の異常検知（同一行の過剰反復を弾く）」の側で行うべき。改善案に追加検討
- `_preprocess_images` は失敗ページを元画像で代替するため、`preprocessed_NN.png` が
  元画像と同一になる場合がある（添字の整合を優先した割り切り）

---

## 5. 開発の決めごと（迷ったらここを見る）

- **文字を消さない**を最優先。分割も失敗処理も「欠落させない」側に倒す（G1・G2で一貫）
- **データを失わない側が既定**。失敗時の挙動は skip / keep_original を既定にし、
  従来の中断挙動は `abort` として選べるだけにする
- 設定のデフォルトは `utils/config.py` の `_DEFAULTS` が唯一の正解。`config.toml` は差分のみ
- meta.json は**問題があったときだけ**キーを足す（正常時は既存ライブラリと差分が出ない）
- `SCHEMA_VERSION` は追加のみの変更では上げない（再インデックス判定への影響を避ける）
- テストは `unittest.mock` を使わず、手書きフェイク＋純粋関数の直接テストで書く
- Python実行は必ず `uv run` 経由。機密資料（input/ output/ library/）はGit管理しない

---

## 6. よく使うコマンド

```bash
uv run prewar                      # 対話メニュー
uv run prewar ocr input/画像.png    # 画像 → OCR → 正規化 → 口語体変換
uv run prewar ocr input/session_/  # フォルダを1記録として一括処理
uv run prewar search 関東大震災     # 全文検索
uv run prewar index                # 検索インデックス更新
uv run prewar fix output/x.txt     # テキスト後処理のみ
uv run prewar check                # 環境確認

uv run pytest tests/ pkg/ -q       # テスト全実行
```

---

## 7. このファイルの更新ルール

- 作業の区切り（機能実装・バグ修正の完了）ごとに「直近の作業」と「履歴」を更新する
- 「直近の作業」は最新1件だけ詳しく残し、古いものは「履歴」の1行に畳む
- 設計の詳細は `openspec/changes/<変更名>/` に置き、ここからはリンクするだけにする
  （OpenSpec 導入前の設計文書は `plan/` 配下に残っている。`plan/` は今後バックログ専用）
- 機密情報（APIキー・資料の中身）は書かない

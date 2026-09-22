# 開発進捗記録

戦前日本語OCRツールの作業ログ。会話が長引いて記憶が飛んでも、
このファイルを読めば「今どこまで出来ていて、次に何をするか」が分かる状態を保つ。

最終更新: 2026-09-22（G8 デッドコード・不要依存の整理 完了）

---

## 1. 現在地

基幹パイプラインは完成済みで、実運用しながら弱点を潰していく段階。

```
画像 → 前処理 → GLM-OCR → senzen_word正規化 → qwen3.5口語化 → library保存 → FTS5全文検索
```

- 完全ローカル実行（外部送信ゼロ）を達成
- 統合CLI `prewar` に全機能を集約（引数なしで対話メニュー。起動コマンドは `prewar` だけ）
- テスト: 本体308件 + senzen_word 73件 = **381件**（`uv run pytest tests/ pkg/`）

G系（コード品質・堅牢性）の「静かに壊れる」バグと索引の正確性を潰し、検索の使い勝手（C系）も上げた。
OCRパイプラインの経路を1本化してテストの安全網を張り、不要依存と古い記述も掃除したので、以降の大きな改修（F1 等）に入れる土台が整った。

---

## 2. 直近の作業（2026-09-22）: G8 デッドコード・不要依存の整理

**問題**: 使っていない依存・効かない設定・読まれないコード・古い記述が残り、混乱の元になっていた。
特に `surya-ocr` は `prewar check` で「import できるか」を見るだけなのに、torch 等を引き込んで
`.venv` の7割超を占めていた。`chunk.overlap` は設定しても分割処理に一切効いていなかった。

**やったこと**（設計と詳細は `openspec/changes/` 配下の g8-dead-code-cleanup、事前調査は `survey/g8-dead-code-survey.md`）

| 対応 | 実装場所 |
|---|---|
| `requests`・`pillow` を削除、`surya-ocr` を extra `surya` へ（`uv sync --extra surya` で導入） | `pyproject.toml`, `uv.lock` |
| `prewar check` は必須4項目だけで合否判定。Surya 未導入は「未導入（任意）」表示で不合格にしない。確認対象を実使用の8パッケージに | `scripts/setup_check.py` |
| 旧コマンド `prewar-ocr` / `prewar-library` を廃止。検索構文ヘルプを `prewar search --help` へ移設 | `pyproject.toml`, `scripts/cli.py`, `scripts/library.py` |
| `chunk.overlap`・`OCRResult.raw_response`・`is_available()`・`ModernizeResult.ok`・ルートの `main.py` を削除 | `utils/`, `config.toml` |
| テスト追加（環境確認の合否・起動コマンドが `prewar` だけ・検索ヘルプの内容） | `tests/test_setup_check.py`, `tests/test_cli.py` |
| 文書の食い違いを修正（senzen_word の字数 318→384・パターン数 109→92・変換例、未記載の `diff`/`clean` など） | `README.md`, `CLAUDE.md`, `pkg/senzen_word/README.md` ほか |

**設計上の判断**

- `chunk.overlap` は実装せず削除。文の境界で切る分割なので、重ねると同じ文が二度口語化されて出力が重複する
- Surya は削除せず任意依存に。A2（複数エンジン比較）の候補として残す。確認は `find_spec` で有無だけ見る（torch を読まないので速い）
- 依存の変更は `uv remove` ではなく `pyproject.toml` の直接編集＋`uv lock` で行った。`uv remove` → `uv add` だと
  surya の推移依存（torch 2.10→2.14 など）まで解き直されるため

**利用者から見える変化**: `uv run prewar-ocr` / `uv run prewar-library` は使えない（README に置き換え表）。
`.venv` が **700MB → 152MB**。OCR・正規化・口語化・保存・検索の出力は不変。

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
| 2026-08-11 | **G2**（失敗耐性・部分成功の保存・中断耐性） | `plan/g2-batch-failure-tolerance.md` |
| 2026-08-16 | **G4**（OCRの temperature=0 で再現性確保・全Ollama呼び出しに300秒timeout） | `utils/ollama_client.py`, `config.toml` |
| 2026-08-16 | **G3**（変体仮名変換をパイプラインに接続。あわせて**壊れていた変換テーブルを修復**） | `utils/text_normalizer.py`, `pkg/senzen_word/` |
| 2026-08-24 | **G5/G6**（正規化済み原文も索引に追加・索引入力3ファイルの mtime 署名で変更検知） | `openspec/changes/archive/2026-08-24-search-index-original-text/` |
| 2026-08-31 | **C2/C3**（OR/NOT/対象限定の検索構文・抜粋の可変長と色分離・一致箇所数） | `openspec/changes/archive/2026-08-31-search-query-expression/` |
| 2026-09-22 | **G7/E1**（1枚/複数枚のOCR経路を1本化・パイプラインとCLIのテスト66件） | `openspec/changes/archive/2026-09-22-unify-ocr-pipeline/` |
| 2026-09-22 | **G8**（不要依存・旧コマンド・効かない設定の削除、文書の食い違い修正。`.venv` 700MB→152MB） | 上記セクション2 |

---

## 4. 次にやる候補

`plan/improvement-ideas.md` の優先順位に従う。

1. **D3 処理ログのファイル保存**（全部 print で揮発している） ← 次の候補
2. G9 口語化チャンクのフェイルファスト（G4で顕在化。無応答が続くと 300秒×チャンク数 待つ）
3. G10 旧字体変換表の穴（「內」→「内」等）を機械生成で塞ぐ
4. OCR出力の反復検知（下の保留メモ。G7の実機確認でも再現し、口語化の所要時間を大きく押し上げている。
   G8 の `prewar check` の簡易テストでも、GLM-OCR が「東京」の応答のあとに質問文と答えを繰り返した）
5. 本丸: F1 チャット要約（ローカルRAG）→ F2 セマンティック検索 → F3 出典付き回答

C4（タグ付けのCLI編集）は、C2で見送った**タグ・日付ファセット**の前提になる。
日付ファセットは「資料の年代」をどう得るか（本文からの和暦抽出？手入力？）の
設計が別途必要で、単独の変更として扱う。

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
- テストは `unittest.mock` を使わず、手書きフェイク＋純粋関数の直接テストで書く。
  フェイクは `tests/fakes.py` に置いて共有し、処理の入口のキーワード引数で差し替える
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
uv run prewar diff <doc_id>        # 変換前後の差分を色付き表示
uv run prewar clean input|library  # データ整理（input 掃除 / 誤記録削除）
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

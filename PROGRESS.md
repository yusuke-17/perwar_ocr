# 開発進捗記録

戦前日本語OCRツールの作業ログ。会話が長引いて記憶が飛んでも、
このファイルを読めば「今どこまで出来ていて、次に何をするか」が分かる状態を保つ。

最終更新: 2026-10-21（OCR エンジンの再選定 → NDLOCR-Lite への切り替えを OpenSpec に起票。未着手）

---

## 1. 現在地

基幹パイプラインは完成済みで、実運用しながら弱点を潰していく段階。

```
画像 → 前処理 → GLM-OCR → senzen_word正規化 → qwen3.5口語化 → library保存 → FTS5全文検索
```

- 完全ローカル実行（外部送信ゼロ）を達成
- 統合CLI `prewar` に全機能を集約（引数なしで対話メニュー。起動コマンドは `prewar` だけ）
- テスト: 本体416件 + senzen_word 73件 = **489件**（`uv run pytest tests/ pkg/`）

G系（コード品質・堅牢性）の「静かに壊れる」バグと索引の正確性を潰し、検索の使い勝手（C系）も上げた。
OCRパイプラインの経路を1本化してテストの安全網を張り、不要依存と古い記述も掃除したので、以降の大きな改修（F1 等）に入れる土台が整った。

---

## 2. 直近の作業（2026-10-21）: OCR エンジンの再選定 → NDLOCR-Lite への切り替えを起票

**問題**: G12 で GLM-OCR の反復を抑えても、毎回丸ごと失われるページ（10 枚中 1 枚）と系統的な誤読（カタカナ「ニ」→「二」、旧字体→新字体）が残る。

**分かったこと**（`survey/ndlocr-lite-survey.md`・`survey/ocr-engine-comparison-2026-10.md`）

- 国立国会図書館の **NDLOCR-Lite**（2026-02 公開、v1.3.1、CPU/ONNX、CC BY 4.0）が最適。手元 10 枚で失敗 0・GLM-OCR より明らかに正確。
  RapidOCR・Apple Live Text・VLM 各種（Qwen・Gemma・PaddleOCR-VL 等）・YomiToku・PaddleOCR は精度か依存で劣る
- 公式は依存を `==` 固定（numpy 2.2.2 等）でプロジェクトの numpy 2.4.2 と衝突。**ただし固定を外しても 10 枚の結果が完全一致**し、
  追加の依存は onnxruntime・Pillow・PyYAML・lxml・networkx・tqdm の 6 つだけ
- v1.3.1 は**パッケージとして入れると起動しない**（`py-modules` の漏れ）。`uv tool install` も不可。ソースのまま使う必要がある
- 関数を直接呼んでも CLI と完全一致。モデル読み込み 2.3 秒のあと 1 枚約 0.4 秒。画像前処理（A1）は NDLOCR-Lite では逆効果

**次の一手**: `openspec/changes/ndlocr-lite-engine/`（起票済み・未着手、20 タスク）。submodule（`vendor/ndlocr-lite`、タグ 1.3.1）で取り込み、
プロジェクトの環境で直接動かす。既定エンジンを NDLOCR-Lite に、GLM-OCR は `--model glm-ocr` で残す。`/opsx:apply` で実装に入る。
あわせて OpenSpec CLI を 1.14.3 に上げ、長すぎる要件 2 つを分割した（どちらもコミット済み）。

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
| 2026-10-04 | **D5**（複数画像のページ順を自然順に。並び順の表示・食い違い警告・`--order`・`.tif`/`.webp` の取りこぼし修正） | `openspec/changes/archive/2026-10-04-d5-page-order-sort/` |
| 2026-10-11 | 一括処理の遅延・失敗の原因調査（glm-ocr の反復ループ）→ G12 起票、G13 を backlog に | `survey/batch-slow-failure-survey.md` |
| 2026-10-18 | **G12**（反復の切り落とし・`num_predict` 上限・反復失敗の分類・Ollama バージョン表示。10 枚 30 分超 → 5 分） | `openspec/changes/archive/2026-10-18-g12-ocr-repetition-loop/` |

---

## 4. 次にやる候補

`plan/improvement-ideas.md` の優先順位に従う。

0. **NDLOCR-Lite への切り替え**（`openspec/changes/ndlocr-lite-engine/` 起票済み） ← 次の候補
1. **D3 処理ログのファイル保存**（全部 print で揮発している）
   （口語化の質では、D5 でページ順が正しくなったので **B3 ページ境界の連結 ＋ G11 失敗ページの目印** を1つの変更にまとめるのが効率的）
2. G13 口語化チャンクの余裕（2,000 字で 4096 トークンの 92%。末尾が無言で欠けるリスク）と
   G9 口語化チャンクのフェイルファスト（G4で顕在化。無応答が続くと 300秒×チャンク数 待つ）は同じファイルなのでまとめてよい
3. G10 旧字体変換表の穴（「內」→「内」等）を機械生成で塞ぐ
4. 本丸: F1 チャット要約（ローカルRAG）→ F2 セマンティック検索 → F3 出典付き回答

C4（タグ付けのCLI編集）は、C2で見送った**タグ・日付ファセット**の前提になる。
日付ファセットは「資料の年代」をどう得るか（本文からの和暦抽出？手入力？）の
設計が別途必要で、単独の変更として扱う。

### 保留メモ
- glm-ocr の反復ループ: G4 時点の計測（temperature・repeat_penalty では直らない）を経て G12 で対応済み。経緯は `survey/batch-slow-failure-survey.md`
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

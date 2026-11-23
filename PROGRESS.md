# 開発進捗記録

戦前日本語OCRツールの作業ログ。会話が長引いて記憶が飛んでも、
このファイルを読めば「今どこまで出来ていて、次に何をするか」が分かる状態を保つ。

最終更新: 2026-11-23（G13＋G9 口語化チャンクの溢れと連続失敗の打ち切りを実装・アーカイブ。仕様を本体に統合）

---

## 1. 現在地

基幹パイプラインは完成済みで、実運用しながら弱点を潰していく段階。

```
画像 → NDLOCR-Lite（既定。GLM-OCR なら前処理 → GLM-OCR） → senzen_word正規化 → qwen3.5口語化 → library保存 → FTS5全文検索
```

- 完全ローカル実行（外部送信ゼロ）を達成
- 統合CLI `prewar` に全機能を集約（引数なしで対話メニュー。起動コマンドは `prewar` だけ）
- テスト: 本体577件 + senzen_word 134件 = **711件**（`uv run pytest tests/ pkg/`）

G系（コード品質・堅牢性）の「静かに壊れる」バグと索引の正確性を潰し、検索の使い勝手（C系）も上げた。
OCRパイプラインの経路を1本化してテストの安全網を張り、不要依存と古い記述も掃除したので、以降の大きな改修（F1 等）に入れる土台が整った。

---

## 2. 直近の作業（2026-11-23）: G13＋G9 口語化チャンクの溢れと連続失敗（ブランチ `g13-g9-chunk-safety`、2026-11-23 アーカイブ済み）

**問題**
- G13: 口語化の 1 チャンク（2,000 字）は入力＋訳で Ollama のコンテキスト長（この Mac の既定 4096）の最大 88〜92% を使う。
  上限に達すると Ollama はエラーにせず `done_reason=length` で止め、コードはそれを成功として採用していたので、**訳の末尾が黙って欠ける**
- G9: 口語化はどのチャンクで失敗しても最後まで試し続けるので、Ollama が途中で固まると「300 秒 × 残りのチャンク数」待つ

**やったこと**（`openspec/changes/archive/2026-11-23-g13-g9-chunk-safety/`、22 タスク完了）
- **溢れの検知と分割**: `done_reason=length` の訳は採用せず、チャンクを真ん中に近い「。」の直後で 2 つに分けて 1 回だけ変換し直す。
  半分でも途切れたらチャンク全体を原文のまま残して失敗に数える（途中までの訳は採用しない）。分けた半分にもお手本の混入の判定（G14）をかける
- **`[llm] num_ctx = 8192` を既定に**: 実測で 4096 と 1 トークンあたりの速さは同じ、メモリは +0.3GB。`0` で Ollama の既定に戻せる（`llm_options()`）
- **`[llm] num_predict = 3072` も既定に**（`/code-review` の指摘）: 8192 だけでは、LLM が暴走したとき上限に届く前に 300 秒の時間切れになり、分割が働かず連続失敗に数えられてしまう。最長でも約 170 秒で `length` に止める
- **連続失敗の打ち切り**: `chunk.abort_after_consecutive_failures`（既定 3、0 で無効）。お手本の混入・反復・溢れは数えない（OCR 側と同じ考え方）。
  残りは原文のまま残し `failed_chunks` に数える（`meta.json` の形は変えない。終了コード 2）
- 反復検知の文言を「OCRエンジンが」から「モデル '名前' が」に（口語化でも起きるため）

**実機で分かったこと**（数値は `survey/batch-slow-failure-survey.md` 2-4）
- qwen3.5:9b は画像対応の部品（Projector）付きなので、上限で context shift せず止まって `length` を返す（Ollama の既定は context shift なので、モデルが変わったら要確認）
- 同じチャンクでも訳の長さは 1,235〜1,531 トークンと毎回揺れる
- 32 枚の処理中に Ollama を止めると、3 チャンク目で打ち切りの行が出て残り 3 チャンクは送られず、`failed_chunks: 6`・終了コード 2
- 設計の途中変更: `_chat()` の戻り値は変えず、送信を `_request()` に分けた（既存のテストの子クラスを書き換えずに済むため。design D7）
- `/code-review` の指摘で直したこと（tasks 6）: 上の `num_predict`、分けた訳は切れ目に改行があったときだけ改行でつなぐ（段落の途中に改行を入れない）、空白だけの半分は送らない、お手本なしの訳が溢れたら半分もお手本なしで送る、`num_ctx`・`num_predict` を整数に直して渡す。既定値の二重記述の指摘は既存の書き方に合わせて見送り

**後始末（2026-11-23）**: `/opsx:archive` で仕様を本体に統合（`text-modernization` に 2 要件・9 シナリオを追加）。PR でマージ待ち。

**残した課題**: B5（お手本の例 2 の話題が資料と重なり、実機でもまた混入→変換し直しが起きた）。

注意: OpenSpec の文書・テストに資料の本文を書かない（テストの例文は架空）。試験用の記録は確認後に削除済み。

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
| 2026-10-21 | OCR エンジンの再選定（NDLOCR-Lite が最適。固定を外しても結果一致、パッケージとしては起動しない）→ 起票 | `survey/ndlocr-lite-survey.md`, `survey/ocr-engine-comparison-2026-10.md` |
| 2026-10-25 | **NDLOCR-Lite を既定の OCR エンジンに**（submodule・整形・低信頼度の警告・環境確認。Surya 削除。10 枚 136 秒 → 4 秒、失敗 0） | `openspec/changes/archive/2026-11-02-ndlocr-lite-engine/` |
| 2026-11-03 | **B3＋G11**（文の途中のページ境界は改行1つ・失敗ページに目印の行・分割で句点を足さない。指示の追記は比較の結果外した。G14 を起票） | `openspec/changes/archive/2026-11-03-page-boundary-join/` |
| 2026-11-03 | **G10**（旧字体変換表 384→533 字。機械生成をやめ、判断一覧＋監査ツールに。索引の版を 3 に） | `openspec/changes/archive/2026-11-03-g10-kanji-variant-table/` |
| 2026-11-15 | **G14**（few-shot 例文の混入を目印の語で検出し、お手本なしで変換し直した結果を採用。B5 を起票） | `openspec/changes/archive/2026-11-15-g14-few-shot-leak/` |
| 2026-11-23 | **G13＋G9**（溢れた訳を検知して半分に分けて変換し直す・`num_ctx` 8192 を明示・口語化の連続失敗の打ち切り） | `openspec/changes/archive/2026-11-23-g13-g9-chunk-safety/` |

---

## 4. 次にやる候補

`plan/improvement-ideas.md` の優先順位に従う。

1. B5 お手本の話題を資料と重ねない（G14 の残り。例 2 の差し替えと比較実験。★★☆・小）← 次
2. senzen_word の仮名まわりの改善（`survey/senzen-word-gap-survey.md` の 2〜5 章: 開拗長音・語の境目の誤変換・カタカナ助詞の取りこぼし・踊り字）
3. 本丸: F1 チャット要約（ローカルRAG）→ F2 セマンティック検索 → F3 出典付き回答

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

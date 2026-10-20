# OCR エンジンの比較と依存の衝突（2026-10 時点）

調査日: 2026-10-21
問い: 依存パッケージ（numpy など）の版の衝突を避けたうえで、このプロジェクトに最も合う OCR エンジンは何か
手段: Web 調査（日本語特化 OCR・汎用 OCR / VLM の 2 系統）＋ 手元の `input/1.png`〜`10.png` と依存解決の実験（M4、Python 3.13）

---

## 結論

**NDLOCR-Lite（国立国会図書館、v1.3.1）を、公式の `requirements.txt` を使わずにプロジェクトの環境へ組み込む。**

- NDLOCR-Lite の `==` 固定は、動かすために必須ではなかった。プロジェクトと同じ numpy 2.4.2・OpenCV 4.11 と、
  最新の onnxruntime 1.31.0 の組み合わせで、10 枚の本文と信頼度が公式の固定版と**1 文字も違わなかった**
- 追加で要る依存は **onnxruntime・Pillow・PyYAML・lxml・networkx・tqdm の 6 つだけ**（どれも版の固定なし。PDF・GUI 関係は不要）
- 精度で並ぶ候補は見つからなかった。依存の衝突が無い代替（RapidOCR、Apple Live Text）は、
  GLM-OCR と同じ「カタカナを漢字と読む」誤りや旧字体の新字体化が出る

## 1. 依存の衝突の実験（手元で確認）

| 方式 | 結果 |
|---|---|
| 公式の固定のまま、プロジェクトの依存に追加 | ✕ `numpy==2.2.2` と `numpy>=2.4.2` が衝突して解決不能 |
| uv の `override-dependencies` で固定を外して追加 | 依存の解決は ◯。ただし起動時に ✕（下記の配布設定の不具合） |
| `uv tool install git+…@1.3.1` / `uv tool run`（前回の提案 D2 の方式） | ✕ 同じ不具合で起動しない |
| ソースのまま、固定を外した依存（numpy 2.4.2・onnxruntime 1.31.0）で実行 | ◯ 10 枚とも本文・信頼度が固定版と完全一致。2 回目 6.4 秒（固定版 9.3 秒） |
| ソースのまま、追加 6 つだけの最小構成で実行 | ◯ 10 枚とも固定版と完全一致。7.7 秒 |

**配布設定の不具合**: v1.3.1（と 2026-10-08 の master）の `pyproject.toml` の `py-modules` に `pdf_output_utils` と `version` が無く、
パッケージとして入れると `ModuleNotFoundError: No module named 'pdf_output_utils'` で起動しない。ソースから直接 `src/ocr.py` を
実行する README の手順でだけ動く。

**NDL の方針**（Issue #34、2026-03-25 の NDL 職員の回答）: サプライチェーン攻撃対策と破壊的更新の回避のため、依存は今後も固定して公開する。
緩める要望には沿えない。代わりに `pip install --no-deps` で入れて依存は利用者が管理する方法を案内している。
→ 「固定を外して自分で依存を管理する」こと自体は公式に案内された使い方。ただしその組み合わせは NDL の動作保証の外になる。
onnxruntime は 1.23 以上が推奨（1.20→1.23 で PARSeq のメモリ消費が大きく改善したため）。

## 2. 精度の比較

### 手元の 10 枚（NDLOCR-Lite を基準にした一致率）

| エンジン | 依存の衝突 | 10 枚の時間 | 結果 |
|---|---|---|---|
| NDLOCR-Lite | 固定を外せば無し | 6〜9 秒 | 失敗 0。5 枚目を画像と照合して 422 字中 4 か所の誤り（`ndlocr-lite-survey.md`） |
| GLM-OCR（現行） | 無し（Ollama 経由） | 約 2 分 | 全ページで反復。1 枚全損。カタカナ「ニ」→「二」、旧字体→新字体 |
| RapidOCR 3.10.0（PP-OCRv6、ONNX） | 無し | 5.5〜6 秒 | 一致率 平均 0.76（0.57〜0.89）。ニ→二・ハ→八・ト→卜・ヲ→チ、**列をまるごと読み飛ばす**（5 枚目で 1 列欠落） |

RapidOCR の日本語モデル指定（`Rec.lang_type=JAPAN`）は結果が既定と同一で、指定が効いていない可能性がある（未解決。
ただし PP-OCR の日本語モデルで戦前の旧字体・カタカナ文語が改善するという情報は見つからなかった）。

### 公開情報

- **NDLOCR-Lite**: 縦書き書籍 120 ページで文字精度 99.49%（約 5 分）、同じ画像で Ollama の qwen3.5:27b 単独は 93.47%（約 80 分、
  密なページで反復ループ）（Zenn、2026-05-10）。NDL の評価データで 1900〜1930 年代の活字 F 値 0.97 前後
- **縦書き日本語の VLM 比較**（arXiv 2511.15059、2025-11、現代の官公庁 PDF・旧字体は対象外）: PaddleOCR-VL が最良で CER 20.1
  （レイアウト解析を通した結果で、他のモデルとは条件が違う）。GPT-5 は 70.1、DeepSeek-OCR は 182、Qwen2.5-VL-32B は 128。
  「多くのモデルがトークン上限まで反復する」と報告
- **Apple Vision**: `VNRecognizeTextRequest` は縦書きを読めない（結果が空）。Live Text（ocrmac の `livetext`）は縦書きを読めるが、
  合成画像で 劍→剣（新字体化）・ハ→八・ニ→二 が出た
- 戦前の旧字体・カタカナ文語を直接測った公開ベンチマークは、どの候補にも見つからなかった

## 3. 候補ごとの判断

| 候補 | 判断 | 理由 |
|---|---|---|
| **NDLOCR-Lite** | **採用** | 精度・速度・失敗の少なさで他を引き離す。CPU のみ・モデル同梱・CC BY 4.0。固定を外した組み込みで衝突も避けられる |
| RapidOCR（PP-OCRv5/v6） | 見送り | 依存は最もきれいだが、カタカナの誤読と列の読み飛ばし（手元で確認） |
| Apple Live Text（ocrmac） | 見送り（補助なら可） | 依存は最小だが、旧字体の新字体化とカタカナの誤読 |
| PaddleOCR-VL 1.6（mlx-vlm 経由） | 見送り | 縦書きの公表値は VLM で最良だが CER 20%。旧字体は未評価。VLM 特有の反復の恐れ。公式クライアントは `numpy<2.4` で衝突 |
| Sarashina2.2-OCR（MLX 4bit） | 見送り | 縦書き特化だが古いスキャンに弱い兆候。`transformers==4.57.1`・`mlx-vlm==0.6.6` 固定で隔離が必要 |
| YomiToku 0.15.1 | 見送り | CC BY-NC-SA（非商用）。torch が重い。`opencv-python`（非 headless）と同居。戦前資料の評価なし |
| PaddleOCR 3.7 本体 | 見送り | `numpy<2.4`・`opencv-contrib-python==4.10.0.84` 固定で衝突 |
| Qwen3-VL / Qwen3.5 / Gemma 4（Ollama） | 見送り | 依存は増えないが、縦書きで反復（Qwen3-VL は報告者の計測でループ率 24〜55%）。Gemma 4 の縦書きは未検証 |
| DeepSeek-OCR、Surya、EasyOCR、Tesseract、manga-ocr、NDL古典籍OCR-Lite | 見送り | 縦書きに弱い・依存が重い・更新停止・対象外（くずし字用） |

## 4. 組み込み方の選択肢（NDLOCR-Lite）

| 方式 | 依存の衝突 | 長所 | 短所 |
|---|---|---|---|
| **A. プロジェクトの環境に組み込む**（ソースを v1.3.1 に固定して取り込み、追加 6 つを `uv add`） | 無し（手元で一致を確認） | 環境が 1 つ。モデルを 1 回読めば 1 枚 0.7 秒。subprocess が要らない | NDL の動作保証の外の組み合わせ。NDL の内部関数を呼ぶので、版を上げるときに壊れうる |
| B. 別の仮想環境に公式の固定どおり入れ、subprocess で呼ぶ | 無し（環境が別） | NDL の動作保証どおり | 環境が 2 つ。`uv tool install` が使えないので、clone＋venv の手順を自前で用意する。起動込み 1 枚 2.6 秒 |

ソースの取り込み方は、git submodule でタグ `1.3.1` に固定するのが素直（モデル約 157MB はプロジェクトの履歴に入らない）。
A なら、版を上げるときは 10 枚の出力を前の版と比べる回帰確認を手順に入れる。

## 5. 前回の提案（`openspec/changes/ndlocr-lite-engine/`）への影響

- design D2（`uv tool install` で別環境に入れ、ページごとに CLI を呼ぶ）は、配布設定の不具合で**そのままでは動かない**
- 方式 A に切り替えるなら、D2・tasks の 1.1 と 3.x・proposal の「依存」の記述を直す（`/opsx:update`）。
  整形（D3）・信頼度（D4）・前処理（D5）・G12 の範囲（D6）・環境確認（D7、確認方法は変わる）の判断はそのまま使える

## 参照

- https://github.com/ndl-lab/ndlocr-lite （Issue #34 #38 #43 #54 #56、requirements.txt、pyproject.toml）
- https://zenn.dev/phpmyadmin/articles/0dba6fef411e21 （2026-05-10、NDLOCR-Lite と qwen3.5:27b の比較）
- https://arxiv.org/abs/2511.15059 （2025-11-19、縦書き日本語の VLM 評価）、https://github.com/llm-jp/eval_vertical_ja
- https://github.com/QwenLM/Qwen3-VL/issues/1611 （Qwen3-VL の反復ループ）
- https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6 、https://huggingface.co/sbintuitions/sarashina2.2-ocr
- https://pypi.org/project/rapidocr/ 、https://pypi.org/project/ocrmac/ 、https://pypi.org/project/yomitoku/ 、https://pypi.org/project/paddleocr/
- https://developer.apple.com/forums/thread/772972 （Apple Vision の縦書き）

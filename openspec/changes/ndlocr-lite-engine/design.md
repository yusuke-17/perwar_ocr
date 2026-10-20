## Context

動機は `proposal.md`、実測と NDLOCR-Lite の仕様は `survey/ndlocr-lite-survey.md`、依存の衝突と他エンジンとの比較は
`survey/ocr-engine-comparison-2026-10.md`。設計に効く事実だけを挙げる。

- OCR は `scripts/ocr_vision_llm.py` の `process_batch` → `_create_ocr_client(args)` → `_ocr_pages` → `_run_ocr_page` → `client.ocr(target)` の 1 経路（G7）。
  クライアントはダックタイピングで、`ocr(image_path) -> OCRResult` と `model` 属性があればよい（`tests/fakes.py` もこの形）。
- 失敗の分類は `_OCR_ERROR_KINDS`（例外クラス → 理由コード・表示名）。連続失敗の打ち切りは理由 `repeat` 以外を数える（G12）。
- エンジン名の設定口はすでにある: `[models] ocr`（既定 `glm-ocr`）と `--model`。`DEFAULT_MODEL` は `utils/ollama_client.py` が持つ。
- 前処理は `_preprocess_images(args, …)` が `--no-preprocess` と `preprocess.enabled` を見て決める。
- 題名は `extract_title(ocr_raw)` が本文の最初の非空行から取る。ページは `"\n\n"` で結合される。
- NDLOCR-Lite v1.3.1（タグ `1.3.1`）の事実（手元で確認）:
  - `requirements.txt` が `numpy==2.2.2`・`onnxruntime==1.23.2`（macOS）・`flet` などを `==` で固定。プロジェクトは `numpy>=2.4.2` で、
    そのままでは同じ環境に入らない。NDL は固定を緩める要望を断り、`--no-deps` で入れて依存を利用者が管理する方法を案内している（Issue #34）
  - **固定は動作に必須ではない**: numpy 2.4.2・onnxruntime 1.31.0 で、10 枚の本文と信頼度が固定版と完全に一致した。
    実行に要るのは onnxruntime・Pillow・PyYAML・lxml・networkx・tqdm だけ（PDF・GUI 関係は画像の OCR に不要）
  - **パッケージとして入れると起動しない**: `pyproject.toml` の `py-modules` に `pdf_output_utils` と `version` が無く、
    `pip install` / `uv tool install` / `uv tool run` のどれでも `ModuleNotFoundError` になる。ソースのまま動かす必要がある
  - プロセス内の境目: `get_detector(args)`・`get_recognizer(args, weights_path)` でモデルを読み、
    `_run_ocr_on_image_array(detector, rec30, rec50, rec100, name, img, outputpath, save_viz=False)` に RGB の画像配列を渡すと、
    JSON 出力と同じ形の行のリスト（`json_lines`）を返す。10 枚で CLI の出力と完全に一致。モデルの読み込み 2.3 秒、その後 1 枚約 0.4 秒
  - 行の形: 読み順に並んだリスト。各行に `text`・`confidence`・`isVertical`（文字列 `"true"`/`"false"`）・`boundingBox`（4 点）・
    `id`・`class_index`。読点の後などに半角空白が入る。縦書きは 1 列が 1 行
  - モデル（ONNX 4 本・約 157MB）は Git LFS ではなくリポジトリに直接入っている。リポジトリ全体は履歴込みで約 238MB
  - 版: `pyproject.toml` は 1.3.1 でも `1.3.0`、`--version` は `0.0.0.dev0`（版の書き込みは配布用ビルドだけ）。タグからしか分からない
  - 前処理後の画像は元画像より平均信頼度が下がり、1 枚は 37 字欠けた（10 枚で比較）

## Goals / Non-Goals

**Goals:**
- エンジンの切り替えを `client.ocr()` の差し替えに閉じ込め、`_ocr_pages` 以降（失敗の扱い・結合・保存）を共通のまま使う
- 仮想環境は 1 つのまま、公式の `==` 固定を持ち込まずに、プロジェクトの依存の範囲で NDLOCR-Lite を動かす
- NDLOCR-Lite のソースには手を入れず、版をタグで固定して取り込む
- NDLOCR-Lite の出力の整形を純粋関数にし、実機の JSON 形でテストする
- 自動テストは NDLOCR-Lite も Ollama も無しで通す

**Non-Goals:**
- NDLOCR-Lite の PDF 入力・透明テキスト PDF・GUI・縦中横の検出（画像の OCR だけを使う）
- NDLOCR-Lite のパッケージ化の不具合を直すこと（上流の問題。直れば導入方法を見直す）
- 段落の判定を字下げ（列の開始位置）まで使って厳密にすること（短い列での改行で、題名と検索の目的は満たす）

## Decisions

### D1. エンジン名は既存の `[models] ocr` / `--model` で選ぶ

- `_DEFAULTS["models"]["ocr"]` を `"ndlocr-lite"` に変える。値が `ndlocr-lite` なら NDLOCR-Lite、それ以外は Ollama のモデル名として
  従来の `OllamaOCRClient` を作る（`_create_ocr_client` の分岐 1 か所）。
- 代替案（見送り）: `[ocr] engine` を新設する → `[ocr]` は Ollama の options にそのまま渡るセクションで、混ぜると G12 の
  `_OCR_NON_OPTION_KEYS` のような除外が増える。エンジンとモデル名を別々に持つと「engine=ndlocr-lite・model=glm-ocr」のような
  意味のない組み合わせが生まれる。
- `--prompt` は Ollama のエンジンでだけ意味を持つ。NDLOCR-Lite で指定されたら「無視する」旨を 1 行表示する。

### D2. NDLOCR-Lite のソースを submodule で取り込み、プロジェクトの環境で直接呼ぶ（新規 `utils/ndlocr_client.py`）

- 取り込み: `git submodule add` で `vendor/ndlocr-lite` に置き、タグ `1.3.1` のコミット（`6feccb2`）に固定する。
  `.gitmodules` に `shallow = true` を書き、利用者は `git submodule update --init --depth 1` で最新 1 世代だけ取る
  （履歴込みの約 238MB を避け、モデル約 157MB はプロジェクトの履歴に入らない）。ソースには手を入れない。
- 依存: 実行に要る 6 つを `uv add` する（`onnxruntime>=1.23.2`・`pillow`・`pyyaml`・`lxml`・`networkx`・`tqdm`）。
  onnxruntime の下限は NDL の推奨（1.20→1.23 で認識のメモリ消費が大きく改善した。Issue #34）。
  NDLOCR-Lite の `requirements.txt` と `pyproject.toml` は使わない（パッケージとしては入れない）。
- 読み込み: `utils/ndlocr_client.py` の中でだけ、初回の `ocr()` で `vendor/ndlocr-lite/src` を `sys.path` の**末尾**に足して `ocr` モジュールを import する
  （起動を遅くしない既存方針）。`src` には `ocr`・`config`・`model`・`version`・`deim`・`parseq` という一般的な名前のモジュールがあるため、
  先頭に足して他のライブラリの import を横取りしないようにする。プロジェクト側にこれらの名前のトップレベルモジュールが無いことは実装時に確認する。
  `get_detector`・`get_recognizer` に渡す引数は、v1.3.1 の CLI の既定値（モデルのパス・閾値 0.2/0.25/0.2・`device="cpu"`）を
  写した `argparse.Namespace` を組み立てて渡す。モデルは 1 クライアントで 1 回だけ読み、ページ間で使い回す。
- `NdlocrLiteClient.ocr(image_path)`: 画像を検証し（`OllamaOCRClient._validate_image` と同じ規則。共通関数に切り出す）、
  Pillow で RGB に変換した配列を `_run_ocr_on_image_array(..., save_viz=False)` に渡す（出力先は一時ディレクトリ。可視化しないので何も書かれない）。
  返った `json_lines` を D3 の整形に通して `OCRResult` を返す。`elapsed_seconds` は認識にかかった時間（初回のモデル読み込みは含めず、画面に別に出す）、
  `model="ndlocr-lite"`、`prompt=""`、`options={}`。
- 設定: `[ndlocr] path = "vendor/ndlocr-lite"`（プロジェクト直下からの相対。別の場所に置いた利用者のため）、`low_confidence = 0.7`（D4）。
- 失敗の分類（`_OCR_ERROR_KINDS` に追加）:
  - `NdlocrNotInstalledError` → 理由 `model`・表示「OCRエンジン未導入」。ソースやモデルのファイルが無い（submodule 未取得）か、
    import に失敗した（依存が足りない）とき。メッセージに `git submodule update --init --depth 1` と `uv sync` を出す
  - `NdlocrError` → 理由 `unknown`。認識中に NDLOCR-Lite 側で例外が出たとき（元の例外の種類とメッセージを含める）
  - 画像が開けないときは既存の `ImageFileError`（理由 `image`）
- 制限時間（timeout）は設けない: 同じプロセス内の CPU 計算はサーバーのように応答が途絶えることがなく、計算を安全に途中で止める手段も無い。
  中断は従来どおり Ctrl+C（`KeyboardInterrupt` は捕まえない）で受ける。
- 未導入はページごとに同じ失敗になるので、既存の連続失敗の打ち切り（既定 3）でそのまま早く止まる。
  事前確認（ファイルの有無と import）は 1 クライアントで 1 回だけ行い、成功したときだけ覚える（`_check_model_available` と同じ流儀）。
- 代替案（見送り）:
  - `uv tool install git+…@1.3.1` で別環境に入れて CLI を呼ぶ（前回の案） → パッケージ化の不具合で起動しない
  - プロジェクトの依存に git の URL で加え、`[tool.uv] override-dependencies` で固定を外す → 依存の解決は通るが、同じ不具合で起動しない
  - 別の仮想環境を自前で作り（clone ＋ `uv venv` ＋ 公式の固定どおり）、subprocess で呼ぶ → 公式の保証どおりだが、環境が 2 つになり
    導入手順も自前で持つことになる。起動ごとにモデルを読むので 1 枚 2.6 秒
  - ソースとモデルをプロジェクトのリポジトリに丸ごとコピーする → 約 157MB のモデルが履歴に残る。版の追跡もしにくい

### D3. 出力の整形は純粋関数 `shape_ndlocr_lines(lines) -> str`

1. 行は JSON の並び（読み順）のまま使う。`text` が空の行は捨てる。
2. 空白: 半角空白のうち、前後どちらかが非 ASCII 文字のものを取り除く（`re.sub(r"(?<=[^\x00-\x7f]) | (?=[^\x00-\x7f])", "")`）。
   英字どうしの間の空白は残す。全角空白は資料の字下げの可能性があるので触らない。
3. 列の長さ: `boundingBox` から、縦書き（`isVertical == "true"`）は y の幅、横書きは x の幅。向きごとにページ内の最大値を取る。
4. 連結: 行を順に連結し、長さが同じ向きの最大値の 0.9 倍未満の行の後には改行を入れる。最後の行の後には改行を入れない。
   ただし次の行が同じ列の続き（縦書きなら x の範囲が重なり、次の行の上端が今の行の下端より下）のときは改行しない。
- 0.9 の根拠（手元 10 枚の全 127 行を計測）: 本文の列は最大値の 0.96〜1.00。0.83〜0.88 が 3 本あり、うち 2 本は段落の終わり
  （「。」で終わり次の列が上端から始まる、署名の後で宛名に移る）で改行すべき、1 本は 1 本の列が括弧書きの位置で上下 2 つの行に
  分かれたもの（2 枚目。次の行が真下に続く）で改行してはいけない。見出し・ページ番号・短い署名などは 0.66 未満。
  0.9 なら段落の終わりを拾え、本文の列（0.96 以上）とも余裕がある。分かれた列は「真下に続く」規則で救う。
  定数 `_SHORT_LINE_RATIO = 0.9` としてモジュールに置く（設定にはしない。利用者が調整する値ではない）。
- 代替案（見送り）: NDLOCR-Lite の TXT 出力をそのまま使う → 1 列ごとの改行で、列をまたぐ語が全文検索（trigram）に引っかからない。
  見出しの判定に `class_index` を使う → 手元の 10 枚はすべて `line_main`（1）で、見出しの区別がつかなかった。

### D4. 信頼度と記録

- `OCRResult` に `low_confidence_lines: int = 0` と `engine_version: str = ""` を追加（既定値つき。GLM-OCR とフェイクは変更不要）。
  閾値は `[ndlocr] low_confidence = 0.7`。行数の数え方は `confidence < 閾値`。
- `_warn_ocr_quality`（G12）に「⚠ {ページ名} に認識の信頼度が低い行が N 行あります（prewar diff で確認できます）」を足す。
- `MetaOcr` に `low_confidence_lines: dict[int, int]` と `engine_version: str` を追加。`meta.json` の `ocr` に
  `low_confidence_lines`（あるときだけ、キーはページ番号の文字列）と `engine_version`（NDLOCR-Lite のときだけ）を出す。
  `_build_record` が `ok_indices` に合わせて元のページ番号で集める（G12 の `repetition_trimmed` と同じ形）。
- 版の取得: `git -C vendor/ndlocr-lite describe --tags --exact-match` の結果（`1.3.1`）を版とする。
  取れなければ（git が無い・タグの無いコミット・submodule ではなく手で置いた）`"不明"`。1 クライアントで 1 回だけ実行してメモする。
  `prewar check` も同じ関数を使う。

### D5. 前処理はエンジンで決める

- `_preprocess_images` の冒頭で、エンジンが `ndlocr-lite` なら `(None, None)` を返す（`--no-preprocess` と同じ扱い）。
  このとき `--no-preprocess`・`--binarize` の指定は効かない旨を表示しない（既定の動作を説明するために毎回出すと雑音になる）。README に書く。

### D6. G12 の反復対策の範囲

- 切り落とし（`trim_repetition`）と `num_predict` は `OllamaOCRClient` の中にあるので、NDLOCR-Lite のクライアントでは自然に働かない。
  コードの変更は不要で、仕様の範囲を明記するだけ（`specs/ocr-pipeline`）。テストで「NDLOCR-Lite の結果は `trimmed_chars == 0`・`hit_limit is False`」を確認する。

### D7. `prewar check`

- `REQUIRED_CHECKS` を固定の辞書から「選ばれたエンジンに応じて組み立てる」形に変える。
  - エンジンが `ndlocr-lite`: 必須に「NDLOCR-Lite」（ソースとモデル 4 本の有無・import できるか・版の表示）。
    GLM-OCR は任意項目として導入有無だけ表示（簡易テストはしない）
  - エンジンが Ollama のモデル: 従来どおり GLM-OCR（そのモデル）の確認と簡易テストを必須。NDLOCR-Lite は任意項目
- NDLOCR-Lite の確認ではモデルを読み込まず、画像も渡さない（ファイルの有無と import だけ。数秒かかるモデルの読み込みを環境確認でしない）。
- `REQUIRED_PACKAGES`（G8）に onnxruntime・lxml・networkx・yaml・PIL を足す（D2 で足した依存）。

### D8. テスト

- 整形: 実機の JSON（5 枚目・9 枚目）の**形だけ**を写した架空の行データで、列の連結・見出しの改行・段落の改行・空白の除去・
  横書きの行の混在を確認する（資料の本文はテストに入れない。G12 で決めた方針）。
- 呼び出し: NDLOCR-Lite の読み込みと認識を差し替える口（`backend=` キーワード引数。「1 枚の画像配列を受けて行のリストを返す」形）を
  `NdlocrLiteClient` に持たせ、手書きの偽バックエンドで正常・未導入（ファイルが無い・import 失敗）・認識中の例外を再現する
  （`unittest.mock` は使わない）。版の取得も `version_reader=` で差し替える。
- 上流との結合: `vendor/ndlocr-lite` が取得済みの環境でだけ、合成した縦書きの画像（テスト内で描く。資料は使わない）を本物の
  NDLOCR-Lite で読み、行のリストの形（キーと型）が D3 の前提どおりかを確かめる。取得していない環境では skip する。
  版を上げて内部関数（`_run_ocr_on_image_array` など）が変わったときに、ここで気づける。
- パイプライン: `tests/fakes.py` の `FakeClient` に `low_confidence_lines` などを `extras` で渡し、警告とメタ情報を確認する。
- 実機確認は `input/1.png`〜`10.png` で、所要時間・失敗数・題名・低信頼度の警告を `survey/ndlocr-lite-survey.md` に追記する。

## Risks / Trade-offs

- [同じ字の重複（「禪禪」型）が本文に残る] → 自動では直さない（正しい重ね字と区別できない）。低信頼度の警告と `prewar diff` で人が確認する。
  頻度が問題になれば、低信頼度の行だけ GLM-OCR で読み直す併用を別変更で検討する
- [短い列での改行が段落を誤って分ける／つなぐ] → 字は変えないので本文は欠けない。題名と検索に効く範囲で割り切る
- [NDLOCR-Lite の内部関数（`_run_ocr_on_image_array`・`get_detector`・`get_recognizer`）に頼る。公式の安定 API ではない]
  → submodule でコミットごと固定し、勝手には変わらない。版を上げるときは、上流との結合テスト（D8）と、10 枚の出力の比較を取り直してから
- [公式の `==` 固定を外した組み合わせは NDL の動作保証の外] → 10 枚で固定版と完全一致を確認済み。依存を大きく上げたとき
  （numpy・onnxruntime のメジャー版など）は同じ比較を取り直す。onnxruntime は NDL の推奨どおり 1.23 以上に保つ
- [submodule の取得を忘れる・`git clone` に `--recurse-submodules` を付け忘れる] → 未導入のエラーと `prewar check` に取得コマンドを出す。
  連続失敗の打ち切りで早く止まる
- [依存が 6 つ増える] → どれも版の固定が無く、numpy 2.4 系と衝突しないことを確認済み。PDF・GUI 関係（reportlab・pypdf・flet など）は入れない
- [既定のエンジンが変わり、NDLOCR-Lite を取得していない環境で OCR が失敗する] → 上と同じく、取得コマンドの案内と早い打ち切り
- [口語化の入力が変わる（GLM-OCR より改行が少なく、誤読も少ない）] → チャンク分割は「。」→「、」→ 改行 → 字数の順でフォールバックする（G1）ので
  改行が少なくても切れる。口語化の結果は実機確認で目視する

## Migration Plan

- 既定が NDLOCR-Lite に変わる。利用者は `git submodule update --init --depth 1` と `uv sync` を一度実行する（README・`prewar check`・エラーで案内）。
  新しく clone する人は `git clone --recurse-submodules --shallow-submodules` でもよい。
- GLM-OCR に戻すには `config.toml` に `[models] ocr = "glm-ocr"` を書くか、`--model glm-ocr` を付ける。
- `library/` の既存記録・検索索引には触らない。新しい `meta.json` のキーは追加のみで、`SCHEMA_VERSION` は上げない。
- NDLOCR-Lite の版を上げるときは、submodule のコミットを新しいタグに移し、D8 の結合テストと 10 枚の比較を取り直す。
- 元に戻す（NDLOCR-Lite をやめる）ときは、既定のエンジンを戻し、`git submodule deinit vendor/ndlocr-lite` と `git rm vendor/ndlocr-lite`、
  足した 6 つの依存を `uv remove` する。

## Open Questions

- 低信頼度の閾値 0.7 が妥当か。手元 10 枚では本文の行は 0.9 前後、ページ番号などの短い行が 0.6〜0.75 だった。運用しながら調整する（設定で変えられる）。

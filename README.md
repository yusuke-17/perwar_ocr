# 戦前日本語OCR

戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。

OCR は国立国会図書館の [NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite)（CPU で動く OCR）、口語体変換は Ollama + qwen3.5 を
Mac のローカルで動かすことで、**データ漏洩ゼロ** で実現する。OCR エンジンは Ollama の GLM-OCR（OCR専用Vision LLM）にも切り替えられる。

## 前提条件

- Apple Silicon Mac（M1〜M4）
- RAM 16GB 以上推奨（8GBでも動作可能）
- Python 3.13 以上
- [Ollama](https://ollama.com/download/mac) がインストール済みであること
- [uv](https://docs.astral.sh/uv/) がインストール済みであること

## セットアップ

### 1. Ollama のインストール

https://ollama.com/download/mac からダウンロードし、Applications にドラッグして起動する。

### 2. モデルのダウンロード

```bash
# 口語体変換用モデル（必須）
ollama pull qwen3.5:9b

# OCR を GLM-OCR で行う場合だけ（既定の NDLOCR-Lite では不要）
ollama pull glm-ocr
```

### 3. NDLOCR-Lite（既定の OCR エンジン）の取得

NDLOCR-Lite は git の submodule として `vendor/ndlocr-lite` に置く（タグ 1.3.1 に固定。モデル込みで約 160MB）。
パッケージとしてではなく、ソースのまま使う（上流の配布設定の不具合で、インストールすると起動しないため）。

```bash
# これから clone するなら、submodule もまとめて取る
git clone --recurse-submodules --shallow-submodules <このリポジトリのURL>

# clone 済みなら、リポジトリのフォルダで次を実行する
git submodule update --init --depth 1
```

普通の `git clone` だけでは `vendor/ndlocr-lite` が空のままになる。その状態で OCR すると
「OCRエンジン未導入」のエラーになり、取得コマンドが表示される（`git pull` でも submodule の中身は更新されない）。

### 4. uv のインストールと依存パッケージの導入

```bash
# uv のインストール（未導入の場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存パッケージのインストール（このリポジトリのフォルダで実行）
cd prewar-ocr
uv sync
```

### 5. セットアップ確認

```bash
uv run prewar check
```

## 使い方

すべての機能は `prewar` コマンド1つに集約されている。**コマンドを覚えていなくても、引数なしで実行すれば対話メニューが出る**ので、矢印キーで選ぶだけでよい。

```bash
# 対話メニュー（OCR / 撮りため / 検索 / 口語体変換 / 差分表示 / データ整理 / 環境確認 を矢印キーで選択）
uv run prewar
```

慣れたらサブコマンドで直接実行もできる（速い）。

| やりたいこと | コマンド |
|------------|---------|
| 画像をOCR→現代語化 | `uv run prewar ocr input/画像.png` |
| 範囲スクショで撮りため | `uv run prewar shoot` |
| ライブラリを全文検索 | `uv run prewar search 関東大震災` |
| 検索インデックス更新 | `uv run prewar index` |
| ライブラリ統計 | `uv run prewar stat` |
| テキスト後処理（正規化/口語体化） | `uv run prewar fix output/x.txt` |
| 変換前後の差分を見る | `uv run prewar diff <ドキュメントID>` |
| データ整理（input 掃除 / 誤記録削除） | `uv run prewar clean input` / `uv run prewar clean library` |
| 環境確認 | `uv run prewar check` |

```bash
# OCR: 対話モード（input/ の画像を一覧から選択して実行）
uv run prewar ocr

# OCR: 画像を直接指定して実行
uv run prewar ocr input/画像.png
```

> 旧コマンド `prewar-ocr` / `prewar-library` は廃止した。次のように置き換える。
>
> | 旧コマンド | 新コマンド |
> |---|---|
> | `uv run prewar-ocr ...` | `uv run prewar ocr ...` |
> | `uv run prewar-ocr shoot ...` | `uv run prewar shoot ...` |
> | `uv run prewar-library find ...` | `uv run prewar search ...` |
> | `uv run prewar-library index` / `stat` | `uv run prewar index` / `uv run prewar stat` |

実行すると `library/{YYYY-MM-DD}_{画像名}/` フォルダが作られ、1回の処理結果が「1件の記録」として保存される。

### 範囲スクショで撮りため → 一括処理（macOS）

ブラウザ上の資料を範囲スクショで取り込む場合は `shoot` を使う。macOS標準の範囲選択（`screencapture -i`）で本文だけをドラッグして囲うため、ブラウザのUIや周辺本文がOCR対象に写り込まない。複数ページを撮りためてから最後にまとめて処理できる。

```bash
# 範囲スクショを繰り返し撮影 → 終了時にそのまま一括処理
uv run prewar shoot

# 撮るだけ（処理は後回し）
uv run prewar shoot --no-run

# 貯めたセッションフォルダを後からまとめて処理（1記録として保存）
uv run prewar ocr input/session_2026-05-31_103000/

# フォルダ内を画像ごとの別記録として処理
uv run prewar ocr input/session_2026-05-31_103000/ --separate
```

- 撮った画像は一時置き場 `input/session_{日時}/p001.png, p002.png ...` に撮った順（＝ページ順）で貯まる。
- 既定では1セッションを結合して「1件の長い文書」として保存する（同一資料の複数ページ撮影向け）。`--separate` で画像ごとの別記録に切り替えられる。
- セッションフォルダは処理後も残る（`library/` にコピー保存済み。撮り直し用に手元に残す。不要なら手動で削除）。
- `shoot` は macOS 専用。他OSでは画像を `input/` に置いてフォルダ/パス指定で処理する。

### 複数画像のページ順

複数の画像を1件の記録に結合するとき（フォルダ指定・対話メニューの複数選択・`shoot`）、ページは次の順に並ぶ。

- **既定はファイル名の自然順**。名前の数字を数値として比べるので、`1.png, 2.png, …, 10.png` は番号順になる（文字列順の `1, 10, 11, …, 2` にはならない）。`スクリーンショット … 9.05.03` と `… 10.05.03` のように時刻の桁数が違う名前や、同じ秒の ` (2)` 付きの名前も正しく並ぶ。
- 処理の前に、並び順を番号付きの一覧で表示する。取り違えに気づくため、OCR を始める前に見ておく。
- ファイル名順がファイルの**更新日時の順と食い違う**ときは警告を出す（最初に食い違う位置を表示）。フォルダ指定では警告を出して**そのまま続行**し、終了コードは変わらない。対話メニューでは「このまま進む / 更新日時の古い順に並べ替えて進む / やめる」を選べる。コピーなどで日時が変わっているだけなら、ファイル名順のままで正しい。
- ファイル名がページ順を表していないとき（英語の AM/PM 表記のスクショ名、漢数字、`IMG_9999` の次が `IMG_0001` に戻る連番など）は、`--order mtime` で**更新日時の古い順**に切り替える。日時が同じ画像どうしはファイル名の自然順になる。
- `shoot` で撮った画像は、並べ方の指定にかかわらず**撮った順**のまま処理する（警告も出ない）。

```bash
# 更新日時の古い順で結合（名前がページ順になっていないとき）
uv run prewar ocr input/scans/ --order mtime
```

`config.toml` の `[batch] order = "mtime"` で既定を変えることもできる（`--order` が優先）。

対象になる画像は `.png .jpg .jpeg .webp .bmp .tiff .tif`。名前が `.` で始まる隠しファイルと、フォルダは対象外。1ファイルに複数ページを持つ TIFF は先頭ページしか読まれない（NDLOCR-Lite の読み込みも、GLM-OCR で使う前処理も先頭ページだけ）ので、1ページ1ファイルにして使う。

### 出力フォーマット

```
library/
└── 2026-05-24_画像名/
    ├── source.png       元画像のコピー（複数枚なら source_01.png, source_02.png ...）
    ├── ocr_raw.txt      OCR生テキスト（正規化前）
    ├── modern.txt       現代語テキスト（最終成果物）
    └── meta.json        処理メタ情報（モデル・設定・処理時間）
```

`meta.json` には使用モデル・正規化設定・処理時間などが記録され、後から検索・再実行・修正の素材として使える。

### オプション

```bash
# 正規化（旧字体・仮名・誤読修正）をスキップ
uv run prewar ocr input/画像.png --no-normalize

# 口語体変換（LLMリライト）をスキップ
uv run prewar ocr input/画像.png --no-modernize

# 旧形式（output/{画像名}_modern.txt）も併せて出力
uv run prewar ocr input/画像.png --legacy-output

# ライブラリのルートディレクトリを変更
uv run prewar ocr input/画像.png --library-root mylib/

# ファイル保存せずコンソール出力のみ
uv run prewar ocr input/画像.png --no-save

# OCRエンジンを変更（既定は ndlocr-lite。Ollama のモデル名を書けば Ollama で読む）
uv run prewar ocr input/画像.png -m glm-ocr

# 撮影のみ行い処理は後回し（shoot と併用）
uv run prewar shoot --no-run

# フォルダ内を画像ごとの別記録として処理
uv run prewar ocr input/session_.../ --separate

# ページのOCRが失敗したらその場で中断する（既定は失敗ページを飛ばして続行）
uv run prewar ocr input/session_.../ --on-page-error abort
```

### 途中で失敗・中断したとき

大量のページを処理する途中で1枚失敗しても、**成功したページだけで記録を保存する**。
Ctrl+C で中断した場合も、そこまでの結果は保存される。

- スキップしたページは `meta.json` の `pages.skipped` に理由つきで残るので、
  あとからその画像だけ指定して処理し直せる
- 口語体変換（LLM）が失敗した場合は、正規化までのテキストを `modern.txt` に保存する
  （OCR結果は失われない）。失敗したチャンクは原文のまま残る
- Ollama が停止しているときなど、連続3回失敗したら残りのページを待たずに打ち切る
  （`config.toml` の `batch.abort_after_consecutive_failures` で変更可）
- Ollama が応答しなくなったページは 300 秒でタイムアウトし、`reason: "timeout"` として
  スキップされる（無限に待ち続けない）。`config.toml` の
  `ollama.generate_timeout_seconds` で変更でき、`0` にすると無制限に戻せる
- OCR エンジンが同じ内容を繰り返して Ollama に打ち切られたページは `reason: "repeat"` としてスキップされる。
  これは連続失敗の回数に**数えない**（Ollama 停止とは違い、次のページは成功しうるため）

### OCR エンジン（NDLOCR-Lite / GLM-OCR）

既定は NDLOCR-Lite。手元の 10 枚では GLM-OCR より正確で、失敗 0 枚・1 枚約 0.4 秒だった
（最初の 1 枚の前にモデルの読み込みが 2 秒ほどかかる。`survey/ndlocr-lite-survey.md`）。
GLM-OCR に戻すには、実行時に `-m glm-ocr` を付けるか、`config.toml` に次を書く。

```toml
[models]
ocr = "glm-ocr"   # 既定は "ndlocr-lite"
```

- **画像前処理（傾き補正・コントラスト強調など）は NDLOCR-Lite にはかけない**。前処理後の画像は認識の信頼度が下がり、
  字が欠けたページもあったため。`--no-preprocess`・`--binarize` と `[preprocess]` は GLM-OCR を選んだときだけ効く
- `--prompt` は NDLOCR-Lite では使わない（指定すると無視する旨が出る）
- NDLOCR-Lite の出力は、縦書きの列を文としてつなぎ、見出しや段落の終わり（短い列）と、横書きのページ番号などの前後で改行する。
  日本語に隣り合う半角空白は取り除く（字は変えない）
- 使ったエンジンは `meta.json` の `ocr.model` に、NDLOCR-Lite の版は `ocr.engine_version` に残る

| 画面の警告 | 意味 | 対処 |
|---|---|---|
| `⚠ … に認識の信頼度が低い行が N 行あります` | NDLOCR-Lite が自信のない行があった（既定は信頼度 0.7 未満）。ページ番号などの短い行に多い | `uv run prewar diff <doc_id>` で原文を確認する。閾値は `[ndlocr] low_confidence` で変えられる |
| `✗ OCRエンジン未導入` | `vendor/ndlocr-lite` が空、モデルが足りない、または依存パッケージが足りない | 表示どおり `git submodule update --init --depth 1` と `uv sync` を実行する |

信頼度の低い行があったページは `meta.json` の `ocr.low_confidence_lines`（ページ番号 → 行数）に残る（あったときだけ）。

#### NDLOCR-Lite の版を上げるとき

上流の内部関数を直接呼んでいるので、版を上げたら動作を確かめてからコミットする。

```bash
git -C vendor/ndlocr-lite fetch --depth 1 origin tag <新しいタグ>
git -C vendor/ndlocr-lite checkout <新しいタグ>
uv run pytest tests/ pkg/                  # 上流との結合テスト（tests/test_ndlocr_upstream.py）を含む
uv run prewar check                        # 新しい版が表示されること
# 手元の画像をいくつか読み、前の版の記録と prewar diff などで比べてから
git add vendor/ndlocr-lite
git commit -m "NDLOCR-Liteを<新しいタグ>に更新"
```

モデルのファイル名が変わった版では、`utils/ndlocr_client.py` のモデル名（v1.3.1 の CLI の既定値を写したもの）も直す。

### OCRの反復対策と警告（GLM-OCR）

GLM-OCR（Ollama 経由のエンジン）を選んだときの話。NDLOCR-Lite の出力には反復の切り落としも生成上限も適用しない。

glm-ocr は縦書き・旧字体の資料で、読み終えたあとも同じ内容を延々と繰り返すことがある。
そのため OCR の結果は自動で次のように扱う。

| 画面の警告 | 意味 | 対処 |
|---|---|---|
| `⚠ 反復を検知し、… 末尾 N 字を切り落としました` | 繰り返しが始まった所から後ろを捨てた。ページの本文は冒頭にまとまっているので、普通は欠けていない | 不要。気になるときは記録の `ocr_raw.txt` を確認する |
| `⚠ … は生成上限（1024 トークン）に達しました` | 1ページで生成する量の上限に達して止まった | 反復の警告も出ていれば問題ない。**上限の警告だけ**が出たら本当に長いページなので、`[ocr] num_predict` を増やす |
| `✗ 反復による打ち切り` | 繰り返しを Ollama が検知し、そのページの出力を捨てた | そのページだけ処理し直す。直らないことが多い |

反復の判定は「前の行と同じ行」「30字以上で95%以上似ている行（繰り返すたびに似た字へ読み違えるため）」
「1行の中で再び現れる20字以上の同じ文字列」のうち最初のもの。切り落とした字数は `meta.json` の
`ocr.repetition_trimmed`（ページ番号 → 字数）、上限に達したページは `ocr.hit_limit_pages` に残る（どちらも起きたときだけ）。

```toml
[ocr]
num_predict = 1024    # 1ページの生成トークン数の上限（既定）。0で無制限（1枚55秒ほどかかる）
retry_on_repeat = 0   # 反復による打ち切りのあと、シードを変えて再試行する回数（既定0）
                      # temperature = 0 ではシードが効かないので、使うなら temperature も上げる
```

`prewar check` には Ollama のバージョンが出る。Ollama.app は自動更新されるので、
ある日から反復による打ち切りが増えた・減ったといった変化の切り分けに使える。

### OCRの再現性

OCR は `temperature = 0` で実行するため、同じ画像・同じモデルなら結果が安定する。
どの設定で読み取ったかは `meta.json` の `ocr.options` に残る。
読み取りが硬すぎると感じる場合は `config.toml` に次を書けば戻せる。

```toml
[ocr]
temperature = 0.3
```

終了コードで結果を判別できる（スクリプトから使う場合）:

| コード | 意味 |
|--------|------|
| `0` | 全ページ成功 |
| `2` | 一部が欠けたが、成功分は保存済み |
| `1` | 保存物なし（全ページ失敗・入力エラー） |

## ライブラリ検索

`library/` に溜まった文書を全文検索する。SQLite FTS5 + trigram tokenizer を使うため日本語の部分一致が効き、追加パッケージは不要（Python標準ライブラリのみ）。

### 検索インデックスの構築

```bash
# 差分更新（meta.json / modern.txt / ocr_raw.txt の mtime を見て変更分だけ更新）
uv run prewar index

# 全件再構築（インデックス破損時など）
uv run prewar index --rebuild
```

`modern.txt` や `ocr_raw.txt` を手で修正した場合も差分更新で拾われる。

### キーワード検索

```bash
# 単一語
uv run prewar search 関東大震災

# 複数語スペース区切り = AND（両方を含む文書のみヒット）
uv run prewar search 関東大震災 警察報告

# OR = いずれかを含む
uv run prewar search 関東大震災 OR 大阪府庁

# NOT 以降 = 除外（複数書けば「そのいずれかを含む文書」を除く）
uv run prewar search 関東大震災 NOT 大阪府庁 横浜港

# 一致対象を限定（原文 / 口語 / 題名。全角コロンも可）
uv run prewar search 原文:罹災者

# 表示件数・抜粋の長さを変更（デフォルト 20件 / 40文字）
uv run prewar search 関東大震災 --limit 50 --snippet 64

# JSON 出力（パイプ処理用）
uv run prewar search 関東大震災 --format json
```

#### 検索構文まとめ

| 書き方 | 意味 |
|---|---|
| `語 語` | すべてを含む（AND） |
| `語 OR 語` | いずれかを含む（OR） |
| `語 NOT 語` | NOT 以降を除外 |
| `原文:語` | 一致対象を限定（`原文`/`口語`/`題名`、英語名 `original`/`modern`/`title` も可） |

`OR` は**モード切替**として働く。語群のどこかに1つでも `OR` があれば、その群は全体が OR
結合になる（AND と OR の混在はできない）。こうすることで FTS5 本来の演算子優先順位
（`NOT` > `AND` > `OR`）が結果に現れず、「AND か OR か」の二択だけを意識すればよくなる。

除外語だけのクエリ（`NOT 大阪府庁` のみ）は検索できない。FTS5 の `NOT` は二項演算子で、
「全件から引く」という式が書けないため。

### 検索対象 ― 原文の語でも引ける

インデックスには3つが入る。**口語化で言い換えられた語も、原文の語で検索できる。**

| 対象 | 中身 |
|---|---|
| `title` | `meta.json` の題名（正規化して索引。表示は元のまま） |
| `modern` | `modern.txt`（LLM口語化後のテキスト） |
| `original` | `ocr_raw.txt` を正規化したテキスト（＝正規化済み原文） |

原文は索引時に正規化される（旧字体→新字体、変体仮名→現代ひらがな、歴史的仮名遣い→現代仮名遣い、カタカナ助詞→ひらがな）ので、**現代表記のクエリで旧字体の原文が引ける**。

```
# 原文「罹災者ノ數ハ數十萬ニ達シ」→ 口語化後「被災者の数は数十万に達し」
uv run prewar search 罹災者      # ヒットする（原文にのみ存在する語）
uv run prewar search 被災者      # ヒットする（口語化後にのみ存在する語）
uv run prewar search 関東大震災  # ヒットする（原文が「關東大震災」でも可）
```

抜粋（スニペット）は**実際に一致した本文**から出る。一致箇所は端末では色が付き、
どの対象に何箇所当たったかが表示される。原文にだけ一致した場合は注記が付く:

```
[2026-01-01_shinsai] 關東大震災ノ記錄
  場所: library/2026-01-01_shinsai/
  抜粋: …罹災者の数は数十万に達し…
  一致: 原文1  ← 原文のみ一致：口語化で語が変わっています
  作成: 2026-01-01T00:00:00+09:00
```

色は `--no-color` / `NO_COLOR` 環境変数 / 設定 `search.color` / パイプ・リダイレクト
（出力先が端末でない）のいずれかで自動的に外れる。色を外しても本文は変わらない。

`--format json` の各件には次が載る:

| フィールド | 中身 |
|---|---|
| `matched_fields` | 一致した対象の一覧（`title` / `modern` / `original`） |
| `match_counts` | 対象ごとの一致箇所数 |
| `snippet` | 装飾を含まない素の抜粋 |
| `snippet_highlights` | 一致箇所の `[開始, 終了)` 位置（`snippet` 内の文字インデックス） |

並び順は内部の関連度（bm25）で決まるが、その値は表示しない。trigram かつ語彙の偏った
小規模な資料集では、頻出語のスコアが全件ほぼ同値に潰れて序列にならないため
（実測: 200件中196件ヒットで最良・最悪とも -0.000）。代わりに一致箇所数を出している。

> ⚠️ trigram の仕様上、検索語は **3文字以上**が必要（2文字以下は警告して中断）。
> これは除外語・限定語にも等しく効く。

> ⚠️ 抜粋の長さの上限は 64 文字（SQLite の `snippet()` の仕様による）。
> 超える指定は上限に丸められる。

> 💡 インデックスの形式が変わったときは、次回の検索・更新時に自動で作り直される（メッセージが出る）。資料ファイルには一切触れない。

### ライブラリ統計

```bash
uv run prewar stat
```

文書数・インデックスサイズ・最終更新日が表示される。

## 変換前後の差分表示

OCR 結果がどう書き換えられたかを、2段階に分けて色付きで表示する。
特に LLM による口語化で語が勝手に変わった箇所（誤変換）を目視で見つけるために使う。

| 段階 | 比べるもの |
|---|---|
| 1 | OCR生テキスト → 正規化後（旧字体・仮名の機械変換） |
| 2 | 正規化後 → `modern.txt`（LLM による口語化） |

```bash
uv run prewar diff 2026-05-24_画像名             # 2段階とも表示
uv run prewar diff 2026-05-24_画像名 --stage 2   # LLM変換だけ
uv run prewar diff 2026-05-24_画像名 --no-color  # 色なし（[-削除-]{+追加+} 表記）
uv run prewar diff 2026-05-24_画像名 --context 0 # 全文表示
```

## データ整理

```bash
# input/ の処理済み画像・セッションフォルダを掃除（library の記録には影響しない）
uv run prewar clean input

# 誤った記録を library/ から削除し、検索インデックスからも消す
uv run prewar clean library                     # 一覧から選ぶ
uv run prewar clean library 2026-05-24_画像名    # ドキュメントIDを指定
```

削除はゴミ箱を経由しない完全削除で、実行前に必ず確認を求める（`--yes` で省略）。

## フォルダ構成

| 場所 | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `library/` | 処理結果の蓄積先（1文書＝1フォルダ） |
| `output/` | `--legacy-output` 指定時の旧形式出力先 |
| `scripts/` | CLI（統合コマンド `prewar` と各サブコマンドの中身） |
| `utils/` | OCR・正規化・口語体変換・ライブラリ保存などのユーティリティ |
| `vendor/ndlocr-lite/` | NDLOCR-Lite のソースとモデル（git submodule。`git submodule update --init --depth 1` で取得） |
| `pkg/senzen_word/` | 旧字体・仮名変換ライブラリ（自作PyPIパッケージ） |
| `tests/` | テスト（`uv run pytest tests/ pkg/`） |
| `config.toml` | 設定の上書き（既定値から変えたい値だけを書く） |
| `openspec/` | 仕様（`specs/`）と進行中の変更（`changes/`） |
| `plan/` | 改善案のバックログ |
| `survey/` | 調査レポート |

## ライセンスと出典

- OCR エンジンとして、国立国会図書館が公開する [NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite)（v1.3.1）を使用している。
  NDLOCR-Lite は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja) で公開されている（出典: 国立国会図書館「NDLOCR-Lite」）。
  ソースには手を加えていない。実行時に使うライブラリのライセンスは `vendor/ndlocr-lite/LICENCE_DEPENDENCEIES` を参照
- NDLOCR-Lite のレイアウト認識モデルは DEIMv2（Apache License 2.0）で、Meta の DINOv3 を基にしているため、
  その利用には DINOv3 のライセンスの条件も適用される（`survey/ndlocr-lite-survey.md`）

# 戦前日本語文書 OCR プロジェクト — 学習ロードマップ

## 🎯 ゴール
戦前の日本語文書画像 → OCR読み取り → 現代日本語テキストファイル出力

---

## プロジェクト構成

```
prewar-ocr/
├── input/                  # 入力画像を置くフォルダ
├── output/                 # 出力テキストを保存するフォルダ
├── models/                 # 学習済みモデル・カスタムモデル
├── training_data/          # 学習データ（画像＋正解テキスト）
│   ├── images/
│   └── labels/
├── scripts/
│   ├── preprocess.py       # Step 2: 画像前処理
│   ├── ocr_basic.py        # Step 3: 基本OCR実行
│   ├── postprocess.py      # Step 4: 後処理（旧字体→新字体等）
│   ├── train_custom.py     # Step 5: カスタムモデル学習
│   └── pipeline.py         # Step 6: 全体パイプライン統合
├── utils/
│   ├── char_converter.py   # 旧字体→新字体 変換辞書
│   └── kana_converter.py   # 歴史的仮名遣い→現代仮名遣い
├── requirements.txt
└── README.md
```

---

## 学習ロードマップ（6ステップ）

### Step 1: 環境構築（所要時間: 1〜2時間）

**学べること:** Python仮想環境、PaddlePaddleフレームワーク

```bash
# 仮想環境を作成
python -m venv prewar-ocr-env
source prewar-ocr-env/bin/activate  # Mac/Linux
# prewar-ocr-env\Scripts\activate   # Windows

# PaddlePaddle（CPU版）をインストール
pip install paddlepaddle
# GPU版が使える場合: pip install paddlepaddle-gpu

# PaddleOCR をインストール
pip install paddleocr

# その他必要なライブラリ
pip install opencv-python Pillow numpy
```

**確認テスト:**
```python
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls=True, lang='japan')
print("セットアップ完了！")
```

---

### Step 2: 画像前処理を学ぶ（所要時間: 3〜5時間）

**学べること:** OpenCV基礎、画像処理の考え方

戦前文書は劣化・ノイズが多いため、前処理が精度に大きく影響します。

**主な前処理テクニック:**

| テクニック | 効果 | 使う関数 |
|---|---|---|
| グレースケール変換 | 色情報を除去 | `cv2.cvtColor()` |
| 二値化（大津の方法） | 文字と背景を分離 | `cv2.threshold()` |
| 適応的二値化 | ムラのある画像に対応 | `cv2.adaptiveThreshold()` |
| ノイズ除去 | 小さなゴミを除去 | `cv2.fastNlMeansDenoising()` |
| 傾き補正 | 斜めの文書をまっすぐに | `cv2.getRotationMatrix2D()` |
| コントラスト調整 | 薄い文字を読みやすく | `cv2.convertScaleAbs()` |

**サンプルコード（`scripts/preprocess.py`）:**
```python
import cv2
import numpy as np

def preprocess_image(image_path):
    """戦前文書用の画像前処理"""
    # 画像読み込み
    img = cv2.imread(image_path)

    # グレースケール変換
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # コントラスト調整（古い文書の薄い文字対策）
    alpha = 1.5  # コントラスト係数（1.0〜3.0で調整）
    beta = 0     # 明るさ調整
    enhanced = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)

    # ノイズ除去
    denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

    # 適応的二値化（ムラのある古い文書に最適）
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,  # 奇数で調整
        C=2
    )

    return binary

if __name__ == "__main__":
    result = preprocess_image("input/sample.jpg")
    cv2.imwrite("output/preprocessed.jpg", result)
    print("前処理完了！")
```

---

### Step 3: PaddleOCRで基本的なOCRを実行（所要時間: 2〜3時間）

**学べること:** PaddleOCRの仕組み（検出→方向分類→認識の3段階）

**PaddleOCRの3段階パイプライン:**
1. **テキスト検出（Detection）** — 画像のどこに文字があるかを検出
2. **方向分類（Angle Classification）** — 文字の向きを判定
3. **テキスト認識（Recognition）** — 検出した領域の文字を読み取り

```python
from paddleocr import PaddleOCR
import cv2

def run_ocr(image_path, preprocessed=True):
    """PaddleOCRで文字を読み取る"""
    # OCRインスタンスの作成
    ocr = PaddleOCR(
        use_angle_cls=True,  # 文字の向き検出を有効に
        lang='japan',         # 日本語モデルを使用
        use_gpu=False         # GPUがあればTrueに
    )

    # 前処理済み画像でOCRを実行
    result = ocr.ocr(image_path, cls=True)

    # 結果を整形
    extracted_text = []
    for line in result:
        for word_info in line:
            bbox = word_info[0]       # 文字の位置（座標）
            text = word_info[1][0]    # 認識されたテキスト
            confidence = word_info[1][1]  # 信頼度（0〜1）
            extracted_text.append({
                'text': text,
                'confidence': confidence,
                'bbox': bbox
            })
            print(f"[信頼度 {confidence:.2f}] {text}")

    return extracted_text

if __name__ == "__main__":
    results = run_ocr("output/preprocessed.jpg")
```

---

### Step 4: 後処理 — 旧字体→新字体・仮名遣い変換（所要時間: 5〜8時間）

**学べること:** テキスト処理、辞書ベースの変換、正規表現

これがこのプロジェクトの核心部分です。OCRが正しく旧字体を読んでも、
そのままでは現代の読者には読みにくいため、変換処理が必要です。

**4-a: 旧字体→新字体変換**
```python
# utils/char_converter.py

# 旧字体→新字体の辞書（代表例、実際は数百文字）
OLD_TO_NEW_KANJI = {
    '國': '国', '學': '学', '會': '会', '權': '権',
    '點': '点', '當': '当', '體': '体', '發': '発',
    '變': '変', '廣': '広', '氣': '気', '號': '号',
    '區': '区', '寫': '写', '聲': '声', '實': '実',
    '圖': '図', '從': '従', '條': '条', '獨': '独',
    '佛': '仏', '黨': '党', '經': '経', '關': '関',
    '證': '証', '醫': '医', '臺': '台', '齒': '歯',
    '鐵': '鉄', '辯': '弁', '舊': '旧', '靈': '霊',
    '觀': '観', '歷': '歴', '戰': '戦', '獻': '献',
    '總': '総', '廳': '庁', '藝': '芸', '檢': '検',
    '澤': '沢', '戀': '恋', '龍': '竜', '瀧': '滝',
    # ... 完全版は数百エントリ
    # 参考: Unicode CJK Compatibility Ideographs
}

def convert_old_to_new_kanji(text):
    """旧字体を新字体に変換する"""
    for old, new in OLD_TO_NEW_KANJI.items():
        text = text.replace(old, new)
    return text
```

**4-b: 歴史的仮名遣い→現代仮名遣い**
```python
# utils/kana_converter.py
import re

# 歴史的仮名遣い→現代仮名遣い（代表的なルール）
KANA_RULES = [
    # ゐ/ヰ → い/イ
    ('ゐ', 'い'), ('ヰ', 'イ'),
    # ゑ/ヱ → え/エ
    ('ゑ', 'え'), ('ヱ', 'エ'),
    # 語中・語尾の「は行」転呼
    # 例: 言ふ→言う、思ひ→思い
    # ※これは単純置換では不完全。辞書ベースが望ましい
    ('ふ$', 'う'),   # 語尾の「ふ」→「う」
    ('ひ$', 'い'),   # 語尾の「ひ」→「い」
    ('へ$', 'え'),   # 語尾の「へ」→「え」（助詞を除く）
    ('ほ$', 'お'),   # 語尾の「ほ」→「お」
]

def convert_historical_kana(text):
    """歴史的仮名遣いを現代仮名遣いに変換（簡易版）"""
    # 単純な文字置換
    text = text.replace('ゐ', 'い')
    text = text.replace('ヰ', 'イ')
    text = text.replace('ゑ', 'え')
    text = text.replace('ヱ', 'エ')

    # 注意: は行転呼の完全な変換には
    # 形態素解析（MeCab等）との組み合わせが必要
    return text
```

**4-c: カタカナ文→ひらがな混じり文への変換（公文書向け）**
```python
def katakana_to_modern(text):
    """戦前公文書のカタカナ文を現代的な表記に変換（簡易版）
    例: 「コレハ重要ナル事項ナリ」→「これは重要なる事項なり」
    注意: 完全な変換には形態素解析が必要
    """
    # カタカナ→ひらがな変換テーブル
    result = []
    for char in text:
        code = ord(char)
        # カタカナ範囲（ァ〜ヶ）をひらがなに変換
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return ''.join(result)
```

---

### Step 5: モデルのカスタム学習（所要時間: 1〜2週間）

**学べること:** ディープラーニング基礎、データセット作成、学習ループ

ここが「AI学習」の本丸です。PaddleOCRの認識モデルを
戦前の日本語文書に特化してファインチューニングします。

**5-a: 学習データの準備**

最低でも数百〜数千の画像-テキストペアが必要です。

```
training_data/
├── images/
│   ├── 0001.jpg    # 文字領域を切り出した画像
│   ├── 0002.jpg
│   └── ...
└── labels/
    └── train.txt   # ラベルファイル
```

`train.txt`の形式:
```
images/0001.jpg	帝國議會
images/0002.jpg	大日本帝國憲法
images/0003.jpg	文部省告示
```

**5-b: 学習データの作り方（3つの方法）**

1. **手動アノテーション（最も確実）**
   - 戦前文書の画像から文字領域を切り出し
   - 正解テキストを人手で入力
   - 時間はかかるが精度は最高

2. **合成データ生成（効率的）**
   - 旧字体フォントを使って画像を自動生成
   - ノイズや劣化を加えて戦前文書風にする
   ```python
   from PIL import Image, ImageDraw, ImageFont
   import random

   def generate_training_image(text, font_path, size=(256, 64)):
       img = Image.new('L', size, 255)
       draw = ImageDraw.Draw(img)
       font = ImageFont.truetype(font_path, 32)
       draw.text((10, 10), text, font=font, fill=0)
       # ノイズ追加でリアルに
       # ... （省略）
       return img
   ```

3. **既存データセット活用**
   - CODH（人文学オープンデータ共同利用センター）の
     くずし字データセットなどを活用

**5-c: ファインチューニング実行**

```bash
# PaddleOCRリポジトリをクローン
git clone https://github.com/PaddlePaddle/PaddleOCR.git
cd PaddleOCR

# 設定ファイルを編集（日本語認識モデル）
# configs/rec/PP-OCRv4/以下の設定ファイルをベースに
# - 学習データのパスを変更
# - 文字辞書を旧字体含むものに拡張
# - バッチサイズ等をPC性能に合わせ調整

# 学習開始
python tools/train.py -c configs/rec/your_custom_config.yml
```

**重要な学習パラメータ:**
| パラメータ | 初心者おすすめ値 | 説明 |
|---|---|---|
| learning_rate | 0.0001 | ファインチューニングなので小さめ |
| epoch_num | 50〜100 | データ量次第で調整 |
| batch_size | 16〜32 | メモリに合わせて |
| pretrained_model | 日本語v4 | PaddleOCRの既存モデル |

---

### Step 6: パイプライン統合（所要時間: 3〜5時間）

**学べること:** ソフトウェア設計、モジュール統合

Step 2〜5を1つのパイプラインにまとめます。

```python
# scripts/pipeline.py

import sys
import os
from preprocess import preprocess_image
from ocr_basic import run_ocr
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.char_converter import convert_old_to_new_kanji
from utils.kana_converter import convert_historical_kana

def process_document(image_path, output_path):
    """戦前文書画像を現代日本語テキストに変換する"""

    print(f"処理開始: {image_path}")

    # Step 1: 画像前処理
    print("  [1/4] 画像前処理...")
    preprocessed = preprocess_image(image_path)
    temp_path = "temp_preprocessed.jpg"
    import cv2
    cv2.imwrite(temp_path, preprocessed)

    # Step 2: OCR実行
    print("  [2/4] OCR実行...")
    ocr_results = run_ocr(temp_path)

    # Step 3: テキスト結合（信頼度でフィルタリング）
    raw_text = ""
    for item in ocr_results:
        if item['confidence'] > 0.5:  # 信頼度50%以上のみ採用
            raw_text += item['text'] + "\n"

    print(f"  [3/4] OCR結果（原文）:\n{raw_text[:200]}...")

    # Step 4: 後処理（旧字体→新字体、仮名遣い変換）
    print("  [4/4] 後処理（現代語変換）...")
    modern_text = convert_old_to_new_kanji(raw_text)
    modern_text = convert_historical_kana(modern_text)

    # 出力
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(modern_text)

    print(f"完了！出力: {output_path}")
    return modern_text

if __name__ == "__main__":
    process_document("input/sample.jpg", "output/result.txt")
```

---

## 📚 学習リソース

| リソース | 内容 | URL |
|---|---|---|
| PaddleOCR公式ドキュメント | インストール・使い方 | https://github.com/PaddlePaddle/PaddleOCR |
| PaddleOCR日本語モデル | 既存の日本語対応 | PaddleOCR model list参照 |
| CODH くずし字データ | 学習用データセット | https://codh.rois.ac.jp/ |
| OpenCV公式チュートリアル | 画像処理の基礎 | https://docs.opencv.org/ |
| 文化庁 常用漢字表 | 新旧字体対応表 | 文化庁サイト |

---

## ⏱ 全体スケジュール目安

| ステップ | 期間 | 難易度 |
|---|---|---|
| Step 1: 環境構築 | 1〜2時間 | ★☆☆☆☆ |
| Step 2: 画像前処理 | 3〜5時間 | ★★☆☆☆ |
| Step 3: 基本OCR | 2〜3時間 | ★★☆☆☆ |
| Step 4: 後処理 | 5〜8時間 | ★★★☆☆ |
| Step 5: モデル学習 | 1〜2週間 | ★★★★☆ |
| Step 6: 統合 | 3〜5時間 | ★★★☆☆ |

**合計: 約2〜4週間**（学習ペース次第）

Step 1〜4までで実用的なツールが完成します。
Step 5のモデル学習は精度をさらに上げたい場合に取り組んでください。

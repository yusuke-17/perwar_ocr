# 戦前日本語文書 OCR プロジェクト — 修正版ロードマップ

## 🎯 ゴール
戦前の日本語公文書画像 → ローカルOCR読み取り → 現代日本語テキストファイル出力

## ⚠️ 制約条件
- **M1/M2/M3 Mac**（NVIDIA GPUなし）
- **資料の外部送信禁止** → クラウドOCR API（Google Vision等）は使えない
- **対象文書の特徴:**
  - 旧字体の漢字（國→国、學→学など）
  - カタカナ仮名遣い（公文書）
  - 歴史的仮名遣い（「言ふ」「ウヰスキー」など）
  - 右横書きを含む

---

## プロジェクト構成

```
prewar-ocr/
├── input/                  # 入力画像を置くフォルダ
├── output/                 # 出力テキストを保存するフォルダ
├── models/                 # 学習済みモデル・カスタムモデル
├── scripts/
│   ├── preprocess.py       # Step 2: 画像前処理
│   ├── ocr_compare.py      # Step 3: OCR比較テスト
│   ├── ocr_engine.py       # Step 3: OCRエンジン統合
│   ├── postprocess.py      # Step 4: 後処理（旧字体→新字体等）
│   └── pipeline.py         # Step 5: 全体パイプライン統合
├── utils/
│   ├── char_converter.py   # 旧字体→新字体 変換辞書
│   └── kana_converter.py   # 歴史的仮名遣い→現代仮名遣い
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 学習ロードマップ（5ステップ）

### Step 1: 環境構築 + OCRエンジン選定

**学べること:** Python仮想環境、複数OCRライブラリの比較評価

#### 1-a: 3つのOCRエンジンをインストール

```bash
# 仮想環境を作成
python -m venv prewar-ocr-env
source prewar-ocr-env/bin/activate

# --- OCRエンジン① Surya OCR（★最有力候補）---
# PyTorchベース、M1 Macネイティブ対応、90言語以上対応
pip install surya-ocr

# --- OCRエンジン② PaddleOCR ---
# M1 Macでも動作可能（一部注意点あり）
pip install paddlepaddle paddleocr

# --- OCRエンジン③ Tesseract OCR ---
# 古くからある定番。Homebrewでインストール
brew install tesseract tesseract-lang
pip install pytesseract

# --- 共通ライブラリ ---
pip install opencv-python-headless Pillow numpy
```

#### 1-b: 各エンジンの動作確認

```python
# Surya OCR の動作確認
from surya.recognition import RecognitionPredictor
predictor = RecognitionPredictor()
print("Surya OCR セットアップ完了！")

# PaddleOCR の動作確認
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls=True, lang='japan')
print("PaddleOCR セットアップ完了！")

# Tesseract の動作確認
import pytesseract
print(pytesseract.get_languages())  # 'jpn' が含まれていればOK
print("Tesseract セットアップ完了！")
```

#### なぜ3つ試すのか？

| OCRエンジン | 強み | 弱み | 戦前文書との相性 |
|---|---|---|---|
| **Surya OCR** | M1最適化、高精度、多言語対応 | 戦前文書に特化していない | ★★★ 要検証 |
| **PaddleOCR** | 日本語モデルあり、縦書き対応 | M1で動作不安定な場合あり | ★★☆ 現代語向け |
| **Tesseract** | 安定動作、カスタム辞書対応 | 深層学習モデルより精度低め | ★★☆ 補助的 |

**戦前文書に完璧に対応するローカルOCRは現時点で存在しない**ため、
複数エンジンを試して最適なものを見つけるのがベストです。

> **参考:** NDLOCR（国立国会図書館OCR）が最も精度が高い（明治期文書で約95%）が、
> NVIDIA GPU必須のため M1 Mac では直接使えない。
> 将来的にGPU環境が用意できれば、NDLOCRへの移行も検討。

---

### Step 2: 画像前処理を学ぶ

**学べること:** OpenCV基礎、画像処理の考え方

戦前文書は劣化・ノイズが多いため、前処理が精度に大きく影響します。

#### 主な前処理テクニック

| テクニック | 効果 | 使う関数 |
|---|---|---|
| グレースケール変換 | 色情報を除去 | `cv2.cvtColor()` |
| 二値化（大津の方法） | 文字と背景を分離 | `cv2.threshold()` |
| 適応的二値化 | ムラのある画像に対応 | `cv2.adaptiveThreshold()` |
| ノイズ除去 | 小さなゴミを除去 | `cv2.fastNlMeansDenoising()` |
| 傾き補正 | 斜めの文書をまっすぐに | `cv2.getRotationMatrix2D()` |
| コントラスト調整 | 薄い文字を読みやすく | `cv2.convertScaleAbs()` |
| **右横書き反転** | **右→左の横書きを左→右に** | **`cv2.flip()`** |

#### サンプルコード（`scripts/preprocess.py`）

```python
import cv2
import numpy as np

def preprocess_image(image_path, right_to_left=False):
    """戦前文書用の画像前処理"""
    # 画像読み込み
    img = cv2.imread(image_path)

    # 右横書きの場合、左右反転してOCRに渡す
    if right_to_left:
        img = cv2.flip(img, 1)  # 水平反転

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
    result = preprocess_image("input/sample.jpg", right_to_left=True)
    cv2.imwrite("output/preprocessed.jpg", result)
    print("前処理完了！")
```

---

### Step 3: OCR比較テスト＋最適エンジン選定

**学べること:** 複数ツールの比較評価、OCRの仕組み（検出→認識）

ここが**最も重要なステップ**です。
実際の戦前文書画像を使って、3つのOCRエンジンの精度を比較します。

#### 3-a: 比較テストスクリプト

```python
# scripts/ocr_compare.py

from paddleocr import PaddleOCR
import pytesseract
from PIL import Image
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor

def test_surya(image_path):
    """Surya OCRでテスト"""
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor()
    image = Image.open(image_path)
    # Surya OCRの実行（APIは最新版に合わせて調整が必要）
    from surya.pipeline import OCRPipeline
    pipeline = OCRPipeline(det_predictor=det_predictor, rec_predictor=rec_predictor)
    results = pipeline([image], languages=[["ja"]])
    text = "\n".join([line.text for line in results[0].text_lines])
    return text

def test_paddleocr(image_path):
    """PaddleOCRでテスト"""
    ocr = PaddleOCR(use_angle_cls=True, lang='japan', use_gpu=False)
    result = ocr.ocr(image_path, cls=True)
    texts = []
    for line in result:
        for word_info in line:
            texts.append(word_info[1][0])
    return "\n".join(texts)

def test_tesseract(image_path):
    """Tesseractでテスト（日本語＋縦書き）"""
    img = Image.open(image_path)
    # jpn: 日本語、jpn_vert: 日本語縦書き
    text = pytesseract.image_to_string(img, lang='jpn+jpn_vert')
    return text

if __name__ == "__main__":
    image_path = "output/preprocessed.jpg"

    print("=" * 50)
    print("【Surya OCR の結果】")
    print("=" * 50)
    print(test_surya(image_path))

    print("\n" + "=" * 50)
    print("【PaddleOCR の結果】")
    print("=" * 50)
    print(test_paddleocr(image_path))

    print("\n" + "=" * 50)
    print("【Tesseract の結果】")
    print("=" * 50)
    print(test_tesseract(image_path))
```

#### 3-b: 比較のチェックポイント

テスト結果を以下の観点で比較してください:

- [ ] 旧字体の漢字は正しく読めているか？（例: 「國」「學」）
- [ ] カタカナの認識精度は？
- [ ] 句読点や記号の認識は？
- [ ] 縦書き・右横書きの読み順は正しいか？
- [ ] 信頼度スコアは十分か？

**この結果を見て、メインで使うエンジンを1〜2個に絞ります。**

---

### Step 4: 後処理 — 旧字体→新字体・仮名遣い変換

**学べること:** テキスト処理、辞書ベースの変換、正規表現

OCRが正しく旧字体を読んでも、そのままでは現代の読者には読みにくいため、
変換処理が必要です。**このプロジェクトの核心部分**です。

#### 4-a: 旧字体→新字体変換

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

#### 4-b: 歴史的仮名遣い→現代仮名遣い

```python
# utils/kana_converter.py

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

#### 4-c: カタカナ文→ひらがな混じり文への変換（公文書向け）

```python
def katakana_to_modern(text):
    """戦前公文書のカタカナ文を現代的な表記に変換（簡易版）
    例: 「コレハ重要ナル事項ナリ」→「これは重要なる事項なり」
    注意: 完全な変換には形態素解析が必要
    """
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

#### 4-d: 右横書きテキストの反転

```python
def reverse_rtl_lines(text):
    """右横書き（右→左）のテキストを左→右に並べ替える
    注意: 画像レベルで反転する方が確実（Step 2参照）
    """
    lines = text.split('\n')
    reversed_lines = [line[::-1] for line in lines]
    return '\n'.join(reversed_lines)
```

---

### Step 5: パイプライン統合

**学べること:** ソフトウェア設計、モジュール統合

Step 2〜4を1つのパイプラインにまとめます。

```python
# scripts/pipeline.py

import sys
import os
import cv2

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from scripts.preprocess import preprocess_image
from utils.char_converter import convert_old_to_new_kanji
from utils.kana_converter import convert_historical_kana

def process_document(image_path, output_path, right_to_left=False):
    """戦前文書画像を現代日本語テキストに変換する"""

    print(f"処理開始: {image_path}")

    # Step 1: 画像前処理
    print("  [1/4] 画像前処理...")
    preprocessed = preprocess_image(image_path, right_to_left=right_to_left)
    temp_path = "temp_preprocessed.jpg"
    cv2.imwrite(temp_path, preprocessed)

    # Step 2: OCR実行（Step 3で選定したエンジンを使用）
    print("  [2/4] OCR実行...")
    # ※ここは Step 3 の比較結果に基づいて最適なエンジンを選択
    from scripts.ocr_engine import run_ocr
    ocr_results = run_ocr(temp_path)

    # Step 3: テキスト結合
    raw_text = "\n".join(ocr_results)
    print(f"  [3/4] OCR結果（原文）:\n{raw_text[:200]}...")

    # Step 4: 後処理（旧字体→新字体、仮名遣い変換）
    print("  [4/4] 後処理（現代語変換）...")
    modern_text = convert_old_to_new_kanji(raw_text)
    modern_text = convert_historical_kana(modern_text)

    # 出力
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(modern_text)

    # 一時ファイルを削除
    if os.path.exists(temp_path):
        os.remove(temp_path)

    print(f"完了！出力: {output_path}")
    return modern_text

if __name__ == "__main__":
    process_document(
        "input/sample.jpg",
        "output/result.txt",
        right_to_left=True  # 右横書きの場合True
    )
```

---

## 📚 学習リソース

| リソース | 内容 | URL |
|---|---|---|
| Surya OCR | M1 Mac対応の高精度OCR | https://github.com/VikParuchuri/surya |
| PaddleOCR | 日本語対応OCR | https://github.com/PaddlePaddle/PaddleOCR |
| Tesseract OCR | 定番OCR（brew install） | https://github.com/tesseract-ocr/tesseract |
| NDLOCR | 国会図書館OCR（GPU必要） | https://github.com/ndl-lab/ndlocr_cli |
| NDL古典籍OCR-Lite | くずし字OCR（GPU不要） | https://github.com/ndl-lab/ndlkotenocr-lite |
| OpenCV公式 | 画像処理の基礎 | https://docs.opencv.org/ |
| CODH くずし字データ | 学習用データセット | https://codh.rois.ac.jp/ |
| JACAR | アジア歴史資料センター | https://www.jacar.go.jp/ |

---

## ⏱ 全体スケジュール目安

| ステップ | 期間 | 難易度 | 備考 |
|---|---|---|---|
| Step 1: 環境構築＋選定 | 2〜3時間 | ★☆☆☆☆ | 3エンジンのインストール |
| Step 2: 画像前処理 | 3〜5時間 | ★★☆☆☆ | OpenCV基礎 |
| Step 3: OCR比較テスト | 3〜5時間 | ★★★☆☆ | **最重要ステップ** |
| Step 4: 後処理 | 5〜8時間 | ★★★☆☆ | 旧字体→新字体変換 |
| Step 5: 統合 | 3〜5時間 | ★★☆☆☆ | パイプライン化 |

**合計: 約2〜3週間**（学習ペース次第）

---

## 🔮 将来の拡張（精度を上げたくなったら）

### オプションA: NVIDIA GPU環境を用意してNDLOCRを使う
- 最も精度が高い（明治期文書で約95%）
- クラウドGPUインスタンス（自分管理のサーバーなので外部送信にあたるか要確認）
- または NVIDIA GPU搭載のデスクトップPC

### オプションB: ファインチューニング
- Step 3で選んだOCRエンジンを戦前文書用にカスタム学習
- 数百〜数千の画像-テキストペアが必要
- PaddleOCRの場合、PaddleOCRリポジトリのファインチューニング手順に従う

### オプションC: 複数OCRの結果を組み合わせ（アンサンブル）
- 複数エンジンの結果を比較し、多数決や信頼度ベースで最終テキストを決定
- 単独エンジンより高い精度が期待できる

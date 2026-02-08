# 戦前日本語文書OCR調査レポート（2025-2026年時点）

調査日：2026年2月8日

---

## 調査サマリー

**結論：戦前日本語のOCRには、文書の種類によって最適ツールが異なる**

- **活字の近代文書（明治～昭和初期）**: NDLOCR ver.2が最適
- **くずし字・古典籍（江戸期以前）**: NDL古典籍OCR-Lite または CODHのRURIモデル
- **汎用的な日本語OCR**: PaddleOCR（ただし戦前文書への特化はなし）

---

## 1. ローカル実行可能なOCRツール

### 1.1 NDLOCR（国立国会図書館OCR）★推奨

#### バージョン・更新日
- **最新版**: NDLOCR ver.2.1（2023年7月公開）
- 2022年4月にオープンソース化、2023年に改善版リリース

#### 要点
- **明治～昭和初期の活字資料に特化**した高精度OCR
- 旧字体・異体字・旧仮名遣いに対応
- **認識精度90%以上**（明治期で約90%、商用OCRは約40%）
- **完全ローカル実行可能**（Docker / WSL2 / Google Colabで動作）
- ライセンス：CC BY 4.0

#### インストール方法
```bash
# GitHubリポジトリからクローン
git clone https://github.com/ndl-lab/ndlocr_cli.git

# Dockerでの実行（推奨）
docker build -t ndlocr .
docker run ndlocr
```

Windows環境ではWSL2 + Ubuntuでの実行が可能。最新の環境構築手順はコミュニティによって提供されている。

#### 適用対象
- 明治～昭和初期の活字印刷物
- 縦書き文書
- 旧字体・異体字を含む近代文書

#### 参照リンク
- [GitHub - ndl-lab/ndlocr_cli](https://github.com/ndl-lab/ndlocr_cli)
- [NDLOCR ver.2の公開について - NDLラボ](https://lab.ndl.go.jp/news/2023/2023-07-12/)

---

### 1.2 NDL古典籍OCR-Lite ★くずし字専用

#### バージョン・更新日
- **最新版**: NDL古典籍OCR-Lite（2024年11月公開）
- ver.3と比較して精度が約2%低下するが、**GPUなしで高速動作**

#### 要点
- **江戸期以前の和古書・漢籍に特化**
- **GPUが不要**でノートPCでも動作
- レイアウト認識、文字列認識、読み順整序の3モジュール構成
- ライセンス：CC BY 4.0

#### インストール方法
```bash
# GitHubからバイナリをダウンロード
git clone https://github.com/ndl-lab/ndlkotenocr-lite.git

# 起動用ショートカットからGUIで実行
```

#### 使い方
1. 起動用ショートカットをダブルクリック
2. 「画像ファイルを処理する」を押して画像選択
3. 出力先フォルダを選択
4. OCRボタンを押してテキスト出力

#### 適用対象
- くずし字（江戸期以前）
- 和古書、漢籍
- 手書き古文書

#### 参照リンク
- [GitHub - ndl-lab/ndlkotenocr-lite](https://github.com/ndl-lab/ndlkotenocr-lite)
- [NDL古典籍OCR-Liteの公開について - NDLラボ](https://lab.ndl.go.jp/news/2024/2024-11-26/)

---

### 1.3 PaddleOCR

#### バージョン・更新日
- **最新版**: PaddleOCR v3.0（2025年5月20日リリース）
- PP-OCRv5で日本語含む109言語対応、精度が前版比+13%向上

#### 要点
- **汎用的な日本語OCR**として高精度
- 横書き・縦書き・斜め文字に対応
- PDFやドキュメント画像のMarkdown/JSON変換機能（PP-StructureV3）
- **戦前文書への特化はなし**（現代日本語向け）

#### インストール方法
```bash
pip install paddleocr

# Python実行例
from paddleocr import PaddleOCR
ocr = PaddleOCR(lang='japan')
result = ocr.ocr('image.jpg')
```

#### 適用対象
- 現代日本語文書
- 英語混在文書
- ポスター、看板など傾きのある文書

#### 精度比較
処理速度・精度では **PaddleOCR > EasyOCR > Tesseract**

#### 参照リンク
- [PaddleOCR公式ドキュメント](https://www.paddleocr.ai/v2.10.0/ja/)
- [GitHub - PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

---

### 1.4 Tesseract OCR

#### 要点
- Google開発のオープンソースOCR
- 100以上の言語対応（日本語含む）
- **縦書き対応**（jpn_vert.traineddata）
- **戦前文書・くずし字には不向き**（現代日本語想定）

#### インストール方法
```bash
# macOS
brew install tesseract
brew install tesseract-lang  # 日本語データ

# 実行例
tesseract image.jpg output -l jpn
```

#### 適用対象
- 現代日本語の横書き・縦書き
- 多言語混在文書

#### 参照リンク
- [Tesseract OCR - Wikipedia](https://ja.wikipedia.org/wiki/Tesseract_(%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2))

---

## 2. 戦前日本語・歴史的文書に特化したモデル

### 2.1 CODHのRURIモデル（くずし字認識）

#### バージョン・更新日
- **最新モデル**: RURI（瑠璃）- 2022年10月にKuroNetから移行
- Google DeepMindのTarin Clanuwat氏が開発

#### 要点
- **100万文字超のくずし字データセット**で学習
- AIオブジェクト検出技術を最適化
- 複雑な背景色・パターンにも対応
- **スマホアプリ「miwo」で利用可能**

#### 制約事項
- **完全ローカル実行は不可**（CODHサーバーに画像送信が必要）
- サーバーに画像・認識結果は保存されない（プライバシー配慮）

#### 利用方法
- **miwoアプリ**（iOS/Android）でスマホカメラから直接認識
- **KuroNet Webサービス**でIIIF準拠画像のOCR

#### 参照リンク
- [AIくずし字OCRサービス - CODH](https://codh.rois.ac.jp/kuzushiji-ocr/)
- [miwoアプリ - CODH](https://codh.rois.ac.jp/miwo/)

---

## 3. PaddleOCRベースのロードマップの妥当性

### 評価：△（条件付きで可）

#### PaddleOCRが適している場合
- 現代日本語に近い活字文書
- 横書き・斜め文字・複雑なレイアウト
- 英語混在文書

#### PaddleOCRが不適切な場合
- 旧字体・異体字が多い明治期文書 → **NDLOCRが優位**
- くずし字・古典籍 → **NDL古典籍OCRまたはRURI必須**
- 縦書き中心の書物 → **NDLOCRが優位**

#### 推奨アプローチ
**戦前日本語には、まずNDLOCRを試すべき**

理由：
1. 国立国会図書館が明治～昭和初期の実データで学習・チューニング
2. 旧字体・異体字の認識率が圧倒的に高い（90% vs 40%）
3. 完全ローカル実行可能
4. オープンソース（CC BY 4.0）

---

## 4. 各ツールの比較表

| ツール | 精度（戦前文書） | 使いやすさ | ローカル実行 | 適用対象 |
|--------|------------------|------------|--------------|----------|
| **NDLOCR** | ★★★★★（90%+） | ★★★☆☆（Docker必要） | ○ | 明治～昭和活字 |
| **NDL古典籍OCR-Lite** | ★★★★☆（くずし字） | ★★★★☆（GUI有） | ○（GPU不要） | 江戸期以前 |
| **RURI/miwo** | ★★★★★（くずし字） | ★★★★★（スマホアプリ） | × | くずし字専用 |
| **PaddleOCR** | ★★☆☆☆（現代日本語向け） | ★★★★★（pip install） | ○ | 現代日本語・汎用 |
| **Tesseract** | ★☆☆☆☆（戦前文書不向き） | ★★★★☆（brew install） | ○ | 現代日本語 |

---

## 5. 推奨ロードマップ

### フェーズ1：文書種類の判別
1. **活字の近代文書**（明治～昭和初期）→ NDLOCR
2. **くずし字・古典籍**（江戸期以前）→ NDL古典籍OCR-Lite
3. **現代日本語に近い**文書 → PaddleOCR

### フェーズ2：ツールのセットアップ
```bash
# NDLOCR（推奨）
git clone https://github.com/ndl-lab/ndlocr_cli.git
cd ndlocr_cli
docker build -t ndlocr .

# NDL古典籍OCR-Lite（くずし字）
git clone https://github.com/ndl-lab/ndlkotenocr-lite.git

# PaddleOCR（補助）
pip install paddleocr
```

### フェーズ3：精度評価
- 実際の文書でNDLOCRとPaddleOCRを比較
- 必要に応じてハイブリッド運用（活字→NDLOCR、横書き→PaddleOCR）

---

## 6. 重要な注意事項

### NDLOCR使用時の注意
- **GPU推奨**（CPUでも動作するが遅い）
- Dockerまたは仮想環境が必要
- Windows環境ではWSL2経由での実行

### くずし字認識の限界
- 完全自動認識は難しく、**人間の校正が必須**
- 時代・地域による字体の変化に注意
- 学習データにない稀な字体は誤認識の可能性

### ライセンス確認
- NDLOCR、NDL古典籍OCR：CC BY 4.0（商用利用可）
- PaddleOCR：Apache 2.0
- Tesseract：Apache 2.0

---

## 参照リンク一覧

### NDLOCR関連
- [NDLOCR ver.2の公開 - NDLラボ](https://lab.ndl.go.jp/news/2023/2023-07-12/)
- [GitHub - ndl-lab/ndlocr_cli](https://github.com/ndl-lab/ndlocr_cli)
- [AI-OCRで国立国会図書館の資料をテキスト化 - ITmedia](https://www.itmedia.co.jp/news/articles/2210/26/news009.html)

### NDL古典籍OCR関連
- [NDL古典籍OCR-Liteの公開 - NDLラボ](https://lab.ndl.go.jp/news/2024/2024-11-26/)
- [GitHub - ndl-lab/ndlkotenocr-lite](https://github.com/ndl-lab/ndlkotenocr-lite)

### CODH/RURI関連
- [AIくずし字OCRサービス - CODH](https://codh.rois.ac.jp/kuzushiji-ocr/)
- [miwoアプリ - CODH](https://codh.rois.ac.jp/miwo/)
- [KuroNetくずし字認識サービス](https://codh.rois.ac.jp/kuronet/)

### PaddleOCR関連
- [PaddleOCR公式ドキュメント](https://www.paddleocr.ai/v2.10.0/ja/)
- [GitHub - PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

### その他
- [日本語対応オープンソースOCRの比較](https://zenn.dev/piment/articles/254dde3ecf7f10)
- [Tesseract OCR - Wikipedia](https://ja.wikipedia.org/wiki/Tesseract_(%E3%82%BD%E3%83%95%E3%83%88%E3%82%A6%E3%82%A7%E3%82%A2))

---

## まとめ

**戦前日本語文書のOCRには、NDLOCRが最適解**

- 明治～昭和初期の活字 → **NDLOCR**（精度90%+、完全ローカル実行）
- くずし字・古典籍 → **NDL古典籍OCR-Lite**（GPU不要、ローカル実行）
- 補助ツール → PaddleOCR（現代日本語、横書き文書）

PaddleOCRは汎用性が高いが、戦前文書の旧字体・異体字認識ではNDLOCRに劣る。
まずはNDLOCRで実験し、不足があればPaddleOCRを補助的に使う戦略を推奨。

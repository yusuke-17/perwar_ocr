# Apple Silicon Mac では amd64 エミュレーションで動かす
FROM --platform=linux/amd64 python:3.13-slim

# システム依存パッケージ（OpenCV と画像処理に必要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-jpn \
    tesseract-ocr-jpn-vert \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pip パッケージのインストール（キャッシュ活用のため先にコピー）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY scripts/ ./scripts/
COPY utils/ ./utils/

# input/output はボリュームマウントで外から渡す
VOLUME ["/app/input", "/app/output"]

CMD ["python", "-c", "print('戦前日本語OCR 環境構築完了！')"]

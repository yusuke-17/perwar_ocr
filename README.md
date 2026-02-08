# 戦前日本語OCR

戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。

## 前提条件

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) がインストール済みであること
- M1/M2/M3 Mac で動作確認済み（`linux/amd64` エミュレーションを使用）

## 初回セットアップ

Docker イメージをビルドする（初回のみ、数分かかる）:

```bash
docker compose build
```

ビルド完了後、セットアップ確認を実行:

```bash
docker compose up
```

「セットアップ完了！」と表示されれば成功。`Ctrl + C` で停止。

## コンテナの起動・停止

### セットアップ確認（フォアグラウンド）

```bash
docker compose up
```

ターミナルにログが表示される。`Ctrl + C` で停止。

### バックグラウンドで起動

```bash
docker compose up -d
```

### 停止

```bash
docker compose down
```

### ログ確認（バックグラウンド起動中）

```bash
docker compose logs
```

リアルタイムでログを見続けるには:

```bash
docker compose logs -f
```

## OCR実行

`input/` フォルダに画像を置き、以下のコマンドで実行:

```bash
docker compose run ocr python scripts/pipeline.py
```

結果は `output/` フォルダに出力される。

## コンテナ内に入る（デバッグ用）

コンテナ内でコマンドを直接実行したいとき:

```bash
docker compose run ocr bash
```

コンテナ内から出るには `exit` と入力。

## リビルド

Dockerfile や requirements.txt を変更したら、再ビルドが必要:

```bash
docker compose build
```

キャッシュを使わず完全に再ビルドしたい場合:

```bash
docker compose build --no-cache
```

## 不要リソースの削除

Docker の不要なイメージやキャッシュを削除してディスク容量を空けたいとき:

```bash
docker system prune
```

確認メッセージが出るので `y` で実行。

## フォルダ構成

| フォルダ | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `output/` | OCR結果のテキストが出力される |
| `models/` | 学習済みモデルの保存先 |
| `scripts/` | OCRパイプラインなどのスクリプト |
| `utils/` | ユーティリティ関数 |

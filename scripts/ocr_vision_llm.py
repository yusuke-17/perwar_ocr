"""
戦前日本語OCRスクリプト — 画像から現代日本語テキストを生成

画像 → OCR → 正規化（旧字体・仮名・誤読修正） → 口語体変換 を一括実行する。

使い方:
    uv run python scripts/ocr_vision_llm.py input/画像.png
    uv run python scripts/ocr_vision_llm.py input/画像.png -o results/
    uv run python scripts/ocr_vision_llm.py input/画像.png --no-save
"""

import argparse
import sys
from pathlib import Path

from utils.ollama_client import (
    DEFAULT_MODEL,
    ImageFileError,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaOCRClient,
)
from utils.text_normalizer import normalize_text
from utils.text_modernizer import TextModernizer


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="戦前日本語OCR — 画像から現代日本語テキストを生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run python scripts/ocr_vision_llm.py input/画像.png
  uv run python scripts/ocr_vision_llm.py input/画像.png -o results/
  uv run python scripts/ocr_vision_llm.py input/画像.png --no-save
        """,
    )

    parser.add_argument(
        "image",
        type=str,
        help="OCR対象の画像ファイルパス",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=DEFAULT_MODEL,
        help=f"OCR用モデル名（デフォルト: {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="output",
        help="結果の保存先ディレクトリ（デフォルト: output/）",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        type=str,
        default=None,
        help="OCR用のカスタムプロンプト",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイル保存をスキップ（コンソール出力のみ）",
    )

    return parser.parse_args()


def save_result(text: str, image_path: str, output_dir: Path) -> Path:
    """
    最終結果をテキストファイルとして保存する

    ファイル名: 元画像名_modern.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    image_stem = Path(image_path).stem
    output_file = output_dir / f"{image_stem}_modern.txt"

    output_file.write_text(text, encoding="utf-8")
    return output_file



def main() -> int:
    """メインエントリポイント"""
    args = parse_args()

    image_path = Path(args.image)

    # ── 1. OCR ──
    print(f"\n[1/3] OCR実行中: {image_path}")
    print(f"  モデル: {args.model}")

    client_kwargs = {"model": args.model}
    if args.prompt is not None:
        client_kwargs["prompt"] = args.prompt

    client = OllamaOCRClient(**client_kwargs)

    try:
        result = client.ocr(image_path)
    except ImageFileError as e:
        print(f"\n✗ 画像エラー: {e}")
        return 1
    except OllamaConnectionError as e:
        print(f"\n✗ Ollama接続エラー: {e}")
        return 1
    except OllamaModelNotFoundError as e:
        print(f"\n✗ モデルエラー: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ 予期しないエラー: {e}")
        return 1

    print(f"  完了（{result.elapsed_seconds:.2f}秒）")
    text = result.text

    print()
    print("=" * 50)
    print("OCR結果")
    print("=" * 50)
    print(text)
    print("-" * 50)

    # ── 2. テキスト正規化 ──
    print(f"\n[2/3] テキスト正規化中（旧字体・仮名・誤読修正）...")
    text = normalize_text(text)
    print(f"  完了")

    print()
    print("=" * 50)
    print("正規化結果")
    print("=" * 50)
    print(text)
    print("-" * 50)

    # ── 3. 口語体変換 ──
    print(f"\n[3/3] 口語体変換中（LLM: qwen3.5:9b）...")
    modernizer = TextModernizer()
    text = modernizer.modernize(text)
    print(f"  完了")

    # 最終結果を表示
    print()
    print("=" * 50)
    print("変換結果")
    print("=" * 50)
    print(text)
    print("-" * 50)

    # ファイル保存
    if not args.no_save:
        output_path = save_result(text, str(image_path), Path(args.output))
        print(f"\n✓ 保存しました: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

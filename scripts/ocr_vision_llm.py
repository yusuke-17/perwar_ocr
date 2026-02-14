"""
GLM-OCR による画像テキスト読み取りスクリプト

使い方:
    uv run python scripts/ocr_vision_llm.py input/画像.png
    uv run python scripts/ocr_vision_llm.py input/画像.png --model qwen3-vl
    uv run python scripts/ocr_vision_llm.py input/画像.png -o results/
    uv run python scripts/ocr_vision_llm.py input/画像.png --no-save
"""

import argparse
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加（utils をインポートするため）
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from utils.ollama_client import (
    DEFAULT_MODEL,
    ImageFileError,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaOCRClient,
)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="GLM-OCR による画像テキスト読み取り",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run python scripts/ocr_vision_llm.py input/画像.png
  uv run python scripts/ocr_vision_llm.py input/画像.png --model qwen3-vl
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
        help=f"使用するOllamaモデル名（デフォルト: {DEFAULT_MODEL}）",
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


def save_result(result, output_dir: Path) -> Path:
    """
    OCR結果をテキストファイルとして保存する

    ファイル名: 元画像名_ocr.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    image_stem = Path(result.image_path).stem
    output_file = output_dir / f"{image_stem}_ocr.txt"

    header = (
        f"# OCR結果\n"
        f"# 画像: {result.image_path}\n"
        f"# モデル: {result.model}\n"
        f"# プロンプト: {result.prompt}\n"
        f"# 処理時間: {result.elapsed_seconds:.2f}秒\n"
        f"# ---\n\n"
    )

    output_file.write_text(header + result.text, encoding="utf-8")
    return output_file


def print_result(result) -> None:
    """OCR結果をコンソールに見やすく表示する"""
    print()
    print("=" * 50)
    print("GLM-OCR 認識結果")
    print("=" * 50)
    print(f"  画像: {result.image_path}")
    print(f"  モデル: {result.model}")
    print(f"  処理時間: {result.elapsed_seconds:.2f}秒")
    print("-" * 50)
    print(result.text)
    print("-" * 50)


def main() -> int:
    """メインエントリポイント"""
    args = parse_args()

    image_path = Path(args.image)

    print(f"\n画像を読み取り中: {image_path}")
    print(f"使用モデル: {args.model}")

    # クライアント作成
    client_kwargs = {"model": args.model}
    if args.prompt is not None:
        client_kwargs["prompt"] = args.prompt

    client = OllamaOCRClient(**client_kwargs)

    # OCR実行
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

    # 結果表示
    print_result(result)

    # ファイル保存
    if not args.no_save:
        output_path = save_result(result, Path(args.output))
        print(f"\n✓ 結果を保存しました: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

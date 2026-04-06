"""
戦前日本語OCRスクリプト — 画像から現代日本語テキストを生成

画像 → OCR → 正規化（旧字体・仮名・誤読修正） → 口語体変換 を一括実行する。
複数画像を結合して一括処理することも可能。

使い方:
    uv run prewar-ocr                          # 対話モード（input/から画像を選択）
    uv run prewar-ocr input/画像.png            # 直接指定（1枚）
    uv run prewar-ocr input/画像.png -o results/
    uv run prewar-ocr input/画像.png --no-save
"""

import argparse
import sys
from pathlib import Path

import questionary

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
        nargs="?",
        default=None,
        help="OCR対象の画像ファイルパス（省略時は対話モード）",
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


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
INPUT_DIR = Path("input")


def select_image_interactive() -> Path | None:
    """input/ディレクトリから画像を対話的に選択する"""
    if not INPUT_DIR.exists():
        print(f"✗ {INPUT_DIR}/ ディレクトリが見つかりません")
        return None

    images = sorted(
        [f for f in INPUT_DIR.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
    )

    if not images:
        print(f"✗ {INPUT_DIR}/ に画像ファイルがありません")
        return None

    choices = [f.name for f in images]
    selected = questionary.select(
        "処理する画像を選択してください:",
        choices=choices,
    ).ask()

    if selected is None:
        # Ctrl+C でキャンセルされた場合
        return None

    return INPUT_DIR / selected


def select_mode_interactive() -> str | None:
    """処理モード（1枚 or 複数）を対話的に選択する"""
    mode = questionary.select(
        "処理モードを選択してください:",
        choices=[
            "1枚の画像を処理",
            "複数画像をまとめて処理",
        ],
    ).ask()

    if mode is None:
        return None

    return "single" if mode == "1枚の画像を処理" else "batch"


def select_images_batch() -> list[Path] | None:
    """input/ディレクトリから複数画像を対話的に選択する"""
    if not INPUT_DIR.exists():
        print(f"✗ {INPUT_DIR}/ ディレクトリが見つかりません")
        return None

    images = sorted(
        [f for f in INPUT_DIR.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
    )

    if not images:
        print(f"✗ {INPUT_DIR}/ に画像ファイルがありません")
        return None

    choices = [f.name for f in images]
    selected = questionary.checkbox(
        "処理する画像を選択してください（スペースで選択、Enterで確定）:",
        choices=choices,
        validate=lambda x: len(x) > 0 or "1つ以上の画像を選択してください",
    ).ask()

    if selected is None:
        return None

    # ファイル名順にソート（選択順ではなく番号順を保証）
    return sorted([INPUT_DIR / name for name in selected])


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


def save_result_batch(text: str, image_paths: list[Path], output_dir: Path) -> Path:
    """
    複数画像の結合結果をテキストファイルとして保存する

    ファイル名: {先頭画像名}-{末尾画像名}_modern.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    first_stem = image_paths[0].stem
    last_stem = image_paths[-1].stem
    if first_stem == last_stem:
        filename = f"{first_stem}_modern.txt"
    else:
        filename = f"{first_stem}-{last_stem}_modern.txt"

    output_file = output_dir / filename
    output_file.write_text(text, encoding="utf-8")
    return output_file


def _create_ocr_client(args: argparse.Namespace) -> OllamaOCRClient:
    """引数からOCRクライアントを生成する"""
    client_kwargs = {"model": args.model}
    if args.prompt is not None:
        client_kwargs["prompt"] = args.prompt
    return OllamaOCRClient(**client_kwargs)


def _run_ocr(client: OllamaOCRClient, image_path: Path) -> str | None:
    """1枚の画像にOCRを実行し、テキストを返す。エラー時はNone"""
    try:
        result = client.ocr(image_path)
    except ImageFileError as e:
        print(f"\n✗ 画像エラー: {e}")
        return None
    except OllamaConnectionError as e:
        print(f"\n✗ Ollama接続エラー: {e}")
        return None
    except OllamaModelNotFoundError as e:
        print(f"\n✗ モデルエラー: {e}")
        return None
    except Exception as e:
        print(f"\n✗ 予期しないエラー: {e}")
        return None

    print(f"  完了（{result.elapsed_seconds:.2f}秒）")
    return result.text


def process_single(args: argparse.Namespace, image_path: Path) -> int:
    """1枚の画像を処理するパイプライン"""
    # ── 1. OCR ──
    print(f"\n[1/3] OCR実行中: {image_path}")
    print(f"  モデル: {args.model}")

    client = _create_ocr_client(args)
    text = _run_ocr(client, image_path)
    if text is None:
        return 1

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


def process_batch(args: argparse.Namespace, image_paths: list[Path]) -> int:
    """複数画像を結合して処理するパイプライン"""
    total = len(image_paths)
    names = ", ".join(p.name for p in image_paths)
    print(f"\n処理モード: 複数画像（{total}枚）")
    print(f"対象: {names}")

    # ── 1. 各画像をOCR ──
    client = _create_ocr_client(args)
    ocr_texts = []

    for i, path in enumerate(image_paths):
        print(f"\n[OCR {i + 1}/{total}] {path.name}")
        print(f"  モデル: {args.model}")

        text = _run_ocr(client, path)
        if text is None:
            return 1
        ocr_texts.append(text)

    # ── 2. テキスト結合 ──
    combined_text = "\n\n".join(ocr_texts)
    print(f"\n結合テキスト: {len(combined_text)}文字（{total}画像分）")

    print()
    print("=" * 50)
    print("結合OCR結果")
    print("=" * 50)
    print(combined_text)
    print("-" * 50)

    # ── 3. テキスト正規化 ──
    print(f"\n[正規化] テキスト正規化中（旧字体・仮名・誤読修正）...")
    combined_text = normalize_text(combined_text)
    print(f"  完了")

    print()
    print("=" * 50)
    print("正規化結果")
    print("=" * 50)
    print(combined_text)
    print("-" * 50)

    # ── 4. 口語体変換 ──
    print(f"\n[口語体変換] 口語体変換中（LLM: qwen3.5:9b）...")
    modernizer = TextModernizer()
    combined_text = modernizer.modernize(combined_text)
    print(f"  完了")

    # 最終結果を表示
    print()
    print("=" * 50)
    print("変換結果")
    print("=" * 50)
    print(combined_text)
    print("-" * 50)

    # ファイル保存
    if not args.no_save:
        output_path = save_result_batch(
            combined_text, image_paths, Path(args.output)
        )
        print(f"\n✓ 保存しました: {output_path}")

    return 0


def main() -> int:
    """メインエントリポイント"""
    args = parse_args()

    # 引数あり → 単一画像を直接処理
    if args.image is not None:
        return process_single(args, Path(args.image))

    # 引数なし → 対話モード
    mode = select_mode_interactive()
    if mode is None:
        return 1

    if mode == "single":
        selected = select_image_interactive()
        if selected is None:
            return 1
        return process_single(args, selected)
    else:
        selected = select_images_batch()
        if selected is None:
            return 1
        return process_batch(args, selected)


if __name__ == "__main__":
    sys.exit(main())

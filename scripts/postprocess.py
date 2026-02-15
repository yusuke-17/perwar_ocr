"""
後処理スクリプト — OCR出力テキストを現代日本語に変換

旧字体→新字体、歴史的仮名遣い→現代仮名遣いの変換を行う。
--modernize オプションでLLMによる文語体→口語体リライトも実行可能。

使い方:
    # テキストファイル1つを変換
    uv run python scripts/postprocess.py output/sample_ocr.txt

    # 変換結果を別ファイルに保存
    uv run python scripts/postprocess.py output/sample_ocr.txt -o output/sample_modern.txt

    # フォルダ内の全 .txt を一括変換
    uv run python scripts/postprocess.py output/ -o output_converted/

    # 旧字体変換のみ（仮名遣い変換をスキップ）
    uv run python scripts/postprocess.py output/sample_ocr.txt --no-kana

    # 変換前後の差分を表示
    uv run python scripts/postprocess.py output/sample_ocr.txt --diff

    # LLMで文語体→口語体にリライト
    uv run python scripts/postprocess.py output/sample_ocr.txt --modernize

    # リライト用モデルを変更
    uv run python scripts/postprocess.py output/sample_ocr.txt --modernize --modernize-model qwen3:8b
"""

import argparse
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from utils.char_converter import convert_old_to_new, find_old_chars
from utils.kana_converter import convert_historical_kana, find_historical_kana


def postprocess(
    text: str,
    convert_chars: bool = True,
    convert_kana: bool = True,
    modernize: bool = False,
    modernize_model: str = "qwen3:14b",
) -> str:
    """
    OCR出力テキストに後処理を適用する

    Args:
        text: OCR出力テキスト
        convert_chars: 旧字体→新字体変換を行うか
        convert_kana: 歴史的仮名遣い→現代仮名遣い変換を行うか
        modernize: LLMで文語体→口語体リライトを行うか
        modernize_model: リライトに使用するLLMモデル名

    Returns:
        変換後のテキスト
    """
    if convert_chars:
        text = convert_old_to_new(text)
    if convert_kana:
        text = convert_historical_kana(text)
    if modernize:
        from utils.text_modernizer import TextModernizer

        modernizer = TextModernizer(model=modernize_model)
        text = modernizer.modernize(text)
    return text


def show_diff(original: str, converted: str) -> None:
    """変換前後の差分を分かりやすく表示する"""
    if original == converted:
        print("  変換箇所なし")
        return

    for i, (old_char, new_char) in enumerate(zip(original, converted)):
        if old_char != new_char:
            # 前後の文脈を表示
            start = max(0, i - 5)
            end = min(len(original), i + 6)
            context_old = original[start:end]
            context_new = converted[start:end]
            print(f"  位置{i}: ...{context_old}... → ...{context_new}...")


def process_file(
    input_path: Path,
    output_path: Path | None,
    convert_chars: bool,
    convert_kana: bool,
    modernize: bool,
    modernize_model: str,
    show_changes: bool,
) -> None:
    """1つのテキストファイルを後処理する"""
    original = input_path.read_text(encoding="utf-8")
    converted = postprocess(
        original, convert_chars, convert_kana, modernize, modernize_model
    )

    # 変換統計
    old_chars = find_old_chars(original) if convert_chars else []
    old_kana = find_historical_kana(original) if convert_kana else []

    print(f"\n  ファイル: {input_path}")
    print(f"  旧字体: {len(old_chars)}箇所")
    print(f"  旧仮名: {len(old_kana)}箇所")

    if show_changes and (old_chars or old_kana):
        print("  --- 変換内容 ---")
        for old, new, pos in old_chars:
            print(f"    [{pos}] {old} → {new}")
        for old, new, pos in old_kana:
            print(f"    [{pos}] {old} → {new}")

    # 保存
    if output_path is None:
        # 元ファイル名に _modern を付けて同じディレクトリに保存
        output_path = input_path.with_stem(input_path.stem + "_modern")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(converted, encoding="utf-8")
    print(f"  保存先: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR出力テキストを現代日本語に変換する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run python scripts/postprocess.py output/sample_ocr.txt
  uv run python scripts/postprocess.py output/ -o output_converted/
  uv run python scripts/postprocess.py output/sample_ocr.txt --diff
  uv run python scripts/postprocess.py output/sample_ocr.txt --no-kana
        """,
    )

    parser.add_argument(
        "input",
        type=str,
        help="変換対象のテキストファイルまたはディレクトリ",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="出力先ファイルまたはディレクトリ（省略時: 元ファイル名_modern.txt）",
    )
    parser.add_argument(
        "--no-chars",
        action="store_true",
        help="旧字体→新字体変換をスキップ",
    )
    parser.add_argument(
        "--no-kana",
        action="store_true",
        help="歴史的仮名遣い→現代仮名遣い変換をスキップ",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="変換箇所の詳細を表示する",
    )
    parser.add_argument(
        "--modernize",
        action="store_true",
        help="LLMを使って文語体を現代口語体にリライトする",
    )
    parser.add_argument(
        "--modernize-model",
        type=str,
        default="qwen3:14b",
        help="リライトに使用するLLMモデル名（デフォルト: qwen3:14b）",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    convert_chars = not args.no_chars
    convert_kana = not args.no_kana

    if not input_path.exists():
        print(f"エラー: '{input_path}' が見つかりません")
        return 1

    print("=" * 50)
    print("後処理: 旧字体・旧仮名遣い → 現代日本語")
    print("=" * 50)
    print(f"  旧字体変換: {'ON' if convert_chars else 'OFF'}")
    print(f"  旧仮名変換: {'ON' if convert_kana else 'OFF'}")
    print(f"  LLMリライト: {'ON (' + args.modernize_model + ')' if args.modernize else 'OFF'}")

    if input_path.is_file():
        # 単一ファイル
        output_path = Path(args.output) if args.output else None
        process_file(
            input_path, output_path, convert_chars, convert_kana,
            args.modernize, args.modernize_model, args.diff,
        )

    elif input_path.is_dir():
        # ディレクトリ内の全 .txt を処理
        txt_files = sorted(input_path.glob("*.txt"))
        if not txt_files:
            print(f"\nエラー: '{input_path}' に .txt ファイルがありません")
            return 1

        print(f"\n  対象ファイル数: {len(txt_files)}")

        for txt_file in txt_files:
            if txt_file.stem.endswith("_modern"):
                continue  # 既に変換済みのファイルはスキップ

            if args.output:
                out_dir = Path(args.output)
                output_path = out_dir / txt_file.name
            else:
                output_path = None

            process_file(
                txt_file, output_path, convert_chars, convert_kana,
                args.modernize, args.modernize_model, args.diff,
            )

    print("\n完了!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
後処理スクリプト — OCR出力テキストを現代日本語に変換

テキスト正規化（旧字体変換・仮名変換・OCR誤読修正等）を行う。
--modernize オプションでLLMによる文語体→口語体リライトも実行可能。

使い方:
    # テキストファイル1つを変換
    uv run python scripts/postprocess.py output/sample_ocr.txt

    # 変換結果を別ファイルに保存
    uv run python scripts/postprocess.py output/sample_ocr.txt -o output/sample_modern.txt

    # フォルダ内の全 .txt を一括変換
    uv run python scripts/postprocess.py output/ -o output_converted/

    # 正規化をスキップ（LLMリライトのみ）
    uv run python scripts/postprocess.py output/sample_ocr.txt --no-normalize --modernize

    # 変換前後の差分を表示
    uv run python scripts/postprocess.py output/sample_ocr.txt --diff

    # LLMで文語体→口語体にリライト
    uv run python scripts/postprocess.py output/sample_ocr.txt --modernize

    # リライト用モデルを変更
    uv run python scripts/postprocess.py output/sample_ocr.txt --modernize --modernize-model qwen3:8b

終了コード:
    0  全ファイル成功
    2  一部ファイルをスキップしたが、残りは変換済み（Ctrl+C 中断を含む）
    1  1件も変換できなかった（入力エラーを含む）
"""

import argparse
import sys
from pathlib import Path

from utils.config import CONFIG
from utils.text_normalizer import normalize_text, find_normalizations
from senzen_word.kana import find_historical_kana, find_katakana_particles


def postprocess(
    text: str,
    normalize: bool = True,
    modernize: bool = False,
    modernize_model: str = CONFIG.get("models.modernize"),
) -> str:
    """
    OCR出力テキストに後処理を適用する

    処理順序:
      1. テキスト正規化（旧字体・仮名・OCR誤読・空白等の一括処理）
      2. LLM口語体リライト（--modernize 時のみ）

    Args:
        text: OCR出力テキスト
        normalize: テキスト正規化を行うか
        modernize: LLMで文語体→口語体リライトを行うか
        modernize_model: リライトに使用するLLMモデル名

    Returns:
        変換後のテキスト
    """
    if normalize:
        text = normalize_text(text)
    if modernize:
        from utils.text_modernizer import TextModernizer

        modernizer = TextModernizer(model=modernize_model)
        # チャンク単位の失敗は原文のまま吸収される（失敗数だけ知らせる）
        result = modernizer.modernize_detailed(text)
        if result.failures:
            print(
                f"  ⚠ {len(result.failures)}/{result.chunk_total} チャンクは"
                "変換できず原文のまま残しました"
            )
        text = result.text
    return text


def process_file(
    input_path: Path,
    output_path: Path | None,
    normalize: bool,
    modernize: bool,
    modernize_model: str,
    show_changes: bool,
) -> bool:
    """1つのテキストファイルを後処理する

    Returns:
        保存まで到達したら True、失敗したら False
        （一括処理で1ファイルの失敗が残りを巻き添えにしないため、
        例外は呼び出し側で握って次のファイルへ進む）
    """
    original = input_path.read_text(encoding="utf-8")
    converted = postprocess(original, normalize, modernize, modernize_model)

    # 変換統計
    normalizations = find_normalizations(original) if normalize else []
    kana_matches = find_historical_kana(original) if normalize else []
    particle_matches = find_katakana_particles(original) if normalize else []

    print(f"\n  ファイル: {input_path}")
    print(f"  OCR誤読修正: {len(normalizations)}箇所")
    print(f"  仮名変換: {len(kana_matches)}箇所")
    print(f"  カタカナ助詞変換: {len(particle_matches)}箇所")

    if show_changes and (normalizations or kana_matches or particle_matches):
        print("  --- 変換内容 ---")
        for old, new, pos in normalizations:
            print(f"    [{pos}] {old} → {new} (OCR誤読)")
        for old, new, pos in kana_matches:
            print(f"    [{pos}] {old} → {new} (仮名)")
        for old, new, pos in particle_matches:
            print(f"    [{pos}] {old} → {new} (助詞)")

    # 保存
    if output_path is None:
        # 元ファイル名に _modern を付けて同じディレクトリに保存
        output_path = input_path.with_stem(input_path.stem + "_modern")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(converted, encoding="utf-8")
    print(f"  保存先: {output_path}")
    return True


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """後処理コマンドの引数を追加する（統合CLIの fix サブコマンドで流用）"""
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
        "--no-normalize",
        action="store_true",
        help="テキスト正規化（旧字体・仮名・OCR誤読修正等）をスキップ",
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
        default=CONFIG.get("models.modernize"),
        help="リライトに使用するLLMモデル名（デフォルト: qwen3.5:9b）",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR出力テキストを現代日本語に変換する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run python scripts/postprocess.py output/sample_ocr.txt
  uv run python scripts/postprocess.py output/ -o output_converted/
  uv run python scripts/postprocess.py output/sample_ocr.txt --diff
  uv run python scripts/postprocess.py output/sample_ocr.txt --modernize
        """,
    )
    add_arguments(parser)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    normalize = not args.no_normalize

    if not input_path.exists():
        print(f"エラー: '{input_path}' が見つかりません")
        return 1

    print("=" * 50)
    print("後処理: OCRテキスト → 現代日本語")
    print("=" * 50)
    print(f"  テキスト正規化: {'ON' if normalize else 'OFF'}")
    print(f"  LLMリライト: {'ON (' + args.modernize_model + ')' if args.modernize else 'OFF'}")

    if input_path.is_file():
        # 単一ファイル
        output_path = Path(args.output) if args.output else None
        try:
            process_file(
                input_path, output_path, normalize,
                args.modernize, args.modernize_model, args.diff,
            )
        except KeyboardInterrupt:
            print("\n⚠ 中断しました")
            return 1
        except Exception as e:
            print(f"\n✗ 変換に失敗: {input_path} — {e}")
            return 1

    elif input_path.is_dir():
        # ディレクトリ内の全 .txt を処理
        txt_files = sorted(input_path.glob("*.txt"))
        if not txt_files:
            print(f"\nエラー: '{input_path}' に .txt ファイルがありません")
            return 1

        targets = [f for f in txt_files if not f.stem.endswith("_modern")]
        print(f"\n  対象ファイル数: {len(targets)}")

        failed: list[str] = []
        done = 0
        interrupted = False

        for txt_file in targets:
            if args.output:
                out_dir = Path(args.output)
                output_path = out_dir / txt_file.name
            else:
                output_path = None

            # 1ファイルの失敗で残りを巻き添えにしない（G2 と同じ方針）
            try:
                process_file(
                    txt_file, output_path, normalize,
                    args.modernize, args.modernize_model, args.diff,
                )
            except KeyboardInterrupt:
                print("\n⚠ 中断しました。ここまでの変換結果は保存済みです")
                interrupted = True
                break
            except Exception as e:
                print(f"  ✗ 変換に失敗（スキップ）: {txt_file.name} — {e}")
                failed.append(txt_file.name)
                continue
            done += 1

        if failed:
            print(f"\n⚠ {len(targets)}件中 {len(failed)}件が変換できませんでした:")
            for name in failed:
                print(f"  - {name}")

        if done == 0 and (failed or interrupted):
            return 1
        if failed or interrupted:
            print("\n完了（一部スキップ）")
            return 2

    print("\n完了!")
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())

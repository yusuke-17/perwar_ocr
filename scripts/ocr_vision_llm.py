"""
戦前日本語OCRスクリプト — 画像から現代日本語テキストを生成

画像 → OCR → 正規化（旧字体・仮名・誤読修正） → 口語体変換 を一括実行する。
複数画像を結合して一括処理することも可能。

処理結果は library/{YYYY-MM-DD}_{slug}/ に「1件の記録」として保存される
（元画像コピー・OCR生テキスト・現代語テキスト・meta.json）。

使い方:
    uv run prewar-ocr                                # 対話モード（input/から画像を選択）
    uv run prewar-ocr input/画像.png                  # 直接指定（1枚）
    uv run prewar-ocr shoot                          # 範囲スクショを撮りため → 終了時に一括処理（macOS）
    uv run prewar-ocr shoot --no-run                 # 撮るだけ（処理は後回し）
    uv run prewar-ocr input/session_.../             # 貯めたフォルダを1記録として一括処理
    uv run prewar-ocr input/session_.../ --separate  # フォルダ内を画像ごとの別記録として処理
    uv run prewar-ocr input/画像.png --no-modernize   # 口語体変換をスキップ
    uv run prewar-ocr input/画像.png --legacy-output  # 旧 output/*_modern.txt も併存
    uv run prewar-ocr input/画像.png --no-save        # 保存をスキップ（コンソール出力のみ）
"""

import argparse
import sys
from pathlib import Path

import questionary

from utils.config import CONFIG
from utils.library_writer import (
    DocumentRecord,
    MetaModernize,
    MetaNormalization,
    MetaOcr,
    save_document,
)
from utils.ollama_client import (
    DEFAULT_MODEL,
    ImageFileError,
    OCRResult,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaOCRClient,
)
from utils.text_normalizer import normalize_text
from utils.text_modernizer import TextModernizer
from utils import screen_capture


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """OCRコマンドの引数を追加する（統合CLIの ocr / shoot サブコマンドで流用）"""
    parser.add_argument(
        "image",
        type=str,
        nargs="?",
        default=None,
        help=(
            "OCR対象（画像ファイル / フォルダ / 'shoot'）。"
            "省略時は対話モード、shoot は範囲スクショ撮影、"
            "フォルダ指定はその中の画像を一括処理"
        ),
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
        default=CONFIG.get("paths.output"),
        help="--legacy-output 時の旧形式保存先（デフォルト: output/）",
    )
    parser.add_argument(
        "--library-root",
        type=str,
        default=CONFIG.get("paths.library"),
        help="ライブラリのルートディレクトリ（デフォルト: library/）",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        type=str,
        default=None,
        help="OCR用のカスタムプロンプト",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="テキスト正規化（旧字体・仮名・誤読修正）をスキップ",
    )
    parser.add_argument(
        "--no-modernize",
        action="store_true",
        help="口語体変換（LLMリライト）をスキップ",
    )
    parser.add_argument(
        "--legacy-output",
        action="store_true",
        help="旧形式（output/{stem}_modern.txt）も併せて出力",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイル保存をスキップ（コンソール出力のみ）",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="shoot 時に撮影のみ行い、OCR処理は後回しにする",
    )
    parser.add_argument(
        "--separate",
        action="store_true",
        help="フォルダ/セッションを画像ごとの別記録として処理（既定は結合して1記録）",
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="戦前日本語OCR — 画像から現代日本語テキストを生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run python scripts/ocr_vision_llm.py input/画像.png
  uv run python scripts/ocr_vision_llm.py input/画像.png --no-modernize
  uv run python scripts/ocr_vision_llm.py input/画像.png --legacy-output
  uv run python scripts/ocr_vision_llm.py input/画像.png --library-root mylib/
  uv run python scripts/ocr_vision_llm.py input/画像.png --no-save
        """,
    )
    add_arguments(parser)
    return parser.parse_args()


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
INPUT_DIR = Path(CONFIG.get("paths.input"))


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


def _save_legacy(text: str, image_path: Path, output_dir: Path) -> Path:
    """旧形式の保存（単一画像）

    --legacy-output 指定時のみ呼ばれる。
    ファイル名: {元画像名}_modern.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{image_path.stem}_modern.txt"
    output_file.write_text(text, encoding="utf-8")
    return output_file


def _save_legacy_batch(text: str, image_paths: list[Path], output_dir: Path) -> Path:
    """旧形式の保存（バッチ）

    --legacy-output 指定時のみ呼ばれる。
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


def _run_ocr(client: OllamaOCRClient, image_path: Path) -> OCRResult | None:
    """1枚の画像にOCRを実行し、OCRResultを返す。エラー時はNone

    meta.json 用に model/prompt/elapsed_seconds を保持したいため、
    text だけでなく OCRResult まるごと返す。
    """
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
    return result


def process_single(args: argparse.Namespace, image_path: Path) -> int:
    """1枚の画像を処理するパイプライン"""
    # ── 1. OCR ──
    print(f"\n[1/3] OCR実行中: {image_path}")
    print(f"  モデル: {args.model}")

    client = _create_ocr_client(args)
    result = _run_ocr(client, image_path)
    if result is None:
        return 1

    ocr_raw = result.text

    print()
    print("=" * 50)
    print("OCR結果")
    print("=" * 50)
    print(ocr_raw)
    print("-" * 50)

    # ── 2. テキスト正規化 ──
    if not args.no_normalize:
        print(f"\n[2/3] テキスト正規化中（旧字体・仮名・誤読修正）...")
        normalized = normalize_text(ocr_raw)
        print(f"  完了")

        print()
        print("=" * 50)
        print("正規化結果")
        print("=" * 50)
        print(normalized)
        print("-" * 50)
    else:
        print(f"\n[2/3] テキスト正規化をスキップ（--no-normalize）")
        normalized = ocr_raw

    # ── 3. 口語体変換 ──
    modernizer = TextModernizer()
    if not args.no_modernize:
        print(f"\n[3/3] 口語体変換中（LLM: {modernizer.model}）...")
        modern = modernizer.modernize(normalized)
        print(f"  完了")

        # 最終結果を表示
        print()
        print("=" * 50)
        print("変換結果")
        print("=" * 50)
        print(modern)
        print("-" * 50)
    else:
        print(f"\n[3/3] 口語体変換をスキップ（--no-modernize）")
        modern = normalized

    # ファイル保存
    if not args.no_save:
        record = DocumentRecord(
            source_paths=[image_path],
            ocr_raw=ocr_raw,
            modern_text=modern,
            ocr_meta=MetaOcr(
                model=result.model,
                prompt=result.prompt,
                elapsed_seconds=result.elapsed_seconds,
            ),
            normalization=MetaNormalization(
                old_kanji=not args.no_normalize,
                historical_kana=not args.no_normalize,
                ocr_misread_correction=not args.no_normalize,
            ),
            modernize=MetaModernize(
                enabled=not args.no_modernize,
                model=modernizer.model if not args.no_modernize else "",
            ),
        )
        doc_dir = save_document(record, library_root=Path(args.library_root))
        print(f"\n✓ ライブラリに保存: {doc_dir}")

        if args.legacy_output:
            legacy_path = _save_legacy(modern, image_path, Path(args.output))
            print(f"✓ 旧形式でも保存: {legacy_path}")

    return 0


def process_batch(args: argparse.Namespace, image_paths: list[Path]) -> int:
    """複数画像を結合して処理するパイプライン"""
    total = len(image_paths)
    names = ", ".join(p.name for p in image_paths)
    print(f"\n処理モード: 複数画像（{total}枚）")
    print(f"対象: {names}")

    # ── 1. 各画像をOCR ──
    client = _create_ocr_client(args)
    ocr_results: list[OCRResult] = []

    for i, path in enumerate(image_paths):
        print(f"\n[OCR {i + 1}/{total}] {path.name}")
        print(f"  モデル: {args.model}")

        result = _run_ocr(client, path)
        if result is None:
            return 1
        ocr_results.append(result)

    # ── 2. テキスト結合 ──
    ocr_raw_combined = "\n\n".join(r.text for r in ocr_results)
    print(f"\n結合テキスト: {len(ocr_raw_combined)}文字（{total}画像分）")

    print()
    print("=" * 50)
    print("結合OCR結果")
    print("=" * 50)
    print(ocr_raw_combined)
    print("-" * 50)

    # ── 3. テキスト正規化 ──
    if not args.no_normalize:
        print(f"\n[正規化] テキスト正規化中（旧字体・仮名・誤読修正）...")
        normalized = normalize_text(ocr_raw_combined)
        print(f"  完了")

        print()
        print("=" * 50)
        print("正規化結果")
        print("=" * 50)
        print(normalized)
        print("-" * 50)
    else:
        print(f"\n[正規化] テキスト正規化をスキップ（--no-normalize）")
        normalized = ocr_raw_combined

    # ── 4. 口語体変換 ──
    modernizer = TextModernizer()
    if not args.no_modernize:
        print(f"\n[口語体変換] 口語体変換中（LLM: {modernizer.model}）...")
        modern = modernizer.modernize(normalized)
        print(f"  完了")

        # 最終結果を表示
        print()
        print("=" * 50)
        print("変換結果")
        print("=" * 50)
        print(modern)
        print("-" * 50)
    else:
        print(f"\n[口語体変換] 口語体変換をスキップ（--no-modernize）")
        modern = normalized

    # ファイル保存
    if not args.no_save:
        # OCR メタ情報はバッチ全体を1件として記録する
        # （model/prompt はバッチ内で同一、elapsed_seconds は合計）
        record = DocumentRecord(
            source_paths=image_paths,
            ocr_raw=ocr_raw_combined,
            modern_text=modern,
            ocr_meta=MetaOcr(
                model=ocr_results[0].model,
                prompt=ocr_results[0].prompt,
                elapsed_seconds=sum(r.elapsed_seconds for r in ocr_results),
            ),
            normalization=MetaNormalization(
                old_kanji=not args.no_normalize,
                historical_kana=not args.no_normalize,
                ocr_misread_correction=not args.no_normalize,
            ),
            modernize=MetaModernize(
                enabled=not args.no_modernize,
                model=modernizer.model if not args.no_modernize else "",
            ),
        )
        doc_dir = save_document(record, library_root=Path(args.library_root))
        print(f"\n✓ ライブラリに保存: {doc_dir}")

        if args.legacy_output:
            legacy_path = _save_legacy_batch(modern, image_paths, Path(args.output))
            print(f"✓ 旧形式でも保存: {legacy_path}")

    return 0


def load_folder_images(folder: Path) -> list[Path] | None:
    """フォルダ内の画像をファイル名順（＝ページ順）に並べて返す

    pNNN（ゼロ埋め）連番なら sorted() で読む順が保たれる。
    画像が1枚もなければ警告して None を返す。
    """
    images = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
    )
    if not images:
        print(f"✗ {folder}/ に画像ファイルがありません")
        return None
    return images


def process_folder(args: argparse.Namespace, folder: Path) -> int:
    """フォルダ（撮影セッション等）内の画像を一括処理する

    既定は結合して1記録（process_batch）。--separate 指定時は
    画像ごとに別記録（process_single）として処理する。
    """
    images = load_folder_images(folder)
    if images is None:
        return 1

    if args.separate:
        print(f"\n処理モード: 画像ごとに別記録（{len(images)}件）")
        for i, image in enumerate(images, start=1):
            print(f"\n===== {i}/{len(images)}: {image.name} =====")
            code = process_single(args, image)
            if code != 0:
                return code
        return 0

    return process_batch(args, images)


def cmd_shoot(args: argparse.Namespace) -> int:
    """範囲スクショを撮りため、終了時に一括処理する（macOS専用）"""
    if not screen_capture.is_supported():
        print("✗ 範囲スクショ撮影（shoot）は macOS 専用です。")
        print(
            "  他OSでは、画像を input/ に置いてから "
            "`uv run prewar-ocr <画像 or フォルダ>` で処理してください。"
        )
        return 1

    try:
        images = screen_capture.shoot_session(INPUT_DIR)
    except screen_capture.ScreenCaptureError as e:
        print(f"✗ 撮影エラー: {e}")
        return 1

    if images is None:
        # 1枚も撮らずに終了
        return 0

    session_dir = images[0].parent

    if args.no_run:
        print(f"\n撮影のみ完了しました（--no-run）。後で処理するには:")
        print(f"  uv run prewar-ocr {session_dir}/")
        return 0

    return process_folder(args, session_dir)


def run(args: argparse.Namespace) -> int:
    """パース済み引数を受け取り、OCR処理を実行する"""
    # 'shoot' → 範囲スクショ撮りためモード
    if args.image == "shoot":
        return cmd_shoot(args)

    # 引数あり → ファイル or フォルダ
    if args.image is not None:
        target = Path(args.image)
        if target.is_dir():
            return process_folder(args, target)
        return process_single(args, target)

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


def main() -> int:
    """メインエントリポイント"""
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())

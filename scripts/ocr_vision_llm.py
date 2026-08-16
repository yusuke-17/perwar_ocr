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

終了コード:
    0  全ページ成功（保存済み）
    2  一部が欠けたが、成功分は保存済み
       （OCR失敗ページのスキップ / 口語体変換の失敗 / Ctrl+C 中断）
    1  保存物なし（全ページ失敗・入力エラー）
"""

import argparse
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import questionary

from utils.config import CONFIG
from utils.image_preprocessor import (
    PreprocessError,
    options_from_config,
    preprocess_image,
)
from utils.library_writer import (
    DocumentRecord,
    MetaModernize,
    MetaNormalization,
    MetaOcr,
    MetaPageFailure,
    MetaPreprocess,
    save_document,
)
from utils.ollama_client import (
    DEFAULT_MODEL,
    ImageFileError,
    OCRResult,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaOCRClient,
    OllamaTimeoutError,
)
from utils.progress import spinner
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
        "--no-preprocess",
        action="store_true",
        help="画像前処理（傾き補正・コントラスト等）をスキップ",
    )
    parser.add_argument(
        "--binarize",
        choices=["none", "otsu", "adaptive"],
        default=None,
        help="二値化方式を一時的に上書き（既定は config / none）",
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
    parser.add_argument(
        "--on-page-error",
        choices=["skip", "abort"],
        default=None,
        help=(
            "複数枚処理でページのOCRが失敗したときの挙動。"
            "skip=失敗ページを飛ばして続行（既定）、abort=その場で中断"
        ),
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


# 例外クラス → (meta.json に残す理由コード, 画面表示ラベル)
# 新しい例外を足すときはここに1行足せばよい（分岐を増やさない）
_OCR_ERROR_KINDS: list[tuple[type[Exception], str, str]] = [
    (ImageFileError, "image", "画像エラー"),
    (OllamaConnectionError, "connection", "Ollama接続エラー"),
    (OllamaTimeoutError, "timeout", "Ollamaタイムアウト"),
    (OllamaModelNotFoundError, "model", "モデルエラー"),
]


def _classify_ocr_error(error: Exception) -> tuple[str, str]:
    """OCR例外を (理由コード, 表示ラベル) に分類する"""
    for exc_type, reason, label in _OCR_ERROR_KINDS:
        if isinstance(error, exc_type):
            return reason, label
    return "unknown", "予期しないエラー"


def _run_ocr_page(
    client: OllamaOCRClient, target: Path, source: Path, index: int = 1
) -> OCRResult | MetaPageFailure:
    """1枚の画像にOCRを実行する。失敗しても例外を投げず失敗記録を返す

    meta.json 用に model/prompt/elapsed_seconds を保持したいため、
    text だけでなく OCRResult まるごと返す。

    KeyboardInterrupt は BaseException なので意図的に捕まえない
    （中断をどう扱うかは呼び出し側のループが決める）。

    Args:
        client: OCRクライアント
        target: 実際にOCRにかける画像（前処理後があればそちら）
        source: 元画像（表示・記録用）
        index: 1始まりのページ番号（記録用）

    Returns:
        成功なら OCRResult、失敗なら MetaPageFailure
    """
    try:
        # OCR推論は所要時間が読めないため、待機中はスピナーを回す
        # （非TTY時はメッセージを1行 print してフォールバック）
        with spinner(f"  OCR推論中: {source.name} ..."):
            result = client.ocr(target)
    except Exception as e:
        reason, label = _classify_ocr_error(e)
        print(f"\n✗ {label}: {e}")
        return MetaPageFailure(
            index=index, source=source.name, reason=reason, message=str(e)
        )

    print(f"  完了（{result.elapsed_seconds:.2f}秒）")
    return result


def _preprocess_images(
    args: argparse.Namespace, image_paths: list[Path], workdir: Path
) -> tuple[list[Path] | None, MetaPreprocess | None]:
    """前処理が有効なら各画像を workdir に整形して返す。

    無効（--no-preprocess または config の preprocess.enabled=False）なら
    (None, None) を返し、呼び出し側は元画像をそのままOCRに使う。

    1枚が失敗したときは**そのページだけ元画像にフォールバック**し、
    他ページの前処理結果は捨てない（全滅した場合のみ (None, None)）。
    戻り値のリストは image_paths と必ず同順・同数になる。

    Returns:
        (OCRに使う画像パスのリスト, MetaPreprocess) または (None, None)
    """
    if args.no_preprocess or not CONFIG.get("preprocess.enabled", True):
        return None, None

    options = options_from_config(binarize_override=args.binarize)
    out_paths: list[Path] = []
    steps_used: list[str] = []
    total_elapsed = 0.0
    failed = 0

    print(f"\n[前処理] 画像を整形中（{len(image_paths)}枚）...")
    for i, path in enumerate(image_paths, start=1):
        out_path = workdir / f"pre_{i:02d}{path.suffix or '.png'}"
        try:
            result = preprocess_image(path, out_path, options)
        except PreprocessError as e:
            print(f"  ⚠ 前処理に失敗（このページは元画像を使用）: {path.name}\n    {e}")
            out_paths.append(path)
            failed += 1
            continue
        out_paths.append(result.output_path)
        steps_used = result.steps
        total_elapsed += result.elapsed_seconds

    if failed == len(image_paths):
        # 1枚も整形できなかった → 前処理なしとして扱う（メタにも残さない）
        return None, None

    print(f"  完了（{', '.join(steps_used)}）")
    meta = MetaPreprocess(
        enabled=True, steps=steps_used, elapsed_seconds=total_elapsed
    )
    return out_paths, meta


@dataclass
class BatchOcrOutcome:
    """複数ページOCRの結果（成功分と失敗分をまとめて持つ）"""

    results: list[OCRResult] = field(default_factory=list)  # 成功ページのみ・元の順序
    ok_indices: list[int] = field(default_factory=list)  # 成功ページの0始まり添字
    failures: list[MetaPageFailure] = field(default_factory=list)
    aborted: bool = False  # 連続失敗／中断で残りページを処理しなかったか


def _ocr_pages(
    client: OllamaOCRClient,
    image_paths: list[Path],
    ocr_targets: list[Path],
    *,
    on_page_error: str = "skip",
    abort_after: int = 0,
) -> BatchOcrOutcome:
    """全ページをOCRし、失敗ページはスキップして成功分を集める

    1枚の失敗で全件を捨てないための中核（G2）。
    ok_indices を使って呼び出し側が画像リストを同じ添字で絞り込むことで、
    保存される source_01.png … の連番とテキストのページ順が一致する。

    Args:
        client: OCRクライアント
        image_paths: 元画像のリスト（ページ順）
        ocr_targets: 実際にOCRにかける画像（前処理後 or 元画像）。image_paths と同順・同数
        on_page_error: "skip"（失敗しても続行）/ "abort"（1枚失敗で打ち切り）
        abort_after: 連続失敗がこの数に達したら打ち切る。0 で無効
                     （Ollama停止時に全ページ分のタイムアウトを待たないため）

    Returns:
        BatchOcrOutcome
    """
    total = len(image_paths)
    outcome = BatchOcrOutcome()
    consecutive = 0

    for i, (source, target) in enumerate(zip(image_paths, ocr_targets)):
        print(f"\n[OCR {i + 1}/{total}] {source.name}")
        print(f"  モデル: {client.model}")

        try:
            page = _run_ocr_page(client, target, source, index=i + 1)
        except KeyboardInterrupt:
            # Ctrl+C。ここまでの成功分は捨てずに呼び出し側へ返す（G2c）
            print("\n⚠ 中断しました。ここまでの結果を保存します")
            outcome.failures.append(
                MetaPageFailure(
                    index=i + 1,
                    source=source.name,
                    reason="interrupted",
                    message="ユーザーによる中断（Ctrl+C）",
                )
            )
            outcome.aborted = True
            break

        if isinstance(page, OCRResult):
            outcome.results.append(page)
            outcome.ok_indices.append(i)
            consecutive = 0
            continue

        outcome.failures.append(page)
        consecutive += 1

        # 従来挙動（abort）と、Ollama停止などで全ページ失敗が確定的な場合の打ち切り
        if on_page_error == "abort" or (abort_after and consecutive >= abort_after):
            remaining = total - (i + 1)
            if remaining:
                print(
                    f"\n⚠ 連続 {consecutive} 件失敗したため中断します"
                    f"（未処理 {remaining}枚）"
                )
            outcome.aborted = True
            break

    return outcome


def _print_failure_summary(
    outcome: BatchOcrOutcome, total: int, saved: bool = True
) -> None:
    """スキップしたページを最後にまとめて表示する

    処理中のログは流れて見えなくなるため、終了時にもう一度出す。
    """
    if not outcome.failures:
        return

    ok = len(outcome.results)
    tried = ok + len(outcome.failures)
    print()
    print("=" * 60)
    if saved:
        print(f"⚠ {total}枚中 {ok}枚を保存、{len(outcome.failures)}枚をスキップしました")
    elif tried < total:
        print(
            f"✗ {total}枚中 {tried}枚を試して全て失敗しました。保存するものがありません"
        )
    else:
        print(f"✗ {total}枚すべてのOCRに失敗しました。保存するものがありません")
    for f in outcome.failures:
        print(f"  [{f.index}] {f.source} — {f.message}")
    if outcome.aborted:
        print("  ※ 残りのページは処理していません（中断）")
    print("再試行するには、失敗した画像を指定して実行してください:")
    print("  uv run prewar ocr <画像パス>")
    print("=" * 60)


def _run_modernize(
    modernizer: TextModernizer, normalized: str, args: argparse.Namespace
) -> tuple[str, MetaModernize]:
    """口語体変換を実行し、失敗しても正規化テキストで先へ進める（G2b）

    LLMが落ちてもOCR結果を保存前に失わないことが目的。
    チャンク単位の失敗は TextModernizer 側で原文のまま吸収される。

    Returns:
        (保存するテキスト, meta.json 用の modernize 情報)
    """
    if args.no_modernize:
        print("\n[口語体変換] 口語体変換をスキップ（--no-modernize）")
        return normalized, MetaModernize(enabled=False, model="")

    print(f"\n[口語体変換] 口語体変換中（LLM: {modernizer.model}）...")
    try:
        result = modernizer.modernize_detailed(normalized)
    except KeyboardInterrupt:
        print("\n⚠ 中断しました。正規化テキストのまま保存します")
        return normalized, MetaModernize(
            enabled=True, model=modernizer.model, error="interrupted"
        )
    except Exception as e:
        print(f"\n⚠ 口語体変換に失敗しました: {e}")
        print("  正規化テキストのまま保存します（OCR結果は失われません）")
        return normalized, MetaModernize(
            enabled=True, model=modernizer.model, error=str(e)
        )

    if result.failures:
        print(
            f"  完了（{len(result.failures)}/{result.chunk_total} チャンクは"
            "変換できず原文のまま）"
        )
    elif result.aborted:
        print("  中断（未変換部分は原文のまま）")
    else:
        print("  完了")

    return result.text, MetaModernize(
        enabled=True,
        model=modernizer.model,
        error="interrupted" if result.aborted else "",
        failed_chunks=len(result.failures),
        chunk_total=result.chunk_total if result.failures else 0,
    )


def _batch_policy(args: argparse.Namespace) -> tuple[str, int]:
    """ページ失敗時の方針を (on_page_error, abort_after) で返す

    CLI フラグ > config.toml > 既定値 の優先順。
    """
    on_page_error = getattr(args, "on_page_error", None) or CONFIG.get(
        "batch.on_page_error", "skip"
    )
    abort_after = CONFIG.get("batch.abort_after_consecutive_failures", 3)
    return on_page_error, abort_after


def process_single(args: argparse.Namespace, image_path: Path) -> int:
    """1枚の画像を処理するパイプライン

    終了コード: 0=成功 / 2=保存はできたが一部欠けた / 1=保存物なし
    """
    # 前処理後画像は一時ディレクトリに置き、OCR入力に使う。
    # 保存時は save_document が temp 削除前に library へ実体コピーする。
    with tempfile.TemporaryDirectory(prefix="prewar_pre_") as tmp:
        pre_paths, pre_meta = _preprocess_images(args, [image_path], Path(tmp))
        ocr_target = pre_paths[0] if pre_paths else image_path

        # ── 1. OCR ──
        print(f"\n[1/3] OCR実行中: {image_path}")
        print(f"  モデル: {args.model}")

        client = _create_ocr_client(args)
        try:
            page = _run_ocr_page(client, ocr_target, image_path)
        except KeyboardInterrupt:
            print("\n⚠ 中断しました（保存するものがありません）")
            return 1
        if isinstance(page, MetaPageFailure):
            return 1

        result = page
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

        # ── 3. 口語体変換 ──（失敗しても正規化テキストで保存まで進む）
        modernizer = TextModernizer()
        modern, modern_meta = _run_modernize(modernizer, normalized, args)

        if not args.no_modernize:
            # 最終結果を表示
            print()
            print("=" * 50)
            print("変換結果")
            print("=" * 50)
            print(modern)
            print("-" * 50)

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
                    options=result.options,
                ),
                normalization=MetaNormalization(
                    old_kanji=not args.no_normalize,
                    historical_kana=not args.no_normalize,
                    ocr_misread_correction=not args.no_normalize,
                ),
                modernize=modern_meta,
                preprocessed_paths=pre_paths,
                preprocess=pre_meta,
            )
            doc_dir = save_document(record, library_root=Path(args.library_root))
            print(f"\n✓ ライブラリに保存: {doc_dir}")

            if args.legacy_output:
                legacy_path = _save_legacy(modern, image_path, Path(args.output))
                print(f"✓ 旧形式でも保存: {legacy_path}")

        # 口語体変換が部分的にしか成功しなかった場合は「部分成功」を伝える
        if modern_meta.error or modern_meta.failed_chunks:
            return 2
        return 0


def process_batch(args: argparse.Namespace, image_paths: list[Path]) -> int:
    """複数画像を結合して処理するパイプライン

    1枚のOCR失敗で全件を捨てず、成功したページだけで記録を作る（G2）。
    終了コード: 0=全ページ成功 / 2=一部欠けたが保存済み / 1=保存物なし
    """
    total = len(image_paths)
    names = ", ".join(p.name for p in image_paths)
    print(f"\n処理モード: 複数画像（{total}枚）")
    print(f"対象: {names}")

    with tempfile.TemporaryDirectory(prefix="prewar_pre_") as tmp:
        # 前処理（全画像）。無効なら元画像をそのままOCRに使う。
        pre_paths, pre_meta = _preprocess_images(args, image_paths, Path(tmp))
        ocr_targets = pre_paths if pre_paths else image_paths

        # ── 1. 各画像をOCR（失敗ページはスキップして継続）──
        client = _create_ocr_client(args)
        on_page_error, abort_after = _batch_policy(args)
        outcome = _ocr_pages(
            client,
            image_paths,
            ocr_targets,
            on_page_error=on_page_error,
            abort_after=abort_after,
        )

        if not outcome.results:
            _print_failure_summary(outcome, total, saved=False)
            return 1

        # 成功ページだけで以降を組み立てる
        # （画像とテキストを同じ添字で絞り、ページ順のズレを防ぐ）
        ocr_results = outcome.results
        ok_sources = [image_paths[i] for i in outcome.ok_indices]
        ok_pre_paths = (
            [pre_paths[i] for i in outcome.ok_indices] if pre_paths else None
        )

        # ── 2. テキスト結合 ──
        ocr_raw_combined = "\n\n".join(r.text for r in ocr_results)
        print(
            f"\n結合テキスト: {len(ocr_raw_combined)}文字"
            f"（{len(ocr_results)}/{total}画像分）"
        )

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

        # ── 4. 口語体変換 ──（失敗しても正規化テキストで保存まで進む）
        modernizer = TextModernizer()
        modern, modern_meta = _run_modernize(modernizer, normalized, args)

        if not args.no_modernize:
            # 最終結果を表示
            print()
            print("=" * 50)
            print("変換結果")
            print("=" * 50)
            print(modern)
            print("-" * 50)

        # ファイル保存
        if not args.no_save:
            # OCR メタ情報はバッチ全体を1件として記録する
            # （model/prompt はバッチ内で同一、elapsed_seconds は合計）
            record = DocumentRecord(
                source_paths=ok_sources,
                ocr_raw=ocr_raw_combined,
                modern_text=modern,
                ocr_meta=MetaOcr(
                    model=ocr_results[0].model,
                    prompt=ocr_results[0].prompt,
                    elapsed_seconds=sum(r.elapsed_seconds for r in ocr_results),
                    options=ocr_results[0].options,
                ),
                normalization=MetaNormalization(
                    old_kanji=not args.no_normalize,
                    historical_kana=not args.no_normalize,
                    ocr_misread_correction=not args.no_normalize,
                ),
                modernize=modern_meta,
                preprocessed_paths=ok_pre_paths,
                preprocess=pre_meta,
                page_failures=outcome.failures,
                pages_total=total,
                pages_aborted=outcome.aborted,
            )
            doc_dir = save_document(record, library_root=Path(args.library_root))
            print(f"\n✓ ライブラリに保存: {doc_dir}")

            if args.legacy_output:
                legacy_path = _save_legacy_batch(modern, ok_sources, Path(args.output))
                print(f"✓ 旧形式でも保存: {legacy_path}")

        _print_failure_summary(outcome, total)

        if outcome.failures or modern_meta.error or modern_meta.failed_chunks:
            return 2
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

    --separate では1枚失敗しても残りの画像を処理し続ける（G2）。
    終了コード: 0=全件成功 / 2=一部失敗 / 1=全件失敗
    """
    images = load_folder_images(folder)
    if images is None:
        return 1

    if args.separate:
        print(f"\n処理モード: 画像ごとに別記録（{len(images)}件）")
        failed: list[str] = []
        partial = False
        interrupted = False
        for i, image in enumerate(images, start=1):
            print(f"\n===== {i}/{len(images)}: {image.name} =====")
            try:
                code = process_single(args, image)
            except KeyboardInterrupt:
                print("\n⚠ 中断しました。ここまでの記録は保存済みです")
                interrupted = True
                break
            if code == 1:
                # 保存できなかった画像のみ「失敗」として数える
                # （2 は部分成功＝記録は保存済み）
                failed.append(image.name)
            elif code == 2:
                partial = True

        if failed:
            print(f"\n⚠ {len(images)}件中 {len(failed)}件が保存できませんでした:")
            for name in failed:
                print(f"  - {name}")
        if len(failed) == len(images):
            return 1
        if failed or partial or interrupted:
            return 2
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

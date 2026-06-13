"""
変換箇所の可視化（diff表示）

OCRパイプラインは多段でテキストを書き換える:

    ocr_raw.txt（OCR生）
      → normalize_text()         旧字体・仮名の「機械変換」
      → TextModernizer.modernize() qwen3.5 の「LLM変換（口語化）」
      → modern.txt（最終）

「何がどう変わったか」、特に LLM が勝手に書き換えた箇所（誤変換・ハルシネーション）
を目視で見つけられるよう、変換前後の差分をターミナルに色付きで表示する。

2段階に分けて見せる:
    段階1  ocr_raw   → 正規化後   （senzen_word 等による決定的な機械変換）
    段階2  正規化後  → modern     （qwen3.5 による非決定的な書き換え・要確認）

正規化後テキストはライブラリに保存されていないため、ocr_raw.txt から
normalize_text() を再実行して再現する（決定的・高速・外部依存なし）。
LLM段は非決定的かつ低速なので再実行せず、保存済み modern.txt を使う。

使い方:
    uv run prewar diff <doc_id>            # 2段階の色付きdiff
    uv run prewar diff <doc_id> --stage 1  # 機械変換のみ
    uv run prewar diff <doc_id> --no-color # 色なし（[-削除-]{+追加+} 表記）
"""

import argparse
import difflib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from utils.config import CONFIG
from utils.text_normalizer import normalize_text

# ---------- ANSIカラー ----------
RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"


# ---------- 差分計算（純粋関数・テスト対象） ----------


@dataclass
class DiffSegment:
    """差分の1区間。kind は difflib の opcode タグ。

    - equal:   before == after（変化なし）
    - delete:  before のみ（削除された）
    - insert:  after のみ（追加された）
    - replace: before → after（置換された）
    """

    kind: str
    before: str
    after: str


def compute_segments(before: str, after: str) -> list[DiffSegment]:
    """2つのテキストの文字単位の差分セグメント列を返す。

    日本語の旧字体変換（國→国）や仮名変換は1文字単位の置換が主なので、
    行単位ではなく文字単位（autojunk無効）で比較する。
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return [
        DiffSegment(tag, before[i1:i2], after[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
    ]


def count_changes(segments: list[DiffSegment]) -> tuple[int, int]:
    """(削除文字数, 追加文字数) を返す。サマリ表示用。

    replace は before を削除・after を追加の両方として数える。
    """
    deleted = sum(len(s.before) for s in segments if s.kind in ("delete", "replace"))
    added = sum(len(s.after) for s in segments if s.kind in ("insert", "replace"))
    return deleted, added


def _shorten_equal(text: str, context: int | None) -> str:
    """変化のない長い区間を前後 context 文字に省略する。

    context が None または 0以下、あるいは十分短いテキストはそのまま返す。
    """
    if not context or context <= 0:
        return text
    if len(text) <= context * 2:
        return text
    omitted = len(text) - context * 2
    return f"{text[:context]}…（中略{omitted}字）…{text[-context:]}"


def render_inline(
    segments: list[DiffSegment], use_color: bool, context: int | None
) -> str:
    """セグメント列を1本のインライン差分文字列に整形する。

    削除は赤、追加は緑で表示する。色なし時は [-削除-] {+追加+} の記号で表す
    （パイプ/リダイレクト時でも変更箇所が分かるように）。
    """
    parts: list[str] = []
    for seg in segments:
        if seg.kind == "equal":
            parts.append(_shorten_equal(seg.before, context))
        elif seg.kind == "delete":
            parts.append(_mark_delete(seg.before, use_color))
        elif seg.kind == "insert":
            parts.append(_mark_insert(seg.after, use_color))
        else:  # replace
            parts.append(_mark_delete(seg.before, use_color))
            parts.append(_mark_insert(seg.after, use_color))
    return "".join(parts)


def _mark_delete(text: str, use_color: bool) -> str:
    return f"{RED}{text}{RESET}" if use_color else f"[-{text}-]"


def _mark_insert(text: str, use_color: bool) -> str:
    return f"{GREEN}{text}{RESET}" if use_color else f"{{+{text}+}}"


# ---------- ターゲット解決・入出力 ----------


def _resolve_doc_dir(target: str, library_root: str) -> Path:
    """target をドキュメントフォルダに解決する。

    target がそのままフォルダなら採用、そうでなければ library_root/target を見る。
    """
    candidate = Path(target)
    if candidate.is_dir():
        return candidate
    return Path(library_root) / target


# ---------- CLI ----------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """diff サブコマンドの引数を追加する。"""
    parser.add_argument(
        "target",
        help="library のドキュメントID、または ocr_raw.txt/modern.txt のあるフォルダ",
    )
    parser.add_argument(
        "--stage",
        choices=["1", "2", "all"],
        default="all",
        help="1=機械変換, 2=LLM変換, all=両方（既定）",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="色付けを無効化（[-削除-]{+追加+} の記号で表示）",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=CONFIG.get("diff.context"),
        help="変更箇所の前後に残す文字数（0以下で全文表示）",
    )


def _should_use_color(no_color_flag: bool) -> bool:
    """色付けするかを判定する。

    --no-color / NO_COLOR 環境変数 / 非tty（パイプ・リダイレクト）/ 設定の
    いずれかが無効を示すなら色を付けない。
    """
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if not CONFIG.get("diff.color", True):
        return False
    return sys.stdout.isatty()


def _print_stage(title: str, before: str, after: str, use_color: bool, context: int) -> None:
    """1段階分の見出し・サマリ・インライン差分を表示する。"""
    segments = compute_segments(before, after)
    deleted, added = count_changes(segments)
    header = f"=== {title} ===  削除{deleted}字 / 追加{added}字"
    print(f"{DIM}{header}{RESET}" if use_color else header)
    print(render_inline(segments, use_color, context))
    print()


def run(args: argparse.Namespace) -> int:
    """diff サブコマンドの本体。"""
    library_root = getattr(args, "library_root", None) or CONFIG.get("paths.library")
    doc_dir = _resolve_doc_dir(args.target, library_root)

    raw_path = doc_dir / "ocr_raw.txt"
    modern_path = doc_dir / "modern.txt"
    missing = [p.name for p in (raw_path, modern_path) if not p.exists()]
    if missing:
        print(f"✗ ファイルが見つかりません: {doc_dir}/ （{', '.join(missing)}）")
        return 1

    ocr_raw = raw_path.read_text(encoding="utf-8")
    modern = modern_path.read_text(encoding="utf-8")
    # 正規化後テキストを再現（保存されていないため normalize_text を再実行）
    normalized = normalize_text(ocr_raw)

    use_color = _should_use_color(args.no_color)
    context = args.context

    if args.stage in ("1", "all"):
        _print_stage(
            "段階1: OCR生 → 正規化（旧字体・仮名の機械変換）",
            ocr_raw,
            normalized,
            use_color,
            context,
        )
    if args.stage in ("2", "all"):
        _print_stage(
            "段階2: 正規化 → modern（LLM口語化・要確認）",
            normalized,
            modern,
            use_color,
            context,
        )

    return 0

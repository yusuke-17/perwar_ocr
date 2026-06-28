"""
データ整理サブコマンド（prewar clean）

役割の異なる2系統を1つのサブコマンドに集約する。

- ``clean input``   … 処理後の残りカス画像 / セッションフォルダを掃除する。
                      ディスク整理が目的で、検索・要約には影響しない。
- ``clean library`` … OCR・正規化・LLM変換まで終えた誤った成果物を library から
                      削除し、検索インデックス（search.db）からも同期削除する。
                      これが検索・F1要約の汚染対策の本体。

設計方針:
- 削除は即時・完全削除（ゴミ箱なし）。ただし削除前に必ず確認プロンプトを出す
  （``--yes/-y`` で省略可）。
- input と library は独立。自動連動はしない（library/source.png は元画像の独立
  コピーであり、input を消しても library は無傷。逆方向の連動は良い成果物まで
  失う事故になるため意図的に実装しない）。
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import questionary

from utils.config import CONFIG
from utils.library_search import LibraryIndex

# OCR対象画像の拡張子（ocr_vision_llm と揃える）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


# ---------- CLI 引数 ----------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """clean サブコマンドの引数を追加する。"""
    parser.add_argument(
        "mode",
        choices=["input", "library"],
        help="整理対象: input（画像/セッション掃除）または library（誤記録削除）",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="library モード時の doc_id（library/ 直下のフォルダ名）。省略時は一覧から選択",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="input モード時、input/ の中身を丸ごと削除対象にする",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="確認プロンプトをスキップして即削除する",
    )


def run(args: argparse.Namespace) -> int:
    """clean サブコマンドの本体。mode で分岐する。"""
    library_root = getattr(args, "library_root", None) or CONFIG.get("paths.library")
    if args.mode == "input":
        return _clean_input(args)
    return _clean_library(args, Path(library_root))


# ---------- 共通ヘルパー ----------


def _confirm(message: str, assume_yes: bool) -> bool:
    """確認プロンプト。--yes 指定時は無条件 True。

    Ctrl+C 等でキャンセルされた場合は False（＝削除しない）扱い。
    """
    if assume_yes:
        return True
    answer = questionary.confirm(message, default=False).ask()
    return bool(answer)


def _format_size(num_bytes: int) -> str:
    """バイト数を人間が読みやすい単位に整形する。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _format_mtime(path: Path) -> str:
    """更新日時を YYYY-MM-DD HH:MM 形式で返す。"""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _dir_size(path: Path) -> int:
    """ディレクトリ配下の合計サイズ（バイト）を再帰的に求める。"""
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _entry_size(path: Path) -> int:
    """ファイルなら自身、フォルダなら配下合計のサイズを返す。"""
    return _dir_size(path) if path.is_dir() else path.stat().st_size


def _remove_path(path: Path) -> None:
    """ファイル/フォルダを完全削除する。"""
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


# ---------- input 整理 ----------


def _clean_input(args: argparse.Namespace) -> int:
    """input/ の画像ファイル・session_* フォルダを掃除する。"""
    input_dir = Path(CONFIG.get("paths.input"))
    if not input_dir.exists():
        print(f"✗ {input_dir}/ が見つかりません。")
        return 1

    # 直下の画像ファイルと session_* フォルダの両方を列挙（先頭 . は除外）
    entries = sorted(
        child
        for child in input_dir.iterdir()
        if not child.name.startswith(".")
        and (child.is_dir() or child.suffix.lower() in IMAGE_EXTENSIONS)
    )
    if not entries:
        print(f"{input_dir}/ に削除対象はありません。")
        return 0

    if args.all:
        targets = entries
    else:
        choices = [
            questionary.Choice(
                title=f"{e.name}{'/' if e.is_dir() else ''}  "
                f"[{_format_size(_entry_size(e))}, {_format_mtime(e)}]",
                value=e,
            )
            for e in entries
        ]
        selected = questionary.checkbox(
            "削除する項目を選んでください（スペースで選択 / Enterで確定）:",
            choices=choices,
        ).ask()
        if not selected:
            print("選択がないため中止しました。")
            return 0
        targets = selected

    print("\n削除対象:")
    for t in targets:
        print(f"  - {t.name}{'/' if t.is_dir() else ''}")

    if not _confirm(f"{len(targets)} 件を完全に削除します。よろしいですか？", args.yes):
        print("中止しました。")
        return 0

    removed = 0
    for t in targets:
        try:
            _remove_path(t)
            removed += 1
        except OSError as e:
            print(f"⚠ 削除に失敗しました（{t.name}）: {e}")
    print(f"✓ {removed} 件を削除しました。")
    return 0


# ---------- library 誤記録の削除 ----------


def _resolve_doc_dir(target: str, library_root: Path) -> Path:
    """target をドキュメントフォルダに解決する（diff_viewer と同じ規則）。"""
    candidate = Path(target)
    if candidate.is_dir():
        return candidate
    return library_root / target


def _load_title(doc_dir: Path) -> str:
    """meta.json から title を読む（読めなければ空文字）。"""
    meta_path = doc_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("title", "") or ""
    except (json.JSONDecodeError, OSError):
        return ""


def _iter_doc_dirs(library_root: Path) -> list[Path]:
    """library_root 直下の文書フォルダ（meta.json を持つ）を列挙する。"""
    if not library_root.exists():
        return []
    return sorted(
        child
        for child in library_root.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and (child / "meta.json").is_file()
    )


def _clean_library(args: argparse.Namespace, library_root: Path) -> int:
    """library の誤記録を削除し、検索インデックスからも同期削除する。"""
    if args.target:
        doc_dir = _resolve_doc_dir(args.target, library_root)
        if not doc_dir.is_dir():
            print(f"✗ ドキュメントが見つかりません: {doc_dir}")
            return 1
    else:
        doc_dirs = _iter_doc_dirs(library_root)
        if not doc_dirs:
            print(f"{library_root}/ に削除できる記録はありません。")
            return 0
        choices = [
            questionary.Choice(
                title=f"{d.name}  「{_load_title(d) or '（タイトルなし）'}」",
                value=d,
            )
            for d in doc_dirs
        ]
        doc_dir = questionary.select(
            "削除する記録を選んでください:",
            choices=choices,
        ).ask()
        if doc_dir is None:
            print("選択がないため中止しました。")
            return 0

    doc_id = doc_dir.name
    title = _load_title(doc_dir)
    print(f"\n削除対象: {doc_id}  「{title or '（タイトルなし）'}」")

    if not _confirm(
        f"記録「{doc_id}」をフォルダごと完全削除し、検索インデックスからも消します。"
        "よろしいですか？",
        args.yes,
    ):
        print("中止しました。")
        return 0

    # 1) フォルダを物理削除
    try:
        shutil.rmtree(doc_dir)
    except OSError as e:
        print(f"✗ フォルダ削除に失敗しました: {e}")
        return 1

    # 2) 検索インデックス（search.db）から同期削除
    index = LibraryIndex(library_root)
    existed = index.delete(doc_id)

    print(f"✓ {doc_id} を削除しました。")
    if existed:
        print("  検索インデックスからも削除しました。")
    else:
        print("  （インデックスには未登録でした）")
    return 0

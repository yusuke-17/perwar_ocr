"""
ライブラリ検索 CLI

library/ 配下に蓄積された文書を全文検索する。
サブコマンド型（index / find / stat）。

使い方:
    uv run prewar-library index                  # 差分更新
    uv run prewar-library index --rebuild         # 全件再構築
    uv run prewar-library find 関東 震災          # AND検索
    uv run prewar-library find 警察 --limit 50
    uv run prewar-library find 警察 --format json
    uv run prewar-library stat                    # 統計情報
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from utils.library_search import (
    IndexStats,
    LibraryIndex,
    QueryTooShortError,
    SearchHit,
)


def add_library_root_argument(parser: argparse.ArgumentParser) -> None:
    """--library-root オプションを追加する（統合CLIの各サブコマンドで流用）"""
    parser.add_argument(
        "--library-root",
        type=str,
        default="library",
        help="ライブラリのルートディレクトリ（デフォルト: library/）",
    )


def add_index_arguments(parser: argparse.ArgumentParser) -> None:
    """index サブコマンドの引数を追加する"""
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="既存インデックスを削除して全件再構築",
    )


def add_find_arguments(parser: argparse.ArgumentParser) -> None:
    """find サブコマンドの引数を追加する"""
    parser.add_argument(
        "query",
        type=str,
        nargs="+",
        help="検索語（スペース区切りで複数指定するとAND検索）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="表示件数の上限（デフォルト: 20）",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="出力形式（デフォルト: text）",
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """library 全体の引数（共通オプション + index/find/stat サブコマンド）を追加する"""
    add_library_root_argument(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_index = subparsers.add_parser("index", help="検索インデックスを更新")
    add_index_arguments(p_index)

    p_find = subparsers.add_parser("find", help="ライブラリを全文検索")
    add_find_arguments(p_find)

    subparsers.add_parser("stat", help="ライブラリの統計情報を表示")


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="戦前日本語OCRライブラリ検索ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run prewar-library index                # 差分更新
  uv run prewar-library index --rebuild       # 全件再構築
  uv run prewar-library find 警察             # 単一語検索
  uv run prewar-library find 関東 震災         # AND検索
  uv run prewar-library find 警察 --limit 50
  uv run prewar-library find 警察 --format json
  uv run prewar-library stat                  # 統計情報
        """,
    )
    add_arguments(parser)
    return parser.parse_args()


# ---------- 各サブコマンド ----------


def cmd_index(args: argparse.Namespace) -> int:
    """index サブコマンド"""
    library_root = Path(args.library_root)
    if not library_root.exists():
        print(f"✗ ライブラリディレクトリが見つかりません: {library_root}")
        return 1

    idx = LibraryIndex(library_root)
    print(f"インデックス{'再構築' if args.rebuild else '更新'}中: {library_root}/")

    if args.rebuild:
        stats = idx.rebuild()
    else:
        stats = idx.update()

    _print_stats(stats)
    print("✓ 完了")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """find サブコマンド"""
    library_root = Path(args.library_root)
    if not library_root.exists():
        print(f"✗ ライブラリディレクトリが見つかりません: {library_root}")
        return 1

    idx = LibraryIndex(library_root)

    # インデックス未構築なら自動で update
    if not idx.db_path.exists():
        print("⚠ インデックス未構築のため自動で更新します...")
        idx.update()
        print()

    query = " ".join(args.query)
    try:
        hits = idx.search(query, limit=args.limit)
    except QueryTooShortError as e:
        print(f"✗ {e}")
        return 1

    if args.format == "json":
        print(json.dumps([_hit_to_dict(h) for h in hits], ensure_ascii=False, indent=2))
        return 0

    if not hits:
        print(f'検索結果なし: "{query}"')
        return 0

    for h in hits:
        print(f"[{h.id}] {h.title or '(タイトルなし)'}")
        try:
            rel = h.dir.relative_to(Path.cwd())
            dir_display = str(rel)
        except ValueError:
            dir_display = str(h.dir)
        print(f"  場所: {dir_display}/")
        print(f"  抜粋: {h.snippet}")
        print(f"  作成: {h.created_at}")
        print()

    print(f"→ {len(hits)}件{'（--limit で上限）' if len(hits) >= args.limit else ''}")
    return 0


def cmd_stat(args: argparse.Namespace) -> int:
    """stat サブコマンド"""
    library_root = Path(args.library_root)
    if not library_root.exists():
        print(f"✗ ライブラリディレクトリが見つかりません: {library_root}")
        return 1

    idx = LibraryIndex(library_root)

    if not idx.db_path.exists():
        print("⚠ インデックス未構築のため自動で更新します...")
        idx.update()
        print()

    s = idx.stat()
    print(f"ライブラリ: {s['library_root']}")
    print(f"文書数: {s['document_count']}")
    print(f"インデックスサイズ: {s['db_size_bytes'] / 1024:.1f} KB")
    if s["latest_doc_mtime"]:
        dt = datetime.fromtimestamp(s["latest_doc_mtime"])
        print(f"最終更新: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("最終更新: (文書なし)")
    return 0


# ---------- ヘルパー ----------


def _print_stats(stats: IndexStats) -> None:
    print(f"  追加: {stats.added}件")
    print(f"  更新: {stats.updated}件")
    print(f"  削除: {stats.removed}件")
    print(f"  スキップ: {stats.skipped}件")


def _hit_to_dict(hit: SearchHit) -> dict:
    d = asdict(hit)
    d["dir"] = str(hit.dir)
    return d


# ---------- エントリポイント ----------


def run(args: argparse.Namespace) -> int:
    """パース済み引数を受け取り、対応するサブコマンドを実行する"""
    if args.command == "index":
        return cmd_index(args)
    if args.command == "find":
        return cmd_find(args)
    if args.command == "stat":
        return cmd_stat(args)
    return 1


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())

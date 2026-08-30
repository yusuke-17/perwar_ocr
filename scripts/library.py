"""
ライブラリ検索 CLI

library/ 配下に蓄積された文書を全文検索する。
サブコマンド型（index / find / stat）。

使い方:
    uv run prewar-library index                     # 差分更新
    uv run prewar-library index --rebuild            # 全件再構築
    uv run prewar-library find 関東地方 震災被害      # AND検索
    uv run prewar-library find 関東地方 OR 大阪府下   # OR検索
    uv run prewar-library find 震災被害 NOT 大阪府下  # 除外
    uv run prewar-library find 原文:罹災者            # 対象を限定
    uv run prewar-library find 警察署 --limit 50
    uv run prewar-library find 警察署 --format json
    uv run prewar-library stat                       # 統計情報
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from utils.config import CONFIG
from utils.library_search import (
    SNIPPET_MAX_CHARS,
    IndexStats,
    LibraryIndex,
    LibrarySearchError,
    SearchHit,
    split_marked,
)
from utils.terminal import MATCH, RESET, should_use_color

# 一致対象の表示名（内部のカラム名を利用者向けの言葉に置き換える）
_FIELD_LABELS = {"title": "題名", "modern": "口語", "original": "原文"}


def add_library_root_argument(parser: argparse.ArgumentParser) -> None:
    """--library-root オプションを追加する（統合CLIの各サブコマンドで流用）"""
    parser.add_argument(
        "--library-root",
        type=str,
        default=CONFIG.get("paths.library"),
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
        help=(
            "検索語。スペース区切りでAND検索。"
            "OR を挟むとOR検索、NOT 以降は除外語、"
            "原文:語 / 口語:語 / 題名:語 で一致対象を限定できる"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=CONFIG.get("search.limit"),
        help="表示件数の上限（デフォルト: 20）",
    )
    parser.add_argument(
        "--snippet",
        type=int,
        default=CONFIG.get("search.snippet_chars"),
        help=f"抜粋の長さ（デフォルト: 40、上限: {SNIPPET_MAX_CHARS}）",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="一致箇所の色付けを無効化",
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
  uv run prewar-library index                     # 差分更新
  uv run prewar-library index --rebuild            # 全件再構築
  uv run prewar-library find 警察署                # 単一語検索
  uv run prewar-library find 関東地方 震災被害      # AND検索（すべて含む）
  uv run prewar-library find 関東地方 OR 大阪府下   # OR検索（いずれかを含む）
  uv run prewar-library find 震災被害 NOT 大阪府下  # 除外（NOT以降を含まない）
  uv run prewar-library find 原文:罹災者            # 原文にだけ残る語を狙う
  uv run prewar-library find 警察署 --limit 50 --snippet 64
  uv run prewar-library find 警察署 --format json
  uv run prewar-library stat                       # 統計情報

検索構文:
  語 語        すべてを含む（AND）
  語 OR 語     いずれかを含む（OR。1つでも OR があれば語群全体が OR になる）
  語 NOT 語    NOT 以降を除外（除外語が複数ならそのいずれかを含む文書を除く）
  原文:語      一致対象を限定（原文 / 口語 / 題名。全角コロンも可）

  ※ 各語は正規化後3文字以上必要（trigram索引のため）
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
        hits = idx.search(query, limit=args.limit, snippet_chars=args.snippet)
    except (LibrarySearchError, ValueError) as e:
        print(f"✗ {e}")
        return 1

    if args.format == "json":
        print(json.dumps([_hit_to_dict(h) for h in hits], ensure_ascii=False, indent=2))
        return 0

    if not hits:
        print(f'検索結果なし: "{query}"')
        return 0

    use_color = should_use_color(args.no_color, "search.color")
    for h in hits:
        print(f"[{h.id}] {h.title or '(タイトルなし)'}")
        try:
            rel = h.dir.relative_to(Path.cwd())
            dir_display = str(rel)
        except ValueError:
            dir_display = str(h.dir)
        print(f"  場所: {dir_display}/")
        print(f"  抜粋: {_render_snippet(h.snippet, use_color)}")
        print(f"  一致: {_matched_summary(h)}{_matched_note(h)}")
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


def _render_snippet(marked: str, use_color: bool) -> str:
    """マーカ付き抜粋を表示用の文字列にする

    色が使えないときはマーカを取り除くだけで、本文は色付き時と一致する。
    表示用の記号を本文に混ぜないのは、本文が元から角括弧などを含んでいても
    強調と見分けがつくようにするため。
    """
    plain, spans = split_marked(marked)
    if not use_color or not spans:
        return plain

    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(plain[cursor:start])
        parts.append(f"{MATCH}{plain[start:end]}{RESET}")
        cursor = end
    parts.append(plain[cursor:])
    return "".join(parts)


def _matched_summary(hit: SearchHit) -> str:
    """一致した対象と箇所数の要約（例: "原文3 / 口語1"）

    並び順を決める bm25 の値は出さない。trigram かつ語彙の偏った小規模な
    資料集では、頻出語のスコアが全件ゼロ付近に潰れて序列にならないため
    （実測: 200件中196件ヒットで best/worst とも -0.000）。
    """
    parts = [
        f"{_FIELD_LABELS[name]}{hit.match_counts.get(name, 0)}"
        for name in hit.matched_fields
    ]
    return " / ".join(parts) if parts else "(なし)"


def _matched_note(hit: SearchHit) -> str:
    """原文にのみ一致した場合の注記

    口語化で語が言い換えられた箇所に当たったことを示す。史料調査では
    「どの語が現代語に置き換わったか」自体が手がかりになるため明示する。
    """
    if "original" in hit.matched_fields and "modern" not in hit.matched_fields:
        return "  ← 原文のみ一致：口語化で語が変わっています"
    return ""


def _hit_to_dict(hit: SearchHit) -> dict:
    """JSON 出力用の dict にする

    snippet は表示用の装飾を含まない素の抜粋にし、一致箇所は
    snippet_highlights（[開始, 終了) の位置）として機械処理できる形で持たせる。
    """
    d = asdict(hit)
    d["dir"] = str(hit.dir)
    d["matched_fields"] = list(hit.matched_fields)  # asdict は tuple のまま返す
    plain, spans = split_marked(hit.snippet)
    d["snippet"] = plain
    d["snippet_highlights"] = [[start, end] for start, end in spans]
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

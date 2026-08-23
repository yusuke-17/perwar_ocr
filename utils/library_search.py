"""
ライブラリ検索インデックスモジュール

library/ 配下に蓄積された文書を SQLite FTS5 (trigram tokenizer) で全文検索する。
完全ローカル動作・Python 標準ライブラリ（sqlite3）のみで完結。

使い方:
    from pathlib import Path
    from utils.library_search import LibraryIndex

    idx = LibraryIndex(Path("library"))
    stats = idx.update()                  # 差分更新
    hits = idx.search("関東 震災", limit=20)  # AND検索
    for h in hits:
        print(h.id, h.title, h.snippet)
"""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from utils.config import CONFIG
from utils.text_normalizer import normalize_query, normalize_text

# ---------- 定数 ----------

INDEX_DIR_NAME = ".index"
INDEX_DB_NAME = "search.db"
TRIGRAM_MIN_QUERY_CHARS = CONFIG.get("search.min_query_chars")  # FTS5 trigram は3文字未満を扱えない

# 索引スキーマの版。PRAGMA user_version に刻み、不一致なら索引を作り直す。
#
# 【重要】このファイルのテーブル定義を変えたときだけでなく、
# normalize_text() の変換規則を変えたときも必ずこの値を上げること。
# 索引には normalize_text() を通した結果が入っているため、規則だけ変えると
# 古い規則で作られた索引が残り、新しい規則のクエリと噛み合わなくなる。
INDEX_SCHEMA_VERSION = 2

# 索引の入力となるファイル（差分更新の変更検知はこの3つを見る）
_SOURCE_FILES = ("meta.json", "modern.txt", "ocr_raw.txt")

# 一致カラムの判定に使う区切り文字（STX/ETX）。本文に出現しないことを保証するため
# 制御文字を使う。highlight() がこのマーカを入れたかどうかで一致を判定する。
_MARK_OPEN = "\x02"
_MARK_CLOSE = "\x03"

# FTS テーブルのカラム番号（snippet()/highlight() に渡す）。
# 0 = id (UNINDEXED), 1 = title, 2 = modern, 3 = original
_FTS_FIELDS = ((1, "title"), (2, "modern"), (3, "original"))


# ---------- データクラス ----------


@dataclass
class SearchHit:
    """検索結果1件

    matched_fields は検索語が実際に一致した対象の一覧
    （"title" / "modern" / "original" の組み合わせ）。
    ("original",) だけなら「口語化で言い換えられて消えた語」に当たったことを意味する。
    """

    id: str
    dir: Path
    title: str
    snippet: str
    created_at: str
    matched_fields: tuple[str, ...] = ()


@dataclass
class IndexStats:
    """インデックス更新の集計"""

    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0


# ---------- 例外クラス ----------


class LibrarySearchError(Exception):
    """検索機能の汎用例外"""

    pass


class QueryTooShortError(LibrarySearchError):
    """検索語が短すぎて trigram で扱えない"""

    pass


# ---------- メインクラス ----------


class LibraryIndex:
    """ライブラリ全文検索インデックス

    SQLite FTS5 + trigram tokenizer により、日本語の部分一致検索を提供する。

    インデックス対象は3つ:
      - title   … meta.json の題名を normalize_text() で正規化したもの（照合用）
      - modern  … modern.txt（LLM口語化後）
      - original… ocr_raw.txt を normalize_text() で正規化したもの（＝正規化済み原文）

    original を索引するのは、口語化で言い換えられた語（「罹災者」→「被災者」等）が
    原文の語で検索できなくなるのを防ぐため。正規化済み原文はファイルとして
    保存されていないので、索引時に normalize_text() を再実行して得る
    （決定的・外部依存なし。scripts/diff_viewer.py と同じ手法）。
    """

    def __init__(self, library_root: Path):
        self.library_root = library_root

    @property
    def db_path(self) -> Path:
        return self.library_root / INDEX_DIR_NAME / INDEX_DB_NAME

    # ---------- public API ----------

    def update(self) -> IndexStats:
        """差分更新

        索引の入力となる meta.json / modern.txt / ocr_raw.txt の mtime 署名を
        DB に記録した値と比較し、変化のあった文書だけ再インデックスする。
        フォルダごと削除された文書は DB からも消す。

        索引スキーマの版が古い場合は _ensure_schema がテーブルを作り直すため、
        existing が空になり結果的に全件が再索引される（追加の分岐は不要）。
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            stats = IndexStats()

            existing = {
                row[0]: row[1]
                for row in conn.execute("SELECT id, source_sig FROM documents")
            }
            seen: set[str] = set()

            for meta_path in self._iter_meta_paths():
                doc_dir = meta_path.parent
                doc_id = doc_dir.name
                mtime = meta_path.stat().st_mtime
                source_sig = self._source_sig(doc_dir)
                seen.add(doc_id)

                is_update = doc_id in existing
                if is_update and existing[doc_id] == source_sig:
                    continue  # 入力ファイルがどれも変わっていない

                meta = self._load_meta(meta_path)
                modern = self._load_modern(doc_dir)
                if meta is None or modern is None:
                    stats.skipped += 1
                    continue
                original = self._load_original(doc_dir)

                if is_update:
                    self._delete_doc(conn, doc_id)
                    stats.updated += 1
                else:
                    stats.added += 1
                self._insert_doc(
                    conn, doc_id, doc_dir, meta, modern, original, mtime, source_sig
                )

            # 消えた文書を削除
            for doc_id in existing.keys() - seen:
                self._delete_doc(conn, doc_id)
                stats.removed += 1

            conn.commit()
            return stats
        finally:
            conn.close()

    def rebuild(self) -> IndexStats:
        """全削除して再構築"""
        # DB ファイルごと削除
        if self.db_path.exists():
            self.db_path.unlink()
        return self.update()

    def delete(self, doc_id: str) -> bool:
        """インデックスから文書を1件だけ削除する。

        documents / search 両テーブルから該当 ID を消す。
        削除前に存在した場合のみ True を返す（存在しなければ False）。
        library フォルダ自体の削除は呼び出し側の責務。
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            existed = (
                conn.execute(
                    "SELECT 1 FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
                is not None
            )
            self._delete_doc(conn, doc_id)
            conn.commit()
            return existed
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        """全文検索

        スペース区切りの語は AND 検索。各語は trigram で部分一致する。
        2文字未満の語が含まれていたら QueryTooShortError を投げる。
        """
        match_expr = self._build_match_expr(query)
        self._ensure_ready()
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            # snippet の第2引数 -1 は「最もよく一致したカラムから抜粋する」指定。
            # 原文にのみ残る語で当たったときに、その箇所が抜粋に出る。
            # highlight() は一致が無ければマーカを入れずにカラム全文を返すので、
            # マーカの有無がそのまま「そのカラムが一致したか」を表す。
            marks = ", ".join(
                f"instr(highlight(search, {num}, ?, ?), ?) > 0" for num, _ in _FTS_FIELDS
            )
            params: list = []
            for _ in _FTS_FIELDS:
                params.extend([_MARK_OPEN, _MARK_CLOSE, _MARK_OPEN])

            cur = conn.execute(
                f"""
                SELECT s.id,
                       snippet(search, -1, '[', ']', '...', 16) AS sn,
                       d.dir,
                       d.title,
                       d.created_at,
                       {marks}
                  FROM search s JOIN documents d ON s.id = d.id
                 WHERE search MATCH ?
                 ORDER BY bm25(search)
                 LIMIT ?
                """,
                (*params, match_expr, limit),
            )
            return [
                SearchHit(
                    id=row[0],
                    dir=Path(row[2]),
                    title=row[3],
                    snippet=row[1],
                    created_at=row[4],
                    matched_fields=tuple(
                        name for i, (_, name) in enumerate(_FTS_FIELDS) if row[5 + i]
                    ),
                )
                for row in cur
            ]
        finally:
            conn.close()

    def stat(self) -> dict:
        """インデックスの統計情報"""
        self._ensure_ready()
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            (count,) = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
            (latest_mtime,) = conn.execute(
                "SELECT MAX(mtime) FROM documents"
            ).fetchone()
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "library_root": str(self.library_root.resolve()),
                "document_count": count,
                "db_size_bytes": db_size,
                "latest_doc_mtime": latest_mtime,
            }
        finally:
            conn.close()

    # ---------- private ----------

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _ensure_ready(self) -> None:
        """索引スキーマが古ければ作り直してから全件を再索引する

        search() / stat() の先頭で呼ぶ。update() は移行後に existing が空になり
        自然に全件再索引されるので、この関数を通す必要がない。
        """
        conn = self._connect()
        try:
            migrated = self._ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()

        if migrated:
            print("⚠ インデックス形式が変わったため再構築します...")
            self.update()

    def _ensure_schema(self, conn: sqlite3.Connection) -> bool:
        """スキーマを用意する

        PRAGMA user_version に刻んだ版が現行と異なれば、テーブルを作り直す。
        破棄するのは索引（library/.index/search.db）の中身だけで、
        ライブラリ内の資料ファイルには一切触れない（索引はいつでも再生成できる派生物）。

        Returns:
            移行のためにテーブルを作り直したら True。新規作成・変更なしなら False。
        """
        (version,) = conn.execute("PRAGMA user_version").fetchone()
        has_tables = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = 'documents'"
            ).fetchone()
            is not None
        )

        # 旧DBは user_version が 0。テーブルがあるのに版が違う＝移行が必要。
        migrated = has_tables and version != INDEX_SCHEMA_VERSION
        if migrated:
            conn.executescript(
                """
                DROP TABLE IF EXISTS documents;
                DROP TABLE IF EXISTS search;
                """
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                dir         TEXT NOT NULL,
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                mtime       REAL NOT NULL,
                source_sig  TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                id UNINDEXED,
                title,
                modern,
                original,
                tokenize = 'trigram'
            );
            """
        )
        if version != INDEX_SCHEMA_VERSION:
            # PRAGMA はプレースホルダを受け付けないので定数を直接埋める
            conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
        return migrated

    def _iter_meta_paths(self) -> Iterator[Path]:
        """library_root 配下の meta.json を列挙

        '.' で始まるフォルダ（`.index` 等）は除外する。
        """
        if not self.library_root.exists():
            return
        for child in self.library_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            meta_path = child / "meta.json"
            if meta_path.is_file():
                yield meta_path

    def _load_meta(self, meta_path: Path) -> dict | None:
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠ meta.json を読めません ({meta_path}): {e}")
            return None

    def _load_modern(self, doc_dir: Path) -> str | None:
        modern_path = doc_dir / "modern.txt"
        if not modern_path.is_file():
            print(f"⚠ modern.txt がありません: {doc_dir}")
            return None
        try:
            return modern_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"⚠ modern.txt を読めません ({modern_path}): {e}")
            return None

    def _load_original(self, doc_dir: Path) -> str:
        """正規化済み原文を得る（ocr_raw.txt に normalize_text を適用）

        正規化後テキストはファイル保存されていないため、索引時に再計算する。
        normalize_text() は決定的な純Python変換で、外部通信も乱数も無い。

        _load_modern と挙動が異なる点に注意:
        modern.txt が読めない文書は「本文が無い」ので索引ごとスキップするが、
        ocr_raw.txt が読めなくても空文字を返し、文書自体はスキップしない。
        口語化後テキストによる検索は従来どおり機能させるため。
        """
        raw_path = doc_dir / "ocr_raw.txt"
        if not raw_path.is_file():
            print(f"⚠ ocr_raw.txt がありません（原文検索は無効）: {doc_dir}")
            return ""
        try:
            return normalize_text(raw_path.read_text(encoding="utf-8"))
        except OSError as e:
            print(f"⚠ ocr_raw.txt を読めません（原文検索は無効） ({raw_path}): {e}")
            return ""

    def _source_sig(self, doc_dir: Path) -> str:
        """索引入力3ファイルの mtime 署名

        meta.json / modern.txt / ocr_raw.txt の mtime を連結した文字列を返す
        （欠損は "-"）。文字列一致で変更を判定するため、ファイルを古い版に
        戻した場合（mtime が小さくなる場合）も検知できる。
        """
        parts = []
        for name in _SOURCE_FILES:
            path = doc_dir / name
            try:
                parts.append(f"{name}:{path.stat().st_mtime:.6f}")
            except OSError:
                parts.append(f"{name}:-")
        return "|".join(parts)

    def _insert_doc(
        self,
        conn: sqlite3.Connection,
        doc_id: str,
        doc_dir: Path,
        meta: dict,
        modern: str,
        original: str,
        mtime: float,
        source_sig: str,
    ) -> None:
        title = meta.get("title", "") or ""
        created_at = meta.get("created_at", "") or ""
        conn.execute(
            "INSERT INTO documents (id, dir, title, created_at, mtime, source_sig) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, str(doc_dir.resolve()), title, created_at, mtime, source_sig),
        )
        # 表示用と照合用の分離: documents.title は生のまま（検索結果に出す題名）、
        # FTS の title は normalize_text() 済み（正規化されたクエリと噛み合わせる）。
        # 題名は生OCRから切り出すため旧字体・歴史的仮名遣いを含みうる。
        conn.execute(
            "INSERT INTO search (id, title, modern, original) VALUES (?, ?, ?, ?)",
            (doc_id, normalize_text(title), modern, original),
        )

    def _delete_doc(self, conn: sqlite3.Connection, doc_id: str) -> None:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.execute("DELETE FROM search WHERE id = ?", (doc_id,))

    def _build_match_expr(self, query: str) -> str:
        """スペース区切りクエリを FTS5 の AND 構文に変換

        - 半角/全角スペースで分割
        - 各語を normalize_query() で照合用に正規化（旧字体・仮名遣い等を
          インデックス側 modern.txt と揃える）
        - 正規化「後」の文字数が TRIGRAM_MIN_QUERY_CHARS 未満なら
          QueryTooShortError（拗音縮約で字数が縮むため長さ判定は正規化の後）
        - ダブルクォートで囲んで AND 連結（特殊文字を無害化）
        """
        # 半角/全角スペース両方で分割
        raw_terms = [t for t in query.replace("　", " ").split(" ") if t]
        if not raw_terms:
            raise QueryTooShortError("検索語が空です")

        # 各語を照合用に正規化（インデックス側と字体・仮名遣いを揃える）
        terms = [normalize_query(t) for t in raw_terms]

        for term in terms:
            if len(term) < TRIGRAM_MIN_QUERY_CHARS:
                raise QueryTooShortError(
                    f'"{term}" は{TRIGRAM_MIN_QUERY_CHARS}文字未満のため '
                    "trigram で検索できません"
                )

        # ダブルクォート内のダブルクォートは "" にエスケープ
        quoted = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms]
        return " AND ".join(quoted)

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

from utils.text_normalizer import normalize_query

# ---------- 定数 ----------

INDEX_DIR_NAME = ".index"
INDEX_DB_NAME = "search.db"
TRIGRAM_MIN_QUERY_CHARS = 3  # FTS5 trigram は3文字未満を扱えない


# ---------- データクラス ----------


@dataclass
class SearchHit:
    """検索結果1件"""

    id: str
    dir: Path
    title: str
    snippet: str
    created_at: str


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
    インデックス対象は modern.txt と meta.json の title のみ（ocr_raw は除外）。
    """

    def __init__(self, library_root: Path):
        self.library_root = library_root

    @property
    def db_path(self) -> Path:
        return self.library_root / INDEX_DIR_NAME / INDEX_DB_NAME

    # ---------- public API ----------

    def update(self) -> IndexStats:
        """差分更新

        meta.json の mtime を DB に記録した値と比較し、変化のあった文書だけ
        再インデックスする。フォルダごと削除された文書は DB からも消す。
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            stats = IndexStats()

            existing = {
                row[0]: row[1] for row in conn.execute("SELECT id, mtime FROM documents")
            }
            seen: set[str] = set()

            for meta_path in self._iter_meta_paths():
                doc_id = meta_path.parent.name
                mtime = meta_path.stat().st_mtime
                seen.add(doc_id)

                if doc_id in existing:
                    if abs(existing[doc_id] - mtime) < 1e-6:
                        continue  # 変化なし
                    # 更新
                    meta = self._load_meta(meta_path)
                    modern = self._load_modern(meta_path.parent)
                    if meta is None or modern is None:
                        stats.skipped += 1
                        continue
                    self._delete_doc(conn, doc_id)
                    self._insert_doc(conn, doc_id, meta_path.parent, meta, modern, mtime)
                    stats.updated += 1
                else:
                    # 追加
                    meta = self._load_meta(meta_path)
                    modern = self._load_modern(meta_path.parent)
                    if meta is None or modern is None:
                        stats.skipped += 1
                        continue
                    self._insert_doc(conn, doc_id, meta_path.parent, meta, modern, mtime)
                    stats.added += 1

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

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        """全文検索

        スペース区切りの語は AND 検索。各語は trigram で部分一致する。
        2文字未満の語が含まれていたら QueryTooShortError を投げる。
        """
        match_expr = self._build_match_expr(query)
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.execute(
                """
                SELECT s.id,
                       snippet(search, 2, '[', ']', '...', 16) AS sn,
                       d.dir,
                       d.title,
                       d.created_at
                  FROM search s JOIN documents d ON s.id = d.id
                 WHERE search MATCH ?
                 ORDER BY bm25(search)
                 LIMIT ?
                """,
                (match_expr, limit),
            )
            return [
                SearchHit(
                    id=row[0],
                    dir=Path(row[2]),
                    title=row[3],
                    snippet=row[1],
                    created_at=row[4],
                )
                for row in cur
            ]
        finally:
            conn.close()

    def stat(self) -> dict:
        """インデックスの統計情報"""
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

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                dir         TEXT NOT NULL,
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                mtime       REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                id UNINDEXED,
                title,
                modern,
                tokenize = 'trigram'
            );
            """
        )

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

    def _insert_doc(
        self,
        conn: sqlite3.Connection,
        doc_id: str,
        doc_dir: Path,
        meta: dict,
        modern: str,
        mtime: float,
    ) -> None:
        title = meta.get("title", "") or ""
        created_at = meta.get("created_at", "") or ""
        conn.execute(
            "INSERT INTO documents (id, dir, title, created_at, mtime) VALUES (?, ?, ?, ?, ?)",
            (doc_id, str(doc_dir.resolve()), title, created_at, mtime),
        )
        conn.execute(
            "INSERT INTO search (id, title, modern) VALUES (?, ?, ?)",
            (doc_id, title, modern),
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

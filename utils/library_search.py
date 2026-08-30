"""
ライブラリ検索インデックスモジュール

library/ 配下に蓄積された文書を SQLite FTS5 (trigram tokenizer) で全文検索する。
完全ローカル動作・Python 標準ライブラリ（sqlite3）のみで完結。

使い方:
    from pathlib import Path
    from utils.library_search import LibraryIndex

    idx = LibraryIndex(Path("library"))
    stats = idx.update()                       # 差分更新
    hits = idx.search("関東地方 震災被害")       # AND検索
    hits = idx.search("関東地方 OR 大阪府下")    # OR検索
    hits = idx.search("震災被害 NOT 大阪府下")   # 除外
    hits = idx.search("原文:罹災者")             # 対象を限定
    for h in hits:
        print(h.id, h.title, h.snippet)
"""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
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

# 一致箇所を示すマーカ（STX/ETX）。本文に出現しないことを保証するため制御文字を使う。
# highlight() / snippet() の開始・終了記号として渡し、
#   - highlight(): マーカの個数がそのカラムの一致箇所数になる
#   - snippet():   抜粋のどこが一致箇所かを表示層へ伝える
# 表示用の記号（角括弧・ANSI色）をここで埋め込まないのは、text 出力と JSON 出力で
# 必要な表現が違うため。変換は scripts/library.py（表示層）の責務。
MARK_OPEN = "\x02"
MARK_CLOSE = "\x03"

# 抜粋の省略記号（trigram では snippet の N がほぼ文字数に対応する）
_SNIPPET_ELLIPSIS = "…"

# 抜粋長の上限。SQLite の snippet() は N を「0 より大きく 64 以下」と定めている。
# 手元の 3.50.4 は 64 超も通すが、ドキュメント外の挙動に依存すると版が上がったとき
# 黙って壊れるため上限で丸める。これ以上が必要になったら highlight() の全文から
# 自前で窓を切り出す方式へ移行する（design.md Decision 5）。
SNIPPET_MAX_CHARS = 64

# FTS テーブルのカラム番号（snippet()/highlight() に渡す）。
# 0 = id (UNINDEXED), 1 = title, 2 = modern, 3 = original
_FTS_FIELDS = ((1, "title"), (2, "modern"), (3, "original"))

# 検索対象カラムの別名。利用者が書くのは日本語（`原文:罹災者`）でも英語でもよい。
#
# 別名表を挟むのは、利用者の入力が FTS5 の識別子として解釈される経路を断つため。
# 生の識別子を通すと未知のカラム名が SQLite の `no such column` として漏れ、
# 実装の内部（FTS5 のカラム名）が利用者に露出する。
FIELD_ALIASES: dict[str, str] = {
    "原文": "original",
    "元": "original",
    "original": "original",
    "口語": "modern",
    "現代": "modern",
    "modern": "modern",
    "題名": "title",
    "表題": "title",
    "title": "title",
}

# カラム限定の区切り文字。日本語入力からそのまま打てるよう全角コロンも受ける。
_FIELD_SEPARATORS = (":", "：")

# 演算子。記号（`-除外`）を使わないのは argparse の nargs="+" が `-` 始まりの語を
# 未知オプションとして飲み込むため（design.md Decision 1）。
_OP_OR = "OR"
_OP_NOT = "NOT"

# 語の役割（エラーメッセージで「どの語が弾かれたか」を伝えるために使う）
_ROLE_TERM = "検索語"
_ROLE_EXCLUDE = "除外語"
_ROLE_FIELD = "限定語"


# ---------- データクラス ----------


@dataclass
class SearchHit:
    """検索結果1件

    snippet は一致箇所を MARK_OPEN / MARK_CLOSE で囲んだ文字列。
    表示用の記号や色はここには含まれない（表示層で変換する）。

    match_counts は対象ごとの一致箇所数（"title" / "modern" / "original"）。
    matched_fields はそのうち1箇所以上一致した対象の一覧で、
    ("original",) だけなら「口語化で言い換えられて消えた語」に当たったことを意味する。
    """

    id: str
    dir: Path
    title: str
    snippet: str
    created_at: str
    matched_fields: tuple[str, ...] = ()
    match_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class ParsedQuery:
    """解析済みの検索クエリ

    terms は (対象カラム名 or None, 正規化済みの語) の並び。
    join は terms の結合方法（"AND" または "OR"）。
    excludes は正規化済みの除外語で、互いに OR で束ねてから NOT を当てる。
    """

    terms: list[tuple[str | None, str]]
    join: str
    excludes: list[str]


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


class QuerySyntaxError(LibrarySearchError):
    """検索クエリの組み立てが成立しない

    除外語だけ・NOT の重複・未知の対象名など、語の長さ以外の理由で
    検索式を作れない場合に投げる。
    """

    pass


# ---------- クエリ解析 ----------


def parse_query(query: str) -> ParsedQuery:
    """検索クエリ文字列を解析する。

    構文（利用者に見せるのはこれだけ）:
        語 語          … すべてを含む（AND。従来どおり）
        語 OR 語       … いずれかを含む（OR が1つでもあれば語群全体が OR）
        語 NOT 語 語   … NOT 以降を除外（除外語は互いに OR）
        原文:語        … 一致対象を限定（区切りは半角 : / 全角 ：）

    OR を「モード切替」として扱い、AND と OR の混在を許さないのは、
    FTS5 の優先順位（NOT > AND > OR）が利用者の直感と逆で、
    混在を許すと説明できない挙動を抱え込むため（design.md Decision 2）。

    Raises:
        QueryTooShortError: 正規化後に最小文字数を割る語がある／語が1つも無い
        QuerySyntaxError:   除外語のみ／NOT が2回以上／未知の対象名
    """
    tokens = [t for t in query.replace("　", " ").split(" ") if t]

    raw_terms: list[tuple[str | None, str]] = []  # (対象カラム, 生の語)
    raw_excludes: list[str] = []
    join = "AND"
    in_exclude = False

    for token in tokens:
        if token == _OP_NOT:
            if in_exclude:
                raise QuerySyntaxError(
                    f"{_OP_NOT} は1回だけ指定できます（2回以上は解釈できません）"
                )
            in_exclude = True
            continue
        if token == _OP_OR:
            # 語群の中の OR だけがモードを切り替える。除外語は元から互いに OR。
            if not in_exclude:
                join = "OR"
            continue

        field_name, term = _split_field(token)
        if in_exclude:
            if field_name is not None:
                raise QuerySyntaxError(
                    f"除外語に対象の限定は指定できません: {token}"
                )
            raw_excludes.append(term)
        else:
            raw_terms.append((field_name, term))

    if not raw_terms:
        if raw_excludes:
            raise QuerySyntaxError(
                "除外語だけでは検索できません（残す語も指定してください）"
            )
        raise QueryTooShortError("検索語が空です")

    terms = [
        (f, _normalize_checked(t, _ROLE_FIELD if f else _ROLE_TERM))
        for f, t in raw_terms
    ]
    excludes = [_normalize_checked(t, _ROLE_EXCLUDE) for t in raw_excludes]
    return ParsedQuery(terms=terms, join=join, excludes=excludes)


def _split_field(token: str) -> tuple[str | None, str]:
    """`原文:罹災者` を ("original", "罹災者") に分解する。

    コロンの左が別名表にある場合だけ限定として扱う。そうしないと
    `午前10:30` のような本文由来のコロンが限定指定に誤解される。

    ただし左が ASCII 英字だけの語（`body:`、`orig:` 等）は、日本語の資料本文に
    現れる見込みが無く「対象名の書き間違い」とみなせるため、黙って検索語に
    落とさずエラーにする。
    """
    for sep in _FIELD_SEPARATORS:
        head, found, tail = token.partition(sep)
        if not found:
            continue
        alias = FIELD_ALIASES.get(head) or FIELD_ALIASES.get(head.lower())
        if alias is not None:
            return alias, tail
        if head.isascii() and head.isalpha():
            raise QuerySyntaxError(
                f'"{head}" は検索対象の名前ではありません。'
                f"使えるのは: {'、'.join(sorted(set(FIELD_ALIASES)))}"
            )
    return None, token


def _normalize_checked(term: str, role: str) -> str:
    """語を照合用に正規化し、trigram で扱える長さかを検査する。

    長さの判定を正規化の「後」に行うのは、歴史的仮名遣いの変換や拗音の縮約で
    字数が縮むため（「けふ」→「きょう」のように増える場合も減る場合もある）。
    """
    normalized = normalize_query(term)
    if len(normalized) < TRIGRAM_MIN_QUERY_CHARS:
        shown = f'"{normalized}"' if normalized else "（空）"
        suffix = f"（{role}「{term}」の正規化後）" if normalized != term else f"（{role}）"
        raise QueryTooShortError(
            f"{shown} は{TRIGRAM_MIN_QUERY_CHARS}文字未満のため "
            f"trigram で検索できません{suffix}"
        )
    return normalized


def build_match_expr(parsed: ParsedQuery) -> str:
    """解析済みクエリを FTS5 の MATCH 式へ組み立てる。

    語群を丸ごと括弧で包んでから NOT を当てることで、FTS5 の優先順位
    （NOT > AND > OR）が結果に現れないようにする。

        ("A" AND "B") NOT ("C" OR "D")
        (({original} : "A") AND "B")

    カラム限定した語を括弧で包むのは、FTS5 の `{col} : expr` が
    直後の1句にしか掛からないことを式の見た目からも明らかにするため。
    """
    parts = [
        f"({{{field_name}}} : {_quote(term)})" if field_name else _quote(term)
        for field_name, term in parsed.terms
    ]
    expr = f"({f' {parsed.join} '.join(parts)})"
    if parsed.excludes:
        excluded = " OR ".join(_quote(t) for t in parsed.excludes)
        expr = f"{expr} NOT ({excluded})"
    return expr


def _quote(term: str) -> str:
    """FTS5 の文字列リテラルにする（内部のダブルクォートは "" にエスケープ）"""
    return '"' + term.replace('"', '""') + '"'


# ---------- 抜粋マーカの解析 ----------


def split_marked(marked: str) -> tuple[str, list[tuple[int, int]]]:
    """マーカ付き抜粋を「素の本文」と「一致箇所の [開始, 終了) 位置」に分ける。

    位置は素の本文における文字インデックス。表示用の記号を本文に混ぜないため、
    text 出力（ANSI色）と JSON 出力（構造化）はどちらもここを通す。

    対にならない孤立マーカは強調として扱わず、マーカ文字ごと落とす。
    索引した本文が万一 STX/ETX を含んでいても表示が壊れないようにするため
    （索引側でのサニタイズは索引の作り直しを伴うので行わない）。
    """
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    open_at: int | None = None

    for ch in marked:
        if ch == MARK_OPEN:
            if open_at is None:
                open_at = len(plain)
            # 既に開いている最中の開始マーカは孤立とみなして捨てる
        elif ch == MARK_CLOSE:
            if open_at is not None:
                spans.append((open_at, len(plain)))
                open_at = None
            # 対応する開始が無い終了マーカも捨てる
        else:
            plain.append(ch)

    # 閉じられなかった開始マーカは強調にしない
    return "".join(plain), spans


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

    def search(
        self,
        query: str,
        limit: int = 20,
        snippet_chars: int | None = None,
    ) -> list[SearchHit]:
        """全文検索

        クエリ構文は parse_query() を参照（AND / OR / NOT / 対象の限定）。
        各語は trigram で部分一致し、正規化後に3文字未満だと QueryTooShortError。

        snippet_chars は抜粋の長さ。None なら設定の既定値を使い、
        SNIPPET_MAX_CHARS を超える指定は上限に丸める。

        Raises:
            ValueError: snippet_chars が零以下
        """
        match_expr = build_match_expr(parse_query(query))
        length = self._resolve_snippet_chars(snippet_chars)

        self._ensure_ready()
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            # snippet の第2引数 -1 は「最もよく一致したカラムから抜粋する」指定。
            # 原文にのみ残る語で当たったときに、その箇所が抜粋に出る。
            #
            # 一致箇所数は highlight() が入れたマーカを SQL 内で数える。
            # highlight() はカラム全文を返すので Python 側へ運ぶと
            # 20件 × 3カラム分の本文が転送される。SQL で数えれば整数3つで済む。
            # マーカは char() 式で埋め込み、パラメータの数を増やさない。
            open_sql = f"char({ord(MARK_OPEN)})"
            close_sql = f"char({ord(MARK_CLOSE)})"
            counts = ", ".join(
                f"length(highlight(search, {num}, {open_sql}, {close_sql}))"
                f" - length(replace(highlight(search, {num}, {open_sql}, {close_sql}),"
                f" {open_sql}, ''))"
                for num, _ in _FTS_FIELDS
            )

            cur = conn.execute(
                f"""
                SELECT s.id,
                       snippet(search, -1, {open_sql}, {close_sql}, ?, ?) AS sn,
                       d.dir,
                       d.title,
                       d.created_at,
                       {counts}
                  FROM search s JOIN documents d ON s.id = d.id
                 WHERE search MATCH ?
                 ORDER BY bm25(search)
                 LIMIT ?
                """,
                (_SNIPPET_ELLIPSIS, length, match_expr, limit),
            )
            return [self._row_to_hit(row) for row in cur]
        finally:
            conn.close()

    @staticmethod
    def _resolve_snippet_chars(snippet_chars: int | None) -> int:
        """抜粋長を決める（既定値の補完と上限の丸め）"""
        length = (
            CONFIG.get("search.snippet_chars", 40)
            if snippet_chars is None
            else snippet_chars
        )
        if length <= 0:
            raise ValueError(f"抜粋の長さは1以上で指定してください: {length}")
        return min(length, SNIPPET_MAX_CHARS)

    @staticmethod
    def _row_to_hit(row: tuple) -> SearchHit:
        """検索結果の1行を SearchHit にする（一致回数から matched_fields を導く）"""
        match_counts = {
            name: row[5 + i] for i, (_, name) in enumerate(_FTS_FIELDS)
        }
        return SearchHit(
            id=row[0],
            dir=Path(row[2]),
            title=row[3],
            snippet=row[1],
            created_at=row[4],
            matched_fields=tuple(
                name for _, name in _FTS_FIELDS if match_counts[name] > 0
            ),
            match_counts=match_counts,
        )

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

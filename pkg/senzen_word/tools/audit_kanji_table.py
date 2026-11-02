"""旧字体変換表の監査スクリプト

開発用ツール。パッケージ本体（src/）には含めない。

OCR エンジンが出しうる字のうち「旧字の候補なのに、変換表にも
『変換しない字』の一覧（tools/kanji_keep.json）にも無い字」を洗い出す。
変換表そのものは人が1字ずつ判断して作り、このスクリプトは判断の漏れを
見つけるだけ（Unihan から自動生成すると誤りが混ざるため）。

候補の定義:
    --charset で渡したファイルに含まれる字のうち、
      - CJK 統合漢字で、
      - 常用漢字（kJoyoKanji）でも人名用漢字（kJinmeiyoKanji）でもなく、
      - NFKC で変わらず（互換漢字は前段の NFKC が処理する）、
      - Unihan の異体字5項目を双方向に辿ると常用・人名用漢字に結び付く
    字。

    未判断 = 候補 − 変換表のキー − kanji_keep.json のキー

注意:
    Unihan は主に中国語の簡体字・繁体字の関係を記録したデータで、日本の
    新字体・旧字体の対応とは一致しない。「尙」「產」のように Unihan が
    常用漢字と結び付けない旧字は、この監査では見つからない（網であって
    完全ではない）。

使い方（リポジトリ直下で）:
    uv run python pkg/senzen_word/tools/audit_kanji_table.py \\
        --charset vendor/ndlocr-lite/src/config/NDLmoji.yaml

    --unihan を省略すると、Unicode 公式サイトから Unihan.zip（版は固定）を
    取得して tools/.cache/ に保存し、次回から再利用する。取得するのは
    公開データだけで、資料は一切送らない。

終了コード:
    0: 未判断の字が無い
    1: 未判断の字がある
    2: 入力ファイルの不備
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from senzen_word.kanji import get_kanji_table


# 再現性のため版を固定する（latest を使うと結果が黙って変わる）
UNIHAN_VERSION = "18.0.0"
UNIHAN_URL = f"https://www.unicode.org/Public/{UNIHAN_VERSION}/ucd/Unihan.zip"

TOOLS_DIR = Path(__file__).resolve().parent
CACHE_DIR = TOOLS_DIR / ".cache"
KEEP_PATH = TOOLS_DIR / "kanji_keep.json"

# 双方向に辿る異体字の項目
VARIANT_FIELDS = (
    "kZVariant",
    "kSemanticVariant",
    "kSpecializedSemanticVariant",
    "kSimplifiedVariant",
    "kTraditionalVariant",
)


class AuditInputError(Exception):
    """監査の入力（文字集合・Unihan・判断一覧）の不備"""


@dataclass
class Unihan:
    """監査に使う Unihan の部分"""

    modern: set[str]  # 常用漢字・人名用漢字
    links: dict[str, set[str]]  # 異体字の結び付き（双方向）
    simplified: set[str]  # 簡体字（kTraditionalVariant を持つ字）


@dataclass
class Finding:
    """未判断の字1つ"""

    char: str
    modern_links: list[str]
    maybe_simplified: bool


# ---------- 入力の読み込み ----------


def _codepoint_to_char(token: str) -> str:
    """'U+5167' や 'U+5167<kMatthews' を文字に変換する"""
    return chr(int(token[2:].split("<")[0], 16))


def _unihan_zip_path(explicit: Path | None) -> Path:
    """Unihan.zip の場所を決める（無ければ取得してキャッシュする）"""
    if explicit is not None:
        if not explicit.is_file():
            raise AuditInputError(f"Unihan.zip が見つかりません: {explicit}")
        return explicit

    cached = CACHE_DIR / f"Unihan-{UNIHAN_VERSION}.zip"
    if not cached.is_file():
        print(f"Unihan {UNIHAN_VERSION} を取得します: {UNIHAN_URL}", file=sys.stderr)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(UNIHAN_URL, timeout=60) as response:
            cached.write_bytes(response.read())
    return cached


def load_unihan(zip_path: Path) -> Unihan:
    """Unihan.zip から常用・人名用漢字と異体字の結び付きを読む"""
    modern: set[str] = set()
    links: dict[str, set[str]] = defaultdict(set)
    simplified: set[str] = set()

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise AuditInputError(f"Unihan.zip を開けません: {zip_path}") from e

    with archive:
        for member in ("Unihan_OtherMappings.txt", "Unihan_Variants.txt"):
            try:
                raw = archive.read(member)
            except KeyError as e:
                raise AuditInputError(f"Unihan.zip に {member} がありません") from e
            for line in io.StringIO(raw.decode("utf-8")):
                if line.startswith("#") or not line.strip():
                    continue
                code, field, value = line.rstrip("\n").split("\t")
                char = _codepoint_to_char(code)
                if field in ("kJoyoKanji", "kJinmeiyoKanji"):
                    modern.add(char)
                elif field in VARIANT_FIELDS:
                    if field == "kTraditionalVariant":
                        simplified.add(char)
                    for token in value.split():
                        other = _codepoint_to_char(token)
                        if other != char:
                            links[char].add(other)
                            links[other].add(char)

    if not modern:
        raise AuditInputError("Unihan から常用・人名用漢字を読み取れませんでした")
    return Unihan(modern=modern, links=dict(links), simplified=simplified)


def load_charset(path: Path) -> set[str]:
    """文字集合のファイルを読み、含まれる全文字の集合を返す"""
    if not path.is_file():
        raise AuditInputError(f"文字集合のファイルが見つかりません: {path}")
    return set(path.read_text(encoding="utf-8"))


def load_keep(path: Path = KEEP_PATH) -> dict[str, dict[str, str]]:
    """「変換しない字」の一覧を読む（無ければ空）"""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- 監査 ----------


def find_candidates(charset: set[str], unihan: Unihan) -> dict[str, list[str]]:
    """旧字の候補と、結び付く常用・人名用漢字を返す"""
    candidates: dict[str, list[str]] = {}
    for char in charset:
        if not unicodedata.name(char, "").startswith("CJK UNIFIED IDEOGRAPH"):
            continue
        if char in unihan.modern:
            continue
        if unicodedata.normalize("NFKC", char) != char:
            continue
        linked = sorted(t for t in unihan.links.get(char, ()) if t in unihan.modern)
        if linked:
            candidates[char] = linked
    return candidates


def audit(
    charset: set[str],
    unihan: Unihan,
    table: dict[str, str],
    keep: dict[str, dict[str, str]],
) -> list[Finding]:
    """未判断の字をコードポイント順に返す"""
    candidates = find_candidates(charset, unihan)
    findings = [
        Finding(
            char=char,
            modern_links=linked,
            maybe_simplified=char in unihan.simplified,
        )
        for char, linked in candidates.items()
        if char not in table and char not in keep
    ]
    return sorted(findings, key=lambda f: f.char)


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="旧字体変換表の判断漏れ（変換表にも変換しない一覧にも無い旧字の候補）を洗い出す"
    )
    parser.add_argument(
        "--charset",
        type=Path,
        required=True,
        help="OCR の出力文字集合を含むファイル（例: vendor/ndlocr-lite/src/config/NDLmoji.yaml）",
    )
    parser.add_argument(
        "--unihan",
        type=Path,
        default=None,
        help=f"Unihan.zip のパス（省略時は Unicode {UNIHAN_VERSION} を取得して tools/.cache/ に保存）",
    )
    args = parser.parse_args(argv)

    try:
        charset = load_charset(args.charset)
        unihan = load_unihan(_unihan_zip_path(args.unihan))
        keep = load_keep()
    except AuditInputError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    table = get_kanji_table()
    findings = audit(charset, unihan, table, keep)

    for f in findings:
        hint = "  ※簡体字の可能性" if f.maybe_simplified else ""
        print(f"{f.char}  U+{ord(f.char):04X}  → {''.join(f.modern_links)}{hint}")

    candidates = len(find_candidates(charset, unihan))
    print(
        f"\n候補 {candidates} 字 / 変換表 {len(table)} 字 / 変換しない字 {len(keep)} 字"
        f" / 未判断 {len(findings)} 字"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

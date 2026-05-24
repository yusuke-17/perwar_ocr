"""
ライブラリ保管モジュール

1回のOCR処理結果を「1件の記録」として library/ 配下のフォルダに書き出す。
フォルダには元画像（コピー）・OCR生テキスト・現代語テキスト・メタ情報を保存し、
後から検索・再実行・修正できる蓄積基盤を構成する。

使い方:
    from utils.library_writer import (
        DocumentRecord, MetaOcr, MetaNormalization, MetaModernize, save_document,
    )

    record = DocumentRecord(
        source_paths=[Path("input/3.png")],
        ocr_raw="...",
        modern_text="...",
        ocr_meta=MetaOcr(model="glm-ocr", prompt="...", elapsed_seconds=12.3),
        normalization=MetaNormalization(True, True, True),
        modernize=MetaModernize(enabled=True, model="qwen3.5:9b"),
    )
    doc_dir = save_document(record)
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------- 定数 ----------

LIBRARY_ROOT = Path("library")
SCHEMA_VERSION = 1

_TZ_JST = ZoneInfo("Asia/Tokyo")
_INVALID_SLUG_CHARS = ("/", "\\", " ", "\0", "\n", "\r", "\t")


# ---------- データクラス ----------


@dataclass
class MetaOcr:
    """meta.json の ocr セクション"""

    model: str
    prompt: str
    elapsed_seconds: float


@dataclass
class MetaNormalization:
    """meta.json の normalization セクション

    現状 normalize_text() は3項目を固定で実行するため、
    呼び出し有無に応じて3項目とも同じ値（true/false）を入れる。
    将来 normalize_text を引数化したら個別に true/false を区別できるようにする。
    """

    old_kanji: bool
    historical_kana: bool
    ocr_misread_correction: bool


@dataclass
class MetaModernize:
    """meta.json の modernize セクション"""

    enabled: bool
    model: str


@dataclass
class DocumentRecord:
    """1件の処理結果を集約するレコード（save_document への入力）"""

    source_paths: list[Path]
    ocr_raw: str
    modern_text: str
    ocr_meta: MetaOcr
    normalization: MetaNormalization
    modernize: MetaModernize
    tags: list[str] = field(default_factory=list)
    note: str = ""


# ---------- ヘルパー関数 ----------


def slugify_from_image(image_path: Path) -> str:
    """画像パスから slug を生成する

    image_path.stem をそのまま採用し、不正文字のみ '-' に置換する。
    日本語ファイル名はそのまま残す（可搬性より人間可読性を優先）。
    """
    slug = image_path.stem
    for ch in _INVALID_SLUG_CHARS:
        slug = slug.replace(ch, "-")
    slug = slug.strip("-")
    return slug or "untitled"


def extract_title(ocr_raw: str, max_chars: int = 40) -> str:
    """OCR生テキストの先頭非空行をタイトルとして抽出する

    - 改行・前後空白を trim
    - max_chars を超えたら切り詰める
    - 全行が空なら空文字を返す
    """
    for line in ocr_raw.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:max_chars]
    return ""


def resolve_unique_dir(root: Path, base_id: str) -> Path:
    """命名衝突時に -2, -3 ... を末尾に付けてユニークなパスを返す"""
    candidate = root / base_id
    if not candidate.exists():
        return candidate

    n = 2
    while True:
        candidate = root / f"{base_id}-{n}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------- メイン保存関数 ----------


def save_document(
    record: DocumentRecord, library_root: Path = LIBRARY_ROOT
) -> Path:
    """DocumentRecord をライブラリフォルダに書き出す

    生成されるフォルダ構成:
        library/{YYYY-MM-DD}_{slug}/
            source.png            (1枚なら) または source_01.png, source_02.png ... (複数枚)
            ocr_raw.txt
            modern.txt
            meta.json

    Args:
        record: 保存するレコード
        library_root: ライブラリのルートディレクトリ（デフォルト: library/）

    Returns:
        作成された文書フォルダのパス
    """
    if not record.source_paths:
        raise ValueError("source_paths が空です")

    created_at = datetime.now(_TZ_JST)
    date_part = created_at.strftime("%Y-%m-%d")
    slug = slugify_from_image(record.source_paths[0])
    base_id = f"{date_part}_{slug}"

    doc_dir = resolve_unique_dir(library_root, base_id)
    doc_dir.mkdir(parents=True)

    # 元画像をコピー（実体コピー）
    source_names = _copy_sources(record.source_paths, doc_dir)

    # ocr_raw.txt
    (doc_dir / "ocr_raw.txt").write_text(record.ocr_raw, encoding="utf-8", newline="\n")

    # modern.txt
    (doc_dir / "modern.txt").write_text(
        record.modern_text, encoding="utf-8", newline="\n"
    )

    # meta.json
    meta = {
        "schema_version": SCHEMA_VERSION,
        "id": doc_dir.name,
        "created_at": created_at.isoformat(timespec="seconds"),
        "title": extract_title(record.ocr_raw),
        "sources": source_names,
        "ocr": {
            "model": record.ocr_meta.model,
            "prompt": record.ocr_meta.prompt,
            "elapsed_seconds": round(record.ocr_meta.elapsed_seconds, 2),
        },
        "normalization": {
            "old_kanji": record.normalization.old_kanji,
            "historical_kana": record.normalization.historical_kana,
            "ocr_misread_correction": record.normalization.ocr_misread_correction,
        },
        "modernize": {
            "enabled": record.modernize.enabled,
            "model": record.modernize.model,
        },
        "tags": list(record.tags),
        "note": record.note,
    }
    meta_json = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
    (doc_dir / "meta.json").write_text(meta_json, encoding="utf-8", newline="\n")

    return doc_dir


def _copy_sources(source_paths: list[Path], doc_dir: Path) -> list[str]:
    """元画像を doc_dir にコピーし、コピー先のファイル名リストを返す

    1枚: source{元拡張子}
    複数枚: source_01{元拡張子}, source_02{元拡張子}, ...
    """
    if len(source_paths) == 1:
        src = source_paths[0]
        dest_name = f"source{src.suffix}"
        shutil.copy2(src, doc_dir / dest_name)
        return [dest_name]

    names: list[str] = []
    for i, src in enumerate(source_paths, start=1):
        dest_name = f"source_{i:02d}{src.suffix}"
        shutil.copy2(src, doc_dir / dest_name)
        names.append(dest_name)
    return names

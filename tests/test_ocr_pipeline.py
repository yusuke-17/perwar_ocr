"""OCRパイプライン全体の特性テスト（E1）

1枚処理・複数枚処理・フォルダ処理が「何を保存し、どの終了コードを返すか」を固定する。
G7 のリファクタ（1枚処理を複数枚処理へ一本化）の前に書き、リファクタ後も
**無修正で**通ることで「挙動を壊していない」ことを確かめる安全網。

Ollama には接続しない。OCRクライアントと口語化器は手書きのフェイクを
処理の入口のキーワード引数で差し替える（unittest.mock は使わない）。
仕様: openspec/changes/unify-ocr-pipeline/specs/ocr-pipeline/spec.md
"""

import json
from pathlib import Path

from scripts import ocr_vision_llm
from scripts.cli import _defaults_for
from scripts.ocr_vision_llm import process_batch, process_folder, process_single
from utils.library_writer import SCHEMA_VERSION
from utils.ollama_client import ImageFileError, OllamaConnectionError
from utils.text_normalizer import normalize_text

from fakes import MODERN_MARK, EchoModernizer, FakeClient, StubModernizer

# 旧字体（關・狀）とカタカナ助詞（ノ）を含む、戦前公文書らしい1行
OLD_TEXT = "關東地方ノ狀況"


# ---------- 共通ヘルパー ----------


def _args(tmp_path: Path, **overrides):
    """本番と同じ既定値で埋めた引数に、テスト用の出力先を上書きして返す

    _defaults_for を使うので、処理が参照する引数の取りこぼしもここで検出される。
    前処理は既存テスト（test_ocr_batch）で担保済みのため切る。
    """
    args = _defaults_for(ocr_vision_llm.add_arguments)
    args.no_preprocess = True
    args.library_root = str(tmp_path / "library")
    args.output = str(tmp_path / "output")
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _images(folder: Path, n: int) -> list[Path]:
    """p001.png … を n 枚作る

    中身は自分のファイル名のバイト列。フェイククライアントは中身を読まないので
    画像である必要はなく、保存後に「どの元画像がコピーされたか」を判別できる。
    """
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        p = folder / f"p{i:03d}.png"
        p.write_bytes(p.name.encode())
        paths.append(p)
    return paths


def _docs(tmp_path: Path) -> list[Path]:
    """ライブラリに作られた記録フォルダを名前順で返す"""
    root = tmp_path / "library"
    if not root.exists():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir())


def _only_doc(tmp_path: Path) -> Path:
    docs = _docs(tmp_path)
    assert len(docs) == 1, docs
    return docs[0]


def _meta(doc: Path) -> dict:
    return json.loads((doc / "meta.json").read_text(encoding="utf-8"))


def _read(doc: Path, name: str) -> str:
    return (doc / name).read_text(encoding="utf-8")


# ---------- 1枚処理 ----------


def test_single_success_saves_one_record(tmp_path):
    """1枚成功: 終了コード0、4ファイルが揃い、pages セクションは無い"""
    [image] = _images(tmp_path / "input", 1)

    code = process_single(
        _args(tmp_path), image, client=FakeClient(), modernizer=EchoModernizer()
    )

    assert code == 0
    doc = _only_doc(tmp_path)
    assert sorted(p.name for p in doc.iterdir()) == [
        "meta.json",
        "modern.txt",
        "ocr_raw.txt",
        "source.png",
    ]
    assert (doc / "source.png").read_bytes() == b"p001.png"
    assert _read(doc, "ocr_raw.txt") == "ページ1の本文"
    assert _read(doc, "modern.txt").startswith(MODERN_MARK)
    assert "pages" not in _meta(doc)


def test_single_ocr_failure_saves_nothing(tmp_path):
    """1枚のOCR失敗: 終了コード1、記録は作られない"""
    [image] = _images(tmp_path / "input", 1)
    client = FakeClient({1: OllamaConnectionError("停止中")})

    code = process_single(
        _args(tmp_path), image, client=client, modernizer=EchoModernizer()
    )

    assert code == 1
    assert _docs(tmp_path) == []


def test_single_no_save_writes_nothing(tmp_path):
    """保存省略: ライブラリにも旧形式の出力先にも何も作らない"""
    [image] = _images(tmp_path / "input", 1)
    args = _args(tmp_path, no_save=True, legacy_output=True)

    code = process_single(
        args, image, client=FakeClient(), modernizer=EchoModernizer()
    )

    assert code == 0
    assert not (tmp_path / "library").exists()
    assert not (tmp_path / "output").exists()


def test_single_normalizes_old_kanji(tmp_path):
    """正規化あり: 旧字体が新字体になった本文が口語化へ渡る"""
    [image] = _images(tmp_path / "input", 1)

    process_single(
        _args(tmp_path),
        image,
        client=FakeClient(texts=[OLD_TEXT]),
        modernizer=EchoModernizer(),
    )

    doc = _only_doc(tmp_path)
    modern = _read(doc, "modern.txt")
    assert "関東" in modern and "状況" in modern
    assert "關東" not in modern
    assert _read(doc, "ocr_raw.txt") == OLD_TEXT  # 生テキストは手を加えず残す
    assert all(_meta(doc)["normalization"].values())


def test_single_no_normalize_keeps_old_kanji(tmp_path):
    """正規化省略: 旧字体のまま口語化へ渡り、メタの正規化項目は全て無効"""
    [image] = _images(tmp_path / "input", 1)

    process_single(
        _args(tmp_path, no_normalize=True),
        image,
        client=FakeClient(texts=[OLD_TEXT]),
        modernizer=EchoModernizer(),
    )

    doc = _only_doc(tmp_path)
    assert _read(doc, "modern.txt") == f"{MODERN_MARK}{OLD_TEXT}"
    assert not any(_meta(doc)["normalization"].values())


def test_single_no_modernize_saves_normalized_text(tmp_path):
    """口語化省略: 終了コード0、正規化テキストを保存、メタは口語化無効"""
    [image] = _images(tmp_path / "input", 1)
    modernizer = EchoModernizer()

    code = process_single(
        _args(tmp_path, no_modernize=True),
        image,
        client=FakeClient(texts=[OLD_TEXT]),
        modernizer=modernizer,
    )

    assert code == 0
    assert modernizer.calls == 0
    doc = _only_doc(tmp_path)
    assert _read(doc, "modern.txt") == normalize_text(OLD_TEXT)
    assert _meta(doc)["modernize"] == {"enabled": False, "model": ""}


def test_single_modernize_failure_keeps_normalized_text(tmp_path):
    """口語化が丸ごと失敗: 終了コード2、正規化テキストを保存、理由がメタに残る"""
    [image] = _images(tmp_path / "input", 1)

    code = process_single(
        _args(tmp_path),
        image,
        client=FakeClient(texts=[OLD_TEXT]),
        modernizer=StubModernizer(error=OllamaConnectionError("LLM停止中")),
    )

    assert code == 2
    doc = _only_doc(tmp_path)
    assert _read(doc, "modern.txt") == normalize_text(OLD_TEXT)
    assert "LLM停止中" in _meta(doc)["modernize"]["error"]


def test_single_legacy_output(tmp_path):
    """旧形式出力: output/{元画像名}_modern.txt"""
    [image] = _images(tmp_path / "input", 1)

    process_single(
        _args(tmp_path, legacy_output=True),
        image,
        client=FakeClient(),
        modernizer=EchoModernizer(),
    )

    legacy = tmp_path / "output" / "p001_modern.txt"
    assert legacy.read_text(encoding="utf-8") == _read(_only_doc(tmp_path), "modern.txt")


def test_single_meta_is_stable(tmp_path):
    """1枚処理が作るメタ情報（時刻・IDを除く）を固定する

    リファクタ前後で同じ入力から同じ meta.json が作られることの基準。
    """
    [image] = _images(tmp_path / "input", 1)

    process_single(
        _args(tmp_path),
        image,
        client=FakeClient(texts=[OLD_TEXT]),
        modernizer=EchoModernizer(),
    )

    meta = _meta(_only_doc(tmp_path))
    meta.pop("created_at")
    meta.pop("id")
    assert meta == {
        "schema_version": SCHEMA_VERSION,
        "title": OLD_TEXT,
        "sources": ["source.png"],
        "ocr": {
            "model": "fake-ocr",
            "prompt": "テスト用",
            "elapsed_seconds": 0.1,
            "options": {},
        },
        "normalization": {
            "old_kanji": True,
            "hentaigana": True,
            "historical_kana": True,
            "ocr_misread_correction": True,
        },
        "modernize": {"enabled": True, "model": "fake-llm"},
        "tags": [],
        "note": "",
    }


# ---------- 複数枚処理 ----------


def test_batch_all_success(tmp_path):
    """3枚成功: 終了コード0、連番の元画像、OCR所要時間は合計"""
    images = _images(tmp_path / "input", 3)

    code = process_batch(
        _args(tmp_path), images, client=FakeClient(), modernizer=EchoModernizer()
    )

    assert code == 0
    doc = _only_doc(tmp_path)
    meta = _meta(doc)
    assert meta["sources"] == ["source_01.png", "source_02.png", "source_03.png"]
    assert meta["ocr"]["elapsed_seconds"] == 0.3
    assert "pages" not in meta
    assert _read(doc, "ocr_raw.txt") == (
        "ページ1の本文\n\nページ2の本文\n\nページ3の本文"
    )


def test_batch_middle_failure_saves_rest_in_order(tmp_path):
    """2枚目だけ失敗: 終了コード2、成功2枚が元の順で連番保存、内訳がメタに残る"""
    images = _images(tmp_path / "input", 3)
    client = FakeClient({2: ImageFileError("画像が壊れています")})

    code = process_batch(
        _args(tmp_path), images, client=client, modernizer=EchoModernizer()
    )

    assert code == 2
    doc = _only_doc(tmp_path)
    assert (doc / "source_01.png").read_bytes() == b"p001.png"
    assert (doc / "source_02.png").read_bytes() == b"p003.png"
    assert not (doc / "source_03.png").exists()
    assert _read(doc, "ocr_raw.txt") == "ページ1の本文\n\nページ3の本文"

    pages = _meta(doc)["pages"]
    assert pages["total"] == 3
    assert pages["succeeded"] == 2
    assert [(s["index"], s["source"], s["reason"]) for s in pages["skipped"]] == [
        (2, "p002.png", "image")
    ]


def test_batch_all_failure_saves_nothing(tmp_path):
    """全ページ失敗: 終了コード1、記録は作られない"""
    images = _images(tmp_path / "input", 2)
    client = FakeClient(
        {1: OllamaConnectionError("停止中"), 2: OllamaConnectionError("停止中")}
    )

    code = process_batch(
        _args(tmp_path), images, client=client, modernizer=EchoModernizer()
    )

    assert code == 1
    assert _docs(tmp_path) == []


def test_batch_legacy_output(tmp_path):
    """旧形式出力: output/{先頭}-{末尾}_modern.txt"""
    images = _images(tmp_path / "input", 3)

    process_batch(
        _args(tmp_path, legacy_output=True),
        images,
        client=FakeClient(),
        modernizer=EchoModernizer(),
    )

    assert (tmp_path / "output" / "p001-p003_modern.txt").exists()


# ---------- フォルダ処理 ----------


def test_folder_without_images(tmp_path):
    """画像の無いフォルダ: 終了コード1"""
    folder = tmp_path / "session"
    folder.mkdir()
    (folder / "memo.txt").write_text("画像ではない", encoding="utf-8")

    code = process_folder(
        _args(tmp_path), folder, client=FakeClient(), modernizer=EchoModernizer()
    )

    assert code == 1
    assert _docs(tmp_path) == []


def test_folder_default_combines_into_one_record(tmp_path):
    """既定: フォルダ内の全画像をファイル名順に結合して1記録"""
    folder = tmp_path / "session"
    _images(folder, 3)

    code = process_folder(
        _args(tmp_path), folder, client=FakeClient(), modernizer=EchoModernizer()
    )

    assert code == 0
    doc = _only_doc(tmp_path)
    assert len(_meta(doc)["sources"]) == 3
    assert (doc / "source_01.png").read_bytes() == b"p001.png"


def test_folder_separate_all_success(tmp_path):
    """画像ごとの別記録: 全成功なら終了コード0、記録が画像の数だけできる"""
    folder = tmp_path / "session"
    _images(folder, 3)

    code = process_folder(
        _args(tmp_path, separate=True),
        folder,
        client=FakeClient(),
        modernizer=EchoModernizer(),
    )

    assert code == 0
    assert len(_docs(tmp_path)) == 3


def test_folder_separate_partial_failure(tmp_path, capsys):
    """画像ごとの別記録で1枚失敗: 終了コード2、成功分は別記録、失敗画像名を表示"""
    folder = tmp_path / "session"
    _images(folder, 3)
    client = FakeClient({2: OllamaConnectionError("停止中")})

    code = process_folder(
        _args(tmp_path, separate=True),
        folder,
        client=client,
        modernizer=EchoModernizer(),
    )

    assert code == 2
    docs = _docs(tmp_path)
    assert len(docs) == 2
    assert [(d / "source.png").read_bytes() for d in docs] == [
        b"p001.png",
        b"p003.png",
    ]
    out = capsys.readouterr().out
    assert "保存できませんでした" in out
    assert "- p002.png" in out


def test_folder_separate_all_failure(tmp_path):
    """画像ごとの別記録ですべて失敗: 終了コード1"""
    folder = tmp_path / "session"
    _images(folder, 2)
    client = FakeClient(
        {1: OllamaConnectionError("停止中"), 2: OllamaConnectionError("停止中")}
    )

    code = process_folder(
        _args(tmp_path, separate=True),
        folder,
        client=client,
        modernizer=EchoModernizer(),
    )

    assert code == 1
    assert _docs(tmp_path) == []

"""OCRパイプライン全体の特性テスト（E1）

1枚処理・複数枚処理・フォルダ処理が「何を保存し、どの終了コードを返すか」を固定する。
G7 のリファクタ（1枚処理を複数枚処理へ一本化）の前に書き、リファクタ後も
**無修正で**通ることで「挙動を壊していない」ことを確かめる安全網。

Ollama には接続しない。OCRクライアントと口語化器は手書きのフェイクを
処理の入口のキーワード引数で差し替える（unittest.mock は使わない）。
仕様: openspec/specs/ocr-pipeline/spec.md
"""

import json
import os
from pathlib import Path

import pytest

from scripts import ocr_vision_llm
from scripts.cli import _defaults_for
from scripts.ocr_vision_llm import (
    BatchOcrOutcome,
    _build_record,
    _exit_code,
    process_batch,
    process_folder,
    process_single,
)
from utils.library_writer import SCHEMA_VERSION, MetaModernize, MetaPageFailure
from utils.ollama_client import ImageFileError, OCRResult, OllamaConnectionError
from utils.text_normalizer import normalize_text

from fakes import (
    MODERN_MARK,
    EchoModernizer,
    FakeClient,
    NameEchoClient,
    StubModernizer,
)

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


# ---------- 一本化（G7）で意図して変えた表示 ----------


def test_single_does_not_show_batch_heading(tmp_path, capsys):
    """1枚処理では「処理モード: 複数画像」「結合OCR結果」の見出しを出さない"""
    [image] = _images(tmp_path / "input", 1)

    process_single(
        _args(tmp_path), image, client=FakeClient(), modernizer=EchoModernizer()
    )

    out = capsys.readouterr().out
    assert "処理モード: 複数画像" not in out
    assert "結合OCR結果" not in out
    assert "OCR結果" in out


def test_batch_still_shows_batch_heading(tmp_path, capsys):
    """複数枚処理では従来どおり見出しを表示する（対象の一覧は並び順を決める入口が出す）"""
    images = _images(tmp_path / "input", 2)

    process_batch(
        _args(tmp_path), images, client=FakeClient(), modernizer=EchoModernizer()
    )

    out = capsys.readouterr().out
    assert "処理モード: 複数画像（2枚）" in out
    assert "対象:" not in out  # 1行のカンマ区切り表示は番号付き一覧に置き換えた


def test_single_failure_shows_summary_and_retry_hint(tmp_path, capsys):
    """1枚のOCR失敗でも、失敗画像名・理由・再試行のコマンド例をまとめて出す"""
    [image] = _images(tmp_path / "input", 1)
    client = FakeClient({1: OllamaConnectionError("Ollamaが停止中")})

    code = process_single(
        _args(tmp_path), image, client=client, modernizer=EchoModernizer()
    )

    assert code == 1
    out = capsys.readouterr().out
    assert "[1] p001.png — Ollamaが停止中" in out
    assert "再試行するには" in out
    assert "uv run prewar ocr <画像パス>" in out


def test_single_interrupt_saves_nothing(tmp_path):
    """1枚のOCR中に Ctrl+C: 終了コード1、記録は作られない（従来と同じ）"""
    [image] = _images(tmp_path / "input", 1)
    client = FakeClient({1: KeyboardInterrupt()})

    code = process_single(
        _args(tmp_path), image, client=client, modernizer=EchoModernizer()
    )

    assert code == 1
    assert _docs(tmp_path) == []


# ---------- 純粋関数: 記録の組み立て ----------


def _ocr_result(text: str, elapsed: float, model: str = "glm-ocr"):
    return OCRResult(
        text=text,
        model=model,
        image_path="",
        elapsed_seconds=elapsed,
        prompt="p",
        options={"temperature": 0.0},
    )


def _outcome(results, ok_indices, failures=(), aborted=False) -> BatchOcrOutcome:
    return BatchOcrOutcome(
        results=list(results),
        ok_indices=list(ok_indices),
        failures=list(failures),
        aborted=aborted,
    )


def test_build_record_sums_elapsed_and_uses_first_page_meta(tmp_path):
    """OCR所要時間は合計、モデル名・プロンプト・生成パラメータは先頭ページのもの"""
    images = [Path(f"p{i:03d}.png") for i in (1, 2)]
    outcome = _outcome(
        [_ocr_result("一", 1.5, model="先頭"), _ocr_result("二", 2.0, model="次")],
        [0, 1],
    )

    record = _build_record(
        _args(tmp_path), images, outcome, "一\n\n二", "現代語", MetaModernize(True, "m"),
        None, None,
    )

    assert record.ocr_meta.elapsed_seconds == 3.5
    assert record.ocr_meta.model == "先頭"
    assert record.ocr_meta.options == {"temperature": 0.0}
    assert record.source_paths == images
    assert record.page_failures == []
    assert record.pages_total == 2


def test_build_record_keeps_only_successful_pages(tmp_path):
    """失敗ページを除き、元画像と前処理後画像を同じ添字で絞り込む"""
    images = [Path(f"p{i:03d}.png") for i in (1, 2, 3)]
    pre = [Path(f"pre_{i:02d}.png") for i in (1, 2, 3)]
    failure = MetaPageFailure(index=2, source="p002.png", reason="image", message="壊")
    outcome = _outcome(
        [_ocr_result("一", 1.0), _ocr_result("三", 1.0)], [0, 2], [failure], True
    )

    record = _build_record(
        _args(tmp_path), images, outcome, "一\n\n三", "現代語", MetaModernize(True, "m"),
        pre, None,
    )

    assert record.source_paths == [images[0], images[2]]
    assert record.preprocessed_paths == [pre[0], pre[2]]
    assert record.page_failures == [failure]
    assert record.pages_total == 3
    assert record.pages_aborted is True


def test_build_record_collects_trim_and_limit_by_original_page(tmp_path):
    """G12: 切り落とし字数と上限到達を、失敗ページを飛ばした元のページ番号で集める"""
    images = [Path(f"p{i:03d}.png") for i in (1, 2, 3, 4)]
    failure = MetaPageFailure(index=2, source="p002.png", reason="repeat", message="反復")
    results = [_ocr_result("一", 1.0), _ocr_result("三", 1.0), _ocr_result("四", 1.0)]
    results[1].trimmed_chars = 1200  # 3枚目（成功分の2件目）
    results[1].hit_limit = True
    results[2].hit_limit = True  # 4枚目: 反復なしで上限到達＝本当に長いページ
    outcome = _outcome(results, [0, 2, 3], [failure])

    record = _build_record(
        _args(tmp_path), images, outcome, "一\n\n三\n\n四", "現代語",
        MetaModernize(True, "m"), None, None,
    )

    assert record.ocr_meta.repetition_trimmed == {3: 1200}
    assert record.ocr_meta.hit_limit_pages == [3, 4]


def test_build_record_has_no_trim_info_when_clean(tmp_path):
    """反復も上限到達も無ければ空のまま（meta.json にキーが出ない）"""
    outcome = _outcome([_ocr_result("一", 1.0)], [0])

    record = _build_record(
        _args(tmp_path), [Path("p001.png")], outcome, "一", "一",
        MetaModernize(True, "m"), None, None,
    )

    assert record.ocr_meta.repetition_trimmed == {}
    assert record.ocr_meta.hit_limit_pages == []


@pytest.mark.parametrize("no_normalize", [False, True])
def test_build_record_normalization_flags(tmp_path, no_normalize):
    """正規化の4項目は --no-normalize の有無でそろって切り替わる"""
    outcome = _outcome([_ocr_result("一", 1.0)], [0])

    record = _build_record(
        _args(tmp_path, no_normalize=no_normalize),
        [Path("p001.png")],
        outcome,
        "一",
        "一",
        MetaModernize(True, "m"),
        None,
        None,
    )

    flags = record.normalization
    expected = not no_normalize
    assert (
        flags.old_kanji,
        flags.hentaigana,
        flags.historical_kana,
        flags.ocr_misread_correction,
    ) == (expected,) * 4


# ---------- 純粋関数: 終了コード ----------

_FAILURE = MetaPageFailure(index=1, source="p001.png", reason="timeout", message="t")


@pytest.mark.parametrize(
    ("outcome", "modern_meta", "expected"),
    [
        (_outcome([], [], [_FAILURE]), None, 1),
        (_outcome([_ocr_result("一", 1.0)], [0]), MetaModernize(True, "m"), 0),
        (_outcome([_ocr_result("一", 1.0)], [0]), MetaModernize(False, ""), 0),
        (
            _outcome([_ocr_result("一", 1.0)], [1], [_FAILURE]),
            MetaModernize(True, "m"),
            2,
        ),
        (
            _outcome([_ocr_result("一", 1.0)], [0]),
            MetaModernize(True, "m", error="停止中"),
            2,
        ),
        (
            _outcome([_ocr_result("一", 1.0)], [0]),
            MetaModernize(True, "m", error="interrupted"),
            2,
        ),
        (
            _outcome([_ocr_result("一", 1.0)], [0]),
            MetaModernize(True, "m", failed_chunks=1, chunk_total=5),
            2,
        ),
    ],
    ids=[
        "全ページ失敗",
        "全成功",
        "口語化省略",
        "失敗ページあり",
        "口語化エラー",
        "口語化中断",
        "失敗チャンクあり",
    ],
)
def test_exit_code(outcome, modern_meta, expected):
    assert _exit_code(outcome, modern_meta) == expected


# ---------- ページ順（D5） ----------


def _files(folder: Path, names: list[str], mtimes: dict[str, int] | None = None):
    """名前のリストどおりに画像ファイルを作る（中身は自分の名前）

    mtimes があれば {名前: 更新日時(秒)} を設定する。作らないものは現在時刻のまま。
    """
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        p = folder / name
        p.write_bytes(name.encode())
        if mtimes and name in mtimes:
            os.utime(p, (mtimes[name], mtimes[name]))
        paths.append(p)
    return paths


def _sources(doc: Path) -> list[bytes]:
    """保存された元画像を source_NN の番号順に、中身（元の名前）で返す"""
    return [p.read_bytes() for p in sorted(doc.glob("source_*"))]


def _run_folder(tmp_path, folder, **overrides):
    return process_folder(
        _args(tmp_path, **overrides),
        folder,
        client=NameEchoClient(),
        modernizer=EchoModernizer(),
    )


def test_folder_unpadded_numbers_are_combined_in_page_order(tmp_path):
    """0埋めのない 1.png〜12.png は、本文も保存される画像も 1→12 の順になる"""
    folder = tmp_path / "input"
    _files(folder, [f"{i}.png" for i in range(1, 13)])

    code = _run_folder(tmp_path, folder)

    assert code == 0
    doc = _only_doc(tmp_path)
    expected = [f"{i}.png" for i in range(1, 13)]
    assert _sources(doc) == [n.encode() for n in expected]
    assert _read(doc, "ocr_raw.txt").split("\n\n") == [f"本文:{n}" for n in expected]


def test_folder_unpadded_numbers_legacy_output_name(tmp_path):
    """旧形式の出力名は先頭と末尾のページから作る: 1-12_modern.txt"""
    folder = tmp_path / "input"
    _files(folder, [f"{i}.png" for i in range(1, 13)])

    _run_folder(tmp_path, folder, legacy_output=True)

    assert (tmp_path / "output" / "1-12_modern.txt").exists()


def test_folder_includes_tif_and_webp(tmp_path):
    """OCR が受け付ける .tif / .webp も処理対象になり、この順で結合される"""
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.tif", "3.webp"])

    assert _run_folder(tmp_path, folder) == 0
    assert _sources(_only_doc(tmp_path)) == [b"1.png", b"2.tif", b"3.webp"]


def test_folder_ignores_hidden_files_and_directories(tmp_path):
    """隠しファイル（._1.png）と、画像のような名前のフォルダは対象にしない"""
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.png", "._1.png"])
    (folder / "old.png").mkdir()

    assert _run_folder(tmp_path, folder) == 0
    assert _sources(_only_doc(tmp_path)) == [b"1.png", b"2.png"]


# --- 並び順の表示 ---


def test_folder_prints_numbered_order_before_ocr(tmp_path, capsys):
    """結合するときは OCR より前に、並べ方と番号付きの一覧を表示する"""
    folder = tmp_path / "input"
    _files(folder, ["10.png", "2.png", "1.png"])

    _run_folder(tmp_path, folder)

    out = capsys.readouterr().out
    assert "並び順: ファイル名順（3枚）" in out
    assert out.index("1. 1.png") < out.index("2. 2.png") < out.index("3. 10.png")
    assert out.index("3. 10.png") < out.index("[OCR 1/3]")


def test_single_image_prints_no_order_list(tmp_path, capsys):
    """画像が1枚のときは並び順の一覧を表示しない"""
    folder = tmp_path / "input"
    _files(folder, ["1.png"])

    _run_folder(tmp_path, folder)

    assert "並び順:" not in capsys.readouterr().out


def test_separate_prints_no_order_list_or_warning(tmp_path, capsys):
    """画像ごとの別記録では、一覧も食い違いの警告も出さない"""
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.png", "3.png"], {"1.png": 1000, "2.png": 3000, "3.png": 2000})

    _run_folder(tmp_path, folder, separate=True)

    out = capsys.readouterr().out
    assert "並び順:" not in out
    assert "食い違" not in out


# --- 食い違いの警告 ---


def test_folder_warns_on_mismatch_but_continues(tmp_path, capsys):
    """名前順と更新日時順が食い違っても、警告を出してファイル名順のまま完了する"""
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.png", "3.png"], {"1.png": 1000, "2.png": 3000, "3.png": 2000})

    code = _run_folder(tmp_path, folder)

    assert code == 0  # 警告は終了コードに反映しない
    out = capsys.readouterr().out
    assert "食い違っています（2番目から）" in out
    assert "--order mtime" in out
    assert out.index("食い違") < out.index("[OCR 1/3]")  # OCR の前に出る
    assert _sources(_only_doc(tmp_path)) == [b"1.png", b"2.png", b"3.png"]


def test_folder_no_warning_when_orders_agree(tmp_path, capsys):
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.png", "10.png"], {"1.png": 1000, "2.png": 2000, "10.png": 3000})

    _run_folder(tmp_path, folder)

    assert "食い違" not in capsys.readouterr().out


def test_folder_no_warning_when_all_mtimes_equal(tmp_path, capsys):
    """更新日時がすべて同じ（zip 展開など）なら警告しない"""
    folder = tmp_path / "input"
    _files(folder, ["1.png", "2.png", "10.png"], {n: 5000 for n in ["1.png", "2.png", "10.png"]})

    _run_folder(tmp_path, folder)

    assert "食い違" not in capsys.readouterr().out


# --- 並べ方の指定 ---


def test_folder_order_mtime_uses_oldest_first_without_warning(tmp_path, capsys):
    """--order mtime: 更新日時の古い順で結合し、食い違いの警告は出さない"""
    folder = tmp_path / "input"
    _files(folder, ["a.png", "b.png"], {"a.png": 2000, "b.png": 1000})

    assert _run_folder(tmp_path, folder, order="mtime") == 0

    assert _sources(_only_doc(tmp_path)) == [b"b.png", b"a.png"]
    out = capsys.readouterr().out
    assert "並び順: 更新日時の古い順（2枚）" in out
    assert "食い違" not in out


def test_folder_order_mtime_ties_use_natural_order(tmp_path):
    """更新日時がすべて同じなら、mtime 指定でも自然順（文字列順ではない）"""
    folder = tmp_path / "input"
    names = ["10.png", "2.png", "1.png"]
    _files(folder, names, {n: 5000 for n in names})

    _run_folder(tmp_path, folder, order="mtime")

    assert _sources(_only_doc(tmp_path)) == [b"1.png", b"2.png", b"10.png"]


def test_folder_order_flag_overrides_config(tmp_path, monkeypatch):
    """設定ファイルで mtime を指定していても、--order name が優先される"""
    real_get = ocr_vision_llm.CONFIG.get
    monkeypatch.setattr(
        ocr_vision_llm.CONFIG,
        "get",
        lambda key, default=None: "mtime" if key == "batch.order" else real_get(key, default),
    )
    folder = tmp_path / "input"
    _files(folder, ["a.png", "b.png"], {"a.png": 2000, "b.png": 1000})

    _run_folder(tmp_path, folder, order="name")

    assert _sources(_only_doc(tmp_path)) == [b"a.png", b"b.png"]


# --- 撮りため ---


def _shoot_args(tmp_path, **overrides):
    args = _args(tmp_path, **overrides)
    args.image = "shoot"
    return args


def test_shoot_processes_in_capture_order_regardless_of_order(tmp_path, monkeypatch, capsys):
    """撮りためは、並べ方が mtime でも撮った順で結合し、食い違いの警告も出さない"""
    # 撮った順（a, b, c）と、更新日時の順（c, b, a）を食い違わせておく
    session = tmp_path / "input" / "session_x"
    captured = _files(
        session, ["a.png", "b.png", "c.png"], {"a.png": 3000, "b.png": 2000, "c.png": 1000}
    )
    monkeypatch.setattr(ocr_vision_llm.screen_capture, "is_supported", lambda: True)
    monkeypatch.setattr(
        ocr_vision_llm.screen_capture, "shoot_session", lambda input_dir: captured
    )
    received: list[list[Path]] = []

    def fake_batch(args, image_paths, **kwargs):
        received.append(list(image_paths))
        return 0

    monkeypatch.setattr(ocr_vision_llm, "process_batch", fake_batch)

    code = ocr_vision_llm.run(_shoot_args(tmp_path, order="mtime"))

    assert code == 0
    assert received == [captured]  # 撮った順のまま
    out = capsys.readouterr().out
    assert "並び順: 撮影順（3枚）" in out
    assert "食い違" not in out


def test_shoot_session_returns_capture_order(tmp_path, monkeypatch):
    """1000枚撮っても撮った順で返す（文字列順に並べ直すと p1000 が先頭に来てしまう）"""
    from utils import screen_capture

    total = 1000
    monkeypatch.setattr(screen_capture, "is_supported", lambda: True)
    monkeypatch.setattr(
        screen_capture, "capture_one", lambda dest: dest.write_bytes(b"x") or True
    )
    session = tmp_path / "session"
    session.mkdir()
    monkeypatch.setattr(screen_capture, "create_session_dir", lambda input_dir: session)
    answers = iter(["次を撮る"] * (total - 1) + ["終了して処理へ"])
    monkeypatch.setattr(
        screen_capture.questionary,
        "select",
        lambda *a, **k: _Answer(next(answers)),
    )

    result = screen_capture.shoot_session(tmp_path)

    assert [p.name for p in result] == [f"p{i:03d}.png" for i in range(1, total + 1)]
    assert result[-1].name == "p1000.png"


# --- 対話メニュー ---


class _Answer:
    """questionary の prompt オブジェクトの代わり（ask() で決まった答えを返す）"""

    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


def _interactive_args(tmp_path, **overrides):
    args = _args(tmp_path, **overrides)
    args.image = None
    return args


def _patch_interactive(monkeypatch, selected, answer):
    """対話の複数選択: 処理モード=複数、選択した画像=selected、食い違い時の答え=answer"""
    monkeypatch.setattr(ocr_vision_llm, "select_mode_interactive", lambda: "batch")
    monkeypatch.setattr(ocr_vision_llm, "select_images_batch", lambda order="name": selected)
    asked: list[list[str]] = []

    def fake_select(message, choices=None, **kwargs):
        asked.append(list(choices))
        return _Answer(answer)

    monkeypatch.setattr(ocr_vision_llm.questionary, "select", fake_select)
    received: list[list[Path]] = []

    def fake_batch(args, image_paths, **kwargs):
        received.append(list(image_paths))
        return 0

    monkeypatch.setattr(ocr_vision_llm, "process_batch", fake_batch)
    return asked, received


def _mismatched(tmp_path):
    """名前順 1,2,3 / 更新日時順 1,3,2 になる3枚（名前順で返す）"""
    return _files(
        tmp_path / "input",
        ["1.png", "2.png", "3.png"],
        {"1.png": 1000, "2.png": 3000, "3.png": 2000},
    )


def test_interactive_keep_name_order(tmp_path, monkeypatch, capsys):
    """食い違いの警告の後、「このまま進む」ならファイル名順で処理する"""
    selected = _mismatched(tmp_path)
    asked, received = _patch_interactive(monkeypatch, selected, ocr_vision_llm._CHOICE_KEEP)

    code = ocr_vision_llm.run(_interactive_args(tmp_path))

    assert code == 0
    assert received == [selected]
    assert asked == [
        [
            ocr_vision_llm._CHOICE_KEEP,
            ocr_vision_llm._CHOICE_MTIME,
            ocr_vision_llm._CHOICE_QUIT,
        ]
    ]
    assert "食い違っています（2番目から）" in capsys.readouterr().out


def test_interactive_choose_mtime_order(tmp_path, monkeypatch, capsys):
    """「更新日時の古い順に並べ替えて進む」なら、並べ替え後の一覧を出して更新日時順で処理する"""
    selected = _mismatched(tmp_path)
    _, received = _patch_interactive(monkeypatch, selected, ocr_vision_llm._CHOICE_MTIME)

    code = ocr_vision_llm.run(_interactive_args(tmp_path))

    assert code == 0
    assert [p.name for p in received[0]] == ["1.png", "3.png", "2.png"]
    out = capsys.readouterr().out
    assert "並び順: 更新日時の古い順（3枚）" in out
    assert out.index("並び順: ファイル名順") < out.index("並び順: 更新日時の古い順")


@pytest.mark.parametrize("answer", [ocr_vision_llm._CHOICE_QUIT, None])
def test_interactive_quit_does_nothing(tmp_path, monkeypatch, answer):
    """「やめる」や Ctrl+C なら OCR は行われず、終了コード 1"""
    selected = _mismatched(tmp_path)
    _, received = _patch_interactive(monkeypatch, selected, answer)

    code = ocr_vision_llm.run(_interactive_args(tmp_path))

    assert code == 1
    assert received == []
    assert _docs(tmp_path) == []


def test_interactive_no_prompt_when_orders_agree(tmp_path, monkeypatch):
    """食い違いが無ければ選択肢は出さず、そのまま処理する"""
    selected = _files(
        tmp_path / "input", ["1.png", "2.png"], {"1.png": 1000, "2.png": 2000}
    )
    asked, received = _patch_interactive(monkeypatch, selected, None)

    assert ocr_vision_llm.run(_interactive_args(tmp_path)) == 0

    assert asked == []
    assert received == [selected]


def test_interactive_mtime_order_skips_check(tmp_path, monkeypatch):
    """更新日時順を指定しているときは、食い違いがあっても選択肢を出さない"""
    selected = _mismatched(tmp_path)
    asked, received = _patch_interactive(monkeypatch, selected, None)

    assert ocr_vision_llm.run(_interactive_args(tmp_path, order="mtime")) == 0

    assert asked == []
    assert received == [selected]  # 並べ替えは select_images_batch 側の責務


def test_select_images_batch_returns_in_page_order(tmp_path, monkeypatch):
    """複数選択は、選んだ順や表示順にかかわらず指定の並べ方で返す"""
    names = ["10.png", "2.png", "1.png"]
    _files(tmp_path / "input", names, {"10.png": 1000, "2.png": 2000, "1.png": 3000})
    monkeypatch.setattr(ocr_vision_llm, "INPUT_DIR", tmp_path / "input")
    # checkbox は一覧（自然順）と無関係な順で答えを返してくる想定
    monkeypatch.setattr(
        ocr_vision_llm.questionary,
        "checkbox",
        lambda *a, **k: _Answer(["10.png", "1.png", "2.png"]),
    )

    by_name = ocr_vision_llm.select_images_batch("name")
    by_mtime = ocr_vision_llm.select_images_batch("mtime")

    assert [p.name for p in by_name] == ["1.png", "2.png", "10.png"]
    assert [p.name for p in by_mtime] == ["10.png", "2.png", "1.png"]

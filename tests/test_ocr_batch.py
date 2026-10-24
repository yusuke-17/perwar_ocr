"""バッチOCRの失敗耐性（G2）のテスト

1枚の失敗で全件を捨てないこと、成功分だけが正しい順序で保存対象になること、
Ollama停止時に全ページ分のタイムアウトを待たないことを確認する。
_ocr_pages は Ollama を直接触らないため、手書きのフェイククライアントで足りる。
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from scripts.ocr_vision_llm import (
    _ocr_pages,
    _preprocess_images,
    _run_modernize,
    _run_ocr_page,
)
from utils.text_modernizer import ChunkFailure, ModernizeResult
from utils.library_writer import (
    DocumentRecord,
    MetaModernize,
    MetaNormalization,
    MetaOcr,
    MetaPageFailure,
    save_document,
)
from utils.ndlocr_client import NdlocrLiteClient
from utils.ollama_client import (
    ImageFileError,
    OllamaConnectionError,
    OllamaRepeatError,
    OllamaTimeoutError,
)

from fakes import FakeClient as _FakeClient
from fakes import FakeNdlocrBackend, install_fake_ndlocr
from fakes import StubModernizer as _StubModernizer


def _pages(n: int) -> list[Path]:
    """p001.png … 形式のダミー画像パスを n 件返す（ファイル実体は不要）"""
    return [Path(f"input/p{i:03d}.png") for i in range(1, n + 1)]


# ---------- 失敗ページのスキップ ----------


def test_last_page_failure_keeps_earlier_results():
    """10枚目が接続エラーでも、成功済み9枚が残る（G2の核）"""
    images = _pages(10)
    client = _FakeClient({10: OllamaConnectionError("接続できません")})

    outcome = _ocr_pages(client, images, images)

    assert len(outcome.results) == 9
    assert outcome.ok_indices == list(range(9))
    assert len(outcome.failures) == 1
    assert outcome.failures[0].index == 10
    assert outcome.failures[0].reason == "connection"


def test_middle_page_failure_continues():
    """途中の1枚が壊れていても、後続のページは処理される"""
    images = _pages(5)
    client = _FakeClient({3: ImageFileError("画像が壊れています")})

    outcome = _ocr_pages(client, images, images)

    assert outcome.ok_indices == [0, 1, 3, 4]
    assert outcome.failures[0].reason == "image"
    assert outcome.failures[0].source == "p003.png"
    # 成功ページのテキストだけが元の順序で並ぶ
    assert [r.text for r in outcome.results] == [
        "ページ1の本文",
        "ページ2の本文",
        "ページ4の本文",
        "ページ5の本文",
    ]


def test_timeout_page_is_recorded_as_timeout():
    """無応答ページは reason="timeout" で記録され、後続は処理される（G4）

    タイムアウトが「例外」になったことで、G2の部分保存機構にそのまま乗る。
    """
    images = _pages(3)
    client = _FakeClient({2: OllamaTimeoutError("300 秒以内に応答しませんでした")})

    outcome = _ocr_pages(client, images, images)

    assert outcome.failures[0].reason == "timeout"
    assert outcome.ok_indices == [0, 2]
    assert len(outcome.results) == 2


def test_consecutive_timeouts_abort():
    """連続タイムアウトも既存の打ち切り機構で止まる（全ページ分待たない）"""
    images = _pages(10)
    client = _FakeClient({i: OllamaTimeoutError("無応答") for i in range(1, 11)})

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.aborted is True
    assert client.calls == 3


def test_unknown_error_is_classified():
    """未知の例外も unknown として記録され、処理は継続する"""
    images = _pages(3)
    client = _FakeClient({2: ValueError("想定外")})

    outcome = _ocr_pages(client, images, images)

    assert outcome.failures[0].reason == "unknown"
    assert len(outcome.results) == 2


def test_all_pages_fail():
    """全滅時は results が空（呼び出し側が保存せず1を返す判断に使う）"""
    images = _pages(2)
    client = _FakeClient(
        {1: OllamaConnectionError("停止中"), 2: OllamaConnectionError("停止中")}
    )

    outcome = _ocr_pages(client, images, images, abort_after=0)

    assert outcome.results == []
    assert len(outcome.failures) == 2


# ---------- 打ち切り（フェイルファスト） ----------


def test_abort_after_consecutive_failures():
    """連続3枚失敗したら残りを待たずに打ち切る"""
    images = _pages(10)
    client = _FakeClient({i: OllamaConnectionError("停止中") for i in range(1, 11)})

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.aborted is True
    assert client.calls == 3  # 4枚目以降は呼ばれない
    assert len(outcome.failures) == 3


def test_consecutive_counter_resets_on_success():
    """間に成功が挟まれば連続失敗はリセットされ、打ち切らない"""
    images = _pages(6)
    client = _FakeClient(
        {
            1: OllamaConnectionError("一時的"),
            2: OllamaConnectionError("一時的"),
            4: OllamaConnectionError("一時的"),
        }
    )

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.aborted is False
    assert client.calls == 6
    assert outcome.ok_indices == [2, 4, 5]


def test_repeat_failure_is_recorded_as_repeat():
    """仕様「反復による失敗がメタ情報に残る」: 理由 repeat で記録され、残りは処理される"""
    images = _pages(3)
    client = _FakeClient({2: OllamaRepeatError("反復検知で打ち切り")})

    outcome = _ocr_pages(client, images, images)

    assert outcome.failures[0].index == 2
    assert outcome.failures[0].reason == "repeat"
    assert outcome.ok_indices == [0, 2]


def test_repeat_failures_do_not_abort():
    """仕様「反復による失敗は打ち切りに数えない」: 1〜3枚目が反復でも 4 枚目以降を処理する"""
    images = _pages(10)
    client = _FakeClient({i: OllamaRepeatError("反復") for i in (1, 2, 3)})

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.aborted is False
    assert client.calls == 10
    assert [f.reason for f in outcome.failures] == ["repeat"] * 3
    assert outcome.ok_indices == list(range(3, 10))


def test_connection_failures_still_abort_after_repeat():
    """仕様「接続不可は従来どおり打ち切りに数える」: 反復を挟んでも接続不可×3 で止まる

    反復は数えないがリセットもしないので、反復→接続不可×3 の並びで打ち切る。
    """
    images = _pages(10)
    fail_at = {1: OllamaRepeatError("反復")}
    fail_at.update({i: OllamaConnectionError("停止中") for i in range(2, 11)})
    client = _FakeClient(fail_at)

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.aborted is True
    assert client.calls == 4
    assert [f.reason for f in outcome.failures] == ["repeat"] + ["connection"] * 3


def test_on_page_error_abort_keeps_old_behavior():
    """on_page_error='abort' なら1枚目の失敗で即打ち切る（従来挙動）"""
    images = _pages(5)
    client = _FakeClient({1: ImageFileError("壊れています")})

    outcome = _ocr_pages(client, images, images, on_page_error="abort")

    assert outcome.aborted is True
    assert client.calls == 1
    assert outcome.results == []


def test_keyboard_interrupt_keeps_successful_pages():
    """Ctrl+C でも、そこまでの成功分は捨てずに返す（G2c）"""
    images = _pages(5)
    client = _FakeClient({3: KeyboardInterrupt()})

    outcome = _ocr_pages(client, images, images)

    assert outcome.aborted is True
    assert len(outcome.results) == 2
    assert outcome.failures[0].reason == "interrupted"
    assert outcome.failures[0].index == 3
    assert client.calls == 3  # 4枚目以降は処理しない


def test_preprocessed_targets_are_used():
    """OCR対象は前処理後の画像、記録に残る名前は元画像"""
    images = _pages(2)
    targets = [Path("/tmp/pre_01.png"), Path("/tmp/pre_02.png")]
    client = _FakeClient({2: ImageFileError("壊れています")})

    outcome = _ocr_pages(client, images, targets)

    assert outcome.results[0].image_path == "/tmp/pre_01.png"
    assert outcome.failures[0].source == "p002.png"


# ---------- 口語体変換の失敗吸収（G2b） ----------


def test_modernize_failure_keeps_normalized_text():
    """LLMが落ちても正規化テキストで保存へ進み、理由がメタに残る"""
    args = argparse.Namespace(no_modernize=False)

    text, meta = _run_modernize(
        _StubModernizer(error=OllamaConnectionError("停止中")), "正規化済み本文", args
    )

    assert text == "正規化済み本文"
    assert meta.enabled is True
    assert "停止中" in meta.error


def test_modernize_interrupt_is_recorded():
    """Ctrl+C も正規化テキストで保存し、interrupted として記録する"""
    args = argparse.Namespace(no_modernize=False)

    text, meta = _run_modernize(
        _StubModernizer(error=KeyboardInterrupt()), "正規化済み本文", args
    )

    assert text == "正規化済み本文"
    assert meta.error == "interrupted"


def test_modernize_partial_failure_is_counted():
    """一部チャンクが失敗したら件数をメタに残す（テキストは変換結果を採用）"""
    args = argparse.Namespace(no_modernize=False)
    result = ModernizeResult(
        text="変換済み本文",
        chunk_total=5,
        failures=[ChunkFailure(index=2, message="失敗")],
    )

    text, meta = _run_modernize(_StubModernizer(result=result), "原文", args)

    assert text == "変換済み本文"
    assert meta.failed_chunks == 1
    assert meta.chunk_total == 5


def test_modernize_skipped_by_flag():
    """--no-modernize なら LLM を呼ばず enabled=False で記録する"""
    args = argparse.Namespace(no_modernize=True)

    text, meta = _run_modernize(_StubModernizer(), "正規化済み本文", args)

    assert text == "正規化済み本文"
    assert meta.enabled is False
    assert meta.model == ""


# ---------- 前処理のページ単位フォールバック ----------


def _write_valid_image(path: Path) -> None:
    """cv2 で読める最小限の文書風画像を書き出す"""
    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (20, 40), (180, 60), (0, 0, 0), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))


def _preprocess_args(model: str = "glm-ocr") -> argparse.Namespace:
    """前処理が効く引数。前処理は Ollama 経由のエンジン（GLM-OCR）でだけ働くので既定は glm-ocr"""
    return argparse.Namespace(no_preprocess=False, binarize=None, model=model)


def test_preprocess_falls_back_per_page(tmp_path):
    """1枚が壊れていても、他ページの前処理結果は捨てない"""
    good1, broken, good2 = (tmp_path / n for n in ("a.png", "b.png", "c.png"))
    _write_valid_image(good1)
    _write_valid_image(good2)
    broken.write_bytes(b"not an image")
    workdir = tmp_path / "work"
    workdir.mkdir()

    paths, meta = _preprocess_images(
        _preprocess_args(), [good1, broken, good2], workdir
    )

    assert paths is not None and meta is not None
    assert len(paths) == 3  # 元画像と同順・同数（添字の対応が崩れない）
    assert paths[1] == broken  # 失敗ページだけ元画像にフォールバック
    assert paths[0].parent == workdir and paths[2].parent == workdir


@pytest.mark.parametrize("suffix", [".tif", ".tiff", ".webp", ".jpg", ".bmp"])
def test_preprocess_reads_every_format_the_folder_scan_accepts(tmp_path, suffix):
    """フォルダ処理が対象にする形式（.tif / .webp を含む）は、前処理で読めて元画像に頼らない

    列挙側を OCR が対応する形式にそろえたので、前処理（OpenCV）が読めない形式が
    混ざると全ページ「元画像にフォールバック」になって前処理が静かに効かなくなる。
    """
    src = tmp_path / f"page{suffix}"
    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (20, 40), (180, 60), (0, 0, 0), -1)
    ok, buf = cv2.imencode(suffix, img)
    assert ok
    buf.tofile(str(src))
    workdir = tmp_path / "work"
    workdir.mkdir()

    paths, meta = _preprocess_images(_preprocess_args(), [src], workdir)

    assert paths is not None and meta is not None
    assert paths[0] != src and paths[0].parent == workdir  # フォールバックしていない


def test_preprocess_all_failed_disables_preprocess(tmp_path):
    """全ページ失敗なら前処理なし扱い（従来どおり元画像でOCR）"""
    broken = tmp_path / "b.png"
    broken.write_bytes(b"not an image")
    workdir = tmp_path / "work"
    workdir.mkdir()

    paths, meta = _preprocess_images(_preprocess_args(), [broken], workdir)

    assert paths is None
    assert meta is None


# ---------- NDLOCR-Lite の失敗の分類（ndlocr-lite-engine） ----------


def _pngs(folder: Path, n: int) -> list[Path]:
    """本物の PNG を n 枚作る（NDLOCR-Lite のクライアントは画像を開くため）"""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        path = folder / f"p{i:03d}.png"
        Image.new("RGB", (40, 60), "white").save(path)
        paths.append(path)
    return paths


def test_ndlocr_not_installed_aborts_early(tmp_path, capsys):
    """NDLOCR-Lite を取得していないと、理由「OCRエンジン未導入」で失敗し、連続失敗の打ち切りで残りを待たない"""
    images = _pngs(tmp_path / "input", 5)
    backend = FakeNdlocrBackend()
    client = NdlocrLiteClient(tmp_path / "not-fetched", backend=backend)

    outcome = _ocr_pages(client, images, images, abort_after=3)

    assert outcome.results == []
    assert [f.reason for f in outcome.failures] == ["model"] * 3
    assert outcome.aborted is True
    assert "git submodule update --init --depth 1" in outcome.failures[0].message
    assert backend.recognized == []
    out = capsys.readouterr().out
    assert "OCRエンジン未導入" in out
    assert "未処理 2枚" in out


def test_ndlocr_recognition_error_skips_only_that_page(tmp_path):
    """2 枚目の認識中にエラーが出ても、その理由と内容を記録してスキップし、1・3 枚目は残る"""
    images = _pngs(tmp_path / "input", 3)
    backend = FakeNdlocrBackend(recognize_errors={2: RuntimeError("onnx の推論に失敗")})
    root = install_fake_ndlocr(tmp_path / "ndlocr")
    client = NdlocrLiteClient(root, backend=backend, version_reader=lambda _root: "1.3.1")

    outcome = _ocr_pages(client, images, images)

    assert outcome.ok_indices == [0, 2]
    [failure] = outcome.failures
    assert (failure.index, failure.reason) == (2, "unknown")
    assert "onnx の推論に失敗" in failure.message
    assert outcome.aborted is False


# ---------- meta.json への記録 ----------


def _record(tmp_path: Path, **kwargs) -> DocumentRecord:
    """save_document に渡す最小構成のレコード"""
    src = tmp_path / "source.png"
    src.write_bytes(b"dummy")
    base = dict(
        source_paths=[src],
        ocr_raw="本文",
        modern_text="本文",
        ocr_meta=MetaOcr(model="glm-ocr", prompt="p", elapsed_seconds=1.0),
        normalization=MetaNormalization(True, True, True),
        modernize=MetaModernize(enabled=True, model="qwen3.5:9b"),
    )
    base.update(kwargs)
    return DocumentRecord(**base)


def _saved_meta(tmp_path: Path, record: DocumentRecord) -> dict:
    """レコードを保存して meta.json を読み返す"""
    doc_dir = save_document(record, library_root=tmp_path / "library")
    return json.loads((doc_dir / "meta.json").read_text(encoding="utf-8"))


def test_meta_records_ocr_options(tmp_path):
    """どの生成パラメータで作られた記録かを meta.json に残す（G4）"""
    record = _record(
        tmp_path,
        ocr_meta=MetaOcr(
            model="glm-ocr",
            prompt="p",
            elapsed_seconds=1.0,
            options={"temperature": 0.0, "seed": 0},
        ),
    )

    meta = _saved_meta(tmp_path, record)

    assert meta["ocr"]["options"] == {"temperature": 0.0, "seed": 0}


def test_meta_has_no_pages_section_when_all_succeed(tmp_path):
    """失敗ゼロなら pages キーを出さない（従来の meta.json と同じ形）"""
    meta = _saved_meta(tmp_path, _record(tmp_path))

    assert "pages" not in meta
    assert "error" not in meta["modernize"]
    assert "failed_chunks" not in meta["modernize"]


def test_meta_records_skipped_pages(tmp_path):
    """スキップしたページが pages.skipped に残る"""
    failure = MetaPageFailure(
        index=10, source="p010.png", reason="connection", message="接続できません"
    )
    record = _record(
        tmp_path, page_failures=[failure], pages_total=10, pages_aborted=True
    )

    meta = _saved_meta(tmp_path, record)

    assert meta["pages"]["total"] == 10
    assert meta["pages"]["succeeded"] == 1  # source_paths の件数
    assert meta["pages"]["aborted"] is True
    assert meta["pages"]["skipped"] == [
        {
            "index": 10,
            "source": "p010.png",
            "reason": "connection",
            "message": "接続できません",
        }
    ]


def test_meta_records_modernize_failure(tmp_path):
    """口語体変換の失敗内容が modernize セクションに残る"""
    record = _record(
        tmp_path,
        modernize=MetaModernize(
            enabled=True, model="qwen3.5:9b", error="timeout", failed_chunks=2,
            chunk_total=37,
        ),
    )

    meta = _saved_meta(tmp_path, record)

    assert meta["modernize"]["error"] == "timeout"
    assert meta["modernize"]["failed_chunks"] == 2
    assert meta["modernize"]["chunk_total"] == 37


def test_saved_sources_match_successful_pages(tmp_path):
    """失敗ページの画像はコピーされず、連番が成功ページ数と一致する"""
    sources = []
    for i in (1, 2, 4):  # 3枚目は失敗した想定で渡さない
        p = tmp_path / f"p{i:03d}.png"
        p.write_bytes(b"dummy")
        sources.append(p)

    failure = MetaPageFailure(
        index=3, source="p003.png", reason="image", message="壊れています"
    )
    record = _record(
        tmp_path, source_paths=sources, page_failures=[failure], pages_total=4
    )
    doc_dir = save_document(record, library_root=tmp_path / "library")
    meta = json.loads((doc_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["sources"] == ["source_01.png", "source_02.png", "source_03.png"]
    assert not (doc_dir / "source_04.png").exists()
    assert meta["pages"]["succeeded"] == 3


# ---------- G12: 反復・上限到達・再試行の警告と記録 ----------


def _page_output(capsys, extras: dict) -> str:
    """1ページ分の OCR を流し、画面表示を返す"""
    client = _FakeClient(extras={1: extras})
    image = Path("input/p001.png")

    result = _run_ocr_page(client, image, image)

    assert not isinstance(result, MetaPageFailure)  # どの警告でも成功ページのまま
    return capsys.readouterr().out


def test_trimmed_page_shows_warning_with_chars(capsys):
    """反復を切り落としたページは、ページ名と字数入りの警告が出る"""
    out = _page_output(capsys, {"trimmed_chars": 1234})

    assert "反復" in out
    assert "p001.png" in out
    assert "1234 字" in out


def test_hit_limit_page_tells_how_to_raise_limit(capsys):
    """上限到達のページは、上限値と num_predict の案内が出る"""
    out = _page_output(
        capsys, {"hit_limit": True, "options": {"num_predict": 1024}}
    )

    assert "生成上限（1024 トークン）" in out
    assert "num_predict" in out
    assert "反復を検知" not in out  # 切り落とし無し＋上限到達＝本当に長いページ


def test_retried_page_shows_attempts(capsys):
    """再試行で成功したページは、何回目で成功したかが出る"""
    out = _page_output(capsys, {"attempts": 2})

    assert "再試行" in out
    assert "2回目" in out


def test_clean_page_has_no_warning(capsys):
    """反復も上限到達も再試行も無いページは警告を出さない"""
    out = _page_output(capsys, {})

    assert "⚠" not in out


def test_meta_records_repetition_and_hit_limit(tmp_path):
    """反復の切り落とし字数と上限到達ページが meta.json の ocr セクションに残る"""
    record = _record(
        tmp_path,
        ocr_meta=MetaOcr(
            model="glm-ocr",
            prompt="p",
            elapsed_seconds=1.0,
            repetition_trimmed={3: 900, 1: 1200},
            hit_limit_pages=[3, 1],
        ),
    )

    meta = _saved_meta(tmp_path, record)

    # JSON のキーは文字列。ページ順に並べる
    assert meta["ocr"]["repetition_trimmed"] == {"1": 1200, "3": 900}
    assert list(meta["ocr"]["repetition_trimmed"]) == ["1", "3"]
    assert meta["ocr"]["hit_limit_pages"] == [1, 3]


def test_meta_has_no_repetition_keys_when_clean(tmp_path):
    """反復も上限到達も無ければキーを出さない（従来の meta.json と同じ形）"""
    meta = _saved_meta(tmp_path, _record(tmp_path))

    assert "repetition_trimmed" not in meta["ocr"]
    assert "hit_limit_pages" not in meta["ocr"]

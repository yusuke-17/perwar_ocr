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

from scripts.ocr_vision_llm import _ocr_pages, _preprocess_images, _run_modernize
from utils.text_modernizer import ChunkFailure, ModernizeResult
from utils.library_writer import (
    DocumentRecord,
    MetaModernize,
    MetaNormalization,
    MetaOcr,
    MetaPageFailure,
    save_document,
)
from utils.ollama_client import (
    ImageFileError,
    OCRResult,
    OllamaConnectionError,
)


class _FakeClient:
    """指定したページ番号で例外を投げるOCRクライアント

    fail_at: {1始まりのページ番号: 投げる例外} を渡す。
    calls に実際に呼ばれた回数が残るので、打ち切りの検証にも使える。
    """

    model = "fake-ocr"

    def __init__(self, fail_at: dict[int, BaseException] | None = None):
        self.fail_at = fail_at or {}
        self.calls = 0

    def ocr(self, image_path):
        self.calls += 1
        error = self.fail_at.get(self.calls)
        if error is not None:
            raise error
        return OCRResult(
            text=f"ページ{self.calls}の本文",
            model=self.model,
            image_path=str(image_path),
            elapsed_seconds=0.1,
            prompt="テスト用",
        )


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


class _StubModernizer:
    """modernize_detailed だけを持つ最小のスタブ"""

    model = "qwen3.5:9b"

    def __init__(self, result=None, error: BaseException | None = None):
        self.result = result
        self.error = error

    def modernize_detailed(self, text: str):
        if self.error is not None:
            raise self.error
        return self.result


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


def _preprocess_args() -> argparse.Namespace:
    return argparse.Namespace(no_preprocess=False, binarize=None)


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


def test_preprocess_all_failed_disables_preprocess(tmp_path):
    """全ページ失敗なら前処理なし扱い（従来どおり元画像でOCR）"""
    broken = tmp_path / "b.png"
    broken.write_bytes(b"not an image")
    workdir = tmp_path / "work"
    workdir.mkdir()

    paths, meta = _preprocess_images(_preprocess_args(), [broken], workdir)

    assert paths is None
    assert meta is None


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

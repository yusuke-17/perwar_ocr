"""テキスト正規化（normalize_text）のテスト

G3「変体仮名変換のパイプライン接続」で追加。
変体仮名の変換そのものだけでなく、パイプライン内での「位置」が
守られていることを機械的に固定する（位置が動くと静かに壊れるため）。
"""

from utils.text_normalizer import _normalize_body, normalize_text


# 変体仮名リテラル（コメントに Unicode 名を併記）
HG_A = "\U0001B002"    # HENTAIGANA LETTER A-1  → あ
HG_KA = "\U0001B017"   # HENTAIGANA LETTER KA-1 → か
HG_U = "\U0001B00A"    # HENTAIGANA LETTER U-1  → う
HG_RA = "\U0001B0ED"   # HENTAIGANA LETTER RA-1 → ら


# ---------- 変体仮名の基本変換 ----------


def test_hentaigana_converted():
    """変体仮名が現代ひらがなに変換される"""
    assert normalize_text(HG_A) == "あ"


def test_hentaigana_with_header():
    """ヘッダー行があっても本文の変体仮名は変換される"""
    result = normalize_text(f"# タイトル\n{HG_A}{HG_RA}")
    assert result.startswith("# タイトル")
    assert result.endswith("あら")


def test_no_hentaigana_remains():
    """変換後にBMP外の文字（＝未変換の変体仮名）が残らない"""
    result = normalize_text(f"{HG_A}{HG_KA}{HG_U}{HG_RA}")
    assert all(ord(c) <= 0xFFFF for c in result)


# ---------- パイプライン内での位置の固定 ----------


def test_hentaigana_before_historical_kana():
    """変体仮名変換は歴史的仮名遣い変換より前に置かれている

    KA-1 + U-1 → 「かう」→「こう」。
    歴史的仮名遣い変換より後ろに動かすと「かう」で止まって落ちる。
    """
    assert normalize_text(HG_KA + HG_U) == "こう"


def test_hentaigana_before_jaconv():
    """変体仮名変換は jaconv.normalize より前に置かれている

    変体仮名に濁音の合成済み文字は無く「基字 + U+3099」で表す。
    jaconv より後ろに動かすと濁点が分解のまま残って落ちる。
    """
    result = normalize_text(HG_KA + "゙")
    assert result == "が"
    assert len(result) == 1          # U+304C（合成済み）であること
    assert ord(result) == 0x304C


# ---------- 他の変換段との組み合わせ ----------


def test_mixed_with_old_kanji_and_particle():
    """旧字体・変体仮名・カタカナ助詞が同時に変換される"""
    # 關東（旧字体）+ 変体仮名「あ」+ カタカナ助詞「ノ」
    assert normalize_text(f"關東{HG_A}ノ図") == "関東あの図"


def test_halfwidth_kana_still_normalized():
    """変体仮名を足しても既存の半角カナ→全角の正規化は効いている"""
    assert normalize_text(f"{HG_A}ﾃｽﾄ") == "あテスト"


# ---------- 無害性 ----------


def test_modern_text_unchanged():
    """変体仮名を含まない現代文は変換で壊れない"""
    text = "今日は良い天気です"
    assert normalize_text(text) == text


def test_ocr_misread_correction_still_works():
    """既存のOCR誤読修正が引き続き効いている（回帰）

    漢字の「卜」がカタカナ「ト」に直り、その結果できた助詞「トシテ」が
    さらにひらがな「として」になる（既存の挙動）。
    """
    assert normalize_text("忽然卜シテ") == "忽然として"
    # 誤読修正が効かないと「卜」が残る
    assert "卜" not in normalize_text("コ卜")


# ---------- 読み取れなかったページの目印（G11） ----------

_MARKER = "〔第2頁 読み取り失敗（舊記ヰ号.png）〕"


def test_gap_marker_is_kept_as_is():
    """目印の行は一字も変わらず、前後の本文の旧字体は新字体になる"""
    text = f"陸軍省ノ當分ノ間\n\n{_MARKER}\n\n舊記ノ續キ"
    result = normalize_text(text)
    assert result == f"陸軍省の当分の間\n\n{_MARKER}\n\n旧記の続キ"
    # 守らずに正規化の規則を当てると、カッコが半角に・「.」が「。」に・旧字体が新字体に変わる
    assert _normalize_body(_MARKER) == "〔第2頁 読み取り失敗(旧記イ号。png)〕"


def test_gap_marker_splits_normalization():
    """目印の前後は別々に正規化され、"\\n\\n" でつなぎ直される"""
    a = "陸軍省ノ當分ノ間\n施行スルコトヲ得"
    b = "依テ右囘答ス\nコ卜"
    text = f"{a}\n\n{_MARKER}\n\n{b}"
    assert normalize_text(text) == (
        f"{normalize_text(a)}\n\n{_MARKER}\n\n{normalize_text(b)}"
    )


def test_unprocessed_marker_at_end_is_kept():
    text = "第一條 本文ノ途中\n\n〔第8〜10頁 未処理〕"
    assert normalize_text(text).endswith("\n\n〔第8〜10頁 未処理〕")


def test_index_schema_version_is_not_raised():
    """目印の無い文章の正規化は変わらないので、索引の版は上げない（design D4）"""
    from utils.library_search import INDEX_SCHEMA_VERSION

    assert INDEX_SCHEMA_VERSION == 2

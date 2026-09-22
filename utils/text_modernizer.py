"""
現代語リライトモジュール

戦前文書の文語体テキストを、LLM（Ollama）を使って
現代の口語体に書き換える。

使い方:
    from utils.text_modernizer import TextModernizer

    modernizer = TextModernizer()
    modern_text = modernizer.modernize(old_text)

    # 失敗チャンクの内訳も欲しい場合
    result = modernizer.modernize_detailed(old_text)
    print(result.text, result.failures, result.aborted)
"""

import time
from dataclasses import dataclass, field

from utils.config import CONFIG
from utils.ollama_client import (
    OllamaModelNotFoundError,
    chat_client,
    generate_timeout,
    list_client,
    list_timeout,
    ollama_errors,
)
from utils.progress import progress_active, track

# ---------- 定数 ----------

DEFAULT_TEXT_MODEL = CONFIG.get("models.modernize")

# チャンク分割の設定
DEFAULT_CHUNK_SIZE = CONFIG.get("chunk.size")  # 文字数

# チャンク変換が失敗したときの方針
#   "keep_original": 原文のまま採用して次のチャンクへ進む（既定）
#   "abort":         例外を送出して変換全体を中止する（従来の挙動）
DEFAULT_ON_CHUNK_ERROR = CONFIG.get("chunk.on_error", "keep_original")

SYSTEM_PROMPT = """\
あなたは戦前の日本語を現代の読みやすい日本語に書き直す専門家です。

【方針】
- 文語体・旧仮名遣いをすべて現代の口語体に直す
- 難しい漢語や堅い表現は、意味が同じ平易な言葉に言い換える
- 「だ・である」調で書くが、自然でやわらかい文体にする
- 一文が長すぎる場合は適切に分ける

【制約】
- 固有名詞（人名・地名・流派名等）はそのまま保持する
- 原文の意味を変えない。推測で情報を足さない
- 出力は変換後の文章のみ"""

# Few-shot例（小さいモデルの指示追従を向上させるため）
# 出典: 大日本帝国憲法・教育勅語・歴史叙述文（いずれも公知の歴史的文書）
FEW_SHOT_EXAMPLES = [
    {
        "input": "日本臣民ハ法律ノ定ムル所ニ従ヒ納税ノ義務ヲ有ス。",
        "output": "日本の国民は、法律の定めに従って税金を納める義務がある。",
    },
    {
        "input": "其ノ流祖ハ常陸國ノ人ニシテ、始メ心影流ヲ學ビ、後ニ自ラ一流ヲ開キタリ。"
        "其ノ技倆甚ダ優レタリト雖モ、未ダ以テ足レリトセザリキ。",
        "output": "その流派の創始者は常陸国の出身で、はじめは心影流を学んだが、のちに独自の流派を立ち上げた。"
        "腕前はとても優れていたが、それでもまだ満足しなかった。",
    },
    {
        "input": "朕惟フニ我ガ皇祖皇宗國ヲ肇ムルコト宏遠ニ德ヲ樹ツルコト深厚ナリ。",
        "output": "思うに、皇室の祖先が国を開いたのは遥か昔のことで、その徳はとても深く厚いものだった。",
    },
]


# ---------- 結果の型 ----------


@dataclass
class ChunkFailure:
    """変換に失敗した1チャンクの記録"""

    index: int  # 1始まりのチャンク番号
    message: str


@dataclass
class ModernizeResult:
    """modernize_detailed() の戻り値

    text は「失敗チャンクを原文のまま埋めた」完全な本文。
    LLMが落ちても文字が欠けないことを保証する（G1と同じ思想）。
    """

    text: str
    chunk_total: int
    failures: list[ChunkFailure] = field(default_factory=list)
    aborted: bool = False  # Ctrl+C で途中打ち切りしたか


# ---------- メインクラス ----------


class TextModernizer:
    """
    戦前文語体テキストを現代口語体にリライトする

    使い方:
        modernizer = TextModernizer()
        result = modernizer.modernize(old_text)
        print(result)

        # モデルを変更する場合
        modernizer = TextModernizer(model="qwen3:8b")
    """

    def __init__(
        self,
        model: str = DEFAULT_TEXT_MODEL,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        on_chunk_error: str = DEFAULT_ON_CHUNK_ERROR,
    ):
        self.model = model
        self.chunk_size = chunk_size
        self.on_chunk_error = on_chunk_error

    def modernize(self, text: str) -> str:
        """
        文語体テキストを現代口語体に変換する（後方互換のラッパー）

        変換結果のテキストだけを返す。失敗チャンクの内訳も欲しい場合は
        modernize_detailed() を使う。

        Args:
            text: 変換対象のテキスト

        Returns:
            現代口語体に変換されたテキスト
        """
        return self.modernize_detailed(text).text

    def modernize_detailed(self, text: str) -> ModernizeResult:
        """
        文語体テキストを現代口語体に変換し、失敗の内訳も返す

        ヘッダー行（# で始まる行）はそのまま保持し、本文部分のみをLLMでリライトする。

        1チャンクの変換に失敗しても、そのチャンクは**原文のまま採用して続行**する
        （on_chunk_error="abort" なら従来どおり例外送出）。50チャンク中1個の失敗で
        成功済み49個分のLLM処理を捨てないため。Ctrl+C も同様に、未処理チャンクを
        原文のまま残して打ち切る。

        Args:
            text: 変換対象のテキスト

        Returns:
            ModernizeResult（変換後テキスト・チャンク総数・失敗一覧・中断フラグ）

        Raises:
            OllamaConnectionError / OllamaModelNotFoundError / OllamaTimeoutError:
                事前のモデル存在確認に失敗した場合（1チャンクも変換できないため）
        """
        self._check_model_available()

        # ヘッダーと本文を分離
        header_lines, body = self._separate_header(text)

        if not body.strip():
            return ModernizeResult(text=text, chunk_total=0)

        # 本文をチャンクに分割
        chunks = self._split_text(body)

        # 各チャンクをリライト。進捗が有効ならバー表示、無効なら従来 print。
        # （バーと print の二重表示を避けるため有効時は print を抑制）
        modernized_chunks: list[str] = []
        failures: list[ChunkFailure] = []
        aborted = False
        show_print = not progress_active()
        for i, chunk in enumerate(
            track(chunks, total=len(chunks), description="    口語体変換中")
        ):
            if show_print:
                print(f"    リライト中... ({i + 1}/{len(chunks)})")
            start = time.time()
            try:
                result = self._modernize_chunk(chunk)
            except KeyboardInterrupt:
                # 中断。未処理チャンクは原文のまま残して打ち切る（欠落させない）
                print(f"\n    ⚠ 中断しました（{i + 1}/{len(chunks)} チャンク目）")
                print("      残りは原文のまま残します")
                modernized_chunks.extend(chunks[i:])
                aborted = True
                break
            except Exception as e:
                if self.on_chunk_error == "abort":
                    raise
                # 失敗チャンクは原文のまま採用。文字を消さないことを最優先する
                print(
                    f"    ⚠ チャンク {i + 1}/{len(chunks)} の変換に失敗（原文のまま）: {e}"
                )
                failures.append(ChunkFailure(index=i + 1, message=str(e)))
                result = chunk
            if show_print:
                print(f"    → {time.time() - start:.1f}秒")
            modernized_chunks.append(result)

        # ヘッダーとリライト結果を結合
        modernized_body = "\n".join(modernized_chunks)

        if header_lines:
            modernized = header_lines + "\n\n" + modernized_body
        else:
            modernized = modernized_body

        return ModernizeResult(
            text=modernized,
            chunk_total=len(chunks),
            failures=failures,
            aborted=aborted,
        )

    def _separate_header(self, text: str) -> tuple[str, str]:
        """ヘッダー行（# で始まる行）と本文を分離する"""
        lines = text.split("\n")
        header = []
        body_start = 0

        for i, line in enumerate(lines):
            if line.startswith("#") or line.strip() == "---":
                header.append(line)
                body_start = i + 1
            else:
                break

        header_text = "\n".join(header)
        body_text = "\n".join(lines[body_start:])
        return header_text, body_text

    def _split_text(self, text: str) -> list[str]:
        """
        長文をチャンク分割する

        - chunk_size 以下ならそのまま返す
        - 句点「。」で文に区切る（従来の挙動）
        - 1文が chunk_size を超える場合は _split_oversized でさらに分解し、
          どんな入力でも各断片が必ず chunk_size 以下になることを保証する
          （句読点の乏しい戦前文書で全文が1チャンク化し、超過分が
          無言で切り捨てられて後半が欠落するのを防ぐ = G1修正）
        - 断片を chunk_size を超えない範囲で greedy に結合する
        """
        if len(text) <= self.chunk_size:
            return [text]

        # 句点で文に分割
        raw_sentences = text.split("。")
        sentences = [s + "。" for s in raw_sentences if s.strip()]

        # 上限超えの文をさらに分解し、全断片を chunk_size 以下に揃える
        pieces: list[str] = []
        for sentence in sentences:
            if len(sentence) <= self.chunk_size:
                pieces.append(sentence)
            else:
                pieces.extend(self._split_oversized(sentence))

        # 断片を chunk_size を超えないように greedy に結合
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_length = 0

        for piece in pieces:
            piece_length = len(piece)

            if current_length + piece_length > self.chunk_size and current_chunk:
                # 現在のチャンクを確定
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_length = 0

            current_chunk.append(piece)
            current_length += piece_length

        # 最後のチャンク
        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks

    def _split_oversized(self, sentence: str) -> list[str]:
        """
        chunk_size を超える1文を、読点・改行・最終手段の文字数で分割する

        自然な切れ目を優先し、無ければ機械的に切る:
        1. 「、」「改行」を境界に再分割（区切り文字は手前の断片に残す）
        2. それでも超える断片は chunk_size 文字ごとに強制カット（最終手段）

        返り値の全断片が必ず chunk_size 以下になることを保証する。
        """
        result: list[str] = []
        for part in self._split_keep_delims(sentence, ("、", "\n")):
            if len(part) <= self.chunk_size:
                result.append(part)
                continue

            # 切れ目が作れなかった長文 → 文字数で強制カット。
            # 無言欠落と誤解されないよう注意を出す（既存の進捗表示に合わせ print）
            print(
                f"    ⚠ 句読点のない長文を {self.chunk_size} 文字で強制分割します"
                f"（{len(part)} 文字）"
            )
            for i in range(0, len(part), self.chunk_size):
                result.append(part[i : i + self.chunk_size])

        return result

    @staticmethod
    def _split_keep_delims(text: str, delimiters: tuple[str, ...]) -> list[str]:
        """
        指定の区切り文字で分割し、区切り文字を手前の断片の末尾に残す

        例: _split_keep_delims("あ、い\nう", ("、", "\n")) -> ["あ、", "い\n", "う"]
        区切り文字を含まない文字列はそのまま1件返す。
        """
        pieces: list[str] = []
        current: list[str] = []
        for ch in text:
            current.append(ch)
            if ch in delimiters:
                pieces.append("".join(current))
                current = []
        if current:
            pieces.append("".join(current))
        return pieces

    def _modernize_chunk(self, chunk: str) -> str:
        """1チャンクをOllama APIでリライトする"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})
        messages.append({"role": "user", "content": chunk})

        with ollama_errors(self.model, generate_timeout()):
            response = chat_client().chat(
                model=self.model,
                messages=messages,
                think=False,
                # コピーを渡す（渡した先で書き換えられても設定を汚さない）
                options=dict(CONFIG.get("llm") or {}),
            )

        return response.message.content.strip()

    def _check_model_available(self) -> None:
        """指定モデルがOllamaにインストール済みかチェック"""
        with ollama_errors(self.model, list_timeout()):
            models = list_client().list()
        model_names = [m.model for m in models.models]

        found = any(self.model in name for name in model_names)
        if not found:
            raise OllamaModelNotFoundError(
                f"モデル '{self.model}' が見つかりません。\n"
                f"→ ollama pull {self.model} を実行してください\n"
                f"インストール済み: {', '.join(model_names) or '(なし)'}"
            )

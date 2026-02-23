"""
現代語リライトモジュール

戦前文書の文語体テキストを、LLM（Ollama）を使って
現代の口語体に書き換える。

使い方:
    from utils.text_modernizer import TextModernizer

    modernizer = TextModernizer()
    modern_text = modernizer.modernize(old_text)
"""

import time

from utils.ollama_client import OllamaConnectionError, OllamaModelNotFoundError

# ---------- 定数 ----------

DEFAULT_TEXT_MODEL = "qwen3:14b"

# チャンク分割の設定
DEFAULT_CHUNK_SIZE = 2000  # 文字数
DEFAULT_CHUNK_OVERLAP = 200  # オーバーラップ文字数

MODERNIZATION_PROMPT = """\
あなたは戦前日本語の専門家です。以下のテキストを現代日本語に書き換えてください。

ルール:
1. 文語体 → 口語体に変換する（ニシテ→であり、ナリ→である 等）
2. カタカナ助詞・助動詞 → ひらがなに変換する（ノ→の、ニ→に、ヲ→を 等）
3. 長すぎる文は適切な箇所で分割する
4. 句読点を適切に追加する
5. 原文の意味・内容を正確に保つ（要約や解釈は加えない）
6. 固有名詞（人名・地名・年号）はそのまま保持する

出力は変換後のテキストのみ。説明や注釈は不要。"""


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
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.model = model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def modernize(self, text: str) -> str:
        """
        文語体テキストを現代口語体に変換する

        ヘッダー行（# で始まる行）はそのまま保持し、
        本文部分のみをLLMでリライトする。

        Args:
            text: 変換対象のテキスト

        Returns:
            現代口語体に変換されたテキスト
        """
        self._check_model_available()

        # ヘッダーと本文を分離
        header_lines, body = self._separate_header(text)

        if not body.strip():
            return text

        # 本文をチャンクに分割
        chunks = self._split_text(body)

        # 各チャンクをリライト
        modernized_chunks = []
        for i, chunk in enumerate(chunks):
            print(f"    リライト中... ({i + 1}/{len(chunks)})")
            start = time.time()
            result = self._modernize_chunk(chunk)
            elapsed = time.time() - start
            print(f"    → {elapsed:.1f}秒")
            modernized_chunks.append(result)

        # ヘッダーとリライト結果を結合
        modernized_body = "\n".join(modernized_chunks)

        if header_lines:
            return header_lines + "\n\n" + modernized_body
        return modernized_body

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
        長文を句点「。」を基準にチャンク分割する

        - chunk_size 以下なら分割しない
        - 句点で文を区切り、chunk_size を超えないように文をまとめる
        """
        if len(text) <= self.chunk_size:
            return [text]

        # 句点で文に分割
        raw_sentences = text.split("。")
        sentences = [s + "。" for s in raw_sentences if s.strip()]

        chunks = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > self.chunk_size and current_chunk:
                # 現在のチャンクを確定
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_length

        # 最後のチャンク
        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks

    def _modernize_chunk(self, chunk: str) -> str:
        """1チャンクをOllama APIでリライトする"""
        import ollama

        prompt = MODERNIZATION_PROMPT + "\n\n--- 入力テキスト ---\n" + chunk

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                think=False,
            )
        except ConnectionError:
            raise OllamaConnectionError(
                "Ollamaサーバーに接続できません。\n"
                "→ Ollama.app を起動してください（メニューバーにアイコンが出ます）"
            )
        except ollama.ResponseError as e:
            if "not found" in str(e).lower():
                raise OllamaModelNotFoundError(
                    f"モデル '{self.model}' が見つかりません。\n"
                    f"→ ollama pull {self.model} を実行してください"
                )
            raise

        return response.message.content.strip()

    def _check_model_available(self) -> None:
        """指定モデルがOllamaにインストール済みかチェック"""
        import ollama

        try:
            models = ollama.list()
            model_names = [m.model for m in models.models]
        except ConnectionError:
            raise OllamaConnectionError(
                "Ollamaサーバーに接続できません。\n"
                "→ Ollama.app を起動してください（メニューバーにアイコンが出ます）"
            )

        found = any(self.model in name for name in model_names)
        if not found:
            raise OllamaModelNotFoundError(
                f"モデル '{self.model}' が見つかりません。\n"
                f"→ ollama pull {self.model} を実行してください\n"
                f"インストール済み: {', '.join(model_names) or '(なし)'}"
            )

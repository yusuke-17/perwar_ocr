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

DEFAULT_TEXT_MODEL = "qwen3.5:4b"

# チャンク分割の設定
DEFAULT_CHUNK_SIZE = 2000  # 文字数
DEFAULT_CHUNK_OVERLAP = 200  # オーバーラップ文字数

SYSTEM_PROMPT = """\
あなたは戦前の文語体日本語を現代の口語体に書き換える専門家です。
文語体の表現をすべて口語体に変換してください。固有名詞はそのまま保持してください。
出力は変換後のテキストのみ。説明や注釈は一切不要です。"""

# Few-shot例（小さいモデルの指示追従を向上させるため）
# 出典: 大日本帝国憲法・教育勅語・陸軍省通達（いずれも公知の歴史的文書）
FEW_SHOT_EXAMPLES = [
    {
        "input": "日本臣民ハ法律ノ定ムル所ニ従ヒ納税ノ義務ヲ有ス。"
        "日本臣民ハ法律命令ノ規定ニ従ヒ兵役ノ義務ヲ有ス。",
        "output": "日本臣民は、法律の定めるところに従い、納税の義務を有する。"
        "日本臣民は、法律命令の規定に従い、兵役の義務を有する。",
    },
    {
        "input": "朕惟フニ我ガ皇祖皇宗國ヲ肇ムルコト宏遠ニ德ヲ樹ツルコト深厚ナリ。"
        "我ガ臣民克ク忠ニ克ク孝ニ億兆心ヲ一ニシテ世世厥ノ美ヲ濟セルハ此レ我ガ國體ノ精華ニシテ教育ノ淵源亦實ニ此ニ存ス。",
        "output": "思うに、我が皇祖皇宗が国を始められたことは広大で遠く、徳を立てられたことは深く厚い。"
        "我が臣民がよく忠に、よく孝に、億兆が心を一つにして代々その美風を成し遂げてきたことは、これが我が国体の精華であり、教育の源もまた実にここにある。",
    },
    {
        "input": "軍司令官ハ直チニ命令ヲ下達セリ。各部隊ハ之ニ基キ速ヤカニ行動ヲ開始スベシ。",
        "output": "軍司令官はただちに命令を伝達した。各部隊はこれに基づき、速やかに行動を開始すべきである。",
    },
]


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

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for example in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})
        messages.append({"role": "user", "content": chunk})

        try:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                think=False,
                options={
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 20,
                    "presence_penalty": 1.5,
                },
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

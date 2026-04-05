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

DEFAULT_TEXT_MODEL = "qwen3.5:9b"

# チャンク分割の設定
DEFAULT_CHUNK_SIZE = 2000  # 文字数
DEFAULT_CHUNK_OVERLAP = 200  # オーバーラップ文字数

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
                    "temperature": 0.5,
                    "top_p": 0.9,
                    "top_k": 40,
                    "repeat_penalty": 1.1,
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

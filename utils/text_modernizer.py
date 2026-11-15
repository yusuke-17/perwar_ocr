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
from utils.page_join import split_by_gap_markers
from utils.progress import progress_active, track

# ---------- 定数 ----------

DEFAULT_TEXT_MODEL = CONFIG.get("models.modernize")

# チャンク分割の設定
DEFAULT_CHUNK_SIZE = CONFIG.get("chunk.size")  # 文字数

# チャンク変換が失敗したときの方針
#   "keep_original": 原文のまま採用して次のチャンクへ進む（既定）
#   "abort":         例外を送出して変換全体を中止する（従来の挙動）
DEFAULT_ON_CHUNK_ERROR = CONFIG.get("chunk.on_error", "keep_original")

# 結果に few-shot のお手本が混入したとき、お手本なしで変換し直すか（G14）
DEFAULT_RETRY_WITHOUT_EXAMPLES = CONFIG.get("chunk.retry_without_examples", True)

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


@dataclass(frozen=True)
class LeakMarker:
    """お手本の混入を見分ける目印の組（G14）

    LLM がお手本まで本文と取り違えると、お手本の入力を訳し直した文が
    結果に混ざる（一字一句同じではないので、完全一致では見つからない）。
    そこで「原文に無いのに、お手本由来の語が出た」ことで混入とみなす。

    output_terms: 変換結果に**すべて**含まれたら、お手本を訳し直した疑いがある
    source_terms: 原文に**どれか 1 つでも**あれば本物の引用とみなし、混入としない
    """

    output_terms: tuple[str, ...]
    source_terms: tuple[str, ...]


# Few-shot例（小さいモデルの指示追従を向上させるため）
# 出典: 大日本帝国憲法・教育勅語・歴史叙述文（いずれも公知の歴史的文書）
# leak_markers はお手本の混入を見分ける目印（G14）。プロンプトには使わない。
# お手本の文面を変えたら目印も見直すこと（付け忘れはテストで落ちる）。
FEW_SHOT_EXAMPLES = [
    {
        "input": "日本臣民ハ法律ノ定ムル所ニ従ヒ納税ノ義務ヲ有ス。",
        "output": "日本の国民は、法律の定めに従って税金を納める義務がある。",
        # 固有名詞が無いので、弱い言い回し 2 つがそろったときだけ混入とみなす。
        # 片方だけだと租税を扱う公文書の正しい訳を誤判定してしまう。
        # 原文に「税」が 1 字でもあれば（租税・納税・稅 など）本物の訳とみなす
        "leak_markers": [
            LeakMarker(
                output_terms=("日本の国民は", "税金を納める義務"),
                source_terms=("臣民", "税", "稅"),
            ),
        ],
    },
    {
        "input": "其ノ流祖ハ常陸國ノ人ニシテ、始メ心影流ヲ學ビ、後ニ自ラ一流ヲ開キタリ。"
        "其ノ技倆甚ダ優レタリト雖モ、未ダ以テ足レリトセザリキ。",
        "output": "その流派の創始者は常陸国の出身で、はじめは心影流を学んだが、のちに独自の流派を立ち上げた。"
        "腕前はとても優れていたが、それでもまだ満足しなかった。",
        "leak_markers": [
            LeakMarker(output_terms=("常陸",), source_terms=("常陸",)),
            LeakMarker(output_terms=("心影流",), source_terms=("心影流",)),
        ],
    },
    {
        "input": "朕惟フニ我ガ皇祖皇宗國ヲ肇ムルコト宏遠ニ德ヲ樹ツルコト深厚ナリ。",
        "output": "思うに、皇室の祖先が国を開いたのは遥か昔のことで、その徳はとても深く厚いものだった。",
        "leak_markers": [
            # 「皇室の祖先」は皇宗・祖宗・列聖などの訳にもなるので、どれかがあれば本物の訳とみなす
            LeakMarker(
                output_terms=("皇室の祖先",),
                source_terms=("皇祖", "皇宗", "祖宗", "列聖", "皇考"),
            ),
        ],
    },
]


def find_few_shot_leak(source: str, result: str) -> LeakMarker | None:
    """変換結果にお手本が混入していれば、判定に使った目印の組を返す（G14）

    どれかの組で「出力側の語がすべて結果にあり、原文側の語が 1 つも原文に無い」とき混入。
    原文が憲法や勅語を実際に引用している場合は原文側の語があるので見逃す。

    Args:
        source: LLM に渡したチャンクの原文
        result: そのチャンクの変換結果

    Returns:
        混入と判定した目印の組。混入が無ければ None
    """
    for example in FEW_SHOT_EXAMPLES:
        for marker in example["leak_markers"]:
            if all(t in result for t in marker.output_terms) and not any(
                t in source for t in marker.source_terms
            ):
                return marker
    return None


# ---------- 例外 ----------


class FewShotLeakError(Exception):
    """お手本の混入を見つけ、お手本なしで変換し直さない設定のときの例外（G14）

    modernize_detailed がほかの失敗と同じく受け止め、そのチャンクを原文のまま残す。
    """


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
        retry_without_examples: bool = DEFAULT_RETRY_WITHOUT_EXAMPLES,
    ):
        self.model = model
        self.chunk_size = chunk_size
        self.on_chunk_error = on_chunk_error
        self.retry_without_examples = bool(retry_without_examples)

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

        # 本文を読み取れなかったページの目印で区切り、区間ごとにチャンクに分割する。
        # 目印は LLM に渡さず、目印の前後の本文が同じチャンクに入らないようにする（G11）
        segments = split_by_gap_markers(body)
        segment_chunks = [
            None if is_marker else self._split_text(segment)
            for is_marker, segment in segments
        ]
        chunks = [c for cs in segment_chunks if cs for c in cs]

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

        # 区間ごとにリライト結果をつなぎ、目印は元の位置にそのまま戻す
        modernized_body = self._assemble(segments, segment_chunks, modernized_chunks)

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

    @staticmethod
    def _assemble(
        segments: list[tuple[bool, str]],
        segment_chunks: list[list[str] | None],
        modernized_chunks: list[str],
    ) -> str:
        """区間ごとのリライト結果と目印を元の並びに組み立てる

        区間の中のチャンクは従来どおり改行1つ、区間と目印の間は空行でつなぐ。
        目印が無ければ、全チャンクを改行1つでつないだ従来の結果と同じになる。
        """
        results = iter(modernized_chunks)
        parts: list[str] = []
        for (is_marker, segment), chunks in zip(segments, segment_chunks):
            if is_marker or chunks is None:
                parts.append(segment)
            else:
                parts.append("\n".join(next(results) for _ in chunks))
        return "\n\n".join(parts)

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
        - 句点「。」で文に区切る。「。」は手前の文に残し、原文に無い字は足さない
          （全チャンクを "".join すると分割前の text と一字も違わない）
        - 1文が chunk_size を超える場合は _split_oversized でさらに分解し、
          どんな入力でも各断片が必ず chunk_size 以下になることを保証する
          （句読点の乏しい戦前文書で全文が1チャンク化し、超過分が
          無言で切り捨てられて後半が欠落するのを防ぐ = G1修正）
        - 断片を chunk_size を超えない範囲で greedy に結合する
        """
        if len(text) <= self.chunk_size:
            return [text]

        # 句点で文に分割。「。」は手前の文の末尾に残し、原文に無い「。」は足さない
        # （「。」で終わらない最後の文に句点を付けていたバグの修正 = B3）。
        # 空白だけの断片も捨てずに前後と一緒に詰めるので、チャンクをつなぐと原文に戻る
        sentences = self._split_keep_delims(text, ("。",))

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
        """1チャンクをOllama APIでリライトする

        まずお手本つきで変換する。結果に few-shot のお手本が混入していたら、
        お手本を外して 1 回だけ変換し直し、その結果を判定せずに採用する（G14）。
        - 話題がお手本と重なる資料では、お手本つきのままだと何度やっても混入する
        - お手本を渡さなければ混入は起きようがない。そこで判定に掛かるのは誤判定
          （引用がチャンクの境目で切れた場合など）だけなので、正しい訳を捨てない
        retry_without_examples が False なら FewShotLeakError を投げ、呼び出し元の
        失敗処理（原文のまま残す / abort なら中止）に任せる。
        """
        result = self._chat(self._build_messages(chunk))
        marker = find_few_shot_leak(chunk, result)
        if marker is None:
            return result
        terms = "・".join(marker.output_terms)
        if not self.retry_without_examples:
            raise FewShotLeakError(f"お手本の例文が混入しました（{terms}）")
        print(f"    ⚠ お手本の例文の混入を検出（{terms}）。お手本なしで変換し直します")
        return self._chat(self._build_messages(chunk, with_examples=False))

    @staticmethod
    def _build_messages(chunk: str, with_examples: bool = True) -> list[dict[str, str]]:
        """LLM に渡すメッセージ（指示・few-shot の例・チャンク）を組み立てる

        with_examples=False ならお手本を入れない（お手本が混入したときの変換し直し用。G14）
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for example in FEW_SHOT_EXAMPLES if with_examples else ():
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})
        messages.append({"role": "user", "content": chunk})
        return messages

    def _chat(self, messages: list[dict[str, str]]) -> str:
        """Ollama にメッセージを送り、応答の本文を返す"""
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

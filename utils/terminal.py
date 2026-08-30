"""ターミナル出力の共通処理

「色を付けてよいか」の判定は diff 表示・検索結果表示のどちらにも要る。
同じ4条件判定をコピーで増やさないよう、ANSIコードと一緒にここへ集約する。

`utils/progress.py` は統合していない。あちらは `progress.enabled` という別の
設定キーを見ており、「rich を使うか」という別の関心事を持つため、
無理に1本化すると条件が絡まる。

使い方:
    from utils.terminal import BOLD, RESET, should_use_color

    if should_use_color(args.no_color, "search.color"):
        print(f"{BOLD}強調{RESET}")
"""

import os
import sys

from utils.config import CONFIG

# ---------- ANSIエスケープ ----------
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# 検索結果の一致箇所に使う色（黄色＋太字。赤緑は diff の削除/追加に予約済み）
MATCH = YELLOW + BOLD


def should_use_color(no_color_flag: bool = False, config_key: str = "") -> bool:
    """色付けしてよいかを判定する。

    次のいずれかが無効を示すなら色を付けない:
      1. --no-color の明示
      2. NO_COLOR 環境変数（https://no-color.org/ の慣行）
      3. 設定（config_key が空なら見ない）
      4. 出力先が端末でない（パイプ・リダイレクト）

    設定より前に環境変数を見るのは、NO_COLOR が「その場限りの上書き」として
    使われる慣行に合わせるため。
    """
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if config_key and not CONFIG.get(config_key, True):
        return False
    return sys.stdout.isatty()

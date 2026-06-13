"""
設定の一元管理モジュール

設定値の「デフォルトの正解」はこのファイルの ``_DEFAULTS`` に1か所だけ置く。
プロジェクト直下の ``config.toml`` には「デフォルトから変えたい値だけ」を書けばよく、
起動時に「デフォルト ← config.toml」の順で deep merge される。

そのため config.toml は:
- 無くても動く（全部デフォルトが使われる）
- 書いた行だけが効く（消せばデフォルトに戻る）
- 設定が増えてもファイルは膨らまない

使い方:
    from utils.config import CONFIG

    model = CONFIG.get("models.modernize")   # "qwen3.5:9b"
    opts = CONFIG.get("llm")                  # {"temperature": 0.5, ...}

Python 3.11+ 標準の tomllib を使うため、追加依存はゼロ。
"""

import tomllib
from pathlib import Path
from typing import Any

# ---------- 設定のデフォルト値（単一の真実） ----------
# config.toml で上書きできるキーの一覧でもある。

_DEFAULTS: dict[str, Any] = {
    "models": {"ocr": "glm-ocr", "modernize": "qwen3.5:9b"},
    "paths": {"input": "input", "output": "output", "library": "library"},
    "chunk": {"size": 2000, "overlap": 200},
    "llm": {"temperature": 0.5, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1},
    "search": {"limit": 20, "min_query_chars": 3},
    "diff": {"color": True, "context": 30},
}

# プロジェクトルート（utils/ の親）。config.toml はここに置く。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"


class ConfigError(Exception):
    """config.toml の読み込み・解析に失敗したときの例外。"""


def _deep_merge(base: dict, override: dict) -> dict:
    """base に override を再帰的に重ねた新しい dict を返す。

    どちらの値も dict のキーは中身を再帰マージし、それ以外は override で上書きする。
    base 側は破壊しない（コピーを返す）。
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_toml(path: Path) -> dict:
    """config.toml を読み込む。無ければ空 dict。壊れていれば ConfigError。"""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"設定ファイルの書式が不正です: {path}\n"
            f"→ {e}\n"
            "TOMLの書き方を確認してください（例: key = \"値\"）。"
        ) from e


class Config:
    """deep merge 済みの設定をドット記法で読み出すラッパー。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """``"models.modernize"`` のようなドット区切りキーで値を取り出す。

        セクション名だけ（例: ``"llm"``）を渡すとそのセクション dict を返す。
        存在しないキーは default（未指定なら None）を返す。
        """
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config() -> Config:
    """_DEFAULTS に config.toml を重ねた Config を生成する。"""
    overrides = _load_toml(CONFIG_PATH)
    return Config(_deep_merge(_DEFAULTS, overrides))


# モジュールレベルのシングルトン（import 時に一度だけ読み込む）。
CONFIG = load_config()
